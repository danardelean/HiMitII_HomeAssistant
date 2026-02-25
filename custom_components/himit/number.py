"""Number platform for Hi-Mit II — temperature setpoint controls."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HimitCoordinator
from .entity import HimitEntity


@dataclass(frozen=True)
class HimitNumberDescription(NumberEntityDescription):
    """Describe a Hi-Mit II setpoint number."""
    field: str = ""          # data key for current setpoint value
    cmd_type: str = ""       # cmdType for setDeviceProperty
    min_field: str = ""      # data key for min limit (from fixedDid*)
    max_field: str = ""      # data key for max limit (from fixedDid*)
    default_min: float = 10.0
    default_max: float = 60.0


NUMBER_DESCRIPTIONS: tuple[HimitNumberDescription, ...] = (
    HimitNumberDescription(
        key="c1_setpoint",
        name="Circuit 1 Setpoint",
        field="Ts_c1_water",
        cmd_type="Ts_c1_water",
        min_field="fixedDid27",    # 12°C default
        max_field="fixedDid28",    # 22°C default (heat mode)
        default_min=12.0,
        default_max=55.0,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:thermometer-chevron-up",
    ),
    HimitNumberDescription(
        key="c2_setpoint",
        name="Circuit 2 Setpoint",
        field="Ts_c2_water",
        cmd_type="Ts_c2_water",
        min_field="fixedDid27",    # 27°C default
        max_field="fixedDid28",    # 55°C default
        default_min=27.0,
        default_max=55.0,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:thermometer-chevron-up",
    ),
    HimitNumberDescription(
        key="dhw_setpoint",
        name="DHW Setpoint",
        field="TDHWS",
        cmd_type="TDHWS",
        min_field="fixedDid29",    # 40°C default
        max_field="fixedDid30",    # 55°C default
        default_min=40.0,
        default_max=65.0,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:water-thermometer-outline",
    ),
    HimitNumberDescription(
        key="swp_setpoint",
        name="Pool Setpoint",
        field="Tswps",
        cmd_type="Tswps",
        min_field="fixedDid31",    # 24°C default
        max_field="fixedDid32",    # 33°C default
        default_min=20.0,
        default_max=40.0,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:pool-thermometer",
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
        for description in NUMBER_DESCRIPTIONS:
            entities.append(HimitNumber(coordinator, device_id, description))

    async_add_entities(entities)


class HimitNumber(HimitEntity, NumberEntity):
    """A temperature setpoint control for Hi-Mit II."""

    entity_description: HimitNumberDescription

    def __init__(
        self,
        coordinator: HimitCoordinator,
        device_id: str,
        description: HimitNumberDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        return self._device_data.get(self.entity_description.field)

    @property
    def native_min_value(self) -> float:
        """Use device-reported min, falling back to description default."""
        val = self._device_data.get(self.entity_description.min_field)
        if val is not None:
            return float(val)
        return self.entity_description.default_min

    @property
    def native_max_value(self) -> float:
        """Use device-reported max, falling back to description default."""
        val = self._device_data.get(self.entity_description.max_field)
        if val is not None:
            return float(val)
        return self.entity_description.default_max

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self.native_value is not None
        )

    async def async_set_native_value(self, value: float) -> None:
        """Send new setpoint to the heat pump."""
        await self.coordinator.async_set_property(
            self._wifi_id,
            self._device_id,
            self.entity_description.cmd_type,
            str(int(value)),
        )
