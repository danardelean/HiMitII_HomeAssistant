"""DataUpdateCoordinator for Hi-Mit II — polls device state every 30 s."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HimitAPI, HimitAPIError, HimitAuthError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_HOME_ID,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_EXPIRE_SECS,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_CREATED_MS,
    CONF_TOKEN_EXPIRE_SECS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SENSOR_DISCONNECTED,
)

_LOGGER = logging.getLogger(__name__)

# Refresh the access token 5 minutes before it expires
_TOKEN_REFRESH_BUFFER = 5 * 60  # seconds


class HimitCoordinator(DataUpdateCoordinator):
    """Manages polling and token lifecycle for one Hi-Mit II system."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: HimitAPI,
        entry: ConfigEntry,
    ) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api    = api
        self.entry  = entry
        self._token_data = dict(entry.data)  # mutable copy for in-memory updates

        # Discovered ATW devices [{wifiId, deviceId, deviceNickName}]
        self.atw_devices: list[dict] = []

        # Raw API response from device discovery (for diagnostics)
        self._raw_device_discovery: dict = {}

    # ── Token helpers ─────────────────────────────────────────────────────────

    @property
    def access_token(self) -> str:
        return self._token_data[CONF_ACCESS_TOKEN]

    def _token_is_expiring(self) -> bool:
        created_ms  = self._token_data.get(CONF_TOKEN_CREATED_MS, 0)
        expire_secs = self._token_data.get(CONF_TOKEN_EXPIRE_SECS, 7200)
        expiry_ts   = (created_ms / 1000) + expire_secs
        return time.time() > expiry_ts - _TOKEN_REFRESH_BUFFER

    def _refresh_token_is_valid(self) -> bool:
        refresh_tok = self._token_data.get(CONF_REFRESH_TOKEN, "")
        if not refresh_tok:
            return False
        created_ms    = self._token_data.get(CONF_TOKEN_CREATED_MS, 0)
        expire_secs   = self._token_data.get(CONF_REFRESH_EXPIRE_SECS, 2592000)
        expiry_ts     = (created_ms / 1000) + expire_secs
        return time.time() < expiry_ts - _TOKEN_REFRESH_BUFFER

    async def _ensure_token(self) -> None:
        """Refresh access token if it is about to expire."""
        if not self._token_is_expiring():
            return

        if self._refresh_token_is_valid():
            _LOGGER.debug("Access token expiring — refreshing via refresh_token")
            try:
                new_data = await self.api.refresh_token(
                    self._token_data[CONF_REFRESH_TOKEN]
                )
                self._apply_new_tokens(new_data)
                _LOGGER.info("Access token refreshed successfully")
                return
            except HimitAuthError:
                _LOGGER.warning("Token refresh failed — attempting re-login")

        # Refresh token expired or refresh failed — try a full re-login
        # using stored credentials before giving up
        await self._try_relogin()

    async def _try_relogin(self) -> None:
        """Attempt a full re-login using stored credentials."""
        from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

        username = self.entry.data.get(CONF_USERNAME)
        password = self.entry.data.get(CONF_PASSWORD)
        if not username or not password:
            raise ConfigEntryAuthFailed(
                "No stored credentials — re-authenticate in integration settings"
            )

        _LOGGER.debug("Attempting re-login for %s", username)
        try:
            new_data = await self.api.login(username, password)
        except HimitAuthError as exc:
            raise ConfigEntryAuthFailed(
                "Re-login failed — password may have changed"
            ) from exc

        self._apply_new_tokens(new_data)
        _LOGGER.info("Re-login successful — new tokens acquired")

    def _apply_new_tokens(self, new_data: dict) -> None:
        """Update in-memory token data and persist to config entry."""
        self._token_data.update({
            CONF_ACCESS_TOKEN:        new_data["access_token"],
            CONF_REFRESH_TOKEN:       new_data.get("refresh_token", ""),
            CONF_TOKEN_CREATED_MS:    new_data.get("token_created_ms", 0),
            CONF_TOKEN_EXPIRE_SECS:   new_data.get("token_expire_secs", 7200),
            CONF_REFRESH_EXPIRE_SECS: new_data.get("refresh_expire_secs", 2592000),
        })
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, **self._token_data}
        )

    # ── Device discovery ──────────────────────────────────────────────────────

    async def _discover_atw_devices(self) -> None:
        """Fetch device list and cache ATW devices.

        The API returns ATW heat pumps in dedicated lists (atwInfoList,
        hicubeAtwList), not in a generic deviceList.
        """
        home_id = self._token_data[CONF_HOME_ID]
        try:
            resp = await self.api.get_devices(self.access_token, home_id)
        except HimitAPIError as exc:
            _LOGGER.warning("Device discovery failed: %s", exc)
            return

        # Store raw response for diagnostics
        self._raw_device_discovery = resp

        # ATW devices live in their own lists (from CustomerDeviceResponse)
        atw = resp.get("atwInfoList") or []
        atw += resp.get("hicubeAtwList") or []
        self.atw_devices = [d for d in atw if isinstance(d, dict)]

        _LOGGER.debug(
            "Discovered %d ATW device(s): %s",
            len(self.atw_devices),
            [d.get("deviceNickName", d.get("deviceId")) for d in self.atw_devices],
        )

    # ── Main poll ─────────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest state from the cloud. Called every scan interval."""
        await self._ensure_token()

        if not self.atw_devices:
            await self._discover_atw_devices()

        if not self.atw_devices:
            raise UpdateFailed("No ATW heat pump devices found for this home")

        device_refs = [
            {"wifiId": d["wifiId"], "deviceId": d["deviceId"]}
            for d in self.atw_devices
        ]

        try:
            props_list = await self.api.get_device_property(
                self.access_token, device_refs
            )
        except HimitAuthError as exc:
            raise ConfigEntryAuthFailed(
                f"Authentication error: {exc}"
            ) from exc
        except HimitAPIError as exc:
            raise UpdateFailed(str(exc)) from exc

        # Parse each device property into a clean flat dict
        return {
            prop.get("deviceId", prop.get("wifiId", f"device_{i}")): _parse_property(prop)
            for i, prop in enumerate(props_list)
        }

    # ── Control helpers ───────────────────────────────────────────────────────

    # Seconds to wait before polling the cloud after a command,
    # giving the server time to reflect the new state.
    _COMMAND_REFRESH_DELAY = 3

    async def async_set_property(
        self, wifi_id: str, device_id: str, cmd_type: str, cmd_value: str
    ) -> None:
        """Send a control command, log it, optimistically update, then confirm.

        Mirrors the mobile app flow: setDeviceProperty → usrControlRecord → refresh.
        """
        await self._ensure_token()
        props = [{"cmdType": cmd_type, "cmdValue": cmd_value}]
        await self.api.set_device_property(
            self.access_token, wifi_id, device_id, props,
        )
        try:
            await self.api.usr_control_record(
                self.access_token, wifi_id, device_id, props,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("usrControlRecord failed (non-fatal)", exc_info=True)
        self._optimistic_update(device_id, cmd_type, cmd_value)
        self._schedule_delayed_refresh()

    async def async_set_multiple(
        self, wifi_id: str, device_id: str, commands: list[dict]
    ) -> None:
        """Send multiple control commands at once."""
        await self._ensure_token()
        await self.api.set_device_property(
            self.access_token, wifi_id, device_id, commands
        )
        try:
            await self.api.usr_control_record(
                self.access_token, wifi_id, device_id, commands,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("usrControlRecord failed (non-fatal)", exc_info=True)
        for cmd in commands:
            self._optimistic_update(device_id, cmd["cmdType"], cmd["cmdValue"])
        self._schedule_delayed_refresh()

    @callback
    def _optimistic_update(
        self, device_id: str, field: str, value: str
    ) -> None:
        """Apply the expected value locally so the UI updates immediately."""
        if self.data and device_id in self.data:
            device = self.data[device_id]
            # Switch fields: store as bool
            if value in ("0", "1"):
                device[field] = value == "1"
            else:
                # Temperature setpoints: store as float to match _parse_property
                try:
                    device[field] = float(value)
                except (ValueError, TypeError):
                    device[field] = value
            self.async_set_updated_data(self.data)

    @callback
    def _schedule_delayed_refresh(self) -> None:
        """Refresh from the cloud after a short delay to confirm the command."""
        async def _delayed() -> None:
            await asyncio.sleep(self._COMMAND_REFRESH_DELAY)
            await self.async_request_refresh()

        self.hass.async_create_task(_delayed())


# ── Property parser ───────────────────────────────────────────────────────────

def _safe_float(value: Any) -> float | None:
    """Convert to float, return None for missing/disconnected sensors."""
    if value in (None, "", "null"):
        return None
    try:
        f = float(value)
        if f <= SENSOR_DISCONNECTED:
            return None
        return f
    except (ValueError, TypeError):
        return None


def _parse_property(prop: dict) -> dict[str, Any]:
    """Merge allStatus / functions / status into one flat dict.

    Status wins over functions wins over allStatus (same priority as APK).
    Numeric sensor values are converted to float; None means not available.
    """
    flat: dict[str, Any] = {}
    flat.update(prop.get("allStatus") or {})
    flat.update(prop.get("functions") or {})
    flat.update(prop.get("status") or {})

    # Numeric conversions for all temperature fields
    temp_fields = [
        "Ts_c1_water", "Ts_c2_water", "TDHWS", "Tswps",
        "fixedDid16", "fixedDid17", "fixedDid18", "fixedDid19",
        "swj_Ta",
        # Room sensors
        *[f"TsR{i}" for i in range(1, 9)],
        # Room setpoints
        *[f"Trc1R{i}" for i in range(1, 5)],
        *[f"Trc2R{i}" for i in range(1, 5)],
        # Setpoint limits
        "fixedDid25", "fixedDid26", "fixedDid27", "fixedDid28",
        "fixedDid29", "fixedDid30", "fixedDid31", "fixedDid32",
    ]
    for field in temp_fields:
        flat[field] = _safe_float(flat.get(field))

    # Boolean conversions for switches
    sw_fields = [
        "A2W_SW_ON", "c1_SW_ON", "c2_SW_ON", "DHW_SW_ON", "SWP_SW_ON",
    ]
    for field in sw_fields:
        val = flat.get(field)
        flat[field] = (str(val) == "1") if val is not None else None

    # Keep wifiId and deviceId
    flat["_wifiId"]   = prop.get("wifiId",   "")
    flat["_deviceId"] = prop.get("deviceId", "")
    flat["_name"]     = prop.get("deviceNickName", prop.get("deviceId", "Hi-Mit II"))

    return flat
