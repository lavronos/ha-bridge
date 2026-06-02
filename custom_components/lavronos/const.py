"""Constants for the LavronOS HA Bridge integration."""

from __future__ import annotations

from logging import Logger, getLogger

DOMAIN = "lavronos"
NAME = "LavronOS HA Bridge"
VERSION = "0.1.4"

CONF_LAVRONOS_URL = "lavronos_url"
CONF_PAIRING_CODE = "pairing_code"
CONF_BRIDGE_TOKEN = "bridge_token"
CONF_HOME_ASSISTANT_NAME = "home_assistant_name"
CONF_HOME_ASSISTANT_VERSION = "home_assistant_version"
CONF_INSTANCE_ID = "instance_id"

PAIR_ENDPOINT = "/api/ha/pair"
SNAPSHOT_ENDPOINT = "/api/ha/snapshot"
STATE_EVENT_ENDPOINT = "/api/ha/events/state"
TEST_CONNECTION_ENDPOINT = "/api/ha/bridge"

REQUEST_TIMEOUT_SECONDS = 15

LOGGER: Logger = getLogger(__package__)
