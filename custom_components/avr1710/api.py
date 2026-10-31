"""Async client for the Harman Kardon AVR 1710's proprietary TCP:10025 dispatcher.

This module is intentionally free of any `homeassistant` imports so it can be
unit-tested (or run live against a real receiver) completely standalone.

TCP:10025 is a proprietary dispatcher reverse-engineered from the receiver's
own firmware (FUN_08049d90 / FUN_08044dc4), hosted on the receiver's main
STM32 MCU. It provides: power on/off/toggle, 24 named source inputs,
query-status for live power/source/volume/mute state on patched firmware,
relative volume step (up/down, no absolute set), mute on/off/toggle, play/pause/
next/previous (write-only, no "stop" command exists), and ~20 other simple
remote-button-style commands (menu/tone/delay/etc.).

The custom firmware's volume/mute fix reports volume as a percentage (0-100)
and mute as "on"/"off". Older firmware returns empty values, which remain
unknown. No DLNA/UPnP connection is used, and fine-grained transport state
(playing/paused/idle) isn't available.

IMPORTANT, confirmed via live testing against a real device: this port is
only reliably reachable while the STM32 is NOT in its low-power STOP sleep
state, AND it only accepts one client connection at a time -- any other
open connection (another app, a manual telnet/nc session, or even this same
integration's own periodic poll racing a manual command) will cause other
connection attempts to be refused. `send_command` below serializes all
calls through a lock and retries a few times to absorb this.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, replace

_LOGGER = logging.getLogger(__name__)

CONTROL_PORT_DEFAULT = 10025
TIMEOUT = 5
# See the module docstring: the dispatcher only accepts one client at a time,
# so this integration's own periodic poll and any user-triggered command can
# race each other (and any external client) for that single slot and lose,
# even though the receiver is genuinely reachable and on.
CONTROL_RETRY_ATTEMPTS = 3
CONTROL_RETRY_DELAY = 0.4  # seconds between retries

_TAG_PATTERNS = {
    "name": re.compile(r"<name>(.*?)</name>", re.S),
    "zone": re.compile(r"<zone>(.*?)</zone>", re.S),
    "para": re.compile(r"<para>(.*?)</para>", re.S),
}


class AVR1710ConnectionError(Exception):
    """Raised when the control port cannot be reached at all."""


class AVR1710ResponseError(Exception):
    """Raised when the receiver reports an invalid status value."""


@dataclass
class AVR1710Status:
    """Snapshot of dispatcher-reported state."""

    power_on: bool | None = None
    source: str | None = None
    volume_level: float | None = None
    is_volume_muted: bool | None = None

    @property
    def is_likely_on(self) -> bool:
        """True only when the control port has confirmed the receiver is on.

        Failed power polls raise an update error rather than publishing
        a snapshot with guessed power state.
        """
        return bool(self.power_on)


def _build_control_message(name: str, host: str, port: int, zone: str = "", para: str = "") -> bytes:
    # NOTE: the opening tag is "<staus>" (misspelled) while the closing tag is
    # the correctly-spelled "</status>" -- this exact asymmetry is present in
    # the shipping firmware's own string table and must be reproduced
    # verbatim; do not "fix" it here.
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<harman><avr><common><staus>"
        f"<name>{name}</name><zone>{zone}</zone><para>{para}</para>"
        "</status></common></avr></harman>"
    )
    body = xml.encode("ascii")
    header = (
        "POST AVR HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "User-Agent:Harman Kardon AVR171/AVR1710\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    )
    return header.encode("ascii") + body


class AVR1710Client:
    """Client for the TCP:10025 proprietary command dispatcher."""

    def __init__(self, host: str, control_port: int = CONTROL_PORT_DEFAULT) -> None:
        self._host = host
        self._control_port = control_port
        # Serializes ALL control-port traffic (reads and writes alike) so
        # this integration never contends with itself for the receiver's
        # single TCP:10025 client slot -- see CONTROL_RETRY_ATTEMPTS above.
        self._control_lock = asyncio.Lock()

    async def close(self) -> None:
        """No persistent resources to release; kept for API symmetry with callers."""

    # ---------------------------------------------------------------
    # Low-level dispatcher I/O
    # ---------------------------------------------------------------

    async def send_command(self, name: str, zone: str = "", para: str = "") -> dict[str, str]:
        """Send one command frame to the proprietary dispatcher and parse its reply.

        Returns whichever of name/zone/para tags were present in the reply
        (the reply is not strict XML -- its opening/closing status tags are
        mismatched in the real firmware -- so this uses simple regex
        extraction rather than an XML parser).

        Serializes against other calls on this same client (see
        `_control_lock`) and retries up to CONTROL_RETRY_ATTEMPTS times on a
        connection failure, since the receiver only accepts one client at a
        time and a refusal is often transient (the previous client finishes
        quickly). Raises AVR1710ConnectionError only if every attempt fails.
        """
        msg = _build_control_message(name, self._host, self._control_port, zone, para)
        async with self._control_lock:
            data = b""
            last_err: Exception | None = None
            for attempt in range(CONTROL_RETRY_ATTEMPTS):
                last_err = None
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(self._host, self._control_port), timeout=TIMEOUT
                    )
                except (OSError, asyncio.TimeoutError) as err:
                    last_err = err
                else:
                    try:
                        writer.write(msg)
                        await writer.drain()
                        try:
                            data = await asyncio.wait_for(reader.read(4096), timeout=TIMEOUT)
                        except asyncio.TimeoutError:
                            data = b""
                    except OSError as err:
                        last_err = err
                    finally:
                        writer.close()
                        with contextlib.suppress(Exception):
                            await writer.wait_closed()

                if last_err is None:
                    break
                if attempt < CONTROL_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(CONTROL_RETRY_DELAY)

            if last_err is not None:
                raise AVR1710ConnectionError(
                    f"Cannot reach {self._host}:{self._control_port} after "
                    f"{CONTROL_RETRY_ATTEMPTS} attempts (receiver may be asleep, or "
                    f"another client is holding the single connection slot): {last_err}"
                ) from last_err

        text = data.decode("ascii", errors="replace")
        result: dict[str, str] = {}
        for key, pattern in _TAG_PATTERNS.items():
            match = pattern.search(text)
            if match:
                result[key] = match.group(1)
        return result

    async def query_status(self, para: str) -> str | None:
        reply = await self.send_command("query-status", para=para)
        if reply.get("name") != para or "para" not in reply:
            raise AVR1710ResponseError(f"Invalid {para} status reply: {reply!r}")
        return reply.get("para") or None

    # ---------------------------------------------------------------
    # Power / source
    # ---------------------------------------------------------------

    async def get_power(self) -> bool:
        value = await self.query_status("power")
        if value is None:
            raise AVR1710ResponseError("Power status is empty")
        value = value.strip().lower()
        if value not in ("on", "off"):
            raise AVR1710ResponseError(f"Invalid power status: {value!r}")
        return value == "on"

    async def get_source(self) -> str | None:
        return await self.query_status("source")

    async def set_power(self, on: bool, zone: str = "") -> None:
        await self.send_command("power-on" if on else "power-off", zone=zone)

    async def select_source(self, source: str, zone: str = "") -> None:
        await self.send_command("source-selection", zone=zone, para=source)

    # ---------------------------------------------------------------
    # Volume / mute
    # ---------------------------------------------------------------

    async def get_volume(self) -> float | None:
        """Read the firmware's percentage as Home Assistant's 0-1 level."""
        value = await self.query_status("volume")
        if value is None:
            return None
        value = value.strip()
        if not re.fullmatch(r"[0-9]+", value) or not 0 <= int(value) <= 100:
            raise AVR1710ResponseError(f"Invalid volume status: {value!r}")
        return int(value) / 100

    async def get_mute(self) -> bool | None:
        """Read mute state; empty replies on older firmware remain unknown."""
        value = await self.query_status("mute")
        if value is None:
            return None
        value = value.strip().lower()
        if value not in ("on", "off"):
            raise AVR1710ResponseError(f"Invalid mute status: {value!r}")
        return value == "on"

    async def volume_up(self) -> None:
        await self.send_command("volume-up")

    async def volume_down(self) -> None:
        await self.send_command("volume-down")

    async def set_mute(self, mute: bool) -> None:
        await self.send_command("mute-on" if mute else "mute-off")

    async def mute_toggle(self) -> None:
        await self.send_command("mute-toggle")

    # ---------------------------------------------------------------
    # Transport -- confirmed real dispatcher commands. No "stop" exists in
    # the firmware's command table, so there is no media_stop() here.
    # ---------------------------------------------------------------

    async def media_play(self) -> None:
        await self.send_command("play")

    async def media_pause(self) -> None:
        await self.send_command("pause")

    async def media_next(self) -> None:
        await self.send_command("next")

    async def media_previous(self) -> None:
        await self.send_command("previous")

    async def send_button(self, command: str, zone: str = "") -> None:
        """Send one of the simple remote-button-style commands (see const.REMOTE_COMMANDS)."""
        await self.send_command(command, zone=zone)

    # ---------------------------------------------------------------
    # Combined status (used by the DataUpdateCoordinator)
    # ---------------------------------------------------------------

    async def async_update_status(self, previous: AVR1710Status | None = None) -> AVR1710Status:
        """Poll power/source/volume/mute and return a snapshot.

        Only an explicit power reply determines on/off. An unreachable or
        invalid power reply raises, allowing Home Assistant to mark the
        entity unavailable rather than guessing standby. Once power is
        confirmed on, auxiliary query failures retain unread fields from
        the previous on-state snapshot and are logged for diagnosis.
        """
        power_on = await self.get_power()
        if not power_on:
            return AVR1710Status(power_on=False)

        status = (
            replace(previous, power_on=True)
            if previous is not None and previous.power_on
            else AVR1710Status(power_on=True)
        )
        try:
            status.source = await self.get_source()
            status.volume_level = await self.get_volume()
            status.is_volume_muted = await self.get_mute()
        except (AVR1710ConnectionError, AVR1710ResponseError) as err:
            _LOGGER.warning(
                "Receiver confirmed on, but auxiliary status poll failed; "
                "retaining last-known values for unread fields: %s", err,
            )

        return status
