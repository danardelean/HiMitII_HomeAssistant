"""Base entity for Hi-Mit II."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HimitCoordinator


class HimitEntity(CoordinatorEntity[HimitCoordinator]):
    """Base class for all Hi-Mit II entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HimitCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def _device_data(self) -> dict:
        return self.coordinator.data.get(self._device_id, {})

    @property
    def _wifi_id(self) -> str:
        return self._device_data.get("_wifiId", "")

    @property
    def device_info(self) -> DeviceInfo:
        name = self._device_data.get("_name", "Hi-Mit II")
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=name,
            manufacturer="Hisense",
            model="Hi-Mit II ATW",
        )
