import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bridge_app import App, radio_readout
from bridge_core import Pair
from rumlog_panel import RumlogPanel, NativePowerControl, band_fields, frequency_hz, ON, OFF
import macos_ax


class PanelElement:
    def __init__(self, children=(), **attributes):
        self.children = list(children)
        self.attributes = attributes

    def get(self, name, default=None):
        return self.attributes.get(name, default)

    def attrs(self, *names):
        return {name: self.get(name) for name in names}


class NativeReadbackTests(unittest.TestCase):
    def test_locked_session_holds_before_window_lookup_or_menu_actions(self):
        with patch('macos_ax.session_locked',return_value=True),patch('macos_ax.subprocess.run') as lookup:
            with self.assertRaisesRegex(RuntimeError,'Unlock the Mac'):
                macos_ax.application()
            lookup.assert_not_called()

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

    def power_slider(self):
        def set_number(percent):
            self.writes.append(percent)
            if self.cap_works:
                self.percent=max(0,percent-1)
        return SimpleNamespace(set_number=set_number)

    def wait(self, predicate, label, timeout=3):
        if not predicate():
            raise RuntimeError(label)


class NativePowerTests(unittest.TestCase):
    def test_macdoppler_default_80_accepts_radio_quantization_and_is_not_a_monitor(self):
        panel=FakePowerPanel(4)
        power=NativePowerControl(panel)
        with patch('rumlog_panel.time.sleep'):
            self.assertEqual(power.set_default(80),79)
        self.assertEqual(panel.writes,[80])
        panel.percent=35
        self.assertEqual(power.feedback()['power_percent'],79)
        self.assertEqual(panel.writes,[80])

    def test_macdoppler_power_default_waits_for_ptt_release(self):
        panel=FakePowerPanel()
        def transmitting():raise RuntimeError('Release PTT')
        with self.assertRaisesRegex(RuntimeError,'Release PTT'):
            NativePowerControl(panel).set_default(80,transmitting)
        self.assertEqual(panel.writes,[])

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
    def test_ambiguous_vfo_cannot_click_a_filter(self):
        panel = FilterPanelModel()
        original = panel.description
        panel.description = lambda group,name: ON if group == 'VFO' else original(group,name)
        with self.assertRaisesRegex(RuntimeError,'Select only Main/RX'):
            panel.select_filter('CW',2)
        self.assertFalse(any(group=='Mode' for group,name in panel.presses))

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


class SatellitePanelModel(RumlogPanel):
    def __init__(self, band="Main", toggling=True):
        super().__init__()
        self.band, self.toggling = band, toggling
        self.modes = {"Main": "USB-D", "Sub": "USB-D"}
        self.frequencies = {"Main": 433540000, "Sub": 144040000}
        self.presses, self.frequency_writes = [], []
        self.tone_writes = []
        self.tones = {b:{"Tone":0.0,"TSQL":0.0} for b in ("Main","Sub")}
        self.frontend_writes=[]

    def sat_on(self):
        return True

    def description(self, group, name):
        if group == "VFO":
            return ON if self.band == name else OFF
        if group == "Miscellaneous" and name == "Toggle":
            return ON if self.toggling else OFF
        mode = self.modes[self.band]
        if group == "Mode":
            if name == "Data":
                return ON if mode in ("USB-D", "LSB-D") else OFF
            title = {"USB-D":"USB", "LSB-D":"LSB", "CW-R":"CW R", "RTTY":"RY", "RTTY-R":"RY R"}.get(mode, mode)
            return ON if name == title else OFF
        raise AssertionError((group,name))

    def press(self, group, name):
        self.presses.append((group,name))
        if group == "VFO":
            self.band = name
        elif group == "Miscellaneous":
            self.toggling = not self.toggling
        elif group == "Mode":
            if name == "Data":
                mode = self.modes[self.band]
                self.modes[self.band] = mode[:-2] if mode.endswith("-D") else mode+"-D"
            else:
                self.modes[self.band] = {"CW R":"CW-R", "RY":"RTTY", "RY R":"RTTY-R"}.get(name,name)
        else:
            raise AssertionError((group,name))

    def selected_mode(self, band):
        return self.modes[band] if self.band == band else None

    def fields(self, group):
        band = "Main" if "Main" in group else "Sub"
        mode = self.modes[band]
        return [str(self.frequencies[band]/1000), "Data" if mode.endswith("-D") else "",
                mode[:-2] if mode.endswith("-D") else mode, "FIL 1"]

    def wait(self, predicate, label, timeout=3):
        if not predicate():
            raise RuntimeError(label)

    def set_frequency(self, hz):
        self.frequency_writes.append((self.band,hz))
        self.frequencies[self.band] = hz

    def select_vfo(self, band):
        self.press("VFO", band)

    def set_selected_tone(self, band, kind, hz, check_rx=lambda:None):
        if self.band != band:
            raise RuntimeError("Wrong tone VFO")
        check_rx()
        self.tone_writes.append((self.band,kind,hz))
        self.tones[self.band][kind] = hz
        return hz

    def set_rx_frontend(self,source,hz,check_rx):
        check_rx()
        if self.band!='Main':raise RuntimeError('Wrong receiver VFO')
        self.frontend_writes.append((source,hz))
        return {'source':source}


class SatellitePairTests(unittest.TestCase):
    def pair(self, rx_mode="USB", tx_mode="USB"):
        return Pair.from_values("433.740", "144.240", rx_mode, tx_mode)

    def apply(self, panel, pair=None, previous=None, check_rx=lambda:None):
        return panel.apply_satellite_pair(pair or self.pair(), previous, panel.set_frequency, check_rx, lambda *a,**k:None)

    def test_ssb_pair_clears_data_on_both_vfos_and_targets_each_frequency(self):
        panel = SatellitePanelModel()
        result = self.apply(panel)
        self.assertEqual(panel.modes,{"Main":"USB","Sub":"USB"})
        self.assertEqual(panel.frequency_writes,[("Main",433740000),("Sub",144240000)])
        self.assertEqual((result["rx_mode"],result["tx_mode"]),("USB","USB"))
        self.assertEqual(panel.band,"Main")
        self.assertTrue(panel.toggling)
        self.assertFalse(any(name.startswith("Fi.") for group,name in panel.presses))

    def test_mixed_modes_and_reverse_modes_are_independent(self):
        for rx,tx in (("CW","USB-D"),("LSB-D","CW-R"),("RTTY-R","FM"),("AM","RTTY")):
            with self.subTest(rx=rx,tx=tx):
                panel = SatellitePanelModel()
                self.apply(panel,self.pair(rx,tx))
                self.assertEqual(panel.modes,{"Main":rx,"Sub":tx})

    def test_digital_pair_enables_data_on_each_vfo(self):
        panel = SatellitePanelModel()
        panel.modes = {"Main":"USB","Sub":"USB"}
        self.apply(panel,self.pair("USB-D","USB-D"))
        self.assertEqual(panel.modes,{"Main":"USB-D","Sub":"USB-D"})

    def test_sub_view_and_disabled_polling_are_preserved(self):
        panel = SatellitePanelModel(band="Sub",toggling=False)
        self.apply(panel)
        self.assertEqual(panel.band,"Sub")
        self.assertFalse(panel.toggling)

    def test_unchanged_frequency_is_not_written(self):
        panel = SatellitePanelModel()
        before = Pair.from_values("433.540","144.040","USB-D","USB-D")
        target = Pair.from_values("433.740","144.040","USB","USB")
        self.apply(panel,target,before)
        self.assertEqual(panel.frequency_writes,[("Main",433740000)])

    def test_reselect_after_manual_tuning_recovers_vfo_changed_by_frequency_update(self):
        panel = SatellitePanelModel(band="Sub")
        panel.frequencies = {"Main":433744800,"Sub":144244800}
        panel.modes = {"Main":"USB","Sub":"USB"}
        original = panel.set_frequency
        def set_and_change_view(hz):
            original(hz)
            panel.band = "Sub" if panel.band == "Main" else "Main"
        panel.set_frequency = set_and_change_view
        self.apply(panel)
        self.assertEqual(panel.frequency_writes,[("Main",433740000),("Sub",144240000)])
        self.assertEqual(panel.modes,{"Main":"USB","Sub":"USB"})
        self.assertEqual(panel.band,"Sub")
        self.assertTrue(panel.toggling)

    def test_vfo_selection_waits_through_late_conflicting_feedback(self):
        panel = SatellitePanelModel()
        clock=[0.0]
        def description(group,name):
            self.assertEqual(group,"VFO")
            if clock[0]<.2:
                return ON
            if .35<=clock[0]<.45:
                return ON if name=="Sub" else OFF
            return ON if name=="Main" else OFF
        panel.description=description
        with patch('rumlog_panel.time.monotonic',lambda:clock[0]), patch('rumlog_panel.time.sleep',lambda n:clock.__setitem__(0,clock[0]+n)):
            RumlogPanel.select_vfo(panel,"Main")
        self.assertGreaterEqual(clock[0],.7)

    def test_active_ptt_blocks_every_control_and_frequency_write(self):
        panel = SatellitePanelModel()
        def transmitting():
            raise RuntimeError("PTT active")
        with self.assertRaisesRegex(RuntimeError,"PTT active"):
            self.apply(panel,check_rx=transmitting)
        self.assertFalse(panel.presses)
        self.assertFalse(panel.frequency_writes)

    def test_ptt_during_pair_stops_before_tx_write_and_restores_view(self):
        panel = SatellitePanelModel()
        def check():
            if panel.band == "Sub":
                raise RuntimeError("PTT active")
        with self.assertRaisesRegex(RuntimeError,"PTT active"):
            self.apply(panel,check_rx=check)
        self.assertEqual(panel.frequency_writes,[("Main",433740000)])
        self.assertEqual(panel.modes["Sub"],"USB-D")
        self.assertEqual(panel.band,"Main")
        self.assertTrue(panel.toggling)

    def test_wrong_frequency_feedback_is_not_retried(self):
        panel = SatellitePanelModel()
        writes=[]
        with self.assertRaisesRegex(RuntimeError,"RX frequency"):
            panel.apply_satellite_pair(self.pair(),None,writes.append,lambda:None,lambda *a,**k:None)
        self.assertEqual(writes,[433740000])
        self.assertEqual(panel.band,"Main")
        self.assertTrue(panel.toggling)

    def test_mode_cannot_be_written_to_an_unselected_vfo(self):
        panel = SatellitePanelModel()
        with self.assertRaisesRegex(RuntimeError,"Select only Sub"):
            panel.set_selected_mode("Sub","CW")
        self.assertFalse(panel.presses)
        self.assertEqual(panel.modes["Sub"],"USB-D")

    def test_ptt_is_rechecked_before_a_data_button_change(self):
        panel = SatellitePanelModel()
        def transmitting():
            raise RuntimeError("PTT became active")
        with self.assertRaisesRegex(RuntimeError,"PTT became active"):
            panel.set_selected_mode("Main","USB",transmitting)
        self.assertFalse(panel.presses)
        self.assertEqual(panel.modes["Main"],"USB-D")

    def test_native_failure_does_not_fall_back_to_commander_setters(self):
        app = App.__new__(App)
        app.radio_panel = SatellitePanelModel()
        app.bridge = SimpleNamespace(source="qo100")
        def fail(*args,**kwargs):
            raise RuntimeError("Mode feedback unavailable")
        app.radio_panel.apply_satellite_pair = fail
        transport = app.transport(lambda *a,**k:None)
        commands=[]
        def command(name,*args,**kwargs):
            commands.append(name)
            return "OFF"
        transport.command = command
        with self.assertRaisesRegex(RuntimeError,"Mode feedback unavailable"):
            transport.apply(self.pair(),force=True)
        self.assertFalse(any(name.startswith("CmdSet") for name in commands))
        self.assertIsNone(transport.last_pair)

    def test_app_qo_transport_uses_selected_vfos_and_no_commander_tx_setters(self):
        app = App.__new__(App)
        app.radio_panel = SatellitePanelModel()
        app.bridge = SimpleNamespace(source="qo100")
        transport = app.transport(lambda *a,**k:None)
        commands=[]
        def command(name,params="",reply=None):
            commands.append(name)
            if name == "CmdSendTx":
                return "OFF"
            self.assertEqual(name,"CmdSetFreq")
            hz = int(float(params.split(">",1)[1])*1000)
            app.radio_panel.set_frequency(hz)
        transport.command = command
        transport.apply(self.pair(),force=True)
        self.assertEqual(commands.count("CmdSetFreq"),2)
        self.assertEqual(app.radio_panel.modes,{"Main":"USB","Sub":"USB"})
        self.assertEqual(transport.last_pair,self.pair())

    def test_macdoppler_transport_targets_both_sat_vfos_and_keeps_tones_separate(self):
        app = App.__new__(App)
        app.radio_panel = SatellitePanelModel()
        power_defaults=[]
        app.power_control=SimpleNamespace(set_default=lambda percent,check:power_defaults.append(percent))
        app.bridge = SimpleNamespace(source="macdoppler")
        transport = app.transport(lambda *a,**k:None)
        commands=[]
        def command(name,params="",reply=None):
            commands.append(name)
            if name=="CmdSendTx":
                return "OFF"
            self.assertEqual(name,"CmdSetFreq")
            app.radio_panel.set_frequency(int(float(params.split(">",1)[1])*1000))
        transport.command=command
        target=Pair.from_values("436.795","145.850","FM","FM",67.0,0.0)
        transport.apply(target,force=True)
        self.assertEqual(app.radio_panel.frequency_writes,[("Main",436795000),("Sub",145850000)])
        self.assertEqual(app.radio_panel.tone_writes,[("Main","TSQL",0.0),("Sub","Tone",67.0)])
        self.assertFalse(any(c in commands for c in ("CmdSetTXFreq","CmdSetTXMode")))
        self.assertEqual(power_defaults,[80])
        next_pair=Pair.from_values('436.794950','145.850123','FM','FM',67.0,0.0)
        transport.apply(next_pair)
        self.assertEqual(power_defaults,[80])

    def test_tone_change_without_frequency_change_only_updates_tx_tone(self):
        panel = SatellitePanelModel()
        opening = Pair.from_values("436.795", "145.850", "FM", "FM", 74.4, 0.0)
        access = Pair.from_values("436.795", "145.850", "FM", "FM", 67.0, 0.0)
        self.apply(panel, opening)
        panel.frequency_writes.clear()
        panel.tone_writes.clear()
        self.apply(panel, access, opening)
        self.assertEqual(panel.frequency_writes, [])
        self.assertEqual(panel.tone_writes, [("Sub", "Tone", 67.0)])
        self.assertEqual(panel.tones["Main"]["TSQL"], 0.0)

    def test_frequency_only_update_does_not_repeat_tone_controls(self):
        panel = SatellitePanelModel()
        previous = Pair.from_values("436.795", "145.850", "FM", "FM", 67.0, 0.0)
        self.apply(panel, previous)
        panel.tone_writes.clear()
        target = Pair.from_values("436.794950", "145.850123", "FM", "FM", 67.0, 0.0)
        self.apply(panel, target, previous)
        self.assertEqual(panel.tone_writes, [])

    def test_continuous_tracking_keeps_polling_off_and_background_reads_cannot_enable_it(self):
        panel = SatellitePanelModel()
        pair = self.pair()
        with patch('rumlog_panel.time.sleep'):
            panel.apply_satellite_pair(pair,None,panel.set_frequency,lambda:None,lambda *a,**k:None,continuous=True)
        self.assertFalse(panel.toggling)
        self.assertIs(panel._polling_before_tracking,True)
        panel.ensure_polling()
        self.assertFalse(panel.toggling)
        next_pair = Pair.from_values('433.740013','144.239989','USB','USB')
        panel.apply_satellite_pair(next_pair,pair,panel.set_frequency,lambda:None,lambda *a,**k:None,continuous=True)
        self.assertFalse(panel.toggling)
        self.assertEqual(panel.presses.count(('Miscellaneous','Toggle')),1)

    def test_return_to_qo_restores_polling_after_the_one_time_pair(self):
        panel = SatellitePanelModel()
        pair = self.pair()
        with patch('rumlog_panel.time.sleep'):
            panel.apply_satellite_pair(pair,None,panel.set_frequency,lambda:None,lambda *a,**k:None,continuous=True)
        self.apply(panel,self.pair('USB-D','USB-D'))
        self.assertTrue(panel.toggling)
        self.assertIsNone(panel._polling_before_tracking)

    def test_continuous_failure_stays_paused_from_polling_until_explicit_restore(self):
        panel = SatellitePanelModel()
        with patch('rumlog_panel.time.sleep'),self.assertRaisesRegex(RuntimeError,'RX frequency'):
            panel.apply_satellite_pair(self.pair(),None,lambda hz:None,lambda:None,lambda *a,**k:None,continuous=True)
        self.assertFalse(panel.toggling)
        panel.ensure_polling()
        self.assertFalse(panel.toggling)
        panel.release_tracking_polling()
        self.assertTrue(panel.toggling)
        self.assertIsNone(panel._polling_before_tracking)

    def test_tracking_close_preserves_an_initially_disabled_polling_choice(self):
        panel = SatellitePanelModel(toggling=False)
        with patch('rumlog_panel.time.sleep'):
            panel.apply_satellite_pair(self.pair(),None,panel.set_frequency,lambda:None,lambda *a,**k:None,continuous=True)
        panel.release_tracking_polling()
        self.assertFalse(panel.toggling)


class TonePanelModel(RumlogPanel):
    """Model the actual popup/menu/button API used by the native method."""

    def __init__(self):
        super().__init__()
        self.band = "Sub"
        self.mode = "FM"
        self.states = {b:{"Tone":OFF,"TSQL":OFF} for b in ("Main","Sub")}
        self.hz = {b:{"Tone":88.5,"TSQL":123.0} for b in ("Main","Sub")}
        self.writes = []
        self.menu_open = self.cancelled = False
        self.change_band_on_open = self.ignore_frequency = False
        self.offered = (67.0,74.4)
        self.popups = [self.popup(kind) for kind in ("Tone","TSQL")]
        self._groups["Miscellaneous"] = PanelElement(children=self.popups)

    def popup(self, kind):
        panel = self
        class Popup(PanelElement):
            def get(self, name, default=None):
                if name == "AXValue":
                    return f"{panel.hz[panel.band][kind]:.1f} Hz"
                return super().get(name, default)

            def press(self):
                panel.writes.append(("open",panel.band,kind))
                panel.menu_open = True
                self.children = [Menu(children=[Choice(hz) for hz in panel.offered],AXRole="AXMenu")]
                if panel.change_band_on_open:
                    panel.band = "Main"

        class Menu(PanelElement):
            def cancel(self):
                panel.cancelled, panel.menu_open = True, False

        class Choice(PanelElement):
            def __init__(self, hz):
                super().__init__(AXTitle=f"{hz:.1f} Hz")
                self.hz = hz

            def press(self):
                panel.writes.append(("frequency",panel.band,kind,self.hz))
                if not panel.ignore_frequency:
                    panel.hz[panel.band][kind] = self.hz
                panel.menu_open = False

        return Popup(AXRole="AXPopUpButton")

    def focus_for_menu(self):
        return None

    def description(self, group, name):
        if group == "VFO":
            return ON if self.band == name else OFF
        if group == "Miscellaneous":
            return self.states[self.band][name]
        raise AssertionError((group,name))

    def selected_mode(self, band):
        return self.mode if self.band == band else None

    def press(self, group, name):
        self.writes.append(("button",self.band,name))
        self.states[self.band][name] = OFF if self.states[self.band][name] == ON else ON

    def wait(self, predicate, label, timeout=3):
        if not predicate():
            raise RuntimeError(label)


class NativeToneTests(unittest.TestCase):
    def test_background_tone_menu_is_focused_before_open_and_previous_app_is_restored(self):
        panel = TonePanelModel()
        state={'front':False,'restored':False}
        def set_front(name,value):
            self.assertEqual((name,value),('AXFrontmost',True))
            state['front']=True
        panel._app=SimpleNamespace(get=lambda name:state['front'],set_boolean=set_front)
        panel.window=lambda:None
        panel.focus_for_menu=lambda:RumlogPanel.focus_for_menu(panel)
        previous=SimpleNamespace(set_boolean=lambda name,value:state.__setitem__('restored',True))
        popup=panel.popups[0];original=popup.press
        def press():
            self.assertTrue(state['front'])
            original()
        popup.press=press
        with patch('rumlog_panel.focused_application',return_value=previous):
            self.assertEqual(panel.set_selected_tone('Sub','Tone',67),67)
        self.assertTrue(state['restored'])

    def test_menu_may_appear_after_the_popup_press_returns(self):
        panel = TonePanelModel()
        popup = panel.popups[0]
        original = popup.press
        pending = []
        def press():
            original()
            pending.extend(popup.children)
            popup.children = []
        popup.press = press
        clock = [0.0]
        def advance(seconds):
            clock[0] += seconds
            if pending:
                popup.children = list(pending)
                pending.clear()
        panel.wait = lambda predicate,label,timeout=3: RumlogPanel.wait(panel,predicate,label,timeout)
        with patch('rumlog_panel.time.monotonic',lambda:clock[0]),patch('rumlog_panel.time.sleep',advance):
            self.assertEqual(panel.set_selected_tone('Sub','Tone',67),67)
        self.assertGreater(clock[0],0)

    def test_tx_67_and_74_4_use_encoder_popup_and_leave_rx_squelch_unchanged(self):
        for hz in (67.0,74.4):
            with self.subTest(hz=hz):
                panel = TonePanelModel()
                panel.states["Main"]["TSQL"] = ON
                self.assertEqual(panel.set_selected_tone("Sub","Tone",hz),hz)
                self.assertEqual(panel.hz["Sub"]["Tone"],hz)
                self.assertEqual(panel.states["Sub"]["Tone"],ON)
                self.assertEqual(panel.states["Main"]["TSQL"],ON)
                self.assertEqual(panel.hz["Main"]["TSQL"],123.0)
                self.assertEqual([w for w in panel.writes if w[0]=='button'],[("button","Sub","Tone")])

    def test_zero_disables_tx_encoder_without_opening_popup(self):
        panel = TonePanelModel()
        panel.states["Sub"]["Tone"] = ON
        self.assertEqual(panel.set_selected_tone("Sub","Tone",0),0.0)
        self.assertEqual(panel.states["Sub"]["Tone"],OFF)
        self.assertEqual(panel.hz["Sub"]["Tone"],88.5)
        self.assertEqual(panel.writes,[("button","Sub","Tone")])

    def test_omitted_tone_does_not_change_any_panel_control(self):
        panel = TonePanelModel()
        self.assertIsNone(panel.set_selected_tone("Sub","Tone",None))
        self.assertEqual(panel.writes,[])

    def test_wrong_vfo_or_non_fm_cannot_enable_tone(self):
        for wrong_vfo in (False,True):
            panel = TonePanelModel()
            if wrong_vfo:
                panel.band = "Main"
            else:
                panel.mode = "USB"
            with self.assertRaises(RuntimeError):
                panel.set_selected_tone("Sub","Tone",67)
            self.assertEqual(panel.writes,[])

    def test_ptt_blocks_frequency_and_enable_writes(self):
        panel = TonePanelModel()
        def transmitting():
            raise RuntimeError("PTT active")
        with self.assertRaisesRegex(RuntimeError,"PTT active"):
            panel.set_selected_tone("Sub","Tone",67,transmitting)
        self.assertEqual(panel.writes,[])

    def test_vfo_change_while_menu_is_open_cancels_without_setting_rx_tone(self):
        panel = TonePanelModel()
        panel.change_band_on_open = True
        with self.assertRaisesRegex(RuntimeError,"Select only Sub"):
            panel.set_selected_tone("Sub","Tone",67)
        self.assertTrue(panel.cancelled)
        self.assertFalse(panel.menu_open)
        self.assertEqual(panel.hz["Main"]["Tone"],88.5)
        self.assertFalse(any(w[0] in ('frequency','button') for w in panel.writes))

    def test_missing_tone_choice_cancels_instead_of_enabling(self):
        panel = TonePanelModel()
        panel.offered = ()
        with self.assertRaisesRegex(RuntimeError,"does not offer"):
            panel.set_selected_tone("Sub","Tone",67)
        self.assertTrue(panel.cancelled)
        self.assertEqual(panel.states["Sub"]["Tone"],OFF)

    def test_unchanged_popup_after_choice_is_not_treated_as_success(self):
        panel = TonePanelModel()
        panel.ignore_frequency = True
        with self.assertRaisesRegex(RuntimeError,"Tone frequency"):
            panel.set_selected_tone("Sub","Tone",67)
        self.assertEqual(panel.states["Sub"]["Tone"],OFF)


if __name__ == "__main__":
    unittest.main(verbosity=2)
