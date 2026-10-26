"""Fast native access to the IC-9700 panel owned by RUMlogNG."""

import math
import re
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from bridge_core import normalize_mode, tone_hz, virtual_split_target, dial_band
from macos_ax import AXError, Element, application, focused_application, session_locked


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
        self._polling_before_tracking = None

    def invalidate(self):
        self._app = self._window = self._power = None
        self._groups.clear()
        self._buttons.clear()
        self._texts.clear()

    def window(self):
        self.require_session()
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

    def require_session(self):
        if isinstance(self._app,Element) and session_locked():
            raise RuntimeError("Unlock the Mac to allow IC-9700 panel control")

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
        # Alternating polling can select a different VFO between a Doppler
        # setter and its feedback. During continuous output the writer owns
        # VFO selection; the background reader must not turn Toggle back on.
        if self._polling_before_tracking is not None:
            return
        if self.description("Miscellaneous", "Toggle") == OFF:
            self.press("Miscellaneous", "Toggle")

    def release_tracking_polling(self):
        """Restore the pre-tracking polling choice when the app closes."""
        with self.lock:
            previous = self._polling_before_tracking
            if previous is None:
                return
            if previous and self.description("Miscellaneous", "Toggle") != ON:
                self.press("Miscellaneous", "Toggle")
                self.wait(lambda: self.description("Miscellaneous", "Toggle") == ON, "restore alternating polling")
            self._polling_before_tracking = None

    def power_slider(self):
        self.require_session()
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
            self.require_session()
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
            raise ValueError("Unsupported RX filter rule")
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
                    if self.description("VFO", "Main") != ON or self.description("VFO", "Sub") != OFF:
                        raise RuntimeError("Select only Main/RX before setting its filter")
                    self.press("Mode", f"Fi. {number}")
                self.wait(lambda: band_fields(self.fields("VFO Main Band (RX)"))["filter"] == number, "RX filter readback")
                return number
            finally:
                if was_sub:
                    self.press("VFO", "Sub")
                    self.wait(lambda: self.description("VFO", "Sub") == ON, "restore Sub view")
                if was_toggling:
                    self.press("Miscellaneous", "Toggle")

    def set_selected_mode(self, band, mode, check_rx=lambda: None):
        buttons = {"USB": "USB", "USB-D": "USB", "LSB": "LSB", "LSB-D": "LSB",
                   "CW": "CW", "CW-R": "CW R", "RTTY": "RY", "RTTY-R": "RY R", "FM": "FM", "AM": "AM"}
        if mode not in buttons:
            raise ValueError("Unsupported satellite mode")
        other = "Sub" if band == "Main" else "Main"
        if self.description("VFO", band) != ON or self.description("VFO", other) != OFF:
            raise RuntimeError(f"Select only {band} before setting its mode")
        button = buttons[mode]
        if self.description("Mode", button) != ON:
            check_rx()
            self.press("Mode", button)
            self.wait(lambda: self.description("Mode", button) == ON, f"{band} {button}")
        if mode in ("USB", "USB-D", "LSB", "LSB-D"):
            self.wait(lambda: self.description("Mode", "Data") in (ON, OFF), f"{band} Data feedback")
            wanted = ON if mode.endswith("-D") else OFF
            if self.description("Mode", "Data") != wanted:
                check_rx()
                self.press("Mode", "Data")
            self.wait(lambda: self.description("Mode", "Data") == wanted, f"{band} Data state")
        self.wait(lambda: self.selected_mode(band) == mode, f"{band} mode {mode}")

    def select_vfo(self, band):
        other = "Sub" if band == "Main" else "Main"
        self.press("VFO", band)
        stable_since = None
        deadline = time.monotonic() + 3
        while True:
            now = time.monotonic()
            selected = self.description("VFO", band) == ON and self.description("VFO", other) == OFF
            if selected:
                stable_since = now if stable_since is None else stable_since
                if now - stable_since >= .25:
                    return
            else:
                stable_since = None
            if now >= deadline:
                raise RuntimeError(f"IC-9700 feedback timed out: stable {band} selection")
            time.sleep(.04)

    def tone_popup(self, kind):
        if kind not in ("Tone", "TSQL"):
            raise ValueError("Unknown tone control")
        popups = [c for c in self.group("Miscellaneous").children if c.get("AXRole") == "AXPopUpButton"]
        if len(popups) != 2:
            raise RuntimeError("IC-9700 tone frequency controls are unavailable")
        return popups[0 if kind == "Tone" else 1]

    def focus_for_menu(self):
        self.window()
        if self._app.get("AXFrontmost"):
            return None
        try:
            previous = focused_application()
        except AXError:
            previous = None
        self._app.set_boolean("AXFrontmost",True)
        self.wait(lambda:self._app.get("AXFrontmost") is True,"foreground tone menu")
        return previous

    @staticmethod
    def restore_menu_focus(previous):
        if previous is not None:
            try:
                previous.set_boolean("AXFrontmost",True)
            except AXError:
                # App focus restoration cannot undo a verified tone change.
                pass

    def set_selected_tone(self, band, kind, hz, check_rx=lambda: None):
        """Set a tone on one explicitly selected VFO through the panel."""
        if band not in ("Main", "Sub") or kind not in ("Tone", "TSQL"):
            raise ValueError("Unknown tone target")
        hz = tone_hz(hz)
        if hz is None:
            return None

        def check_target():
            other = "Sub" if band == "Main" else "Main"
            if self.description("VFO", band) != ON or self.description("VFO", other) != OFF:
                raise RuntimeError(f"Select only {band} before setting its tone")
            if hz and self.selected_mode(band) != "FM":
                raise RuntimeError(f"Verify {band} FM mode before enabling a tone")

        def before_write():
            check_rx()
            check_target()

        check_target()
        if hz:
            popup = self.tone_popup(kind)
            wanted = f"{hz:.1f} Hz"
            if popup.get("AXValue") != wanted:
                before_write()
                previous_focus = self.focus_for_menu()
                menu = None
                selected = False
                try:
                    before_write()
                    popup.press()
                    def opened():
                        nonlocal menu
                        menu = next((c for c in popup.children if c.get("AXRole") == "AXMenu"), None)
                        return menu is not None
                    self.wait(opened, f"{kind} frequency menu")
                    choices = [c for c in menu.children if c.get("AXTitle") == wanted]
                    if len(choices) != 1:
                        raise RuntimeError(f"IC-9700 does not offer {wanted}")
                    before_write()
                    choices[0].press()
                    selected = True
                finally:
                    if menu is not None and not selected:
                        menu.cancel()
                    self.restore_menu_focus(previous_focus)
                self.wait(lambda: popup.get("AXValue") == wanted, f"{kind} frequency {wanted}")
        wanted_state = ON if hz else OFF
        check_target()
        self.wait(lambda: self.description("Miscellaneous", kind) in (ON, OFF), f"{kind} state")
        if self.description("Miscellaneous", kind) != wanted_state:
            before_write()
            self.press("Miscellaneous", kind)
        self.wait(lambda: self.description("Miscellaneous", kind) == wanted_state, f"{kind} enable state")
        if hz:
            self.wait(lambda: self.tone_popup(kind).get("AXValue") == f"{hz:.1f} Hz", f"{kind} frequency feedback")
        check_target()
        return hz

    def apply_satellite_pair(self, pair, previous, set_frequency, check_rx, log, continuous=False, rx_profile=None):
        """Apply changed satellite fields through explicitly selected SAT VFOs.

        RUMlogNG 6.6's TX Commander setters no longer address the SAT Sub
        VFO reliably. Its ordinary frequency setter and panel mode buttons
        do, once alternating polling is stopped and the VFO is selected.
        """
        with self.lock:
            self.require_session()
            if not self.sat_on():
                raise RuntimeError("SAT must be on for satellite pair control")
            check_rx()
            was_toggling = self.description("Miscellaneous", "Toggle") == ON
            first_tracking_update = continuous and self._polling_before_tracking is None
            if first_tracking_update:
                self._polling_before_tracking = was_toggling
            restore_toggling = (self._polling_before_tracking if self._polling_before_tracking is not None
                                else was_toggling) if not continuous else False
            if was_toggling:
                self.press("Miscellaneous", "Toggle")
                self.wait(lambda: self.description("Miscellaneous", "Toggle") == OFF, "stop alternating polling")
            if continuous and (first_tracking_update or was_toggling):
                # Let the last alternating poll finish before selecting a
                # VFO for the first stream update. Later updates keep it off.
                time.sleep(.8)
            was_sub = self.description("VFO", "Sub") == ON
            verified = {}
            try:
                for side, band, group in (("rx", "Main", "VFO Main Band (RX)"),
                                          ("tx", "Sub", "VFO Sub Band (TX)")):
                    hz, mode = getattr(pair, side + "_hz"), getattr(pair, side + "_mode")
                    frequency_changed = previous is None or getattr(previous, side + "_hz") != hz
                    mode_changed = previous is None or getattr(previous, side + "_mode") != mode
                    tone = getattr(pair, side + "_tone_hz")
                    tone_changed = tone is not None and (previous is None or mode_changed or getattr(previous, side + "_tone_hz") != tone)
                    if not (frequency_changed or mode_changed or tone_changed):
                        continue
                    check_rx()
                    self.select_vfo(band)
                    if frequency_changed:
                        check_rx()
                        set_frequency(hz)
                    self.wait(lambda: band_fields(self.fields(group))["hz"] == hz, f"{side.upper()} frequency")
                    if mode_changed or tone_changed:
                        check_rx()
                        # Frequency updates can change the selected VFO.
                        self.select_vfo(band)
                    if mode_changed:
                        self.set_selected_mode(band, mode, check_rx)
                    if tone_changed:
                        kind = "Tone" if side == "tx" else "TSQL"
                        actual_tone = self.set_selected_tone(band, kind, tone, check_rx)
                        verified[side + "_tone_hz"] = actual_tone
                        log("sat_tone_verified", side=side, control=kind, hz=actual_tone, enabled=bool(actual_tone))
                    if side=='rx' and rx_profile is not None and (previous is None or mode_changed or
                            dial_band(previous.rx_hz)!=dial_band(pair.rx_hz)):
                        verified['rx_frontend']=self.set_rx_frontend(rx_profile,hz,check_rx)
                        log('rx_frontend_applied',**verified['rx_frontend'])
                    self.wait(lambda: band_fields(self.fields(group))["hz"] == hz, f"{side.upper()} frequency")
                    verified[side + "_hz"] = band_fields(self.fields(group))["hz"]
                    verified[side + "_mode"] = self.selected_mode(band)
                    log("sat_vfo_verified", side=side, band=band, hz=verified[side + "_hz"], mode=verified[side + "_mode"])
                return verified
            finally:
                restore = "Sub" if was_sub else "Main"
                if self.description("VFO", restore) != ON:
                    self.press("VFO", restore)
                    self.wait(lambda: self.description("VFO", restore) == ON, "restore control view")
                if restore_toggling and self.description("Miscellaneous", "Toggle") != ON:
                    self.press("Miscellaneous", "Toggle")
                    self.wait(lambda: self.description("Miscellaneous", "Toggle") == ON, "restore alternating polling")
                if not continuous:
                    self._polling_before_tracking = None

    def sat_on(self):
        with self.lock:
            return self.description("Miscellaneous", "SAT") == ON

    def set_rx_frontend(self, source, rx_hz, check_rx):
        if source not in ('qo100','macdoppler'):
            raise ValueError('Unknown receiver profile')
        from rumlog_macros import ensure_frontend_macros
        check_rx()
        ensure_frontend_macros(self)
        self.select_vfo('Main')
        def target():
            if self.description('VFO','Main')!=ON or self.description('VFO','Sub')!=OFF:
                raise RuntimeError('Select only Main/RX before changing receiver settings')
            if band_fields(self.fields('VFO Main Band (RX)'))['hz']!=rx_hz:
                raise RuntimeError('RX frequency changed before applying receiver settings')
        target()
        wanted_att=ON if source=='qo100' else OFF
        if source=='macdoppler':
            self.wait(lambda:self.description('Miscellaneous','ATT') in (ON,OFF),'RX ATT feedback')
            if self.description('Miscellaneous','ATT')!=wanted_att:
                check_rx();target();self.press('Miscellaneous','ATT')
                self.wait(lambda:self.description('Miscellaneous','ATT')==wanted_att,'RX ATT off')
        external=source=='macdoppler' and dial_band(rx_hz)==70
        name='SB RX Off' if source=='qo100' else 'SB RX Ext' if external else 'SB RX Int'
        check_rx();target();self.press('IC-9700 Macros',name)
        wanted_pre=OFF if source=='qo100' else ON
        self.wait(lambda:self.description('Miscellaneous','PRE')==wanted_pre,'RX preamp feedback')
        if self.description('Miscellaneous','ATT')!=wanted_att:
            check_rx();target();self.press('Miscellaneous','ATT')
        self.wait(lambda:self.description('Miscellaneous','ATT')==wanted_att,'RX ATT profile')
        target()
        return {'source':source,'rx_band':dial_band(rx_hz),'att_on':source=='qo100',
                'internal_preamp_on':source=='macdoppler','external_preamp_commanded':external}

    def apply_virtual_split(self, base_hz, offset_hz, remember_base, set_frequency, check_rx):
        """One TX-only change, using the actual radio frequency as its base."""
        with self.lock:
            check_rx()
            if not self.sat_on():
                raise RuntimeError("QO-100 SAT mode is required for virtual split")
            was_toggling = self.description("Miscellaneous", "Toggle") == ON
            was_sub = self.description("VFO", "Sub") == ON
            if was_toggling:
                self.press("Miscellaneous", "Toggle")
                self.wait(lambda:self.description("Miscellaneous", "Toggle") == OFF,"stop alternating polling")
                time.sleep(.8)
            try:
                self.select_vfo("Sub")
                current = band_fields(self.fields("VFO Sub Band (TX)"))
                mode = self.selected_mode("Sub")
                rx_hz = band_fields(self.fields("VFO Main Band (RX)"))["hz"]
                if current["hz"] is None or rx_hz is None or mode is None:
                    raise RuntimeError("Fresh RX/TX frequency and TX mode feedback are required for split")
                base = current["hz"] if base_hz is None else base_hz
                target = virtual_split_target(base,offset_hz,mode)
                remember_base(base)
                check_rx()
                if self.description("VFO","Sub") != ON or self.description("VFO","Main") != OFF:
                    raise RuntimeError("Select only Sub/TX before applying virtual split")
                set_frequency(target)
                stable = [None]
                def verified():
                    now = time.monotonic()
                    matches = (band_fields(self.fields("VFO Sub Band (TX)"))["hz"] == target
                               and band_fields(self.fields("VFO Main Band (RX)"))["hz"] == rx_hz
                               and self.selected_mode("Sub") == mode)
                    stable[0] = (now if stable[0] is None else stable[0]) if matches else None
                    return stable[0] is not None and now-stable[0]>=.8
                self.wait(verified,"TX virtual split and unchanged RX",timeout=4)
                return {"base_tx_hz":base,"tx_hz":target,"rx_hz":rx_hz,"tx_mode":mode}
            finally:
                restore = "Sub" if was_sub else "Main"
                if self.description("VFO",restore) != ON:
                    self.press("VFO",restore)
                    self.wait(lambda:self.description("VFO",restore) == ON,"restore control view")
                if was_toggling and self.description("Miscellaneous","Toggle") != ON:
                    self.press("Miscellaneous","Toggle")
                    self.wait(lambda:self.description("Miscellaneous","Toggle") == ON,"restore alternating polling")

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

    def set_default(self, percent, check_rx=lambda:None):
        if type(percent) is not int or not 0<=percent<=100:
            raise ValueError("Invalid power default")
        with self.panel.lock:
            check_rx()
            self.panel.power_slider().set_number(percent)
            time.sleep(.3)
            # CI-V's 0..255 scale can display one percent below a request.
            self.panel.wait(lambda:percent-1<=self.panel.read_power()<=percent,"TX power default",timeout=3)
            self.last_feedback=self.panel.snapshot(require_power=True)
            self.log("power_default_applied",requested_percent=percent,reported_percent=self.last_feedback["power_percent"])
            return self.last_feedback["power_percent"]

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
