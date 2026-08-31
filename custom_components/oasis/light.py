"""Light platform for Oasis smart bulbs."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_MAX_KELVIN, DEFAULT_MIN_KELVIN, DOMAIN
from .coordinator import OasisCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Oasis lights from a config entry."""
    coordinator: OasisCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        OasisLight(coordinator, key) for key in coordinator.data
    )


def _bounds(param_defs: list[dict[str, Any]], name: str | None) -> tuple[int, int] | None:
    """Read a parameter's declared range from the node's own config."""
    if not name:
        return None
    for param in param_defs:
        if param.get("name") == name:
            spec = param.get("bounds") or {}
            low, high = spec.get("min"), spec.get("max")
            if isinstance(low, int) and isinstance(high, int) and low < high:
                return low, high
    return None


class OasisLight(CoordinatorEntity[OasisCoordinator], LightEntity):
    """A single Oasis bulb."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: OasisCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        record = coordinator.data[key]
        self._attr_unique_id = key

        if record.get("key_cct"):
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
        elif record.get("key_brightness"):
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

        low_high = _bounds(record.get("param_defs", []), record.get("key_cct"))
        self._attr_min_color_temp_kelvin = low_high[0] if low_high else DEFAULT_MIN_KELVIN
        self._attr_max_color_temp_kelvin = low_high[1] if low_high else DEFAULT_MAX_KELVIN

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, record["node_id"])},
            name=record["name"],
            manufacturer="Oasis (Mixtiles)",
            model=(record.get("serial") or "Oasis Light")[:6] or "Oasis Light",
            sw_version=record.get("fw_version"),
        )

    @property
    def _record(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._key, {})

    @property
    def _params(self) -> dict[str, Any]:
        """Parameters including any command the cloud has not confirmed yet."""
        return self.coordinator.params_for(self._key)

    @property
    def available(self) -> bool:
        return super().available and bool(self._record.get("online"))

    @property
    def is_on(self) -> bool | None:
        key = self._record.get("key_power")
        if not key:
            return None
        return bool(self._params.get(key))

    @property
    def brightness(self) -> int | None:
        key = self._record.get("key_brightness")
        if not key:
            return None
        value = self._params.get(key)
        if value is None:
            return None
        return round(max(0, min(100, int(value))) * 255 / 100)

    @property
    def color_temp_kelvin(self) -> int | None:
        key = self._record.get("key_cct")
        if not key:
            return None
        value = self._params.get(key)
        return int(value) if value else None

    async def _async_send(self, payload: dict[str, Any]) -> None:
        record = self._record
        await self.coordinator.client.async_set_params(
            record["node_id"], record["device"], payload
        )
        # Show the commanded value straight away and hold it until the cloud
        # agrees. Refreshing here instead would read back the stale value and
        # make the control visibly snap back before correcting itself.
        self.coordinator.note_command(self._key, payload)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        record = self._record
        payload: dict[str, Any] = {}
        if key := record.get("key_power"):
            payload[key] = True
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            if key := record.get("key_brightness"):
                payload[key] = max(0, min(100, round(int(brightness) * 100 / 255)))
        if (kelvin := kwargs.get(ATTR_COLOR_TEMP_KELVIN)) is not None:
            if key := record.get("key_cct"):
                payload[key] = int(kelvin)
        if payload:
            await self._async_send(payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if key := self._record.get("key_power"):
            await self._async_send({key: False})
