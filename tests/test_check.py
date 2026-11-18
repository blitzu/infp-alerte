"""Serviciul de verificare a abonarilor: doar canalele de difuzare care par INFP."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.infp_alerte.const import DOMAIN
from custom_components.infp_alerte.telegram import TelegramListener
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .test_init import _FakeListener, _setup


class _Client:
    def __init__(self, dialogs):
        self._dialogs = dialogs

    async def iter_dialogs(self):
        for d in self._dialogs:
            yield d


def _dialog(title, broadcast):
    return SimpleNamespace(entity=SimpleNamespace(title=title, broadcast=broadcast))


async def test_listeaza_doar_canale_de_difuzare_care_par_infp():
    obj = TelegramListener.__new__(TelegramListener)
    obj._client = _Client([
        _dialog("Alerta Cutremur M>5", True),
        _dialog("INFP - alerte 4.0", True),
        _dialog("Familia", True),               # canal fara legatura: nu apare
        _dialog("Grup cutremur discutii", False),  # grup, nu canal de difuzare: nu apare
    ])
    assert await obj.async_list_candidate_channels() == ["Alerta Cutremur M>5", "INFP - alerte 4.0"]


async def test_serviciul_intoarce_lista(hass: HomeAssistant, hass_storage):
    _FakeListener.async_list_candidate_channels = AsyncMock(return_value=["Alerta Cutremur M>5"])
    with patch("custom_components.infp_alerte.hub.TelegramListener", _FakeListener):
        await _setup(hass, data={"api_id": 1, "api_hash": "h", "session": "s"})
        res = await hass.services.async_call(DOMAIN, "check_subscriptions", {}, blocking=True, return_response=True)
    assert res == {"count": 1, "channels": ["Alerta Cutremur M>5"]}


async def test_fara_cont_telegram_da_eroare(hass: HomeAssistant, hass_storage):
    await _setup(hass)  # doar EMSC
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "check_subscriptions", {}, blocking=True, return_response=True)
