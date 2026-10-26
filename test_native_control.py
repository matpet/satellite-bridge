import threading
import time
import unittest

from bridge_app import radio_readout
from rumlog_panel import RumlogPanel, NativePowerControl, band_fields, frequency_hz, ON, OFF


class PanelElement:
    def __init__(self, children=(), **attributes):
        self.children = list(children)
        self.attributes = attributes

    def get(self, name, default=None):
        return self.attributes.get(name, default)

    def attrs(self, *names):
        return {name: self.get(name) for name in names}


class NativeReadbackTests(unittest.TestCase):
    def placeholder_panel(self, selected="Main", mode="USB", data=ON):
        def button(title, state):
            return PanelElement(AXRole="AXButton", AXTitle=title, AXDescription=state)
        panel = RumlogPanel()
        panel._groups = {
            "VFO Main Band (RX)": PanelElement(children=[
                PanelElement(AXRole="AXStaticText", AXValue=v)
                for v in ("433,540.000", "Data", "Mode", "FIL 1")]),
            "VFO": PanelElement(children=[button(b, ON if b == selected else OFF) for b in ("Main", "Sub")]),
            "Mode": PanelElement(children=[button(mode, ON), button("Data", data), button("Fi. 1", ON)]),
        }
        return panel

    def test_frequency_fields_keep_whole_hertz_and_reject_missing_or_other_rig_data(self):
        self.assertEqual(frequency_hz("433,532.350"), 433532350)
        self.assertEqual(frequency_hz("144,032.350"), 144032350)
        for text in ("No Data", "", "0", "NaN", "28,442.9", "433,532.3501"):
            self.assertIsNone(frequency_hz(text), text)

    def test_mode_and_filter_readback(self):
        self.assertEqual(band_fields(["433,540.000", "Data", "USB", "FIL 1"]), {"hz":433540000, "mode":"USB-D", "filter":1})
        self.assertEqual(band_fields(["433,512.000", "", "CWR", "FIL 2"])["mode"], "CW-R")

    def test_compact_tx_readback_without_a_data_field(self):
        self.assertEqual(band_fields(["144,040.000", "USB", "FIL 1", "", "VFO Sub (TX)"]),
                         {"hz":144040000, "mode":"USB", "filter":1})

    def test_placeholder_mode_is_not_reported_as_a_radio_mode(self):
        self.assertEqual(band_fields(["433,540.000", "Data", "Mode", "FIL 1", "VFO Main (RX)"]),
                         {"hz":433540000, "mode":None, "filter":1})

    def test_placeholder_uses_live_mode_buttons_for_selected_rx_only(self):
        panel = self.placeholder_panel()
        self.assertEqual(panel.read_band("VFO Main Band (RX)", "Main")["mode"], "USB-D")
        self.assertIsNone(self.placeholder_panel(selected="Sub").read_band("VFO Main Band (RX)", "Main")["mode"])

    def test_selected_mode_preserves_data_off_and_reverse_modes(self):
        self.assertEqual(self.placeholder_panel(data=OFF).selected_mode("Main"), "USB")
        self.assertEqual(self.placeholder_panel(mode="CW R").selected_mode("Main"), "CW-R")
        self.assertEqual(self.placeholder_panel(mode="RY R").selected_mode("Main"), "RTTY-R")

    def test_ambiguous_mode_or_vfo_indicators_are_not_feedback(self):
        panel = self.placeholder_panel()
        panel._groups["Mode"].children.append(PanelElement(AXRole="AXButton", AXTitle="LSB", AXDescription=ON))
        self.assertIsNone(panel.selected_mode("Main"))
        panel = self.placeholder_panel()
        panel._groups["VFO"].children[1].attributes["AXDescription"] = ON
        self.assertIsNone(panel.selected_mode("Main"))
        self.assertIsNone(self.placeholder_panel(data="partially available").selected_mode("Main"))

    def test_placeholder_with_verified_mode_and_filter_needs_no_filter_click(self):
        panel = self.placeholder_panel()
        self.assertEqual(panel.select_filter("USB-D", 1), 1)

    def test_fields_are_identified_by_content_when_layout_changes(self):
        self.assertEqual(band_fields(["VFO Main (RX)", "FIL 2", "144,012.000", "CW-R"]),
                         {"hz":144012000, "mode":"CW-R", "filter":2})
        self.assertEqual(band_fields(["FIL 3", "DATA-L", "433,540.000"]),
                         {"hz":433540000, "mode":"LSB-D", "filter":3})

    def test_both_rumlog_vfo_group_names_keep_rx_and_tx_separate(self):
        for rx_name, tx_name in (("VFO Main Band (RX)", "VFO Sub Band (TX)"),
                                 ("VFO Main (RX)", "VFO Sub (TX)")):
            with self.subTest(rx=rx_name, tx=tx_name):
                rx = PanelElement(AXTitleUIElement=PanelElement(AXValue=rx_name))
                tx = PanelElement(AXTitleUIElement=PanelElement(AXValue=tx_name))
                panel = RumlogPanel()
                panel._window = PanelElement(children=[tx, rx])
                self.assertIs(panel.group("VFO Main Band (RX)"), rx)
                self.assertIs(panel.group("VFO Sub Band (TX)"), tx)

    def test_missing_rx_group_cannot_fall_back_to_tx(self):
        panel = RumlogPanel()
        panel._window = PanelElement(children=[PanelElement(
            AXTitleUIElement=PanelElement(AXValue="VFO Sub (TX)"))])
        with self.assertRaisesRegex(RuntimeError, "VFO Main Band"):
            panel.group("VFO Main Band (RX)")

    def test_all_band_fields_are_read_after_a_panel_refresh(self):
        controls = [PanelElement(AXRole="AXStaticText", AXValue=value) for value in
                    ("VFO Sub (TX)", "", "FIL 1", "144,040.000", "USB")]
        group = PanelElement(children=controls, AXTitleUIElement=PanelElement(AXValue="VFO Sub (TX)"))
        panel = RumlogPanel()
        panel._window = PanelElement(children=[group])
        self.assertEqual(band_fields(panel.fields("VFO Sub Band (TX)")),
                         {"hz":144040000, "mode":"USB", "filter":1})
        controls[-1].attributes["AXValue"] = "CW"
        self.assertEqual(band_fields(panel.fields("VFO Sub Band (TX)"))["mode"], "CW")

    def test_operations_show_manual_radio_frequency_instead_of_commanded_preset(self):
        text, fresh = radio_readout({"radio":{"rx_hz":433532350,"tx_hz":144032350,"rx_mode":"CW","tx_mode":None},"radio_age":.2,"last_sent":{"rx_mhz":"433.512000"}})
        self.assertTrue(fresh)
        self.assertIn("433.532350", text)
        self.assertIn("144.032350", text)
        self.assertNotIn("433.512000", text)
        self.assertNotIn("None", text)

    def test_missing_or_stale_feedback_is_not_presented_as_a_live_requested_value(self):
        text, fresh = radio_readout({"last_sent":{"rx_mhz":"433.540000"}})
        self.assertFalse(fresh)
        self.assertIn("waiting", text)
        self.assertNotIn("433.540000", text)
        partial, fresh = radio_readout({"radio":{"rx_hz":433540000,"tx_hz":None},"radio_age":.1})
        self.assertFalse(fresh)
        self.assertIn("TX waiting", partial)
        self.assertNotIn("stale", partial)
        text, fresh = radio_readout({"radio":{"rx_hz":433532350,"tx_hz":None},"radio_age":5})
        self.assertFalse(fresh)
        self.assertIn("stale", text)
        self.assertIn("waiting", text)


class FakePowerPanel:
    def __init__(self, percent=4, cap_works=True):
        self.lock = threading.RLock()
        self.percent, self.cap_works = percent, cap_works
        self.writes = []
        self.reads = 0

    def snapshot(self, require_power=False):
        self.reads += 1
        return {"power_percent":self.percent,"rx_hz":433540000,"tx_hz":144040000,"monotonic_at":time.monotonic()}

    def set_power_ceiling(self):
        self.writes.append(5)
        if self.cap_works:
            self.percent = 4

    def read_power(self):
        return self.percent

    def wait(self, predicate, label, timeout=3):
        if not predicate():
            raise RuntimeError(label)


class NativePowerTests(unittest.TestCase):
    def test_ordinary_monitor_leaves_verified_safe_power_alone(self):
        panel = FakePowerPanel()
        control = NativePowerControl(panel)
        self.assertEqual(control.limit(), 4)
        self.assertEqual(control.limit(), 4)
        self.assertEqual(panel.writes, [])
        self.assertEqual(panel.reads, 2)

    def test_preset_boundary_forces_the_ceiling_even_if_old_band_was_safe(self):
        panel = FakePowerPanel()
        self.assertEqual(NativePowerControl(panel).limit(force=True),4)
        self.assertEqual(panel.writes,[5])

    def test_above_ceiling_power_is_lowered_and_verified(self):
        panel = FakePowerPanel(80)
        self.assertEqual(NativePowerControl(panel).limit(), 4)
        self.assertEqual(panel.writes, [5])
        self.assertGreaterEqual(panel.reads, 2)

    def test_failed_power_reduction_cannot_be_reported_as_verified(self):
        panel = FakePowerPanel(80, cap_works=False)
        control = NativePowerControl(panel)
        with self.assertRaises(RuntimeError):
            control.limit()
        self.assertIsNone(control.last_feedback)

    def test_radio_display_reuses_the_fresh_power_poll(self):
        panel = FakePowerPanel()
        control = NativePowerControl(panel)
        control.limit()
        self.assertEqual(control.feedback()["rx_hz"],433540000)
        self.assertEqual(panel.reads,1)


class FilterPanelModel(RumlogPanel):
    def __init__(self):
        super().__init__()
        self.band = "Sub"
        self.filters = {"Main":1,"Sub":1}
        self.toggling = False
        self.rx_mode = "CW"
        self.presses = []

    def fields(self, group):
        return ["433,540.000","",self.rx_mode,f"FIL {self.filters['Main']}"]

    def description(self, group, name):
        if group == "Miscellaneous":
            return ON if self.toggling else OFF
        if group == "VFO":
            return ON if self.band == name else OFF
        if group == "Mode" and name.startswith("Fi. "):
            return ON if self.filters[self.band] == int(name[-1]) else OFF
        raise AssertionError((group,name))

    def press(self, group, name):
        self.presses.append((group,name))
        if group == "VFO":
            self.band = name
        elif group == "Miscellaneous":
            self.toggling = not self.toggling
        elif group == "Mode":
            self.filters[self.band] = int(name[-1])

    def wait(self, predicate, label, timeout=3):
        if not predicate():
            raise RuntimeError(label)


class NativeFilterTests(unittest.TestCase):
    def test_rx_filter_changes_main_only_and_restores_sub_view(self):
        panel = FilterPanelModel()
        self.assertEqual(panel.select_filter("CW",2),2)
        self.assertEqual(panel.filters,{"Main":2,"Sub":1})
        self.assertEqual(panel.band,"Sub")

    def test_already_correct_rx_filter_needs_no_controls_changed(self):
        panel = FilterPanelModel()
        panel.filters["Main"] = 2
        self.assertEqual(panel.select_filter("CW",2),2)
        self.assertEqual(panel.presses,[])
        self.assertEqual(panel.band,"Sub")

    def test_mode_not_ready_cannot_change_tx_filter(self):
        panel = FilterPanelModel()
        with self.assertRaises(RuntimeError):
            panel.select_filter("USB-D",1)
        self.assertEqual(panel.filters,{"Main":1,"Sub":1})
        self.assertEqual(panel.band,"Sub")

    def test_alternating_polling_is_restored_after_filter_change(self):
        panel = FilterPanelModel()
        panel.toggling = True
        panel.select_filter("CW",2)
        self.assertTrue(panel.toggling)
        self.assertEqual(panel.filters["Sub"],1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
