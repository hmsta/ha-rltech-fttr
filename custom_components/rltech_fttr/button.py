"""Button entities for RLTech FTTR."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import RltechError
from .const import DOMAIN
from .coordinator import RltechCoordinator
from .entity import RltechEntity, ap_device_info
from .identifiers import ap_sensor_object_id, ap_sensor_unique_id
from .models import RltechAp

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RLTech FTTR AP buttons."""
    coordinator: RltechCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_aps: set[str] = set()

    def add_dynamic_entities() -> None:
        if coordinator.data is None:
            return
        new_entities: list[RltechApRebootButton] = []
        for mac, ap in coordinator.data.aps.items():
            if not ap.sn or ap.sn in known_aps:
                continue
            known_aps.add(ap.sn)
            new_entities.append(RltechApRebootButton(entry, coordinator, mac))
        if new_entities:
            async_add_entities(new_entities)

    add_dynamic_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_dynamic_entities))


class RltechApRebootButton(RltechEntity, ButtonEntity):
    """Button to reboot one managed AP."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "ap_reboot"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RltechCoordinator,
        mac: str,
    ) -> None:
        super().__init__(entry, coordinator)
        self._mac = mac
        ap = self._ap
        unique_id = ap_sensor_unique_id(entry.entry_id, ap, "reboot")
        if unique_id is None:
            raise ValueError(f"AP {mac} has no SN")
        self._attr_unique_id = unique_id
        object_id = ap_sensor_object_id(ap, "reboot")
        if object_id is None:
            raise ValueError(f"AP {mac} has no SN")
        self.entity_id = f"button.{object_id}"

    @property
    def available(self) -> bool:
        ap = self._ap
        return super().available and ap is not None and bool(ap.ip)

    @property
    def device_info(self):
        ap = self._ap
        return ap_device_info(self.config_entry, self._mac, ap)

    async def async_press(self) -> None:
        """Reboot the AP."""
        ap = self._ap
        if ap is None or not ap.ip:
            raise HomeAssistantError("AP has no IP address for reboot")
        session = async_get_clientsession(self.coordinator.hass)
        try:
            await self.coordinator.client.reboot_ap(session, ap)
        except RltechError as err:
            raise HomeAssistantError(f"Unable to reboot RLTech AP: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected RLTech AP reboot failure")
            raise HomeAssistantError(f"Unable to reboot RLTech AP: {err}") from err

    @property
    def _ap(self) -> RltechAp | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.aps.get(self._mac)
