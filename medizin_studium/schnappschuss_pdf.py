"""Die Lese-Ansicht für unterwegs — als PDF statt als HTML.

**Warum der Wechsel.** Seit iOS 18.5 öffnet Safari keine lokale HTML-Datei
mehr per ``file://``, und die Schnellansicht (Quick Look) führt bei HTML kein
JavaScript aus — bei manchen Dateien verweigert sie die Vorschau ganz. Das ist
kein Fehler in dieser App, sondern eine dokumentierte, aktuelle
Plattform-Einschränkung. PDF hat dieses Problem nicht: Quick Look rendert es
zuverlässig, seit es Quick Look gibt.

**Warum kein HTML-zu-PDF-Konverter.** Auf diesem Rechner steht kein
Homebrew, und Werkzeuge wie ``wkhtmltopdf`` oder ``weasyprint`` bräuchten
entweder Homebrew oder schwere native Abhängigkeiten (Cairo, Pango), die sich
ohne Paketmanager nicht sauber installieren lassen. ``reportlab`` ist reines
Python plus vorgefertigte Wheels (nur ``pillow`` als Abhängigkeit) und baut
das PDF direkt aus denselben Daten, die auch die HTML-Fassung speist — kein
Browser, kein Rendern eines Zwischenschritts.

**Die Sicherheitsgarantie ist hier stärker als bei HTML, nicht schwächer.**
``schnappschuss.daten()`` baut die Nutzlast bereits feldweise auf; was nicht
hineingeschrieben wird, kann auch nicht ins PDF geraten. ``pruefen()`` scannt
zusätzlich den extrahierten Text als zweite Sicherung — falls der Payload sich
einmal ändert und dabei doch ein verbotenes Feld hineinrutscht.
"""

from __future__ import annotations

import io
import re
import time
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .schnappschuss import VERBOTEN, SchnappschussFehler
from .vault import Vault, atomar_schreiben_bytes

BREITE, HOEHE = A4
RAND = 16 * mm
NAVY = colors.HexColor("#1b3358")
TINTE = colors.HexColor("#17233a")
GRAU = colors.HexColor("#6f6a62")
GRAU_HELL = colors.HexColor("#8b857c")
LINIE = colors.HexColor("#ddd5c8")
WARN_HG = colors.HexColor("#fbf1de")
WARN_RAND = colors.HexColor("#d9a441")
ROT = colors.HexColor("#a33526")

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag"]


class _Seite:
    """Dünner Wrapper um ``canvas.Canvas``: merkt sich die y-Position und
    bricht die Seite um, statt dass jede Zeichenfunktion selbst rechnen muss.
    """

    def __init__(self, puffer: io.BytesIO) -> None:
        self.c = canvas.Canvas(puffer, pagesize=A4)
        self.y = HOEHE - RAND
        self._neue_seite_kopf = None

    def platz_sichern(self, hoehe: float) -> None:
        if self.y - hoehe < RAND:
            self.seitenumbruch()

    def seitenumbruch(self) -> None:
        self.c.showPage()
        self.y = HOEHE - RAND
        if self._neue_seite_kopf:
            self._neue_seite_kopf(self)

    def zeile(self, text: str, *, groesse: float = 10, farbe=TINTE,
              fett: bool = False, x: float | None = None,
              abstand_danach: float = 4) -> None:
        self.platz_sichern(groesse + abstand_danach)
        schrift = "Helvetica-Bold" if fett else "Helvetica"
        self.c.setFont(schrift, groesse)
        self.c.setFillColor(farbe)
        self.c.drawString(x if x is not None else RAND, self.y - groesse, text)
        self.y -= groesse + abstand_danach

    def trennlinie(self, abstand: float = 8) -> None:
        self.platz_sichern(abstand)
        self.c.setStrokeColor(LINIE)
        self.c.line(RAND, self.y, BREITE - RAND, self.y)
        self.y -= abstand


def _kuerzen(text: str, breite: float, schrift: str, groesse: float) -> str:
    if stringWidth(text, schrift, groesse) <= breite:
        return text
    while text and stringWidth(text + "…", schrift, groesse) > breite:
        text = text[:-1]
    return text + "…"


def _kasten_warn(s: _Seite, zeilen: list[str]) -> None:
    if not zeilen:
        return
    hoehe = 14 + 12 * len(zeilen)
    s.platz_sichern(hoehe + 8)
    s.c.setFillColor(WARN_HG)
    s.c.setStrokeColor(WARN_RAND)
    s.c.roundRect(RAND, s.y - hoehe, BREITE - 2 * RAND, hoehe, 3, fill=1, stroke=1)
    y = s.y - 14
    s.c.setFont("Helvetica", 8.5)
    s.c.setFillColor(TINTE)
    for zeile in zeilen:
        s.c.drawString(RAND + 8, y, zeile)
        y -= 12
    s.y -= hoehe + 10


def _kopf(s: _Seite, d: dict) -> None:
    s.zeile("Studium — unterwegs", groesse=17, fett=True, farbe=NAVY, abstand_danach=3)
    s.zeile(f"Stand {d['erzeugt']} · nur Lesen", groesse=8.5, farbe=GRAU_HELL, abstand_danach=10)

    b = d["block"]
    if b.get("name"):
        unter = f"Woche {b['woche']} von {b['wochen_gesamt']} · {b['phase']}"
        if b.get("platzhalter"):
            unter += " · nicht amtlich"
        s.zeile(b["name"], groesse=13, fett=True, abstand_danach=2)
        s.zeile(unter, groesse=9, farbe=GRAU, abstand_danach=8)
    else:
        s.zeile("Kein Themenblock erfasst", groesse=13, fett=True, abstand_danach=8)

    tage = b.get("tage_bis_klausur")
    if tage is not None:
        s.zeile(f"Blockklausur in {tage} Tagen", groesse=10.5, fett=True, farbe=NAVY,
                abstand_danach=8)

    s.trennlinie()


def _woche(s: _Seite, d: dict) -> None:
    s.zeile("DIESE WOCHE", groesse=8.5, fett=True, farbe=GRAU, abstand_danach=6)
    irgendwas = any(t["eintraege"] for t in d["woche"])
    if not irgendwas:
        s.zeile(f"Keine Termine in den freigegebenen Bereichen "
                f"({', '.join(d['bereiche'])}) — nicht „nichts los“, "
                "sondern nichts erfasst.", groesse=9, farbe=GRAU, abstand_danach=10)
        return

    for tag in d["woche"]:
        if not tag["eintraege"]:
            continue
        tagdatum = date.fromisoformat(tag["iso"])
        heute = " · heute" if tag["iso"] == d["heute"] else ""
        s.zeile(f"{WOCHENTAGE[tagdatum.weekday()]} {tagdatum.day}.{tagdatum.month}.{heute}",
                groesse=10, fett=True, abstand_danach=3)
        for e in tag["eintraege"]:
            praefix = "▸" if not e["gestrichen"] else "▸ (abgesagt)"
            titel = e["titel"] + ("" if not e["gestrichen"] else "")
            farbe = GRAU_HELL if e["gestrichen"] else TINTE
            s.zeile(f"  {praefix} {e['zeit']}  {titel}", groesse=9, farbe=farbe,
                    abstand_danach=2)
        s.y -= 4
    s.trennlinie()


def _liste(s: _Seite, titel: str, zeilen: list[str], leer: str) -> None:
    s.zeile(titel, groesse=8.5, fett=True, farbe=GRAU, abstand_danach=6)
    if not zeilen:
        s.zeile(leer, groesse=9, farbe=GRAU, abstand_danach=8)
    else:
        for z in zeilen:
            s.zeile(f"  · {z}", groesse=9, abstand_danach=3)
        s.y -= 4
    s.trennlinie()


def bauen(d: dict) -> bytes:
    """Baut das PDF aus der Nutzlast von ``schnappschuss.daten()``."""
    puffer = io.BytesIO()
    s = _Seite(puffer)

    def kopfzeile_folgeseiten(seite: _Seite) -> None:
        seite.zeile(f"Studium — unterwegs · Stand {d['erzeugt']}", groesse=8,
                     farbe=GRAU_HELL, abstand_danach=8)

    s._neue_seite_kopf = kopfzeile_folgeseiten

    maengel = d.get("maengel") or []
    if maengel:
        _kasten_warn(s, [
            "Unvollständig — was daraus käme, ist ungelesen, nicht „nichts erfasst“:",
            *[f"  {m['datei']} ({m['grund']})" for m in maengel],
        ])

    _kopf(s, d)
    _woche(s, d)

    aufgaben = [
        f"{a['titel']}" + (f"  ({a['ueberfaellig']} T. über)" if a["ueberfaellig"] > 0 else "  (heute)")
        for a in d["aufgaben"]
    ]
    _liste(s, "HEUTE ZU TUN", aufgaben, "Nichts fällig.")

    fristen = [
        f"{f['titel']}  " + (f"in {f['tage']} Tagen" if f["tage"] is not None else "Datum unbekannt")
        for f in d["fristen"]
    ]
    _liste(s, "FRISTEN", fristen, "Keine Frist in Sichtweite.")

    a = d["anki"]
    s.zeile("ANKI FÄLLIG", groesse=8.5, fett=True, farbe=GRAU, abstand_danach=6)
    if a["stand"] == "ok":
        s.zeile(f"{a['gesamt']} Karten über {a['decks']} Decks", groesse=9, abstand_danach=8)
    else:
        text = "Anki läuft nicht" if a["stand"] == "aus" else "Anki antwortet, liefert aber nichts"
        s.zeile(f"{text} — Stand unbekannt, nicht null.", groesse=9, farbe=ROT, abstand_danach=8)

    s.trennlinie()
    s.zeile("Nur Lesen. Kein Abhaken, kein Anlegen.", groesse=7.5, farbe=GRAU_HELL, abstand_danach=2)
    s.zeile("Ohne Klausurergebnisse und ohne Anwesenheit — die stehen nur auf dem Rechner.",
            groesse=7.5, farbe=GRAU_HELL)

    s.c.save()
    return puffer.getvalue()


def _text_pruefen(pdf: bytes) -> None:
    """Zweite Sicherung: den sichtbaren Text nach dem gebauten PDF durchsuchen.

    ``daten()`` liefert die verbotenen Felder erst gar nicht mit — diese
    Prüfung greift also nur, falls sich das einmal ändert. PDF-Text lässt sich
    nicht mit derselben Regex wie bei HTML aus dem Binärformat lesen; hier
    reicht ein Blick in die reine Textschicht, die reportlab in jedem
    ``drawString`` hinterlässt.
    """
    from pypdf import PdfReader

    text = "\n".join(seite.extract_text() or "" for seite in PdfReader(io.BytesIO(pdf)).pages)
    for muster, was in VERBOTEN:
        treffer = re.search(muster, text, re.IGNORECASE)
        if treffer:
            raise SchnappschussFehler(
                f"Das PDF enthält {was} ({treffer.group(0)!r}). "
                "Nicht geschrieben — diese Daten dürfen die Seite nie verlassen."
            )


def einzeln_bauen(v: Vault, ziel: Path, heute: date | None = None) -> Path:
    from .schnappschuss import daten as _daten

    nutzlast = _daten(v, heute)
    pdf = bauen(nutzlast)
    _text_pruefen(pdf)
    ziel = Path(ziel).expanduser()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    # Ein neuer Dateiname in iCloud Drive ist für einen Moment noch nicht in
    # dessen Verwaltung aufgenommen; das abschließende Umbenennen scheitert
    # dann mit „Operation not permitted", obwohl die Rechte stimmen. Beim
    # zweiten Versuch geht es — dieselbe Eigenheit wie bei der HTML-Fassung
    # (schnappschuss.py), hier für einen neuen Dateinamen erneut aufgetreten.
    for versuch in (1, 2):
        try:
            atomar_schreiben_bytes(ziel, pdf)
            break
        except PermissionError:
            if versuch == 2:
                raise
            time.sleep(2)
    return ziel
