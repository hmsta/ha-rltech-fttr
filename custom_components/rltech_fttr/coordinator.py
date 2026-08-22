"""Coordinator for RLTech FTTR."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AccountBusyError, AuthenticationError, RltechClient
from .const import (
    CONF_BASE_URL,
    CONF_ENABLE_AP_POLLING,
    CONF_ENABLE_HARDWARE_STATUS,
    CONF_ENABLE_MQTT,
    CONF_LEGACY_HOSTS,
    CONF_LEGACY_PASSWORD,
    CONF_LEGACY_USERNAME,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_PSK,
    CONF_MQTT_PSK_IDENTITY,
    CONF_MQTT_USERNAME,
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_STATION_POLLING,
    CONF_AP_PASSWORD,
    CONF_AP_USERNAME,
    DEFAULT_ENABLE_HARDWARE_STATUS,
    DEFAULT_ENABLE_AP_POLLING,
    DEFAULT_AP_PASSWORD,
    DEFAULT_AP_USERNAME,
    DEFAULT_DHCP_HOSTNAME_REFRESH_INTERVAL,
    DEFAULT_ENABLE_MQTT,
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_MQTT_PORT,
    DEFAULT_MQTT_PSK_IDENTITY,
    DEFAULT_MQTT_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_STATION_POLLING,
    DEFAULT_STATION_RETENTION,
    DOMAIN,
    SIGNAL_STATIONS_CHANGED,
    CONF_STATION_RETENTION,
)
from .hostname_enrichment import enrich_from_home_assistant_dhcp
from .models import RltechData
from .mqtt import (
    MqttApHealthUpdate,
    MqttApStatusUpdate,
    MqttStationUpdate,
    RltechMqttManager,
    RltechMqttStats,
    merge_ap_health_update,
    merge_ap_status_update,
    merge_station_updates,
    preserve_live_overlay,
)
from .oui_enrichment import enrich_station_vendors

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
        self._mqtt_manager: RltechMqttManager | None = None
        self.mqtt_stats = RltechMqttStats(
            enabled=entry.data.get(CONF_ENABLE_MQTT, DEFAULT_ENABLE_MQTT)
        )
        self._last_mqtt_hostname_enrichment: datetime | None = None
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
        previous = self._last_data
        try:
            data = await self.client.fetch_snapshot(
                session,
                previous=previous,
                station_retention=self.config_entry.data.get(
                    CONF_STATION_RETENTION, DEFAULT_STATION_RETENTION
                ),
                include_ap_inventory=self.config_entry.data.get(
                    CONF_ENABLE_AP_POLLING, DEFAULT_ENABLE_AP_POLLING
                ),
                include_station_inventory=self.config_entry.data.get(
                    CONF_ENABLE_STATION_POLLING, DEFAULT_ENABLE_STATION_POLLING
                ),
                include_hardware_status=self.config_entry.data.get(
                    CONF_ENABLE_HARDWARE_STATUS,
                    DEFAULT_ENABLE_HARDWARE_STATUS,
                ),
                scan_interval=self.config_entry.data.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
                local_timezone=dt_util.DEFAULT_TIME_ZONE,
            )
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except AccountBusyError as err:
            _LOGGER.warning("RLTech Web UI account is already in use: %s", err)
            if self._last_data is not None:
                return self._last_data
            raise UpdateFailed("RLTech Web UI account is already in use") from err
        except Exception as err:
            raise UpdateFailed(f"Unable to fetch RLTech FTTR data: {err}") from err
        try:
            data = enrich_from_home_assistant_dhcp(self.hass, data)
        except Exception as err:  # pragma: no cover - defensive around HA internals
            _LOGGER.debug("Unable to enrich station hostnames from DHCP cache: %s", err)
        data = enrich_station_vendors(data)
        current = self._last_data
        if current is not None and current is not previous:
            data = preserve_live_overlay(current, data, previous)
            data = enrich_station_vendors(data)
        self._last_data = data
        return data

    async def async_start_mqtt(self) -> None:
        """Start optional MQTT live overlay after the first HTTP baseline."""
        self.mqtt_stats.enabled = self.config_entry.data.get(
            CONF_ENABLE_MQTT, DEFAULT_ENABLE_MQTT
        )
        if not self.mqtt_stats.enabled:
            return
        psk = str(self.config_entry.data.get(CONF_MQTT_PSK) or "").strip()
        if not psk:
            self.mqtt_stats.last_error = "MQTT PSK is not configured"
            return
        self._mqtt_manager = build_mqtt_manager(self.config_entry, self)
        self._mqtt_manager.start()

    async def async_stop_mqtt(self) -> None:
        """Stop optional MQTT live overlay."""
        if self._mqtt_manager is not None:
            await self._mqtt_manager.stop()
            self._mqtt_manager = None

    def async_apply_mqtt_update(
        self,
        cmd: str,
        update: list[MqttStationUpdate]
        | MqttApHealthUpdate
        | MqttApStatusUpdate
        | None,
        now: datetime,
    ) -> None:
        """Merge one parsed MQTT update into the in-memory coordinator data."""
        data = self._last_data
        if data is None or update is None:
            return
        if cmd == "XReport_StaList" and isinstance(update, list):
            data = merge_station_updates(data, update, now=now)
            data = self._maybe_enrich_mqtt_station_hostnames(data, now)
            data = enrich_station_vendors(data)
        elif cmd == "XReport_ExtendInfo" and isinstance(update, MqttApHealthUpdate):
            data = merge_ap_health_update(data, update, now=now)
        elif cmd in {"APOnline", "APOffline"} and isinstance(
            update, MqttApStatusUpdate
        ):
            data = merge_ap_status_update(data, update)
        else:
            return
        if data is self._last_data:
            return
        self._last_data = data
        self.async_set_updated_data(data)
        if cmd == "XReport_StaList":
            async_dispatcher_send(
                self.hass,
                f"{SIGNAL_STATIONS_CHANGED}_{self.config_entry.entry_id}",
                now,
            )

    def _maybe_enrich_mqtt_station_hostnames(
        self, data: RltechData, now: datetime
    ) -> RltechData:
        """Occasionally retry DHCP hostname enrichment for MQTT-only updates."""
        if self._last_mqtt_hostname_enrichment is not None and (
            now - self._last_mqtt_hostname_enrichment
        ) < timedelta(seconds=DEFAULT_DHCP_HOSTNAME_REFRESH_INTERVAL):
            return data
        self._last_mqtt_hostname_enrichment = now
        try:
            return enrich_from_home_assistant_dhcp(self.hass, data)
        except Exception as err:  # pragma: no cover - defensive around HA internals
            _LOGGER.debug(
                "Unable to enrich MQTT station hostnames from DHCP cache: %s", err
            )
            return data


def build_client(entry: ConfigEntry) -> RltechClient:
    """Build an API client from a config entry."""
    base_url = entry.data[CONF_BASE_URL]
    legacy_hosts = _legacy_hosts_from_entry(entry)
    return RltechClient(
        base_url,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        legacy_base_urls=legacy_hosts,
        legacy_username=entry.data.get(CONF_LEGACY_USERNAME, "admin"),
        legacy_password=entry.data.get(CONF_LEGACY_PASSWORD, "admin"),
        ap_username=entry.data.get(CONF_AP_USERNAME, DEFAULT_AP_USERNAME),
        ap_password=entry.data.get(CONF_AP_PASSWORD, DEFAULT_AP_PASSWORD),
    )


def build_mqtt_manager(
    entry: ConfigEntry, coordinator: RltechCoordinator
) -> RltechMqttManager:
    """Build an MQTT manager from a config entry."""
    host = str(entry.data.get(CONF_MQTT_HOST) or _entry_host(entry)).strip()
    return RltechMqttManager(
        host=host,
        port=entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT),
        username=entry.data.get(CONF_MQTT_USERNAME, DEFAULT_MQTT_USERNAME),
        password=entry.data.get(CONF_MQTT_PASSWORD, DEFAULT_MQTT_PASSWORD),
        psk_identity=entry.data.get(CONF_MQTT_PSK_IDENTITY, DEFAULT_MQTT_PSK_IDENTITY),
        psk_hex=entry.data.get(CONF_MQTT_PSK, ""),
        client_id=f"ha-rltech-fttr-{entry.entry_id[:8]}",
        apply_update=coordinator.async_apply_mqtt_update,
        stats=coordinator.mqtt_stats,
    )


def _entry_host(entry: ConfigEntry) -> str:
    """Return the primary OLT host from a config entry."""
    base_url = entry.data[CONF_BASE_URL]
    parsed = urlsplit(base_url)
    return parsed.hostname or parsed.netloc.split(":", 1)[0] or base_url


def _legacy_hosts_from_entry(entry: ConfigEntry) -> list[str]:
    """Return legacy port-80 URLs for the master plus optional slave hosts."""
    from urllib.parse import urlsplit

    base_url = entry.data[CONF_BASE_URL]
    parsed = urlsplit(base_url)
    host = parsed.hostname or parsed.netloc.split(":", 1)[0] or base_url
    hosts = [host]
    extra_hosts = entry.data.get(CONF_LEGACY_HOSTS, "")
    for item in re.split(r"[\s,]+", str(extra_hosts)):
        item = item.strip()
        if not item:
            continue
        if "://" in item:
            item = urlsplit(item).hostname or item
        elif ":" in item and item.rsplit(":", 1)[1].isdigit():
            item = item.rsplit(":", 1)[0]
        if item not in hosts:
            hosts.append(item)
    return [f"http://{item}" for item in hosts]

