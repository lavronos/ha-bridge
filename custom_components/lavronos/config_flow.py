"""Config flow for LavronOS HA Bridge."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import __version__ as HOME_ASSISTANT_VERSION
from homeassistant.helpers import aiohttp_client, instance_id

from .api import LavronOSApiClient, LavronOSCannotConnectError, LavronOSPairingError
from .const import (
    CONF_BRIDGE_TOKEN,
    CONF_HOME_ASSISTANT_NAME,
    CONF_HOME_ASSISTANT_VERSION,
    CONF_INSTANCE_ID,
    CONF_LAVRONOS_URL,
    CONF_PAIRING_CODE,
    DOMAIN,
    LOGGER,
)


class LavronOSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LavronOS HA Bridge."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            lavronos_url = _normalize_url(user_input[CONF_LAVRONOS_URL])
            pairing_code = user_input[CONF_PAIRING_CODE].strip()

            if not _is_valid_local_url(lavronos_url):
                errors["base"] = "invalid_url"
            elif not pairing_code:
                errors[CONF_PAIRING_CODE] = "invalid_pairing_code"
            else:
                home_assistant_name = self.hass.config.location_name or "Home Assistant"
                ha_instance_id = await _async_get_instance_id(self.hass)
                await self.async_set_unique_id(ha_instance_id or lavronos_url)
                self._abort_if_unique_id_configured()

                session = aiohttp_client.async_get_clientsession(self.hass)
                client = LavronOSApiClient(session, lavronos_url)

                try:
                    bridge_token = await client.pair(
                        pairing_code,
                        home_assistant_name=home_assistant_name,
                        home_assistant_version=HOME_ASSISTANT_VERSION,
                        instance_id=ha_instance_id,
                    )
                except LavronOSPairingError as err:
                    LOGGER.warning("LavronOS pairing failed: %s", err)
                    errors["base"] = "invalid_pairing_code"
                except LavronOSCannotConnectError as err:
                    LOGGER.warning("Could not connect to LavronOS during pairing: %s", err)
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001 - config flows should return clean UI errors.
                    LOGGER.exception("Unexpected error while pairing LavronOS HA Bridge")
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title="LavronOS",
                        data={
                            CONF_LAVRONOS_URL: lavronos_url,
                            CONF_BRIDGE_TOKEN: bridge_token,
                            CONF_HOME_ASSISTANT_NAME: home_assistant_name,
                            CONF_HOME_ASSISTANT_VERSION: HOME_ASSISTANT_VERSION,
                            CONF_INSTANCE_ID: ha_instance_id,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LAVRONOS_URL, default="http://192.168.1.135:3000"): str,
                    vol.Required(CONF_PAIRING_CODE): str,
                }
            ),
            errors=errors,
        )


async def _async_get_instance_id(hass: Any) -> str | None:
    """Return the Home Assistant instance ID when available."""
    try:
        return await instance_id.async_get(hass)
    except Exception:  # noqa: BLE001 - instance ID should not block pairing.
        LOGGER.debug("Home Assistant instance ID is not available yet", exc_info=True)
        return None


def _normalize_url(value: str) -> str:
    """Normalize the LavronOS URL."""
    return value.strip().rstrip("/")


def _is_valid_local_url(value: str) -> bool:
    """Validate HTTP(S) URLs while allowing local HTTP for the MVP."""
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
