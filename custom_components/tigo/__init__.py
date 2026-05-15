"""Tigo Energy integration setup.

Commit 2: same runtime behaviour as before, but all HTTP now goes through the
async ``api`` package using Home Assistant's shared aiohttp session (no more
synchronous ``requests`` in an executor, no per-call ``ClientSession``).
"""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TigoApiError, TigoV3Client
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Setting up Tigo integration")

    session = async_get_clientsession(hass)
    client = TigoV3Client(session)

    try:
        await client.login(entry.data["email"], entry.data["password"])
        system_id = await client.get_system_id()

        async def update_method():
            try:
                return await client.fetch_panel_data(system_id)
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

    except Exception as e:
        raise ConfigEntryNotReady(f"Tigo setup failed: {e}") from e

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Unloading Tigo integration")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
