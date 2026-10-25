# Development

## Runtime and build

The production code uses the Python standard library, Tk, CoreFoundation and macOS ApplicationServices. Native Accessibility calls use `ctypes`; no third-party Python package is needed to run from source when a suitable Python/Tk environment is already installed.

The tested bundled runtime is **Python 3.12.14 / Tcl-Tk 9.0.4, x86_64**. The builder requires Python 3.12 or later and Tk 9. The older Python 3.9 / Tk 8.6.8 combination produced blank windows on the original macOS 15.7.3 machine and is not a supported build environment for this release.

```sh
python3 -c 'import sys, tkinter; print(sys.version); print("Tk", tkinter.TkVersion)'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-build.txt
python build_macos_app.py
```

The build uses Apple's command-line tools, generates its icon, invokes PyInstaller, and verifies the local signature. Output: `dist/Satellite Bridge.app`. It does not install the app or tune the radio.

The supplied spec targets Intel. A native Apple Silicon build needs an appropriate runtime/spec and separate live validation. The bundle's declared minimum OS is not a claim that all those systems were tested.

To run the source UI: `python bridge_app.py`. Running the real UI can select Digital and tune the radio once, so use isolated data and simulated endpoints for automated development.

## Tests

```sh
python -m unittest test_bridge test_app_packaging test_native_control -v
```

The 50 tests exercise parsers, independent setters, source arbitration, TCP frames, PTT restrictions, persistence, startup, native-control models, readback, one-shot behavior and power recovery. They bind temporary loopback sockets and do not connect to the IC-9700. The test modules import macOS native frameworks, so this test command targets macOS.

## Source map

| File | Responsibility |
| --- | --- |
| `bridge_core.py` | Pair model, report parser, source ownership, command transport, one-shot verification and power recovery |
| `bridge_app.py` | Tk operating UI, pair editor, startup and native-control wiring |
| `macos_ax.py` | Small native macOS Accessibility wrapper |
| `rumlog_panel.py` | RUMlogNG panel readback, SAT, power and RX-filter controls |
| `bridge_paths.py` | Data placement, first-launch defaults and instance ownership |
| `bridge_rpc.py`, `bridge_ctl.py` | User-only local UI control socket and CLI |
| `rumlog_test.py` | Commander frame helpers shared by the runtime and an optional live diagnostic CLI |
| `rumlog_filter.py`, `rumlog_ui.py` | Legacy AppleScript helpers retained for regression tests; not the app's production control backend |

The optional CLI diagnostic modules can affect a real station when explicitly invoked. Unit tests do not invoke their live entry points.

## Commands and ordering

The transport uses `CmdSetFreq`, `CmdSetTXFreq`, `CmdSetMode` and `CmdSetTXMode`; frequency payloads are kHz. USB-D/LSB-D map to DATA-U/DATA-L on this interface. `CmdSendTx` is used as a PTT-status query, not as a transmit command.

Source changes invalidate stale work before waiting for in-flight dispatch to finish. The UDP receiver retains only the latest pending MacDoppler report and requires fresh data. QO-100 sends one batch per selection and never retries frequency setters automatically. Power recovery can release a pending selection that has not sent any tuning commands yet; it never replays an already-sent batch.

Use `SATELLITE_BRIDGE_DATA_DIR` for isolated development data. Do not start a second real bridge on UDP 9932. No source file should hard-code a local user's serial-device path or private account details.

## Release handling

Publish the existing validated app without replacing the installed running copy. ZIP with `ditto -c -k --sequesterRsrc --keepParent` so macOS bundle attributes are retained. Verify the extracted app signature and publish SHA-256 checksums. Include runtime licenses as separate notices; the bridge's MIT license does not replace those licenses.

The PDF can be rebuilt with `python tools/build_guide.py` after installing `requirements-docs.txt`. That command creates documentation only and does not connect to the radio.
