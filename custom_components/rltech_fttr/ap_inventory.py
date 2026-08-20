"""Access point inventory serialization for RLTech FTTR."""

from __future__ import annotations

from typing import Any

from .models import RltechAp, RltechApDetail, RltechData


def _detail_fields(detail: RltechApDetail | None) -> dict[str, Any]:
    if detail is None:
        return {}
    return {
        "detail_last_update": detail.last_update.isoformat() if detail.last_update else None,
        "optical_rx_power": detail.optical_rx_power,
        "optical_tx_power": detail.optical_tx_power,
        "downstream_optical_rx_power": detail.downstream_optical_rx_power,
        "optical_temperature": detail.optical_temperature,
        "optical_voltage": detail.optical_voltage,
        "optical_current": detail.optical_current,
        "ont_distance": detail.ont_distance,
        "last_down_cause": detail.last_down_cause,
        "last_up_time": detail.last_up_time,
        "last_down_time": detail.last_down_time,
        "last_dying_gasp_time": detail.last_dying_gasp_time,
        "onu_status": detail.onu_status,
        "cpu_usage": detail.cpu_usage,
        "cpu_temperature": detail.cpu_temperature,
        "memory_usage": detail.memory_usage,
        "flash_usage": detail.flash_usage,
        "sys_duration": detail.sys_duration,
    }


def ap_to_row(
    ap: RltechAp,
    registry_info: dict[str, Any] | None = None,
    detail: RltechApDetail | None = None,
) -> dict[str, Any]:
    """Return one AP row for UI/service use."""
    registry_info = registry_info or {}
    return {
        "device_id": registry_info.get("device_id"),
        "hardware_id": ap.sn,
        "mac": ap.mac,
        "alias": ap.alias,
        "ip": ap.ip,
        "online": ap.online,
        "model": ap.model,
        "version": ap.version,
        "profile": ap.profile,
        "profile_idx": ap.profile_idx,
        "channel_24": ap.channel_24,
        "channel_5": ap.channel_5,
        "bssid_24": ap.bssid_24,
        "bssid_5": ap.bssid_5,
        "assoc_count": ap.assoc_count,
        "uplink": ap.uplink,
        "uplink_port": ap.uplink_port,
        "sn": ap.sn,
        "dev_sn": ap.dev_sn,
        "upgrade_flag": ap.upgrade_flag,
        "entities": registry_info.get("entities") or {},
        **_detail_fields(detail),
    }


def ap_rows(
    data: RltechData | None,
    registry_info: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return stable, sorted AP rows from coordinator data."""
    if data is None:
        return []
    return [
        ap_to_row(ap, (registry_info or {}).get(ap.mac), data.ap_details.get(ap.mac))
        for ap in sorted(
            data.aps.values(), key=lambda item: ((item.alias or "").lower(), item.mac)
        )
    ]
