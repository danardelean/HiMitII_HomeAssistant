"""Sensor platform for Hi-Mit II — temperature and status sensors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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

from .const import CONF_HOME_ID, DOMAIN
from .coordinator import HimitCoordinator
from .entity import STALE_AFTER_SECONDS, HimitEntity


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
        entities.append(HimitLastDataSensor(coordinator, device_id))

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
        self._attr_unique_id = f"{coordinator.entry.data[CONF_HOME_ID]}_{device_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        return self._device_data.get(self.entity_description.field)

    @property
    def available(self) -> bool:
        # 2026-11-07: anche "_data_is_fresh" — con il modulo Wi-Fi bloccato
        # il cloud restituisce l'ultimo stato noto per ore.
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self.native_value is not None
            and self._data_is_fresh
        )


class HimitLastDataSensor(HimitEntity, SensorEntity):
    """Ora dell'ultimo dato ricevuto dalla pompa tramite il cloud (2026-11-07).

    Resta disponibile anche quando i dati sono vecchi: serve proprio a
    vedere da quando la pompa non comunica.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:cloud-clock-outline"
    _attr_name = "Ultimo dato dalla pompa"

    def __init__(self, coordinator: HimitCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_last_data"

    @property
    def native_value(self) -> datetime | None:
        ts = self._device_timestamp
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        age = self._data_age_seconds
        return {
            "minuti_dall_ultimo_dato": round(age / 60, 1) if age is not None else None,
            "dati_freschi": self._data_is_fresh,
            "soglia_minuti": STALE_AFTER_SECONDS // 60,
        }

    @property
    def available(self) -> bool:
        return super().available and self._device_id in self.coordinator.data
