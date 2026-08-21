"""Config flow for RLTech FTTR."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

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
    CONF_ENABLE_HARDWARE_STATUS,
    CONF_LEGACY_HOSTS,
    CONF_LEGACY_PASSWORD,
    CONF_LEGACY_USERNAME,
    CONF_AP_AREA_ID,
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_STATION_POLLING,
    DEFAULT_BASE_URL,
    DEFAULT_USERNAME,
    DEFAULT_ENABLE_HARDWARE_STATUS,
    DEFAULT_ENABLE_AP_POLLING,
    DEFAULT_LEGACY_PASSWORD,
    DEFAULT_LEGACY_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_STATION_POLLING,
    DEFAULT_STATION_RETENTION,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    CONF_STATION_RETENTION,
)


def _base_url_to_host(value: str | None) -> str:
    """Return the host portion of a stored base URL for display in the form."""
    if not value:
        return _base_url_to_host(DEFAULT_BASE_URL)
    text = str(value).strip()
    if "://" in text:
        parsed = urlsplit(text)
        return parsed.hostname or parsed.netloc.split(":", 1)[0] or text
    if ":" in text and text.rsplit(":", 1)[1].isdigit():
        return text.rsplit(":", 1)[0]
    return text.rstrip("/")


def _entry_title(base_url: str) -> str:
    """Return a readable integration title for a normalized base URL."""
    return f"RLTech FTTR {_base_url_to_host(base_url)}"


def _host_to_base_url(value: str) -> str:
    """Normalize a host/IP form value to the fixed RLTech Web UI base URL."""
    text = str(value).strip().rstrip("/")
    if "://" in text:
        parsed = urlsplit(text)
        host = parsed.hostname or parsed.netloc.split(":", 1)[0]
    elif ":" in text and text.rsplit(":", 1)[1].isdigit():
        host = text.rsplit(":", 1)[0]
    else:
        host = text
    return f"http://{host}:8080"


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    password_selector = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )
    ap_area_key = vol.Optional(CONF_AP_AREA_ID)
    if defaults.get(CONF_AP_AREA_ID):
        ap_area_key = vol.Optional(
            CONF_AP_AREA_ID,
            default=defaults[CONF_AP_AREA_ID],
        )
    schema: dict[Any, Any] = {
        vol.Required(
            CONF_BASE_URL,
            default=_base_url_to_host(defaults.get(CONF_BASE_URL, DEFAULT_BASE_URL)),
        ): str,
        vol.Required(
            CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)
        ): str,
    }
    if CONF_PASSWORD in defaults:
        schema[vol.Optional(CONF_PASSWORD)] = password_selector
    else:
        schema[vol.Required(CONF_PASSWORD)] = password_selector
    schema.update(
        {
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
                default=defaults.get(
                    CONF_ENABLE_AP_POLLING, DEFAULT_ENABLE_AP_POLLING
                ),
            ): bool,
            vol.Optional(
                CONF_ENABLE_STATION_POLLING,
                default=defaults.get(
                    CONF_ENABLE_STATION_POLLING, DEFAULT_ENABLE_STATION_POLLING
                ),
            ): bool,
            vol.Optional(
                CONF_ENABLE_HARDWARE_STATUS,
                default=defaults.get(
                    CONF_ENABLE_HARDWARE_STATUS,
                    defaults.get("enable_olt_status", DEFAULT_ENABLE_HARDWARE_STATUS),
                ),
            ): bool,
            vol.Optional(
                CONF_LEGACY_USERNAME,
                default=defaults.get(CONF_LEGACY_USERNAME, DEFAULT_LEGACY_USERNAME),
            ): str,
            vol.Optional(CONF_LEGACY_PASSWORD): password_selector,
            vol.Optional(
                CONF_LEGACY_HOSTS,
                default=defaults.get(CONF_LEGACY_HOSTS, ""),
            ): str,
            ap_area_key: selector.AreaSelector(),
        }
    )
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
            user_input[CONF_BASE_URL] = _host_to_base_url(user_input[CONF_BASE_URL])
            if not user_input.get(CONF_LEGACY_PASSWORD):
                user_input[CONF_LEGACY_PASSWORD] = DEFAULT_LEGACY_PASSWORD
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
                    title=_entry_title(unique_id),
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
            user_input[CONF_BASE_URL] = _host_to_base_url(user_input[CONF_BASE_URL])
            if not user_input.get(CONF_PASSWORD):
                user_input = {
                    key: value
                    for key, value in user_input.items()
                    if key != CONF_PASSWORD
                }
            if not user_input.get(CONF_LEGACY_PASSWORD):
                user_input = {
                    key: value
                    for key, value in user_input.items()
                    if key != CONF_LEGACY_PASSWORD
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
                    title=_entry_title(unique_id),
                    data=data,
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(defaults),
            errors=errors,
        )
