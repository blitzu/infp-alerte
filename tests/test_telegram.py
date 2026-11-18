"""Ascultatorul Telegram: accepta buletine doar din canale de difuzare (nu din chat-uri private sau grupuri)."""
from types import SimpleNamespace

import pytest

from custom_components.infp_alerte.telegram import TelegramListener

MESAJ = "Exemplu 2026-03-04 05:06:07 UTC Mw=5.3 LAT=45.6 LON=26.7 H=120"


class _Event:
    def __init__(self, text, chat):
        self.raw_text = text
        self._chat = chat

    async def get_chat(self):
        return self._chat


@pytest.fixture
def listener():
    primite = []

    async def on_quake(q):
        primite.append(q)

    obj = TelegramListener.__new__(TelegramListener)  # fara conexiune reala
    obj._on_quake = on_quake
    return obj, primite


async def test_canal_de_difuzare_este_acceptat(listener):
    obj, primite = listener
    await obj._handle(_Event(MESAJ, SimpleNamespace(broadcast=True)))
    assert len(primite) == 1 and primite[0].magnitude == 5.3


@pytest.mark.parametrize(
    "chat",
    [
        SimpleNamespace(first_name="Cineva"),  # chat privat (User, fara atributul broadcast)
        SimpleNamespace(broadcast=False, megagroup=True),  # supergrup: oricine din grup poate scrie
        SimpleNamespace(title="Grup mic"),  # grup obisnuit
    ],
)
async def test_chat_privat_si_grupuri_sunt_ignorate(listener, chat):
    obj, primite = listener
    await obj._handle(_Event(MESAJ, chat))
    assert primite == []


async def test_text_obisnuit_nu_cere_nici_macar_chatul(listener):
    obj, primite = listener

    class _FaraChat:
        raw_text = "salut"

        async def get_chat(self):
            raise AssertionError("nu trebuie apelat pentru mesaje care nu sunt buletine")

    await obj._handle(_FaraChat())
    assert primite == []
