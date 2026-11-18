"""Blueprint-ul de alerta pe trepte, instantiat intr-un Home Assistant de test."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.infp_alerte.const import DOMAIN
from custom_components.infp_alerte.parser import Quake
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

BP = Path(__file__).parent.parent / "blueprints/automation/infp_alerte/alerta_pe_trepte.yaml"


def _act(name):
    return [{"action": f"test.{name}", "data": {
        "tier": "{{ tier }}", "magnitude": "{{ magnitude }}", "distance": "{{ distance_km }}",
        "region": "{{ region }}", "source": "{{ source }}", "ora": "{{ quake_time }}"}}]


async def _setup(hass: HomeAssistant):
    hass.config.latitude, hass.config.longitude = 44.4268, 26.1025
    dest = Path(hass.config.path("blueprints/automation/infp_alerte"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BP, dest / "alerta_pe_trepte.yaml")
    calls = {n: async_mock_service(hass, "test", n) for n in ("t1", "t2", "t3")}
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, unique_id="x")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    event_id = er.async_get(hass).async_get_entity_id("event", DOMAIN, f"{entry.entry_id}_quake")
    assert await async_setup_component(hass, "automation", {"automation": {
        "alias": "Test alerta",
        "use_blueprint": {"path": "infp_alerte/alerta_pe_trepte.yaml", "input": {
            "quake_event": event_id,
            "tier1_actions": _act("t1"), "tier2_actions": _act("t2"), "tier3_actions": _act("t3")}}}})
    await hass.async_block_till_done()
    hub = entry.runtime_data
    await hub._async_poll_emsc()  # seed
    return entry, hub, calls


def _q(mag, lat=45.6947, lon=26.5747, minutes_ago=0, source="infp"):
    return Quake(mag, lat, lon, 141.0, datetime.now(UTC) - timedelta(minutes=minutes_ago), source, "Vrancea")


async def _fire(hass, hub, quake):
    await hub.async_handle_quake(quake)
    await hass.async_block_till_done()


async def test_treapta_2_la_cutremurul_de_azi_noapte(hass: HomeAssistant, hass_storage):
    entry, hub, calls = await _setup(hass)
    await _fire(hass, hub, _q(5.3))  # M5.3 la ~162 km, ca azi-noapte
    assert len(calls["t2"]) == 1 and not calls["t1"] and not calls["t3"]
    d = calls["t2"][0].data
    assert d["tier"] == 2 and float(d["magnitude"]) == 5.3 and d["source"] == "infp" and d["region"] == "Vrancea"
    assert 140 < float(d["distance"]) < 155 and len(d["ora"]) == 8


async def test_celelalte_trepte_si_sub_prag(hass: HomeAssistant, hass_storage):
    entry, hub, calls = await _setup(hass)
    await _fire(hass, hub, _q(4.1, lat=45.0, lon=26.9, minutes_ago=10))  # treapta 1
    await _fire(hass, hub, _q(5.9, lat=45.2, lon=26.4, minutes_ago=5))  # treapta 3 (alt cutremur, la minute distanta)
    await _fire(hass, hub, _q(3.8, lat=44.9, lon=25.5, minutes_ago=0))  # emis de integrare, sub toate pragurile
    assert [len(calls[k]) for k in ("t1", "t2", "t3")] == [1, 0, 1]


async def test_revizuire_in_sus_realerteaza_pe_treapta_mai_mare(hass: HomeAssistant, hass_storage):
    entry, hub, calls = await _setup(hass)
    await _fire(hass, hub, _q(5.2))  # INFP: treapta 2
    await _fire(hass, hub, _q(5.6, source="emsc"))  # EMSC revizuieste in sus: treapta 3
    assert len(calls["t2"]) == 1 and len(calls["t3"]) == 1


async def test_reincarcarea_nu_declanseaza(hass: HomeAssistant, hass_storage):
    entry, hub, calls = await _setup(hass)
    await _fire(hass, hub, _q(5.3))
    assert len(calls["t2"]) == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls["t2"]) == 1  # entitatea isi restaureaza ultimul eveniment, dar blueprintul il ignora


async def test_cutremur_mai_vechi_de_30_min_e_ignorat(hass: HomeAssistant, hass_storage):
    entry, hub, calls = await _setup(hass)
    await _fire(hass, hub, _q(5.3, minutes_ago=45))  # trece de filtrul de 1 h al integrarii, nu de cel de 30 min
    assert not calls["t2"]


async def test_valul_real_de_mesaje_INFP_nu_realerteaza_in_aceeasi_treapta(hass: HomeAssistant, hass_storage):
    """Secventa reala din 18 nov. 2026: 5.3 -> 5.4 (x4) -> 5.5 -> 5.6 -> 5.7 -> 5.8, cu ora/coordonate usor diferite."""
    entry, hub, calls = await _setup(hass)
    seq = [(5.3, 45.6947, 26.5747, 0.0), (5.4, 45.6947, 26.5747, 0.0), (5.4, 45.6947, 26.5747, 0.0),
           (5.5, 45.7036, 26.5555, -0.4), (5.6, 45.7036, 26.5555, -0.4), (5.6, 45.7058, 26.5523, -0.3),
           (5.7, 45.7145, 26.5653, -0.5), (5.7, 45.7102, 26.5588, -0.4), (5.8, 45.7279, 26.5076, 1.4)]
    base = datetime.now(UTC) - timedelta(seconds=20)
    for mag, lat, lon, off in seq:
        q = Quake(mag, lat, lon, 141.0, base + timedelta(seconds=off), "infp", "Vrancea")
        await _fire(hass, hub, q)
    # 5.3 -> treapta 2 (o data); 5.5 -> treapta 3 (o data); 5.7 (revizuire in aceeasi treapta 3) NU mai ruleaza
    assert len(calls["t2"]) == 1 and len(calls["t3"]) == 1 and not calls["t1"]
    assert float(calls["t2"][0].data["magnitude"]) == 5.3 and float(calls["t3"][0].data["magnitude"]) == 5.5
