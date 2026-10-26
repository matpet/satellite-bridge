"""Regressions for QO-100 / Mode B band reversals through RUMlogNG."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bridge_app import App
from bridge_core import Bridge, Pair, dial_band
from rumlog_panel import RumlogPanel
from test_bridge import FakeTransport, eventually, packet
from test_native_control import PanelElement, SatellitePanelModel


QO = Pair.from_values("433.512", "144.012", "CW", "CW")
AO7 = Pair.from_values("145.967560", "432.128150", "CW", "CW", 0, 0)


class BandCollisionPanel(SatellitePanelModel):
    """Reject a setter into the band occupied by the other VFO."""

    def __init__(self):
        super().__init__()
        self.power = 4
        self.power_limits = []
        self.exchange_works = True

    def press(self, group, name):
        if (group, name) == ("VFO", "M / S"):
            self.presses.append((group, name))
            if self.exchange_works:
                for values in (self.frequencies, self.modes, self.tones):
                    values["Main"], values["Sub"] = values["Sub"], values["Main"]
                self.power = 90  # The newly selected TX band recalls power.
        else:
            super().press(group, name)

    def set_frequency(self, hz):
        other = "Sub" if self.band == "Main" else "Main"
        if dial_band(hz) == dial_band(self.frequencies[other]):
            return  # The radio refuses a same-band collision.
        if dial_band(hz) != dial_band(self.frequencies[self.band]):
            self.modes[self.band] = "FM"  # Recall a different band mode.
        super().set_frequency(hz)

    def read_power(self):
        return self.power

    def set_power_ceiling(self):
        self.power_limits.append(self.power)
        self.power = 4


class BandTransitionTests(unittest.TestCase):
    def apply(self, panel, pair, previous=None, source=None):
        with patch("rumlog_panel.time.sleep"):
            return panel.apply_satellite_pair(
                pair, previous, panel.set_frequency, lambda: None,
                lambda *args, **kwargs: None, rx_profile=source)

    def test_ao7_reversal_exchanges_bands_before_either_frequency(self):
        panel = BandCollisionPanel()
        panel.set_frequency(AO7.rx_hz)
        self.assertEqual(panel.frequency_writes, [])
        result = self.apply(panel, AO7)
        self.assertEqual(panel.frequencies, {"Main": AO7.rx_hz, "Sub": AO7.tx_hz})
        self.assertEqual(panel.modes, {"Main": "CW", "Sub": "CW"})
        self.assertEqual(panel.presses.count(("VFO", "M / S")), 1)
        self.assertEqual(result["tx_mode"], "CW")

    def test_return_to_qo_exchanges_back_and_holds_recalled_power(self):
        panel = BandCollisionPanel()
        self.apply(panel, AO7, source="macdoppler")
        panel.power = 80
        self.apply(panel, QO, AO7, source="qo100")
        self.assertEqual(panel.frequencies, {"Main": QO.rx_hz, "Sub": QO.tx_hz})
        self.assertEqual(panel.presses.count(("VFO", "M / S")), 2)
        self.assertEqual(panel.power_limits, [90, 90])
        self.assertLessEqual(panel.power, 5)

    def test_frequency_only_updates_do_not_repeat_band_exchange(self):
        panel = BandCollisionPanel()
        self.apply(panel, AO7)
        panel.power = 63
        target = Pair.from_values("145.967550", "432.128180", "CW", "CW", 0, 0)
        self.apply(panel, target, AO7, source="macdoppler")
        self.assertEqual(panel.presses.count(("VFO", "M / S")), 1)
        self.assertEqual(panel.power, 63)

    def test_unconfirmed_exchange_has_no_frequency_retry_or_second_exchange(self):
        panel = BandCollisionPanel()
        panel.exchange_works = False
        with self.assertRaisesRegex(RuntimeError, "band after Main/Sub exchange"):
            self.apply(panel, AO7)
        self.assertEqual(panel.frequency_writes, [])
        self.assertEqual(panel.presses.count(("VFO", "M / S")), 1)
        self.assertEqual(panel.band, "Main")

    def test_ptt_blocks_the_exchange_before_any_mutation(self):
        panel = BandCollisionPanel()
        def transmitting():
            raise RuntimeError("PTT active")
        with self.assertRaisesRegex(RuntimeError, "PTT active"):
            panel.prepare_satellite_bands(AO7, transmitting, lambda *a, **k: None)
        self.assertEqual(panel.presses, [])
        self.assertEqual(panel.frequency_writes, [])

    def test_missing_sub_readback_is_refreshed_before_planning_exchange(self):
        panel = BandCollisionPanel()
        original = panel.fields
        def fields(group):
            if "Sub" in group and ("VFO", "Sub") not in panel.presses:
                return []
            return original(group)
        panel.fields = fields
        self.apply(panel, AO7)
        self.assertEqual(panel.frequencies, {"Main": AO7.rx_hz, "Sub": AO7.tx_hz})

    def test_same_layout_never_exchanges_bands(self):
        panel = BandCollisionPanel()
        self.apply(panel, QO)
        self.assertNotIn(("VFO", "M / S"), panel.presses)

    def test_changed_band_reapplies_same_requested_mode_after_memory_recall(self):
        panel = BandCollisionPanel()
        previous = Pair.from_values("433.540", "144.040", "USB-D", "USB-D")
        target = Pair.from_values("433.540", "1268.1", "USB-D", "USB-D")
        self.apply(panel, target, previous)
        self.assertEqual(panel.modes["Sub"], "USB-D")

    def test_rx_collision_with_third_band_target_also_frees_main(self):
        panel = BandCollisionPanel()
        target = Pair.from_values("145.960", "1268.1", "USB", "USB")
        self.apply(panel, target)
        self.assertEqual(panel.frequencies, {"Main": target.rx_hz, "Sub": target.tx_hz})

    def test_macdoppler_default_follows_complete_target_and_low_transition(self):
        app = App.__new__(App)
        app.radio_panel = panel = BandCollisionPanel()
        app.bridge = SimpleNamespace(source="macdoppler")
        defaults = []
        def default(percent, check_rx):
            check_rx()
            self.assertEqual(panel.frequencies, {"Main": AO7.rx_hz, "Sub": AO7.tx_hz})
            self.assertEqual(panel.modes, {"Main": "CW", "Sub": "CW"})
            self.assertLessEqual(panel.power, 5)
            defaults.append(percent)
            panel.power = percent
        app.power_control = SimpleNamespace(set_default=default)
        transport = app.transport(lambda *a, **k: None)
        def command(name, params="", reply=None):
            if name == "CmdSendTx":
                return "OFF"
            self.assertEqual(name, "CmdSetFreq")
            panel.set_frequency(int(float(params.split(">", 1)[1]) * 1000))
        transport.command = command
        with patch("rumlog_panel.time.sleep"):
            transport.apply(AO7, force=True)
        self.assertEqual(defaults, [80])
        self.assertEqual(panel.power_limits, [90])
        self.assertEqual(panel.power, 80)

    def test_replaced_readout_elements_are_read_fresh(self):
        panel = RumlogPanel()
        group = PanelElement(children=[PanelElement(AXRole="AXStaticText", AXValue="144,012.000")])
        panel._groups["VFO Sub Band (TX)"] = group
        self.assertEqual(panel.fields("VFO Sub Band (TX)"), ["144,012.000"])
        group.children = [PanelElement(AXRole="AXStaticText", AXValue="432,128.150")]
        self.assertEqual(panel.fields("VFO Sub Band (TX)"), ["432,128.150"])

    def test_continuous_updates_restore_original_view_only_on_release(self):
        panel = BandCollisionPanel()
        with patch("rumlog_panel.time.sleep"):
            panel.apply_satellite_pair(AO7, None, panel.set_frequency, lambda: None,
                                       lambda *a, **k: None, continuous=True)
        self.assertEqual(panel.band, "Sub")
        self.assertEqual(panel._view_before_tracking, "Main")
        panel.release_tracking_polling()
        self.assertEqual(panel.band, "Main")
        self.assertIsNone(panel._view_before_tracking)
        self.assertTrue(panel.toggling)

    def test_frequency_updates_reuse_verified_filter_until_reported_change(self):
        selected = []
        bridge = Bridge(transport_factory=FakeTransport,
                        rx_filter=lambda mode, n: selected.append((mode, n)) or n)
        bridge.start(port=0)
        try:
            bridge.follow_macdoppler()
            for count in range(1, 4):
                bridge.ingest(packet(f"{145.96 + count / 1000:.6f}", "432.13", "CW", "CW"))
                eventually(lambda: bridge.applied == count)
            self.assertEqual(selected, [("CW", 2)])
            with bridge.lock:
                bridge.radio = {"rx_filter": 1}
            bridge.ingest(packet("145.964", "432.13", "CW", "CW"))
            eventually(lambda: bridge.applied == 4)
            self.assertEqual(selected, [("CW", 2), ("CW", 2)])
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
