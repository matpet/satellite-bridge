# Changelog

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
