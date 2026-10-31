"""Media player platform for the Harman Kardon AVR 1710."""
from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AVR1710ConnectionError
from .const import DOMAIN, MANUFACTURER, MODEL, SOURCE_LIST
from .coordinator import AVR1710Coordinator

_LOGGER = logging.getLogger(__name__)

# No VOLUME_SET: the dispatcher only has relative volume-up/volume-down
# step commands, not an absolute "set volume to X" command. No STOP: no
# stop command exists anywhere in the dispatcher's command table. Both
# would have to be faked (e.g. stop mapped to pause) to support, which
# this integration deliberately avoids -- see api.py's module docstring.
SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AVR1710Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AVR1710MediaPlayer(coordinator, entry)])


class AVR1710MediaPlayer(CoordinatorEntity[AVR1710Coordinator], MediaPlayerEntity):
    """Representation of the AVR 1710 as a Home Assistant media player."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_source_list = SOURCE_LIST
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, coordinator: AVR1710Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_media_player"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def state(self) -> MediaPlayerState:
        # No DLNA transport-state readback anymore (see api.py), so this can
        # only distinguish ON/OFF -- not PLAYING/PAUSED/IDLE.
        return MediaPlayerState.ON if self.coordinator.data.is_likely_on else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        return self.coordinator.data.volume_level

    @property
    def is_volume_muted(self) -> bool | None:
        return self.coordinator.data.is_volume_muted

    @property
    def source(self) -> str | None:
        return self.coordinator.data.source

    async def _async_call(self, action, description: str) -> None:
        """Run a client action, converting connection failures into a visible HA error.

        Without this, a genuine failure (e.g. an external client holding the
        receiver's single TCP:10025 connection slot for a long time) would
        raise AVR1710ConnectionError straight out of a service call, which
        Home Assistant does surface, but with a confusing internal message.
        This re-raises it as a clear, user-facing HomeAssistantError instead.
        """
        try:
            await action
        except AVR1710ConnectionError as err:
            raise HomeAssistantError(f"Harman Kardon AVR 1710: failed to {description}: {err}") from err

    async def async_turn_on(self) -> None:
        await self._async_call(self.coordinator.client.set_power(True), "turn on")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self._async_call(self.coordinator.client.set_power(False), "turn off")
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        await self._async_call(self.coordinator.client.select_source(source), f"select source {source!r}")
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        await self._async_call(self.coordinator.client.volume_up(), "increase volume")
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        await self._async_call(self.coordinator.client.volume_down(), "decrease volume")
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        await self._async_call(self.coordinator.client.set_mute(mute), "set mute")
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self._async_call(self.coordinator.client.media_play(), "play")
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        await self._async_call(self.coordinator.client.media_pause(), "pause")
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        await self._async_call(self.coordinator.client.media_next(), "skip to next track")
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        await self._async_call(self.coordinator.client.media_previous(), "skip to previous track")
        await self.coordinator.async_request_refresh()
