# Planned functionality - not in 1.0.6

Version 1.0.6 is a public preview. The following future requirements are not promises about the downloadable app.

## Current operating decision - 26 October 2026

RUMlogNG remains the sole physical CAT owner. During MacDoppler operation, the operator uses MacDoppler's tuning aids; radio-knob tracking in MacDoppler is not required. Keep the UDP route and forward RX/TX independently. The experimental virtual-radio route is outside the current repair scope.

QO-100 retains SAT and accepts manual tuning at the radio after a preset has been applied once. Display changes and power-feedback recovery must preserve those dial changes. Explicitly selecting a preset again restores its saved pair once. Incoming MacDoppler reports remain blocked, and the 5% power ceiling continues to be monitored.

MacDoppler TX CTCSS must use RUMlogNG's IC-9700 control panel: select TX, set the tone frequency, and enable or disable Tone. RX TSQL is a separate request. SO-50's 74.4 Hz and 67.0 Hz settings must be forwarded as supplied by MacDoppler, with no automatic PTT. Controlled real-radio replay verified frequency/mode, tones, filters, power and virtual split. External-amplifier operation and on-air satellite access are separate operator checks.

## Respect the RUMlogNG Toggle setting

Remove automatic Toggle activation from feedback polling and preserve the operator's choice. Readback must honestly show unavailable fields rather than silently imposing a panel setting.

## Add Terrestrial as a third operating mode

Alongside QO-100 and MacDoppler, provide one-click terrestrial profiles with editing in Settings.

**Repeater profiles:** name, VHF/UHF band, RX frequency (repeater output), TX frequency (repeater input), duplex direction/offset including DUP-, mode, and TX CTCSS opening tone or none.

**Simplex profiles:** name, equal RX/TX frequency, no duplex offset, and saved voice/data settings. An example requested by the operator is a packet-radio channel at **144.800 MHz**.

Selecting a terrestrial profile should disable SAT, block MacDoppler, configure duplex/tone/mode/frequencies once, then permit manual tuning with live feedback. No continuous preset enforcement is wanted.

## Add power defaults by operating mode

| Mode | Planned power behavior |
| --- | --- |
| QO-100 | Maximum 5%, verified before tuning and continuously monitored |
| MacDoppler | Implemented: 80% after target verification on entry or a TX band/mode change |
| Terrestrial repeater/simplex | Default 80%, set once when entering the mode |

Manual power adjustment remains possible outside the QO-100 ceiling. MacDoppler's ongoing frequency packets must not repeatedly reset power. Transitions into QO-100 must lower and verify power before tuning.

The MacDoppler default is implemented in 1.0.6. Terrestrial profiles and their proposed 80% default remain unimplemented. QO-100 remains capped at 5%.
