"""Coordinator for LavronOS HA Bridge."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .api import LavronOSApiClient, LavronOSApiError
from .const import LOGGER


class LavronOSBridgeCoordinator:
    """Collect and stream Home Assistant data to LavronOS."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: LavronOSApiClient) -> None:
        """Initialize the bridge coordinator."""
        self.hass = hass
        self.entry = entry
        self.client = client
        self._unsub_state_changed: Callable[[], None] | None = None

    async def async_start(self) -> None:
        """Start the bridge."""
        self._unsub_state_changed = self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)
        await self.async_push_snapshot()

    async def async_unload(self) -> None:
        """Unload the bridge."""
        if self._unsub_state_changed is not None:
            self._unsub_state_changed()
            self._unsub_state_changed = None

    async def async_push_snapshot(self) -> None:
        """Collect and send an initial Home Assistant snapshot."""
        snapshot = self._build_snapshot()

        try:
            await self.client.push_snapshot(snapshot)
            LOGGER.info("Sent Home Assistant snapshot to LavronOS")
        except LavronOSApiError as err:
            LOGGER.warning("Could not send Home Assistant snapshot to LavronOS: %s", err)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        """Forward state changes to LavronOS without blocking Home Assistant."""
        payload = {
            "eventType": EVENT_STATE_CHANGED,
            "timeFired": event.time_fired.isoformat(),
            "origin": _enum_value(event.origin),
            "context": _serialize_context(event.context),
            "entityId": event.data.get("entity_id"),
            "oldState": _serialize_state(event.data.get("old_state")),
            "newState": _serialize_state(event.data.get("new_state")),
        }

        self.hass.async_create_task(self._async_push_state_event(payload))

    async def _async_push_state_event(self, payload: dict[str, Any]) -> None:
        """Push a state change payload to LavronOS."""
        try:
            await self.client.push_event(payload)
        except LavronOSApiError as err:
            LOGGER.debug("Could not send state change to LavronOS: %s", err)

    def _build_snapshot(self) -> dict[str, Any]:
        """Build a Home Assistant snapshot for LavronOS."""
        area_registry = ar.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        states = self.hass.states.async_all()

        return {
            "homeAssistant": {
                "name": self.hass.config.location_name,
                "timeZone": str(self.hass.config.time_zone),
                "latitude": self.hass.config.latitude,
                "longitude": self.hass.config.longitude,
                "unitSystem": {
                    "temperature": _enum_value(getattr(self.hass.config.units, "temperature_unit", None)),
                    "length": _enum_value(getattr(self.hass.config.units, "length_unit", None)),
                    "mass": _enum_value(getattr(self.hass.config.units, "mass_unit", None)),
                    "volume": _enum_value(getattr(self.hass.config.units, "volume_unit", None)),
                },
            },
            "areas": [_serialize_area(area) for area in _registry_values(area_registry, "areas")],
            "devices": [_serialize_device(device) for device in _registry_values(device_registry, "devices")],
            "entities": [_serialize_entity(entity) for entity in _registry_values(entity_registry, "entities")],
            "states": [_serialize_state(state) for state in states],
            "scenes": [_serialize_state(state) for state in states if state.domain == "scene"],
            "scripts": [_serialize_state(state) for state in states if state.domain == "script"],
            "automations": [_serialize_state(state) for state in states if state.domain == "automation"],
        }


def _registry_values(registry: Any, attr: str) -> list[Any]:
    """Return values from a Home Assistant registry internal mapping."""
    values = getattr(registry, attr, {})
    if isinstance(values, dict):
        return list(values.values())
    return list(values)


def _serialize_area(area: Any) -> dict[str, Any]:
    """Serialize an area registry entry."""
    return {
        "id": getattr(area, "id", None),
        "name": getattr(area, "name", None),
        "aliases": sorted(getattr(area, "aliases", []) or []),
        "floorId": getattr(area, "floor_id", None),
        "icon": getattr(area, "icon", None),
        "picture": getattr(area, "picture", None),
    }


def _serialize_device(device: Any) -> dict[str, Any]:
    """Serialize a device registry entry."""
    return {
        "id": getattr(device, "id", None),
        "areaId": getattr(device, "area_id", None),
        "name": getattr(device, "name", None),
        "nameByUser": getattr(device, "name_by_user", None),
        "manufacturer": getattr(device, "manufacturer", None),
        "model": getattr(device, "model", None),
        "modelId": getattr(device, "model_id", None),
        "swVersion": getattr(device, "sw_version", None),
        "hwVersion": getattr(device, "hw_version", None),
        "entryType": _enum_value(getattr(device, "entry_type", None)),
        "disabledBy": _enum_value(getattr(device, "disabled_by", None)),
        "identifiers": _serialize_tuple_set(getattr(device, "identifiers", set())),
        "connections": _serialize_tuple_set(getattr(device, "connections", set())),
        "configEntries": sorted(getattr(device, "config_entries", []) or []),
    }


def _serialize_entity(entity: Any) -> dict[str, Any]:
    """Serialize an entity registry entry."""
    return {
        "entityId": getattr(entity, "entity_id", None),
        "uniqueId": getattr(entity, "unique_id", None),
        "platform": getattr(entity, "platform", None),
        "domain": getattr(entity, "domain", None),
        "deviceId": getattr(entity, "device_id", None),
        "areaId": getattr(entity, "area_id", None),
        "name": getattr(entity, "name", None),
        "originalName": getattr(entity, "original_name", None),
        "icon": getattr(entity, "icon", None),
        "entityCategory": _enum_value(getattr(entity, "entity_category", None)),
        "disabledBy": _enum_value(getattr(entity, "disabled_by", None)),
        "hiddenBy": _enum_value(getattr(entity, "hidden_by", None)),
    }


def _serialize_state(state: State | Any | None) -> dict[str, Any] | None:
    """Serialize a Home Assistant state."""
    if state is None:
        return None

    if isinstance(state, State):
        return state.as_dict()

    return None


def _serialize_context(context: Any) -> dict[str, Any]:
    """Serialize a Home Assistant context."""
    return {
        "id": getattr(context, "id", None),
        "parentId": getattr(context, "parent_id", None),
        "userId": getattr(context, "user_id", None),
    }


def _serialize_tuple_set(values: set[tuple[str, str]] | Any) -> list[list[str]]:
    """Serialize Home Assistant identifier/connection sets."""
    return sorted([list(value) for value in values])


def _enum_value(value: Any) -> str | None:
    """Return a JSON-safe enum value."""
    if value is None:
        return None
    return getattr(value, "value", str(value))
