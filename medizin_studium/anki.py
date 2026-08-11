"""Fällige Karten aus Anki holen.

Über AnkiConnect, also nur solange Anki offen ist. Genau deshalb gibt es hier
drei Zustände statt zwei: ``ok``, ``aus`` und ``fehler``. Läuft Anki nicht, ist
die Fälligkeit **unbekannt** — und die Oberfläche schreibt das hin, statt
„0 fällig" anzuzeigen. Null hieße „nachgesehen, es war nichts".

Deckschema ist ``Medizin::<Fach>``; Block und Thema stehen als Schlagwörter an
den Notizen. Andersherum (``TB1::<Fach>``) zerfiele die Fach-Achse, und die
zählt für die Ärztliche Zwischenprüfung.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .konfig import dienst

ZEITSCHRANKE = 2.0          # Anki antwortet lokal in Millisekunden oder gar nicht


def _ruf(adresse: str, aktion: str, **parameter):
    anfrage = json.dumps(
        {"action": aktion, "version": 6, "params": parameter}
    ).encode("utf-8")
    with urllib.request.urlopen(adresse, anfrage, timeout=ZEITSCHRANKE) as antwort:
        daten = json.loads(antwort.read())
    if daten.get("error"):
        raise RuntimeError(daten["error"])
    return daten["result"]


def faellig() -> dict:
    """Fällige Karten je Fach. Wirft nie — der Zustand steht im Ergebnis."""
    einstellung = dienst("anki")
    adresse = einstellung.get("adresse", "http://127.0.0.1:8765")
    praefix = einstellung.get("deck_praefix", "Medizin")

    try:
        decks = _ruf(adresse, "deckNames")
    except (urllib.error.URLError, OSError, TimeoutError):
        return {"stand": "aus", "gesamt": None, "faecher": [],
                "text": "Keine Verbindung zu AnkiConnect."}
    except Exception as fehler:
        return {"stand": "fehler", "gesamt": None, "faecher": [],
                "text": str(fehler)[:200]}

    meine = sorted(d for d in decks if d == praefix or d.startswith(praefix + "::"))
    if not meine:
        return {"stand": "leer", "gesamt": 0, "faecher": [],
                "text": f"Anki läuft, aber es gibt kein Deck unter „{praefix}“."}

    zeilen, gesamt = [], 0
    for deck in meine:
        if deck == praefix:
            continue
        try:
            karten = _ruf(adresse, "findCards", query=f'deck:"{deck}" is:due')
        except Exception:
            continue
        anzahl = len(karten)
        gesamt += anzahl
        zeilen.append({"fach": deck.split("::", 1)[1], "deck": deck, "n": anzahl})

    zeilen.sort(key=lambda z: (-z["n"], z["fach"]))
    return {"stand": "ok", "gesamt": gesamt, "faecher": zeilen}
