"""Select only the RX IF filter in RUMlogNG's IC-9700 SAT panel."""

import time
from rumlog_ui import run_ui


WINDOW = 'window "ICOM IC-9700"'
TOGGLE = f'button "Toggle" of group "Miscellaneous" of {WINDOW}'
MODE = f'group "Mode" of {WINDOW}'
MAIN = f'button "Main" of group "VFO" of {WINDOW}'
SUB = f'button "Sub" of group "VFO" of {WINDOW}'
ON = "available"
OFF = "no availability status"


class RxFilterControl:
    def __init__(self, log=None):
        self.log = log or (lambda *args, **kwargs: None)

    def script(self, body):
        return run_ui(body, "Cannot set QO-100 RX filter")

    def wait_for(self, body, wanted, label):
        deadline = time.monotonic() + 4
        while True:
            if self.script(body) == wanted:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(f"RX filter check timed out: {label}")
            time.sleep(.15)

    def select(self, rx_mode, number):
        if (rx_mode, number) not in (("CW", 2), ("CW-R", 2), ("USB-D", 1), ("USB", 1)):
            raise ValueError("Unsupported QO-100 RX filter rule")
        description = self.script(f'return description of {TOGGLE}')
        if description not in (ON, OFF):
            raise RuntimeError("RX/TX control selection is not stable")
        was_toggling = description == ON
        # Toggle periodically polls both bands; stop it while sending the
        # selected-band filter command, then explicitly select Main/RX.
        if was_toggling:
            self.script(f'click {TOGGLE}')
            self.wait_for(f'return description of {TOGGLE}', OFF, "select RX controls")
        was_sub = self.script(f'return description of {SUB}') == ON
        try:
            if self.script(f'return description of {MAIN}') != ON:
                self.script(f'click {MAIN}')
            self.wait_for(f'return description of {MAIN}', ON, "Main/RX band")
            button = "CW R" if rx_mode == "CW-R" else "USB" if rx_mode in ("USB", "USB-D") else "CW"
            self.wait_for(f'return description of button "{button}" of {MODE}', ON, rx_mode)
            if rx_mode == "USB-D":
                self.wait_for(f'return description of button "Data" of {MODE}', ON, "USB-D data mode")
            elif rx_mode == "USB":
                self.wait_for(f'return description of button "Data" of {MODE}', OFF, "USB without data mode")
            target = f'button "Fi. {number}" of {MODE}'
            if self.script(f'return description of {target}') != ON:
                self.script(f'click {target}')
            self.wait_for(f'return description of {target}', ON, f"filter {number}")
            self.wait_for(f'return value of static text 4 of group "VFO Main Band (RX)" of {WINDOW}', f"FIL {number}", "RX filter readout")
            self.log("rx_filter_selected", rx_mode=rx_mode, filter=number, tx_filter_changed=False)
            return number
        finally:
            if was_sub:
                self.script(f'click {SUB}')
                self.wait_for(f'return description of {SUB}', ON, "restore Sub control view")
            if was_toggling:
                self.script(f'click {TOGGLE}')
                self.wait_for(f'return description of {TOGGLE}', ON, "restore TX control view")
