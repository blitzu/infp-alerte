"""Integrarea in Home Assistant: entitati, evenimente, deduplicare si persistenta."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.infp_alerte.const import DOMAIN
from custom_components.infp_alerte.parser import Quake
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def _quake(mag=5.3, minutes_ago=1, lat=45.6947, lon=26.5747, source="emsc") -> Quake:
    return Quake(mag, lat, lon, 141.0, datetime.now(UTC) - timedelta(minutes=minutes_ago), source, "Vrancea", "id1")


def _entity(hass: HomeAssistant, entry, key: str) -> str:
    reg = er.async_get(hass)
    ent = reg.async_get_entity_id(
        {"event": "event", "last_magnitude": "sensor", "last_distance": "sensor", "last_time": "sensor",
         "telegram_connected": "binary_sensor"}[key],
        DOMAIN,
        f"{entry.entry_id}_{key if key != 'event' else 'quake'}",
    )
    assert ent is not None, key
    return ent


async def _setup(hass: HomeAssistant, *, data=None, options=None):
    hass.config.latitude, hass.config.longitude = 44.4268, 26.1025  # centrul Bucurestiului (generic)
    entry = MockConfigEntry(domain=DOMAIN, data=data or {}, options=options or {}, unique_id="x")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_emsc_prima_citire_nu_alerteaza_apoi_da_cutremurul_nou(hass: HomeAssistant, hass_storage):
    vechi = _quake(minutes_ago=30)
    with patch("custom_components.infp_alerte.hub.fetch_emsc", AsyncMock(return_value=[vechi])) as fetch:
        entry = await _setup(hass)
        hub = entry.runtime_data
        ev = _entity(hass, entry, "event")
        # prima citire = seed: nicio alerta, senzorul fara valoare
        assert hass.states.get(ev).state == "unknown"
        assert hass.states.get(_entity(hass, entry, "last_magnitude")).state == "unknown"

        nou = _quake(mag=4.8, minutes_ago=0, lat=46.0, lon=26.8)
        fetch.return_value = [vechi, nou]
        await hub._async_poll_emsc()
        await hass.async_block_till_done()

    st = hass.states.get(ev)
    assert st.attributes["event_type"] == "cutremur"
    assert st.attributes["magnitude"] == 4.8
    assert 150 < st.attributes["distance_km"] < 220
    assert st.attributes["source"] == "emsc" and st.attributes["revised"] is False
    mag = hass.states.get(_entity(hass, entry, "last_magnitude"))
    assert mag.state == "4.8" and mag.attributes["region"] == "Vrancea"
    assert hass.states.get(_entity(hass, entry, "last_distance")).state != "unknown"


async def test_prag_de_magnitudine_si_distanta(hass: HomeAssistant, hass_storage):
    with patch("custom_components.infp_alerte.hub.fetch_emsc", AsyncMock(return_value=[])):
        entry = await _setup(hass, options={"min_magnitude": 4.0, "max_distance_km": 200, "use_emsc": True})
        hub = entry.runtime_data
        await hub._async_poll_emsc()  # seed
        await hub.async_handle_quake(_quake(mag=3.5))  # prea mic
        await hub.async_handle_quake(_quake(mag=6.0, lat=47.9, lon=21.0))  # prea departe
        await hass.async_block_till_done()
        assert hub.last is None
        await hub.async_handle_quake(_quake(mag=4.5))
        await hass.async_block_till_done()
        assert hub.last is not None and hub.last.magnitude == 4.5


async def test_cutremur_vechi_nu_alerteaza(hass: HomeAssistant, hass_storage):
    with patch("custom_components.infp_alerte.hub.fetch_emsc", AsyncMock(return_value=[])):
        entry = await _setup(hass)
        hub = entry.runtime_data
        await hub._async_poll_emsc()
        await hub.async_handle_quake(_quake(minutes_ago=90))
        assert hub.last is None


class _FakeListener:
    instances: list["_FakeListener"] = []

    def __init__(self, api_id, api_hash, session, on_quake):
        self.on_quake = on_quake
        self.connected = True
        _FakeListener.instances.append(self)

    async def async_start(self):
        pass

    async def async_stop(self):
        self.connected = False

    async def async_check_authorized(self):
        return True


async def test_telegram_primul_apoi_emsc_nu_dubleaza_iar_la_repornire_nu_realerteaza(hass: HomeAssistant, hass_storage):
    _FakeListener.instances.clear()
    emsc = AsyncMock(return_value=[])
    with (
        patch("custom_components.infp_alerte.hub.TelegramListener", _FakeListener),
        patch("custom_components.infp_alerte.hub.fetch_emsc", emsc),
    ):
        entry = await _setup(hass, data={"api_id": 1, "api_hash": "h", "session": "s"})
        hub = entry.runtime_data
        assert hass.states.get(_entity(hass, entry, "telegram_connected")).state == "on"
        await hub._async_poll_emsc()  # seed (gol)

        infp = _quake(mag=5.3, minutes_ago=0, source="infp")
        await _FakeListener.instances[0].on_quake(infp)  # +29 s: INFP prin Telegram
        await hass.async_block_till_done()
        assert hass.states.get(_entity(hass, entry, "event")).attributes["source"] == "infp"
        first_state = hass.states.get(_entity(hass, entry, "event")).state

        # EMSC publica acelasi cutremur peste cateva secunde (alte coordonate usor diferite): nu se dubleaza
        emsc_q = _quake(mag=5.3, minutes_ago=0, lat=45.6952, lon=26.5495, source="emsc")
        emsc_q.time = infp.time + timedelta(seconds=5)
        emsc.return_value = [emsc_q]
        await hub._async_poll_emsc()
        await hass.async_block_till_done()
        assert hass.states.get(_entity(hass, entry, "event")).state == first_state  # neschimbat

        # repornire: evidenta persistata, deci EMSC nu realerteaza
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        hub2 = entry.runtime_data
        await hub2._async_poll_emsc()
        await hass.async_block_till_done()
        assert hub2.last is not None and hub2.last.source == "infp"  # ultimul ramas, nealterat de EMSC


async def test_descarcare_curata(hass: HomeAssistant, hass_storage):
    with patch("custom_components.infp_alerte.hub.fetch_emsc", AsyncMock(return_value=[])):
        entry = await _setup(hass)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state.name == "NOT_LOADED"
