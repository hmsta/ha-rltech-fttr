"""Stable identifiers for RLTech FTTR objects."""

from __future__ import annotations

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
)


def ap_hardware_id(ap: RltechAp | None) -> str | None:
    """Return the AP hardware identity used for HA device/entity identity."""
    return ap.sn if ap is not None else None


def ap_sensor_unique_id(entry_id: str, ap: RltechAp | None, key: str) -> str | None:
    """Return the unique ID for an AP sensor."""
    hardware_id = ap_hardware_id(ap)
    if hardware_id is None:
        return None
    return f"{entry_id}_ap_{hardware_id}_{key}"
