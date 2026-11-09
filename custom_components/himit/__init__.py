"""Hisense Hi-Mit II Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HimitAPI
from .const import DOMAIN
from .coordinator import HimitCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hi-Mit II from a config entry."""
    session = async_get_clientsession(hass)
    api         = HimitAPI(session)
    coordinator = HimitCoordinator(hass, api, entry)

    # Initial fetch — raises ConfigEntryNotReady on failure
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 2026-11-02: snapshot delle opzioni. Il listener viene chiamato da HA a
    # OGNI async_update_entry, compreso il salvataggio dei token che il
    # coordinator fa ogni ~1h55 (token da 2 h). Prima ricaricava sempre
    # l'integrazione → tutte le entità "unavailable" ogni 1h55. Ora ricarica
    # solo se sono cambiate davvero le opzioni (es. scan_interval).
    coordinator.options_snapshot = dict(entry.options)

    # Listen for option updates
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates (ignore data-only updates such as token refresh)."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None and dict(entry.options) == getattr(
        coordinator, "options_snapshot", None
    ):
        _LOGGER.debug("Config entry data updated (token refresh) — no reload")
        return
    await hass.config_entries.async_reload(entry.entry_id)
