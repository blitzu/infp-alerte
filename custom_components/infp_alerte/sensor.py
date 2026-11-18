"""Senzori pentru ultimul cutremur relevant."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_QUAKE
from .entity import InfpEntity
from .hub import Hub


@dataclass(frozen=True, kw_only=True)
class InfpSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Hub], Any]


SENSORS: tuple[InfpSensorDescription, ...] = (
    InfpSensorDescription(
        key="last_magnitude",
        translation_key="last_magnitude",
        icon="mdi:waveform",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda hub: hub.last.magnitude if hub.last else None,
    ),
    InfpSensorDescription(
        key="last_distance",
        translation_key="last_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        value_fn=lambda hub: hub.last_distance_km if hub.last else None,
    ),
    InfpSensorDescription(
        key="last_time",
        translation_key="last_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda hub: hub.last.time if hub.last else None,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(InfpSensor(entry.runtime_data, desc) for desc in SENSORS)


class InfpSensor(InfpEntity, SensorEntity):
    """Valoare din ultimul cutremur; atributele complete sunt pe senzorul de magnitudine."""

    entity_description: InfpSensorDescription

    def __init__(self, hub: Hub, description: InfpSensorDescription) -> None:
        super().__init__(hub, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_QUAKE, self._refresh))

    @callback
    def _refresh(self, _payload: dict[str, Any]) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | datetime | None:
        return self.entity_description.value_fn(self._hub)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "last_magnitude" or self._hub.last is None:
            return None
        quake = self._hub.last
        return {
            "region": quake.region,
            "depth_km": round(quake.depth_km, 1),
            "latitude": quake.latitude,
            "longitude": quake.longitude,
            "quake_time": quake.time.isoformat(),
            "source": quake.source,
            "distance_km": self._hub.last_distance_km,
            "revised": self._hub.last_revised,
        }
