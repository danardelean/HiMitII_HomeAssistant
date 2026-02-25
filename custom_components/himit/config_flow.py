"""Config flow for Hisense Hi-Mit II."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HimitAPI, HimitAPIError, HimitAuthError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_HOME_ID,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_EXPIRE_SECS,
    CONF_TOKEN_CREATED_MS,
    CONF_TOKEN_EXPIRE_SECS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class HimitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Hi-Mit II."""

    VERSION = 1

    def __init__(self) -> None:
        self._login_data: dict[str, Any] = {}
        self._homes: list[dict] = []
        self._username: str = ""
        self._password: str = ""

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

    async def async_step_home(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2 — select a home (only shown when account has >1 home)."""
        if user_input is not None:
            selected = next(
                (h for h in self._homes if h["homeId"] == user_input[CONF_HOME_ID]),
                self._homes[0],
            )
            return await self._create_entry(selected)

        home_options = {
            h["homeId"]: h.get("homeName", h["homeId"])
            for h in self._homes
        }
        return self.async_show_form(
            step_id="home",
            data_schema=vol.Schema({
                vol.Required(CONF_HOME_ID): vol.In(home_options),
            }),
        )

    async def _create_entry(self, home: dict) -> FlowResult:
        """Create the config entry with all credentials and token data."""
        home_id   = home["homeId"]
        home_name = home.get("homeName", home_id)

        # Deduplicate — one entry per home
        await self.async_set_unique_id(f"himit_{home_id}")
        self._abort_if_unique_id_configured()

        entry_data: dict[str, Any] = {
            CONF_USERNAME:             self._username,
            CONF_PASSWORD:             self._password,
            CONF_HOME_ID:              home_id,
            CONF_ACCESS_TOKEN:         self._login_data["access_token"],
            CONF_REFRESH_TOKEN:        self._login_data.get("refresh_token", ""),
            CONF_TOKEN_CREATED_MS:     self._login_data.get("token_created_ms", 0),
            CONF_TOKEN_EXPIRE_SECS:    self._login_data.get("token_expire_secs", 7200),
            CONF_REFRESH_EXPIRE_SECS:  self._login_data.get("refresh_expire_secs", 2592000),
        }
        return self.async_create_entry(
            title=f"Hi-Mit II — {home_name}",
            data=entry_data,
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Re-auth flow triggered when a token can no longer be refreshed."""
        return await self.async_step_user(user_input)
