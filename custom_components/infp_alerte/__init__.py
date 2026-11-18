"""Alerte seismice INFP + EMSC.

Citeste buletinele INFP de pe Telegram (cont propriu al utilizatorului, abonat la botul INFP de alerte) si, optional,
EMSC. Pentru fiecare cutremur relevant expune o entitate `event`, senzori si o stare de conexiune, iar un blueprint
transforma evenimentul in alerte pe trepte (notificari, sirena, lumini, boxe).
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .hub import Hub, TelegramAuthError

PLATFORMS = [Platform.EVENT, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

type InfpConfigEntry = ConfigEntry[Hub]

SERVICE_SIMULATE = "simulate_quake"
SERVICE_CHECK = "check_subscriptions"
SERVICE_ACK = "acknowledge"
SIMULATE_SCHEMA = vol.Schema(
    {
        vol.Required("magnitude"): vol.All(vol.Coerce(float), vol.Range(min=0, max=10)),
        vol.Optional("distance_km", default=100): vol.All(vol.Coerce(float), vol.Range(min=0, max=5000)),
        vol.Optional("depth_km", default=10): vol.All(vol.Coerce(float), vol.Range(min=0, max=700)),
        vol.Optional("region"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serviciul de test (inregistrat o singura data, indiferent de intrarile configurate)."""

    async def _simulate(call: ServiceCall) -> None:
        hubs = [e.runtime_data for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
        if not hubs:
            raise ServiceValidationError("Integrarea nu este incarcata")
        for hub in hubs:
            await hub.async_simulate(
                call.data["magnitude"], call.data["distance_km"], call.data["depth_km"], call.data.get("region")
            )

    async def _check(call: ServiceCall) -> ServiceResponse:
        """Listeaza canalele INFP candidate la care e abonat contul conectat (doar titluri, la cerere)."""
        hubs = [
            e.runtime_data
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED and e.runtime_data.telegram is not None
        ]
        if not hubs:
            raise ServiceValidationError("Nu exista un cont Telegram conectat")
        channels = await hubs[0].telegram.async_list_candidate_channels()
        return {"count": len(channels), "channels": channels}

    async def _ack(call: ServiceCall) -> None:
        """"Am vazut" pentru automatizari/tablouri de bord: opreste alerta si readuce casa cum era."""
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                await entry.runtime_data.engine.async_acknowledge()

    hass.services.async_register(DOMAIN, SERVICE_SIMULATE, _simulate, schema=SIMULATE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_ACK, _ack, schema=vol.Schema({}))
    hass.services.async_register(
        DOMAIN, SERVICE_CHECK, _check, schema=vol.Schema({}), supports_response=SupportsResponse.ONLY
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: InfpConfigEntry) -> bool:
    """Porneste sursele si entitatile."""
    hub = Hub(hass, entry)
    try:
        await hub.async_start()
    except TelegramAuthError as err:
        await hub.async_stop()
        raise ConfigEntryAuthFailed("Sesiunea Telegram nu mai e valida") from err
    except (OSError, TimeoutError) as err:
        await hub.async_stop()
        raise ConfigEntryNotReady(f"Telegram indisponibil: {err}") from err
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InfpConfigEntry) -> bool:
    """Opreste sursele si descarca entitatile."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
