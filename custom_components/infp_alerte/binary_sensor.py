"""Starea conexiunii la Telegram (ca sa stii cand alerta rapida INFP nu mai merge)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_ALERT, SIGNAL_STATUS
from .entity import InfpEntity
from .hub import Hub


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    hub: Hub = entry.runtime_data
    entities: list[BinarySensorEntity] = [AlertActive(hub)]
    if hub.has_telegram:
        entities.append(TelegramConnected(hub))
    async_add_entities(entities)


class TelegramConnected(InfpEntity, BinarySensorEntity):
    """Pornit cat timp ascultatorul Telegram e conectat."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, hub: Hub) -> None:
        super().__init__(hub, "telegram_connected")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_STATUS, self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._hub.telegram_connected


class AlertActive(InfpEntity, BinarySensorEntity):
    """Pornit cat timp o alerta (sirena, lumini, voce) este in curs."""

    _attr_icon = "mdi:alarm-light"

    def __init__(self, hub: Hub) -> None:
        super().__init__(hub, "alert_active")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_ALERT, self._refresh_alert))

    @callback
    def _refresh_alert(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._hub.engine.active

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {"tier": self._hub.engine.active_tier}
