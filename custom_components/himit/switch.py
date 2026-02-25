"""Switch platform for Hi-Mit II — heat pump and circuit on/off switches."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HimitCoordinator
from .entity import HimitEntity


@dataclass(frozen=True)
class HimitSwitchDescription(SwitchEntityDescription):
    """Describe a Hi-Mit II switch."""
    field: str = ""
    cmd_type: str = ""


SWITCH_DESCRIPTIONS: tuple[HimitSwitchDescription, ...] = (
    HimitSwitchDescription(
        key="circuit1",
        name="Circuit 1 (Heating)",
        field="c1_SW_ON",
        cmd_type="c1_SW_ON",
        icon="mdi:hvac",
    ),
    HimitSwitchDescription(
        key="circuit2",
        name="Circuit 2 (Heating)",
        field="c2_SW_ON",
        cmd_type="c2_SW_ON",
        icon="mdi:hvac",
    ),
    HimitSwitchDescription(
        key="dhw",
        name="Domestic Hot Water",
        field="DHW_SW_ON",
        cmd_type="DHW_SW_ON",
        icon="mdi:water-boiler",
    ),
    HimitSwitchDescription(
        key="swp",
        name="Swimming Pool",
        field="SWP_SW_ON",
        cmd_type="SWP_SW_ON",
        icon="mdi:pool",
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
        for description in SWITCH_DESCRIPTIONS:
            entities.append(HimitSwitch(coordinator, device_id, description))

    async_add_entities(entities)


class HimitSwitch(HimitEntity, SwitchEntity):
    """A single Hi-Mit II on/off switch."""

    entity_description: HimitSwitchDescription

    def __init__(
        self,
        coordinator: HimitCoordinator,
        device_id: str,
        description: HimitSwitchDescription,
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

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_property(
            self._wifi_id,
            self._device_id,
            self.entity_description.cmd_type,
            "1",
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_property(
            self._wifi_id,
            self._device_id,
            self.entity_description.cmd_type,
            "0",
        )
