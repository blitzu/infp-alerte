"""Deduplicarea: acelasi cutremur din surse diferite sau dupa repornire nu se anunta de doua ori."""
from datetime import UTC, datetime, timedelta

from custom_components.infp_alerte.parser import Quake
from custom_components.infp_alerte.quake_log import QuakeLog

T0 = datetime(2026, 11, 18, 0, 48, 51, tzinfo=UTC)


def quake(mag=5.3, dt=0, lat=45.6947, lon=26.5747, source="infp"):
    return Quake(mag, lat, lon, 141.0, T0 + timedelta(seconds=dt), source)


def test_cutremur_nou_se_anunta():
    log = QuakeLog()
    assert log.check(quake()) == (True, False)


def test_aceeasi_sursa_de_doua_ori_nu_se_repeta():
    log = QuakeLog()
    log.record(quake())
    assert log.check(quake()) == (False, False)


def test_emsc_dupa_infp_e_duplicat():
    """Cazul real: INFP 00:48:51 (45.6947, 26.5747), EMSC 00:48:56 (45.6952, 26.5495)."""
    log = QuakeLog()
    log.record(quake())
    emsc = quake(dt=5, lat=45.6952, lon=26.5495, source="emsc")
    assert log.check(emsc) == (False, False)


def test_revizuire_in_sus_realerteaza():
    log = QuakeLog()
    log.record(quake(mag=5.2))
    assert log.check(quake(mag=5.6, dt=4, source="emsc")) == (True, True)


def test_revizuire_mica_sau_in_jos_nu_realerteaza():
    log = QuakeLog()
    log.record(quake(mag=5.3))
    assert log.check(quake(mag=5.4, dt=3)) == (False, False)
    assert log.check(quake(mag=5.0, dt=3)) == (False, False)


def test_alt_cutremur_peste_cateva_minute_se_anunta():
    log = QuakeLog()
    log.record(quake())
    assert log.check(quake(dt=600)) == (True, False)


def test_alt_loc_in_acelasi_timp_se_anunta():
    log = QuakeLog()
    log.record(quake())
    assert log.check(quake(lat=47.5, lon=22.0)) == (True, False)


def test_seed_nu_anunta_dar_memoreaza():
    log = QuakeLog()
    log.seed([quake()])
    assert log.check(quake()) == (False, False)


def test_salvare_si_incarcare_pastreaza_evidenta():
    log = QuakeLog()
    log.record(quake())
    restaurat = QuakeLog.from_list(log.as_list())
    assert restaurat.check(quake()) == (False, False)


def test_incarcare_tolereaza_date_stricate():
    assert QuakeLog.from_list([{"gresit": 1}, None or {}]).entries == []
