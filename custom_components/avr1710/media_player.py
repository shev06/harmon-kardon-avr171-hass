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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, SOURCE_LIST
from .coordinator import AVR1710Coordinator

_LOGGER = logging.getLogger(__name__)

# DLNA AVTransport CurrentTransportState values -> Home Assistant states.
_TRANSPORT_STATE_MAP = {
    "PLAYING": MediaPlayerState.PLAYING,
    "PAUSED_PLAYBACK": MediaPlayerState.PAUSED,
    "STOPPED": MediaPlayerState.IDLE,
    "NO_MEDIA_PRESENT": MediaPlayerState.IDLE,
    "TRANSITIONING": MediaPlayerState.BUFFERING,
}

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
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
        status = self.coordinator.data
        if not status.is_likely_on:
            return MediaPlayerState.OFF
        if status.transport_state:
            return _TRANSPORT_STATE_MAP.get(status.transport_state, MediaPlayerState.ON)
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        volume = self.coordinator.data.volume
        return volume / 100 if volume is not None else None

    @property
    def is_volume_muted(self) -> bool | None:
        return self.coordinator.data.muted

    @property
    def source(self) -> str | None:
        return self.coordinator.data.source

    async def async_turn_on(self) -> None:
        await self.coordinator.client.set_power(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self.coordinator.client.set_power(False)
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        await self.coordinator.client.select_source(source)
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.client.set_volume(round(volume * 100))
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        await self.coordinator.client.send_command("volume-up")
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        await self.coordinator.client.send_command("volume-down")
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.client.set_mute(mute)
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self.coordinator.client.media_play()
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        await self.coordinator.client.media_pause()
        await self.coordinator.async_request_refresh()

    async def async_media_stop(self) -> None:
        await self.coordinator.client.media_stop()
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        await self.coordinator.client.media_next()
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        await self.coordinator.client.media_previous()
        await self.coordinator.async_request_refresh()
