"""Butoane: exercitiu pe fiecare treapta si "Am vazut" (opreste alerta si readuce casa cum era)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import TIERS
from .entity import InfpEntity
from .hub import Hub


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    hub: Hub = entry.runtime_data
    entities: list[ButtonEntity] = [DrillButton(hub, tier) for tier in TIERS]
    entities.append(AcknowledgeButton(hub))
    async_add_entities(entities)


class DrillButton(InfpEntity, ButtonEntity):
    """Ruleaza treapta ca exercitiu: efecte REALE (sirena, lumini, boxe, telefoane), dar cu texte "EXERCITIU"."""

    _attr_icon = "mdi:alarm-light-outline"

    def __init__(self, hub: Hub, tier: int) -> None:
        super().__init__(hub, f"drill_tier_{tier}")
        self._tier = tier

    async def async_press(self) -> None:
        cfg = self._hub.engine.tiers.get(self._tier)
        if cfg is None or not cfg.has_actions:
            raise ServiceValidationError(
                translation_domain="infp_alerte",
                translation_key="tier_without_actions",
                translation_placeholders={"tier": str(self._tier)},
            )
        self._hub.engine.start(
            self._tier,
            {"mag": f"{cfg.min_magnitude:.1f}", "region": "TEST", "dist": "100", "depth": "10", "time": "--:--:--"},
            drill=True,
        )


class AcknowledgeButton(InfpEntity, ButtonEntity):
    """"Am vazut": opreste sirenele si boxele, readuce luminile si volumele."""

    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, hub: Hub) -> None:
        super().__init__(hub, "acknowledge")

    async def async_press(self) -> None:
        await self._hub.engine.async_acknowledge()
