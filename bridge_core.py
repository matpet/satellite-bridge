"""MacDoppler UDP -> RUMlogNG TRX 2, with exclusive source ownership."""

import json
import logging
from logging.handlers import RotatingFileHandler
import re
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rumlog_test import field, first_field


MODES = ("USB", "USB-D", "LSB", "LSB-D", "CW", "CW-R", "FM", "AM", "RTTY", "RTTY-R")
MODE_ALIASES = {mode: mode for mode in MODES}
MODE_ALIASES.update({"DATA-U": "USB-D", "USBD": "USB-D", "SSBD": "USB-D", "DATA-L": "LSB-D", "LSBD": "LSB-D", "CWR": "CW-R", "RTTYR": "RTTY-R"})
WIRE_MODES = {"USB-D": "DATA-U", "LSB-D": "DATA-L"}
RX_FILTERS = {"CW": 2, "CW-R": 2, "USB-D": 1, "USB": 1}
CTCSS_TONES = (67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5,
               94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
               131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9,
               171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
               203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1)


def tone_hz(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number not in {Decimal(str(t)) for t in (0.0, *CTCSS_TONES)}:
            raise ValueError
        return float(number)
    except (InvalidOperation, ValueError):
        raise ValueError("Use 0 to disable a tone, or a supported IC-9700 CTCSS frequency")


def utc():
    return datetime.now(timezone.utc).isoformat()


def normalize_mode(value):
    key = value.strip().upper().replace("_", "-")
    if key not in MODE_ALIASES:
        raise ValueError(f"Unsupported operating mode: {value!r}")
    return MODE_ALIASES[key]


def hz_from_mhz(value):
    try:
        number = Decimal(str(value)) * 1000000
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError("Frequency must have whole-Hz precision")
        hz = int(number)
    except (InvalidOperation, OverflowError):
        raise ValueError("Invalid frequency")
    if not any(lo <= hz <= hi for lo, hi in ((144000000, 148000000), (430000000, 450000000), (1240000000, 1300000000))):
        raise ValueError("Use the IC-9700 dial frequency in its 2 m, 70 cm or 23 cm band")
    return hz


def mhz_text(hz):
    return format(Decimal(hz) / 1000000, ".6f")


def dial_band(hz):
    return 2 if hz < 200000000 else 70 if hz < 500000000 else 23


def virtual_split_offsets(mode):
    if mode in ("USB", "USB-D"):
        return (0, 5000, 10000, 15000)
    if mode in ("CW", "CW-R"):
        return (0, 1000, 2000, 3000)
    return (0,)


def virtual_split_target(base_hz, offset_hz, mode):
    if type(offset_hz) is not int or offset_hz not in virtual_split_offsets(mode):
        raise ValueError("Choose a virtual split offset offered for the current TX mode")
    target = base_hz + offset_hz
    hz_from_mhz(Decimal(target) / 1000000)
    return target


@dataclass(frozen=True)
class Pair:
    rx_hz: int
    tx_hz: int
    rx_mode: str
    tx_mode: str
    tx_tone_hz: float = None
    rx_tone_hz: float = None

    @classmethod
    def from_values(cls, rx, tx, rx_mode, tx_mode, tx_tone_hz=None, rx_tone_hz=None):
        pair = cls(hz_from_mhz(rx), hz_from_mhz(tx), normalize_mode(rx_mode), normalize_mode(tx_mode),
                   tone_hz(tx_tone_hz), tone_hz(rx_tone_hz))
        if pair.tx_tone_hz and pair.tx_mode != "FM" or pair.rx_tone_hz and pair.rx_mode != "FM":
            raise ValueError("CTCSS requires FM on the corresponding TX or RX side")
        return pair

    def view(self):
        result = {"rx_mhz": mhz_text(self.rx_hz), "tx_mhz": mhz_text(self.tx_hz), "rx_mode": self.rx_mode, "tx_mode": self.tx_mode}
        for side in ("rx", "tx"):
            value = getattr(self, side + "_tone_hz")
            if value is not None:
                result[side + "_tone_hz"] = value
        return result


def parse_radio_report(text):
    """Parse the complete named pair; never infer one frequency from the other."""
    match = re.fullmatch(r"\s*(?:[0-9a-f]{8}\s+[^\[\]\r\n]{1,200}\s+)?\[Sat Radio Report:(.*?)\]\s*", text, re.I | re.S)
    if not match:
        return None
    fields = {}
    for item in match[1].split(","):
        if ":" not in item:
            raise ValueError("Malformed Sat Radio Report")
        key, value = item.split(":", 1)
        key = " ".join(key.lower().split())
        if key in fields:
            raise ValueError(f"Duplicate field: {key}")
        fields[key] = value.strip()
    required = {"down mhz", "up mhz", "down mode", "up mode"}
    if not required.issubset(fields):
        raise ValueError("Radio report is missing uplink/downlink frequency or mode")
    pair = Pair.from_values(fields["down mhz"], fields["up mhz"], fields["down mode"], fields["up mode"],
                            fields.get("tone"), fields.get("ctone"))
    def band(hz):
        return 2 if hz < 200000000 else 70 if hz < 500000000 else 23
    if band(pair.rx_hz) == band(pair.tx_hz):
        raise ValueError("Not a cross-band satellite pair; MacDoppler may be in its On Exit state")
    return pair


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"presets": [], "home_id": None}
        if self.path.exists():
            loaded = json.loads(self.path.read_text())
            for p in loaded.get("presets", []):
                Pair.from_values(p["rx_mhz"], p["tx_mhz"], p["rx_mode"], p["tx_mode"])
            self.data.update(loaded)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2) + "\n")
        temp.replace(self.path)


class BusyRadio(RuntimeError):
    pass


class PowerUnavailable(RuntimeError):
    pass


class Transport:
    """Tuning transport with optional selected-VFO control; PTT-on is absent."""
    ALLOWED = {"CmdSetFreq", "CmdSetTXFreq", "CmdSetMode", "CmdSetTXMode", "CmdSendTx", "CmdGetFreq", "CmdGetTXFreq", "CmdSendMode"}

    def __init__(self, log, host="127.0.0.1", port=7400, ensure_sat=None, pair_writer=None):
        self.log, self.host, self.port = log, host, port
        self.ensure_sat = ensure_sat
        self.pair_writer = pair_writer
        self.last_pair = None

    def command(self, name, params="", reply=None):
        if name not in self.ALLOWED:
            raise ValueError("Command is not allowed")
        frame = field("command", name) + field("parameters", params)
        with socket.create_connection((self.host, self.port), 2) as connection:
            connection.settimeout(2)
            connection.sendall(frame.encode("ascii"))
            self.log("tcp_sent", command=name, frame=frame)
            if reply is None:
                # Keep the connection open briefly for the asynchronous server.
                time.sleep(0.06)
                return None
            data = bytearray()
            while len(data) < 65536:
                chunk = connection.recv(4096)
                if not chunk:
                    raise RuntimeError("RUMlogNG closed its reply connection")
                data.extend(chunk)
                parsed = first_field(data)
                if parsed:
                    if parsed[0].lower() != reply.lower():
                        raise RuntimeError(f"Unexpected RUMlogNG reply: {parsed[0]}")
                    self.log("tcp_report", field=parsed[0], value=parsed[1])
                    return parsed[1]
            raise RuntimeError("Oversized RUMlogNG reply")

    def apply(self, pair, force=False):
        old = None if force else self.last_pair
        changing_mode = old is None or (old.rx_mode, old.tx_mode, old.tx_tone_hz, old.rx_tone_hz,
                                        dial_band(old.rx_hz),dial_band(old.tx_hz)) != (
            pair.rx_mode, pair.tx_mode, pair.tx_tone_hz, pair.rx_tone_hz,dial_band(pair.rx_hz),dial_band(pair.tx_hz))
        if self.pair_writer is None and any(t is not None for t in (pair.tx_tone_hz, pair.rx_tone_hz)):
            raise RuntimeError("MacDoppler tone control is unavailable; tuning is blocked")
        # Frequency-only Doppler updates may continue during operator-keyed TX.
        # Changing source/bands/modes waits until the operator releases PTT.
        if changing_mode:
            if self.command("CmdSendTx", reply="CmdTX").upper() != "OFF":
                raise BusyRadio("Release PTT before changing source or operating modes")
        if force and self.ensure_sat:
            self.ensure_sat()
        if self.pair_writer and self.pair_writer(pair, old, force):
            self.last_pair = pair
            return
        for attr, cmd in (("rx_hz", "CmdSetFreq"), ("tx_hz", "CmdSetTXFreq")):
            if old is None or getattr(old, attr) != getattr(pair, attr):
                khz = format(Decimal(getattr(pair, attr)) / 1000, ".3f")
                self.command(cmd, field("xcvrfreq", khz))
        for attr, cmd in (("rx_mode", "CmdSetMode"), ("tx_mode", "CmdSetTXMode")):
            mode = getattr(pair, attr)
            if old is None or getattr(old, attr) != mode:
                self.command(cmd, field("1", WIRE_MODES.get(mode, mode)))
        self.last_pair = pair

class Bridge:
    def __init__(self, transport_factory=None, journal=None, freshness=8.0, power_guard=None, rx_filter=None, radio_reader=None, verify_qo=False, split_controller=None):
        self.lock = threading.RLock()
        # Source changes and writes share this lock. On return from a source
        # switch, no old source can still write, including an in-flight update.
        self.dispatch = threading.RLock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.source = "qo100"
        self.enabled = False
        self.epoch = 0
        self.pending = None
        self.qo_pair = None
        self.qo_verified = False
        self.qo_name = "No QO-100 preset selected"
        self.latest = None
        self.latest_at = None
        self.satellite = "Waiting for MacDoppler"
        self.channel = ""
        self.received = self.ignored = self.rejected = self.applied = 0
        self.applied_epoch = None
        self.last_sent = None
        self.last_sent_source = None
        self.last_sent_at = None
        self.status = "Output paused — select a source to begin"
        self.error = ""
        self.input_error = ""
        self.power_guard = power_guard
        self.power_percent = None
        self.power_error = ""
        self.power_checked_at = None
        self.power_recovery_epoch = None
        self.power_recovery_apply = False
        self.radio_reader = radio_reader
        self.verify_qo = verify_qo
        self.radio = None
        self.radio_seen_at = None
        self.radio_error = ""
        self.rx_filter = rx_filter
        self.rx_filter_number = None
        self.split_controller = split_controller
        self.split_base_tx_hz = None
        self.split_offset_hz = 0
        self.split_error = ""
        self.split_pending_offset_hz = None
        self.freshness = freshness
        self.events = deque(maxlen=160)
        self.journal = Path(journal) if journal else None
        self.journal_handler = RotatingFileHandler(self.journal, maxBytes=5_000_000, backupCount=3, encoding="utf-8", delay=True) if self.journal else None
        self.sock = None
        self.threads = []
        self.transport = transport_factory(self.log) if transport_factory else Transport(self.log)

    def log(self, kind, **details):
        event = {"utc": utc(), "kind": kind, **details}
        with self.lock:
            self.events.append(event)
            if self.journal_handler:
                record = logging.LogRecord("satellite_bridge", logging.INFO, "", 0, json.dumps(event), (), None)
                self.journal_handler.emit(record)

    def start(self, host="127.0.0.1", port=9932):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Exclusive bind: do not steal packets from another receiver.
            sock.bind((host, port))
            sock.settimeout(0.3)
        except Exception:
            sock.close()
            raise
        self.sock = sock
        self.udp_address = sock.getsockname()
        targets = [self._receive, self._worker]
        if self.power_guard or self.radio_reader:
            targets.append(self._power_worker)
        for target in targets:
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)
        self.log("started", udp=self.udp_address, source=self.source, enabled=False)

    def ingest(self, payload, peer="127.0.0.1"):
        text = payload.decode("utf-8", "strict") if isinstance(payload, bytes) else payload
        if len(text) > 8192:
            raise ValueError("Oversized UDP report")
        if "[New Satellite Status Report:" in text:
            match = re.search(r"SatName:(.*?)\s+channelName:(.*?)\]", text)
            if match:
                with self.lock:
                    self.satellite, self.channel = match[1], match[2]
                self.log("satellite", name=match[1], channel=match[2])
            return
        try:
            pair = parse_radio_report(text)
        except ValueError as error:
            with self.lock:
                self.rejected += 1
                self.latest = self.latest_at = None
                self.input_error = str(error)
                if self.enabled and self.source == "macdoppler":
                    self.epoch += 1
                    self.pending = None
                    self.status = "MacDoppler report rejected; holding last frequency"
            self.log("udp_rejected", error=str(error), packet=text, peer=peer)
            return
        if pair is None:
            self.log("udp_other", packet=text[:500], peer=peer)
            return
        now = time.monotonic()
        with self.lock:
            satellite = re.search(r",\s*SatName:([^,\]]+)", text, re.I)
            if satellite:
                self.satellite = satellite[1].strip()
            self.received += 1
            self.input_error = ""
            self.latest, self.latest_at = pair, now
            following = self.enabled and self.source == "macdoppler"
            if following:
                self.pending = (self.epoch, "macdoppler", pair, now, False)
                self.wake.set()
            else:
                self.ignored += 1
        self.log("udp_received", packet=text, pair=pair.view(), peer=peer, forwarded=following)

    def use_qo100(self, pair, name):
        token = self._begin_switch("Switching to QO-100; cancelling MacDoppler updates")
        with self.dispatch:
            with self.lock:
                if token != self.epoch:
                    return
                self.source, self.enabled = "qo100", True
                self.qo_pair, self.qo_name = pair, name
                self._clear_virtual_split()
                self.qo_verified = False
                self.pending = (self.epoch, "qo100", pair, time.monotonic(), True)
                self.error = ""
                self.status = "Applying QO-100 preset; MacDoppler blocked"
                self.wake.set()
            self.log("source_selected", source="qo100", name=name, pair=pair.view(), epoch=self.epoch)

    def follow_macdoppler(self):
        token = self._begin_switch("Switching to MacDoppler")
        with self.dispatch:
            with self.lock:
                if token != self.epoch:
                    return
                self.source, self.enabled = "macdoppler", True
                self._clear_virtual_split()
                self.pending = None
                self.error = ""
                self.status = "Waiting for a fresh MacDoppler radio packet"
                self.transport.last_pair = None
                if self.latest_at is not None and time.monotonic() - self.latest_at <= self.freshness:
                    self.pending = (self.epoch, "macdoppler", self.latest, self.latest_at, True)
                    self.wake.set()
            self.log("source_selected", source="macdoppler", epoch=self.epoch)

    def _clear_virtual_split(self):
        # The newly selected source/preset supplies the next TX target.
        # Do not send a separate restore of the previous source's base.
        self.split_base_tx_hz, self.split_offset_hz, self.split_error = None, 0, ""
        self.split_pending_offset_hz = None

    def set_virtual_split(self, offset_hz):
        if type(offset_hz) is not int or offset_hz not in (0,1000,2000,3000,5000,10000,15000):
            raise ValueError("Invalid virtual split offset")
        with self.dispatch:
            with self.lock:
                if self.source != "qo100" or self.qo_pair is None:
                    raise RuntimeError("Virtual split is available in QO-100 only")
                if offset_hz and (not self.enabled or self.pending is not None or self.applied_epoch != self.epoch):
                    raise RuntimeError("Apply the QO-100 pair before enabling virtual split")
                if offset_hz == 0 and self.split_base_tx_hz is None:
                    self.split_error = ""
                    return
                if self.split_controller is None:
                    raise RuntimeError("TX split control is unavailable")
                epoch, base = self.epoch, self.split_base_tx_hz
                self.split_pending_offset_hz = offset_hz
            def remember_base(hz):
                with self.lock:
                    if epoch != self.epoch or self.source != "qo100":
                        raise RuntimeError("Virtual split cancelled by a source change")
                    # Retain the recovery frequency even if verification
                    # fails after the TX-only command has been sent.
                    if self.split_base_tx_hz is None:
                        self.split_base_tx_hz = hz
            try:
                self._check_power()
                proof = self.split_controller(base, offset_hz, remember_base)
                self._check_power()
                with self.lock:
                    if epoch != self.epoch or self.source != "qo100":
                        return
                    self.split_offset_hz, self.split_error = offset_hz, ""
                    if offset_hz == 0:
                        self.split_base_tx_hz = None
                self._read_radio()
                self.log("virtual_split_applied", offset_hz=offset_hz, **proof)
            except Exception as error:
                with self.lock:
                    self.split_error = str(error)
                self.log("virtual_split_error", error=str(error), base_tx_hz=self.split_base_tx_hz)
                raise
            finally:
                with self.lock:
                    if epoch == self.epoch:
                        self.split_pending_offset_hz = None

    def pause(self):
        token = self._begin_switch("Pausing output")
        with self.dispatch:
            with self.lock:
                if token != self.epoch:
                    return
                self.enabled = False
                self.pending = None
                self.status = "Output paused — incoming packets cannot tune the radio"
            self.log("paused", epoch=self.epoch)

    def _begin_switch(self, status):
        # Invalidate queued work before waiting for the one in-flight write.
        # Do not hold the state lock while waiting for the dispatch lock.
        with self.lock:
            self.epoch += 1
            self.power_recovery_epoch = None
            self.power_recovery_apply = False
            self.enabled = False
            self.pending = None
            self.split_pending_offset_hz = None
            self.status = status
            return self.epoch

    def snapshot(self):
        with self.lock:
            age = None if self.latest_at is None else time.monotonic() - self.latest_at
            return {"source": self.source, "enabled": self.enabled, "qo_name": self.qo_name,
                    "qo_pair": self.qo_pair.view() if self.qo_pair else None,
                    "latest": self.latest.view() if self.latest else None, "age": age,
                    "satellite": self.satellite, "channel": self.channel,
                    "received": self.received, "ignored": self.ignored, "rejected": self.rejected, "applied": self.applied,
                    "last_sent": self.last_sent.view() if self.last_sent else None,
                    "last_sent_source": self.last_sent_source, "last_sent_at": self.last_sent_at,
                    "power_percent": self.power_percent, "power_error": self.power_error,
                    "power_checked_at": self.power_checked_at,
                    "power_retrying": self.power_recovery_epoch == self.epoch,
                    "radio": dict(self.radio) if self.radio else None,
                    "radio_age": time.monotonic() - self.radio_seen_at if self.radio_seen_at is not None else None,
                    "radio_error": self.radio_error,
                    "rx_filter_number": self.rx_filter_number,
                    "virtual_split": {"offset_hz":self.split_offset_hz,"base_tx_hz":self.split_base_tx_hz,"error":self.split_error,
                                      "pending_offset_hz":self.split_pending_offset_hz,
                                      "available":self.source=='qo100' and self.enabled and self.applied_epoch==self.epoch and self.pending is None},
                    "power_cap_active": self.source == "qo100" and self.qo_pair is not None,
                    "input_error": self.input_error,
                    "packets": [e for e in self.events if e["kind"] in ("udp_received", "udp_rejected", "udp_other") and "packet" in e][-30:],
                    "status": self.status, "error": self.error, "events": list(self.events)[-12:]}

    def _check_power(self, force=False):
        try:
            if self.power_guard is None:
                raise RuntimeError("QO-100 power control is unavailable; tuning is blocked")
            percent = self.power_guard(force=force)
            if not 0 <= percent <= 5:
                raise RuntimeError(f"QO-100 power exceeds 5%: {percent:g}%")
        except Exception as error:
            with self.lock:
                self.power_percent = None
                self.power_error = str(error)
            raise PowerUnavailable(str(error)) from error
        with self.lock:
            self.power_percent = percent
            self.power_error = ""
            self.power_checked_at = utc()

    def _hold_for_power(self, error, retry_apply=None):
        message = str(error)
        with self.lock:
            already_retrying = self.power_recovery_epoch == self.epoch
            if retry_apply is None:
                retry_apply = not already_retrying and self.applied_epoch != self.epoch
            if self.enabled and not already_retrying:
                self.epoch += 1
                self.power_recovery_epoch = self.epoch
                self.power_recovery_apply = retry_apply
            elif already_retrying:
                self.power_recovery_apply = self.power_recovery_apply or retry_apply
            changed = self.error != message
            self.enabled = False
            self.pending = None
            self.error = self.power_error = message
            self.status = "Power feedback unavailable — holding tuning and retrying"
        if changed or not already_retrying:
            self.log("power_error", error=message, automatic_retry=True)

    def _recover_power(self, previous_error):
        with self.lock:
            if self.source == "qo100" and self.power_recovery_epoch == self.epoch:
                retry_apply = self.power_recovery_apply
                self.power_recovery_epoch = None
                self.power_recovery_apply = False
                self.enabled = True
                self.error = ""
                if retry_apply:
                    self.pending = (self.epoch, "qo100", self.qo_pair, time.monotonic(), True)
                    self.status = "Power verified — applying the selected QO-100 pair"
                    self.wake.set()
                else:
                    # Do not retune an already-applied pair: the operator may
                    # have moved the radio's dial while its display was held.
                    self.status = self._qo_status()
                    self.applied_epoch = self.epoch
                self.log("power_recovered", resumed=True, reapply=retry_apply)
            elif previous_error and self.error == previous_error:
                self.error = ""

    def _read_radio(self):
        if not self.radio_reader:
            return
        try:
            radio = self.radio_reader()
            with self.lock:
                old = self.radio or {}
                changed = any(old.get(k) != radio.get(k) for k in ("rx_hz", "tx_hz", "rx_mode", "tx_mode"))
                self.radio = dict(radio)
                self.radio_seen_at = radio.get("monotonic_at", time.monotonic())
                self.radio_error = ""
            if changed:
                self.log("radio_feedback", **{k:radio.get(k) for k in ("rx_hz", "tx_hz", "rx_mode", "tx_mode")})
            return radio
        except Exception as error:
            with self.lock:
                self.radio_error = str(error)

    def _qo_status(self):
        return "QO-100 active — MacDoppler blocked" if self.qo_verified else "QO-100 selected — readback differs; manual tuning allowed"

    def _confirm_qo_pair(self, pair, epoch):
        """Read-only confirmation after the single preset command batch.

        RUMlogNG can display a requested TX frequency before its next CAT
        poll reports the old value. A successful setter is not confirmation.
        Verification never sends a frequency/mode command. Subsequent
        manual tuning is never pulled back to a preset.
        """
        start = time.monotonic()
        matched_since = None
        expected = {"rx": pair.rx_hz, "tx": pair.tx_hz}
        with self.lock:
            self.status = "Verifying QO-100 frequencies; MacDoppler blocked"
        while time.monotonic() - start < 7:
            with self.lock:
                if epoch != self.epoch or not self.enabled or self.source != "qo100":
                    return False
            self._check_power()
            radio = self._read_radio() or {}
            now = time.monotonic()
            fresh = now - radio.get("monotonic_at", now) <= .5
            matches = fresh and all(radio.get(side + "_hz") == hz for side, hz in expected.items())
            matches = matches and all(radio.get(side + "_mode") in (None, mode) for side, mode in (("rx", pair.rx_mode), ("tx", pair.tx_mode)))
            if matches:
                matched_since = now if matched_since is None else matched_since
                if now - start >= 2 and now - matched_since >= .8:
                    self.log("qo_frequencies_verified", pair=pair.view(), seconds=round(now-start, 3))
                    return True
            else:
                matched_since = None
            if self.stop_event.wait(.15):
                return False
        self.log("qo_readback_differs", requested=pair.view(), reported=radio, automatic_retune=False)
        return None

    def _power_worker(self):
        while not self.stop_event.wait(1):
            with self.dispatch:
                with self.lock:
                    active = self.source == "qo100" and self.qo_pair is not None
                if not active:
                    self._read_radio()
                    continue
                previous_error = self.power_error
                try:
                    self._check_power()
                except PowerUnavailable as error:
                    self._hold_for_power(error)
                else:
                    self._recover_power(previous_error)
                self._read_radio()

    def _receive(self):
        while not self.stop_event.is_set():
            try:
                data, peer = self.sock.recvfrom(8193)
                self.ingest(data, peer[0])
            except socket.timeout:
                continue
            except (ValueError, UnicodeError) as error:
                self.log("udp_rejected", error=str(error))
            except OSError:
                if not self.stop_event.is_set():
                    self.log("udp_error", error="UDP receiver closed unexpectedly")
                break

    def _worker(self):
        while not self.stop_event.is_set():
            self.wake.wait(0.2)
            self.wake.clear()
            with self.lock:
                task, self.pending = self.pending, None
            if task is None:
                continue
            epoch, source, pair, received_at, force = task
            with self.dispatch:
                with self.lock:
                    if not self.enabled or epoch != self.epoch or source != self.source:
                        self.log("cancelled", source=source, epoch=epoch)
                        continue
                    if source == "macdoppler" and time.monotonic() - received_at > self.freshness:
                        self.status = "MacDoppler packet expired; holding last frequency"
                        self.log("expired", source=source)
                        continue
                commands_sent = False
                try:
                    filter_number = RX_FILTERS.get(pair.rx_mode)
                    if filter_number is not None and self.rx_filter is None:
                        raise RuntimeError("RX filter control is unavailable; tuning is blocked")
                    if source == "qo100":
                        self._check_power(force=True)
                    self.transport.apply(pair, force=force or self.transport.last_pair is None)
                    commands_sent = True
                    with self.lock:
                        self.last_sent, self.last_sent_source, self.last_sent_at = pair, source, utc()
                    confirmed = True
                    if filter_number is not None:
                        if self.rx_filter(pair.rx_mode, filter_number) != filter_number:
                            raise RuntimeError("RX filter did not verify")
                    if source == "qo100":
                        # A new TX band or mode may recall a different power.
                        # Do not show QO-100 active until the cap is rechecked.
                        self._check_power(force=True)
                        self._read_radio()
                        if self.verify_qo:
                            confirmed = self._confirm_qo_pair(pair, epoch)
                            if confirmed is False:
                                continue
                    with self.lock:
                        self.applied += 1
                        self.rx_filter_number = filter_number
                        if epoch == self.epoch and self.enabled and source == self.source:
                            self.applied_epoch = epoch
                            if source == "qo100":
                                self.qo_verified = confirmed is True
                            self.error = ""
                            self.status = self._qo_status() if source == "qo100" else "Following MacDoppler"
                    self.log("pair_applied", source=source, pair=pair.view(), epoch=epoch)
                except PowerUnavailable as error:
                    self._hold_for_power(error, retry_apply=not commands_sent)
                    self.transport.last_pair = None
                except BusyRadio as error:
                    with self.lock:
                        self.status = str(error)
                        # Keep the newest packet, not the older deferred one.
                        if self.pending is None:
                            self.pending = task
                    self.stop_event.wait(0.3)
                    self.wake.set()
                except Exception as error:
                    with self.lock:
                        self.enabled = False
                        self.epoch += 1
                        self.pending = None
                        self.error = str(error)
                        self.status = "Output paused after an error"
                    self.transport.last_pair = None
                    self.log("output_error", error=str(error))

    def close(self):
        self.pause()
        self.stop_event.set()
        self.wake.set()
        if self.sock:
            self.sock.close()
        for thread in self.threads:
            thread.join(timeout=3)
        if self.journal_handler:
            self.journal_handler.close()
