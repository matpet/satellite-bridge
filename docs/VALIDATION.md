# Validation and practical limits

## Local regression suite

Version 1.0.6 passes **118 local tests** across `test_bridge`, `test_app_packaging`, `test_native_control`, `test_virtual_split` and `test_receiver_profiles`. These use simulated transports/control models and temporary local sockets. Passing them does not establish RF performance or compatibility with an arbitrary station.

The suite includes independent RX/TX command framing, blocked MacDoppler packets, stale and rejected report handling, startup Digital selection, saved-pair preservation, PTT gating, RX-only filter targeting, optimistic feedback rejection, no frequency retry on mismatch, and no command replay after a post-tuning power-read failure.

Ten compatibility regressions cover full and compact VFO labels, missing Data fields, reordered readouts, placeholder modes, live field refresh, RX/TX separation, selected-VFO mode fallback and ambiguous indicators.

## Version 1.0.6 combined source check - 26 October 2026

The repaired source pipeline received 13 controlled UDP updates and drove the real IC-9700 through RUMlogNG 6.6.1. Six were captured FO-29 reports. Further cases exercised USB, USB-D, CW-R, CW and FM, then TX CTCSS 74.4 Hz, 67.0 Hz and off. RX TSQL stayed off in those FM cases.

RX filter selection verified 2 for CW/CW-R and 1 for USB/USB-D. The TX filter was recorded before and after each RX-filter operation and stayed unchanged. Main/RX receiver profiles switched ATT/preamps through RUMlogNG. External 70 cm activation used the documented receiver command; the external amplifier itself was not independently measured.

MacDoppler power-default requests verified 80% after target application. QO-100 return verified Digital and RX filter 1. An externally imposed +220 Hz change to both QO-100 dials remained in place while the bridge sent zero additional setters.

USB-D split choices produced base 144.040220 MHz plus 5/10/15 kHz, then Off restored exactly 144.040220 MHz. CW used base 144.012000 MHz plus 1/2/3 kHz, then restored exactly 144.012000 MHz. RX stayed fixed throughout each split sequence. Final restoration returned Digital; no PTT command was sent.

This was controlled UDP replay and panel readback on a real radio, not a new live satellite pass or over-the-air contact. Build 10 was installed and its signature/executable verified. Its first packaged-app GUI check is pending an unlocked macOS session and any required Accessibility renewal; this source result does not substitute for that acceptance.

## Historical build 8 SAT pair-control check - 26 October 2026

This earlier partial build checked QO-100 only. Its 72-test count and MacDoppler limitation describe build 8; the combined source result above covers the later tracking repair.

With RUMlogNG 6.6.1 and SAT on, selecting SSB HB Amsat requested TX 144.240000 MHz / USB, but the panel remained at 144.040000 MHz / USB-D despite recorded Commander TX setters. Selecting Sub explicitly, using the ordinary frequency setter and changing mode through the panel correctly updated TX without changing RX or disabling SAT.

The installed 1.0.6 build 8 was checked across SSB HB Amsat, CW, Digital, SSB DX and back to SSB HB Amsat. Each selection verified both frequencies and both selected-VFO mode indicators. CW verified RX filter 2; USB and USB-D verified RX filter 1. SAT stayed enabled and reported RF power stayed at 4%.

Each selection recorded two ordinary frequency setters, one with Main selected and one with Sub selected; mode changes used the panel buttons. No additional frequency setter was recorded during the final stability sample. The normal frequency line can still omit RX mode during alternating polling; per-VFO mode proof comes from the explicit selection phase. No TX-filter rule is applied, although changing operating mode can recall that mode's own filter setting.

The 72 local tests add selected-VFO targeting, independent USB/Data and CW/reverse modes, unchanged-frequency suppression, state restoration, PTT interruption and no automatic fallback or frequency retry after failure. No over-the-air test or new live MacDoppler test was performed. The legacy MacDoppler path with RUMlogNG 6.6.x remains outside this validation.

## Version 1.0.5 live repair check - 26 October 2026

The installed Intel app, version 1.0.5 build 7, was tested with RUMlogNG 6.6.1 on macOS 15.7.3. The original failure was a lookup for `VFO Main Band (RX)` while the panel exposed `VFO Main (RX)`. Its RX mode text also remained at the placeholder `Mode`; the selected-VFO mode buttons supplied the mode needed for RX-filter verification.

After renewing macOS Accessibility access, Digital reached `QO-100 active — MacDoppler blocked`. Panel feedback reported RX 433.540000 MHz, TX 144.040000 MHz, RX filter 1, SAT on and RF power 4%. The bridge recorded exactly one RX-frequency setter, one TX-frequency setter and one mode setter per side. The last-command timestamp and applied count remained unchanged during the final stability sample, with no further setters in that launch's journal.

Both modes were requested as USB-D. TX USB-D was exposed by the panel in the final sample. RX mode could remain unavailable during alternating polling; the filter check used the actual selected-VFO mode indicators rather than substituting the requested mode. Saved presets were byte-for-byte unchanged, and the installed executable matched the packaged build.

No MacDoppler packets arrived during this repair check, so this release does not claim a new live UDP or over-the-air test. The earlier independent RX/TX checks below remain historical evidence.

## Live station checks

Development took place on an Intel Mac running macOS 15.7.3, RUMlogNG 6.5.1 and MacDoppler 2.48, with the IC-9700 as TRX2. The USB CAT connection remained at 19200 baud during the recorded checks.

Earlier live MacDoppler checks used actual UDP broadcasts through the bridge and separate operator confirmation at the IC-9700:

1. RX changed while TX stayed fixed.
2. TX then changed while RX stayed fixed.
3. The operator confirmed the restored QO-100 Digital pair and power within 5%.

The native feedback update was also checked by changing RX and TX separately outside the bridge's preset dispatch. The display followed each side in about one second while its last-commanded pair remained unchanged. This establishes that the display uses feedback, not merely a copy of the selected preset.

After the final 1.0.4 installation and Accessibility refresh, an observation-only startup check recorded one RX-frequency setter, one TX-frequency setter and one mode setter per side. No extra diagnostic tuning commands were issued. Digital readback remained RX 433.540000 MHz / TX 144.040000 MHz, RX USB-D, RX filter 1 and RF power 4% throughout the sample. Both modes were requested as USB-D; the panel did not independently expose a TX-mode value.

## An observed TX mismatch

During operation, the Amsat preset requested TX 144.240000 MHz, but a later RUMlogNG poll reported 144.198770 MHz. The immediate requested value had appeared before reverting. The bridge log showed no subsequent frequency setter, and the recorded MacDoppler packets were blocked. A separate diagnostic TX setter restored 144.240000 MHz and it held during observation.

The exact cause of the retained TX value was not established. It must not be presented as a proven baud-rate, mode-order or satellite-tracking fault. Version 1.0.4 addresses the misleading confirmation by checking stable feedback and reporting a difference without automatic frequency retries.

## Remaining scope

The release is an initial public preview of this station-specific build. It is not notarized, and its Accessibility controls depend on RUMlogNG's panel structure. During MacDoppler output it holds alternating Toggle polling off and restores the prior setting on QO-100 return/app close. QO-100 feedback still enables Toggle. Live physical confirmations from earlier builds and the final startup observation are distinct forms of evidence; neither is an independent RF measurement.

Private raw logs, packet captures and machine-specific test records are intentionally not published. This page summarizes their relevant results and limitations.
