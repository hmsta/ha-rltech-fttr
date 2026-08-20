"""Coordinator for RLTech FTTR."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components import dhcp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import AccountBusyError, AuthenticationError, RltechClient
from .const import (
    CONF_BASE_URL,
    CONF_AP_DETAIL_INTERVAL,
    CONF_ENABLE_AP_DETAIL_POLLING,
    CONF_ENABLE_AP_POLLING,
    CONF_ENABLE_OLT_STATUS,
    CONF_ENABLE_LAN_PORT_STATUS,
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_STATION_POLLING,
    DEFAULT_AP_DETAIL_INTERVAL,
    DEFAULT_ENABLE_AP_DETAIL_POLLING,
    DEFAULT_ENABLE_AP_POLLING,
    DEFAULT_ENABLE_OLT_STATUS,
    DEFAULT_ENABLE_LAN_PORT_STATUS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_STATION_POLLING,
    DEFAULT_STATION_RETENTION,
    DOMAIN,
    CONF_STATION_RETENTION,
)
from .dhcp_enrichment import clean_hostname, enrich_station_hostnames, normalize_lookup_mac
from .models import RltechData

_LOGGER = logging.getLogger(__name__)


class RltechCoordinator(DataUpdateCoordinator[RltechData]):
    """Data update coordinator for RLTech FTTR."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: RltechClient,
    ) -> None:
        self.config_entry = entry
        self.client = client
        self._last_data: RltechData | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )

    async def _async_update_data(self) -> RltechData:
        """Fetch FTTR data from the OLT."""
        session = async_get_clientsession(self.hass)
        try:
            data = await self.client.fetch_snapshot(
                session,
                previous=self._last_data,
                station_retention=self.config_entry.data.get(
                    CONF_STATION_RETENTION, DEFAULT_STATION_RETENTION
                ),
                include_ap_inventory=self.config_entry.data.get(
                    CONF_ENABLE_AP_POLLING, DEFAULT_ENABLE_AP_POLLING
                ),
                include_station_inventory=self.config_entry.data.get(
                    CONF_ENABLE_STATION_POLLING, DEFAULT_ENABLE_STATION_POLLING
                ),
                include_olt_status=self.config_entry.data.get(
                    CONF_ENABLE_OLT_STATUS, DEFAULT_ENABLE_OLT_STATUS
                ),
                include_lan_port_status=self.config_entry.data.get(
                    CONF_ENABLE_LAN_PORT_STATUS, DEFAULT_ENABLE_LAN_PORT_STATUS
                ),
                include_ap_details=self.config_entry.data.get(
                    CONF_ENABLE_AP_DETAIL_POLLING, DEFAULT_ENABLE_AP_DETAIL_POLLING
                ),
                ap_detail_interval=self.config_entry.data.get(
                    CONF_AP_DETAIL_INTERVAL, DEFAULT_AP_DETAIL_INTERVAL
                ),
                scan_interval=self.config_entry.data.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
            )
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except AccountBusyError as err:
            _LOGGER.warning("RLTech Web UI account is already in use: %s", err)
            raise UpdateFailed("RLTech Web UI account is already in use") from err
        except Exception as err:
            raise UpdateFailed(f"Unable to fetch RLTech FTTR data: {err}") from err
        data = enrich_station_hostnames(data, *_dhcp_hostname_lookup(self.hass))
        self._last_data = data
        return data


def build_client(entry: ConfigEntry) -> RltechClient:
    """Build an API client from a config entry."""
    return RltechClient(
        entry.data[CONF_BASE_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )


def _dhcp_hostname_lookup(hass: HomeAssistant) -> tuple[dict[str, str], dict[str, str]]:
    """Build DHCP hostname lookup maps once for a coordinator poll."""
    by_mac: dict[str, str] = {}
    by_ip: dict[str, str] = {}

    try:
        infos = dhcp.async_discovered_service_info(hass)
    except Exception as err:  # pragma: no cover - defensive around HA internals
        _LOGGER.debug("Unable to read Home Assistant DHCP discovery cache: %s", err)
        return by_mac, by_ip

    for info in infos:
        hostname = clean_hostname(_info_value(info, "hostname"))
        if hostname is None:
            continue

        mac = normalize_lookup_mac(_info_value(info, "macaddress"))
        if mac:
            by_mac[mac] = hostname

        ip = _info_value(info, "ip")
        if ip:
            by_ip[str(ip)] = hostname

    return by_mac, by_ip


def _info_value(info, key: str):
    """Return a DHCP discovery value from object or dict-like info."""
    if isinstance(info, dict):
        return info.get(key)
    return getattr(info, key, None)
