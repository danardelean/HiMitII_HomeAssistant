"""Diagnostics support for Hisense Hi-Mit II."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

# Keys that contain sensitive data and must be redacted
TO_REDACT_CONFIG = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
}

TO_REDACT_DEVICE = {
    "wifiId",
    "wifiMac",
    "mac",
    "macAddress",
    "ip",
    "ssid",
    "customerId",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Token lifecycle info (non-sensitive)
    token_info = {
        "token_created_ms": entry.data.get("token_created_ms", 0),
        "token_expire_secs": entry.data.get("token_expire_secs", 0),
        "refresh_expire_secs": entry.data.get("refresh_expire_secs", 0),
        "token_is_expiring": coordinator._token_is_expiring(),
        "refresh_token_is_valid": coordinator._refresh_token_is_valid(),
    }

    # Discovered devices (redact sensitive fields)
    devices = [
        async_redact_data(d, TO_REDACT_DEVICE)
        for d in coordinator.atw_devices
    ]

    # Raw discovery response (redact sensitive fields)
    raw_discovery = async_redact_data(
        coordinator._raw_device_discovery, TO_REDACT_DEVICE
    )

    # Current coordinator data (device states)
    device_states = {}
    if coordinator.data:
        for device_id, state in coordinator.data.items():
            redacted = dict(state)
            # Redact internal wifi ID
            redacted.pop("_wifiId", None)
            device_states[device_id] = redacted

    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT_CONFIG),
        "options": dict(entry.options),
        "token_lifecycle": token_info,
        "discovered_devices": devices,
        "raw_device_discovery": raw_discovery,
        "device_states": device_states,
        "update_interval_seconds": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
        "last_update_success": coordinator.last_update_success,
    }
