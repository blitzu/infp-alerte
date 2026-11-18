"""Sursa EMSC (seismicportal.eu, FDSN): cutremure din lume, acces public fara cont. Rezerva pentru INFP, mai lenta."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
from math import cos, radians
from typing import Any

import aiohttp

from .const import EMSC_URL, EMSC_WINDOW_HOURS
from .parser import Quake

_LOGGER = logging.getLogger(__name__)


def _region(name: str | None) -> str | None:
    if not name:
        return None
    return "România" if name.strip().upper() == "ROMANIA" else name.strip().title()


def parse_emsc(body: str | bytes) -> list[Quake]:
    """Transforma raspunsul EMSC (GeoJSON) in cutremure. Corp gol = niciun eveniment."""
    if not body or not body.strip():
        return []
    data = json.loads(body)
    out: list[Quake] = []
    for feature in data.get("features", []):
        try:
            props = feature["properties"]
            lon, lat = feature["geometry"]["coordinates"][:2]
            when = datetime.fromisoformat(props["time"].replace("Z", "+00:00")).astimezone(UTC)
            out.append(
                Quake(
                    magnitude=float(props["mag"]),
                    latitude=float(lat),
                    longitude=float(lon),
                    depth_km=abs(float(props.get("depth") or 0)),
                    time=when,
                    source="emsc",
                    region=_region(props.get("flynn_region")),
                    event_id=props.get("unid") or feature.get("id"),
                )
            )
        except (KeyError, ValueError, TypeError) as err:
            _LOGGER.debug("Eveniment EMSC ignorat (format neasteptat): %s", err)
    out.sort(key=lambda q: q.time)
    return out


def build_params(lat: float, lon: float, radius_km: float, min_magnitude: float) -> dict[str, Any]:
    """Cutie in jurul casei, cu raza ceruta, ca sa nu cerem lumea intreaga."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(cos(radians(lat)), 0.1))
    start = datetime.now(UTC) - timedelta(hours=EMSC_WINDOW_HOURS)
    return {
        "format": "json",
        "minlat": round(max(lat - dlat, -90), 3),
        "maxlat": round(min(lat + dlat, 90), 3),
        "minlon": round(max(lon - dlon, -180), 3),
        "maxlon": round(min(lon + dlon, 180), 3),
        "minmag": min_magnitude,
        "limit": 50,
        "orderby": "time",
        "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
    }


async def fetch_emsc(
    session: aiohttp.ClientSession, lat: float, lon: float, radius_km: float, min_magnitude: float
) -> list[Quake]:
    """Citeste cutremurele recente din jurul casei. Ridica aiohttp.ClientError la probleme de retea."""
    params = build_params(lat, lon, radius_km, min_magnitude)
    async with session.get(EMSC_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        return parse_emsc(await resp.read())
