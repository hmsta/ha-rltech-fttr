"""Sensors for RLTech FTTR."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import CONF_AP_AREA_ID, DOMAIN
from .coordinator import RltechCoordinator
from .entity import RltechEntity, ap_device_info, controller_device_info
from .identifiers import ap_sensor_unique_id
from .models import (
    RltechAp,
    RltechApDetail,
    RltechData,
    RltechLanPonPort,
    RltechLanPort,
    RltechOltStatus,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class RltechSensorDescription(SensorEntityDescription):
    """Description for a controller sensor."""

    value_fn: Callable[[RltechData], int | float | str | datetime | None]


CONTROLLER_SENSORS = (
    RltechSensorDescription(
        key="ap_count",
        translation_key="ap_count",
        icon="mdi:access-point-network",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.aps),
    ),
    RltechSensorDescription(
        key="online_ap_count",
        translation_key="online_ap_count",
        icon="mdi:wifi-check",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: sum(1 for ap in data.aps.values() if ap.online),
    ),
    RltechSensorDescription(
        key="reported_station_count",
        translation_key="reported_station_count",
        icon="mdi:wifi",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: sum(1 for sta in data.stations.values() if sta.reported_online),
    ),
    RltechSensorDescription(
        key="poll_duration",
        translation_key="poll_duration",
        icon="mdi:timer-outline",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.poll_duration_ms,
    ),
)


@dataclass(frozen=True, kw_only=True)
class OltSensorDescription(SensorEntityDescription):
    """Description for an optional OLT status sensor."""

    value_fn: Callable[[RltechOltStatus], int | float | str | bool | datetime | None]


OLT_SENSORS = (
    OltSensorDescription(
        key="cpu_temperature",
        translation_key="cpu_temperature",
        icon="mdi:thermometer",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.cpu_temperature,
    ),
    OltSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        icon="mdi:restart",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: s.last_boot,
    ),
    OltSensorDescription(
        key="wan_link_up_since",
        translation_key="wan_link_up_since",
        icon="mdi:wan",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: s.wan_link_up_since,
    ),
)


@dataclass(frozen=True, kw_only=True)
class ApSensorDescription(SensorEntityDescription):
    """Description for an AP sensor."""

    value_fn: Callable[[RltechAp], int | float | str | None]


AP_SENSORS = (
    ApSensorDescription(
        key="online",
        translation_key="ap_online",
        icon="mdi:wifi-check",
        value_fn=lambda ap: "online" if ap.online else "offline" if ap.online is False else None,
    ),
    ApSensorDescription(
        key="assoc_count",
        translation_key="ap_assoc_count",
        icon="mdi:account-network",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda ap: ap.assoc_count,
    ),
    ApSensorDescription(
        key="profile",
        translation_key="ap_profile",
        icon="mdi:wifi-cog",
        value_fn=lambda ap: ap.profile,
    ),
    ApSensorDescription(
        key="alias",
        translation_key="ap_alias",
        icon="mdi:tag-outline",
        value_fn=lambda ap: ap.alias,
    ),
)


@dataclass(frozen=True, kw_only=True)
class ApDetailSensorDescription(SensorEntityDescription):
    """Description for a slow AP detail sensor."""

    value_fn: Callable[[RltechApDetail], int | float | str | None]


AP_DETAIL_SENSORS = (
    ApDetailSensorDescription(
        key="optical_rx_power",
        translation_key="ap_optical_rx_power",
        icon="mdi:download-network",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda detail: detail.optical_rx_power,
    ),
    ApDetailSensorDescription(
        key="optical_tx_power",
        translation_key="ap_optical_tx_power",
        icon="mdi:upload-network",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda detail: detail.optical_tx_power,
    ),
    ApDetailSensorDescription(
        key="downstream_optical_rx_power",
        translation_key="ap_downstream_optical_rx_power",
        icon="mdi:download-network-outline",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda detail: detail.downstream_optical_rx_power,
    ),
    ApDetailSensorDescription(
        key="optical_temperature",
        translation_key="ap_optical_temperature",
        icon="mdi:thermometer",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda detail: detail.optical_temperature,
    ),
    ApDetailSensorDescription(
        key="optical_voltage",
        translation_key="ap_optical_voltage",
        icon="mdi:flash",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda detail: detail.optical_voltage,
    ),
    ApDetailSensorDescription(
        key="optical_current",
        translation_key="ap_optical_current",
        icon="mdi:current-dc",
        native_unit_of_measurement="mA",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda detail: detail.optical_current,
    ),
)


@dataclass(frozen=True, kw_only=True)
class LanPortSensorDescription(SensorEntityDescription):
    """Description for a LAN Ethernet port sensor."""

    value_fn: Callable[[RltechLanPort], int | float | str | None]


LAN_PORT_SENSORS = (
    LanPortSensorDescription(
        key="status",
        translation_key="lan_port_status",
        icon="mdi:ethernet",
        value_fn=lambda p: p.status,
    ),
    LanPortSensorDescription(
        key="rate",
        translation_key="lan_port_rate",
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.rate,
    ),
    LanPortSensorDescription(
        key="mode",
        translation_key="lan_port_mode",
        icon="mdi:cog-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.mode,
    ),
)


@dataclass(frozen=True, kw_only=True)
class LanPonPortSensorDescription(SensorEntityDescription):
    """Description for a LAN-PON port sensor."""

    value_fn: Callable[[RltechLanPonPort], int | float | str | None]


LANPON_PORT_SENSORS = (
    LanPonPortSensorDescription(
        key="status",
        translation_key="lanpon_port_status",
        icon="mdi:access-point-network",
        value_fn=lambda p: p.status,
    ),
    LanPonPortSensorDescription(
        key="tx_power",
        translation_key="lanpon_port_tx_power",
        icon="mdi:upload-network",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.tx_power,
    ),
    LanPonPortSensorDescription(
        key="rx_power",
        translation_key="lanpon_port_rx_power",
        icon="mdi:download-network",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.rx_power,
    ),
    LanPonPortSensorDescription(
        key="temperature",
        translation_key="lanpon_port_temperature",
        icon="mdi:thermometer",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.temperature,
    ),
    LanPonPortSensorDescription(
        key="voltage",
        translation_key="lanpon_port_voltage",
        icon="mdi:flash",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.voltage,
    ),
    LanPonPortSensorDescription(
        key="current",
        translation_key="lanpon_port_current",
        icon="mdi:current-dc",
        native_unit_of_measurement="mA",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.current,
    ),
)


LAN_PORT_SUFFIXES = {
    "status": "link",
    "rate": "rate",
    "mode": "mode",
}


LANPON_PORT_SUFFIXES = {
    "status": "optical",
    "tx_power": "TX power",
    "rx_power": "RX power",
    "temperature": "temperature",
    "voltage": "voltage",
    "current": "current",
}


SENSOR_NAMES = {
    "ap_count": "AP count",
    "online_ap_count": "Online AP count",
    "reported_station_count": "Reported station count",
    "poll_duration": "Poll duration",
    "cpu_temperature": "CPU temperature",
    "last_boot": "Last boot",
    "wan_link_up_since": "WAN link up since",
    "online": "Online",
    "assoc_count": "Associated clients",
    "profile": "Profile",
    "alias": "Alias",
    "optical_rx_power": "Optical RX power",
    "optical_tx_power": "Optical TX power",
    "downstream_optical_rx_power": "Downstream optical RX power",
    "optical_temperature": "Optical temperature",
    "optical_voltage": "Optical voltage",
    "optical_current": "Optical current",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RLTech FTTR sensors."""
    coordinator: RltechCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    entities.extend(
        RltechControllerSensor(entry, coordinator, description)
        for description in CONTROLLER_SENSORS
    )
    entities.extend(
        RltechOltStatusSensor(entry, coordinator, description)
        for description in OLT_SENSORS
    )
    async_add_entities(entities)

    known_aps: set[str] = set()
    known_ap_details: set[str] = set()
    known_lan_ports: set[int] = set()
    known_lanpon_ports: set[int] = set()

    @callback
    def add_dynamic_entities() -> None:
        if coordinator.data is None:
            return
        new_entities = []
        new_aps: list[RltechAp] = []
        for mac, ap in coordinator.data.aps.items():
            if mac in known_aps:
                continue
            if not ap.sn:
                _LOGGER.warning("Skipping AP %s sensors because the AP row has no SN", mac)
                continue
            known_aps.add(mac)
            new_aps.append(ap)
            new_entities.extend(
                RltechApSensor(entry, coordinator, mac, description)
                for description in AP_SENSORS
            )
        for mac, detail in coordinator.data.ap_details.items():
            if mac in known_ap_details:
                continue
            ap = coordinator.data.aps.get(mac)
            if not ap or not ap.sn:
                _LOGGER.warning("Skipping AP %s detail sensors because the AP row has no SN", mac)
                continue
            known_ap_details.add(mac)
            new_entities.extend(
                RltechApDetailSensor(entry, coordinator, mac, description)
                for description in AP_DETAIL_SENSORS
            )
        for port in coordinator.data.lan_ports:
            if port in known_lan_ports:
                continue
            known_lan_ports.add(port)
            new_entities.extend(
                RltechLanPortSensor(entry, coordinator, port, description)
                for description in LAN_PORT_SENSORS
            )
        for ponid in coordinator.data.lanpon_ports:
            if ponid in known_lanpon_ports:
                continue
            known_lanpon_ports.add(ponid)
            new_entities.extend(
                RltechLanPonPortSensor(entry, coordinator, ponid, description)
                for description in LANPON_PORT_SENSORS
            )
        if new_entities:
            async_add_entities(new_entities)
        if new_aps:
            hass.async_create_task(_async_assign_area_to_ap_devices(hass, entry, new_aps))

    add_dynamic_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_dynamic_entities))


async def _async_assign_area_to_ap_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    aps: list[RltechAp],
) -> None:
    """Assign newly created AP devices to the configured default AP area."""
    area_id = entry.data.get(CONF_AP_AREA_ID)
    if not area_id:
        return

    device_registry = dr.async_get(hass)
    pending = {ap.sn for ap in aps if ap.sn}
    for _ in range(5):
        remaining = set()
        for sn in pending:
            device = device_registry.async_get_device(
                identifiers={(DOMAIN, f"{entry.entry_id}_ap_{sn}")},
            )
            if device is None:
                remaining.add(sn)
                continue
            if device.area_id is None:
                device_registry.async_update_device(device.id, area_id=area_id)

        if not remaining:
            return
        pending = remaining
        await asyncio.sleep(0.2)


class RltechControllerSensor(RltechEntity, SensorEntity):
    """Controller aggregate sensor."""

    entity_description: RltechSensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RltechCoordinator,
        description: RltechSensorDescription,
    ) -> None:
        super().__init__(entry, coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = SENSOR_NAMES[description.key]
        self._attr_suggested_object_id = f"rltech_fttr_{description.key}"
        self._attr_device_info = controller_device_info(entry)

    @property
    def native_value(self) -> int | float | str | datetime | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class RltechOltStatusSensor(RltechEntity, SensorEntity):
    """Optional OLT status sensor."""

    entity_description: OltSensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RltechCoordinator,
        description: OltSensorDescription,
    ) -> None:
        super().__init__(entry, coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_olt_{description.key}"
        self._attr_name = SENSOR_NAMES[description.key]
        self._attr_suggested_object_id = f"rltech_fttr_olt_{description.key}"
        self._attr_device_info = controller_device_info(entry)

    @property
    def native_value(self) -> int | float | str | bool | datetime | None:
        if self.coordinator.data is None or self.coordinator.data.olt_status is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data.olt_status)

    @property
    def device_info(self):
        status = self.coordinator.data.olt_status if self.coordinator.data else None
        return controller_device_info(self.config_entry, status)


class RltechApSensor(RltechEntity, SensorEntity):
    """Managed AP sensor."""

    entity_description: ApSensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RltechCoordinator,
        mac: str,
        description: ApSensorDescription,
    ) -> None:
        super().__init__(entry, coordinator)
        self._mac = mac
        self.entity_description = description
        ap = self._ap
        unique_id = ap_sensor_unique_id(entry.entry_id, ap, description.key)
        if unique_id is None:
            raise ValueError(f"AP {mac} has no SN")
        self._attr_unique_id = unique_id
        self._attr_name = SENSOR_NAMES[description.key]
        hardware_id = ap.sn if ap else mac
        self._attr_suggested_object_id = (
            f"rltech_ap_{slugify(hardware_id)}_{description.key}"
        )

    @property
    def native_value(self) -> int | float | str | None:
        ap = self._ap
        return self.entity_description.value_fn(ap) if ap else None

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        ap = self._ap
        if ap is None:
            return {}
        return {
            "ip": ap.ip,
            "model": ap.model,
            "version": ap.version,
            "sn": ap.sn,
            "dev_sn": ap.dev_sn,
        }

    @property
    def device_info(self):
        ap = self._ap
        return ap_device_info(self.config_entry, self._mac, ap)

    @property
    def _ap(self) -> RltechAp | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.aps.get(self._mac)


class RltechApDetailSensor(RltechEntity, SensorEntity):
    """Slow managed AP detail sensor."""

    entity_description: ApDetailSensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RltechCoordinator,
        mac: str,
        description: ApDetailSensorDescription,
    ) -> None:
        super().__init__(entry, coordinator)
        self._mac = mac
        self.entity_description = description
        ap = self._ap
        unique_id = ap_sensor_unique_id(entry.entry_id, ap, description.key)
        if unique_id is None:
            raise ValueError(f"AP {mac} has no SN")
        self._attr_unique_id = unique_id
        self._attr_name = SENSOR_NAMES[description.key]
        hardware_id = ap.sn if ap else mac
        self._attr_suggested_object_id = (
            f"rltech_ap_{slugify(hardware_id)}_{description.key}"
        )

    @property
    def native_value(self) -> int | float | str | None:
        detail = self._detail
        return self.entity_description.value_fn(detail) if detail else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        detail = self._detail
        if detail is None:
            return {}
        return {
            "last_update": detail.last_update.isoformat() if detail.last_update else None,
        }

    @property
    def device_info(self):
        ap = self._ap
        return ap_device_info(self.config_entry, self._mac, ap)

    @property
    def _ap(self) -> RltechAp | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.aps.get(self._mac)

    @property
    def _detail(self) -> RltechApDetail | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.ap_details.get(self._mac)


class RltechLanPortSensor(RltechEntity, SensorEntity):
    """LAN Ethernet port sensor."""

    entity_description: LanPortSensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RltechCoordinator,
        port: int,
        description: LanPortSensorDescription,
    ) -> None:
        super().__init__(entry, coordinator)
        self._port = port
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_lan_port_{port}_{description.key}"
        self._attr_device_info = controller_device_info(entry)
        label = f"LANPON{port - 4}" if port > 4 else f"LAN-{port}"
        suffix = LAN_PORT_SUFFIXES[description.key]
        self._attr_name = f"{label} {suffix}"
        self._attr_suggested_object_id = f"{slugify(label)}_{description.key}"

    @property
    def native_value(self) -> int | float | str | None:
        port = self._lan_port
        return self.entity_description.value_fn(port) if port else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        port = self._lan_port
        if port is None:
            return {}
        return {
            "port": port.port,
            "label": port.label,
            "path": port.path,
            "status": port.status,
            "connected": port.connected,
            "rate": port.rate,
            "mode": port.mode,
        }

    @property
    def _lan_port(self) -> RltechLanPort | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.lan_ports.get(self._port)


class RltechLanPonPortSensor(RltechEntity, SensorEntity):
    """LAN-PON port sensor."""

    entity_description: LanPonPortSensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RltechCoordinator,
        ponid: int,
        description: LanPonPortSensorDescription,
    ) -> None:
        super().__init__(entry, coordinator)
        self._ponid = ponid
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_lanpon_port_{ponid}_{description.key}"
        self._attr_device_info = controller_device_info(entry)
        label = f"LANPON{ponid}"
        suffix = LANPON_PORT_SUFFIXES[description.key]
        self._attr_name = f"{label} {suffix}"
        self._attr_suggested_object_id = f"{slugify(label)}_{description.key}"

    @property
    def native_value(self) -> int | float | str | None:
        port = self._lanpon_port
        return self.entity_description.value_fn(port) if port else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        port = self._lanpon_port
        if port is None:
            return {}
        return {
            "ponid": port.ponid,
            "active": port.active,
            "fec": port.fec,
            "autoregister": port.autoregister,
        }

    @property
    def _lanpon_port(self) -> RltechLanPonPort | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.lanpon_ports.get(self._ponid)
