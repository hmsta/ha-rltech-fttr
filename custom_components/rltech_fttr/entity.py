"""Base entities for RLTech FTTR."""

from __future__ import annotations

from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import RltechCoordinator
from .models import RltechAp, RltechOltStatus


class RltechEntity(CoordinatorEntity[RltechCoordinator]):
    """Base coordinator entity."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, coordinator: RltechCoordinator) -> None:
        super().__init__(coordinator)
        self.config_entry = entry


def _base_url_to_host(value: str) -> str:
    """Return the host portion of a normalized base URL."""
    parsed = urlsplit(value)
    return parsed.hostname or parsed.netloc.split(":", 1)[0] or value


def controller_device_info(
    entry: ConfigEntry,
    status: RltechOltStatus | None = None,
) -> DeviceInfo:
    """Return controller device info."""
    base_url = entry.data[CONF_BASE_URL].rstrip("/")
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=status.manufacturer if status and status.manufacturer else "RLTech",
        name=f"RLTech FTTR {_base_url_to_host(base_url)}",
        model=status.gateway_type if status else None,
        hw_version=status.hardware_version if status else None,
        sw_version=status.software_version if status else None,
        serial_number=status.serial_number if status else None,
        configuration_url=base_url,
    )


def ap_device_info(entry: ConfigEntry, mac: str, ap: RltechAp | None) -> DeviceInfo:
    """Return AP device info."""
    hardware_id = ap.sn if ap else None
    configuration_url = urlunsplit(("http", ap.ip, "", "", "")) if ap and ap.ip else None
    return DeviceInfo(
        connections={(dr.CONNECTION_NETWORK_MAC, mac)},
        identifiers={(DOMAIN, f"{entry.entry_id}_ap_{hardware_id}")},
        manufacturer="RLTech",
        name=f"RLTech AP {ap.alias}" if ap and ap.alias else f"RLTech AP {hardware_id or mac}",
        model=ap.model if ap else None,
        sw_version=ap.version if ap else None,
        serial_number=ap.sn if ap else None,
        configuration_url=configuration_url,
        via_device=(DOMAIN, entry.entry_id),
    )
