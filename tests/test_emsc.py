"""Citirea raspunsului EMSC."""
import json

from custom_components.infp_alerte.emsc import build_params, parse_emsc

CORP = json.dumps(
    {
        "type": "FeatureCollection",
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [26.5495, 45.6952, -140.0]},
                "id": "20261118_0000012",
                "properties": {
                    "unid": "20261118_0000012",
                    "mag": 5.3,
                    "time": "2026-11-18T00:48:56.38Z",
                    "depth": 140.0,
                    "flynn_region": "ROMANIA",
                },
            },
            {"geometry": {}, "properties": {}},  # eveniment stricat: se ignora
        ],
    }
)


def test_parseaza_evenimentul_real():
    (q,) = parse_emsc(CORP)
    assert (q.magnitude, q.latitude, q.longitude, q.depth_km) == (5.3, 45.6952, 26.5495, 140.0)
    assert q.region == "România" and q.source == "emsc" and q.event_id == "20261118_0000012"


def test_corp_gol_inseamna_niciun_eveniment():
    assert parse_emsc(b"") == []
    assert parse_emsc("  \n") == []


def test_cutia_de_cautare_e_in_jurul_casei():
    p = build_params(44.43, 26.10, 450, 3.0)
    assert p["minlat"] < 44.43 < p["maxlat"] and p["minlon"] < 26.10 < p["maxlon"]
    assert p["minmag"] == 3.0 and p["format"] == "json"
