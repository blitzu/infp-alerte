"""Configurare comuna teste."""
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Permite incarcarea integrarii din custom_components."""
    yield


@pytest.fixture(autouse=True)
def no_real_network():
    """Testele nu ating internetul: EMSC intoarce implicit lista goala (testele o suprascriu cand au nevoie)."""
    from unittest.mock import AsyncMock, patch

    with patch("custom_components.infp_alerte.hub.fetch_emsc", AsyncMock(return_value=[])):
        yield
