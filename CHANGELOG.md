# Changelog

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
