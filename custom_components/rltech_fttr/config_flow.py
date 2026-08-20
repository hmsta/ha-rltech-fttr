"""Config flow for RLTech FTTR."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AccountBusyError, AuthenticationError, RltechClient
from .const import (
    CONF_BASE_URL,
    CONF_ENABLE_AP_POLLING,
    CONF_ENABLE_AP_DETAIL_POLLING,
    CONF_ENABLE_OLT_STATUS,
    CONF_ENABLE_LAN_PORT_STATUS,
    CONF_AP_DETAIL_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_STATION_POLLING,
    DEFAULT_BASE_URL,
    DEFAULT_AP_DETAIL_INTERVAL,
    DEFAULT_ENABLE_AP_DETAIL_POLLING,
    DEFAULT_ENABLE_AP_POLLING,
    DEFAULT_ENABLE_OLT_STATUS,
    DEFAULT_ENABLE_LAN_PORT_STATUS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_STATION_POLLING,
    DEFAULT_STATION_RETENTION,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    MIN_AP_DETAIL_INTERVAL,
    CONF_STATION_RETENTION,
)


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    password_selector = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )
    schema: dict[Any, Any] = {
        vol.Required(
            CONF_BASE_URL, default=defaults.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        ): str,
        vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
        vol.Optional(
            CONF_SCAN_INTERVAL,
            default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
        vol.Optional(
            CONF_STATION_RETENTION,
            default=defaults.get(CONF_STATION_RETENTION, DEFAULT_STATION_RETENTION),
        ): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(
            CONF_ENABLE_AP_POLLING,
            default=defaults.get(CONF_ENABLE_AP_POLLING, DEFAULT_ENABLE_AP_POLLING),
        ): bool,
        vol.Optional(
            CONF_ENABLE_STATION_POLLING,
            default=defaults.get(
                CONF_ENABLE_STATION_POLLING, DEFAULT_ENABLE_STATION_POLLING
            ),
        ): bool,
        vol.Optional(
            CONF_ENABLE_OLT_STATUS,
            default=defaults.get(CONF_ENABLE_OLT_STATUS, DEFAULT_ENABLE_OLT_STATUS),
        ): bool,
        vol.Optional(
            CONF_ENABLE_LAN_PORT_STATUS,
            default=defaults.get(
                CONF_ENABLE_LAN_PORT_STATUS, DEFAULT_ENABLE_LAN_PORT_STATUS
            ),
        ): bool,
        vol.Optional(
            CONF_ENABLE_AP_DETAIL_POLLING,
            default=defaults.get(
                CONF_ENABLE_AP_DETAIL_POLLING, DEFAULT_ENABLE_AP_DETAIL_POLLING
            ),
        ): bool,
        vol.Optional(
            CONF_AP_DETAIL_INTERVAL,
            default=defaults.get(CONF_AP_DETAIL_INTERVAL, DEFAULT_AP_DETAIL_INTERVAL),
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_AP_DETAIL_INTERVAL)),
    }
    if CONF_PASSWORD in defaults:
        schema[vol.Optional(CONF_PASSWORD)] = password_selector
    else:
        schema[vol.Required(CONF_PASSWORD)] = password_selector
    return vol.Schema(schema)


async def _validate_input(hass, user_input: dict[str, Any]) -> None:
    """Validate credentials by doing one short login/logout."""
    session = async_get_clientsession(hass)
    client = RltechClient(
        user_input[CONF_BASE_URL],
        user_input[CONF_USERNAME],
        user_input[CONF_PASSWORD],
    )
    try:
        await client.login(session)
    finally:
        await client.logout(session)


class RltechConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle RLTech FTTR config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            unique_id = user_input[CONF_BASE_URL].rstrip("/")
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            try:
                await _validate_input(self.hass, user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except AccountBusyError:
                errors["base"] = "account_busy"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"RLTech FTTR {unique_id}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors: dict[str, str] = {}
        defaults = {**entry.data}

        if user_input is not None:
            if not user_input.get(CONF_PASSWORD):
                user_input = {
                    key: value
                    for key, value in user_input.items()
                    if key != CONF_PASSWORD
                }
            data = {**entry.data, **user_input}
            unique_id = data[CONF_BASE_URL].rstrip("/")
            if unique_id != entry.unique_id:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
            try:
                await _validate_input(self.hass, data)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except AccountBusyError:
                errors["base"] = "account_busy"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    unique_id=unique_id,
                    title=f"RLTech FTTR {unique_id}",
                    data=data,
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(defaults),
            errors=errors,
        )
