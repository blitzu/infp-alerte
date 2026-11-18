"""Fluxul de configurare: EMSC simplu, Telegram cu cod, Telegram cu parola de doi pasi, erori."""
from types import SimpleNamespace
from unittest.mock import patch

from telethon import errors

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.infp_alerte.const import DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


class FakeClient:
    """Inlocuieste TelegramClient: controlat de atribute de clasa."""

    need_password = False
    code_error: Exception | None = None
    send_error: Exception | None = None
    password_error: Exception | None = None
    disconnected = 0

    def __init__(self, session, api_id, api_hash, **kwargs):
        self.session = SimpleNamespace(save=lambda: "SESIUNE-TEST")

    async def connect(self):
        pass

    async def disconnect(self):
        FakeClient.disconnected += 1

    async def send_code_request(self, phone):
        if FakeClient.send_error:
            raise FakeClient.send_error
        return SimpleNamespace(phone_code_hash="HASH")

    async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
        if password is not None:
            if FakeClient.password_error:
                raise FakeClient.password_error
            return None
        if FakeClient.code_error:
            raise FakeClient.code_error
        if FakeClient.need_password:
            raise errors.SessionPasswordNeededError(request=None)
        return None

    async def get_me(self):
        return SimpleNamespace(id=777, first_name="Cont separat")


def _reset():
    FakeClient.need_password = False
    FakeClient.code_error = FakeClient.send_error = FakeClient.password_error = None
    FakeClient.disconnected = 0


async def _start_telegram(hass):
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert res["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(res["flow_id"], {"next_step_id": "telegram"})


CREDS = {"api_id": 12345, "api_hash": "a" * 32, "phone": "+40700000000"}


async def test_doar_emsc(hass: HomeAssistant):
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"next_step_id": "emsc_only"})
    assert res["type"] is FlowResultType.CREATE_ENTRY
    assert res["data"] == {} and "EMSC" in res["title"]


async def test_telegram_cu_cod(hass: HomeAssistant):
    _reset()
    with patch("custom_components.infp_alerte.config_flow.TelegramClient", FakeClient):
        res = await _start_telegram(hass)
        assert res["step_id"] == "telegram"
        res = await hass.config_entries.flow.async_configure(res["flow_id"], CREDS)
        assert res["step_id"] == "code"
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"code": "12345"})
    assert res["type"] is FlowResultType.CREATE_ENTRY
    assert res["data"] == {"api_id": 12345, "api_hash": "a" * 32, "session": "SESIUNE-TEST"}
    assert res["result"].unique_id == "777"
    assert FakeClient.disconnected >= 1  # clientul de autentificare s-a inchis


async def test_telegram_cu_parola_de_doi_pasi(hass: HomeAssistant):
    _reset()
    FakeClient.need_password = True
    with patch("custom_components.infp_alerte.config_flow.TelegramClient", FakeClient):
        res = await _start_telegram(hass)
        res = await hass.config_entries.flow.async_configure(res["flow_id"], CREDS)
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"code": "12345"})
        assert res["step_id"] == "password"
        FakeClient.password_error = errors.PasswordHashInvalidError(request=None)
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"password": "gresita"})
        assert res["type"] is FlowResultType.FORM and res["errors"] == {"base": "invalid_password"}
        FakeClient.password_error = None
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"password": "buna"})
    assert res["type"] is FlowResultType.CREATE_ENTRY


async def test_cod_gresit_ramane_pe_pas(hass: HomeAssistant):
    _reset()
    FakeClient.code_error = errors.PhoneCodeInvalidError(request=None)
    with patch("custom_components.infp_alerte.config_flow.TelegramClient", FakeClient):
        res = await _start_telegram(hass)
        res = await hass.config_entries.flow.async_configure(res["flow_id"], CREDS)
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"code": "00000"})
        assert res["type"] is FlowResultType.FORM and res["step_id"] == "code"
        assert res["errors"] == {"base": "invalid_code"}
        FakeClient.code_error = None
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"code": "12345"})
    assert res["type"] is FlowResultType.CREATE_ENTRY


async def test_credentiale_invalide_si_retea(hass: HomeAssistant):
    _reset()
    with patch("custom_components.infp_alerte.config_flow.TelegramClient", FakeClient):
        FakeClient.send_error = errors.ApiIdInvalidError(request=None)
        res = await _start_telegram(hass)
        res = await hass.config_entries.flow.async_configure(res["flow_id"], CREDS)
        assert res["step_id"] == "telegram" and res["errors"] == {"base": "invalid_api"}
        FakeClient.send_error = ConnectionError("fara retea")
        res = await hass.config_entries.flow.async_configure(res["flow_id"], CREDS)
        assert res["errors"] == {"base": "cannot_connect"}


async def test_a_doua_configurare_e_refuzata(hass: HomeAssistant):
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(res["flow_id"], {"next_step_id": "emsc_only"})
    res2 = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert res2["type"] is FlowResultType.ABORT and res2["reason"] == "single_instance_allowed"


async def _options_entry(hass: HomeAssistant):
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"next_step_id": "emsc_only"})
    await hass.async_block_till_done()
    return res["result"]


async def test_optiuni_setari_generale_prin_meniu(hass: HomeAssistant):
    entry = await _options_entry(hass)
    opt = await hass.config_entries.options.async_init(entry.entry_id)
    assert opt["type"] is FlowResultType.MENU
    assert set(opt["menu_options"]) == {"general", "tier_1", "tier_2", "tier_3", "finish"}
    opt = await hass.config_entries.options.async_configure(opt["flow_id"], {"next_step_id": "general"})
    assert opt["type"] is FlowResultType.FORM and opt["step_id"] == "general"
    opt = await hass.config_entries.options.async_configure(
        opt["flow_id"], {"min_magnitude": 4.0, "max_distance_km": 300, "use_emsc": False}
    )
    assert opt["type"] is FlowResultType.MENU  # inapoi la meniu
    opt = await hass.config_entries.options.async_configure(opt["flow_id"], {"next_step_id": "finish"})
    assert opt["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["min_magnitude"] == 4.0 and entry.options["max_distance_km"] == 300 and entry.options["use_emsc"] is False


TIER2_FORM = {
    "conditions": {"min_magnitude": 4.5, "max_distance_km": 350},
    "notify": {"services": ["mobile_app_telefon_a"], "critical": True, "sound": "alarma.wav"},
    "siren": {"entities": ["siren.hol"], "seconds": 30},
    "lights": {"entities": ["light.hol"], "all": False, "brightness": 90},
    "speakers": {"entities": ["media_player.boxa"], "tts_entity": "tts.ro", "message": "Cutremur {magnitude}", "volume": 0.7},
    "repeat": False,
}


async def test_optiuni_treapta_salveaza_alegerile_din_formular(hass: HomeAssistant):
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_mock_service(hass, "notify", "mobile_app_telefon_a")
    entry = await _options_entry(hass)
    opt = await hass.config_entries.options.async_init(entry.entry_id)
    opt = await hass.config_entries.options.async_configure(opt["flow_id"], {"next_step_id": "tier_2"})
    assert opt["type"] is FlowResultType.FORM and opt["step_id"] == "tier_2"
    opt = await hass.config_entries.options.async_configure(opt["flow_id"], TIER2_FORM)
    assert opt["type"] is FlowResultType.MENU
    opt = await hass.config_entries.options.async_configure(opt["flow_id"], {"next_step_id": "finish"})
    assert opt["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["tiers"]["2"]["notify"]["services"] == ["mobile_app_telefon_a"]
    assert entry.options["tiers"]["2"]["siren"] == {"entities": ["siren.hol"], "seconds": 30}


async def test_optiuni_treapta_cere_motor_de_voce_daca_sunt_boxe(hass: HomeAssistant):
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_mock_service(hass, "notify", "mobile_app_telefon_a")
    entry = await _options_entry(hass)
    opt = await hass.config_entries.options.async_init(entry.entry_id)
    opt = await hass.config_entries.options.async_configure(opt["flow_id"], {"next_step_id": "tier_2"})
    bad = {**TIER2_FORM, "speakers": {"entities": ["media_player.boxa"], "volume": 0.7}}
    opt = await hass.config_entries.options.async_configure(opt["flow_id"], bad)
    assert opt["type"] is FlowResultType.FORM and opt["errors"] == {"base": "tts_required"}


async def test_lista_de_notificari_foloseste_numele_telefoanelor(hass: HomeAssistant):
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.infp_alerte.config_flow import notify_options

    async_mock_service(hass, "notify", "mobile_app_iphone_ana")
    async_mock_service(hass, "notify", "alt_serviciu")
    MockConfigEntry(domain="mobile_app", data={"device_name": "iPhone Ana"}).add_to_hass(hass)
    opts = {o["value"]: o["label"] for o in notify_options(hass, ["mobile_app_dispozitiv_vechi"])}
    assert opts["mobile_app_iphone_ana"] == "📱 iPhone Ana"
    assert "alt_serviciu" in opts and "mobile_app_dispozitiv_vechi" in opts  # alegerea veche se pastreaza
    assert "send_message" not in opts


async def test_cu_credentiale_implicite_cere_doar_telefonul(hass: HomeAssistant):
    _reset()
    with (
        patch("custom_components.infp_alerte.config_flow.TelegramClient", FakeClient),
        patch("custom_components.infp_alerte.config_flow.load_default_api", return_value=(4242, "d" * 32)),
    ):
        res = await _start_telegram(hass)
        assert res["step_id"] == "phone"  # fara api_id/api_hash
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"phone": "+40700000000"})
        assert res["step_id"] == "code"
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"code": "12345"})
    assert res["type"] is FlowResultType.CREATE_ENTRY
    assert res["data"]["api_id"] == 4242 and res["data"]["api_hash"] == "d" * 32  # intrarea ramane independenta
