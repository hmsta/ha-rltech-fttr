"""Websocket API for RLTech FTTR."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .ap_inventory import ap_rows
from .identifiers import AP_SENSOR_KEYS, ap_sensor_unique_id
from .station_inventory import station_rows


def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register RLTech FTTR websocket commands."""
    websocket_api.async_register_command(hass, websocket_get_entries)
    websocket_api.async_register_command(hass, websocket_get_stations)
    websocket_api.async_register_command(hass, websocket_get_access_points)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "rltech_fttr/get_entries",
    }
)
@websocket_api.async_response
async def websocket_get_entries(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return loaded RLTech FTTR config entries for card auto-configuration."""
    coordinators = hass.data.get(DOMAIN, {})
    entries = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id not in coordinators:
            continue
        entries.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
            }
        )

    connection.send_result(msg["id"], {"entries": entries})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "rltech_fttr/get_stations",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_stations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return latest station inventory rows for one config entry."""
    entry_id = msg["entry_id"]
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Unknown RLTech FTTR config entry"
        )
        return

    connection.send_result(
        msg["id"],
        {
            "entry_id": entry_id,
            "stations": station_rows(coordinator.data),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "rltech_fttr/get_access_points",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_access_points(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return latest AP inventory rows for one config entry."""
    entry_id = msg["entry_id"]
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Unknown RLTech FTTR config entry"
        )
        return

    connection.send_result(
        msg["id"],
        {
            "entry_id": entry_id,
            "access_points": ap_rows(
                coordinator.data,
                _ap_entity_ids(hass, entry_id, coordinator.data),
            ),
        },
    )


def _ap_entity_ids(hass: HomeAssistant, entry_id: str, data) -> dict[str, dict[str, str]]:
    """Return current HA entity IDs for AP sensors, keyed by AP MAC and sensor key."""
    if data is None:
        return {}

    registry = er.async_get(hass)
    result: dict[str, dict[str, str]] = {}
    for mac, ap in data.aps.items():
        entities: dict[str, str] = {}
        for key in AP_SENSOR_KEYS:
            unique_id = ap_sensor_unique_id(entry_id, ap, key)
            if unique_id is None:
                continue
            entity_id = registry.async_get_entity_id(
                "sensor",
                DOMAIN,
                unique_id,
            )
            if entity_id:
                entities[key] = entity_id
        result[mac] = entities
    return result
