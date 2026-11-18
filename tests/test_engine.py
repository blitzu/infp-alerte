"""Motorul de alerta pe trepte (configurat din optiuni, fara scripturi)."""
import asyncio
from datetime import UTC, datetime, timedelta

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.infp_alerte import const
from custom_components.infp_alerte.alerts import TierConfig
from custom_components.infp_alerte.const import ACK_ACTION, DOMAIN
from custom_components.infp_alerte.parser import Quake
from homeassistant.core import HomeAssistant

import pytest


def tier2_options():
    return {
        "conditions": {"min_magnitude": 4.5, "max_distance_km": 350},
        "notify": {"services": ["mobile_app_telefon_a", "mobile_app_telefon_b"], "critical": True, "sound": "alarma.wav"},
        "siren": {"entities": ["siren.hol"], "seconds": 30},
        "lights": {"entities": ["light.hol", "light.dormitor"], "brightness": 90},
        "speakers": {"entities": ["media_player.boxa"], "tts_entity": "tts.ro", "volume": 0.7, "message": "Cutremur {magnitude} in {region}"},
    }


def tier1_options():
    return {"conditions": {"min_magnitude": 4.0, "max_distance_km": 350}, "notify": {"services": ["mobile_app_telefon_a"]}}


def tier3_options():
    return {"conditions": {"min_magnitude": 5.5, "max_distance_km": 450},
            "notify": {"services": ["mobile_app_telefon_a"], "critical": True},
            "siren": {"entities": ["siren.hol"]}, "repeat": True}


@pytest.fixture(autouse=True)
def fast_times(monkeypatch):
    monkeypatch.setattr(const, "CYCLE_PAUSE", 0.01)
    monkeypatch.setattr(const, "RESTORE_TIMEOUT", 0.2)


async def _setup(hass: HomeAssistant, tiers):
    hass.config.latitude, hass.config.longitude = 44.4268, 26.1025
    hass.config.language = "ro"
    calls = {}
    for dom, svc in [("notify", "mobile_app_telefon_a"), ("notify", "mobile_app_telefon_b"), ("siren", "turn_on"),
                     ("siren", "turn_off"), ("light", "turn_on"), ("scene", "create"), ("scene", "turn_on"),
                     ("tts", "speak"), ("media_player", "volume_set"), ("media_player", "media_stop")]:
        calls[f"{dom}.{svc}"] = async_mock_service(hass, dom, svc)
    hass.states.async_set("media_player.boxa", "idle", {"volume_level": 0.3})
    hass.states.async_set("scene.infp_alerte_before", "unknown")
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={"tiers": tiers}, unique_id="x")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, entry.runtime_data, calls


def _q(mag, source="infp", lat=45.6947, lon=26.5747, minutes_ago=0):
    return Quake(mag, lat, lon, 141.0, datetime.now(UTC) - timedelta(minutes=minutes_ago), source, "Vrancea")


def test_alegerea_treptei():
    cfgs = {1: TierConfig.from_options(1, tier1_options()), 2: TierConfig.from_options(2, tier2_options()),
            3: TierConfig.from_options(3, tier3_options())}
    from custom_components.infp_alerte.alerts import AlertEngine

    eng = AlertEngine.__new__(AlertEngine)
    eng.tiers = cfgs
    assert eng.tier_for(5.3, 160) == 2 and eng.tier_for(5.6, 160) == 3 and eng.tier_for(4.1, 200) == 1
    assert eng.tier_for(3.9, 50) == 0 and eng.tier_for(6.0, 800) == 0
    eng.tiers[3] = TierConfig.from_options(3, {"conditions": {"min_magnitude": 5.5, "max_distance_km": 450}})  # fara actiuni
    assert eng.tier_for(5.9, 160) == 2  # treapta 3 nu are actiuni: cade pe 2


async def test_treapta_2_complet_si_readucerea_la_am_vazut(hass: HomeAssistant, hass_storage, monkeypatch):
    monkeypatch.setattr(const, "RESTORE_TIMEOUT", 30)  # asteapta confirmarea
    entry, hub, c = await _setup(hass, {"2": tier2_options()})
    await hub.async_handle_quake(_q(5.3))
    await asyncio.sleep(0.1)
    # notificari critice cu sunetul ales, la ambele telefoane
    for k in ("notify.mobile_app_telefon_a", "notify.mobile_app_telefon_b"):
        assert len(c[k]) == 1
        d = c[k][0].data
        assert d["title"].startswith("Cutremur M5.3") and "162" not in d["title"]
        assert d["data"]["push"]["interruption-level"] == "critical"
        assert d["data"]["push"]["sound"] == {"name": "alarma.wav", "critical": 1, "volume": 1}
        assert d["data"]["channel"] == "alarm_stream" and d["data"]["ttl"] == 0
        assert d["data"]["actions"][0]["action"] == ACK_ACTION
    # instantaneu luminilor, apoi lumini, sirena si voce
    assert c["scene.create"][0].data["snapshot_entities"] == ["light.hol", "light.dormitor"]
    assert c["light.turn_on"][0].data["brightness_pct"] == 90
    assert c["siren.turn_on"][0].data["duration"] == 30
    assert c["media_player.volume_set"][0].data["volume_level"] == 0.7
    assert c["tts.speak"][0].data["message"] == "Cutremur 5.3 in Vrancea"
    assert hub.engine.active and hub.engine.active_tier == 2
    # "Am vazut": opreste sirena si boxa, readuce luminile si volumul salvat (0.3)
    await hub.engine.async_acknowledge()
    await hass.async_block_till_done()
    assert c["siren.turn_off"] and c["media_player.media_stop"]
    assert c["scene.turn_on"][0].data["entity_id"] == "scene.infp_alerte_before"
    assert c["media_player.volume_set"][-1].data["volume_level"] == 0.3
    assert not hub.engine.active


async def test_readuce_singura_dupa_expirarea_timpului(hass: HomeAssistant, hass_storage):
    entry, hub, c = await _setup(hass, {"2": tier2_options()})
    await hub.async_handle_quake(_q(5.3))
    await hass.async_block_till_done()  # RESTORE_TIMEOUT = 0.2 s
    assert c["scene.turn_on"] and not hub.engine.active


async def test_revizuire_in_aceeasi_treapta_nu_realerteaza_dar_escaladarea_da(hass: HomeAssistant, hass_storage):
    entry, hub, c = await _setup(hass, {"2": tier2_options(), "3": tier3_options()})
    await hub.async_handle_quake(_q(5.3))      # treapta 2
    await asyncio.sleep(0.05)                  # in realitate trec secunde intre mesaje
    await hub.async_handle_quake(_q(5.5))      # revizuire -> treapta 3 (escaladare)
    await asyncio.sleep(0.05)
    await hub.async_handle_quake(_q(5.7))      # revizuire in aceeasi treapta 3: nimic
    await hass.async_block_till_done()
    assert len(c["notify.mobile_app_telefon_a"]) == 2   # o data la 2, o data la 3
    assert len(c["notify.mobile_app_telefon_b"]) == 1   # treapta 3 nu notifica telefonul B


async def test_treapta_3_repeta_pana_la_confirmare(hass: HomeAssistant, hass_storage, monkeypatch):
    monkeypatch.setattr(const, "RESTORE_TIMEOUT", 30)
    entry, hub, c = await _setup(hass, {"3": tier3_options()})
    await hub.async_handle_quake(_q(5.8))
    await asyncio.sleep(0.2)
    assert len(c["siren.turn_on"]) >= 3  # repeta (pauza de 0.01 s in test)
    await hub.engine.async_acknowledge()
    n = len(c["siren.turn_on"])
    await asyncio.sleep(0.1)
    assert len(c["siren.turn_on"]) == n  # nu mai suna dupa confirmare
    await hass.async_block_till_done()


async def test_simularea_e_exercitiu_cu_texte_marcate(hass: HomeAssistant, hass_storage):
    entry, hub, c = await _setup(hass, {"2": tier2_options()})
    await hass.services.async_call(DOMAIN, "simulate_quake", {"magnitude": 4.8, "distance_km": 100}, blocking=True)
    await hass.async_block_till_done()
    d = c["notify.mobile_app_telefon_a"][0].data
    assert d["title"].startswith("EXERCIȚIU – ") and "nu e un cutremur real" in d["message"]
    assert c["tts.speak"][0].data["message"].startswith("Exercițiu, nu este un cutremur real.")


async def test_toate_luminile_si_serviciu_lipsa_nu_opreste_restul(hass: HomeAssistant, hass_storage):
    opts = {"conditions": {"min_magnitude": 4.5, "max_distance_km": 350},
            "notify": {"services": ["mobile_app_inexistent"]}, "lights": {"all": True, "brightness": 80}}
    hass.states.async_set("light.a", "on")
    hass.states.async_set("light.b", "unavailable")
    entry, hub, c = await _setup(hass, {"2": opts})
    await hub.async_handle_quake(_q(5.0))
    await hass.async_block_till_done()
    assert c["scene.create"][0].data["snapshot_entities"] == ["light.a"]  # fara cele indisponibile
    assert c["light.turn_on"][0].data["brightness_pct"] == 80  # notificarea esuata nu a oprit luminile


async def test_butonul_din_notificare_confirma(hass: HomeAssistant, hass_storage, monkeypatch):
    monkeypatch.setattr(const, "RESTORE_TIMEOUT", 30)
    entry, hub, c = await _setup(hass, {"2": tier2_options()})
    await hub.async_handle_quake(_q(5.3))
    await asyncio.sleep(0.1)
    hass.bus.async_fire("mobile_app_notification_action", {"action": ACK_ACTION})
    await hass.async_block_till_done()
    assert c["siren.turn_off"] and not hub.engine.active


async def test_fara_actiuni_configurate_nu_face_nimic(hass: HomeAssistant, hass_storage):
    entry, hub, c = await _setup(hass, {})
    await hub.async_handle_quake(_q(6.0))
    await hass.async_block_till_done()
    assert all(not v for v in c.values())


async def test_doua_cutremure_in_aceeasi_clipa_treapta_mare_o_acopera_pe_cea_mica(hass: HomeAssistant, hass_storage):
    entry, hub, c = await _setup(hass, {"2": tier2_options(), "3": tier3_options()})
    await hub.async_handle_quake(_q(5.3))
    await hub.async_handle_quake(_q(5.5))  # imediat: treapta 3 inlocuieste treapta 2 inainte sa porneasca
    await hass.async_block_till_done()
    assert len(c["notify.mobile_app_telefon_a"]) == 1 and "M5.5" in c["notify.mobile_app_telefon_a"][0].data["title"]


async def test_notificare_catre_entitati_notify_ex_telegram(hass: HomeAssistant, hass_storage):
    opts = {"conditions": {"min_magnitude": 4.5, "max_distance_km": 350}, "notify": {"entities": ["notify.bot_telegram"]}}
    entry, hub, c = await _setup(hass, {"2": opts})
    send = async_mock_service(hass, "notify", "send_message")
    await hub.async_handle_quake(_q(5.0))
    await hass.async_block_till_done()
    assert len(send) == 1 and send[0].data["entity_id"] == ["notify.bot_telegram"]
    assert send[0].data["title"].startswith("Cutremur M5.0")


async def test_treapta_doar_cu_notificari_se_incheie_imediat(hass: HomeAssistant, hass_storage, monkeypatch):
    monkeypatch.setattr(const, "RESTORE_TIMEOUT", 30)  # daca ar astepta confirmare, testul ar atarna 30 s
    entry, hub, c = await _setup(hass, {"1": tier1_options()})
    await hub.async_handle_quake(_q(4.3))
    await asyncio.wait_for(hass.async_block_till_done(), 2)
    assert len(c["notify.mobile_app_telefon_a"]) == 1 and not hub.engine.active


async def test_o_lumina_lenta_nu_intarzie_sirena_si_vocea(hass: HomeAssistant, hass_storage, monkeypatch):
    """Regresie reala (18 nov. 2026): light.turn_on blocant la ~30 de lumini a tinut sirena si vocea >40 s."""
    monkeypatch.setattr(const, "RESTORE_TIMEOUT", 30)
    entry, hub, c = await _setup(hass, {"2": tier2_options()})

    async def slow_light(call):
        await asyncio.sleep(10)  # o lumina care nu raspunde

    hass.services.async_register("light", "turn_on", slow_light)
    await hub.async_handle_quake(_q(5.3))
    await asyncio.sleep(0.3)
    assert c["siren.turn_on"], "sirena nu trebuie sa astepte luminile"
    assert c["tts.speak"], "vocea nu trebuie sa astepte luminile"
    assert c["notify.mobile_app_telefon_a"], "nici notificarile"
    await hub.engine.async_acknowledge()
    await hass.async_block_till_done()


async def test_telegram_primeste_mesaj_cu_buton_si_butonul_opreste_alerta(hass: HomeAssistant, hass_storage, monkeypatch):
    from homeassistant.helpers import entity_registry as er

    from custom_components.infp_alerte.const import ACK_TELEGRAM

    monkeypatch.setattr(const, "RESTORE_TIMEOUT", 30)
    bot = MockConfigEntry(domain="telegram_bot")
    bot.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "notify", "telegram_bot", "111_222", config_entry=bot, suggested_object_id="telegram_bot_111_222"
    )
    opts = {**tier2_options(), "notify": {"entities": ["notify.telegram_bot_111_222"]}}
    entry, hub, c = await _setup(hass, {"2": opts})
    send = async_mock_service(hass, "telegram_bot", "send_message")
    answer = async_mock_service(hass, "telegram_bot", "answer_callback_query")
    edit = async_mock_service(hass, "telegram_bot", "edit_replymarkup")
    await hub.async_handle_quake(_q(5.3))
    await asyncio.sleep(0.1)
    assert len(send) == 1
    d = send[0].data
    assert d["config_entry_id"] == bot.entry_id and d["chat_id"] == 222
    assert d["inline_keyboard"] == [f"Am văzut:{ACK_TELEGRAM}"]
    hass.bus.async_fire("telegram_callback", {"data": ACK_TELEGRAM, "id": "cb1", "chat_id": 222, "message": {"message_id": 9}})
    await hass.async_block_till_done()
    assert c["siren.turn_off"] and not hub.engine.active
    assert answer[0].data["callback_query_id"] == "cb1" and edit[0].data["message_id"] == 9 and edit[0].data["inline_keyboard"] == []


async def test_alte_callback_uri_telegram_sunt_ignorate(hass: HomeAssistant, hass_storage, monkeypatch):
    monkeypatch.setattr(const, "RESTORE_TIMEOUT", 30)
    entry, hub, c = await _setup(hass, {"2": tier2_options()})
    await hub.async_handle_quake(_q(5.3))
    await asyncio.sleep(0.1)
    hass.bus.async_fire("telegram_callback", {"data": "/dezarmeaza_alarmo", "id": "x", "chat_id": 1})
    await asyncio.sleep(0.1)
    assert hub.engine.active and not c["siren.turn_off"]
    await hub.engine.async_acknowledge()
    await hass.async_block_till_done()
