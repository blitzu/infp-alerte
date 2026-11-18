"""Credentiale implicite pentru aplicatia Telegram a integrarii (optionale).

Telegram cere fiecarei aplicatii un api_id/api_hash. Daca exista fisierul `default_api.json` langa acest modul
({"api_id": 123, "api_hash": "..."}), utilizatorii nu mai trebuie sa-si obtina propriile valori, iar fluxul de
configurare cere doar numarul de telefon. Fara fisier, fluxul cere api_id si api_hash ca pana acum.
"""
from __future__ import annotations

import json
from pathlib import Path

_FILE = Path(__file__).with_name("default_api.json")


def load_default_api() -> tuple[int, str] | None:
    """(api_id, api_hash) sau None daca nu exista valori implicite valide."""
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        api_id, api_hash = int(data["api_id"]), str(data["api_hash"]).strip()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (api_id, api_hash) if api_id and len(api_hash) >= 20 else None
