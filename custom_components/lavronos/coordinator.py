"""Coordinator for LavronOS HA Bridge."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .api import LavronOSApiClient, LavronOSApiError
from .const import LOGGER

REGISTRY_UPDATED_EVENTS = ("area_registry_updated", "device_registry_updated", "entity_registry_updated")
SNAPSHOT_INTERVAL = timedelta(minutes=1)
SNAPSHOT_REFRESH_DELAY_SECONDS = 2


class LavronOSBridgeCoordinator:
    """Collect and stream Home Assistant data to LavronOS."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: LavronOSApiClient) -> None:
        """Initialize the bridge coordinator."""
        self.hass = hass
        self.entry = entry
        self.client = client
        self._unsub_state_changed: Callable[[], None] | None = None
        self._unsub_registry_changed: list[Callable[[], None]] = []
        self._unsub_snapshot_refresh: Callable[[], None] | None = None
        self._unsub_snapshot_refresh_delay: Callable[[], None] | None = None

    async def async_start(self) -> None:
        """Start the bridge."""
        self._unsub_state_changed = self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)
        self._unsub_registry_changed = [
            self.hass.bus.async_listen(event_type, self._async_registry_changed)
            for event_type in REGISTRY_UPDATED_EVENTS
        ]
        self._unsub_snapshot_refresh = async_track_time_interval(self.hass, self._async_refresh_snapshot, SNAPSHOT_INTERVAL)
        await self.async_push_snapshot()

    async def async_unload(self) -> None:
        """Unload the bridge."""
        if self._unsub_state_changed is not None:
            self._unsub_state_changed()
            self._unsub_state_changed = None
        for unsubscribe in self._unsub_registry_changed:
            unsubscribe()
        self._unsub_registry_changed = []
        if self._unsub_snapshot_refresh is not None:
            self._unsub_snapshot_refresh()
            self._unsub_snapshot_refresh = None
        if self._unsub_snapshot_refresh_delay is not None:
            self._unsub_snapshot_refresh_delay()
            self._unsub_snapshot_refresh_delay = None

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

    @callback
    def _async_refresh_snapshot(self, _now: Any) -> None:
        """Refresh registry snapshots so LavronOS catches room/device changes without re-pairing."""
        self._schedule_snapshot_refresh()

    @callback
    def _async_registry_changed(self, event: Event) -> None:
        """Refresh snapshots when Home Assistant registry structure changes."""
        LOGGER.debug("Home Assistant registry changed, scheduling snapshot refresh: %s", event.event_type)
        self._schedule_snapshot_refresh()

    @callback
    def _async_run_scheduled_snapshot_refresh(self, _now: Any) -> None:
        """Run a debounced registry snapshot refresh."""
        self._unsub_snapshot_refresh_delay = None
        self.hass.async_create_task(self.async_push_snapshot())

    @callback
    def _schedule_snapshot_refresh(self) -> None:
        """Debounce snapshot refreshes so registry bursts produce one snapshot."""
        if self._unsub_snapshot_refresh_delay is not None:
            self._unsub_snapshot_refresh_delay()
        self._unsub_snapshot_refresh_delay = async_call_later(
            self.hass,
            SNAPSHOT_REFRESH_DELAY_SECONDS,
            self._async_run_scheduled_snapshot_refresh,
        )

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
            "devices": [_serialize_device(device, area_by_id) for device in devices],
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
            {_registry_id(entity, "entity_id", "entityId"): entity for entity in entities if _registry_id(entity, "entity_id", "entityId")},
            {_registry_id(device, "id", "device_id", "deviceId"): device for device in devices if _registry_id(device, "id", "device_id", "deviceId")},
            {_registry_id(area, "id", "area_id", "areaId"): area for area in areas if _registry_id(area, "id", "area_id", "areaId")},
        )


def _registry_values(registry: Any, attr: str) -> list[Any]:
    """Return values from a Home Assistant registry internal mapping."""
    values = getattr(registry, attr, {})
    if values is None:
        return []
    if isinstance(values, Mapping):
        return [{"__registry_key": str(key), "__registry_value": value} for key, value in values.items()]
    return [{"__registry_key": None, "__registry_value": value} for value in list(values)]


def _registry_id(entry: Any, *names: str) -> str | None:
    """Return the stable Home Assistant registry id, falling back to mapping keys."""
    value = _registry_field(entry, *names)
    if value is None and isinstance(entry, Mapping):
        value = entry.get("__registry_key")
    if value is None:
        return None
    return str(value)


def _registry_field(entry: Any, *names: str) -> Any:
    """Read a registry field from Home Assistant objects or dict-backed entries."""
    value = entry
    if isinstance(entry, Mapping) and "__registry_value" in entry:
        value = entry.get("__registry_value")

    if isinstance(value, Mapping):
        for name in names:
            field = value.get(name)
            if field is not None:
                return field
        return None

    for name in names:
        field = getattr(value, name, None)
        if field is not None:
            return field
    return None


def _serialize_area(area: Any) -> dict[str, Any]:
    """Serialize an area registry entry."""
    return {
        "id": _registry_id(area, "id", "area_id", "areaId"),
        "name": _registry_field(area, "name"),
        "aliases": sorted(_registry_field(area, "aliases") or []),
        "floorId": _registry_field(area, "floor_id", "floorId"),
        "icon": _registry_field(area, "icon"),
        "picture": _registry_field(area, "picture"),
    }


def _serialize_device(device: Any, area_by_id: dict[str, Any] | None = None) -> dict[str, Any]:
    """Serialize a device registry entry."""
    area_id = _registry_field(device, "area_id", "areaId")
    area = (area_by_id or {}).get(area_id)

    return {
        "id": _registry_id(device, "id", "device_id", "deviceId"),
        "areaId": area_id,
        "areaName": _registry_field(area, "name") if area is not None else None,
        "suggestedArea": _registry_field(device, "suggested_area", "suggestedArea"),
        "name": _registry_field(device, "name"),
        "nameByUser": _registry_field(device, "name_by_user", "nameByUser"),
        "manufacturer": _registry_field(device, "manufacturer"),
        "model": _registry_field(device, "model"),
        "modelId": _registry_field(device, "model_id", "modelId"),
        "swVersion": _registry_field(device, "sw_version", "swVersion"),
        "hwVersion": _registry_field(device, "hw_version", "hwVersion"),
        "entryType": _enum_value(_registry_field(device, "entry_type", "entryType")),
        "disabledBy": _enum_value(_registry_field(device, "disabled_by", "disabledBy")),
        "identifiers": _serialize_tuple_set(_registry_field(device, "identifiers") or set()),
        "connections": _serialize_tuple_set(_registry_field(device, "connections") or set()),
        "configEntries": sorted(_registry_field(device, "config_entries", "configEntries") or []),
    }


def _serialize_entity(entity: Any) -> dict[str, Any]:
    """Serialize an entity registry entry."""
    return {
        "entityId": _registry_id(entity, "entity_id", "entityId"),
        "uniqueId": _registry_field(entity, "unique_id", "uniqueId"),
        "platform": _registry_field(entity, "platform"),
        "domain": _registry_field(entity, "domain"),
        "deviceId": _registry_field(entity, "device_id", "deviceId"),
        "areaId": _registry_field(entity, "area_id", "areaId"),
        "name": _registry_field(entity, "name"),
        "originalName": _registry_field(entity, "original_name", "originalName"),
        "icon": _registry_field(entity, "icon"),
        "entityCategory": _enum_value(_registry_field(entity, "entity_category", "entityCategory")),
        "disabledBy": _enum_value(_registry_field(entity, "disabled_by", "disabledBy")),
        "hiddenBy": _enum_value(_registry_field(entity, "hidden_by", "hiddenBy")),
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
        data = dict(state.as_dict())
        entity = (entity_by_id or {}).get(state.entity_id)
        device_id = _registry_field(entity, "device_id", "deviceId") if entity is not None else None
        device = (device_by_id or {}).get(device_id)
        area_id = _registry_field(entity, "area_id", "areaId") if entity is not None else None

        if area_id is None and device is not None:
            area_id = _registry_field(device, "area_id", "areaId")

        area = (area_by_id or {}).get(area_id)

        data.update(
            {
                "entityId": state.entity_id,
                "domain": state.domain,
                "name": state.name,
                "deviceId": device_id,
                "deviceName": _device_name(device),
                "areaId": area_id,
                "areaName": _registry_field(area, "name") if area is not None else None,
                "registryName": _registry_field(entity, "name") if entity is not None else None,
                "originalName": _registry_field(entity, "original_name", "originalName") if entity is not None else None,
                "entityCategory": _enum_value(_registry_field(entity, "entity_category", "entityCategory")) if entity is not None else None,
                "disabledBy": _enum_value(_registry_field(entity, "disabled_by", "disabledBy")) if entity is not None else None,
                "hiddenBy": _enum_value(_registry_field(entity, "hidden_by", "hiddenBy")) if entity is not None else None,
            }
        )
        return data

    return None


def _device_name(device: Any | None) -> str | None:
    """Return the most useful Home Assistant device name."""
    if device is None:
        return None

    return (
        _registry_field(device, "name_by_user", "nameByUser")
        or _registry_field(device, "name")
        or _registry_field(device, "original_name", "originalName")
        or _registry_field(device, "default_name", "defaultName")
        or _registry_field(device, "model")
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
