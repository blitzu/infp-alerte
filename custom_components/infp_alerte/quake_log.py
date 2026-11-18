"""Evidenta cutremurelor deja anuntate: deduplicare intre surse si intre reporniri (fara dependente de HA)."""
from __future__ import annotations

from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any

from .const import DEDUP_KM, DEDUP_SECONDS, REVISION_STEP
from .parser import Quake

MAX_ENTRIES = 30


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanta pe sfera, in km."""
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(a))


def _same_event(a: Quake, b: Quake) -> bool:
    dt = abs((a.time - b.time).total_seconds())
    return dt <= DEDUP_SECONDS and haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) <= DEDUP_KM


def to_dict(q: Quake) -> dict[str, Any]:
    return {
        "magnitude": q.magnitude,
        "latitude": q.latitude,
        "longitude": q.longitude,
        "depth_km": q.depth_km,
        "time": q.time.isoformat(),
        "source": q.source,
        "region": q.region,
        "event_id": q.event_id,
    }


def from_dict(d: dict[str, Any]) -> Quake:
    return Quake(
        magnitude=float(d["magnitude"]),
        latitude=float(d["latitude"]),
        longitude=float(d["longitude"]),
        depth_km=float(d.get("depth_km") or 0),
        time=datetime.fromisoformat(d["time"]).astimezone(UTC),
        source=d.get("source", "?"),
        region=d.get("region"),
        event_id=d.get("event_id"),
    )


class QuakeLog:
    """Tine minte ultimele cutremure anuntate si spune daca unul nou trebuie anuntat."""

    def __init__(self, entries: list[Quake] | None = None) -> None:
        self.entries: list[Quake] = list(entries or [])

    def check(self, quake: Quake) -> tuple[bool, bool]:
        """Intoarce (de_anuntat, revizuire).

        - necunoscut inca -> se anunta;
        - deja anuntat (alta sursa sau aceeasi, aceleasi coordonate aprox.) -> se ignora;
        - deja anuntat, dar magnitudinea a crescut cu cel putin REVISION_STEP -> se anunta ca revizuire.
        """
        for known in self.entries:
            if _same_event(known, quake):
                if quake.magnitude >= known.magnitude + REVISION_STEP:
                    return True, True
                return False, False
        return True, False

    def known_magnitude(self, quake: Quake) -> float | None:
        """Magnitudinea ultimei versiuni anuntate a aceluiasi eveniment (None daca e nou)."""
        for known in self.entries:
            if _same_event(known, quake):
                return known.magnitude
        return None

    def record(self, quake: Quake) -> None:
        """Memoreaza cutremurul anuntat (inlocuieste vechea versiune a aceluiasi eveniment)."""
        self.entries = [e for e in self.entries if not _same_event(e, quake)]
        self.entries.append(quake)
        self.entries.sort(key=lambda e: e.time)
        del self.entries[:-MAX_ENTRIES]

    def seed(self, quakes: list[Quake]) -> None:
        """Marcheaza cutremure existente ca vazute, fara a le anunta (prima citire)."""
        for q in quakes:
            if self.check(q)[0]:
                self.record(q)

    def as_list(self) -> list[dict[str, Any]]:
        return [to_dict(e) for e in self.entries]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]] | None) -> QuakeLog:
        out: list[Quake] = []
        for d in data or []:
            try:
                out.append(from_dict(d))
            except (KeyError, ValueError, TypeError):
                continue
        return cls(out)
