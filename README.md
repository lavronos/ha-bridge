# LavronOS HA Bridge

LavronOS HA Bridge is a Home Assistant custom integration that connects Home Assistant to LavronOS without requiring users to paste a Home Assistant long-lived access token into LavronOS.

Home Assistant remains the automation and device engine. LavronOS is not a Home Assistant replacement; it is a modern UX layer that receives rooms, devices, entities, scenes, automations, scripts and realtime states from Home Assistant.

The main LavronOS app runs separately in Docker. This bridge runs inside Home Assistant and uses Home Assistant internal APIs through the `hass` object.

## Status

This is the first MVP version.

Implemented:

- HACS-compatible custom integration structure.
- Home Assistant UI config flow.
- Pairing with LavronOS through `POST /api/ha/pair`.
- Bridge token storage in the Home Assistant config entry.
- Initial Home Assistant snapshot push to LavronOS with area, device and entity registry context.
- Debounced snapshot refresh on Home Assistant area, device and entity registry changes, plus periodic snapshot refresh as a fallback.
- Realtime `state_changed` event push to LavronOS with friendly names and registry context.
- Diagnostics with sensitive token redaction.

Not implemented yet:

- Advanced automation creation.
- Device creation.
- Camera streaming.
- Frontend panels.

## Installation With HACS

1. Open HACS in Home Assistant.
2. Add a custom repository:

   ```text
   https://github.com/lavronos/ha-bridge
   ```

3. Select category: `Integration`.
4. Install `LavronOS HA Bridge`.
5. Restart Home Assistant.
6. Go to Settings -> Devices & Services.
7. Add Integration -> `LavronOS`.
8. Enter the LavronOS URL and pairing code.

Example LavronOS URL:

```text
http://192.168.1.135:3000
```

This is the URL of the LavronOS web app, not the Home Assistant URL. The bridge runs on the Home Assistant server and sends data out to LavronOS, so it must know where LavronOS is reachable on the local network. Home Assistant mobile and desktop clients do not remove this requirement because they are only clients for the Home Assistant UI.

The pairing code is generated inside the LavronOS setup wizard.

## Pairing

When the integration is added in Home Assistant, it sends:

```http
POST {lavronos_url}/api/ha/pair
```

Payload:

```json
{
  "pairingCode": "123456",
  "homeAssistantName": "Home",
  "homeAssistantVersion": "2026.x.x",
  "instanceId": "home-assistant-instance-id"
}
```

LavronOS should return a bridge token:

```json
{
  "bridgeToken": "token-generated-by-lavronos"
}
```

The bridge token is stored inside Home Assistant config entry data. Home Assistant admin credentials are never stored, and LavronOS does not need a Home Assistant long-lived access token.

## Snapshot

After setup, the bridge collects and sends an initial snapshot to LavronOS. It also refreshes the snapshot when Home Assistant area, device or entity registries change, and keeps a periodic refresh as a fallback while the integration is loaded. New spaces, devices and registry changes can appear in LavronOS without creating a new pairing code.

When the bridge code itself is updated through HACS or a custom repository install, Home Assistant still needs an integration reload or restart so it loads the new Python files. That reload does not require disconnecting and re-pairing the LavronOS bridge.

```http
POST {lavronos_url}/api/ha/snapshot
Authorization: Bearer <bridgeToken>
```

Snapshot includes:

- Home Assistant config summary.
- Areas / rooms from the area registry.
- Devices from the device registry.
- Entities from the entity registry.
- Current states.
- Scenes.
- Scripts.
- Automations.
- Registry-derived area and device context on state rows so LavronOS can group entities into understandable rooms and devices.

## Realtime Updates

The bridge subscribes to Home Assistant `state_changed` events and sends state updates to LavronOS:

```http
POST {lavronos_url}/api/ha/events/state
Authorization: Bearer <bridgeToken>
```

For the MVP, only `state_changed` events are forwarded. Other Home Assistant internal events are intentionally left out for now.

## Security

- Home Assistant admin credentials are not stored.
- Home Assistant long-lived access tokens are not required inside LavronOS.
- Only the LavronOS bridge token is stored in Home Assistant.
- Communication is local-first.
- HTTPS is supported by URL, but local HTTP URLs are allowed for the MVP.

## Development

Repository structure:

```text
custom_components/
  lavronos/
    __init__.py
    manifest.json
    config_flow.py
    const.py
    coordinator.py
    api.py
    diagnostics.py
hacs.json
README.md
LICENSE
.gitignore
```

This repository is intended to be added to HACS as a custom integration repository.
