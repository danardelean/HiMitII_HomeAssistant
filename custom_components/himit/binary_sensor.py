"""Binary sensor platform for Hi-Mit II — read-only status indicators."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HimitCoordinator
from .entity import HimitEntity


@dataclass(frozen=True)
class HimitBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Hi-Mit II binary sensor."""
    field: str = ""


BINARY_SENSOR_DESCRIPTIONS: tuple[HimitBinarySensorDescription, ...] = (
    HimitBinarySensorDescription(
        key="a2w_running",
        name="Heat Pump Running",
        field="A2W_SW_ON",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:heat-pump",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HimitCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        HimitBinarySensor(coordinator, device_id, description)
        for device_id in coordinator.data
        for description in BINARY_SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class HimitBinarySensor(HimitEntity, BinarySensorEntity):
    """A read-only binary status sensor for Hi-Mit II."""

    entity_description: HimitBinarySensorDescription

    def __init__(
        self,
        coordinator: HimitCoordinator,
        device_id: str,
        description: HimitBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self._device_data.get(self.entity_description.field)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self._device_data.get(self.entity_description.field) is not None
        )
