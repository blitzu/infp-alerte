"""Modelul unui cutremur si parserul buletinelor INFP (fara dependente de Home Assistant, usor de testat)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re

_NUM = r"(-?[0-9]+(?:[.,][0-9]+)?)"
_RE_MW = re.compile(r"Mw\s*=\s*" + _NUM)
_RE_LAT = re.compile(r"LAT\s*=\s*" + _NUM)
_RE_LON = re.compile(r"LON\s*=\s*" + _NUM)
_RE_H = re.compile(r"\bH\s*=\s*" + _NUM)
_RE_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?")


@dataclass(slots=True)
class Quake:
    """Un cutremur, indiferent de sursa."""

    magnitude: float
    latitude: float
    longitude: float
    depth_km: float
    time: datetime  # UTC, cu fus orar
    source: str
    region: str | None = None
    event_id: str | None = None


def _num(match: re.Match[str]) -> float:
    return float(match.group(1).replace(",", "."))


def vrancea_or_none(lat: float, lon: float) -> str | None:
    """Zona Vrancea e sursa celor mai multe cutremure resimtite in Romania."""
    if 45.2 <= lat <= 46.1 and 26.0 <= lon <= 27.6:
        return "Vrancea"
    return None


def parse_infp(text: str | None, now: datetime | None = None) -> Quake | None:
    """Intoarce un Quake daca textul e un buletin INFP complet (Mw, LAT, LON), altfel None.

    Cauta in text magnitudinea (`Mw=`), coordonatele (`LAT=`, `LON=`), adancimea (`H=`) si data/ora UTC. Formatul e
    cel observat in buletinele serviciului; nu se reproduce aici textul serviciului.
    """
    if not text:
        return None
    mw, lat_m, lon_m = _RE_MW.search(text), _RE_LAT.search(text), _RE_LON.search(text)
    if not (mw and lat_m and lon_m):
        return None
    lat, lon = _num(lat_m), _num(lon_m)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    depth_m = _RE_H.search(text)
    time_m = _RE_TIME.search(text)
    if time_m:
        year, month, day, hour, minute, second = (int(time_m.group(i)) for i in range(1, 7))
        frac = time_m.group(7) or "0"
        micro = int((frac + "000000")[:6])
        when = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    else:
        when = now or datetime.now(UTC)
    return Quake(
        magnitude=_num(mw),
        latitude=lat,
        longitude=lon,
        depth_km=_num(depth_m) if depth_m else 0.0,
        time=when,
        source="infp",
        region=vrancea_or_none(lat, lon),
    )
