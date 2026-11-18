"""Entitatea `event`: se declanseaza la fiecare cutremur relevant (sursa pentru automatizari si blueprint)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPE_QUAKE, SIGNAL_QUAKE
from .entity import InfpEntity
from .hub import Hub


def event_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    """Atributele evenimentului, in forma folosita de blueprint si de automatizari."""
    quake = payload["quake"]
    return {
        "magnitude": quake.magnitude,
        "distance_km": payload["distance_km"],
        "depth_km": round(quake.depth_km, 1),
        "latitude": quake.latitude,
        "longitude": quake.longitude,
        "region": quake.region,
        "quake_time": quake.time.isoformat(),
        "source": quake.source,
        "revised": payload["revised"],
        "previous_magnitude": payload.get("previous_magnitude"),
    }


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([QuakeEvent(entry.runtime_data)])


class QuakeEvent(InfpEntity, EventEntity):
    """Un eveniment `cutremur` cu magnitudine, distanta, adancime, ora si sursa."""

    _attr_event_types = [EVENT_TYPE_QUAKE]

    def __init__(self, hub: Hub) -> None:
        super().__init__(hub, "quake")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_QUAKE, self._handle))

    @callback
    def _handle(self, payload: dict[str, Any]) -> None:
        self._trigger_event(EVENT_TYPE_QUAKE, event_attributes(payload))
        self.async_write_ha_state()
