"""Fast native access to the IC-9700 panel owned by RUMlogNG."""

import math
import re
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from bridge_core import normalize_mode
from macos_ax import AXError, application


ON = "available"
OFF = "no availability status"
VFO_GROUP_NAMES = {
    "VFO Main Band (RX)": ("VFO Main Band (RX)", "VFO Main (RX)"),
    "VFO Sub Band (TX)": ("VFO Sub Band (TX)", "VFO Sub (TX)"),
}


def frequency_hz(text):
    try:
        value = Decimal(str(text).strip().replace(",", "")) * 1000
        if not value.is_finite() or value != value.to_integral_value():
            return None
        value = int(value)
        return value if any(lo <= value <= hi for lo, hi in ((144000000, 148000000), (430000000, 450000000), (1240000000, 1300000000))) else None
    except (InvalidOperation, ValueError):
        return None


def band_fields(values):
    # RUMlogNG can omit the Data field from the Sub readout. Static labels
    # and placeholder text must not be mistaken for a mode or a filter.
    values = [str(value or "").strip() for value in values]
    hz = mode = number = None
    for text in values:
        if hz is None:
            hz = frequency_hz(text)
        match = re.fullmatch(r"FIL\s+([123])", text)
        if match:
            number = int(match[1])
        if mode is None:
            try:
                mode = normalize_mode(text.upper().replace(" ", "-"))
            except ValueError:
                pass
    if mode in ("USB", "LSB") and any(value.lower() == "data" for value in values):
        mode += "-D"
    return {"hz": hz, "mode": mode, "filter": number}


class RumlogPanel:
    def __init__(self):
        self.lock = threading.RLock()
        self._app = self._window = None
        self._groups, self._buttons, self._texts = {}, {}, {}
        self._power = None

    def invalidate(self):
        self._app = self._window = self._power = None
        self._groups.clear()
        self._buttons.clear()
        self._texts.clear()

    def window(self):
        if self._window is None:
            self._app = application()
            windows = self._app.get("AXWindows", [])
            self._window = next((w for w in windows if w.get("AXTitle") == "ICOM IC-9700"), None)
            if self._window is None:
                bar = self._app.get("AXMenuBar")
                transceiver = next(x for x in bar.children if x.get("AXTitle") == "Transceiver")
                menu = transceiver.children[0]
                item = next(x for x in menu.children if x.get("AXTitle") == "IC-9700 control")
                item.press()
                deadline = time.monotonic() + 2
                while self._window is None and time.monotonic() < deadline:
                    self._window = next((w for w in self._app.get("AXWindows", []) if w.get("AXTitle") == "ICOM IC-9700"), None)
                    if self._window is None:
                        time.sleep(.05)
                if self._window is None:
                    raise RuntimeError("Open Transceiver > IC-9700 control in RUMlogNG")
        return self._window

    def group(self, name):
        if name not in self._groups:
            for child in self.window().children:
                label = child.get("AXTitleUIElement")
                if label:
                    self._groups[label.get("AXValue")] = child
            # Accept the compact VFO labels while retaining the explicit
            # Main/RX and Sub/TX identities used by all tuning controls.
            for candidate in VFO_GROUP_NAMES.get(name, (name,)):
                if candidate in self._groups:
                    self._groups[name] = self._groups[candidate]
                    break
        if name not in self._groups:
            raise RuntimeError(f"IC-9700 {name} controls are not ready")
        return self._groups[name]

    def button(self, group, name):
        key = group, name
        if key not in self._buttons:
            for child in self.group(group).children:
                attrs = child.attrs("AXRole", "AXTitle")
                if attrs["AXRole"] == "AXButton":
                    self._buttons[group, attrs["AXTitle"]] = child
        if key not in self._buttons:
            raise RuntimeError(f"IC-9700 {name} button is unavailable")
        return self._buttons[key]

    def description(self, group, name):
        return self.button(group, name).get("AXDescription")

    def press(self, group, name):
        self.button(group, name).press()

    def fields(self, group):
        if group not in self._texts:
            self._texts[group] = [c for c in self.group(group).children if c.get("AXRole") == "AXStaticText"]
        return [c.get("AXValue", "") for c in self._texts[group]]

    def selected_mode(self, band):
        other = "Sub" if band == "Main" else "Main"
        def selected():
            return self.description("VFO", band) == ON and self.description("VFO", other) == OFF
        if not selected():
            return None
        modes, data = [], None
        for child in self.group("Mode").children:
            if child.get("AXRole") != "AXButton":
                continue
            attrs = child.attrs("AXTitle", "AXDescription")
            title, state = attrs["AXTitle"], attrs["AXDescription"]
            if title == "Data":
                data = state
            elif state == ON:
                title = {"RY": "RTTY", "RY R": "RTTY-R"}.get(title, title)
                try:
                    modes.append(normalize_mode(str(title).replace(" ", "-")))
                except ValueError:
                    pass
        if len(modes) != 1 or not selected():
            return None
        mode = modes[0]
        if mode in ("USB", "LSB"):
            if data not in (ON, OFF):
                return None
            if data == ON:
                mode += "-D"
        return mode

    def read_band(self, group, band):
        result = band_fields(self.fields(group))
        if result["mode"] is None:
            # Some layouts leave the readout at the literal label "Mode".
            # Use the live mode buttons only for their selected VFO; never
            # substitute the requested mode or the other band's indicators.
            result["mode"] = self.selected_mode(band)
        return result

    def wait(self, predicate, label, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise RuntimeError(f"IC-9700 feedback timed out: {label}")
            time.sleep(.04)

    def ensure_polling(self):
        if self.description("Miscellaneous", "Toggle") == OFF:
            self.press("Miscellaneous", "Toggle")

    def power_slider(self):
        if self._power is None:
            for group in self.group("Level controls").children:
                if group.get("AXRole") != "AXGroup":
                    continue
                popup = slider = None
                for child in group.children:
                    attrs = child.attrs("AXRole", "AXValue")
                    if attrs["AXRole"] == "AXPopUpButton" and attrs["AXValue"] == "RF power":
                        popup = child
                    elif attrs["AXRole"] == "AXSlider":
                        slider = child
                if popup is not None and slider is not None:
                    self._power = popup, slider
                    break
        if self._power is None:
            raise RuntimeError("RF power control is not visible in RUMlogNG")
        popup, slider = self._power
        if popup.get("AXValue") != "RF power":
            self._power = None
            raise RuntimeError("RF power control changed; retrying its lookup")
        return slider

    def read_power(self):
        percent = float(self.power_slider().get("AXValue"))
        if not math.isfinite(percent) or not 0 <= percent <= 100:
            raise RuntimeError("Invalid RF power feedback")
        return percent

    def set_power_ceiling(self):
        self.power_slider().set_number(5)

    def snapshot(self, require_power=False):
        with self.lock:
            for attempt in range(2):
                try:
                    self.ensure_polling()
                    rx = self.read_band("VFO Main Band (RX)", "Main")
                    tx = self.read_band("VFO Sub Band (TX)", "Sub")
                    try:
                        power = self.read_power()
                    except (AXError, RuntimeError):
                        if require_power:
                            raise
                        power = None
                    return {"rx_hz": rx["hz"], "tx_hz": tx["hz"], "rx_mode": rx["mode"], "tx_mode": tx["mode"],
                            "rx_filter": rx["filter"], "tx_filter": tx["filter"], "power_percent": power,
                            "sat_on": self.description("Miscellaneous", "SAT") == ON,
                            "utc": datetime.now(timezone.utc).isoformat(), "monotonic_at": time.monotonic()}
                except AXError as error:
                    self.invalidate()
                    if error.code == -25211 or attempt:
                        raise
                    time.sleep(.05)

    def select_filter(self, mode, number):
        if (mode, number) not in (("CW", 2), ("CW-R", 2), ("USB", 1), ("USB-D", 1)):
            raise ValueError("Unsupported QO-100 RX filter rule")
        with self.lock:
            # Read the dedicated RX fields first. No band selection or filter
            # click is necessary when the radio already reports the rule.
            current = self.read_band("VFO Main Band (RX)", "Main")
            if current["mode"] == mode and current["filter"] == number:
                return number
            was_toggling = self.description("Miscellaneous", "Toggle") == ON
            if was_toggling:
                self.press("Miscellaneous", "Toggle")
                self.wait(lambda: self.description("Miscellaneous", "Toggle") == OFF, "stop alternating polling")
            was_sub = self.description("VFO", "Sub") == ON
            try:
                if self.description("VFO", "Main") != ON:
                    self.press("VFO", "Main")
                self.wait(lambda: self.description("VFO", "Main") == ON, "Main/RX selection")
                self.wait(lambda: self.read_band("VFO Main Band (RX)", "Main")["mode"] == mode, "RX mode")
                if self.description("Mode", f"Fi. {number}") != ON:
                    self.press("Mode", f"Fi. {number}")
                self.wait(lambda: band_fields(self.fields("VFO Main Band (RX)"))["filter"] == number, "RX filter readback")
                return number
            finally:
                if was_sub:
                    self.press("VFO", "Sub")
                    self.wait(lambda: self.description("VFO", "Sub") == ON, "restore Sub view")
                if was_toggling:
                    self.press("Miscellaneous", "Toggle")

    def sat_on(self):
        with self.lock:
            return self.description("Miscellaneous", "SAT") == ON

    def enable_sat(self):
        with self.lock:
            if not self.sat_on():
                self.press("Miscellaneous", "SAT")
                self.wait(self.sat_on, "SAT on")


class NativePowerControl:
    def __init__(self, panel, log=None):
        self.panel, self.log = panel, log or (lambda *a, **k: None)
        self.last_feedback = None

    def read(self):
        with self.panel.lock:
            return 1, self.panel.read_power()

    def limit(self, force=False):
        with self.panel.lock:
            previous = self.last_feedback
            feedback = self.panel.snapshot(require_power=True)
            before = feedback["power_percent"]
            # Force at the boundaries of a preset change, since changing a
            # TX band/mode can recall its own RF setting. Ordinary monitoring
            # leaves an already-safe setting alone.
            if force or before > 5:
                self.panel.set_power_ceiling()
                time.sleep(.3)
                self.panel.wait(lambda: self.panel.read_power() <= 5, "RF power ceiling", timeout=2)
                feedback = self.panel.snapshot(require_power=True)
                self.log("power_limited", requested_max_percent=5, before_percent=before, reported_percent=feedback["power_percent"])
            if feedback["power_percent"] > 5:
                raise RuntimeError("RF power exceeds the 5% ceiling")
            self.last_feedback = feedback
            if force or not previous or previous.get("power_percent") != feedback["power_percent"]:
                self.log("power_verified", reported_percent=feedback["power_percent"])
            return feedback["power_percent"]

    def feedback(self):
        if self.last_feedback and time.monotonic() - self.last_feedback["monotonic_at"] < .2:
            return dict(self.last_feedback)
        self.last_feedback = self.panel.snapshot()
        return dict(self.last_feedback)


class NativeRxFilterControl:
    def __init__(self, panel, log=None):
        self.panel, self.log = panel, log or (lambda *a, **k: None)

    def select(self, mode, number):
        result = self.panel.select_filter(mode, number)
        self.log("rx_filter_selected", rx_mode=mode, filter=result, tx_filter_changed=False)
        return result
