# Harman Kardon AVR 1710 — Home Assistant Integration

A custom Home Assistant integration for the Harman Kardon AVR 1710 receiver,
built from a full reverse-engineering of its firmware and live network
testing against a real device. This is an **unofficial, community
integration** — not published or endorsed by Harman Kardon.

## What it uses

The receiver exposes two independent, already-shipping network APIs (no
firmware modification needed to use either one):

1. **TCP:10025** — a proprietary XML command dispatcher built into the
   receiver's main firmware. Used here for **power on/off, source
   selection (24 named inputs), and ~20 remote-button commands**
   (menu/transport/tone/etc.).
2. **DLNA/UPnP (port 8080)** — a standard `MediaRenderer:1` stack hosted on
   a separate network-bridge chip. Used here for **volume, mute, and
   transport (play/pause/stop/next/previous) get+set**, because the
   proprietary dispatcher's own status replies for volume/mute are always
   empty by firmware design (those code paths never compute a value to
   report — a pre-existing firmware limitation, not something this
   integration can work around without a flashed binary patch).

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
  command: home   # or: options, setting, sleep, tone, delay, rds,
                  # tune-up, tune-down, channel-up, channel-down,
                  # audio-effect, video-mode, surround-mode,
                  # up/down/left/right/ok/back/forward/reverse
```

## Known limitations (found during live testing, not assumptions)

- **TCP:10025 appears to accept only one client connection at a time.**
  If you have another app or an open telnet/nc session connected to that
  port, every other client's connection attempt (including this
  integration's polling) will be refused until it closes. This
  integration already opens a connection, sends one command, reads the
  reply, and closes immediately — it never holds the port open — but it
  still can't win against another client already occupying the single
  slot. If `power`/`source` look stuck or unavailable, check for another
  open connection to port 10025 first. Since v1.0.1, a single refused poll
  no longer resets `power`/`source` (or `volume`/`mute`/`transport` if DLNA
  has the hiccup instead) back to unknown — the last known-good value is
  kept until the next successful poll updates it.
- **When the control port can't be reached at all**, this integration
  does **not** assume the receiver is off (live testing showed the port
  can refuse connections even while the receiver is genuinely on). Instead
  it falls back to DLNA reachability to decide on/off, and only shows the
  entity as truly `unavailable` if *neither* API responds.
- **Volume/mute readback always comes from DLNA**, not the proprietary
  dispatcher (see "What it uses" above) — this is correct and expected,
  not a bug.
- **Turning the receiver on over the network is not guaranteed from deep
  standby.** The firmware aggressively clock-gates the main MCU to save
  power; depending on how long it's been idle, `power-on` may not reach it
  the same way IR/front-panel power-on does.

## Source list (exact strings the firmware expects)

`Cable Sat`, `Source A`, `Source B`, `Source C`, `Source D`, `Disc`,
`Radio`, `Game`, `Media Server`, `vTuner`, `Home Network`, `Pandora`,
`iPod`, `Internet Radio`, `Audio`, `Server`, `Sirius Radio`, `DVR`, `TV`,
`USB`, `AUX`, `FM`, `AM`, `STB`.

## Files

```
custom_components/avr1710/
├── __init__.py       # entry setup/teardown, platform forwarding
├── api.py            # standalone async client for both network surfaces
├── config_flow.py    # UI setup (host/name/ports)
├── const.py          # domain, defaults, source list, button command list
├── coordinator.py     # polling DataUpdateCoordinator (10s interval)
├── media_player.py    # power/volume/mute/source/transport entity
├── remote.py          # raw button-command passthrough entity
├── manifest.json
├── strings.json
└── translations/en.json
```

`api.py` has no Home Assistant imports and can be run/tested standalone.
