# Changelog

## 1.0.6 - 2026-10-26

Selected-VFO tracking repair, receiver profiles, tones and QO-100 virtual split; build 10.

- Keep Main/RX and Sub/TX explicit, using ordinary frequency setters and panel mode/Data controls with SAT enabled.
- Hold alternating polling off during MacDoppler updates, including background feedback. Restore it on QO-100 return/app close.
- Apply RX filter 2 for CW/CW-R and filter 1 for USB/USB-D in both sources, without changing the TX filter.
- Forward TX CTCSS through the TX Tone popup/button; keep RX TSQL separate. Wait for Cocoa menus and acquire/restore foreground focus when needed.
- Apply QO-100 RX ATT with preamps off; LEO RX internal preamp with ATT off and external 70 cm activation. Use three validated receiver-only macros in unused RUMlogNG slots.
- Apply MacDoppler's 80% TX default after target verification, on entry or TX band/mode changes.
- Add TX-only virtual split: USB/USB-D +5/+10/+15 kHz; CW/CW-R +1/+2/+3 kHz. Save the actual starting TX, avoid stacking, and restore that base on Off.
- Preserve QO-100 manual tuning, its one-shot preset selection, RX-only filtering and 5% ceiling.

118 simulated regressions pass. A controlled real-radio UDP replay verified 13 updates, tone transitions, RX filters, receiver profiles, 80% defaults, both split ranges and manual-tuning preservation. No over-the-air QSO or independent external-amplifier measurement is claimed. Installed build 10 also verified Digital/CW, SAT, 4% power, RX filters and observed split/base restoration after Accessibility renewal.

## 1.0.5 - 2026-10-26

RUMlogNG IC-9700 control-panel compatibility repair, build 7.

- Accept both `VFO Main/Sub Band (RX/TX)` and compact `VFO Main/Sub (RX/TX)` control-group labels while keeping RX and TX separate.
- Identify frequency, mode and filter from field contents, including TX layouts without a Data field.
- Reject placeholder mode labels. When a band readout omits its mode, use the live mode buttons only while that VFO is selected unambiguously.
- Use the same mode fallback for RX-filter verification, fixing the startup `RX mode` timeout.
- Expand regression coverage from 50 to 60 tests. Live Digital startup on RUMlogNG 6.6.1 verified both frequencies, RX filter 1, power at 4% and one batch of four tuning setters.

After replacing an ad-hoc-signed app, macOS may require removing and re-adding its Accessibility entry. Saved pairs remain outside the app bundle and are preserved.

The Toggle override, terrestrial profiles, CTCSS forwarding and 80% power defaults remain outside this release. No new live MacDoppler packet test was performed for 1.0.5.

## 1.0.4 - 2026-10-25

Initial public preview of the existing station-tested app.

- One-shot QO-100 frequency/mode dispatch with read-only stable-feedback confirmation.
- A feedback mismatch does not trigger automatic frequency retries.
- Recovery from a post-tuning power-read failure does not replay the sent batch.
- Default Digital startup, source indicators, editable QO-100 pairs and visible UDP packets.
- Native macOS Accessibility controls and independent RX/TX readback.
- QO-100 5% power ceiling and RX filter rules.

Known limitation: feedback still automatically enables RUMlogNG's Toggle control. Respecting the operator's choice and terrestrial/80% power features remain planned.

The publication does not replace or modify the app running at the original station.
