"""Base entity for Hi-Mit II."""
from __future__ import annotations

import time

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HimitCoordinator

# 2026-11-07: il modulo Wi-Fi della pompa a volte smette di comunicare col
# cloud (05/11 dalle 18:45, 07/11 dalle ~01:40, 09/11 dalle 16:08) mentre il
# cloud continua a rispondere con l'ultimo stato noto. Il campo "timeStamp"
# (ms) dello stato del dispositivo e' l'ora dell'ultimo dato ricevuto dalla
# pompa. Oltre questa soglia le misure diventano "unavailable" invece di
# mostrare valori vecchi come se fossero attuali.
#
# 2026-11-09: dalla history di 24 h la pompa manda dati ogni ~1 min quando
# e' attiva, ma in standby solo un heartbeat ogni 30 min esatti (:12 e :42
# UTC). Con la soglia precedente di 20 min le entita' andavano "unavailable"
# per 10 min ogni mezz'ora senza nessun guasto. 45 min copre l'heartbeat
# con margine e segnala comunque un modulo bloccato entro tre quarti d'ora.
STALE_AFTER_SECONDS = 45 * 60


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
    def _device_timestamp(self) -> float | None:
        """Ora (epoch, secondi) dell'ultimo dato inviato dalla pompa al cloud."""
        raw = self._device_data.get("timeStamp")
        try:
            ts = float(raw)
        except (TypeError, ValueError):
            return None
        if ts <= 0:
            return None
        return ts / 1000 if ts > 1e11 else ts

    @property
    def _data_age_seconds(self) -> float | None:
        ts = self._device_timestamp
        if ts is None:
            return None
        return max(0.0, time.time() - ts)

    @property
    def _data_is_fresh(self) -> bool:
        """True se il dato della pompa e' recente (o se manca il timeStamp)."""
        age = self._data_age_seconds
        return age is None or age <= STALE_AFTER_SECONDS

    @property
    def device_info(self) -> DeviceInfo:
        name = self._device_data.get("_name", "Hi-Mit II")
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=name,
            manufacturer="Hisense",
            model="Hi-Mit II ATW",
        )
