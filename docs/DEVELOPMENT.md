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
python -m unittest test_bridge test_app_packaging test_native_control test_virtual_split test_receiver_profiles -v
```

The 118 tests exercise parsers, independent setters, source arbitration, TCP frames, PTT restrictions, persistence, startup, native-control models, readback, one-shot behavior and power recovery. Compatibility cases cover both VFO label variants, reordered or omitted fields, placeholder modes, selected-VFO mode fallback and ambiguous indicators. They bind temporary loopback sockets and do not connect to the IC-9700. The test modules import macOS native frameworks, so this test command targets macOS.

## Source map

| File | Responsibility |
| --- | --- |
| `bridge_core.py` | Pair model, report parser, source ownership, command transport, one-shot verification and power recovery |
| `bridge_app.py` | Tk operating UI, pair editor, startup and native-control wiring |
| `macos_ax.py` | Small native macOS Accessibility wrapper |
| `rumlog_panel.py` | Selected-VFO frequency/mode/tone control, receiver profiles, TX-only virtual split, SAT, power and RX filters |
| `rumlog_macros.py` | Strict receiver-only CI-V macro provisioning and content validation; existing manual/automatic definitions preserved |
| `bridge_paths.py` | Data placement, first-launch defaults and instance ownership |
| `bridge_rpc.py`, `bridge_ctl.py` | User-only local UI control socket and CLI |
| `rumlog_test.py` | Commander frame helpers shared by the runtime and an optional live diagnostic CLI |
| `rumlog_filter.py`, `rumlog_ui.py` | Legacy AppleScript helpers retained for regression tests; not the app's production control backend |

The optional CLI diagnostic modules can affect a real station when explicitly invoked. Unit tests do not invoke their live entry points.

## Commands and ordering

For QO-100, an optional transport callback writes the pair through explicitly selected SAT VFOs. Alternating polling is stopped, Main/RX and Sub/TX are selected in turn, and each receives one `CmdSetFreq` command in kHz plus native mode-button control. Mode and frequency feedback are checked per VFO; the original control view and polling are restored. The bridge does not send `CmdSetTXFreq`, `CmdSetMode` or `CmdSetTXMode` for this QO-100 path.

MacDoppler uses the same selected-SAT-VFO writer, holding alternating polling off across the stream. Background feedback cannot re-enable it. A return to QO-100 or app close restores the prior polling setting. Mode, tone and band changes require PTT release. TX CTCSS uses the Tone popup/button on Sub; RX decode uses TSQL on Main. Foreground focus is temporarily acquired for Cocoa popup menus and restored afterward. TX power defaults to 80% only after the TX target verifies, on entry or a TX band/mode change. `CmdSendTx` is a read-only PTT query; no PTT-on or PTT-off command is implemented.

PTT is checked before selected-VFO writes. A failure after partial dispatch pauses output and does not fall back to Commander TX setters or automatically replay the pair. Tests cover independent mode/Data changes, exact VFO targeting, state restoration, PTT interruption, missing feedback and no fallback.

Source changes invalidate stale work before waiting for in-flight dispatch to finish. The UDP receiver retains only the latest pending MacDoppler report and requires fresh data. QO-100 sends one batch per selection and never retries frequency setters automatically. Power recovery can release a pending selection that has not sent any tuning commands yet; it never replays an already-sent batch.

Use `SATELLITE_BRIDGE_DATA_DIR` for isolated development data. Do not start a second real bridge on UDP 9932. No source file should hard-code a local user's serial-device path or private account details.

## Release handling

Publish the existing validated app without replacing the installed running copy. ZIP with `ditto -c -k --sequesterRsrc --keepParent` so macOS bundle attributes are retained. Verify the extracted app signature and publish SHA-256 checksums. Include runtime licenses as separate notices; the bridge's MIT license does not replace those licenses.

The PDF can be rebuilt with `python tools/build_guide.py` after installing `requirements-docs.txt`. That command creates documentation only and does not connect to the radio.

RX filters apply to both sources: CW/CW-R selects 2; USB/USB-D selects 1. Main/RX must be the only selected VFO before a filter click. Receiver settings use three exact macros in unused slots: amp off, internal only, or internal plus external 70 cm (including connector permission 0094). Payloads contain no PTT, frequency, CW or voice commands and currently use default address A2.

Virtual split stores the actual TX base on first activation, under the dispatch lock. A choice changes only TX; Off restores the base. Failed verification retains it for explicit recovery. New source/preset selections clear it without an intermediate old-source restore. There is no periodic split enforcement.
