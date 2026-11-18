"""Mentiunea de sursa ceruta de INCDFP apare pe entitati."""
from homeassistant.core import HomeAssistant

from .test_init import _entity, _setup


async def test_atribuire_pe_entitati(hass: HomeAssistant, hass_storage):
    entry = await _setup(hass)
    for key in ("event", "last_magnitude"):
        attrs = hass.states.get(_entity(hass, entry, key)).attributes
        assert "INCDFP" in attrs["attribution"] and "Alerta Cutremur" in attrs["attribution"]
