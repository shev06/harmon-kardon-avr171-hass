"""Async client for the Harman Kardon AVR 1710's two network control surfaces.

This module is intentionally free of any `homeassistant` imports so it can be
unit-tested (or run live against a real receiver) completely standalone.

Two independent, already-shipping network APIs are combined here:

1. TCP:10025 "proprietary dispatcher" -- reverse-engineered from the
   receiver's own firmware (FUN_08049d90 / FUN_08044dc4). Hosted on the
   receiver's main STM32 MCU. This is the richest control surface: power
   on/off/toggle, 24 named source inputs, and ~20 remote-button-style
   commands (transport/menu/tone/etc.), plus `query-status` for live
   power/source state.

   IMPORTANT, confirmed via live testing against a real device: this port
   is only reliably reachable while the STM32 is NOT in its low-power STOP
   sleep state. When the receiver has been in standby for a while, TCP
   connections to :10025 can be refused -- this is a real firmware
   characteristic (the MCU gates its own peripheral clocks on sleep entry),
   not a bug in this client. Connection failures here are treated as
   "receiver is asleep/off", not surfaced as hard errors.

2. DLNA/UPnP (port 8080), hosted on a separate BridgeCo CE2DM870 media
   bridge chip. Standard MediaRenderer:1 services (RenderingControl,
   AVTransport, ConnectionManager). This chip appears to stay reachable
   independently of the main MCU's sleep state, and is the only channel
   that returns real numeric volume / boolean mute state -- the
   proprietary dispatcher's query-status replies for volume/mute are
   permanently empty by firmware design (those dispatcher call sites never
   compute a value to send). So DLNA is used here for volume/mute/transport
   get+set, while the proprietary dispatcher is used for power/source/
   button-style commands.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass

import aiohttp

CONTROL_PORT_DEFAULT = 10025
DLNA_PORT_DEFAULT = 8080
TIMEOUT = 5

_TAG_PATTERNS = {
    "name": re.compile(r"<name>(.*?)</name>", re.S),
    "zone": re.compile(r"<zone>(.*?)</zone>", re.S),
    "para": re.compile(r"<para>(.*?)</para>", re.S),
}


class AVR1710ConnectionError(Exception):
    """Raised when a network surface cannot be reached at all."""


@dataclass
class AVR1710Status:
    """Combined, best-effort snapshot of both network surfaces."""

    power_on: bool | None = None
    source: str | None = None
    volume: int | None = None  # 0-100, from DLNA
    muted: bool | None = None  # from DLNA
    transport_state: str | None = None  # from DLNA AVTransport (e.g. PLAYING)

    @property
    def is_likely_on(self) -> bool:
        """Best-effort on/off determination for display purposes.

        `power_on` is authoritative when known (a real reply was received
        from TCP:10025 query-status/power). When the control port could not
        be reached at all, this deliberately does NOT assume "off": live
        testing showed the control port can refuse connections even while
        the receiver is genuinely on -- e.g. it appears to serve only one
        client at a time, so any other open connection (another app, a
        manual telnet/nc session, etc.) will cause every other client's
        attempt to be refused regardless of power state. In that situation,
        any successful DLNA reply is treated as evidence the receiver has
        power and is in use.
        """
        if self.power_on is not None:
            return self.power_on
        return self.volume is not None or self.muted is not None or self.transport_state is not None


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
    """Combines the TCP:10025 command dispatcher and DLNA/UPnP control."""

    def __init__(
        self,
        host: str,
        control_port: int = CONTROL_PORT_DEFAULT,
        dlna_port: int = DLNA_PORT_DEFAULT,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._host = host
        self._control_port = control_port
        self._dlna_port = dlna_port
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    # ---------------------------------------------------------------
    # TCP:10025 proprietary dispatcher
    # ---------------------------------------------------------------

    async def send_command(self, name: str, zone: str = "", para: str = "") -> dict[str, str]:
        """Send one command frame to the proprietary dispatcher and parse its reply.

        Returns whichever of name/zone/para tags were present in the reply
        (the reply is not strict XML -- its opening/closing status tags are
        mismatched in the real firmware -- so this uses simple regex
        extraction rather than an XML parser).

        Raises AVR1710ConnectionError if the socket can't be reached at all.
        """
        msg = _build_control_message(name, self._host, self._control_port, zone, para)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._control_port), timeout=TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise AVR1710ConnectionError(
                f"Cannot reach {self._host}:{self._control_port} (receiver may be asleep): {err}"
            ) from err

        try:
            writer.write(msg)
            await writer.drain()
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=TIMEOUT)
            except asyncio.TimeoutError:
                data = b""
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

        text = data.decode("ascii", errors="replace")
        result: dict[str, str] = {}
        for key, pattern in _TAG_PATTERNS.items():
            match = pattern.search(text)
            if match:
                result[key] = match.group(1)
        return result

    async def query_status(self, para: str) -> str | None:
        reply = await self.send_command("query-status", para=para)
        return reply.get("para") or None

    async def get_power(self) -> bool | None:
        value = await self.query_status("power")
        if value is None:
            return None
        return value.strip().lower() == "on"

    async def get_source(self) -> str | None:
        return await self.query_status("source")

    async def set_power(self, on: bool, zone: str = "") -> None:
        await self.send_command("power-on" if on else "power-off", zone=zone)

    async def select_source(self, source: str, zone: str = "") -> None:
        await self.send_command("source-selection", zone=zone, para=source)

    async def send_button(self, command: str, zone: str = "") -> None:
        """Send one of the simple remote-button-style commands (see const.REMOTE_COMMANDS)."""
        await self.send_command(command, zone=zone)

    # ---------------------------------------------------------------
    # DLNA / UPnP (BridgeCo chip)
    # ---------------------------------------------------------------

    async def _soap_call(self, service: str, action: str, args: dict | None = None) -> str:
        args = args or {}
        body_args = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<s:Body>"
            f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:1">'
            f"{body_args}"
            f"</u:{action}>"
            "</s:Body></s:Envelope>"
        )
        session = await self._get_session()
        url = f"http://{self._host}:{self._dlna_port}/{service}/ctrl"
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"urn:schemas-upnp-org:service:{service}:1#{action}"',
        }
        try:
            async with session.post(
                url, data=envelope, headers=headers, timeout=aiohttp.ClientTimeout(total=TIMEOUT)
            ) as resp:
                return await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise AVR1710ConnectionError(f"DLNA call {service}#{action} failed: {err}") from err

    @staticmethod
    def _extract(text: str, tag: str) -> str | None:
        match = re.search(f"<{tag}>(.*?)</{tag}>", text, re.S)
        return match.group(1) if match else None

    async def get_volume(self) -> int | None:
        text = await self._soap_call("RenderingControl", "GetVolume", {"InstanceID": 0, "Channel": "Master"})
        value = self._extract(text, "CurrentVolume")
        return int(value) if value is not None else None

    async def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, int(volume)))
        await self._soap_call(
            "RenderingControl", "SetVolume", {"InstanceID": 0, "Channel": "Master", "DesiredVolume": volume}
        )

    async def get_mute(self) -> bool | None:
        text = await self._soap_call("RenderingControl", "GetMute", {"InstanceID": 0, "Channel": "Master"})
        value = self._extract(text, "CurrentMute")
        return value == "1" if value is not None else None

    async def set_mute(self, mute: bool) -> None:
        await self._soap_call(
            "RenderingControl", "SetMute", {"InstanceID": 0, "Channel": "Master", "DesiredMute": 1 if mute else 0}
        )

    async def get_transport_state(self) -> str | None:
        text = await self._soap_call("AVTransport", "GetTransportInfo", {"InstanceID": 0})
        return self._extract(text, "CurrentTransportState")

    async def media_play(self) -> None:
        await self._soap_call("AVTransport", "Play", {"InstanceID": 0, "Speed": 1})

    async def media_pause(self) -> None:
        await self._soap_call("AVTransport", "Pause", {"InstanceID": 0})

    async def media_stop(self) -> None:
        await self._soap_call("AVTransport", "Stop", {"InstanceID": 0})

    async def media_next(self) -> None:
        await self._soap_call("AVTransport", "Next", {"InstanceID": 0})

    async def media_previous(self) -> None:
        await self._soap_call("AVTransport", "Previous", {"InstanceID": 0})

    # ---------------------------------------------------------------
    # Combined status (used by the DataUpdateCoordinator)
    # ---------------------------------------------------------------

    async def async_update_status(self, previous: AVR1710Status | None = None) -> AVR1710Status:
        """Poll both surfaces and return a best-effort combined snapshot.

        `previous` is the last successfully-merged snapshot (if any). When a
        surface fails on this particular poll, its fields are carried
        forward from `previous` instead of being reset to None/unknown --
        this matters because TCP:10025 only accepts one client at a time
        (confirmed via live testing), so any single poll can transiently
        fail there even while the receiver is genuinely on with a known
        source. Without this carry-forward, every such hiccup would wipe
        power/source (or volume/mute/transport) back to unknown, even
        though the overall update below still counts as a "success" (it
        only raises if BOTH surfaces are unreachable).
        """
        status = AVR1710Status()
        control_ok = True
        dlna_ok = True

        try:
            status.power_on = await self.get_power()
            if status.power_on:
                status.source = await self.get_source()
        except AVR1710ConnectionError:
            control_ok = False
            if previous is not None:
                status.power_on = previous.power_on
                status.source = previous.source

        try:
            status.volume = await self.get_volume()
            status.muted = await self.get_mute()
            status.transport_state = await self.get_transport_state()
        except AVR1710ConnectionError:
            dlna_ok = False
            if previous is not None:
                status.volume = previous.volume
                status.muted = previous.muted
                status.transport_state = previous.transport_state

        if not control_ok and not dlna_ok:
            raise AVR1710ConnectionError(f"Cannot reach {self._host} on either network surface")

        return status
