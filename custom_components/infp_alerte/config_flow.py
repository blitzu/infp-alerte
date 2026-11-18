"""Configurare din interfata: autentificare Telegram cu contul propriu al utilizatorului (sau doar EMSC)."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import logging
from typing import Any

from telethon import TelegramClient, errors
from telethon.sessions import StringSession
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .defaults import load_default_api
from .const import (
    CONF_API_HASH,
    CONF_API_ID,
    CONF_CODE,
    CONF_MAX_DISTANCE,
    CONF_MIN_MAGNITUDE,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_SESSION,
    CONF_TIERS,
    CONF_USE_EMSC,
    DEFAULT_MAX_DISTANCE,
    DEFAULT_MIN_MAGNITUDE,
    DEFAULT_USE_EMSC,
    DEFAULT_BRIGHTNESS,
    DEFAULT_SIREN_SECONDS,
    DEFAULT_SPEAKER_VOLUME,
    DEFAULT_TTS_MESSAGE_EN,
    DEFAULT_TTS_MESSAGE_RO,
    DOMAIN,
    TIER_DEFAULTS,
    TIERS,
)

_LOGGER = logging.getLogger(__name__)

_ERRORS: tuple[tuple[type[Exception], str], ...] = (
    (errors.ApiIdInvalidError, "invalid_api"),
    (errors.PhoneNumberInvalidError, "invalid_phone"),
    (errors.PhoneNumberBannedError, "invalid_phone"),
    (errors.PhoneCodeInvalidError, "invalid_code"),
    (errors.PhoneCodeExpiredError, "code_expired"),
    (errors.PasswordHashInvalidError, "invalid_password"),
    (errors.FloodWaitError, "flood"),
    (errors.RPCError, "unknown"),
    (OSError, "cannot_connect"),
    (TimeoutError, "cannot_connect"),
)


def _error_key(err: Exception) -> str:
    for exc_type, key in _ERRORS:
        if isinstance(err, exc_type):
            return key
    return "unknown"


class InfpAlerteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Autentificare in pasi: api_id/api_hash + telefon -> cod -> (parola de doi pasi)."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: TelegramClient | None = None
        self._api_id: int | None = None
        self._api_hash: str | None = None
        self._phone: str | None = None
        self._code_hash: str | None = None
        self._reauth_entry: ConfigEntry | None = None

    @callback
    def async_remove(self) -> None:
        """Flux abandonat: inchid clientul de autentificare (apelat de HA, sincron)."""
        client, self._client = self._client, None
        if client is not None:
            self.hass.async_create_task(client.disconnect())

    async def _async_disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> InfpOptionsFlow:
        return InfpOptionsFlow()

    # ---- alegerea modului ---------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["telegram", "emsc_only"])

    async def async_step_emsc_only(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Doar EMSC: fara cont, fara autentificare (mai lent decat INFP, dar fara pasi)."""
        await self.async_set_unique_id("emsc_only")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Alerte seismice (EMSC)", data={})

    # ---- Telegram: pasul 1 ---------------------------------------------------
    async def _async_send_code(self) -> str | None:
        """Trimite codul de verificare. Intoarce cheia erorii sau None la succes."""
        assert self._api_id and self._api_hash and self._phone
        try:
            await self._async_disconnect()
            self._client = TelegramClient(StringSession(), self._api_id, self._api_hash)
            await self._client.connect()
            sent = await self._client.send_code_request(self._phone)
            self._code_hash = sent.phone_code_hash
        except Exception as err:  # noqa: BLE001 - se transforma in mesaj pentru utilizator
            key = _error_key(err)
            if key == "unknown":
                _LOGGER.exception("Eroare neasteptata la trimiterea codului Telegram")
            await self._async_disconnect()
            return key
        return None

    async def async_step_telegram(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Cu credentiale implicite se cere doar telefonul; altfel si api_id/api_hash."""
        default = load_default_api()
        errors_: dict[str, str] = {}
        if default is not None and self._reauth_entry is None:
            self._api_id, self._api_hash = default
            return await self.async_step_phone()
        if user_input is not None:
            self._api_id = int(user_input[CONF_API_ID])
            self._api_hash = user_input[CONF_API_HASH].strip()
            self._phone = user_input[CONF_PHONE].strip()
            if (key := await self._async_send_code()) is None:
                return await self.async_step_code()
            errors_["base"] = key

        defaults = {}
        if self._reauth_entry is not None:
            defaults = {CONF_API_ID: self._reauth_entry.data.get(CONF_API_ID)}
        schema = vol.Schema(
            {
                vol.Required(CONF_API_ID, default=defaults.get(CONF_API_ID, vol.UNDEFINED)): vol.Coerce(int),
                vol.Required(CONF_API_HASH): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_PHONE): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEL)
                ),
            }
        )
        return self.async_show_form(step_id="telegram", data_schema=schema, errors=errors_)

    async def async_step_phone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Doar numarul de telefon (credentialele aplicatiei sunt cele implicite)."""
        errors_: dict[str, str] = {}
        if user_input is not None:
            self._phone = user_input[CONF_PHONE].strip()
            if (key := await self._async_send_code()) is None:
                return await self.async_step_code()
            errors_["base"] = key
        schema = vol.Schema(
            {
                vol.Required(CONF_PHONE): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEL)
                )
            }
        )
        return self.async_show_form(step_id="phone", data_schema=schema, errors=errors_)

    # ---- pasul 2: codul primit in Telegram ----------------------------------
    async def async_step_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors_: dict[str, str] = {}
        assert self._client is not None and self._phone and self._code_hash
        if user_input is not None:
            try:
                await self._client.sign_in(
                    phone=self._phone, code=user_input[CONF_CODE].strip(), phone_code_hash=self._code_hash
                )
            except errors.SessionPasswordNeededError:
                return await self.async_step_password()
            except Exception as err:  # noqa: BLE001
                errors_["base"] = _error_key(err)
                if errors_["base"] == "unknown":
                    _LOGGER.exception("Eroare neasteptata la verificarea codului Telegram")
                if errors_["base"] == "code_expired":
                    await self._async_disconnect()
                    return await self.async_step_telegram()
            else:
                return await self._async_finish()
        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            errors=errors_,
        )

    # ---- pasul 3 (doar daca exista): parola de doi pasi -------------------------
    async def async_step_password(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors_: dict[str, str] = {}
        assert self._client is not None
        if user_input is not None:
            try:
                await self._client.sign_in(password=user_input[CONF_PASSWORD])
            except Exception as err:  # noqa: BLE001
                errors_["base"] = _error_key(err)
                if errors_["base"] == "unknown":
                    _LOGGER.exception("Eroare neasteptata la parola de doi pasi")
            else:
                return await self._async_finish()
        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors_,
        )

    async def _async_finish(self) -> ConfigFlowResult:
        assert self._client is not None and self._api_id and self._api_hash
        me = await self._client.get_me()
        session = self._client.session.save()
        await self._async_disconnect()
        await self.async_set_unique_id(str(me.id))
        data = {CONF_API_ID: self._api_id, CONF_API_HASH: self._api_hash, CONF_SESSION: session}
        if self._reauth_entry is not None:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._reauth_entry, data=data)
        self._abort_if_unique_id_configured()
        title = f"Alerte seismice INFP ({me.first_name or me.id})"
        return self.async_create_entry(title=title, data=data)

    # ---- reautentificare ----------------------------------------------------
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_telegram()


def notify_options(hass: HomeAssistant, selected: list[str]) -> list[selector.SelectOptionDict]:
    """Telefoanele (aplicatia Home Assistant) si alte servicii de notificare, cu nume prietenoase unde se poate."""
    services = set(hass.services.async_services_for_domain("notify")) - {"send_message", "persistent_notification", "notify"}
    services |= set(selected)  # pastreaza alegerile existente chiar daca serviciul lipseste acum
    names: dict[str, str] = {}
    for entry in hass.config_entries.async_entries("mobile_app"):
        device = entry.data.get("device_name")
        if device:
            names[f"mobile_app_{slugify(device)}"] = f"📱 {device}"
    return [
        selector.SelectOptionDict(value=svc, label=names.get(svc, svc))
        for svc in sorted(services, key=lambda x: names.get(x, x).lower())
    ]


class InfpOptionsFlow(OptionsFlowWithReload):
    """Setari generale si, pentru fiecare treapta de alerta, ce se intampla (alese din liste, fara cod)."""

    def __init__(self) -> None:
        self._opts: dict[str, Any] | None = None

    def _options(self) -> dict[str, Any]:
        if self._opts is None:
            self._opts = deepcopy(dict(self.config_entry.options))
        return self._opts

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._options()
        return self.async_show_menu(
            step_id="init", menu_options=["general", "tier_1", "tier_2", "tier_3", "finish"]
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(data=self._options())

    # ---- setari generale ---------------------------------------------------
    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self._options()
        if user_input is not None:
            opts.update(user_input)
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MIN_MAGNITUDE, default=opts.get(CONF_MIN_MAGNITUDE, DEFAULT_MIN_MAGNITUDE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1.0, max=8.0, step=0.1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_MAX_DISTANCE, default=opts.get(CONF_MAX_DISTANCE, DEFAULT_MAX_DISTANCE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20, max=3000, step=10, unit_of_measurement="km", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_USE_EMSC, default=opts.get(CONF_USE_EMSC, DEFAULT_USE_EMSC)
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    # ---- treptele ----------------------------------------------------------------
    async def async_step_tier_1(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._tier_step(1, user_input)

    async def async_step_tier_2(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._tier_step(2, user_input)

    async def async_step_tier_3(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._tier_step(3, user_input)

    async def _tier_step(self, tier: int, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        opts = self._options()
        current = (opts.get(CONF_TIERS) or {}).get(str(tier)) or {}
        if user_input is not None:
            speakers = user_input.get("speakers") or {}
            if speakers.get("entities") and not speakers.get("tts_entity"):
                errors["base"] = "tts_required"
            else:
                opts.setdefault(CONF_TIERS, {})[str(tier)] = user_input
                return await self.async_step_init()
            current = user_input
        return self.async_show_form(
            step_id=f"tier_{tier}",
            data_schema=self._tier_schema(tier, current),
            errors=errors,
            description_placeholders={"tier": str(tier)},
        )

    def _tier_schema(self, tier: int, cur: Mapping[str, Any]) -> vol.Schema:
        dmag, ddist = TIER_DEFAULTS[tier]
        cond = cur.get("conditions") or {}
        notif = cur.get("notify") or {}
        siren = cur.get("siren") or {}
        lights = cur.get("lights") or {}
        spk = cur.get("speakers") or {}

        default_message = DEFAULT_TTS_MESSAGE_RO if str(self.hass.config.language).lower().startswith("ro") else DEFAULT_TTS_MESSAGE_EN

        def suggested(value):
            return {"suggested_value": value}

        return vol.Schema(
            {
                vol.Required("conditions"): section(
                    vol.Schema(
                        {
                            vol.Required("min_magnitude", default=cond.get("min_magnitude", dmag)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=1.0, max=9.0, step=0.1, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Required("max_distance_km", default=cond.get("max_distance_km", ddist)): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=10, max=3000, step=10, unit_of_measurement="km", mode=selector.NumberSelectorMode.BOX
                                )
                            ),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required("notify"): section(
                    vol.Schema(
                        {
                            vol.Optional("services", description=suggested(notif.get("services", []))): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=notify_options(self.hass, notif.get("services", [])),
                                    multiple=True,
                                    mode=selector.SelectSelectorMode.DROPDOWN,
                                )
                            ),
                            vol.Optional("entities", description=suggested(notif.get("entities", []))): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="notify", multiple=True)
                            ),
                            vol.Optional("critical", default=notif.get("critical", False)): selector.BooleanSelector(),
                            vol.Optional("sound", description=suggested(notif.get("sound", ""))): selector.TextSelector(),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required("siren"): section(
                    vol.Schema(
                        {
                            vol.Optional("entities", description=suggested(siren.get("entities", []))): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="siren", multiple=True)
                            ),
                            vol.Optional("seconds", default=siren.get("seconds", DEFAULT_SIREN_SECONDS)): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=1, max=600, step=1, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
                                )
                            ),
                        }
                    ),
                    {"collapsed": not siren},
                ),
                vol.Required("lights"): section(
                    vol.Schema(
                        {
                            vol.Optional("entities", description=suggested(lights.get("entities", []))): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="light", multiple=True)
                            ),
                            vol.Optional("all", default=lights.get("all", False)): selector.BooleanSelector(),
                            vol.Optional("brightness", default=lights.get("brightness", DEFAULT_BRIGHTNESS)): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=1, max=100, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER
                                )
                            ),
                        }
                    ),
                    {"collapsed": not lights},
                ),
                vol.Required("speakers"): section(
                    vol.Schema(
                        {
                            vol.Optional("entities", description=suggested(spk.get("entities", []))): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="media_player", multiple=True)
                            ),
                            vol.Optional("tts_entity", description=suggested(spk.get("tts_entity"))): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="tts")
                            ),
                            vol.Optional("message", description=suggested(spk.get("message") or default_message)): selector.TextSelector(
                                selector.TextSelectorConfig(multiline=True)
                            ),
                            vol.Optional("volume", default=spk.get("volume", DEFAULT_SPEAKER_VOLUME)): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0.1, max=1.0, step=0.05, mode=selector.NumberSelectorMode.SLIDER
                                )
                            ),
                        }
                    ),
                    {"collapsed": not spk},
                ),
                vol.Optional("repeat", default=cur.get("repeat", False)): selector.BooleanSelector(),
            }
        )
