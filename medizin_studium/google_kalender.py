"""Google Calendar lesen.

Der Zugang ist **lesend**. Das ist keine vorläufige Sparsamkeit, sondern die
Aufgabenteilung aus ``CLAUDE.md`` §11: Was in Google entstehen soll, geht über
``Planer/Sync/Ausgang.jsonl`` und wird vorher bestätigt. Ein Programm, das
nebenbei in einen Kalender schreiben darf, den auch Menschen benutzen, löscht
irgendwann etwas, das niemand angeordnet hat.

Zwei Dinge, die hier leicht falsch laufen und deshalb ausdrücklich geregelt
sind:

- **Ganztägige Termine.** Google liefert ``start.date`` statt
  ``start.dateTime``, und ``end.date`` ist **exklusiv**. Ein Termin vom 3. bis
  4. hat ``end.date = 2026-08-05``. Ohne diese Kenntnis steht jeder ganztägige
  Termin einen Tag zu lang im Raster.
- **Serien.** Mit ``singleEvents=True`` löst Google die Wiederholungen selbst
  auf. Das ist für die Wochenansicht richtig; RRULE nachzubauen wäre unnötig
  und fehleranfällig.

Zugangsdaten liegen im **Vault**, nicht im Repository — der Vault geht nie zu
GitHub, das Repository schon.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable

from .konfig import dienst, im_vault
from .studium import Termin

# Nur lesen. Auch das Auflisten der Kalender steckt in diesem einen Bereich.
BEREICH_LESEND = "https://www.googleapis.com/auth/calendar.readonly"

# Termine mit diesem Präfix gehören zur Praxis (siehe Ben-Kontext).
PRAXIS_PRAEFIX = "[Praxis]"


class GoogleFehler(Exception):
    """Der Google-Zugang fehlt, ist abgelaufen oder wurde entzogen."""


# -- Pfade -------------------------------------------------------------------

def _pfad(schluessel: str, vorgabe: str) -> Path:
    return im_vault(dienst("google_calendar").get(schluessel, vorgabe))


def client_datei() -> Path:
    """Die von Google heruntergeladene ``client_secret``-Datei."""
    return _pfad("client", "Planer/Sync/gcal-client.json")


def zugang_datei() -> Path:
    """Der Zugang, den die Anmeldung erzeugt. Wird von uns geschrieben."""
    return _pfad("zugang", "Planer/Sync/gcal-zugang.json")


# -- Anmeldung ---------------------------------------------------------------

def _zugangsdaten(anmeldung_erlauben: bool):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    daten = None
    if zugang_datei().exists():
        daten = Credentials.from_authorized_user_file(
            str(zugang_datei()), [BEREICH_LESEND]
        )

    if daten and daten.valid:
        return daten

    if daten and daten.expired and daten.refresh_token:
        daten.refresh(Request())
        _zugang_sichern(daten)
        return daten

    if not anmeldung_erlauben:
        raise GoogleFehler(
            "Kein gültiger Google-Zugang. Einmalig anmelden mit:\n"
            "  .venv/bin/python -m medizin_studium.google_kalender anmelden"
        )

    if not client_datei().exists():
        raise GoogleFehler(
            f"Die Datei von Google fehlt: {client_datei()}\n"
            "Sie entsteht in der Google Cloud Console unter „Anmeldedaten“ →\n"
            "OAuth-Client-ID → Desktop-App → JSON herunterladen."
        )

    fluss = InstalledAppFlow.from_client_secrets_file(
        str(client_datei()), [BEREICH_LESEND]
    )
    daten = fluss.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message="Der Browser öffnet sich. Konto wählen, Zugriff erlauben.",
        success_message="Fertig. Das Fenster kann zu, der Rest läuft im Terminal.",
    )
    _zugang_sichern(daten)
    return daten


def _zugang_sichern(daten) -> None:
    ziel = zugang_datei()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(daten.to_json(), encoding="utf-8")
    ziel.chmod(0o600)


def verbindung(anmeldung_erlauben: bool = False):
    from googleapiclient.discovery import build

    return build(
        "calendar", "v3",
        credentials=_zugangsdaten(anmeldung_erlauben),
        cache_discovery=False,
    )


def angemeldet() -> bool:
    return zugang_datei().exists()


# -- Kalender ----------------------------------------------------------------

def kalender(verb=None) -> list[dict]:
    """Alle Kalender des Kontos — Grundlage für die Auswahl in der App."""
    verb = verb or verbindung()
    ergebnis, seite = [], None
    while True:
        antwort = verb.calendarList().list(pageToken=seite, showHidden=False).execute()
        for k in antwort.get("items", []):
            ergebnis.append({
                "id": k["id"],
                "name": k.get("summaryOverride") or k.get("summary") or k["id"],
                "primaer": bool(k.get("primary")),
                "farbe": k.get("backgroundColor"),
                "nur_lesen": k.get("accessRole") in ("reader", "freeBusyReader"),
            })
        seite = antwort.get("nextPageToken")
        if not seite:
            break
    ergebnis.sort(key=lambda k: (not k["primaer"], k["name"].lower()))
    return ergebnis


# -- Termine -----------------------------------------------------------------

def _bereich(kalender_id: str, titel: str) -> str:
    if titel.startswith(PRAXIS_PRAEFIX):
        return "business"
    zuordnung = dienst("google_calendar").get("bereiche", {})
    return zuordnung.get(kalender_id, "extern")


def _zeitpunkt(wert: str) -> datetime:
    """``2026-10-05T08:15:00+02:00`` oder ``…Z`` in einen Zeitpunkt.

    Das ``Z`` ist der Grund für diese Funktion: ``fromisoformat`` versteht es
    vor Python 3.11 nicht, und Google liefert es für Kalender in UTC.
    """
    return datetime.fromisoformat(wert.replace("Z", "+00:00")).astimezone()


def _in_termine(eintrag: dict, kalender_id: str, von: date, bis: date) -> list[Termin]:
    """Einen Google-Eintrag in ein oder mehrere Tagesobjekte übersetzen."""
    if eintrag.get("status") == "cancelled":
        return []

    titel = (eintrag.get("summary") or "(ohne Titel)").strip()
    start, ende = eintrag.get("start", {}), eintrag.get("end", {})
    gemeinsam = dict(
        titel=titel.removeprefix(PRAXIS_PRAEFIX).strip() or titel,
        id="gcal:" + eintrag["id"],
        fach=None,
        ort=(eintrag.get("location") or "").strip() or None,
        art="google",
        bereich=_bereich(kalender_id, titel),
        status="vorlaeufig" if eintrag.get("status") == "tentative" else "geplant",
        quelle="google",
    )

    if "date" in start:
        # Ganztägig. end.date ist exklusiv — der letzte echte Tag ist einer davor.
        erster = date.fromisoformat(start["date"])
        letzter = date.fromisoformat(ende["date"]) - timedelta(days=1)
        tage, lauf = [], max(erster, von)
        while lauf <= min(letzter, bis):
            tage.append(Termin(tag=lauf, von=None, bis=None, **gemeinsam))
            lauf += timedelta(days=1)
        return tage

    beginn = _zeitpunkt(start["dateTime"])
    schluss = _zeitpunkt(ende["dateTime"])
    if beginn.date() != schluss.date():
        # Über Mitternacht: als ein Termin am Starttag führen, Ende offen lassen.
        return [Termin(tag=beginn.date(), von=beginn.strftime("%H:%M"), bis=None,
                       notiz=f"endet {schluss:%d.%m. %H:%M}", **gemeinsam)]
    return [Termin(tag=beginn.date(), von=beginn.strftime("%H:%M"),
                   bis=schluss.strftime("%H:%M"), **gemeinsam)]


def termine(
    von: date,
    bis: date,
    kalender_ids: Iterable[str] | None = None,
    verb=None,
) -> list[Termin]:
    """Alle Termine zwischen ``von`` und ``bis`` — beide Tage eingeschlossen."""
    verb = verb or verbindung()
    if kalender_ids is None:
        gewaehlt = dienst("google_calendar").get("kalender")
        kalender_ids = gewaehlt or [k["id"] for k in kalender(verb)]

    zeitmin = datetime.combine(von, time.min).astimezone().isoformat()
    zeitmax = datetime.combine(bis + timedelta(days=1), time.min).astimezone().isoformat()

    from googleapiclient.errors import HttpError

    ergebnis: list[Termin] = []
    for kid in kalender_ids:
        seite = None
        while True:
            try:
                antwort = verb.events().list(
                    calendarId=kid,
                    timeMin=zeitmin,
                    timeMax=zeitmax,
                    singleEvents=True,      # Serien löst Google auf, nicht wir
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=seite,
                ).execute()
            except HttpError as fehler:
                # Ein Kalender, den es nicht mehr gibt, darf nicht die ganze
                # Woche leeren. Der Rest wird geliefert, dieser fehlt sichtbar.
                if fehler.resp.status in (403, 404):
                    ergebnis.append(Termin(
                        titel=f"Kalender nicht lesbar: {kid}", tag=von, von=None,
                        bis=None, id=None, fach=None, ort=None, art="fehler",
                        bereich="extern", status="fehler", quelle="google",
                    ))
                    break
                raise
            for eintrag in antwort.get("items", []):
                ergebnis.extend(_in_termine(eintrag, kid, von, bis))
            seite = antwort.get("nextPageToken")
            if not seite:
                break

    ergebnis.sort(key=lambda t: (t.tag, t.von or "00:00"))
    return ergebnis


# -- Kommandozeile -----------------------------------------------------------

def _main(argv: list[str]) -> int:
    befehl = argv[1] if len(argv) > 1 else "pruefen"

    if befehl == "anmelden":
        verb = verbindung(anmeldung_erlauben=True)
        liste = kalender(verb)
        print(f"Angemeldet. Zugang liegt in {zugang_datei()}")
        print(f"{len(liste)} Kalender gefunden:")
        for k in liste:
            print(f"  {'*' if k['primaer'] else ' '} {k['name']}   [{k['id']}]")
        return 0

    if befehl == "kalender":
        for k in kalender():
            print(f"{'*' if k['primaer'] else ' '} {k['name']}   [{k['id']}]")
        return 0

    if befehl == "woche":
        heute = date.today()
        montag = heute - timedelta(days=heute.weekday())
        gefunden = termine(montag, montag + timedelta(days=6))
        if not gefunden:
            print("Diese Woche steht nichts in Google.")
        for t in gefunden:
            zeit = f"{t.von}–{t.bis}" if t.von and t.bis else (t.von or "ganztägig")
            print(f"{t.tag:%a %d.%m.}  {zeit:>12}  {t.titel}  ({t.bereich})")
        return 0

    if befehl == "pruefen":
        print(f"Konfiguration: {client_datei().parent}")
        print(f"  Datei von Google: {'da' if client_datei().exists() else 'FEHLT'}")
        print(f"  Zugang:           {'da' if zugang_datei().exists() else 'fehlt noch'}")
        return 0 if client_datei().exists() else 1

    print(__doc__)
    print("Befehle: anmelden | kalender | woche | pruefen")
    return 2


if __name__ == "__main__":
    import sys
    try:
        raise SystemExit(_main(sys.argv))
    except GoogleFehler as fehler:
        print(f"\n{fehler}\n")
        raise SystemExit(1)
