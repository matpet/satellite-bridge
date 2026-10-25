# Validation and practical limits

## Local regression suite

Version 1.0.4 passes **50 local tests** across `test_bridge`, `test_app_packaging` and `test_native_control`. These use simulated transports/control models and temporary local sockets. Passing them does not establish RF performance or compatibility with an arbitrary station.

The suite includes independent RX/TX command framing, blocked MacDoppler packets, stale and rejected report handling, startup Digital selection, saved-pair preservation, PTT gating, RX-only filter targeting, optimistic feedback rejection, no frequency retry on mismatch, and no command replay after a post-tuning power-read failure.

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

The release is an initial public preview of this station-specific build. It is not notarized, and its Accessibility controls depend on RUMlogNG's panel structure. It still forces the Toggle control on during feedback reads. Live physical confirmations from earlier builds and the final startup observation are distinct forms of evidence; neither is an independent RF measurement.

Private raw logs, packet captures and machine-specific test records are intentionally not published. This page summarizes their relevant results and limitations.
