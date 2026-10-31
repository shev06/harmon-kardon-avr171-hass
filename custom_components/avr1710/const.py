"""Constants for the Harman Kardon AVR 1710 integration."""

DOMAIN = "avr1710"
DEFAULT_NAME = "AVR 1710"

CONF_CONTROL_PORT = "control_port"

CONTROL_PORT_DEFAULT = 10025

DEFAULT_SCAN_INTERVAL = 10  # seconds

MANUFACTURER = "Harman Kardon"
MODEL = "AVR 1710"

# Confirmed, reverse-engineered `source-selection` para values (TCP:10025
# dispatcher, FUN_08049d90 in the stock firmware). Sent verbatim over the
# wire; must match these strings exactly (including capitalization).
SOURCE_LIST = [
    "Cable Sat",
    "Source A",
    "Source B",
    "Source C",
    "Source D",
    "Disc",
    "Radio",
    "Game",
    "Media Server",
    "vTuner",
    "Home Network",
    "Pandora",
    "iPod",
    "Internet Radio",
    "Audio",
    "Server",
    "Sirius Radio",
    "DVR",
    "TV",
    "USB",
    "AUX",
    "FM",
    "AM",
    "STB",
]

# Confirmed simple "button" style top-level dispatcher commands (no `para`
# needed) that aren't already covered by the media_player platform
# (power/volume/mute/source/transport) -- exposed via the `remote` platform
# for automations and dashboards. mute-toggle is included here (rather than
# only exposing mute-on/off via media_player) since it's a distinct real
# command with no other way to reach it.
REMOTE_COMMANDS = [
    "mute-toggle",
    "forward",
    "reverse",
    "up",
    "down",
    "left",
    "right",
    "ok",
    "back",
    "options",
    "setting",
    "home",
    "sleep",
    "tone",
    "delay",
    "rds",
    "tune-up",
    "tune-down",
    "channel-up",
    "channel-down",
    "audio-effect",
    "video-mode",
    "surround-mode",
]
