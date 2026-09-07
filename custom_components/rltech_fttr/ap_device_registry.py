"""Helpers for syncing AP device registry metadata."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlunsplit

from .models import RltechAp


def ap_configuration_url(ap: RltechAp) -> str | None:
    """Return the AP web UI URL when the AP has an IP address."""
    if not ap.ip:
        return None
    return urlunsplit(("http", ap.ip, "", "", ""))


def ap_device_registry_updates(
    ap: RltechAp,
    device: Any,
    *,
    controller_device_id: str | None,
    area_id: str | None = None,
) -> dict[str, Any]:
    """Return safe AP device registry updates for mutable metadata only."""
    updates: dict[str, Any] = {}

    if ap.version and getattr(device, "sw_version", None) != ap.version:
        updates["sw_version"] = ap.version

    configuration_url = ap_configuration_url(ap)
    if (
        configuration_url
        and getattr(device, "configuration_url", None) != configuration_url
    ):
        updates["configuration_url"] = configuration_url

    if (
        controller_device_id
        and getattr(device, "via_device_id", None) != controller_device_id
    ):
        updates["via_device_id"] = controller_device_id

    if area_id and getattr(device, "area_id", None) is None:
        updates["area_id"] = area_id

    return updates
