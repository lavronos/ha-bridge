"""Diagnostics support for LavronOS HA Bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_BRIDGE_TOKEN, CONF_PAIRING_CODE, DOMAIN

TO_REDACT = {CONF_BRIDGE_TOKEN, CONF_PAIRING_CODE}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "counts": {
            "areas": len(getattr(area_registry, "areas", {})),
            "devices": len(getattr(device_registry, "devices", {})),
            "entities": len(getattr(entity_registry, "entities", {})),
            "states": len(hass.states.async_all()),
        },
        "runtime": {
            "loaded": entry.entry_id in hass.data.get(DOMAIN, {}),
        },
    }
