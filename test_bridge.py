import json
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from bridge_core import Bridge, Transport, Pair, Settings, BusyRadio, parse_radio_report, hz_from_mhz
from rumlog_filter import RxFilterControl, MAIN, SUB, TOGGLE, ON, OFF


def packet(rx="433.541", tx="144.038", down="USB-D", up="USB-D"):
    return f"[Sat Radio Report:Down Mhz:{rx}, Down Mode:{down}, Up MHz:{tx}, Up Mode:{up}]"


HOME = Pair.from_values("433.540", "144.040", "USB-D", "USB-D")
LEO = Pair.from_values("433.541", "144.038", "USB-D", "USB-D")


def eventually(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for bridge state")


class FakeTransport:
    def __init__(self, log):
        self.log = log
        self.last_pair = None
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    def apply(self, pair, force=False):
        if self.block:
            self.entered.set()
            if not self.release.wait(3):
                raise RuntimeError("Test release timed out")
            self.block = False
        self.calls.append((pair, force))
        self.last_pair = pair


class ParsingTests(unittest.TestCase):
    def test_actual_macdoppler_envelope_and_extra_fields(self):
        raw = "00000003 Matthias’s iMac (2) [Sat Radio Report:Down Mhz:433.540101, Down Mode:USB-D, Up MHz:144.040000, Up Mode:LSB-D, tone:0.0, ctone:0.0, SatName:QO-100]"
        pair = parse_radio_report(raw)
        self.assertEqual((pair.rx_hz, pair.tx_hz), (433540101, 144040000))
        self.assertEqual(pair.tx_mode, "LSB-D")

    def test_separate_frequencies_modes_and_hz_precision(self):
        pair = parse_radio_report(packet("433.541123", "144.037987", "DATA-U", "CW"))
        self.assertEqual((pair.rx_hz, pair.tx_hz), (433541123, 144037987))
        self.assertEqual((pair.rx_mode, pair.tx_mode), ("USB-D", "CW"))

    def test_macdoppler_tx_tone_and_rx_squelch_are_separate(self):
        for hz in (67.0,74.4):
            text = packet("436.795", "145.850", "FM", "FM")[:-1] + f", tone:{hz}, ctone:0.0]"
            pair = parse_radio_report(text)
            self.assertEqual(pair.tx_tone_hz,hz)
            self.assertEqual(pair.rx_tone_hz,0.0)

    def test_omitted_tone_is_distinct_from_disabled_tone(self):
        omitted = parse_radio_report(packet("436.795", "145.850", "FM", "FM"))
        disabled = parse_radio_report(packet("436.795", "145.850", "FM", "FM")[:-1] + ", tone:0.0]")
        self.assertIsNone(omitted.tx_tone_hz)
        self.assertEqual(disabled.tx_tone_hz,0.0)
        self.assertIsNone(disabled.rx_tone_hz)

    def test_invalid_or_non_fm_tone_is_rejected_before_dispatch(self):
        for tone in ('NaN','Infinity','-67','74.5','999'):
            with self.subTest(tone=tone), self.assertRaises(ValueError):
                parse_radio_report(packet("436.795", "145.850", "FM", "FM")[:-1] + f", tone:{tone}]")
        with self.assertRaisesRegex(ValueError,"CTCSS requires FM"):
            parse_radio_report(packet("436.795", "145.850", "FM", "USB")[:-1] + ", tone:67.0]")

    def test_reject_partial_duplicate_invalid_and_nonfinite_packets(self):
        for text in (
            "[Sat Radio Report:Down Mhz:433.5, Down Mode:USB]",
            packet().replace("Up MHz:", "Down Mhz:"),
            packet("10489.750"), packet("NaN"), packet("Infinity"),
            packet("433.5410001"), packet(down="INVALID"),
            packet("145.762500", "145.162500", "FM", "FM"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_radio_report(text)
        self.assertIsNone(parse_radio_report("[AzEl Rotor Report:Azimuth:350.00, Elevation:0.00]"))


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Bridge(transport_factory=FakeTransport, power_guard=lambda force=False: 4, rx_filter=lambda mode, number: number)
        self.bridge.start(port=0)

    def tearDown(self):
        self.bridge.transport.release.set()
        self.bridge.close()

    def send(self, text):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(text.encode(), self.bridge.udp_address)

    def test_start_paused_and_qo_blocks_real_udp_storm(self):
        self.send(packet())
        eventually(lambda: self.bridge.received == 1)
        self.assertFalse(self.bridge.transport.calls)
        self.bridge.use_qo100(HOME, "Home")
        eventually(lambda: len(self.bridge.transport.calls) == 1)
        for i in range(30):
            self.send(packet(tx=str(144.030 + i / 100000)))
        eventually(lambda: self.bridge.received == 31)
        self.assertEqual(self.bridge.transport.calls, [(HOME, True)])
        self.assertEqual(self.bridge.ignored, 31)

    def test_follow_then_return_home_with_separate_values(self):
        self.bridge.use_qo100(HOME, "Home")
        eventually(lambda: self.bridge.last_sent == HOME)
        self.send(packet())
        eventually(lambda: self.bridge.latest == LEO)
        self.bridge.follow_macdoppler()
        eventually(lambda: self.bridge.last_sent == LEO)
        self.bridge.use_qo100(HOME, "Home")
        eventually(lambda: self.bridge.last_sent == HOME)
        count = len(self.bridge.transport.calls)
        self.send(packet("433.549", "144.031"))
        eventually(lambda: self.bridge.latest.rx_hz == 433549000)
        self.assertEqual(len(self.bridge.transport.calls), count)
        self.assertEqual(self.bridge.source, "qo100")

    def test_inflight_and_queued_md_work_cannot_escape_source_switch(self):
        transport = self.bridge.transport
        self.bridge.follow_macdoppler()
        transport.block = True
        self.send(packet())
        self.assertTrue(transport.entered.wait(2))
        switched = threading.Event()
        thread = threading.Thread(target=lambda: (self.bridge.use_qo100(HOME, "Home"), switched.set()))
        thread.start()
        eventually(lambda: not self.bridge.enabled)
        for i in range(12):
            self.send(packet("433.550", "144.030"))
        transport.release.set()
        self.assertTrue(switched.wait(2))
        eventually(lambda: self.bridge.last_sent == HOME)
        self.assertEqual([p for p, _ in transport.calls], [LEO, HOME])
        thread.join()

    def test_stale_input_not_replayed_and_pause_prevents_tuning(self):
        self.bridge.freshness = 0.03
        self.bridge.ingest(packet())
        time.sleep(0.05)
        self.bridge.follow_macdoppler()
        time.sleep(0.05)
        self.assertFalse(self.bridge.transport.calls)
        self.bridge.ingest(packet())
        eventually(lambda: self.bridge.last_sent == LEO)
        self.bridge.pause()
        count = len(self.bridge.transport.calls)
        self.send(packet("433.545", "144.035"))
        eventually(lambda: self.bridge.latest.rx_hz == 433545000)
        self.assertEqual(len(self.bridge.transport.calls), count)

    def test_invalid_data_clears_cached_input_and_holds_manual_target(self):
        self.bridge.use_qo100(HOME, "Home")
        eventually(lambda: self.bridge.last_sent == HOME)
        self.bridge.ingest(packet())
        self.bridge.ingest(packet("2400.100"))
        self.assertIsNone(self.bridge.latest)
        self.assertEqual(self.bridge.last_sent, HOME)
        self.assertEqual(self.bridge.rejected, 1)

    def test_on_exit_report_cannot_replay_previous_satellite_pair(self):
        self.bridge.ingest(packet())
        self.bridge.ingest(packet("145.762500", "145.162500", "FM", "FM"))
        self.bridge.follow_macdoppler()
        time.sleep(.1)
        self.assertFalse(self.bridge.transport.calls)
        self.bridge.ingest(packet())
        eventually(lambda: self.bridge.last_sent == LEO)

    def test_output_error_pauses_and_discards_pending(self):
        def fail(pair, force=False):
            raise OSError("Connection refused")
        self.bridge.transport.apply = fail
        self.bridge.follow_macdoppler()
        self.bridge.ingest(packet())
        eventually(lambda: bool(self.bridge.error))
        self.assertFalse(self.bridge.enabled)
        self.assertIsNone(self.bridge.pending)


class TransportTests(unittest.TestCase):
    def test_tcp_frames_independent_updates_and_no_ptt_command(self):
        frames = []
        stop = threading.Event()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.1)
        def serve():
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    raw = connection.recv(4096).decode()
                    frames.append(raw)
                    if "CmdSendTx" in raw:
                        connection.sendall(b"<CmdTX:3>OFF")
        thread = threading.Thread(target=serve)
        thread.start()
        try:
            transport = Transport(lambda *args, **kwargs: None, port=listener.getsockname()[1])
            transport.apply(HOME, force=True)
            first_count = len(frames)
            rx_only = Pair.from_values("433.541123", "144.040", "USB-D", "USB-D")
            transport.apply(rx_only)
            self.assertEqual(len(frames), first_count + 1)
            self.assertIn("CmdSetFreq", frames[-1])
            self.assertIn("<xcvrfreq:10>433541.123", frames[-1])
            transport.apply(Pair.from_values("433.541123", "144.037987", "USB-D", "USB-D"))
            self.assertIn("CmdSetTXFreq", frames[-1])
            self.assertIn("144037.987", frames[-1])
            self.assertTrue(any("CmdSetTXMode" in f and "DATA-U" in f for f in frames))
            self.assertFalse(any("CmdTX<" in f for f in frames))
            with self.assertRaises(ValueError):
                transport.command("CmdTX")
        finally:
            stop.set()
            thread.join(2)
            listener.close()

    def test_source_mode_change_does_not_tune_during_ptt(self):
        transport = Transport(lambda *args, **kwargs: None)
        commands = []
        def command(name, *args, **kwargs):
            commands.append(name)
            return "ON"
        transport.command = command
        with self.assertRaises(BusyRadio):
            transport.apply(HOME, force=True)
        self.assertEqual(commands, ["CmdSendTx"])


class PresetVerificationTests(unittest.TestCase):
    def make_bridge(self, clock, reading):
        bridge = Bridge(transport_factory=FakeTransport, power_guard=lambda force=False:4, radio_reader=reading, verify_qo=True)
        bridge.use_qo100(HOME, "Digital")
        bridge.stop_event.wait = lambda seconds: clock.__setitem__(0, clock[0]+seconds) or False
        return bridge

    def test_optimistic_tx_echo_that_falls_back_is_reported_without_any_retry(self):
        clock = [0.0]
        def reading():
            tx = HOME.tx_hz if clock[0] < .45 else HOME.tx_hz - 41230
            return {"rx_hz":HOME.rx_hz,"tx_hz":tx,"monotonic_at":clock[0]}
        bridge = self.make_bridge(clock, reading)
        with patch("bridge_core.time.monotonic", lambda:clock[0]):
            self.assertIsNone(bridge._confirm_qo_pair(HOME, bridge.epoch))
        self.assertFalse(bridge.transport.calls)
        self.assertEqual(bridge.events[-1]["kind"], "qo_readback_differs")

    def test_missing_or_wrong_band_feedback_only_reports_without_retuning(self):
        clock = [0.0]
        bridge = self.make_bridge(clock, lambda:{"rx_hz":HOME.tx_hz,"tx_hz":None,"monotonic_at":clock[0]})
        with patch("bridge_core.time.monotonic", lambda:clock[0]):
            self.assertIsNone(bridge._confirm_qo_pair(HOME, bridge.epoch))
        self.assertFalse(bridge.transport.calls)

    def test_stable_feedback_passes_without_sending_a_command(self):
        clock = [0.0]
        bridge = self.make_bridge(clock, lambda:{"rx_hz":HOME.rx_hz,"tx_hz":HOME.tx_hz,"monotonic_at":clock[0]})
        with patch("bridge_core.time.monotonic", lambda:clock[0]):
            self.assertTrue(bridge._confirm_qo_pair(HOME, bridge.epoch))
        self.assertGreaterEqual(clock[0],2)
        self.assertFalse(bridge.transport.calls)

    def test_explicit_source_change_cancels_verification(self):
        clock = [0.0]
        bridge = self.make_bridge(clock, lambda:{"rx_hz":HOME.rx_hz,"tx_hz":HOME.tx_hz-100,"monotonic_at":clock[0]})
        epoch = bridge.epoch
        def wait(seconds):
            clock[0]+=seconds
            bridge.pause()
            return False
        bridge.stop_event.wait = wait
        with patch("bridge_core.time.monotonic", lambda:clock[0]):
            self.assertFalse(bridge._confirm_qo_pair(HOME, epoch))
        self.assertFalse(bridge.transport.calls)
        self.assertFalse(bridge.enabled)


class PowerTests(unittest.TestCase):
    def test_missing_power_controller_blocks_qo_tuning(self):
        bridge = Bridge(transport_factory=FakeTransport, rx_filter=lambda mode, number: number)
        bridge.start(port=0)
        try:
            bridge.use_qo100(HOME, "Home")
            eventually(lambda: bool(bridge.error))
            self.assertFalse(bridge.transport.calls)
            self.assertIn("power control is unavailable", bridge.power_error)
        finally:
            bridge.close()
    def test_qo_checks_power_before_and_after_band_change(self):
        order = []
        power = {"percent": 80}
        def guard(force=False):
            order.append("power")
            power["percent"] = 4
            return power["percent"]
        class BandChangingTransport(FakeTransport):
            def apply(self, pair, force=False):
                order.append("tune")
                power["percent"] = 90
                super().apply(pair, force)
        bridge = Bridge(transport_factory=BandChangingTransport, power_guard=guard, rx_filter=lambda mode, number: number)
        bridge.start(port=0)
        try:
            bridge.use_qo100(HOME, "Home")
            eventually(lambda: bridge.applied == 1)
            self.assertEqual(order[:3], ["power", "tune", "power"])
            self.assertEqual(power["percent"], 4)
            self.assertEqual(bridge.snapshot()["power_percent"], 4)
        finally:
            bridge.close()

    def test_unverified_power_prevents_qo_tuning(self):
        def guard(force=False):
            raise RuntimeError("Power feedback unavailable")
        bridge = Bridge(transport_factory=FakeTransport, power_guard=guard, rx_filter=lambda mode, number: number)
        bridge.start(port=0)
        try:
            bridge.use_qo100(HOME, "Home")
            eventually(lambda: bool(bridge.error))
            self.assertFalse(bridge.transport.calls)
            self.assertFalse(bridge.enabled)
            self.assertIsNone(bridge.power_percent)
            self.assertIn("unavailable", bridge.power_error)
        finally:
            bridge.close()

    def test_power_monitor_stays_active_when_qo_tuning_is_paused(self):
        power = {"percent": 4}
        def guard(force=False):
            if force or power["percent"] > 5:
                power["percent"] = 4
            return power["percent"]
        bridge = Bridge(transport_factory=FakeTransport, power_guard=guard, rx_filter=lambda mode, number: number)
        bridge.start(port=0)
        try:
            bridge.use_qo100(HOME, "Home")
            eventually(lambda: bridge.applied == 1)
            bridge.pause()
            power["percent"] = 50
            eventually(lambda: power["percent"] == 4, timeout=2)
            self.assertFalse(bridge.enabled)
            self.assertTrue(bridge.snapshot()["power_cap_active"])
        finally:
            bridge.close()

    def test_power_recovery_automatically_applies_the_waiting_preset(self):
        missing = threading.Event()
        missing.set()
        def guard(force=False):
            if missing.is_set():
                raise RuntimeError("IC-9700 panel unavailable")
            return 4
        bridge = Bridge(transport_factory=FakeTransport, power_guard=guard, rx_filter=lambda mode, number: number)
        bridge.start(port=0)
        try:
            bridge.use_qo100(HOME, "Home")
            eventually(lambda: bool(bridge.power_error))
            missing.clear()
            eventually(lambda: bridge.applied == 1, timeout=2)
            self.assertTrue(bridge.enabled)
            self.assertEqual(bridge.transport.calls, [(HOME, True)])
            self.assertEqual(bridge.error, "")
            self.assertIn("QO-100 active", bridge.status)
        finally:
            bridge.close()

    def test_monitor_recovery_preserves_manual_tuning_without_reapplying_pair(self):
        missing = threading.Event()
        radio = {"rx_hz": HOME.rx_hz, "tx_hz": HOME.tx_hz}
        def guard(force=False):
            if missing.is_set():
                raise RuntimeError("Temporary power feedback loss")
            return 4
        bridge = Bridge(transport_factory=FakeTransport, power_guard=guard, rx_filter=lambda mode, number: number, radio_reader=lambda: dict(radio))
        bridge.start(port=0)
        try:
            bridge.use_qo100(HOME, "Home")
            eventually(lambda: bridge.applied == 1)
            missing.set()
            eventually(lambda: bool(bridge.power_error), timeout=2)
            radio["rx_hz"] += 350
            radio["tx_hz"] += 350
            # Exercise repeated misses; they must not turn a display recovery
            # into a preset reapplication that would undo the operator's dial.
            bridge._hold_for_power(RuntimeError("Temporary power feedback loss"))
            missing.clear()
            eventually(lambda: bridge.enabled and not bridge.power_error, timeout=2)
            eventually(lambda: bridge.snapshot()["radio"]["rx_hz"] == radio["rx_hz"], timeout=2)
            self.assertEqual(bridge.transport.calls, [(HOME, True)])
            self.assertEqual(bridge.last_sent, HOME)
            self.assertEqual(bridge.snapshot()["radio"]["tx_hz"], radio["tx_hz"])
        finally:
            bridge.close()

    def test_power_failure_after_commands_never_replays_the_pair_on_recovery(self):
        checks = [0]
        def guard(force=False):
            checks[0] += 1
            if checks[0] == 2:
                raise RuntimeError("Post-command power feedback temporarily unavailable")
            return 4
        bridge = Bridge(transport_factory=FakeTransport, power_guard=guard, rx_filter=lambda mode,number:number)
        bridge.start(port=0)
        try:
            bridge.use_qo100(HOME,"Digital")
            eventually(lambda:bridge.snapshot()["power_retrying"])
            self.assertEqual(bridge.transport.calls,[(HOME,True)])
            eventually(lambda:bridge.enabled and not bridge.power_error,timeout=2)
            self.assertEqual(bridge.transport.calls,[(HOME,True)])
            self.assertEqual(bridge.last_sent,HOME)
            self.assertFalse(bridge.pending)
        finally:
            bridge.close()

    def test_explicit_pause_or_macdoppler_choice_cancels_power_auto_resume(self):
        for follow in (False, True):
            with self.subTest(follow=follow):
                missing = threading.Event()
                def guard(force=False):
                    if missing.is_set():
                        raise RuntimeError("Temporary feedback loss")
                    return 4
                bridge = Bridge(transport_factory=FakeTransport, power_guard=guard, rx_filter=lambda mode, number: number)
                bridge.start(port=0)
                try:
                    bridge.use_qo100(HOME, "Home")
                    eventually(lambda: bridge.applied == 1)
                    missing.set()
                    eventually(lambda: bridge.snapshot()["power_retrying"], timeout=2)
                    if follow:
                        bridge.follow_macdoppler()
                        bridge.ingest(packet())
                    else:
                        bridge.pause()
                    missing.clear()
                    if follow:
                        eventually(lambda: bridge.last_sent == LEO)
                        self.assertEqual(bridge.source, "macdoppler")
                    else:
                        eventually(lambda: bridge.power_percent == 4, timeout=2)
                        self.assertFalse(bridge.enabled)
                        self.assertEqual(bridge.transport.calls, [(HOME, True)])
                    self.assertFalse(bridge.snapshot()["power_retrying"])
                finally:
                    bridge.close()


class PersistenceTests(unittest.TestCase):
    def test_presets_round_trip_and_no_auto_follow_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = Settings(path)
            settings.data = {"home_id": "home", "presets": [{"id": "home", "name": "FT8", **HOME.view()}]}
            settings.save()
            self.assertEqual(Settings(path).data, settings.data)
            bridge = Bridge(transport_factory=FakeTransport)
            self.assertFalse(bridge.enabled)
            self.assertEqual(bridge.source, "qo100")


class FilterTests(unittest.TestCase):
    def test_rx_filter_selects_main_even_if_sub_was_selected(self):
        class ModelControl(RxFilterControl):
            def __init__(self):
                super().__init__()
                self.band = "Sub"
                self.filters = {"Main": 1, "Sub": 1}
            def script(self, body):
                if body == f'return description of {TOGGLE}':
                    return OFF
                for name, target in (("Main", MAIN), ("Sub", SUB)):
                    if body == f'click {target}':
                        self.band = name
                        return ""
                    if body == f'return description of {target}':
                        return ON if self.band == name else OFF
                if 'return description of button "CW"' in body:
                    return ON
                if 'return value of static text 4' in body:
                    return f"FIL {self.filters['Main']}"
                for number in (1,2,3):
                    if f'button "Fi. {number}"' in body:
                        if body.startswith('click '):
                            self.filters[self.band] = number
                            return ""
                        return ON if self.filters[self.band] == number else OFF
                raise AssertionError(body)
        control = ModelControl()
        self.assertEqual(control.select("CW", 2), 2)
        self.assertEqual(control.filters, {"Main": 2, "Sub": 1})
        self.assertEqual(control.band, "Sub")

    def test_rx_filter_rules_apply_to_qo_and_macdoppler_modes(self):
        selected = []
        def choose(mode, number):
            selected.append((mode, number))
            return number
        bridge = Bridge(transport_factory=FakeTransport, power_guard=lambda force=False: 4, rx_filter=choose)
        bridge.start(port=0)
        try:
            for count, mode, wanted in ((1, "CW", 2), (2, "USB-D", 1), (3, "USB", 1)):
                pair = Pair.from_values("433.540", "144.040", mode, "USB-D")
                bridge.use_qo100(pair, mode)
                eventually(lambda: bridge.applied == count)
                self.assertEqual(selected[-1], (mode, wanted))
                self.assertEqual(bridge.rx_filter_number, wanted)
                self.assertEqual(bridge.last_sent.tx_mode, "USB-D")
            bridge.follow_macdoppler()
            for mode,wanted in (("CW",2),("CW-R",2),("USB",1),("USB-D",1)):
                pair = Pair.from_values("435.800", "145.997", mode, "FM")
                count = bridge.applied
                bridge.ingest(packet("435.800", "145.997", mode, "FM"))
                eventually(lambda: bridge.applied > count)
                self.assertEqual(selected[-1],(mode,wanted))
                self.assertEqual(bridge.rx_filter_number,wanted)
                self.assertEqual(bridge.last_sent.tx_mode,"FM")
        finally:
            bridge.close()

    def test_missing_rx_filter_control_blocks_qo_tuning(self):
        bridge = Bridge(transport_factory=FakeTransport, power_guard=lambda force=False: 4)
        bridge.start(port=0)
        try:
            bridge.use_qo100(HOME, "Home")
            eventually(lambda: bool(bridge.error))
            self.assertFalse(bridge.transport.calls)
            self.assertIn("RX filter control is unavailable", bridge.error)
        finally:
            bridge.close()

    def test_missing_rx_filter_control_also_blocks_macdoppler_cw_before_tuning(self):
        bridge = Bridge(transport_factory=FakeTransport)
        bridge.start(port=0)
        try:
            bridge.follow_macdoppler()
            bridge.ingest(packet("435.800","145.997","CW","USB"))
            eventually(lambda: bool(bridge.error))
            self.assertFalse(bridge.transport.calls)
            self.assertIn("RX filter control is unavailable",bridge.error)
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
