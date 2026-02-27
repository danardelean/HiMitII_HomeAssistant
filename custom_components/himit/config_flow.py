"""Config flow for Hisense Hi-Mit II."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class HimitConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Hi-Mit II."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> HimitOptionsFlow:
        """Return the options flow handler."""
        return HimitOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._login_data: dict[str, Any] = {}
        self._homes: list[dict] = []
        self._username: str = ""
        self._password: str = ""
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1 — collect credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            api = HimitAPI(session)

            try:
                login_result = await api.login(username, password)
                homes = await api.get_home_list(login_result["access_token"])
            except HimitAuthError:
                errors["base"] = "invalid_auth"
            except (HimitAPIError, aiohttp.ClientError) as exc:
                _LOGGER.error("Login failed: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during login: %s", exc)
                errors["base"] = "unknown"
            else:
                self._login_data = login_result
                self._homes      = homes
                self._username   = username
                self._password   = password

                if len(homes) == 1:
                    # Only one home — skip selection
                    return await self._create_entry(homes[0])
                if not homes:
                    errors["base"] = "no_homes"
                else:
                    return await self.async_step_home()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )

    @staticmethod
    def _home_id(home: dict) -> str:
        """Extract home ID — API may return 'id', 'homeId', or 'home_id'."""
        return str(home.get("id") or home.get("homeId") or home.get("home_id", ""))

    @staticmethod
    def _home_name(home: dict) -> str:
        """Extract home name with fallbacks matching the API response."""
        return (
            home.get("defaultHomeName")
            or home.get("homeName")
            or home.get("name", "")
        )

    async def async_step_home(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2 — select a home (only shown when account has >1 home)."""
        if user_input is not None:
            selected = next(
                (h for h in self._homes
                 if self._home_id(h) == user_input[CONF_HOME_ID]),
                self._homes[0],
            )
            return await self._create_entry(selected)

        home_options = {
            self._home_id(h): self._home_name(h) or self._home_id(h)
            for h in self._homes
        }
        return self.async_show_form(
            step_id="home",
            data_schema=vol.Schema({
                vol.Required(CONF_HOME_ID): vol.In(home_options),
            }),
        )

    def _build_entry_data(self, home_id: str) -> dict[str, Any]:
        """Build the data dict for a config entry."""
        return {
            CONF_USERNAME:             self._username,
            CONF_PASSWORD:             self._password,
            CONF_HOME_ID:              home_id,
            CONF_ACCESS_TOKEN:         self._login_data["access_token"],
            CONF_REFRESH_TOKEN:        self._login_data.get("refresh_token", ""),
            CONF_TOKEN_CREATED_MS:     self._login_data.get("token_created_ms", 0),
            CONF_TOKEN_EXPIRE_SECS:    self._login_data.get("token_expire_secs", 7200),
            CONF_REFRESH_EXPIRE_SECS:  self._login_data.get("refresh_expire_secs", 2592000),
        }

    async def _create_entry(self, home: dict) -> FlowResult:
        """Create the config entry with all credentials and token data."""
        home_id   = self._home_id(home)
        home_name = self._home_name(home) or home_id

        # Deduplicate — one entry per home
        await self.async_set_unique_id(f"himit_{home_id}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Hi-Mit II — {home_name}",
            data=self._build_entry_data(home_id),
        )

    # ── Reauth flow ──────────────────────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Re-auth flow triggered when authentication can no longer succeed."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect new credentials for reauth."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            api = HimitAPI(session)

            try:
                login_result = await api.login(username, password)
                await api.get_home_list(login_result["access_token"])
            except HimitAuthError:
                errors["base"] = "invalid_auth"
            except (HimitAPIError, aiohttp.ClientError) as exc:
                _LOGGER.error("Reauth login failed: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during reauth: %s", exc)
                errors["base"] = "unknown"
            else:
                self._login_data = login_result
                self._username   = username
                self._password   = password
                home_id = self._reauth_entry.data[CONF_HOME_ID]
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data=self._build_entry_data(home_id),
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_USERNAME,
                    default=self._reauth_entry.data.get(CONF_USERNAME, ""),
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )

    # ── Reconfigure flow ─────────────────────────────────────────────────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow the user to update credentials from the integration page."""
        errors: dict[str, str] = {}
        reconfigure_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        assert reconfigure_entry is not None

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            api = HimitAPI(session)

            try:
                login_result = await api.login(username, password)
                await api.get_home_list(login_result["access_token"])
            except HimitAuthError:
                errors["base"] = "invalid_auth"
            except (HimitAPIError, aiohttp.ClientError) as exc:
                _LOGGER.error("Reconfigure login failed: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during reconfigure: %s", exc)
                errors["base"] = "unknown"
            else:
                self._login_data = login_result
                self._username   = username
                self._password   = password
                home_id = reconfigure_entry.data[CONF_HOME_ID]
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data=self._build_entry_data(home_id),
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_USERNAME,
                    default=reconfigure_entry.data.get(CONF_USERNAME, ""),
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )


# ── Options flow ─────────────────────────────────────────────────────────────


class HimitOptionsFlow(OptionsFlow):
    """Handle options for Hi-Mit II (scan interval, etc.)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
            }),
        )
