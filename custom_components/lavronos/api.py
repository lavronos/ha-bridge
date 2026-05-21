"""LavronOS API client for the HA Bridge integration."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import (
    LOGGER,
    PAIR_ENDPOINT,
    REQUEST_TIMEOUT_SECONDS,
    SNAPSHOT_ENDPOINT,
    STATE_EVENT_ENDPOINT,
    TEST_CONNECTION_ENDPOINT,
)


class LavronOSApiError(Exception):
    """Base error for LavronOS API failures."""


class LavronOSCannotConnectError(LavronOSApiError):
    """Raised when LavronOS cannot be reached."""


class LavronOSPairingError(LavronOSApiError):
    """Raised when pairing is rejected by LavronOS."""


class LavronOSApiClient:
    """Async client for the LavronOS bridge API."""

    def __init__(self, session: ClientSession, lavronos_url: str, bridge_token: str | None = None) -> None:
        """Initialize the API client."""
        self._session = session
        self._base_url = lavronos_url.rstrip("/")
        self._bridge_token = bridge_token

    async def pair(
        self,
        pairing_code: str,
        *,
        home_assistant_name: str,
        home_assistant_version: str,
        instance_id: str | None,
    ) -> str:
        """Pair this Home Assistant instance with LavronOS and return a bridge token."""
        payload = {
            "pairingCode": pairing_code,
            "homeAssistantName": home_assistant_name,
            "homeAssistantVersion": home_assistant_version,
            "instanceId": instance_id,
        }

        data = await self._request("POST", PAIR_ENDPOINT, json=payload, authenticated=False)
        token = data.get("bridgeToken") or data.get("bridge_token") or data.get("token")

        if not isinstance(token, str) or not token:
            raise LavronOSPairingError("LavronOS pairing response did not include a bridge token")

        self._bridge_token = token
        return token

    async def push_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Send a complete Home Assistant snapshot to LavronOS."""
        # TODO: Keep this endpoint shape aligned with the LavronOS backend once it lands.
        await self._request("POST", SNAPSHOT_ENDPOINT, json=snapshot)

    async def push_event(self, event: dict[str, Any]) -> None:
        """Send a state_changed event to LavronOS."""
        await self._request("POST", STATE_EVENT_ENDPOINT, json=event)

    async def test_connection(self) -> bool:
        """Test the current bridge token against LavronOS."""
        # TODO: Confirm the final health endpoint name with the LavronOS backend.
        await self._request("GET", TEST_CONNECTION_ENDPOINT)
        return True

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """Run an authenticated JSON request against LavronOS."""
        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json"}

        if authenticated:
            if not self._bridge_token:
                raise LavronOSApiError("LavronOS bridge token is missing")
            headers["Authorization"] = f"Bearer {self._bridge_token}"

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                response = await self._session.request(method, url, json=json, headers=headers)
                response.raise_for_status()
                if response.content_length == 0:
                    return {}
                data = await response.json(content_type=None)
                if isinstance(data, dict):
                    return data
                raise LavronOSApiError("LavronOS returned an unexpected JSON payload")
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise LavronOSPairingError("LavronOS rejected the bridge credentials") from err
            raise LavronOSApiError(f"LavronOS API returned HTTP {err.status}") from err
        except (asyncio.TimeoutError, ClientError) as err:
            LOGGER.warning("Could not connect to LavronOS at %s: %s", url, err)
            raise LavronOSCannotConnectError("Could not connect to LavronOS") from err
        except ValueError as err:
            raise LavronOSApiError("LavronOS returned invalid JSON") from err
