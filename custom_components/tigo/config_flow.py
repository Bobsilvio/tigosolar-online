"""Config & options flow for the Tigo integration.

Validates credentials with a real login (the v1 flow created the entry
blindly), supports premium + API-version selection, multi-system choice,
reauth, and an options flow for intervals / per-panel metric toggles /
logging.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import API_AUTO, API_V3, API_V4, TigoApiError, TigoAuthError, async_create_client
from .const import (
    CONF_API_VERSION,
    CONF_ENABLE_CURRENT,
    CONF_ENABLE_RSSI,
    CONF_ENABLE_VOLTAGE,
    CONF_ENERGY_POLL_INTERVAL,
    CONF_NIGHT_SKIP,
    CONF_PANEL_SCAN_INTERVAL,
    CONF_PREMIUM,
    CONF_PROBE_EXTRA_HARDWARE,
    CONF_VERBOSE_LOGGING,
    DEFAULT_ENERGY_POLL_INTERVAL,
    DEFAULT_NIGHT_SKIP,
    DEFAULT_PANEL_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_API_CHOICES = [API_AUTO, API_V4, API_V3]


async def _validate(hass, email: str, password: str, api_pref: str) -> list[dict]:
    """Return the account's systems, or raise for the flow to map to errors."""
    session = async_get_clientsession(hass)
    client = await async_create_client(session, email, password, api_pref=api_pref)
    if hasattr(client, "get_systems"):
        systems = await client.get_systems()
        if systems:
            return systems
    return [{"system_id": await client.get_system_id()}]


class TigoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._creds: dict[str, Any] = {}
        self._systems: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._systems = await _validate(
                    self.hass,
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                    user_input.get(CONF_API_VERSION, API_AUTO),
                )
            except TigoAuthError:
                errors["base"] = "invalid_auth"
            except (TigoApiError, Exception):  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                self._creds = {
                    CONF_EMAIL: user_input[CONF_EMAIL],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_API_VERSION: user_input.get(CONF_API_VERSION, API_AUTO),
                    CONF_PREMIUM: user_input.get(CONF_PREMIUM, False),
                }
                if len(self._systems) > 1:
                    return await self.async_step_system()
                return await self._create(self._first_system_id())

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_PREMIUM, default=False): bool,
                vol.Optional(CONF_API_VERSION, default=API_AUTO): vol.In(
                    _API_CHOICES
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_system(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return await self._create(int(user_input["system_id"]))
        choices = {
            str(s.get("system_id") or s.get("id")): (
                f"{s.get('name', 'System')} ({s.get('system_id') or s.get('id')})"
            )
            for s in self._systems
        }
        return self.async_show_form(
            step_id="system",
            data_schema=vol.Schema({vol.Required("system_id"): vol.In(choices)}),
        )

    def _first_system_id(self) -> int:
        s = self._systems[0]
        return int(s.get("system_id") or s.get("id"))

    async def _create(self, system_id: int) -> FlowResult:
        await self.async_set_unique_id(f"tigo-{system_id}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Tigo System {system_id}",
            data={
                CONF_EMAIL: self._creds[CONF_EMAIL],
                CONF_PASSWORD: self._creds[CONF_PASSWORD],
                "system_id": system_id,
            },
            options={
                CONF_PREMIUM: self._creds[CONF_PREMIUM],
                CONF_API_VERSION: self._creds[CONF_API_VERSION],
            },
        )

    # ---- reauth ----
    async def async_step_reauth(self, _entry_data: dict) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if user_input is not None:
            try:
                await _validate(
                    self.hass,
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                    entry.options.get(CONF_API_VERSION, API_AUTO),
                )
            except TigoAuthError:
                errors["base"] = "invalid_auth"
            except (TigoApiError, Exception):  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "TigoOptionsFlow":
        return TigoOptionsFlow(config_entry)


class TigoOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        o = self.entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_API_VERSION,
                    default=o.get(CONF_API_VERSION, API_AUTO),
                ): vol.In(_API_CHOICES),
                vol.Optional(
                    CONF_PREMIUM, default=o.get(CONF_PREMIUM, False)
                ): bool,
                vol.Optional(
                    CONF_PANEL_SCAN_INTERVAL,
                    default=o.get(
                        CONF_PANEL_SCAN_INTERVAL, DEFAULT_PANEL_SCAN_INTERVAL
                    ),
                ): vol.All(int, vol.Range(min=15, max=3600)),
                vol.Optional(
                    CONF_ENERGY_POLL_INTERVAL,
                    default=o.get(
                        CONF_ENERGY_POLL_INTERVAL, DEFAULT_ENERGY_POLL_INTERVAL
                    ),
                ): vol.All(int, vol.Range(min=60, max=7200)),
                vol.Optional(
                    CONF_NIGHT_SKIP,
                    default=o.get(CONF_NIGHT_SKIP, DEFAULT_NIGHT_SKIP),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_VOLTAGE,
                    default=o.get(CONF_ENABLE_VOLTAGE, False),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_CURRENT,
                    default=o.get(CONF_ENABLE_CURRENT, False),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_RSSI, default=o.get(CONF_ENABLE_RSSI, False)
                ): bool,
                vol.Optional(
                    CONF_VERBOSE_LOGGING,
                    default=o.get(CONF_VERBOSE_LOGGING, False),
                ): bool,
                vol.Optional(
                    CONF_PROBE_EXTRA_HARDWARE,
                    default=o.get(CONF_PROBE_EXTRA_HARDWARE, False),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
