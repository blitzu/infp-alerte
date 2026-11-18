"""Serviciul de simulare: end-to-end prin blueprint, fara sa astepte un cutremur real."""
from custom_components.infp_alerte.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .test_blueprint import _setup

import pytest


async def test_simulare_declanseaza_treapta_potrivita(hass: HomeAssistant, hass_storage):
    entry, hub, calls = await _setup(hass)
    await hass.services.async_call(DOMAIN, "simulate_quake", {"magnitude": 4.2, "distance_km": 120}, blocking=True)
    await hass.async_block_till_done()
    assert len(calls["t1"]) == 1 and not calls["t2"] and not calls["t3"]
    d = calls["t1"][0].data
    assert d["source"] == "test" and 115 < float(d["distance"]) < 125


async def test_simulare_ocoleste_pragul_si_dedupe(hass: HomeAssistant, hass_storage):
    entry, hub, calls = await _setup(hass)
    for _ in range(2):  # de doua ori la rand: ambele ajung (nu e deduplicat)
        await hass.services.async_call(DOMAIN, "simulate_quake", {"magnitude": 5.8, "distance_km": 80}, blocking=True)
        await hass.async_block_till_done()
    assert len(calls["t3"]) == 2


async def test_simulare_fara_integrare_incarcata_da_eroare(hass: HomeAssistant):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "simulate_quake", {"magnitude": 4}, blocking=True)
