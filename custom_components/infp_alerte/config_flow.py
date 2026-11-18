"""Configurare din interfata: autentificare Telegram cu contul propriu al utilizatorului (sau doar EMSC)."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from telethon import TelegramClient, errors
from telethon.sessions import StringSession
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import selector

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
    CONF_USE_EMSC,
    DEFAULT_MAX_DISTANCE,
    DEFAULT_MIN_MAGNITUDE,
    DEFAULT_USE_EMSC,
    DOMAIN,
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


class InfpOptionsFlow(OptionsFlowWithReload):
    """Praguri de baza; alertele pe trepte se configureaza din blueprint."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
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
        return self.async_show_form(step_id="init", data_schema=schema)
