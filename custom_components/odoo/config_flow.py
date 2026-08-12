"""Config flow for the Odoo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    AMOUNT_TYPES,
    CONF_AMOUNT_TYPE,
    CONF_API_KEY,
    CONF_CURRENCY,
    CONF_DB,
    CONF_RESET_DELAY,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_AMOUNT_TYPE,
    DEFAULT_CURRENCY,
    DEFAULT_RESET_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .odoo_client import OdooAuthError, OdooClient, OdooConnectionError

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_DB): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_API_KEY): str,
        vol.Optional(CONF_CURRENCY, default=DEFAULT_CURRENCY): str,
        vol.Optional(CONF_AMOUNT_TYPE, default=DEFAULT_AMOUNT_TYPE): vol.In(
            AMOUNT_TYPES
        ),
    }
)


async def _test_connection(hass: HomeAssistant, data: dict[str, Any]) -> None:
    client = OdooClient(
        data[CONF_URL], data[CONF_DB], data[CONF_USERNAME], data[CONF_API_KEY]
    )
    await hass.async_add_executor_job(client.authenticate)


class OdooConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Odoo config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _test_connection(self.hass, user_input)
            except OdooAuthError:
                errors["base"] = "invalid_auth"
            except OdooConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while testing the Odoo connection")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_URL]}-{user_input[CONF_DB]}-{user_input[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Odoo ({user_input[CONF_DB]})", data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OdooOptionsFlow:
        return OdooOptionsFlow(config_entry)


class OdooOptionsFlow(config_entries.OptionsFlow):
    """Options: refresh interval and binary_sensor reset delay."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=60)),
                vol.Optional(
                    CONF_RESET_DELAY,
                    default=options.get(CONF_RESET_DELAY, DEFAULT_RESET_DELAY),
                ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
