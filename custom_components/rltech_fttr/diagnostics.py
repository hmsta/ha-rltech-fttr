"""Diagnostics for RLTech FTTR."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

DOMAIN = "rltech_fttr"

REDACTED = "***REDACTED***"
REDACT_KEYS = {
    "password",
    "username",
    "base_url",
    "ecnttoken",
    "token",
    "cookie",
    "cookies",
    "headers",
    "raw_html",
    "html",
    "mac",
    "ip",
    "hostname",
    "ssid",
    "bssid_24",
    "bssid_5",
    "sn",
    "dev_sn",
    "serial_number",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if str(key).lower() in REDACT_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: "HomeAssistant", entry: "ConfigEntry"
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = coordinator.data if coordinator is not None else None
    summary = None
    if data is not None:
        summary = {
            "ap_count": len(data.aps),
            "ap_detail_count": len(data.ap_details),
            "online_ap_count": sum(1 for ap in data.aps.values() if ap.online),
            "station_count": len(data.stations),
            "lan_port_count": len(data.lan_ports),
            "lanpon_port_count": len(data.lanpon_ports),
            "reported_station_count": sum(
                1 for station in data.stations.values() if station.reported_online
            ),
            "last_success": data.last_success.isoformat()
            if data.last_success
            else None,
            "poll_duration_ms": data.poll_duration_ms,
            "olt_status_present": data.olt_status is not None,
            "olt_status_fields": sorted(
                key
                for key, value in vars(data.olt_status).items()
                if value is not None
            )
            if data.olt_status is not None
            else [],
            "ap_detail_fields": sorted(
                {
                    key
                    for detail in data.ap_details.values()
                    for key, value in vars(detail).items()
                    if value is not None
                    and key
                    not in {
                        "mac",
                        "ip",
                        "hostname",
                        "sn",
                        "dev_sn",
                        "pon_sn",
                        "sn_address",
                    }
                }
            ),
        }
    return _redact(
        {
            "entry": {
                "base_url": entry.data.get("base_url"),
                "username": entry.data.get("username"),
                "scan_interval": entry.data.get("scan_interval"),
                "station_retention": entry.data.get("station_retention"),
                "enable_ap_polling": entry.data.get("enable_ap_polling"),
                "enable_station_polling": entry.data.get("enable_station_polling"),
                "enable_olt_status": entry.data.get("enable_olt_status"),
                "enable_lan_port_status": entry.data.get("enable_lan_port_status"),
                "enable_ap_detail_polling": entry.data.get("enable_ap_detail_polling"),
                "ap_detail_interval": entry.data.get("ap_detail_interval"),
                "password": entry.data.get("password"),
            },
            "summary": summary,
        }
    )
