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
        entity_by_id, device_by_id, area_by_id = self._registry_context()
        payload = {
            "eventType": EVENT_STATE_CHANGED,
            "timeFired": event.time_fired.isoformat(),
            "origin": _enum_value(event.origin),
            "context": _serialize_context(event.context),
            "entityId": event.data.get("entity_id"),
            "oldState": _serialize_state(event.data.get("old_state"), entity_by_id, device_by_id, area_by_id),
            "newState": _serialize_state(event.data.get("new_state"), entity_by_id, device_by_id, area_by_id),
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
        entity_by_id, device_by_id, area_by_id = self._registry_context()
        area_registry = ar.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        states = self.hass.states.async_all()
        areas = _registry_values(area_registry, "areas")
        devices = _registry_values(device_registry, "devices")
        entities = _registry_values(entity_registry, "entities")

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
            "areas": [_serialize_area(area) for area in areas],
            "devices": [_serialize_device(device) for device in devices],
            "entities": [_serialize_entity(entity) for entity in entities],
            "states": [_serialize_state(state, entity_by_id, device_by_id, area_by_id) for state in states],
            "scenes": [_serialize_state(state, entity_by_id, device_by_id, area_by_id) for state in states if state.domain == "scene"],
            "scripts": [_serialize_state(state, entity_by_id, device_by_id, area_by_id) for state in states if state.domain == "script"],
            "automations": [_serialize_state(state, entity_by_id, device_by_id, area_by_id) for state in states if state.domain == "automation"],
        }

    def _registry_context(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Return registry lookup maps for enriching states and events."""
        area_registry = ar.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        areas = _registry_values(area_registry, "areas")
        devices = _registry_values(device_registry, "devices")
        entities = _registry_values(entity_registry, "entities")

        return (
            {getattr(entity, "entity_id", None): entity for entity in entities if getattr(entity, "entity_id", None)},
            {getattr(device, "id", None): device for device in devices if getattr(device, "id", None)},
            {getattr(area, "id", None): area for area in areas if getattr(area, "id", None)},
        )


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


def _serialize_state(
    state: State | Any | None,
    entity_by_id: dict[str, Any] | None = None,
    device_by_id: dict[str, Any] | None = None,
    area_by_id: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Serialize a Home Assistant state."""
    if state is None:
        return None

    if isinstance(state, State):
        data = state.as_dict()
        entity = (entity_by_id or {}).get(state.entity_id)
        device_id = getattr(entity, "device_id", None) if entity is not None else None
        device = (device_by_id or {}).get(device_id)
        area_id = getattr(entity, "area_id", None) if entity is not None else None

        if area_id is None and device is not None:
            area_id = getattr(device, "area_id", None)

        area = (area_by_id or {}).get(area_id)

        data.update(
            {
                "entityId": state.entity_id,
                "domain": state.domain,
                "name": state.name,
                "deviceId": device_id,
                "deviceName": _device_name(device),
                "areaId": area_id,
                "areaName": getattr(area, "name", None) if area is not None else None,
                "registryName": getattr(entity, "name", None) if entity is not None else None,
                "originalName": getattr(entity, "original_name", None) if entity is not None else None,
                "entityCategory": _enum_value(getattr(entity, "entity_category", None)) if entity is not None else None,
                "disabledBy": _enum_value(getattr(entity, "disabled_by", None)) if entity is not None else None,
                "hiddenBy": _enum_value(getattr(entity, "hidden_by", None)) if entity is not None else None,
            }
        )
        return data

    return None


def _device_name(device: Any | None) -> str | None:
    """Return the most useful Home Assistant device name."""
    if device is None:
        return None

    return (
        getattr(device, "name_by_user", None)
        or getattr(device, "name", None)
        or getattr(device, "original_name", None)
        or getattr(device, "default_name", None)
        or getattr(device, "model", None)
    )


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
