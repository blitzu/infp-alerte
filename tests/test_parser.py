"""Parserul buletinelor INFP."""
from datetime import UTC, datetime

from custom_components.infp_alerte.parser import parse_infp

# Mesaj INVENTAT, in acelasi format (cifre si formulare proprii), nu textul real al INCDFP.
MESAJ_EXEMPLU = "Exemplu: la 2026-03-04 05:06:07.89 UTC, Mw=4.7, LAT=45.6000, LON=26.7000, H=120.5 km."


def test_mesaj_in_formatul_buletinului():
    q = parse_infp(MESAJ_EXEMPLU)
    assert q is not None
    assert q.magnitude == 4.7
    assert (q.latitude, q.longitude) == (45.6, 26.7)
    assert q.depth_km == 120.5
    assert q.time == datetime(2026, 3, 4, 5, 6, 7, 890000, tzinfo=UTC)
    assert q.source == "infp"
    assert q.region == "Vrancea"


def test_mesaj_fara_date_este_ignorat():
    assert parse_infp("Salut, bine ai venit pe canal") is None
    assert parse_infp("") is None
    assert parse_infp(None) is None


def test_virgula_zecimala_si_fara_adancime():
    q = parse_infp("2026-11-18 03:10:00 UTC Mw=4,6 LAT=44,5 LON=26,1")
    assert q is not None
    assert (q.magnitude, q.latitude, q.longitude, q.depth_km) == (4.6, 44.5, 26.1, 0.0)
    assert q.region is None


def test_fara_ora_foloseste_momentul_primirii():
    acum = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    q = parse_infp("Mw=3.1 LAT=45.0 LON=26.0", now=acum)
    assert q is not None and q.time == acum


def test_coordonate_imposibile_sunt_respinse():
    assert parse_infp("Mw=5 LAT=145 LON=26") is None
