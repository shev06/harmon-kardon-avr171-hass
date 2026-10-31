"""Remote platform for the Harman Kardon AVR 1710 -- raw button passthrough.

Exposes every simple, no-argument command from the reverse-engineered
TCP:10025 dispatcher that isn't already covered by the media_player
platform (power/volume/mute/source/transport). Use via, e.g.:

    service: remote.send_command
    target:
      entity_id: remote.avr_1710
    data:
      command: home
"""
from __future__ import annotations

from typing import Any, Iterable

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AVR1710ConnectionError
from .const import DOMAIN, MANUFACTURER, MODEL, REMOTE_COMMANDS
from .coordinator import AVR1710Coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AVR1710Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AVR1710Remote(coordinator, entry)])


class AVR1710Remote(CoordinatorEntity[AVR1710Coordinator], RemoteEntity):
    """Raw remote-button passthrough for commands not modeled as media_player features."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: AVR1710Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_remote"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.is_likely_on

    async def _async_call(self, action, description: str) -> None:
        """Run a client action, converting connection failures into a visible HA error."""
        try:
            await action
        except AVR1710ConnectionError as err:
            raise HomeAssistantError(f"Harman Kardon AVR 1710: failed to {description}: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_call(self.coordinator.client.set_power(True), "turn on")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_call(self.coordinator.client.set_power(False), "turn off")
        await self.coordinator.async_request_refresh()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        for single in command:
            if single not in REMOTE_COMMANDS:
                raise ValueError(f"Unknown command {single!r}; valid commands: {', '.join(REMOTE_COMMANDS)}")
            await self._async_call(self.coordinator.client.send_button(single), f"send command {single!r}")
        await self.coordinator.async_request_refresh()
