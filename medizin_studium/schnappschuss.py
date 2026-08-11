"""Die Lese-Ansicht für unterwegs — und der veröffentlichte Schnappschuss.

Beides ist derselbe Inhalt, deshalb gibt es dafür genau eine Stelle. Was auf
dem Telefon steht, ist damit zwangsläufig dasselbe wie das, was hochgeladen
wird; zwei Erzeuger wären zwei Gelegenheiten, etwas Falsches zu veröffentlichen.

**Das Sicherheitsargument steht hier, nicht im Server.** Die Seite geht ins
offene Netz, geschützt nur durch Cloudflare Access. Deshalb:

- Die Nutzlast wird **aufgebaut, nicht gefiltert**. Es wird einzeln
  hingeschrieben, was mitkommt. Ein neues Feld in ``studium.zustand()`` landet
  dadurch nicht versehentlich im Netz, weil niemand daran gedacht hat, es
  auszuschließen.
- Danach läuft ``pruefen()`` noch einmal über das **fertige HTML** und sucht
  nach dem, was nie drinstehen darf. Findet es etwas, entsteht keine Datei.
- Klausurergebnisse und Fehltage sind ausdrücklich draußen (Entscheidung vom
  09.08.2026). An diesen beiden hängt die Prüfungszulassung; sie nützen
  unterwegs nichts und wären der teuerste Verlust.
- Termine kommen nur aus den freigegebenen Bereichen, standardmäßig allein
  ``studium``. Arbeitszeiten und Trainingspläne gehören niemandem sonst.
"""

from __future__ import annotations

import html
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from . import anki, studium
from .konfig import konfig
from .vault import Vault

WEB = Path(__file__).parent / "web"

# Was niemals in der veröffentlichten Seite auftauchen darf. Wird gegen das
# fertige HTML geprüft, nicht gegen die Absicht.
VERBOTEN = [
    (r"\bmax_punkte\b", "Prüfungsergebnisse"),
    (r"\bbestanden\b", "Prüfungsergebnisse"),
    (r"\bgefehlt\b", "Anwesenheit"),
    (r"\bentschuldigt\b", "Anwesenheit"),
    (r"\bFehltag", "Anwesenheit"),
    (r"\bPunktekonto\b", "Prüfungsergebnisse"),
]


class SchnappschussFehler(Exception):
    """Der Schnappschuss wurde nicht geschrieben — mit Begründung."""


def _einstellung() -> dict:
    return konfig().get("schnappschuss", {})


def _erlaubte_bereiche() -> list[str]:
    return _einstellung().get("bereiche") or ["studium"]


# ---------------------------------------------------------------------------
# Nutzlast — jedes Feld einzeln, keine Sammelübernahme
# ---------------------------------------------------------------------------

def daten(v: Vault, heute: date | None = None) -> dict:
    heute = heute or date.today()
    voll = studium.zustand(v, heute)
    erlaubt = set(_erlaubte_bereiche())
    montag = date.fromisoformat(voll["woche_ab"])

    tage = []
    for i in range(7):
        tag = montag + timedelta(days=i)
        eintraege = [
            {
                "zeit": (f"{t['von']}–{t['bis']}" if t["von"] and t["bis"]
                         else t["von"] or "ganztägig"),
                "titel": t["titel"],
                "gestrichen": t["status"] == "entfaellt",
            }
            for t in voll["termine"]
            if t["tag"] == tag.isoformat() and t["bereich"] in erlaubt
        ]
        tage.append({"iso": tag.isoformat(), "eintraege": eintraege})

    block = voll["block"] or {}
    ankistand = anki.faellig()

    return {
        "erzeugt": datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "heute": voll["heute"],
        "block": {
            "name": block.get("name"),
            "phase": block.get("phase"),
            "woche": block.get("woche"),
            "wochen_gesamt": block.get("wochen_gesamt"),
            "platzhalter": block.get("platzhalter", False),
            "tage_bis_klausur": block.get("tage_bis_klausur"),
            "tage_lehrbetrieb": block.get("tage_lehrbetrieb"),
            "tage_endspurt": block.get("tage_endspurt"),
        },
        "woche": tage,
        "aufgaben": [
            {"titel": a["titel"], "ueberfaellig": a["ueberfaellig"]}
            for a in voll["aufgaben"]
        ],
        "fristen": [
            {"titel": f["titel"], "tage": f["tage"]}
            for f in voll["fristen"] if f["sichtbar_auf_heute"]
        ],
        "anki": {
            "stand": ankistand["stand"],
            "gesamt": ankistand["gesamt"],
            "decks": len(ankistand["faecher"]),
        },
        "bereiche": sorted(erlaubt),
    }


# ---------------------------------------------------------------------------
# Darstellung
# ---------------------------------------------------------------------------

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag"]


def _e(wert) -> str:
    return html.escape("" if wert is None else str(wert))


def _kopf(d: dict) -> str:
    b = d["block"]
    if not b.get("name"):
        return '<h1>Kein Themenblock erfasst</h1>'
    unter = f'Woche {b["woche"]} von {b["wochen_gesamt"]} · {b["phase"]}'
    if b.get("platzhalter"):
        unter += " · nicht amtlich"
    return f'<h1>{_e(b["name"])}</h1>\n<p class="unter">{_e(unter)}</p>'


def _klausur(d: dict) -> str:
    b = d["block"]
    tage = b.get("tage_bis_klausur")
    if tage is None:
        return ('<section class="klausur"><div class="marke">BLOCKKLAUSUR</div>'
                '<p class="leer">Kein Termin erfasst — unbekannt, nicht „keiner“.</p></section>')
    teil = ""
    if b.get("tage_lehrbetrieb") or b.get("tage_endspurt"):
        teil = (f'<div class="teil">{b["tage_lehrbetrieb"]} Tage Lehrbetrieb, '
                f'danach {b["tage_endspurt"]} Tage Endspurt</div>')
    return (f'<section class="klausur"><div class="marke">BLOCKKLAUSUR</div>'
            f'<div class="zahlzeile"><span class="zahl">{tage}</span>'
            f'<span class="einheit">Tage</span></div>{teil}</section>')


def _woche(d: dict) -> str:
    hat = any(t["eintraege"] for t in d["woche"])
    if not hat:
        return ('<div class="leerkasten">Keine Termine in den freigegebenen '
                f'Bereichen ({", ".join(d["bereiche"])}) — nicht „nichts los“, '
                'sondern nichts erfasst.</div>')
    teile = []
    for t in d["woche"]:
        tag = date.fromisoformat(t["iso"])
        heute = " heute" if t["iso"] == d["heute"] else ""
        zeilen = "".join(
            f'<div class="zeile{" weg" if e["gestrichen"] else ""}">'
            f'<span class="zeit">{_e(e["zeit"])}</span>'
            f'<span class="titel">{_e(e["titel"])}</span></div>'
            for e in t["eintraege"]
        ) or '<div class="zeile leise">keine Termine</div>'
        teile.append(
            f'<div class="tag{heute}"><div class="tagkopf">'
            f'<span>{WOCHENTAGE[tag.weekday()]}</span>'
            f'<span class="datum">{tag.day}.{tag.month}.</span></div>{zeilen}</div>'
        )
    return "".join(teile)


def _liste(titel: str, zeilen: list[str], leer: str) -> str:
    inhalt = "".join(zeilen) if zeilen else f'<div class="leerkasten">{_e(leer)}</div>'
    return f'<div class="marke">{_e(titel)}</div>{inhalt}'


def html_bauen(d: dict) -> str:
    aufgaben = [
        f'<div class="zeile"><span class="punkt"></span>'
        f'<span class="titel">{_e(a["titel"])}</span>'
        f'<span class="meta{" spaet" if a["ueberfaellig"] > 0 else ""}">'
        f'{a["ueberfaellig"]} T. über</span></div>' if a["ueberfaellig"] > 0 else
        f'<div class="zeile"><span class="punkt"></span>'
        f'<span class="titel">{_e(a["titel"])}</span>'
        f'<span class="meta">heute</span></div>'
        for a in d["aufgaben"]
    ]
    fristen = [
        f'<div class="zeile"><span class="titel">{_e(f["titel"])}</span>'
        f'<span class="meta{" spaet" if f["tage"] is not None and f["tage"] <= 14 else ""}">'
        f'{"in " + str(f["tage"]) + " Tagen" if f["tage"] is not None else "Datum unbekannt"}'
        f'</span></div>'
        for f in d["fristen"]
    ]
    a = d["anki"]
    ankiblock = (
        f'<div class="kasten"><span class="zahl klein">{a["gesamt"]}</span>'
        f'<span class="einheit">Karten über {a["decks"]} Decks</span></div>'
        if a["stand"] == "ok" else
        f'<div class="kasten warn">'
        f'{"Anki läuft nicht" if a["stand"] == "aus" else "Anki antwortet, liefert aber nichts"}'
        f' — Stand unbekannt, nicht null.</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Studium — unterwegs</title>
<link rel="stylesheet" href="./schnappschuss.css">
</head>
<body>
<main>
  <div class="stand">Stand {_e(d["erzeugt"])} · nur Lesen</div>
  {_kopf(d)}
  {_klausur(d)}

  <div class="marke">DIESE WOCHE</div>
  <div class="woche">{_woche(d)}</div>

  {_liste("HEUTE ZU TUN", aufgaben, "Nichts fällig.")}
  {_liste("FRISTEN", fristen, "Keine Frist in Sichtweite.")}

  <div class="marke">ANKI FÄLLIG</div>
  {ankiblock}

  <footer>
    Nur Lesen. Kein Abhaken, kein Anlegen.<br>
    Ohne Klausurergebnisse und ohne Anwesenheit — die stehen nur auf dem Rechner.<br>
    Stand {_e(d["erzeugt"])}
  </footer>
</main>
</body>
</html>
"""


def pruefen(seite: str) -> None:
    """Letzte Sperre vor dem Schreiben. Findet sie etwas, entsteht keine Datei."""
    for muster, was in VERBOTEN:
        treffer = re.search(muster, seite, re.IGNORECASE)
        if treffer:
            raise SchnappschussFehler(
                f"Der Schnappschuss enthält {was} ({treffer.group(0)!r}). "
                "Nicht geschrieben — diese Daten dürfen die Seite nie verlassen."
            )


def bauen(v: Vault, ziel: Path, heute: date | None = None) -> Path:
    nutzlast = daten(v, heute)
    seite = html_bauen(nutzlast)
    pruefen(seite)

    ziel = Path(ziel).expanduser()
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "index.html").write_text(seite, encoding="utf-8")
    shutil.copyfile(WEB / "schnappschuss.css", ziel / "schnappschuss.css")
    # Schriften mit, sonst fällt die Seite unterwegs still auf system-ui zurück.
    schrift = ziel / "schrift"
    schrift.mkdir(exist_ok=True)
    for datei in (WEB / "schrift").glob("*.woff2"):
        shutil.copyfile(datei, schrift / datei.name)
    shutil.copyfile(WEB / "schriften.css", ziel / "schriften.css")
    return ziel


def _main(argv: list[str]) -> int:
    ziel = Path(argv[1]) if len(argv) > 1 else Path(
        _einstellung().get("ordner", "~/Documents/Studium-unterwegs")
    ).expanduser()
    v = Vault(konfig()["vault"])
    d = daten(v)
    try:
        pfad = bauen(v, ziel)
    except SchnappschussFehler as fehler:
        print(f"\nAbgebrochen: {fehler}\n")
        return 1
    termine = sum(len(t["eintraege"]) for t in d["woche"])
    print(f"Geschrieben nach {pfad}")
    print(f"  Bereiche:  {', '.join(d['bereiche'])}")
    print(f"  Termine:   {termine} · Aufgaben: {len(d['aufgaben'])} · Fristen: {len(d['fristen'])}")
    print(f"  Anki:      {d['anki']['stand']}")
    print("  Ohne Klausurergebnisse und ohne Anwesenheit — geprüft.")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv))
