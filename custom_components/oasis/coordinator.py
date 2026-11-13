"""Polling coordinator for Oasis lights."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OasisAuthError, OasisClient
from .const import CONF_REFRESH_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# A bulb acknowledges a command within about a second, but it reports its state
# to the cloud only on a cycle of about 20 seconds, so the cloud keeps the
# previous value for up to that long. Two rules follow.
#
# A commanded value is always shown for PENDING_SETTLE seconds, even when the
# cloud already reports the same value. The cloud's value may be left over from
# before an earlier command; trusting it would drop the hold, and the next report
# of that earlier command would then flip the entity to the wrong state.
#
# After that the commanded value stays until the cloud agrees, but only up to
# PENDING_TTL, so a command the bulb never applied gives way to the truth.
PENDING_SETTLE = 30.0
PENDING_TTL = 60.0


class OasisCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Fetch every light's state on one schedule, keyed by node and device."""

    def __init__(self, hass: HomeAssistant, client: OasisClient, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.entry = entry
        # key -> parameter name -> (commanded value, settled at, expires at)
        self._pending: dict[str, dict[str, tuple[Any, float, float]]] = {}

    @staticmethod
    def key(node_id: str, device: str) -> str:
        return f"{node_id}::{device}"

    def note_command(self, key: str, payload: dict[str, Any]) -> None:
        """Remember what was just commanded so the UI can show it immediately."""
        now = time.monotonic()
        slot = self._pending.setdefault(key, {})
        for name, value in payload.items():
            slot[name] = (value, now + PENDING_SETTLE, now + PENDING_TTL)

    def params_for(self, key: str) -> dict[str, Any]:
        """Return a bulb's parameters with any still-unconfirmed command applied."""
        params = dict((self.data or {}).get(key, {}).get("params") or {})
        slot = self._pending.get(key)
        if not slot:
            return params
        now = time.monotonic()
        for name, (value, settled, deadline) in list(slot.items()):
            if deadline < now or (settled < now and params.get(name) == value):
                del slot[name]      # expired, or settled and the cloud agrees
                continue
            params[name] = value
        if not slot:
            self._pending.pop(key, None)
        return params

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            lights = await self.client.async_get_lights()
        except OasisAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Error talking to the Oasis cloud: {err}") from err

        self._persist_refresh_token()
        return {self.key(l["node_id"], l["device"]): l for l in lights}

    def _persist_refresh_token(self) -> None:
        """Keep the stored refresh token current so restarts do not need a re-login."""
        token = self.client.refresh_token
        if token and token != self.entry.data.get(CONF_REFRESH_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_REFRESH_TOKEN: token}
            )
