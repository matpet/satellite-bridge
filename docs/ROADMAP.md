# Planned functionality - not in 1.0.4

The current application is intentionally left unchanged while the original station gathers operating experience. The following are requirements for a later version, not promises about the downloadable 1.0.4 app.

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
| MacDoppler | Default 80%, set once when entering the mode |
| Terrestrial repeater/simplex | Default 80%, set once when entering the mode |

Manual power adjustment remains possible outside the QO-100 ceiling. MacDoppler's ongoing frequency packets must not repeatedly reset power. Transitions into QO-100 must lower and verify power before tuning.

These 80% defaults are **not implemented** in 1.0.4. That version never automatically raises power when selecting MacDoppler.
