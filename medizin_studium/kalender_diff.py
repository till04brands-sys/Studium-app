"""Was hat sich im Kalender seit gestern getan — die Grundlage für §12.

Der Morgen-Check soll melden, was **neu, verschoben oder abgesagt** ist, und
gerade nicht die volle Wochenliste. Dafür braucht es einen Vergleichspunkt.

**Der Vergleichspunkt ist ein Zeitstempel, kein Abbild.** Google weiß selbst,
was sich seit wann geändert hat; ein selbst gepflegtes Abbild des Kalenders
wäre eine zweite Wahrheit, die irgendwann von der ersten abweicht — und zwar
unbemerkt, weil ein Diff, der nichts meldet, wie ein ruhiger Tag aussieht.

Gespeichert wird deshalb nur eine Zeile: wann zuletzt geschaut wurde.

**Ein gelöschter Termin hat bei Google keinen Titel mehr.** Zurück kommt die
Kennung und ``status: cancelled``. Den Namen holt dieses Modul aus
``Kalender.md``, wo jeder gespiegelte Google-Termin mit ``[gcal:: …]`` steht.
Der Vault erinnert sich, Google nicht — das ist einer der Gründe, warum
gespiegelt wird.

Aufruf::

    python3 -m medizin_studium.kalender_diff          # zeigen
    python3 -m medizin_studium.kalender_diff --merken # zeigen und Stand setzen
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .konfig import im_vault, konfig
from .vault import Vault, atomar_schreiben

# Wie weit nach vorn geschaut wird. Eine Änderung an einem Termin in vier
# Monaten ist morgens keine Nachricht; sie wird es, wenn sie näher rückt.
FENSTER_TAGE = 28

# Beim allerersten Lauf gibt es keinen Vergleichspunkt. Dann wird ausdrücklich
# kein Diff behauptet - sonst meldete der erste Morgen-Check den gesamten
# Kalender als "neu", und das ist die unbrauchbarste aller Meldungen.
STAND_DATEI = "Planer/Sync/Basis/kalender-stand.json"


class DiffFehler(Exception):
    """Der Vergleich kam nicht zustande — mit Begründung."""


def stand_datei() -> Path:
    return im_vault(STAND_DATEI)


def letzter_stand() -> datetime | None:
    pfad = stand_datei()
    if not pfad.exists():
        return None
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8")).get("zuletzt")
    except json.JSONDecodeError as fehler:
        raise DiffFehler(f"{pfad} ist kein gültiges JSON: {fehler}") from fehler
    if not roh:
        return None
    return datetime.fromisoformat(roh)


def stand_setzen(zeitpunkt: datetime) -> None:
    pfad = stand_datei()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    atomar_schreiben(pfad, json.dumps({
        "_hinweis": "Nur Maschine. Wann zuletzt nach Kalenderaenderungen "
                    "geschaut wurde (§12). Kein Abbild des Kalenders - Google "
                    "beantwortet 'was hat sich seit X geaendert' selbst.",
        "zuletzt": zeitpunkt.astimezone().isoformat(),
    }, ensure_ascii=False, indent=2) + "\n")


def titel_aus_vault(v: Vault) -> dict[str, str]:
    """``gcal``-Kennung → Titel, aus ``Kalender.md``.

    Für abgesagte Termine die einzige Quelle: Google gibt den Namen mit der
    Löschung her.
    """
    namen: dict[str, str] = {}
    # ``konfig()`` liefert den Pfad ab Vault-Wurzel („Planer/Kalender.md"),
    # ``Vault.datei()`` hängt „Planer/" selbst davor. Beides zusammen ergäbe
    # „Planer/Planer/…" — deshalb hier direkt ab der Wurzel.
    for eintrag in v.eintraege(im_vault(konfig()["gemeinsam"]["kalender"])):
        kennung = eintrag.wert("gcal")
        if kennung:
            namen["gcal:" + kennung] = eintrag.titel
    return namen


def diff(heute: date | None = None) -> dict:
    """Alles zusammen: Stand lesen, fragen, Titel ergänzen."""
    from . import google_kalender

    heute = heute or date.today()
    if not google_kalender.angemeldet():
        raise DiffFehler("Kein Google-Zugang eingerichtet.")

    seit = letzter_stand()
    jetzt = datetime.now().astimezone().replace(microsecond=0)
    if seit is None:
        return {"erster_lauf": True, "seit": None, "jetzt": jetzt, "aenderungen": []}

    try:
        roh = google_kalender.aenderungen(
            seit, heute, heute + timedelta(days=FENSTER_TAGE))
    except google_kalender.VergleichZuAlt as fehler:
        # Nicht als „keine Änderungen" durchgehen lassen. Wer drei Wochen
        # nicht hingesehen hat, braucht genau dann die volle Liste.
        return {"erster_lauf": False, "zu_alt": str(fehler), "seit": seit,
                "jetzt": jetzt, "aenderungen": []}

    v = Vault(konfig()["vault"])
    try:
        namen = titel_aus_vault(v)
    except Exception:
        # Ohne Kalender.md fehlen nur die Namen der Abgesagten, nicht der Diff.
        namen = {}

    for a in roh:
        if not a["titel"]:
            a["titel"] = namen.get(a["id"] or "")
    return {"erster_lauf": False, "zu_alt": None, "seit": seit,
            "jetzt": jetzt, "aenderungen": roh}


REIHENFOLGE = {"abgesagt": 0, "neu": 1, "geaendert": 2, "fehler": 3}
WORT = {"abgesagt": "abgesagt", "neu": "neu", "geaendert": "geändert",
        "fehler": "Fehler"}


def _zeile(a: dict) -> str:
    wann = a["tag"].strftime("%a %d.%m.") if a["tag"] else "ohne Datum"
    zeit = f" {a['von']}–{a['bis']}" if a["von"] and a["bis"] else (
        f" {a['von']}" if a["von"] else " ganztägig")
    titel = a["titel"] or "(Titel nur bei Google, dort bereits gelöscht)"
    return f"  {WORT[a['art']]:<9} {wann}{zeit}  {titel}  [{a['bereich']}]"


def _main(argv: list[str]) -> int:
    merken = "--merken" in argv
    try:
        ergebnis = diff()
    except DiffFehler as fehler:
        print(f"\n{fehler}\n")
        return 1

    if ergebnis["erster_lauf"]:
        print("\nKein Vergleichsstand vorhanden — dies ist der erste Lauf.")
        print("Es wird ausdrücklich kein Diff behauptet: Ohne Vergleichspunkt")
        print("wäre jeder vorhandene Termin „neu\", und das sagt nichts.")
        if merken:
            stand_setzen(ergebnis["jetzt"])
            print(f"\nStand gesetzt auf {ergebnis['jetzt']:%d.%m.%Y %H:%M}. "
                  "Ab dem nächsten Lauf gibt es einen Diff.")
        else:
            print("\nMit --merken den Startpunkt setzen.")
        return 0

    if ergebnis.get("zu_alt"):
        print(f"\n{ergebnis['zu_alt']}")
        print('\nAusdrücklich nicht „keine Änderungen“: Es ist unbekannt, was')
        print("in der Zwischenzeit passiert ist.")
        if merken:
            stand_setzen(ergebnis["jetzt"])
            print(f"\nStand neu gesetzt auf {ergebnis['jetzt']:%d.%m.%Y %H:%M}.")
        return 1

    liste = sorted(ergebnis["aenderungen"],
                   key=lambda a: (REIHENFOLGE.get(a["art"], 9),
                                  a["tag"] or date.max, a["von"] or ""))
    seit = ergebnis["seit"]
    print(f"\nSeit {seit:%d.%m.%Y %H:%M} · Fenster {FENSTER_TAGE} Tage")
    if not liste:
        print("  nichts verändert.")
    else:
        for a in liste:
            print(_zeile(a))
        print(f"\n  {len(liste)} Änderungen")

    if merken:
        stand_setzen(ergebnis["jetzt"])
        print(f"  Stand fortgeschrieben auf {ergebnis['jetzt']:%d.%m.%Y %H:%M}.")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
