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

**Das Seitenformat ist keine feste A4-Seite**, sondern eine Karte, deren Höhe
sich nach dem Inhalt richtet (siehe ``_zuschneiden``). Eine ruhige Woche hätte
sonst eine Din-A4-Seite mit 80 % Leerraum darunter ergeben — das sieht nicht
nach „nichts los" aus, sondern nach kaputt.
"""

from __future__ import annotations

import io
import re
import time
from datetime import date
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .schnappschuss import VERBOTEN, SchnappschussFehler
from .vault import Vault, atomar_schreiben_bytes

# Breite wie eine bequeme Lesespalte auf dem Telefon, nicht wie Druckpapier —
# die Seite wird nie gedruckt, nur in Quick Look angesehen.
BREITE = 420
HOEHE_ARBEITSFLAECHE = 4000  # großzügig; wird am Ende auf den Inhalt gekürzt
RAND = 18

# Palette aus dem Entwurf vom 10.08.2026 (medizin_studium/web/stil.css) —
# dieselben Werte, damit das PDF nicht wie ein zweites, fremdes Programm wirkt.
PAPIER = HexColor("#efebe4")
KARTE = HexColor("#fffdf9")
NAVY = HexColor("#1b3358")
TINTE = HexColor("#17233a")
GRAU = HexColor("#6f6a62")
GRAU_HELL = HexColor("#8b857c")
GRAU_ZART = HexColor("#a09a90")
LINIE = HexColor("#e2dcd2")
ROT = HexColor("#a33526")
GRUEN = HexColor("#3f6b47")
WARN_HG = HexColor("#fbf1de")
WARN_RAND = HexColor("#d9a441")
BAND_CREME = HexColor("#eae4d9")

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag"]


def _kuerzen(text: str, breite: float, schrift: str = "Helvetica", groesse: float = 9) -> str:
    """Auf eine Zeile kürzen, mit „…" statt hartem Abschneiden.

    ``drawString`` bricht nie um — ein zu langer Titel liefe sonst unsichtbar
    über den rechten Rand hinaus. Das fiel beim ersten Bau nicht auf, weil der
    Text in der PDF-Textschicht trotzdem vorhanden ist (``extract_text()``
    findet ihn), nur eben außerhalb der sichtbaren Seite.
    """
    if stringWidth(text, schrift, groesse) <= breite:
        return text
    while text and stringWidth(text + "…", schrift, groesse) > breite:
        text = text[:-1]
    return (text + "…") if text else "…"


class _Seite:
    """Zeichnet von oben nach unten, merkt sich die aktuelle y-Position."""

    def __init__(self, puffer: io.BytesIO) -> None:
        self.c = canvas.Canvas(puffer, pagesize=(BREITE, HOEHE_ARBEITSFLAECHE))
        self.hoehe = HOEHE_ARBEITSFLAECHE
        self.y = self.hoehe - RAND
        self.c.setFillColor(PAPIER)
        self.c.rect(0, 0, BREITE, self.hoehe, fill=1, stroke=0)

    def zeile(self, text: str, *, groesse: float = 9.5, farbe=TINTE,
              fett: bool = False, x: float | None = None,
              abstand_danach: float = 4, kuerzen_auf: float | None = None) -> None:
        schrift = "Helvetica-Bold" if fett else "Helvetica"
        x0 = x if x is not None else RAND + 12
        if kuerzen_auf is not None:
            text = _kuerzen(text, kuerzen_auf, schrift, groesse)
        self.c.setFont(schrift, groesse)
        self.c.setFillColor(farbe)
        self.c.drawString(x0, self.y - groesse, text)
        self.y -= groesse + abstand_danach

    def abstand(self, hoehe: float) -> None:
        self.y -= hoehe


def _karte_start(s: _Seite) -> float:
    """Merkt sich die obere Kante einer Karte; der Hintergrund wird erst
    gezeichnet, wenn die untere Kante bekannt ist (siehe ``_karte_ende``)."""
    return s.y


def _karte_ende(s: _Seite, oben: float, *, rand=LINIE, innenabstand_unten: float = 12) -> None:
    """Zieht den Kartenrahmen um einen bereits gezeichneten Abschnitt.

    Reportlab zeichnet in Aufrufreihenfolge übereinander — ein gefüllter
    Kartenhintergrund müsste also *vor* dem Text stehen, aber die Kartenhöhe
    ist erst bekannt, wenn der Text fertig ist. Deshalb nur ein Rahmen
    (Linie), keine Füllung: Der bewusst wärmere Seitenhintergrund (``PAPIER``)
    trägt die Kartenwirkung, der Rahmen zieht die Grenze.
    """
    unten = s.y - innenabstand_unten
    s.c.setStrokeColor(rand)
    s.c.setLineWidth(1)
    s.c.roundRect(RAND, unten, BREITE - 2 * RAND, oben - unten, 5, fill=0, stroke=1)
    s.y = unten - 14


def _kasten_warn(s: _Seite, zeilen: list[str]) -> None:
    """Warnkasten mit echter Füllung — als einziger Kasten im Voraus bekannter
    Höhe (feste Zeilenzahl), kann er vor dem Text gezeichnet werden."""
    if not zeilen:
        return
    hoehe = 14 + 12 * len(zeilen)
    oben = s.y
    s.c.setFillColor(WARN_HG)
    s.c.setStrokeColor(WARN_RAND)
    s.c.roundRect(RAND, oben - hoehe, BREITE - 2 * RAND, hoehe, 4, fill=1, stroke=1)
    s.y -= 10
    for i, zeile in enumerate(zeilen):
        s.zeile(zeile, groesse=8.5, farbe=TINTE, fett=(i == 0),
                kuerzen_auf=BREITE - 2 * RAND - 24, abstand_danach=3)
    s.y = oben - hoehe - 10


def _kopfband(s: _Seite, d: dict) -> None:
    hoehe = 58
    s.c.setFillColor(NAVY)
    s.c.roundRect(RAND, s.y - hoehe, BREITE - 2 * RAND, hoehe, 6, fill=1, stroke=0)
    s.c.setFillColor(HexColor("#f2ede3"))
    s.c.setFont("Helvetica-Bold", 15)
    s.c.drawString(RAND + 14, s.y - 22, "Studium — unterwegs")
    s.c.setFont("Helvetica", 8.5)
    s.c.setFillColor(BAND_CREME)
    s.c.drawString(RAND + 14, s.y - 38, f"Stand {d['erzeugt']} · nur Lesen")
    tage = (d["block"] or {}).get("tage_bis_klausur")
    if tage is not None:
        etikett = f"KLAUSUR IN {tage} T."
        breite_text = stringWidth(etikett, "Helvetica-Bold", 9.5)
        s.c.setFont("Helvetica-Bold", 9.5)
        s.c.setFillColor(HexColor("#f2ede3"))
        s.c.drawString(BREITE - RAND - 14 - breite_text, s.y - 30, etikett)
    s.y -= hoehe + 14


def _block(s: _Seite, d: dict) -> None:
    b = d["block"] or {}
    oben = _karte_start(s)
    s.y -= 12
    if b.get("name"):
        s.zeile(b["name"], groesse=13, fett=True, farbe=NAVY,
                kuerzen_auf=BREITE - 2 * RAND - 24, abstand_danach=3)
        unter = f"Woche {b['woche']} von {b['wochen_gesamt']} · {b['phase']}"
        if b.get("platzhalter"):
            unter += " · nicht amtlich"
        s.zeile(unter, groesse=8.5, farbe=GRAU, abstand_danach=2)
    else:
        s.zeile("Kein Themenblock erfasst", groesse=12, fett=True, abstand_danach=2)
    _karte_ende(s, oben)


def _woche(s: _Seite, d: dict) -> None:
    oben = _karte_start(s)
    s.y -= 12
    s.zeile("DIESE WOCHE", groesse=8, fett=True, farbe=GRAU_HELL, abstand_danach=8)

    irgendwas = any(t["eintraege"] for t in d["woche"])
    if not irgendwas:
        s.zeile(f"Keine Termine in den freigegebenen Bereichen "
                f"({', '.join(d['bereiche'])}) — nicht „nichts los“,",
                groesse=9, farbe=GRAU, kuerzen_auf=BREITE - 2 * RAND - 24, abstand_danach=2)
        s.zeile("sondern nichts erfasst.", groesse=9, farbe=GRAU, abstand_danach=4)
        _karte_ende(s, oben)
        return

    for tag in d["woche"]:
        if not tag["eintraege"]:
            continue
        tagdatum = date.fromisoformat(tag["iso"])
        heute = tag["iso"] == d["heute"]
        etikett = f"{WOCHENTAGE[tagdatum.weekday()]} {tagdatum.day}.{tagdatum.month}."
        if heute:
            s.c.setFillColor(NAVY)
            s.c.roundRect(RAND + 12, s.y - 13, stringWidth(etikett, "Helvetica-Bold", 9.5) + 12, 15, 3,
                          fill=1, stroke=0)
            s.zeile(etikett, groesse=9.5, fett=True, farbe=HexColor("#f2ede3"),
                    x=RAND + 18, abstand_danach=4)
        else:
            s.zeile(etikett, groesse=9.5, fett=True, abstand_danach=4)
        for e in tag["eintraege"]:
            gestrichen = e["gestrichen"]
            farbe = GRAU_ZART if gestrichen else TINTE
            zusatz = "  (abgesagt)" if gestrichen else ""
            s.zeile(f"{e['zeit']}", groesse=8.5, farbe=GRAU, x=RAND + 24, abstand_danach=0)
            s.zeile(f"{e['titel']}{zusatz}", groesse=9, farbe=farbe, x=RAND + 78,
                    kuerzen_auf=BREITE - RAND - 78 - RAND, abstand_danach=1)
            s.y -= 2
        s.y -= 6
    _karte_ende(s, oben)


def _liste_karte(s: _Seite, titel: str, zeilen: list[tuple[str, str, bool]], leer: str) -> None:
    """``zeilen``: Liste aus (Titel, Zusatz, ist_dringend)."""
    oben = _karte_start(s)
    s.y -= 12
    s.zeile(titel, groesse=8, fett=True, farbe=GRAU_HELL, abstand_danach=8)
    if not zeilen:
        s.zeile(leer, groesse=9, farbe=GRAU, abstand_danach=4)
    else:
        for haupt, zusatz, dringend in zeilen:
            farbe_zusatz = ROT if dringend else GRAU_HELL
            platz_zusatz = stringWidth(zusatz, "Helvetica", 8.5) + 8 if zusatz else 0
            # y VOR dem Zeichnen der Hauptzeile merken: ``s.zeile`` verschiebt
            # ``s.y`` am Ende schon auf die nächste Zeile. Wer erst danach
            # liest, zeichnet den Zusatz eine Zeile zu tief — genau das ist
            # beim ersten Bau passiert und erst beim Draufsehen aufgefallen,
            # weil die reine Textextraktion die Y-Position nicht prüft.
            baseline = s.y - 9.5
            s.zeile(haupt, groesse=9.5, x=RAND + 12,
                    kuerzen_auf=BREITE - 2 * RAND - 24 - platz_zusatz, abstand_danach=1)
            if zusatz:
                s.c.setFont("Helvetica", 8.5)
                s.c.setFillColor(farbe_zusatz)
                s.c.drawRightString(BREITE - RAND - 12, baseline, zusatz)
            s.y -= 3
    _karte_ende(s, oben)


def _zuschneiden(pdf_bytes: bytes, letzte_y: float) -> bytes:
    """Die Arbeitsfläche war absichtlich hoch genug für jeden Inhalt — jetzt
    wird auf das gekürzt, was tatsächlich gezeichnet wurde.

    Ohne das hätte eine ruhige Woche eine riesige leere Fläche unter dem
    Inhalt — das sieht nicht nach „wenig los" aus, sondern nach kaputter
    Seite. Reportlab kennt die Endhöhe erst, wenn alles gezeichnet ist,
    deshalb der Zuschnitt hinterher statt vorher.
    """
    leser = PdfReader(io.BytesIO(pdf_bytes))
    schreiber = PdfWriter()
    for i, seite in enumerate(leser.pages):
        if i == len(leser.pages) - 1:
            seite.mediabox.lower_left = (0, max(0, letzte_y - RAND))
        schreiber.add_page(seite)
    ausgabe = io.BytesIO()
    schreiber.write(ausgabe)
    return ausgabe.getvalue()


def bauen(d: dict) -> bytes:
    """Baut das PDF aus der Nutzlast von ``schnappschuss.daten()``."""
    puffer = io.BytesIO()
    s = _Seite(puffer)

    maengel = d.get("maengel") or []
    if maengel:
        _kasten_warn(s, [
            "Unvollständig — was daraus käme, ist ungelesen, nicht „nichts erfasst“:",
            *[f"{m['datei']} ({m['grund']})" for m in maengel],
        ])
        s.abstand(10)

    _kopfband(s, d)
    _block(s, d)
    s.abstand(10)
    _woche(s, d)
    s.abstand(10)

    aufgaben = [
        (a["titel"],
         f"{a['ueberfaellig']} T. über" if a["ueberfaellig"] > 0 else "heute",
         a["ueberfaellig"] > 0)
        for a in d["aufgaben"]
    ]
    _liste_karte(s, "HEUTE ZU TUN", aufgaben, "Nichts fällig.")
    s.abstand(10)

    fristen = [
        (f["titel"],
         f"in {f['tage']} T." if f["tage"] is not None else "Datum unbekannt",
         f["tage"] is not None and f["tage"] <= 14)
        for f in d["fristen"]
    ]
    _liste_karte(s, "FRISTEN", fristen, "Keine Frist in Sichtweite.")
    s.abstand(10)

    a = d["anki"]
    oben = _karte_start(s)
    s.y -= 12
    s.zeile("ANKI FÄLLIG", groesse=8, fett=True, farbe=GRAU_HELL, abstand_danach=8)
    if a["stand"] == "ok":
        s.zeile(f"{a['gesamt']} Karten über {a['decks']} Decks", groesse=9.5, abstand_danach=4)
    else:
        text = "Anki läuft nicht" if a["stand"] == "aus" else "Anki antwortet, liefert aber nichts"
        s.zeile(f"{text} — Stand unbekannt, nicht null.", groesse=9, farbe=ROT,
                kuerzen_auf=BREITE - 2 * RAND - 24, abstand_danach=4)
    _karte_ende(s, oben)
    s.abstand(4)

    s.zeile("Nur Lesen. Kein Abhaken, kein Anlegen.", groesse=7, farbe=GRAU_ZART, abstand_danach=1)
    s.zeile("Ohne Klausurergebnisse und ohne Anwesenheit — die stehen nur auf dem Rechner.",
            groesse=7, farbe=GRAU_ZART, kuerzen_auf=BREITE - 2 * RAND, abstand_danach=6)

    letzte_y = s.y
    if letzte_y < RAND:
        # Die Arbeitsfläche (HOEHE_ARBEITSFLAECHE) hat nicht gereicht — der
        # Extremtest mit 42 Terminen, 15 Aufgaben und 10 Fristen nutzte
        # weniger als die Hälfte davon, dieser Fall ist also nur ein
        # Sicherheitsnetz. Lieber ein klarer Fehler als eine Seite, deren
        # unterer Teil unsichtbar außerhalb des Blattes liegt.
        raise SchnappschussFehler(
            "Die Nutzlast ist größer, als die PDF-Vorlage vorsieht "
            f"(HOEHE_ARBEITSFLAECHE={HOEHE_ARBEITSFLAECHE} reicht nicht). "
            "Nicht geschrieben — sonst wäre der untere Teil der Seite "
            "unsichtbar statt nur abgeschnitten sichtbar."
        )
    s.c.showPage()
    s.c.save()
    return _zuschneiden(puffer.getvalue(), letzte_y)


def _text_pruefen(pdf: bytes) -> None:
    """Zweite Sicherung: den sichtbaren Text nach dem gebauten PDF durchsuchen.

    ``daten()`` liefert die verbotenen Felder erst gar nicht mit — diese
    Prüfung greift also nur, falls sich das einmal ändert.
    """
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
    # zweiten Versuch geht es — dieselbe Eigenheit wie bei der HTML-Fassung.
    for versuch in (1, 2):
        try:
            atomar_schreiben_bytes(ziel, pdf)
            break
        except PermissionError:
            if versuch == 2:
                raise
            time.sleep(2)
    return ziel
