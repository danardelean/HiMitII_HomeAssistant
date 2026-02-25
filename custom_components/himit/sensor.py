"""Sensor platform for Hi-Mit II — temperature and status sensors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HimitCoordinator
from .entity import HimitEntity


@dataclass(frozen=True)
class HimitSensorDescription(SensorEntityDescription):
    """Describe a Hi-Mit II sensor."""
    field: str = ""


SENSOR_DESCRIPTIONS: tuple[HimitSensorDescription, ...] = (
    # ── Actual temperatures (live readings) ──────────────────────────────────
    HimitSensorDescription(
        key="c1_water_actual",
        name="Circuit 1 Water Temp",
        field="fixedDid18",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer-water",
    ),
    HimitSensorDescription(
        key="c2_water_actual",
        name="Circuit 2 Water Temp",
        field="fixedDid19",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer-water",
    ),
    HimitSensorDescription(
        key="dhw_water_actual",
        name="DHW Water Temp",
        field="fixedDid16",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:water-thermometer",
    ),
    HimitSensorDescription(
        key="swp_water_actual",
        name="Pool Water Temp",
        field="fixedDid17",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:pool-thermometer",
    ),
    HimitSensorDescription(
        key="outdoor_temp",
        name="Outdoor Ambient Temp",
        field="swj_Ta",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer",
    ),
    # ── Setpoint sensors (read-only view; writable via Number entities) ───────
    HimitSensorDescription(
        key="c1_setpoint",
        name="Circuit 1 Setpoint",
        field="Ts_c1_water",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:target",
        entity_registry_enabled_default=False,  # number entity is more useful
    ),
    HimitSensorDescription(
        key="c2_setpoint",
        name="Circuit 2 Setpoint",
        field="Ts_c2_water",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:target",
        entity_registry_enabled_default=False,
    ),
    HimitSensorDescription(
        key="dhw_setpoint",
        name="DHW Setpoint",
        field="TDHWS",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:target",
        entity_registry_enabled_default=False,
    ),
    # ── Room sensors ─────────────────────────────────────────────────────────
    *(
        HimitSensorDescription(
            key=f"room_temp_r{i}",
            name=f"Room {i} Temp",
            field=f"TsR{i}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:home-thermometer",
        )
        for i in range(1, 9)
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HimitCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for device_id in coordinator.data:
        for description in SENSOR_DESCRIPTIONS:
            entities.append(HimitSensor(coordinator, device_id, description))

    async_add_entities(entities)


class HimitSensor(HimitEntity, SensorEntity):
    """A single Hi-Mit II temperature sensor."""

    entity_description: HimitSensorDescription

    def __init__(
        self,
        coordinator: HimitCoordinator,
        device_id: str,
        description: HimitSensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        return self._device_data.get(self.entity_description.field)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self.native_value is not None
        )
