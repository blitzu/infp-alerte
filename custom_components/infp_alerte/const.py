"""Constante pentru Alerte seismice INFP + EMSC."""
from __future__ import annotations

DOMAIN = "infp_alerte"

CONF_API_ID = "api_id"
CONF_API_HASH = "api_hash"
CONF_SESSION = "session"
CONF_PHONE = "phone"
CONF_CODE = "code"
CONF_PASSWORD = "password"

CONF_USE_EMSC = "use_emsc"
CONF_MIN_MAGNITUDE = "min_magnitude"
CONF_MAX_DISTANCE = "max_distance_km"

DEFAULT_USE_EMSC = True
DEFAULT_MIN_MAGNITUDE = 3.0
DEFAULT_MAX_DISTANCE = 450  # km

EMSC_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"
EMSC_INTERVAL = 60  # secunde
EMSC_WINDOW_HOURS = 2

# Un cutremur mai vechi de atat nu mai declanseaza alerta (protectie la repornire/reconectare)
MAX_AGE_SECONDS = 3600
# Acelasi cutremur vazut din surse diferite: timp si loc apropiate
DEDUP_SECONDS = 120
DEDUP_KM = 150
# Se realerteaza daca magnitudinea creste cu cel putin atat (revizuire oficiala)
REVISION_STEP = 0.2

SIGNAL_QUAKE = f"{DOMAIN}_quake"
SIGNAL_STATUS = f"{DOMAIN}_status"
EVENT_TYPE_QUAKE = "cutremur"

# Mentiune ceruta de INCDFP: alertele provin de la INCDFP prin canalul Telegram "Alerta Cutremur".
ATTRIBUTION = (
    "Alerte de la INCDFP (Institutul National de Cercetare-Dezvoltare pentru Fizica Pamantului) prin canalul de Telegram "
    "\"Alerta Cutremur\"; rezerva: EMSC (seismicportal.eu)"
)
