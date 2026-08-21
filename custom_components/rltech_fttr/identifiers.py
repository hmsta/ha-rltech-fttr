"""Stable identifiers for RLTech FTTR objects."""

from __future__ import annotations

import re

from .models import RltechAp

AP_SENSOR_KEYS = (
    "online",
    "assoc_count",
    "profile",
    "alias",
    "optical_rx_power",
    "optical_tx_power",
    "reg_off_time",
    "last_down_cause",
    "source_host",
    "cpu_usage",
    "cpu_temperature",
    "memory_usage",
    "flash_usage",
    "last_boot",
)


def object_id_slug(value: str) -> str:
    """Return a deterministic HA object-id slug."""
    text = re.sub(r"[^a-z0-9_]+", "_", value.lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def controller_sensor_object_id(host: str, key: str) -> str:
    """Return the object ID for a controller-owned sensor."""
    return f"rltech_olt_{object_id_slug(host)}_{key}"


def ap_sensor_object_id(ap: RltechAp | None, key: str) -> str | None:
    """Return the object ID for an AP sensor."""
    hardware_id = ap_hardware_id(ap)
    if hardware_id is None:
        return None
    return f"rltech_ap_{object_id_slug(hardware_id)}_{key}"


def lan_port_sensor_object_id(host: str, label: str, key: str) -> str:
    """Return the object ID for a LAN/LAN-PON link sensor."""
    return f"rltech_olt_{object_id_slug(host)}_{object_id_slug(label)}_{key}"


def ap_hardware_id(ap: RltechAp | None) -> str | None:
    """Return the AP hardware identity used for HA device/entity identity."""
    return ap.sn if ap is not None else None


def ap_sensor_unique_id(entry_id: str, ap: RltechAp | None, key: str) -> str | None:
    """Return the unique ID for an AP sensor."""
    hardware_id = ap_hardware_id(ap)
    if hardware_id is None:
        return None
    return f"{entry_id}_ap_{hardware_id}_{key}"
