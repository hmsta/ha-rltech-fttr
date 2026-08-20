"""RLTech FTTR integration."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import (
    CONF_RESOURCE_TYPE_WS,
    LOVELACE_DATA,
    MODE_STORAGE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AP_CARD_FILENAME,
    AP_CARD_URL,
    DOMAIN,
    PLATFORMS,
    STATION_CARD_FILENAME,
    STATION_CARD_URL,
)
from .coordinator import RltechCoordinator, build_client
from .websocket import async_setup_websocket

_LOGGER = logging.getLogger(__name__)
_STATIC_REGISTERED = False
_CARD_RESOURCES = (STATION_CARD_URL, AP_CARD_URL)


def _get_lovelace_data(hass: HomeAssistant):
    """Return Lovelace data across supported Home Assistant versions."""
    return hass.data.get(LOVELACE_DATA) or hass.data.get("lovelace")


@callback
def _lovelace_resource_collection(lovelace_data):
    """Return the Lovelace resource collection from dataclass or legacy dict data."""
    if lovelace_data is None:
        return None
    if isinstance(lovelace_data, dict):
        return lovelace_data.get("resources")
    return getattr(lovelace_data, "resources", None)


@callback
def _lovelace_resource_mode(lovelace_data) -> str | None:
    """Return the Lovelace resource mode from dataclass or legacy dict data."""
    if lovelace_data is None:
        return None
    if isinstance(lovelace_data, dict):
        return lovelace_data.get("resource_mode") or lovelace_data.get("mode")
    return getattr(lovelace_data, "resource_mode", None)


async def _ensure_lovelace_card_resources(hass: HomeAssistant) -> None:
    """Register bundled custom cards with Lovelace storage resources."""
    lovelace_data = _get_lovelace_data(hass)
    resources = _lovelace_resource_collection(lovelace_data)
    if resources is None:
        _LOGGER.debug("Lovelace resources are not available yet")
        return

    if _lovelace_resource_mode(lovelace_data) != MODE_STORAGE:
        _LOGGER.info(
            "Lovelace resources are not in storage mode; add RLTech FTTR card "
            "resources manually in Lovelace YAML configuration"
        )
        return

    try:
        await resources.async_get_info()
    except Exception:
        _LOGGER.exception("Unable to load Lovelace resources")
        return

    existing_urls = {
        str(item.get(CONF_URL, "")).split("?", 1)[0]
        for item in resources.async_items()
    }
    for url in _CARD_RESOURCES:
        if url in existing_urls:
            continue
        await resources.async_create_item(
            {CONF_RESOURCE_TYPE_WS: "module", CONF_URL: url}
        )
        _LOGGER.info("Registered RLTech FTTR Lovelace resource: %s", url)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RLTech FTTR from a config entry."""
    global _STATIC_REGISTERED
    if not _STATIC_REGISTERED:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATION_CARD_URL,
                    str(Path(__file__).parent / "www" / STATION_CARD_FILENAME),
                    True,
                ),
                StaticPathConfig(
                    AP_CARD_URL,
                    str(Path(__file__).parent / "www" / AP_CARD_FILENAME),
                    True,
                ),
            ]
        )
        await _ensure_lovelace_card_resources(hass)
        async_setup_websocket(hass)
        _STATIC_REGISTERED = True

    client = build_client(entry)
    coordinator = RltechCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an RLTech FTTR config entry."""
    coordinator: RltechCoordinator = hass.data[DOMAIN][entry.entry_id]
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    with contextlib.suppress(Exception):
        await coordinator.client.logout(async_get_clientsession(hass))
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
