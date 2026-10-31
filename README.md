# Harman Kardon AVR 1710 — Home Assistant Integration

A custom Home Assistant integration for the Harman Kardon AVR 1710 receiver,
built from a full reverse-engineering of its firmware and live network
testing against a real device. This is an **unofficial, community
integration** — not published or endorsed by Harman Kardon.

## What it uses

The receiver exposes **TCP:10025**, a proprietary XML command dispatcher
built into the receiver's main firmware (no firmware modification needed to
use it). This integration talks to that single API only:

- **Power** on/off/toggle, with readback (query-status).
- **Source selection** — 24 named inputs, with readback.
- **Volume** — relative step up/down, with live volume-level readback on
  firmware with the volume/mute status fix. The reported percentage is
  converted to Home Assistant's 0-1 volume level. There is no absolute
  "set volume to X" command, so no set-volume slider is exposed.
- **Mute** — on/off/toggle, with live mute-state readback on firmware with
  the volume/mute status fix, so the mute control reflects current state.
- **Transport** — play/pause/next/previous. There is no "stop" command
  anywhere in the firmware's command table, so it isn't exposed (faking it
  with pause would be misleading). No fine-grained playing/paused/idle
  state readback either — the entity only distinguishes on/off.
- ~20 other simple remote-button commands (menu/tone/delay/etc.) via the
  `remote` entity.

An earlier version of this integration also used the receiver's separate
DLNA/UPnP surface (port 8080, a different network-bridge chip) to get real
numeric volume and boolean mute state. That's been dropped by choice to
keep the integration to a single, simpler network surface. As of v1.2.0,
volume and mute are read directly from TCP:10025 when the custom firmware's
volume/mute status fix is installed. Older firmware's empty replies remain
unknown; power/source and existing controls continue to work. Stop and
playing/paused readback remain unsupported.

## Installation

1. Copy the `custom_components/avr1710` folder into your Home Assistant
   config directory, so you have:
   `<config>/custom_components/avr1710/__init__.py` (and so on).
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration**, search for
   "Harman Kardon AVR 1710", and enter your receiver's IP address.
4. Two entities are created: a `media_player` (power/volume/mute/source/
   transport) and a `remote` (raw button passthrough for everything else).

## Using the `remote` entity

```yaml
service: remote.send_command
target:
  entity_id: remote.avr_1710
data:
  command: home   # or: mute-toggle, options, setting, sleep, tone, delay,
                  # rds, tune-up, tune-down, channel-up, channel-down,
                  # audio-effect, video-mode, surround-mode,
                  # up/down/left/right/ok/back/forward/reverse
```

## Known limitations (found during live testing, not assumptions)

- **TCP:10025 accepts only one client connection at a time.** If another
  app or an open telnet/nc session is connected to that port, any other
  client's connection attempt will be refused until it closes. Since this
  integration's own periodic poll and any user-triggered command (turn
  on/off, select source, ...) both use that same single slot, they can
  race each other too — not just external clients. To absorb this, every
  call is serialized through a lock and retried a few times before giving
  up; if you still see an occasional failure surfaced as an error, it means
  something else held the port open for longer than the retry window.
- **Power state requires an explicit `on`/`off` reply.** As of v1.2.1,
  failed source/volume/mute queries cannot overwrite a confirmed `on`
  state. Their unread fields retain last-known values and a warning is
  logged. Missing, invalid, or unreachable power replies mark the entity
  **unavailable**, not off: network failure alone cannot distinguish
  standby from a connection problem. The next successful poll restores
  availability.
- **Volume and mute readback require the custom firmware's volume/mute
  status fix.** Older firmware returns empty values, so those attributes
  remain unknown. Playing/paused/idle readback is unavailable on either
  firmware; the entity only distinguishes on/off.
- **No volume slider or stop button.** The firmware has no absolute
  "set volume" or "stop" command, so `VOLUME_SET`/`STOP` aren't claimed as
  supported features (faking them would be misleading).
- **The receiver cannot be turned on over the network once it's actually
  asleep — confirmed live, not a guess.** Putting the receiver into
  standby via the remote/front panel makes TCP:10025 go completely dark
  (connection refused/timeout; even ICMP ping stops responding), so there
  is no way to send it a wake command from Home Assistant. This is a
  firmware/hardware limitation, not something this integration can patch
  around — you'll need the IR remote or front panel to wake it, after
  which Home Assistant will pick the "on" state back up on its next poll
  (every 10s). When the sleeping receiver cannot report power state, the
  entity is **unavailable** rather than incorrectly inferring off.
- **Turning the receiver off over the network may be slower than
  expected.** Sending `power-off` is accepted immediately, but live
  testing has seen the receiver stay fully reachable and reporting "on"
  for 20+ seconds afterwards before going to sleep. If you need
  confirmation the receiver actually went to standby, don't assume it's
  instant.

## Source list (exact strings the firmware expects)

`Cable Sat`, `Source A`, `Source B`, `Source C`, `Source D`, `Disc`,
`Radio`, `Game`, `Media Server`, `vTuner`, `Home Network`, `Pandora`,
`iPod`, `Internet Radio`, `Audio`, `Server`, `Sirius Radio`, `DVR`, `TV`,
`USB`, `AUX`, `FM`, `AM`, `STB`.

## Files

```
custom_components/avr1710/
├── __init__.py       # entry setup/teardown, platform forwarding
├── api.py            # standalone async client for the TCP:10025 dispatcher
├── config_flow.py    # UI setup (host/name/port)
├── const.py          # domain, defaults, source list, button command list
├── coordinator.py     # polling DataUpdateCoordinator (10s interval)
├── media_player.py    # power/volume/mute/source/transport entity
├── remote.py          # raw button-command passthrough entity
├── manifest.json
├── strings.json
└── translations/en.json
```

`api.py` has no Home Assistant imports and can be run/tested standalone.
