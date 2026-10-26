# Why Satellite Bridge exists

## Keep one CAT owner

The starting point was an existing station: RUMlogNG already controlled the IC-9700 as **TRX2**, and I wanted to keep it that way. RUMlogNG should remain the only application connected to the radio's CAT/USB port.

The bridge therefore sits upstream of RUMlogNG. It receives MacDoppler's radio reports over UDP, chooses whether those reports have authority, and sends the selected frequencies and modes to RUMlogNG's TRX2 TCP server. RUMlogNG handles the radio connection. The bridge also uses RUMlogNG's control panel for selected VFOs, tones, receiver settings, SAT, RF power, RX filters and radio readback.

This preserves the logging/CAT arrangement without making the operator reconnect the radio or move serial-port ownership between applications.

## QO-100 is the home operating environment

My normal operation is on QO-100. Digital operation, different SSB meeting frequencies, and CW use distinct RX/TX dial pairs and mode settings. Entering them by hand every time is unnecessary work and invites mistakes.

I wanted a compact operating window with a short list of named pairs. Selecting a row should apply its frequencies and modes once. I should then be able to tune the IC-9700 manually without the bridge repeatedly pulling it back to the preset.

Pair definition belongs in a separate Settings screen, leaving the operating view simple.

## Follow LEO satellites without disturbing QO-100

MacDoppler can keep tracking LEO satellites while I operate on QO-100. Its continuing broadcasts must not change the radio unless I explicitly select **MacDoppler** in the bridge.

When a LEO becomes workable, selecting MacDoppler should pass its ongoing Doppler corrections through RUMlogNG. Returning to a QO-100 row should immediately revoke that authority and apply the chosen home pair once. Incoming packets should remain visible even while blocked, so the operator can see that MacDoppler is still active.

The source buttons should clearly identify which application or preset family currently owns tuning.

## Uplink and downlink must be independent

Moving RX and TX together is not enough to prove the bridge works: the radio's satellite tracking could produce that result on its own. The requirement is stronger. A change to MacDoppler's downlink must cause the RX setter; a change to its uplink must cause the TX setter. Neither frequency is calculated from the other.

Live checks therefore changed only RX, then only TX, and included operator confirmation at the IC-9700. That distinction remains central to development and testing.

## Protect the QO-100 converter

In the original station, the QO-100 transmit output feeds a converter. The requested maximum RF power setting is **5%**. The bridge applies and verifies that ceiling around QO-100 tuning, then continues monitoring it while QO-100 remains selected, including when frequency output is paused.

The radio often quantizes a 5% request to a displayed 4%; that is within the requested ceiling. The setting is a software guard with feedback latency, not a physical RF limiter.

## Be honest about feedback

Sending a TCP command proves that a request was delivered to RUMlogNG, not that the IC-9700 has retained the requested frequency. The UI must show what RUMlogNG actually reports, including manual tuning and missing or stale data.

Since version 1.0.4, the bridge checks for stable readback after a QO-100 selection. If the values do not confirm the pair, it reports the difference without automatically resending frequencies. Temporary power-read problems can recover automatically, but an already-sent tuning batch must never be replayed by that recovery.

## Extend later, without changing today's operation

The current version is being used for experience and feedback. A future Terrestrial mode should offer the same simple selection model for repeaters and simplex voice/data channels. MacDoppler now applies an 80% TX default on entry or TX band/mode changes; QO-100 keeps its 5% ceiling. Terrestrial profiles and their power default remain in the [roadmap](ROADMAP.md).
