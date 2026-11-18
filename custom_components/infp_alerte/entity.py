"""Baza comuna a entitatilor."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import ATTRIBUTION, DOMAIN
from .hub import Hub


class InfpEntity(Entity):
    """Entitate legata de hub, grupata sub un singur dispozitiv de tip serviciu."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_attribution = ATTRIBUTION

    def __init__(self, hub: Hub, key: str) -> None:
        self._hub = hub
        self._attr_translation_key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.entry.entry_id)},
            name="Alerte seismice",
            manufacturer="INFP / EMSC",
            entry_type=DeviceEntryType.SERVICE,
        )
