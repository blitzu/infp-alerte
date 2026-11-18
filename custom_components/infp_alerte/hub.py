"""Centrul integrarii: primeste cutremure de la surse, filtreaza, deduplica si anunta entitatile."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    CONF_API_HASH,
    CONF_API_ID,
    CONF_MAX_DISTANCE,
    CONF_MIN_MAGNITUDE,
    CONF_SESSION,
    CONF_USE_EMSC,
    DEFAULT_MAX_DISTANCE,
    DEFAULT_MIN_MAGNITUDE,
    DEFAULT_USE_EMSC,
    DOMAIN,
    EMSC_INTERVAL,
    MAX_AGE_SECONDS,
    SIGNAL_QUAKE,
    SIGNAL_STATUS,
)
from .alerts import AlertEngine
from .emsc import fetch_emsc
from .parser import Quake
from .quake_log import QuakeLog, from_dict, haversine_km, to_dict
from .telegram import TelegramAuthError, TelegramListener

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
AUTH_CHECK_EVERY = 10  # cicluri de stare (30 s) intre verificarile de sesiune


class Hub:
    """Gestioneaza sursele (Telegram INFP, EMSC) si starea ultimului cutremur."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.quake_log = QuakeLog()
        self.last: Quake | None = None
        self.last_distance_km: float | None = None
        self.last_revised = False
        self.telegram: TelegramListener | None = None
        self.engine = AlertEngine(hass, self)
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._seeded = False
        self._unsubs: list = []
        self._tick = 0

    # ---- optiuni -----------------------------------------------------
    @property
    def min_magnitude(self) -> float:
        return float(self.entry.options.get(CONF_MIN_MAGNITUDE, DEFAULT_MIN_MAGNITUDE))

    @property
    def max_distance(self) -> float:
        return float(self.entry.options.get(CONF_MAX_DISTANCE, DEFAULT_MAX_DISTANCE))

    @property
    def use_emsc(self) -> bool:
        return bool(self.entry.options.get(CONF_USE_EMSC, DEFAULT_USE_EMSC))

    @property
    def has_telegram(self) -> bool:
        return bool(self.entry.data.get(CONF_SESSION))

    @property
    def telegram_connected(self) -> bool:
        return self.telegram is not None and self.telegram.connected

    # ---- ciclu de viata -----------------------------------------------
    async def async_start(self) -> None:
        saved = await self._store.async_load() or {}
        self.quake_log = QuakeLog.from_list(saved.get("log"))
        self._seeded = bool(saved.get("seeded"))
        if saved.get("last"):
            try:
                self.last = from_dict(saved["last"])
                self.last_distance_km = saved.get("last_distance_km")
            except (KeyError, ValueError, TypeError):
                self.last = None

        await self.engine.async_start()
        if self.has_telegram:
            self.telegram = TelegramListener(
                int(self.entry.data[CONF_API_ID]),
                self.entry.data[CONF_API_HASH],
                self.entry.data[CONF_SESSION],
                self.async_handle_quake,
            )
            await self.telegram.async_start()  # TelegramAuthError -> reauth in __init__

        if self.use_emsc:
            await self._async_poll_emsc()
            self._unsubs.append(
                async_track_time_interval(self.hass, self._async_poll_emsc, timedelta(seconds=EMSC_INTERVAL))
            )
        self._unsubs.append(async_track_time_interval(self.hass, self._async_status_tick, timedelta(seconds=30)))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self.engine.async_stop()
        if self.telegram is not None:
            await self.telegram.async_stop()
            self.telegram = None

    # ---- procesare ----------------------------------------------------
    def distance_km(self, quake: Quake) -> float:
        return haversine_km(self.hass.config.latitude, self.hass.config.longitude, quake.latitude, quake.longitude)

    def _relevant(self, quake: Quake) -> tuple[bool, float]:
        dist = self.distance_km(quake)
        return quake.magnitude >= self.min_magnitude and dist <= self.max_distance, dist

    async def async_handle_quake(self, quake: Quake) -> None:
        """Punct unic de intrare pentru orice sursa."""
        relevant, dist = self._relevant(quake)
        if not relevant:
            return
        age = (datetime.now(UTC) - quake.time).total_seconds()
        if age > MAX_AGE_SECONDS:
            return
        announce, revised = self.quake_log.check(quake)
        if not announce:
            return
        previous = self.quake_log.known_magnitude(quake) if revised else None
        self.quake_log.record(quake)
        self.last, self.last_distance_km, self.last_revised = quake, round(dist, 1), revised
        await self._async_save()
        _LOGGER.info(
            "Cutremur M%.1f (%s) la %.0f km%s, sursa %s",
            quake.magnitude,
            quake.region or "?",
            dist,
            " [revizuit]" if revised else "",
            quake.source,
        )
        async_dispatcher_send(
            self.hass,
            SIGNAL_QUAKE,
            {"quake": quake, "distance_km": round(dist, 1), "revised": revised, "previous_magnitude": previous},
        )

    async def async_simulate(self, magnitude: float, distance_km: float, depth_km: float, region: str | None) -> None:
        """Cutremur de test: ocoleste pragurile si deduplicarea, se anunta imediat ca sursa "test"."""
        lat = self.hass.config.latitude + distance_km / 111.0  # la nord de casa, la distanta ceruta
        quake = Quake(magnitude, lat, self.hass.config.longitude, depth_km, datetime.now(UTC), "test", region)
        dist = self.distance_km(quake)
        self.last, self.last_distance_km, self.last_revised = quake, round(dist, 1), False
        async_dispatcher_send(
            self.hass, SIGNAL_QUAKE, {"quake": quake, "distance_km": round(dist, 1), "revised": False, "previous_magnitude": None}
        )

    async def _async_poll_emsc(self, _now: datetime | None = None) -> None:
        session = async_get_clientsession(self.hass)
        try:
            quakes = await fetch_emsc(
                session,
                self.hass.config.latitude,
                self.hass.config.longitude,
                self.max_distance,
                self.min_magnitude,
            )
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("EMSC indisponibil momentan: %s", err)
            return
        if not self._seeded:
            # Prima citire: cutremurele de dinainte de instalare nu se anunta
            self.quake_log.seed([q for q in quakes if self._relevant(q)[0]])
            self._seeded = True
            await self._async_save()
            return
        for quake in quakes:
            await self.async_handle_quake(quake)

    async def _async_status_tick(self, _now: datetime | None = None) -> None:
        self._tick += 1
        if self.telegram is not None and self._tick % AUTH_CHECK_EVERY == 0:
            if not await self.telegram.async_check_authorized():
                _LOGGER.warning("Sesiunea Telegram nu mai e valida; este nevoie de autentificare")
                self.entry.async_start_reauth(self.hass)
        async_dispatcher_send(self.hass, SIGNAL_STATUS)

    async def _async_save(self) -> None:
        data: dict[str, Any] = {"log": self.quake_log.as_list(), "seeded": self._seeded}
        if self.last is not None:
            data["last"] = to_dict(self.last)
            data["last_distance_km"] = self.last_distance_km
        await self._store.async_save(data)


__all__ = ["Hub", "TelegramAuthError"]
