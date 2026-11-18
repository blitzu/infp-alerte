"""Motorul de alerta pe trepte: face singur ce a ales utilizatorul din interfata (fara scripturi sau YAML).

Treapta unui cutremur se alege dupa magnitudine si distanta. Pentru fiecare treapta utilizatorul poate alege: notificari
pe telefoane (normale sau critice), sirene, lumini, boxe cu mesaj vocal. Inainte de treapta cu lumini/boxe se salveaza
starea lor, iar la "Am vazut" (sau dupa 30 de minute) se readuce.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.util import dt as dt_util

from . import const
from .const import (
    ACK_ACTION,
    ACK_TELEGRAM,
    CONF_TIERS,
    DEFAULT_BRIGHTNESS,
    DEFAULT_SIREN_SECONDS,
    DEFAULT_SPEAKER_VOLUME,
    DEFAULT_TTS_MESSAGE_EN,
    DEFAULT_TTS_MESSAGE_RO,
    SCENE_ID,
    SIGNAL_ALERT,
    SIGNAL_QUAKE,
    TIER_DEFAULTS,
    TIERS,
)

if TYPE_CHECKING:
    from .hub import Hub

_LOGGER = logging.getLogger(__name__)

_TEXTS = {
    "ro": {
        "drill": "EXERCIȚIU",
        "title": "Cutremur M{mag} – {region}",
        "body": "M{mag}, {region}, la {dist} km de casă, adâncime {depth} km, ora {time}.",
        "drill_body": " Exercițiu: nu e un cutremur real.",
        "ack": "Am văzut",
        "ack_done": "Am oprit alerta.",
        "drill_voice": "Exercițiu, nu este un cutremur real. ",
    },
    "en": {
        "drill": "DRILL",
        "title": "Earthquake M{mag} – {region}",
        "body": "M{mag}, {region}, {dist} km from home, depth {depth} km, time {time}.",
        "drill_body": " Drill: this is not a real earthquake.",
        "ack": "Seen it",
        "ack_done": "Alert stopped.",
        "drill_voice": "Drill, this is not a real earthquake. ",
    },
}


@dataclass(slots=True)
class TierConfig:
    """Ce are de facut o treapta (citit din optiunile intrarii)."""

    tier: int
    min_magnitude: float
    max_distance: float
    notify: list[str] = field(default_factory=list)
    notify_entities: list[str] = field(default_factory=list)
    critical: bool = False
    sound: str = "default"
    sirens: list[str] = field(default_factory=list)
    siren_seconds: int = DEFAULT_SIREN_SECONDS
    lights: list[str] = field(default_factory=list)
    all_lights: bool = False
    brightness: int = DEFAULT_BRIGHTNESS
    speakers: list[str] = field(default_factory=list)
    tts_entity: str | None = None
    tts_message: str = ""
    speaker_volume: float = DEFAULT_SPEAKER_VOLUME
    repeat: bool = False

    @property
    def has_actions(self) -> bool:
        return bool(
            self.notify
            or self.notify_entities
            or self.sirens
            or self.lights
            or self.all_lights
            or (self.speakers and self.tts_entity)
        )

    def matches(self, magnitude: float, distance_km: float) -> bool:
        return magnitude >= self.min_magnitude and distance_km <= self.max_distance

    @classmethod
    def from_options(cls, tier: int, data: Mapping[str, Any] | None) -> TierConfig:
        """Citeste o treapta din optiuni (structura cu sectiuni din formular, tolerant la lipsuri)."""
        data = data or {}
        cond = data.get("conditions") or {}
        notif = data.get("notify") or {}
        siren = data.get("siren") or {}
        lights = data.get("lights") or {}
        spk = data.get("speakers") or {}
        dmag, ddist = TIER_DEFAULTS[tier]
        return cls(
            tier=tier,
            min_magnitude=float(cond.get("min_magnitude", dmag)),
            max_distance=float(cond.get("max_distance_km", ddist)),
            notify=list(notif.get("services") or []),
            notify_entities=list(notif.get("entities") or []),
            critical=bool(notif.get("critical", False)),
            sound=(notif.get("sound") or "default").strip() or "default",
            sirens=list(siren.get("entities") or []),
            siren_seconds=int(siren.get("seconds", DEFAULT_SIREN_SECONDS)),
            lights=list(lights.get("entities") or []),
            all_lights=bool(lights.get("all", False)),
            brightness=int(lights.get("brightness", DEFAULT_BRIGHTNESS)),
            speakers=list(spk.get("entities") or []),
            tts_entity=spk.get("tts_entity") or None,
            tts_message=(spk.get("message") or "").strip(),
            speaker_volume=float(spk.get("volume", DEFAULT_SPEAKER_VOLUME)),
            repeat=bool(data.get("repeat", False)),
        )


class AlertEngine:
    """Asculta cutremurele anuntate de hub si executa treapta potrivita."""

    def __init__(self, hass: HomeAssistant, hub: Hub) -> None:
        self.hass = hass
        self.hub = hub
        self.tiers: dict[int, TierConfig] = {}
        self.active_tier = 0
        self._task: asyncio.Task | None = None
        self._ack = asyncio.Event()
        self._snapshot_taken = False
        self._saved_volumes: dict[str, float] = {}
        self._stop_entities: tuple[list[str], list[str]] = ([], [])
        self._telegram_entry_id: str | None = None
        self._unsubs: list = []

    # ---- ciclu de viata -----------------------------------------------
    def load_options(self) -> None:
        raw = self.hub.entry.options.get(CONF_TIERS) or {}
        self.tiers = {t: TierConfig.from_options(t, raw.get(str(t))) for t in TIERS}

    async def async_start(self) -> None:
        self.load_options()
        self._unsubs.append(async_dispatcher_connect(self.hass, SIGNAL_QUAKE, self._on_quake))
        self._unsubs.append(self.hass.bus.async_listen("mobile_app_notification_action", self._on_mobile_action))
        self._unsubs.append(self.hass.bus.async_listen("telegram_callback", self._on_telegram_callback))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    @property
    def active(self) -> bool:
        return self.active_tier > 0

    # ---- alegerea treptei --------------------------------------------------
    def tier_for(self, magnitude: float, distance_km: float) -> int:
        """Cea mai inalta treapta (3 -> 1) potrivita si care are macar o actiune configurata; 0 daca niciuna."""
        for tier in sorted(TIERS, reverse=True):
            cfg = self.tiers.get(tier)
            if cfg is not None and cfg.has_actions and cfg.matches(magnitude, distance_km):
                return tier
        return 0

    @callback
    def _on_quake(self, payload: dict[str, Any]) -> None:
        quake = payload["quake"]
        dist = payload["distance_km"]
        tier = self.tier_for(quake.magnitude, dist)
        if tier == 0:
            return
        if payload.get("revised"):
            # O revizuire ruleaza actiunile doar daca treapta CRESTE (altfel 5.3 -> 5.5 -> 5.7 ar suna de trei ori).
            prev = payload.get("previous_magnitude")
            if prev is not None and self.tier_for(float(prev), dist) >= tier:
                return
        info = {
            "mag": f"{quake.magnitude:.1f}",
            "region": quake.region or ("zona României" if self._ro else "Romania"),
            "dist": f"{dist:.0f}",
            "depth": f"{quake.depth_km:.0f}",
            "time": dt_util.as_local(quake.time).strftime("%H:%M:%S"),
        }
        drill = quake.source == "test"  # cutremurele simulate = exercitiu (efecte reale, texte marcate)
        self.start(tier, info, drill)

    @callback
    def _on_mobile_action(self, event: Event) -> None:
        if event.data.get("action") == ACK_ACTION:
            self.hass.async_create_task(self.async_acknowledge())

    @callback
    def _on_telegram_callback(self, event: Event) -> None:
        """Butonul "Am vazut" din mesajul Telegram."""
        if event.data.get("data") != ACK_TELEGRAM:
            return
        self.hass.async_create_task(self._telegram_ack(event.data))

    async def _telegram_ack(self, data: Mapping[str, Any]) -> None:
        await self.async_acknowledge()
        entry_id = self._telegram_entry_id
        if not entry_id:
            return
        # Confirm apasarea si scot butonul din mesaj (daca esueaza, nu conteaza)
        await self._call(
            "telegram_bot",
            "answer_callback_query",
            {"config_entry_id": entry_id, "callback_query_id": data.get("id"), "message": self._t["ack_done"]},
        )
        message = data.get("message") or {}
        if message.get("message_id") and data.get("chat_id"):
            await self._call(
                "telegram_bot",
                "edit_replymarkup",
                {
                    "config_entry_id": entry_id,
                    "message_id": message["message_id"],
                    "chat_id": data["chat_id"],
                    "inline_keyboard": [],
                },
            )

    # ---- executie -----------------------------------------------------------
    @callback
    def start(self, tier: int, info: dict[str, str], drill: bool) -> None:
        """Porneste (sau escaladeaza) alerta. O alerta noua o inlocuieste pe cea in curs, fara sa piarda starea salvata."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._ack = asyncio.Event()
        self.active_tier = tier
        async_dispatch(self.hass)
        self._task = self.hass.async_create_task(self._run(tier, info, drill))

    @property
    def _ro(self) -> bool:
        return str(self.hass.config.language).lower().startswith("ro")

    @property
    def _t(self) -> dict[str, str]:
        return _TEXTS["ro" if self._ro else "en"]

    def _texts(self, info: dict[str, str], drill: bool) -> tuple[str, str]:
        t = self._t
        title = t["title"].format(**info)
        body = t["body"].format(**info)
        if drill:
            title = f"{t['drill']} – {title}"
            body += t["drill_body"]
        return title, body

    async def _call(self, domain: str, service: str, data: dict[str, Any], *, blocking: bool = False) -> None:
        """Apel de serviciu care nu opreste alerta daca un dispozitiv lipseste sau da eroare.

        Implicit NEBLOCANT: o singura lumina sau un singur telefon lent nu trebuie sa intarzie sirena si vocea.
        """
        try:
            await self.hass.services.async_call(domain, service, data, blocking=blocking)
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("Alerta: %s.%s a esuat: %s", domain, service, err)

    async def _run(self, tier: int, info: dict[str, str], drill: bool) -> None:
        cfg = self.tiers[tier]
        try:
            if (cfg.lights or cfg.all_lights or cfg.speakers) and not self._snapshot_taken:
                await self._snapshot(cfg)
            self._stop_entities = (list(cfg.sirens), list(cfg.speakers))
            cycles = const.MAX_CYCLES if (cfg.repeat and tier >= 3) else 1
            for i in range(cycles):
                if self._ack.is_set():
                    break
                actions = [self._speak(cfg, info, drill), self._sirens(cfg)]
                if i == 0:
                    # Prima data si notificarile si luminile, TOATE in paralel cu sirena si vocea
                    actions += [self._notify(cfg, info, drill), self._lights_on(cfg)]
                await asyncio.gather(*actions)
                if i < cycles - 1:
                    await self._wait_ack(const.CYCLE_PAUSE)
            # Dupa ultimul ciclu: astept confirmarea; fara ea, readuc casa cum era dupa 30 de minute.
            # O treapta doar cu notificari nu are ce sa readuca, deci se incheie imediat.
            if cfg.sirens or cfg.lights or cfg.all_lights or cfg.speakers:
                await self._wait_ack(const.RESTORE_TIMEOUT)
                await self._restore()
        except asyncio.CancelledError:
            raise
        finally:
            if self._task is asyncio.current_task():
                self.active_tier = 0
                async_dispatch(self.hass)

    async def _wait_ack(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._ack.wait(), seconds)
        except TimeoutError:
            pass

    # ---- actiuni ------------------------------------------------------------
    async def _notify(self, cfg: TierConfig, info: dict[str, str], drill: bool) -> None:
        if not (cfg.notify or cfg.notify_entities):
            return
        title, body = self._texts(info, drill)
        data: dict[str, Any] = {
            "tag": "infp_alerte",
            "ttl": 0,
            "priority": "high",
            "sticky": "true",
            "channel": "alarm_stream" if cfg.critical else "infp_alerte",
            "importance": "max" if cfg.critical else "high",
            "push": {
                "interruption-level": "critical" if cfg.critical else "time-sensitive",
                "sound": {"name": cfg.sound if cfg.critical else "default", "critical": 1 if cfg.critical else 0, "volume": 1},
            },
            "actions": [{"action": ACK_ACTION, "title": self._t["ack"]}],
        }
        calls = [self._call("notify", name, {"title": title, "message": body, "data": data}) for name in cfg.notify]
        others: list[str] = []
        registry = er.async_get(self.hass)
        for entity in cfg.notify_entities:
            reg = registry.async_get(entity)
            if reg is not None and reg.platform == "telegram_bot" and reg.config_entry_id and reg.unique_id:
                # Botul Telegram: mesaj cu buton "Am vazut" (unique_id = "<bot>_<chat>")
                chat = reg.unique_id.rsplit("_", 1)[-1]
                self._telegram_entry_id = reg.config_entry_id
                calls.append(
                    self._call(
                        "telegram_bot",
                        "send_message",
                        {
                            "config_entry_id": reg.config_entry_id,
                            "chat_id": int(chat) if chat.lstrip("-").isdigit() else chat,
                            "title": title,
                            "message": body,
                            "inline_keyboard": [f"{self._t['ack']}:{ACK_TELEGRAM}"],
                        },
                    )
                )
            else:
                others.append(entity)
        if others:
            calls.append(self._call("notify", "send_message", {"entity_id": others, "title": title, "message": body}))
        await asyncio.gather(*calls)

    async def _snapshot(self, cfg: TierConfig) -> None:
        """Salveaza luminile (instantaneu) si volumele boxelor, ca sa le poata readuce."""
        lights = self._light_targets(cfg)
        if lights:
            await self._call("scene", "create", {"scene_id": SCENE_ID, "snapshot_entities": lights}, blocking=True)
        self._saved_volumes = {}
        for entity in cfg.speakers:
            state = self.hass.states.get(entity)
            volume = state.attributes.get("volume_level") if state else None
            if volume is not None:
                self._saved_volumes[entity] = float(volume)
        self._snapshot_taken = True

    def _light_targets(self, cfg: TierConfig) -> list[str]:
        if cfg.all_lights:
            return [
                s.entity_id
                for s in self.hass.states.async_all("light")
                if s.state not in ("unavailable", "unknown")
            ]
        return list(cfg.lights)

    async def _lights_on(self, cfg: TierConfig) -> None:
        if not (cfg.lights or cfg.all_lights):
            return
        targets = self._light_targets(cfg)
        if targets:
            await self._call("light", "turn_on", {"entity_id": targets, "brightness_pct": cfg.brightness})

    async def _sirens(self, cfg: TierConfig) -> None:
        if cfg.sirens:
            await self._call(
                "siren", "turn_on", {"entity_id": cfg.sirens, "duration": cfg.siren_seconds, "volume_level": 1.0}
            )

    async def _speak(self, cfg: TierConfig, info: dict[str, str], drill: bool) -> None:
        if not (cfg.speakers and cfg.tts_entity):
            return
        template = cfg.tts_message or (DEFAULT_TTS_MESSAGE_RO if self._ro else DEFAULT_TTS_MESSAGE_EN)
        try:
            text = template.format(
                magnitude=info["mag"], region=info["region"], distance=info["dist"], depth=info["depth"], time=info["time"]
            )
        except (KeyError, IndexError, ValueError):
            text = template  # sablon cu acolade gresite: se citeste ca atare
        if drill:
            text = self._t["drill_voice"] + text
        await asyncio.gather(
            *(
                self._speak_one(entity, cfg.tts_entity, text, cfg.speaker_volume)
                for entity in cfg.speakers
            )
        )

    async def _speak_one(self, entity: str, tts_entity: str, text: str, volume: float) -> None:
        await self._call("media_player", "volume_set", {"entity_id": entity, "volume_level": volume})
        await self._call(
            "tts", "speak", {"entity_id": tts_entity, "media_player_entity_id": entity, "message": text, "cache": False}
        )

    # ---- confirmare si readucere -------------------------------------------
    async def async_acknowledge(self) -> None:
        """"Am vazut": opreste sirenele si boxele, apoi readuce luminile si volumele."""
        self._ack.set()
        sirens, speakers = self._stop_entities
        if sirens:
            await self._call("siren", "turn_off", {"entity_id": sirens})
        if speakers:
            await self._call("media_player", "media_stop", {"entity_id": speakers})
        if self._task is not None and not self._task.done() and self._task is not asyncio.current_task():
            self._task.cancel()
        await self._restore()
        self.active_tier = 0
        async_dispatch(self.hass)

    async def _restore(self) -> None:
        if not self._snapshot_taken:
            return
        self._snapshot_taken = False
        if self.hass.states.get(f"scene.{SCENE_ID}") is not None:
            await self._call("scene", "turn_on", {"entity_id": f"scene.{SCENE_ID}"})
        for entity, volume in self._saved_volumes.items():
            await self._call("media_player", "volume_set", {"entity_id": entity, "volume_level": volume})
        self._saved_volumes = {}


def async_dispatch(hass: HomeAssistant) -> None:
    """Anunta entitatile ca starea alertei s-a schimbat."""
    async_dispatcher_send(hass, SIGNAL_ALERT)
