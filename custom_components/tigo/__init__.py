"""Tigo Energy integration setup.

Commit 8: the integration now runs on the v4/auto data path via
``TigoDataUpdateCoordinator``; entities (sensor + binary_sensor) read from it.
"""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import API_AUTO, TigoAuthError, async_create_client
from .const import CONF_API_VERSION, CONF_VERBOSE_LOGGING, DOMAIN
from .coordinator import TigoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Setting up Tigo integration")

    opts = {**entry.data, **entry.options}
    if opts.get(CONF_VERBOSE_LOGGING):
        logging.getLogger("custom_components.tigo").setLevel(logging.DEBUG)

    session = async_get_clientsession(hass)

    def _store_token(state: dict[str, Any]) -> None:
        if state.get("token") and state.get("token") != entry.data.get("token"):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, **state}
            )

    try:
        client = await async_create_client(
            session,
            entry.data["email"],
            entry.data["password"],
            api_pref=opts.get(CONF_API_VERSION, API_AUTO),
            token_store=_store_token,
        )
        systems = await _resolve_systems(client)
        system_id = _pick_system(entry, systems)
    except TigoAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(f"Tigo setup failed: {err}") from err

    coordinator = TigoDataUpdateCoordinator(hass, entry, client, system_id)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "system_id": system_id,
    }

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _resolve_systems(client) -> list[dict]:
    """Return [{system_id,...}] across v3/v4 client shapes."""
    if hasattr(client, "get_systems"):
        try:
            return await client.get_systems()
        except Exception:  # noqa: BLE001
            pass
    sid = await client.get_system_id()
    return [{"system_id": sid}]


def _pick_system(entry: ConfigEntry, systems: list[dict]) -> int:
    want = entry.data.get("system_id")
    if want is not None:
        return int(want)
    if not systems:
        raise ConfigEntryNotReady("No Tigo systems on this account")
    first = systems[0]
    return int(first.get("system_id") or first.get("id"))


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Unloading Tigo integration")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
