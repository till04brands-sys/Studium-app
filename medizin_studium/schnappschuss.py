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
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import anki, studium
from .konfig import konfig
from .vault import Vault, atomar_schreiben

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

def google_termine(von: date, bis: date) -> tuple[list, str | None]:
    """Google-Termine für den Schnappschuss. Wirft nie, schweigt aber auch nicht.

    Ohne diesen Weg sähe die Ansicht für unterwegs **nie** einen Termin, der
    aus Google kommt. Solange dort nur Arbeit und Training stehen, fällt das
    nicht auf — sobald ein Kalender auf ``studium`` gemappt wird, fehlten die
    Vorlesungen stillschweigend. Genau die Sorte Fehler, die man in der
    Klausurwoche merkt.

    Deshalb reist ein gescheiterter Abruf als Grund mit zurück. Beim Bauen von
    Hand stünde die Fehlermeldung im Terminal; im nächtlichen Lauf sieht sie
    niemand, und übrig bliebe eine Seite, die aussieht wie „nichts los".
    """
    try:
        from . import google_kalender

        if not google_kalender.angemeldet():
            return [], None          # gar nicht eingerichtet ist kein Ausfall
        return google_kalender.termine(von, bis), None
    except Exception as fehler:
        return [], f"{type(fehler).__name__}: {fehler}"[:120]


def daten(v: Vault, heute: date | None = None, extern: list | None = None) -> dict:
    heute = heute or date.today()
    montag = heute - timedelta(days=heute.weekday())
    google_ausfall = None
    if extern is None:
        extern, google_ausfall = google_termine(montag, montag + timedelta(days=6))
    voll = studium.zustand(v, heute, extern=extern)
    erlaubt = set(_erlaubte_bereiche())

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
    maengel = list(voll.get("maengel", []))
    if google_ausfall:
        maengel.append({"datei": "Google Kalender", "grund": google_ausfall})

    jetzt = datetime.now().astimezone().replace(microsecond=0)
    return {
        "erzeugt": jetzt.isoformat(sep=" ")[:16],
        # Zweite Fassung mit Zeitzone, für die Alterrechnung im Browser. Die
        # lesbare oben taugt dafür nicht: Sie trägt keine Zone und ist auf
        # Minuten gekürzt. Engines parsen sie inzwischen zwar (in
        # JavaScriptCore nachgemessen), aber als *Ortszeit des Geräts* — und
        # das ist die falsche Annahme, sobald das Telefon woanders steht.
        "erzeugt_iso": jetzt.isoformat(),
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
        # Fehlende Dateien reisen mit. Unterwegs ist der Unterschied zwischen
        # „nichts erfasst" und „nicht gelesen" am wenigsten überprüfbar.
        "maengel": maengel,
    }


# ---------------------------------------------------------------------------
# Darstellung
# ---------------------------------------------------------------------------

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag"]


def _e(wert) -> str:
    return html.escape("" if wert is None else str(wert))


def _maengel(d: dict) -> str:
    """Fehlende Dateien stehen ganz oben, nicht im Fuß.

    Unterwegs kann man nicht nachsehen, ob wirklich nichts ansteht oder ob
    nur eine Datei nicht gelesen wurde. Also muss es dastehen, bevor man
    anfängt, der Seite zu glauben.
    """
    liste = d.get("maengel") or []
    if not liste:
        return ""
    zeilen = " · ".join(f'{_e(m["datei"])} ({_e(m["grund"])})' for m in liste)
    return (f'<div class="kasten warn">Unvollständig: {zeilen}. '
            "Was daraus käme, ist ungelesen — nicht „nichts erfasst“.</div>")


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
  <div class="stand" id="stand" data-stand="{_e(d["erzeugt"])}"
       data-erzeugt="{_e(d["erzeugt_iso"])}">Stand {_e(d["erzeugt"])} · nur Lesen</div>
  {_maengel(d)}
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
<script>{ALTER_SKRIPT}</script>
</body>
</html>
"""


# Ab hier gilt die Seite als überholt. Erneuert wird täglich; 36 Stunden
# heißen also, dass mindestens ein Lauf ausgefallen ist — Rechner zu, Fehler
# beim Bauen, Dienst nicht geladen. Was davon, weiß das Telefon nicht; dass
# etwas ist, muss es trotzdem sagen.
ALTERSGRENZE_STUNDEN = 36

# Rechnet beim Öffnen, nicht beim Bauen — zum Bauzeitpunkt ist das Alter immer
# null. Ohne das hier steht unterwegs ein Datum, das man selbst ins Verhältnis
# setzen müsste; mit ihm steht da, was man wissen will.
ALTER_SKRIPT = """
(function () {
  var el = document.getElementById("stand");
  if (!el) return;
  var erzeugt = new Date(el.getAttribute("data-erzeugt"));
  if (isNaN(erzeugt.getTime())) return;
  var stunden = (Date.now() - erzeugt.getTime()) / 3600000;
  if (stunden < 0) return;   // Uhr des Geraets geht vor: lieber nichts sagen
  var wie;
  // Abgerundet, nicht gerundet: 37 Stunden sind ein Tag und dreizehn Stunden,
  // nicht zwei Tage. Aufrunden liest sich bei einer Warnung dramatischer, ist
  // aber schlicht die falsche Zahl.
  if (stunden < 1) wie = "gerade eben";
  else if (stunden < 24) wie = "vor " + Math.floor(stunden) + " Std.";
  else {
    var tage = Math.floor(stunden / 24);
    wie = "vor " + tage + (tage === 1 ? " Tag" : " Tagen");
  }
  var alt = el.getAttribute("data-stand");
  el.textContent = "Stand " + alt + " \\u2014 " + wie + " \\u00b7 nur Lesen";
  if (stunden < %(grenze)d) return;
  var kasten = document.createElement("div");
  kasten.className = "kasten warn";
  kasten.textContent =
    "Diese Seite wurde " + wie + " erzeugt und seitdem nicht erneuert. "
    + "Termine, Aufgaben und Fristen stehen auf dem Stand von " + alt
    + " \\u2014 was seither dazukam, fehlt hier.";
  el.insertAdjacentElement("afterend", kasten);
})();
""" % {"grenze": ALTERSGRENZE_STUNDEN}


def pruefen(seite: str) -> None:
    """Letzte Sperre vor dem Schreiben. Findet sie etwas, entsteht keine Datei."""
    for muster, was in VERBOTEN:
        treffer = re.search(muster, seite, re.IGNORECASE)
        if treffer:
            raise SchnappschussFehler(
                f"Der Schnappschuss enthält {was} ({treffer.group(0)!r}). "
                "Nicht geschrieben — diese Daten dürfen die Seite nie verlassen."
            )


# Nur diese vier Schnitte werden eingebettet. Alle sieben wären 384 kB, und
# die Kursiv- und Halbfett-Varianten kommen auf dieser Seite nicht vor.
EINGEBETTET = [
    ("IBM Plex Sans", 400, "IBMPlexSans-400-latin.woff2"),
    ("IBM Plex Sans", 600, "IBMPlexSans-600-latin.woff2"),
    ("IBM Plex Mono", 400, "IBMPlexMono-400-latin.woff2"),
    ("Source Serif 4", 400, "SourceSerif4-400-latin.woff2"),
]


def _schriften_eingebettet() -> str:
    import base64

    teile = []
    for familie, gewicht, datei in EINGEBETTET:
        pfad = WEB / "schrift" / datei
        roh = base64.b64encode(pfad.read_bytes()).decode("ascii")
        teile.append(
            f"@font-face{{font-family:'{familie}';font-style:normal;"
            f"font-weight:{gewicht};font-display:swap;"
            f"src:url(data:font/woff2;base64,{roh}) format('woff2')}}"
        )
    return "\n".join(teile)


def einzeldatei(d: dict) -> str:
    """Eine Datei, die alles enthält — Stil und Schriften inbegriffen.

    Der Grund ist die Dateien-App auf dem iPhone: Sie zeigt eine HTML-Datei in
    der Vorschau an, lädt aber Nachbardateien nicht zuverlässig mit. Eine Seite
    aus mehreren Teilen sähe dort nackt aus.
    """
    stil = (WEB / "schnappschuss.css").read_text(encoding="utf-8")
    stil = stil.replace('@import url("./schriften.css");', "")
    seite = html_bauen(d)
    return seite.replace(
        '<link rel="stylesheet" href="./schnappschuss.css">',
        f"<style>\n{_schriften_eingebettet()}\n{stil}</style>",
    )


def einzeln_bauen(v: Vault, ziel: Path, heute: date | None = None) -> Path:
    nutzlast = daten(v, heute)
    seite = einzeldatei(nutzlast)
    pruefen(seite)
    ziel = Path(ziel).expanduser()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    # Atomar, weil diese Datei jetzt im Hintergrund erneuert wird. Ein Abbruch
    # mitten im Schreiben hinterließe eine halbe Seite — und die sähe unterwegs
    # aus wie eine Woche ohne Termine.
    #
    # Ein frisch angelegter Ordner in iCloud Drive ist für einen Moment noch
    # nicht in dessen Verwaltung aufgenommen; das Umbenennen scheitert dann mit
    # „Operation not permitted", obwohl die Rechte stimmen. Beim zweiten
    # Versuch geht es. Nachgemessen am 15.08.2026: genau ein Lauf betroffen,
    # alle folgenden sauber.
    for versuch in (1, 2):
        try:
            atomar_schreiben(ziel, seite)
            break
        except PermissionError:
            if versuch == 2:
                raise
            time.sleep(2)
    return ziel


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
    ordner_modus = "--ordner" in argv
    argv = [a for a in argv if a != "--ordner"]

    # Zeitstempel voran, weil diese Ausgabe im Hintergrundlauf in eine
    # Logdatei fällt. Ein Protokoll ohne Datum sagt nur, dass irgendwann
    # irgendetwas passiert ist.
    print(f"\n[{datetime.now().replace(microsecond=0)}] Schnappschuss")

    try:
        v = Vault(konfig()["vault"])
        d = daten(v)
    except Exception as fehler:
        print(f"Fehlgeschlagen beim Lesen: {type(fehler).__name__}: {fehler}")
        print("  Die vorhandene Datei bleibt stehen und altert sichtbar.")
        return 1

    # Die Rückfallpfade meiden ~/Documents und iCloud Drive. Beides ist auf
    # macOS geschützt: Aus dem Terminal gestartet käme man hin, im täglichen
    # Hintergrundlauf nicht — und dann scheiterte ausgerechnet der Fall, für
    # den ein Rückfallpfad da ist.
    vorgabe = _einstellung().get("datei", "~/Vault/Studium-unterwegs.html")
    ziel = Path(argv[1]) if len(argv) > 1 else Path(
        _einstellung().get("ordner", "~/Vault/Studium-unterwegs")
        if ordner_modus else vorgabe
    ).expanduser()

    try:
        pfad = bauen(v, ziel) if ordner_modus else einzeln_bauen(v, ziel)
    except SchnappschussFehler as fehler:
        print(f"Abgebrochen: {fehler}")
        print("  Die vorhandene Datei bleibt stehen und altert sichtbar.")
        return 1
    except Exception as fehler:
        print(f"Fehlgeschlagen: {type(fehler).__name__}: {fehler}")
        print("  Die vorhandene Datei bleibt stehen und altert sichtbar.")
        return 1

    termine = sum(len(t["eintraege"]) for t in d["woche"])
    groesse = pfad.stat().st_size if pfad.is_file() else sum(
        p.stat().st_size for p in pfad.rglob("*") if p.is_file())
    print(f"Geschrieben: {pfad}  ({groesse / 1024:.0f} kB)")
    print(f"  Bereiche:  {', '.join(d['bereiche'])}")
    print(f"  Termine:   {termine} · Aufgaben: {len(d['aufgaben'])} · Fristen: {len(d['fristen'])}")
    print(f"  Anki:      {d['anki']['stand']}")
    print("  Ohne Klausurergebnisse und ohne Anwesenheit — geprüft.")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv))
