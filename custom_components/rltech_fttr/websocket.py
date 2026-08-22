"""Websocket API for RLTech FTTR."""

from __future__ import annotations

from typing import Any, Callable

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SIGNAL_STATIONS_CHANGED
from .ap_inventory import ap_rows
from .identifiers import AP_SENSOR_KEYS, ap_sensor_unique_id
from .station_inventory import station_rows

_PAGE_SIZE_MAX = 1000


def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register RLTech FTTR websocket commands."""
    websocket_api.async_register_command(hass, websocket_get_entries)
    websocket_api.async_register_command(hass, websocket_get_stations)
    websocket_api.async_register_command(hass, websocket_subscribe_station_changes)
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
        vol.Optional("page", default=0): vol.Coerce(int),
        vol.Optional("page_size", default=0): vol.Coerce(int),
        vol.Optional("search", default=""): str,
        vol.Optional("sort_key", default="mac"): str,
        vol.Optional("sort_dir", default=1): vol.In([1, -1]),
        vol.Optional("filters", default={}): dict,
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

    rows = station_rows(coordinator.data)
    result = _table_result(
        rows,
        search=msg["search"],
        filters=msg["filters"],
        sort_key=msg["sort_key"],
        sort_dir=msg["sort_dir"],
        page=msg["page"],
        page_size=msg["page_size"],
        filter_specs={
            "ssid": ("SSID", lambda row: row.get("ssid")),
            "ap": ("AP", lambda row: row.get("ap_alias") or row.get("ap_mac")),
            "vlan": ("VLAN", lambda row: row.get("vlan")),
            "band": ("Band", lambda row: row.get("band")),
        },
        filter_predicates={
            "ssid": lambda row, value: row.get("ssid") == value,
            "ap": lambda row, value: (
                row.get("ap_alias") or row.get("ap_mac") or ""
            )
            == value,
            "vlan": lambda row, value: str(
                row.get("vlan") if row.get("vlan") is not None else ""
            )
            == value,
            "band": lambda row, value: row.get("band") == value,
            "online": lambda row, value: (
                "active" if row.get("reported_online") else "inactive"
            )
            == value,
        },
        sort_values={
            "reported_online": lambda row: "active"
            if row.get("reported_online")
            else "inactive",
        },
    )
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry_id,
            "stations": result["rows"],
            **{key: value for key, value in result.items() if key != "rows"},
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "rltech_fttr/subscribe_station_changes",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def websocket_subscribe_station_changes(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Subscribe to tiny station-inventory changed events for one config entry."""
    entry_id = msg["entry_id"]
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "Unknown RLTech FTTR config entry"
        )
        return

    @callback
    def forward_station_change(changed_at) -> None:
        connection.send_event(
            msg["id"],
            {
                "entry_id": entry_id,
                "changed_at": changed_at.isoformat() if changed_at else None,
            },
        )

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass,
        f"{SIGNAL_STATIONS_CHANGED}_{entry_id}",
        forward_station_change,
    )
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "rltech_fttr/get_access_points",
        vol.Required("entry_id"): str,
        vol.Optional("page", default=0): vol.Coerce(int),
        vol.Optional("page_size", default=0): vol.Coerce(int),
        vol.Optional("search", default=""): str,
        vol.Optional("sort_key", default="online"): str,
        vol.Optional("sort_dir", default=1): vol.In([1, -1]),
        vol.Optional("filters", default={}): dict,
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

    rows = ap_rows(
        coordinator.data,
        _ap_registry_info(hass, entry_id, coordinator.data),
    )
    result = _table_result(
        rows,
        search=msg["search"],
        filters=msg["filters"],
        sort_key=msg["sort_key"],
        sort_dir=msg["sort_dir"],
        page=msg["page"],
        page_size=msg["page_size"],
        filter_specs={
            "profile": ("Profile", lambda row: row.get("profile")),
            "model": ("Model", lambda row: row.get("model")),
            "uplink": ("Uplink", _uplink_label),
        },
        filter_predicates={
            "state": lambda row, value: (
                "online" if row.get("online") else "offline"
            )
            == value,
            "profile": lambda row, value: row.get("profile") == value,
            "model": lambda row, value: row.get("model") == value,
            "uplink": lambda row, value: _uplink_label(row) == value,
        },
        sort_values={
            "online": lambda row: 1 if row.get("online") else 0,
            "uplink_label": _uplink_label,
        },
    )
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry_id,
            "access_points": result["rows"],
            **{key: value for key, value in result.items() if key != "rows"},
        },
    )


def _table_result(
    rows: list[dict[str, Any]],
    *,
    search: str,
    filters: dict[str, Any],
    sort_key: str,
    sort_dir: int,
    page: int,
    page_size: int,
    filter_specs: dict[str, tuple[str, Callable[[dict[str, Any]], Any]]],
    filter_predicates: dict[str, Callable[[dict[str, Any], str], bool]],
    sort_values: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
) -> dict[str, Any]:
    """Return filtered, sorted, paginated table rows and filter options."""
    sort_values = sort_values or {}
    search_text = search.strip().lower()
    active_filters = {
        key: str(value)
        for key, value in filters.items()
        if value is not None and str(value) != ""
    }

    filtered = [
        row
        for row in rows
        if _matches_search(row, search_text)
        and all(
            filter_predicates[key](row, value)
            for key, value in active_filters.items()
            if key in filter_predicates
        )
    ]
    filtered.sort(
        key=lambda row: _sort_key(
            sort_values.get(sort_key, lambda item: item.get(sort_key))(row)
        ),
        reverse=sort_dir == -1,
    )

    page_size = max(0, min(_PAGE_SIZE_MAX, page_size))
    page = max(0, page)
    if page_size:
        page_count = max(1, (len(filtered) + page_size - 1) // page_size)
        page = min(page, page_count - 1)
        start = page * page_size
        paged = filtered[start : start + page_size]
    else:
        page_count = 1
        start = 0
        paged = filtered

    return {
        "rows": paged,
        "total": len(rows),
        "filtered": len(filtered),
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "filter_options": _filter_options(rows, filter_specs),
    }


def _matches_search(row: dict[str, Any], search: str) -> bool:
    """Return whether a row matches free-text search."""
    if not search:
        return True
    haystack = " ".join(
        str(value)
        for value in row.values()
        if value is not None and not isinstance(value, dict)
    ).lower()
    return search in haystack


def _filter_options(
    rows: list[dict[str, Any]],
    specs: dict[str, tuple[str, Callable[[dict[str, Any]], Any]]],
) -> dict[str, list[Any]]:
    """Return distinct filter option values."""
    return {
        key: sorted(
            {
                value
                for row in rows
                if (value := value_fn(row)) is not None and value != ""
            },
            key=lambda value: str(value).lower(),
        )
        for key, (_label, value_fn) in specs.items()
    }


def _sort_key(value: Any) -> tuple[int, Any]:
    """Normalize sort values with empty values last."""
    if value is None or value == "":
        return (1, "")
    if isinstance(value, bool):
        return (0, int(value))
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (0, str(value).lower())


def _uplink_label(row: dict[str, Any]) -> str:
    """Return AP uplink label for filtering and sorting."""
    uplink = row.get("uplink")
    if uplink is None:
        return ""
    port = "" if row.get("uplink_port") is None else f" {row['uplink_port']}"
    if uplink == 0:
        return f"LAN{port}"
    if uplink == 2:
        return f"LAN-PON{port}"
    return f"Uplink {uplink}{port}"


def _ap_registry_info(
    hass: HomeAssistant,
    entry_id: str,
    data,
) -> dict[str, dict[str, object]]:
    """Return current HA device/entity registry info, keyed by AP MAC."""
    if data is None:
        return {}

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entity_lookup = {
        entry.unique_id: entry.entity_id
        for entry in er.async_entries_for_config_entry(entity_registry, entry_id)
        if entry.domain == "sensor" and entry.platform == DOMAIN and entry.unique_id
    }
    device_lookup: dict[str, str] = {}
    for device in dr.async_entries_for_config_entry(device_registry, entry_id):
        for domain, identifier in device.identifiers:
            if domain == DOMAIN:
                device_lookup[identifier] = device.id

    result: dict[str, dict[str, object]] = {}
    for mac, ap in data.aps.items():
        entities: dict[str, str] = {}
        device_identifier = f"{entry_id}_ap_{ap.sn}" if ap.sn else None
        for key in AP_SENSOR_KEYS:
            unique_id = ap_sensor_unique_id(entry_id, ap, key)
            if unique_id is None:
                continue
            entity_id = entity_lookup.get(unique_id)
            if entity_id:
                entities[key] = entity_id
        result[mac] = {
            "device_id": device_lookup.get(device_identifier) if device_identifier else None,
            "entities": entities,
        }
    return result
