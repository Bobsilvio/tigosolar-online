"""Tigo Energy integration setup.

Commit 4: authentication now goes through ``async_create_client`` (factory +
token lifecycle: re-login on 401/expiry, token persisted into the entry).

The data path still consumes the v3 client shapes, so the factory is pinned to
``api_pref="v3"`` here for now; the switch to v4/auto happens once the
coordinator and entity model are reworked (commits 6 & 8).
"""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TigoApiError, TigoAuthError, async_create_client
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Setting up Tigo integration")

    session = async_get_clientsession(hass)

    def _store_token(state: dict[str, Any]) -> None:
        # Persist token state so a restart can reuse a still-valid token.
        if state.get("token") and state.get("token") != entry.data.get("token"):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, **state}
            )

    try:
        client = await async_create_client(
            session,
            entry.data["email"],
            entry.data["password"],
            api_pref="v3",  # TODO(commit 6/8): switch to "auto" with v4 data path
            token_store=_store_token,
        )
        system_id = await client.get_system_id()
    except TigoAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except Exception as err:
        raise ConfigEntryNotReady(f"Tigo setup failed: {err}") from err

    async def update_method():
        try:
            return await client.auth_retry(
                lambda: client.fetch_panel_data(system_id)
            )
        except TigoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TigoApiError as err:
            raise UpdateFailed(str(err)) from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Tigo Panel Data",
        update_method=update_method,
        update_interval=SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "system_id": system_id,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Unloading Tigo integration")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
