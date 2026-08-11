"""Der lokale Server.

Bewusst nur Standardbibliothek. Ein Webframework brächte hier nichts außer
einer weiteren Abhängigkeit, die in zwei Jahren gepflegt werden will — die App
läuft auf einem Rechner, für einen Menschen, auf ``127.0.0.1``.

Drei Regeln:

- **Er rechnet nicht.** Alles, was die Oberfläche zeigt, kommt fertig aus
  ``studium.py``. Sonst gäbe es zwei Stellen, an denen „Rückstand" definiert
  ist, und irgendwann widersprechen sie sich.
- **Google darf ausfallen.** Kein Netz, abgelaufener Zugang, Google hat einen
  schlechten Tag: Der Vault-Teil wird trotzdem ausgeliefert, und im Feld
  ``google`` steht, was nicht ging. Eine leere Woche wegen eines Netzfehlers
  sähe aus wie eine freie Woche.
- **Er hört nur auf 127.0.0.1.** Im Vault stehen Blutwerte und Journaleinträge.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import anki, studium
from .konfig import konfig, konfig_pfad
from .vault import (
    Eintrag, Konflikt, Vault, feld_setzen, jsonl_ersetzen, jsonl_lesen,
    zeile_anhaengen,
)

WEB = Path(__file__).parent / "web"

# Google wird höchstens alle zwei Minuten gefragt. Beim Klicken durch die
# Wochen sonst ein Netzaufruf je Klick — langsam und ohne Not.
GOOGLE_FRISCH_SEKUNDEN = 120


class GoogleZwischenspeicher:
    def __init__(self) -> None:
        self._daten: dict[tuple[str, str], tuple[float, list]] = {}
        self._fehler: str | None = None
        self._sperre = threading.Lock()

    def termine(self, von: date, bis: date):
        """Termine plus Statusmeldung. Wirft nie."""
        from . import google_kalender

        schluessel = (von.isoformat(), bis.isoformat())
        with self._sperre:
            eintrag = self._daten.get(schluessel)
            if eintrag and time.time() - eintrag[0] < GOOGLE_FRISCH_SEKUNDEN:
                return eintrag[1], {"stand": "ok", "aus_speicher": True}

        if not google_kalender.angemeldet():
            return [], {"stand": "nicht_eingerichtet",
                        "text": "Google ist nicht verbunden."}
        try:
            liste = google_kalender.termine(von, bis)
        except Exception as fehler:            # Netz, Token, Kontingent — egal
            return [], {"stand": "fehler", "text": str(fehler)[:300]}

        with self._sperre:
            self._daten[schluessel] = (time.time(), liste)
        return liste, {"stand": "ok", "aus_speicher": False}


class Griff(BaseHTTPRequestHandler):
    server_version = "MedizinStudium"

    def __init__(self, vault: Vault, gcal: GoogleZwischenspeicher, *a, **k):
        self.vault = vault
        self.gcal = gcal
        super().__init__(*a, **k)

    # -- Antworten -----------------------------------------------------------
    def _json(self, nutzlast: dict, status: int = 200) -> None:
        roh = json.dumps(nutzlast, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(roh)

    def _datei(self, pfad: Path) -> None:
        # Kein Ausbruch aus web/ — auch nicht über ../ in der Anfrage.
        try:
            pfad = pfad.resolve()
            pfad.relative_to(WEB.resolve())
        except (ValueError, OSError):
            return self._json({"fehler": "verboten"}, 403)
        if not pfad.is_file():
            return self._json({"fehler": "nicht gefunden"}, 404)

        roh = pfad.read_bytes()
        typ = mimetypes.guess_type(pfad.name)[0] or "application/octet-stream"
        if typ.startswith("text/") or typ.endswith(("javascript", "json")):
            typ += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(roh)))
        # Schriften ändern sich nie, alles andere bei jeder Änderung am Code.
        self.send_header("Cache-Control",
                         "max-age=31536000" if pfad.suffix == ".woff2" else "no-store")
        self.end_headers()
        self.wfile.write(roh)

    # -- Routen --------------------------------------------------------------
    def do_GET(self) -> None:
        weg = urlparse(self.path)
        pfad, abfrage = weg.path, parse_qs(weg.query)
        try:
            if pfad == "/api/zustand":
                return self._json(self._zustand(abfrage))
            if pfad == "/api/block":
                self.vault.vergessen()
                return self._json(studium.block_zustand(self.vault, self._tag(abfrage)))
            if pfad == "/api/orga":
                self.vault.vergessen()
                return self._json(studium.orga_zustand(
                    self.vault, self._tag(abfrage), self._dienste()))
            if pfad == "/api/eingang":
                self.vault.vergessen()
                return self._json(studium.eingang_zustand(self.vault))
            if pfad == "/api/fach":
                self.vault.vergessen()
                kennung = (abfrage.get("id") or [""])[0]
                detail = studium.fach_detail(self.vault, kennung, self._tag(abfrage))
                if detail is None:
                    return self._json({"fehler": f"Kein Fach mit der ID {kennung!r}"}, 404)
                detail["anki"] = anki.faellig()
                return self._json(detail)
            if pfad == "/api/einstellungen":
                return self._json(self._einstellungen())
            if pfad == "/api/kalender":
                return self._json(self._kalender())
            if pfad in ("/", "/index.html"):
                return self._datei(WEB / "index.html")
            return self._datei(WEB / pfad.lstrip("/"))
        except Exception:
            traceback.print_exc()
            self._json({"fehler": "Serverfehler", "spur": traceback.format_exc()[-800:]}, 500)

    def do_POST(self) -> None:
        weg = urlparse(self.path)
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
            koerper = json.loads(self.rfile.read(laenge) or b"{}")
            if weg.path == "/api/aufgabe":
                return self._json(self._aufgabe_setzen(koerper))
            if weg.path == "/api/vorschlag":
                return self._json(self._vorschlag_entscheiden(koerper))
            self._json({"fehler": "unbekannter Weg"}, 404)
        except Konflikt as fehler:
            # Kein Serverfehler, sondern der Normalfall bei drei Schreibern.
            self._json({"fehler": "konflikt", "text": str(fehler)}, 409)
        except Exception:
            traceback.print_exc()
            self._json({"fehler": "Serverfehler", "spur": traceback.format_exc()[-800:]}, 500)

    # -- Fachliches ----------------------------------------------------------
    def _tag(self, abfrage: dict) -> date:
        wert = (abfrage.get("tag") or [None])[0]
        return date.fromisoformat(wert) if wert else date.today()

    def _zustand(self, abfrage: dict) -> dict:
        heute = self._tag(abfrage)
        montag = heute - timedelta(days=heute.weekday())
        self.vault.vergessen()          # Obsidian schreibt parallel

        extern, google = ([], {"stand": "aus"})
        if (abfrage.get("google") or ["ja"])[0] != "nein":
            extern, google = self.gcal.termine(montag, montag + timedelta(days=6))

        jetzt = datetime.now() if heute == date.today() else datetime.combine(heute, datetime.min.time())
        antwort = studium.zustand(self.vault, heute, jetzt=jetzt, extern=extern)
        antwort["google"] = google
        antwort["anki"] = anki.faellig()
        antwort["vault"] = str(self.vault.wurzel)
        return antwort

    def _kalender(self) -> dict:
        from . import google_kalender

        if not google_kalender.angemeldet():
            return {"stand": "nicht_eingerichtet", "kalender": []}
        try:
            return {"stand": "ok", "kalender": google_kalender.kalender()}
        except Exception as fehler:
            return {"stand": "fehler", "text": str(fehler)[:300], "kalender": []}

    def _aufgabe_setzen(self, koerper: dict) -> dict:
        kennung = koerper.get("id")
        erledigt = bool(koerper.get("erledigt"))
        if not kennung:
            return {"fehler": "id fehlt"}

        pfad = self.vault.datei("Aufgaben.md")
        self.vault.vergessen()
        treffer: Eintrag | None = next(
            (e for e in self.vault.aufgaben(bereich=None) if e.id == kennung), None
        )
        if treffer is None:
            return {"fehler": f"Aufgabe {kennung} steht nicht in Aufgaben.md"}

        # Die Prüfsumme aus der Anzeige, nicht die von eben. Sonst prüfte der
        # Server gegen seinen eigenen Lesevorgang und merkte nie, dass Obsidian
        # dieselbe Zeile geändert hat, während die Seite offen stand.
        gesehen = koerper.get("pruefsumme")
        if gesehen and gesehen != treffer.pruefsumme:
            raise Konflikt(
                f"Die Zeile zu {kennung} wurde geändert, seit die Seite sie geladen hat."
            )

        # Ein Datum, kein Haken: „wann" ist später mehr wert als „ob".
        neu = feld_setzen(
            pfad, treffer, "erledigt",
            date.today().isoformat() if erledigt else None,
        )
        self.vault.vergessen()
        return {"id": kennung, "erledigt": neu.wert("erledigt"), "zeile": neu.zeile}

    def _einstellungen(self) -> dict:
        """Was verbunden ist und wo die Daten liegen.

        Absichtlich nur Anzeige. Wer den Vault-Pfad oder den Port ändern will,
        ändert ``app-config.json`` — eine Datei, die auch Jarvis und die
        anderen Apps lesen. Ein zweiter Weg dorthin wäre eine zweite Wahrheit.
        """
        from . import google_kalender

        einstellung = konfig()
        gcal = einstellung.get("dienste", {}).get("google_calendar", {})
        ankistand = anki.faellig()
        kalender = self._kalender()
        return {
            "vault": str(self.vault.wurzel),
            "konfig": str(konfig_pfad()),
            "port": einstellung["apps"]["studium"]["port"],
            "google": {
                "stand": "ok" if google_kalender.angemeldet() else "nicht_eingerichtet",
                "modus": gcal.get("modus", "lesend"),
                "zugang": gcal.get("zugang"),
                "kalender": kalender.get("kalender", []),
                "bereiche": gcal.get("bereiche", {}),
            },
            "anki": {"stand": ankistand["stand"], "text": ankistand.get("text"),
                     "adresse": einstellung["dienste"]["anki"]["adresse"],
                     "deck_praefix": einstellung["dienste"]["anki"]["deck_praefix"]},
            "notion": {"stand": "nicht_eingerichtet",
                       "hinweis": einstellung["dienste"]["notion"].get("hinweis")},
            "schnappschuss": einstellung.get("schnappschuss", {}),
        }

    def _dienste(self) -> dict:
        from . import google_kalender

        return {
            "google": "ok" if google_kalender.angemeldet() else "aus",
            "anki": anki.faellig()["stand"],
        }

    def _vorschlag_entscheiden(self, koerper: dict) -> dict:
        """Der einzige Weg, auf dem die App etwas von sich aus anlegt.

        Und auch der nur, wenn Till geklickt hat. „Übernehmen" hängt genau die
        Zeile an, die in der Oberfläche stand — es wird nichts nachträglich
        zusammengebaut.
        """
        kennung = koerper.get("id")
        entscheidung = koerper.get("entscheidung")
        if entscheidung not in ("uebernehmen", "verwerfen", "spaeter"):
            return {"fehler": f"unbekannte Entscheidung: {entscheidung}"}

        pfad = self.vault.vorschlaege_datei()
        alle = jsonl_lesen(pfad)
        treffer = next((s for s in alle if s.get("id") == kennung), None)
        if treffer is None:
            return {"fehler": f"Vorschlag {kennung} steht nicht im Eingang"}
        if treffer.get("stand") not in (None, "offen", "spaeter"):
            return {"fehler": f"Vorschlag {kennung} ist schon {treffer['stand']}"}

        geschrieben = None
        if entscheidung == "uebernehmen":
            ziel = treffer.get("ziel") or {}
            datei, zeile = ziel.get("datei"), ziel.get("zeile")
            if not datei or not zeile:
                return {"fehler": "Der Vorschlag nennt keine Zieldatei oder keine Zeile"}
            # Kein Schreiben außerhalb des Vaults, auch nicht über ../ — und
            # die Absage nennt keine Pfade, die niemanden etwas angehen.
            volle = (self.vault.wurzel / datei).resolve()
            try:
                volle.relative_to(self.vault.wurzel.resolve())
            except ValueError:
                return {"fehler": f"Zieldatei liegt außerhalb des Vaults: {datei}"}
            if not volle.is_file():
                return {"fehler": f"Zieldatei gibt es nicht: {datei}"}
            zeile_anhaengen(volle, zeile)
            geschrieben = datei

        treffer["stand"] = {"uebernehmen": "uebernommen",
                            "verwerfen": "verworfen",
                            "spaeter": "spaeter"}[entscheidung]
        treffer["entschieden"] = date.today().isoformat()
        # Verworfenes bleibt stehen. Gelöscht schlüge derselbe Vorschlag beim
        # nächsten Abgleich wieder auf.
        jsonl_ersetzen(pfad, alle)
        self.vault.vergessen()
        return {"id": kennung, "stand": treffer["stand"], "geschrieben": geschrieben}

    def log_message(self, format: str, *args) -> None:
        if "/api/" in str(args[0] if args else ""):
            super().log_message(format, *args)


def starten(port: int | None = None, oeffnen: bool = True) -> None:
    einstellung = konfig()["apps"]["studium"]
    port = port or einstellung["port"]
    vault = Vault(konfig()["vault"])
    gcal = GoogleZwischenspeicher()

    dienst = ThreadingHTTPServer(("127.0.0.1", port), partial(Griff, vault, gcal))
    adresse = f"http://127.0.0.1:{port}/"
    print(f"{einstellung['name']} läuft auf {adresse}")
    print(f"Vault: {vault.wurzel}")
    print("Beenden mit Strg-C.")
    if oeffnen:
        import webbrowser
        threading.Timer(0.6, webbrowser.open, [adresse]).start()
    try:
        dienst.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")


if __name__ == "__main__":
    import sys
    starten(oeffnen="--kein-browser" not in sys.argv)
