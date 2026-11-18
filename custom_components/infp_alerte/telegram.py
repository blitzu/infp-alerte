"""Ascultator Telegram (cont de utilizator, Telethon): citeste buletinele INFP din canalele la care e abonat contul."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
import re

from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession

from .parser import Quake, parse_infp

_LOGGER = logging.getLogger(__name__)

# Canalele "candidate": difuzare + titlu care aminteste de serviciul de alerta seismica. Titlurile care nu se potrivesc nu
# sunt citite mai departe si nu apar nicaieri.
_CANDIDATE_TITLE = re.compile(r"infp|incdfp|cutremur|seism|alert", re.IGNORECASE)


class TelegramAuthError(Exception):
    """Sesiunea Telegram nu mai e valida: trebuie autentificare din nou."""


class TelegramListener:
    """Se conecteaza cu sesiunea salvata si trimite fiecare buletin INFP recunoscut mai departe.

    Citeste doar mesajele care arata ca un buletin INFP (Mw=, LAT=, LON=). Restul continutului contului nu e stocat,
    logat sau trimis nicaieri.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session: str,
        on_quake: Callable[[Quake], Awaitable[None]],
    ) -> None:
        self._client = TelegramClient(
            StringSession(session),
            api_id,
            api_hash,
            connection_retries=-1,
            retry_delay=5,
            auto_reconnect=True,
        )
        self._on_quake = on_quake

    async def async_start(self) -> None:
        await self._client.connect()
        try:
            authorized = await self._client.is_user_authorized()
        except (errors.AuthKeyError, errors.SessionRevokedError, errors.UserDeactivatedError) as err:
            await self._client.disconnect()
            raise TelegramAuthError(str(err)) from err
        if not authorized:
            await self._client.disconnect()
            raise TelegramAuthError("sesiune neautorizata")
        self._client.add_event_handler(self._handle, events.NewMessage(incoming=True))
        self._client.add_event_handler(self._handle, events.MessageEdited(incoming=True))

    async def async_stop(self) -> None:
        await self._client.disconnect()

    @property
    def connected(self) -> bool:
        return self._client.is_connected()

    async def async_check_authorized(self) -> bool:
        """Verificare periodica (retea): sesiunea mai e valida?"""
        try:
            return await self._client.is_user_authorized()
        except (errors.AuthKeyError, errors.SessionRevokedError, errors.UserDeactivatedError):
            return False
        except Exception:  # retea intrerupta: nu stim, nu declaram sesiunea pierduta
            return True

    async def async_list_candidate_channels(self) -> list[str]:
        """Titlurile canalelor de difuzare ale contului care par canale INFP de alerta seismica."""
        titles: list[str] = []
        async for dialog in self._client.iter_dialogs():
            entity = dialog.entity
            title = getattr(entity, "title", None)
            if getattr(entity, "broadcast", False) and title and _CANDIDATE_TITLE.search(title):
                titles.append(title)
        return sorted(titles)

    async def _handle(self, event) -> None:
        quake = parse_infp(event.raw_text)
        if quake is None:
            return
        # Securitate: un buletin e acceptat DOAR dintr-un canal de difuzare (cum e cel INFP). Conversatiile private si
        # grupurile permit oricui sa trimita un text fals care ar porni sirena, deci sunt ignorate.
        chat = await event.get_chat()
        if not getattr(chat, "broadcast", False):
            _LOGGER.warning(
                "Mesaj in forma unui buletin INFP, ignorat: nu vine dintr-un canal de difuzare (tip chat: %s)",
                type(chat).__name__,
            )
            return
        _LOGGER.debug(
            "Buletin INFP recunoscut din canalul %r: M%s la %s", getattr(chat, "title", "?"), quake.magnitude, quake.time
        )
        await self._on_quake(quake)
