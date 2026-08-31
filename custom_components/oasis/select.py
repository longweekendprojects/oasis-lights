"""Warmth presets for Oasis bulbs.

The Oasis app presents colour temperature as named presets rather than a Kelvin
slider, so this exposes the same choices to Home Assistant. Picking one changes
warmth only; it never switches the bulb on or off, which matches the app.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PRESETS
from .coordinator import OasisCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a warmth preset control for every bulb that supports colour temperature."""
    coordinator: OasisCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        OasisWarmthSelect(coordinator, key)
        for key, record in coordinator.data.items()
        if record.get("key_cct")
    )


class OasisWarmthSelect(CoordinatorEntity[OasisCoordinator], SelectEntity):
    """Named colour temperature presets, mirroring the Oasis app."""

    _attr_has_entity_name = True
    _attr_name = "Warmth"
    _attr_icon = "mdi:white-balance-sunny"

    @property
    def options(self) -> list[str]:
        return list(PRESETS)

    def __init__(self, coordinator: OasisCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        record = coordinator.data[key]
        self._attr_unique_id = f"{key}::warmth"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, record["node_id"])})

    @property
    def _record(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._key, {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._record.get("online"))

    @property
    def current_option(self) -> str | None:
        """Report the preset closest to the bulb's actual colour temperature.

        The bulb can sit at any Kelvin value, including one set from the app or
        by its own schedule, so match the nearest preset rather than requiring an
        exact hit and showing nothing the rest of the time.
        """
        key = self._record.get("key_cct")
        if not key:
            return None
        value = self.coordinator.params_for(self._key).get(key)
        if not value:
            return None
        return min(PRESETS, key=lambda name: abs(PRESETS[name] - int(value)))

    async def async_select_option(self, option: str) -> None:
        kelvin = PRESETS.get(option)
        if kelvin is None:
            return
        record = self._record
        payload = {record["key_cct"]: kelvin}
        await self.coordinator.client.async_set_params(
            record["node_id"], record["device"], payload
        )
        # Hold the chosen preset until the cloud confirms it, otherwise the
        # selection visibly reverts for a few seconds.
        self.coordinator.note_command(self._key, payload)
        self.async_write_ha_state()
