#!/usr/bin/env python3
"""Salveaza api_id/api_hash (de la https://my.telegram.org -> API development tools) ca valori implicite ale integrarii.

Se ruleaza o singura data, de persoana care publica/instaleaza integrarea. Valorile se scriu in
custom_components/infp_alerte/default_api.json (acces doar pentru tine). Dupa asta, utilizatorii nu mai tasteaza api_id si
api_hash: fluxul cere doar numarul de telefon si codul. api_hash se tasteaza ascuns si nu e afisat.
"""
import getpass
import json
import os
import sys
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "custom_components" / "infp_alerte" / "default_api.json"

api_id = input("api_id (numar): ").strip()
api_hash = getpass.getpass("api_hash (nu se vede cand scrii): ").strip()
if not api_id.isdigit() or len(api_hash) < 20:
    sys.exit("api_id sau api_hash arata gresit. Verifica valorile de pe my.telegram.org si reia.")
DEST.write_text(json.dumps({"api_id": int(api_id), "api_hash": api_hash}), encoding="utf-8")
os.chmod(DEST, 0o600)
print(f"Salvat in {DEST}. Gata.")
