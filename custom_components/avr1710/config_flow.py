"""Config flow for the Harman Kardon AVR 1710 integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .api import AVR1710Client, AVR1710ConnectionError
from .const import CONF_CONTROL_PORT, CONTROL_PORT_DEFAULT, DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Optional(CONF_CONTROL_PORT, default=CONTROL_PORT_DEFAULT): int,
    }
)


async def _validate_input(data: dict[str, Any]) -> None:
    """Confirm the control port is reachable."""
    client = AVR1710Client(
        host=data[CONF_HOST],
        control_port=data.get(CONF_CONTROL_PORT, CONTROL_PORT_DEFAULT),
    )
    await client.async_update_status()


class AVR1710ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Harman Kardon AVR 1710."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            try:
                await _validate_input(user_input)
            except AVR1710ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - surface any unexpected error to the UI
                _LOGGER.exception("Unexpected exception during AVR1710 setup")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)
