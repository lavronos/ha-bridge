"""LavronOS HA Bridge integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .api import LavronOSApiClient
from .const import CONF_BRIDGE_TOKEN, CONF_LAVRONOS_URL, DOMAIN, LOGGER
from .coordinator import LavronOSBridgeCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LavronOS HA Bridge from a config entry."""
    session = aiohttp_client.async_get_clientsession(hass)
    client = LavronOSApiClient(
        session,
        entry.data[CONF_LAVRONOS_URL],
        entry.data[CONF_BRIDGE_TOKEN],
    )
    coordinator = LavronOSBridgeCoordinator(hass, entry, client)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_start()
    LOGGER.info("LavronOS HA Bridge started")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload LavronOS HA Bridge."""
    coordinator: LavronOSBridgeCoordinator | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if coordinator is not None:
        await coordinator.async_unload()

    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)

    LOGGER.info("LavronOS HA Bridge unloaded")
    return True
