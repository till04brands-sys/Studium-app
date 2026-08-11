"""Die eine Stelle, an der Pfade und Ports stehen.

Gelesen wird ``Planer/Sync/app-config.json`` **im Vault** — nicht im
Repository. Damit liegt keine Angabe über Tills Rechner im öffentlichen Teil,
und die Konfiguration wandert automatisch mit der Sicherung des Vaults mit.

Henne und Ei: In der Datei steht, wo der Vault liegt — gefunden werden muss sie
also vorher. Deshalb die Kandidatenliste unten, mit Umgebungsvariable als
Vorfahrt für abweichende Rechner.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

UMGEBUNGSVARIABLE = "MEDIZIN_STUDIUM_KONFIG"

_KANDIDATEN = [
    "~/Documents/2.Brain/Tills 2.Gehirn/Planer/Sync/app-config.json",
    "~/Documents/2.Brain/Planer/Sync/app-config.json",
]


class KonfigFehler(Exception):
    """Die Konfiguration fehlt oder ist unbrauchbar."""


def konfig_pfad() -> Path:
    gesetzt = os.environ.get(UMGEBUNGSVARIABLE)
    if gesetzt:
        pfad = Path(gesetzt).expanduser()
        if not pfad.exists():
            raise KonfigFehler(f"{UMGEBUNGSVARIABLE} zeigt auf {pfad} — dort ist nichts")
        return pfad
    for kandidat in _KANDIDATEN:
        pfad = Path(kandidat).expanduser()
        if pfad.exists():
            return pfad
    raise KonfigFehler(
        "app-config.json nicht gefunden. Gesucht wurde in:\n  "
        + "\n  ".join(_KANDIDATEN)
        + f"\nAbhilfe: {UMGEBUNGSVARIABLE} auf die Datei setzen."
    )


@lru_cache(maxsize=1)
def konfig() -> dict:
    pfad = konfig_pfad()
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except json.JSONDecodeError as fehler:
        raise KonfigFehler(f"{pfad} ist kein gültiges JSON: {fehler}") from fehler


def vault_wurzel() -> Path:
    wurzel = Path(konfig()["vault"]).expanduser()
    if not wurzel.exists():
        raise KonfigFehler(f"Vault-Pfad aus der Konfiguration existiert nicht: {wurzel}")
    return wurzel


def im_vault(relativ: str) -> Path:
    """Relativen Vault-Pfad aus der Konfiguration zu einem echten Pfad machen."""
    return vault_wurzel() / relativ


def dienst(name: str) -> dict:
    return konfig().get("dienste", {}).get(name, {})
