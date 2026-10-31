"""DataUpdateCoordinator for the Harman Kardon AVR 1710."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AVR1710Client, AVR1710ConnectionError, AVR1710ResponseError, AVR1710Status
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AVR1710Coordinator(DataUpdateCoordinator[AVR1710Status]):
    """Polls the TCP:10025 control port on a fixed interval."""

    def __init__(self, hass: HomeAssistant, client: AVR1710Client, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> AVR1710Status:
        try:
            return await self.client.async_update_status(previous=self.data)
        except (AVR1710ConnectionError, AVR1710ResponseError) as err:
            raise UpdateFailed(str(err)) from err
