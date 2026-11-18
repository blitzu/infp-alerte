"""Fluxul de configurare: EMSC simplu, Telegram cu cod, Telegram cu parola de doi pasi, erori."""
from types import SimpleNamespace
from unittest.mock import patch

from telethon import errors

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


async def test_optiuni(hass: HomeAssistant):
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"next_step_id": "emsc_only"})
    entry = res["result"]
    await hass.async_block_till_done()
    opt = await hass.config_entries.options.async_init(entry.entry_id)
    assert opt["type"] is FlowResultType.FORM
    opt = await hass.config_entries.options.async_configure(
        opt["flow_id"], {"min_magnitude": 4.0, "max_distance_km": 300, "use_emsc": False}
    )
    assert opt["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"min_magnitude": 4.0, "max_distance_km": 300, "use_emsc": False}


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
