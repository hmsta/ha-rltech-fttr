"""RLTech FTTR integration."""

from __future__ import annotations

import contextlib
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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

_STATIC_REGISTERED = False


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
                )
            ]
        )
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
