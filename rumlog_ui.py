"""Observed RUMlogNG UI controls, including reopening its CAT panel."""

import subprocess


def ui_script(body):
    return '''tell application "System Events"
if not (exists process "RUMlogNG") then error "Open RUMlogNG before selecting a radio source."
tell process "RUMlogNG"
 if not (exists window "ICOM IC-9700") then
  click menu item "IC-9700 control" of menu 1 of menu bar item "Transceiver" of menu bar 1
  repeat 20 times
   if exists window "ICOM IC-9700" then exit repeat
   delay 0.1
  end repeat
  if not (exists window "ICOM IC-9700") then error "Open Transceiver > IC-9700 control in RUMlogNG."
 end if
''' + body + '\nend tell\nend tell'


def run_ui(body, context, timeout=5):
    result = subprocess.run(["/usr/bin/osascript", "-e", ui_script(body)], text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        detail = result.stderr.strip()
        if "assistive access" in detail or "not authorized to send Apple events" in detail:
            detail = "Allow Satellite Bridge in System Settings > Privacy & Security > Accessibility and Automation. " + detail
        raise RuntimeError(context + ": " + detail)
    return result.stdout.strip()
