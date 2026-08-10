"""Aus den Vault-Zeilen das machen, was die Oberfläche zeigt.

Hier steht die Rechnerei — Rückstand, Takt, Wochenraster —, damit weder der
Server noch die Oberfläche etwas ableiten muss.

Zwei Regeln durchziehen die ganze Datei:

- **Kein Nenner, kein Balken.** Fehlt die Stoffliste, wird nicht null Prozent
  gemeldet, sondern ``None``. Die Oberfläche schreibt dann „Stoffliste fehlt".
  Ein leerer Balken läse sich wie Rückstand, obwohl nur eine Liste fehlt.
- **Vermutetes wird als vermutet ausgeliefert.** Alles unter ``Planer/Studium``
  trägt derzeit ``platzhalter: ja``; dieses Kennzeichen wandert bis in die
  Anzeige durch, statt unterwegs verloren zu gehen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .vault import Eintrag, Vault, liste_aus_frontmatter

STUFEN = ["priming", "notizen", "feynman", "loci", "anki"]
OPTIONALE_STUFEN = {"loci"}          # laut Lernsystem.md ausdrücklich freiwillig

WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

_ZEIT = re.compile(r"(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})")
_DATUM_ZEILE = re.compile(r"^\s*[-*]\s*(\d{4}-\d{2}-\d{2})\s*(.*)$")
_TAG_ZEILE = re.compile(r"^\s*[-*]\s*(Mo|Di|Mi|Do|Fr|Sa|So)\s+(.*)$")


def _datum(wert: str | None) -> date | None:
    if not wert:
        return None
    try:
        return date.fromisoformat(wert)
    except ValueError:
        return None


def _ja(wert: str | None) -> bool:
    return (wert or "").strip().lower() in {"ja", "true", "yes", "1"}


# ---------------------------------------------------------------------------
# Termine
# ---------------------------------------------------------------------------

@dataclass
class Termin:
    titel: str
    tag: date
    von: str | None
    bis: str | None
    id: str | None
    fach: str | None
    ort: str | None
    art: str | None
    bereich: str
    status: str
    quelle: str
    serie: str | None = None
    ersetzt: date | None = None
    platzhalter: bool = False
    notiz: str | None = None

    @property
    def ganztags(self) -> bool:
        return self.von is None


def _zeit_und_titel(rest: str) -> tuple[str | None, str | None, str]:
    treffer = _ZEIT.match(rest.strip())
    if not treffer:
        return None, None, rest.split("[")[0].strip()
    a, b, c, d = treffer.groups()
    titel = rest[treffer.end():].split("[")[0].strip()
    return f"{int(a):02d}:{b}", f"{int(c):02d}:{d}", titel


def termine_der_woche(v: Vault, montag: date) -> list[Termin]:
    """Einzeltermine und projizierte Stundenplan-Serien einer Woche.

    Die Reihenfolge ist wichtig: Erst die Serien projizieren, dann die
    Ausnahmen darüberlegen. Eine Ausnahme mit ``ersetzt`` streicht den
    Plantermin **dieses einen Tages** — ohne das Feld stünde die Vorlesung
    zweimal in der Woche.
    """
    sonntag = montag + timedelta(days=6)
    ergebnis: list[Termin] = []

    # 1) Einzeltermine aus Kalender.md
    ausnahmen: dict[tuple[str, date], Termin] = {}
    for e in v.termine():
        treffer = _DATUM_ZEILE.match(e.zeile.split("\n")[0])
        if not treffer:
            continue
        tag = _datum(treffer.group(1))
        if tag is None:
            continue
        von, bis, titel = _zeit_und_titel(treffer.group(2))
        t = Termin(
            titel=titel or e.titel,
            tag=tag,
            von=von,
            bis=bis,
            id=e.id,
            fach=e.wert("fach"),
            ort=e.wert("ort"),
            art=e.wert("art"),
            bereich=e.wert("bereich") or "studium",
            status=e.wert("status") or "geplant",
            quelle=e.wert("quelle") or "manuell",
            serie=e.wert("serie"),
            ersetzt=_datum(e.wert("ersetzt")),
            notiz=e.wert("notiz"),
        )
        if t.serie and t.ersetzt:
            ausnahmen[(t.serie, t.ersetzt)] = t
        if montag <= tag <= sonntag:
            ergebnis.append(t)

    # 2) Stundenplan-Serien auf die Woche projizieren
    for e in v.stundenplan():
        treffer = _TAG_ZEILE.match(e.zeile.split("\n")[0])
        if not treffer:
            continue
        tag = montag + timedelta(days=WOCHENTAGE.index(treffer.group(1)))
        ab, bis_ = _datum(e.wert("ab")), _datum(e.wert("bis"))
        if (ab and tag < ab) or (bis_ and tag > bis_):
            continue
        if not (montag <= tag <= sonntag):
            continue
        if e.id and (e.id, tag) in ausnahmen:
            gestrichen = ausnahmen[(e.id, tag)]
            von, bis, titel = _zeit_und_titel(treffer.group(2))
            # Der gestrichene Plantermin bleibt sichtbar — durchgestrichen.
            # Ein spurlos verschwundener Termin sieht aus wie ein Datenfehler.
            ergebnis.append(
                Termin(
                    titel=titel or e.titel, tag=tag, von=von, bis=bis, id=e.id,
                    fach=e.wert("fach"), ort=e.wert("ort"), art=e.wert("art"),
                    bereich=e.wert("bereich") or "studium",
                    status=gestrichen.status, quelle="plan", serie=e.id,
                )
            )
            continue
        von, bis, titel = _zeit_und_titel(treffer.group(2))
        ergebnis.append(
            Termin(
                titel=titel or e.titel, tag=tag, von=von, bis=bis, id=e.id,
                fach=e.wert("fach"), ort=e.wert("ort"), art=e.wert("art"),
                bereich=e.wert("bereich") or "studium",
                status="geplant", quelle="plan",
            )
        )

    ergebnis.sort(key=lambda t: (t.tag, t.von or "00:00"))
    return ergebnis


def online_ohne_slot(v: Vault) -> list[dict]:
    """Vorlesungen ohne feste Zeit. Sie gehören nicht ins Zeitraster."""
    offen = []
    for e in v.stundenplan():
        if e.wert("art") != "online":
            continue
        offen.append({
            "id": e.id, "titel": e.titel, "fach": e.wert("fach"),
            "dauer": e.zahl("dauer"), "bis": e.wert("bis"),
            "gesehen": e.wert("gesehen"),
        })
    offen.sort(key=lambda o: o["bis"] or "9999-12-31")
    return offen


# ---------------------------------------------------------------------------
# Lernstand
# ---------------------------------------------------------------------------

@dataclass
class Fachstand:
    id: str
    name: str
    vorwissen: str | None
    platzhalter: bool
    anki_deck: str | None
    themen_gesamt: int
    stufen: dict[str, int]
    rueckstand: int
    aeltestes_offen: dict | None
    tage_bis_klausur: int | None
    ohne_anki: int

    @property
    def hat_nenner(self) -> bool:
        """Gibt es überhaupt eine Stoffliste?"""
        return self.themen_gesamt > 0

    @property
    def takt(self) -> float | None:
        """Tage je offenem Thema. ``None``, wenn nicht berechenbar."""
        if not self.hat_nenner or self.tage_bis_klausur is None or self.ohne_anki == 0:
            return None
        return round(self.tage_bis_klausur / self.ohne_anki, 1)

    @property
    def ampel(self) -> str | None:
        t = self.takt
        if t is None:
            return None
        return "gruen" if t > 2 else "gelb" if t >= 1 else "rot"


def fachstand(v: Vault, heute: date | None = None) -> list[Fachstand]:
    heute = heute or date.today()
    themen = v.lernstand()
    bloecke = {b.get("id"): b for b in v.themenbloecke()}

    stand: list[Fachstand] = []
    for f in v.faecher():
        fid = f.get("id", "")
        meine = [t for t in themen if t.wert("fach") == fid]

        stufen = {s: sum(1 for t in meine if t.wert(s)) for s in STUFEN}

        # Rückstand: Vorlesung vorbei, aber keine Notizen. Das ist die einzige
        # Zahl, die wirklich sagt, ob man hinterherhängt — ein Prozentbalken
        # wächst mit dem Semester von allein mit.
        offen = [
            t for t in meine
            if (d := _datum(t.wert("termin"))) is not None
            and d <= heute and not t.wert("notizen")
        ]
        offen.sort(key=lambda t: t.wert("termin") or "")
        aeltestes = None
        if offen:
            d = _datum(offen[0].wert("termin"))
            aeltestes = {
                "titel": offen[0].titel,
                "quelle": offen[0].wert("quelle"),
                "termin": offen[0].wert("termin"),
                "tage": (heute - d).days if d else None,
            }

        klausur = _datum(f.get("klausur")) or next(
            (_datum(bloecke[b].get("klausur"))
             for b in liste_aus_frontmatter(f.get("bloecke")) if b in bloecke),
            None,
        )
        tage = (klausur - heute).days if klausur else None

        stand.append(Fachstand(
            id=fid,
            name=f.get("name", fid),
            vorwissen=f.get("vorwissen") or None,
            platzhalter=_ja(f.get("platzhalter")),
            anki_deck=f.get("anki_deck") or None,
            themen_gesamt=len(meine),
            stufen=stufen,
            rueckstand=len(offen),
            aeltestes_offen=aeltestes,
            tage_bis_klausur=tage,
            ohne_anki=sum(1 for t in meine if not t.wert("anki")),
        ))
    return stand


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------

def blockuhr(v: Vault, heute: date | None = None) -> dict | None:
    """Woche X von Y und die Phase. ``None``, wenn kein Block läuft."""
    heute = heute or date.today()
    for b in v.themenbloecke():
        beginn, ende = _datum(b.get("beginn")), _datum(b.get("ende"))
        klausur = _datum(b.get("klausur"))
        if not beginn or not ende:
            continue

        if heute < beginn:
            phase = "vor Beginn"
        elif heute <= ende:
            phase = "Lehrbetrieb"
        elif klausur and heute < klausur:
            phase = "Endspurt"
        elif klausur and heute == klausur:
            phase = "Klausur"
        else:
            phase = "Nachlauf"

        gesamt = (ende - beginn).days + 1
        vergangen = (heute - beginn).days
        return {
            "id": b.get("id"),
            "name": b.get("name"),
            "phase": phase,
            "tag": max(0, vergangen + 1),
            "tage_gesamt": gesamt,
            "woche": max(1, vergangen // 7 + 1),
            "wochen_gesamt": max(1, -(-gesamt // 7)),
            "klausur": b.get("klausur"),
            "tage_bis_klausur": (klausur - heute).days if klausur else None,
            # Ehrlicher als „51 Tage": wie viele davon wirklich nur Lernen sind.
            "tage_lehrbetrieb": max(0, (ende - heute).days) if heute <= ende else 0,
            "tage_endspurt": max(0, (klausur - ende).days) if klausur and klausur > ende else 0,
            "platzhalter": _ja(b.get("platzhalter")),
        }
    return None


# ---------------------------------------------------------------------------
# Aufgaben und Organisation
# ---------------------------------------------------------------------------

def aufgaben_heute(v: Vault, heute: date | None = None) -> list[dict]:
    """Fällig oder überfällig, nicht erledigt, nicht vertagt."""
    heute = heute or date.today()
    liste = []
    for e in v.aufgaben():
        if e.wert("erledigt"):
            continue
        wieder = _datum(e.wert("wieder"))
        if wieder and wieder > heute:
            continue
        faellig = _datum(e.wert("faellig"))
        if faellig is None or faellig > heute:
            continue
        liste.append({
            "id": e.id, "titel": e.titel, "fach": e.wert("fach"),
            "typ": e.wert("typ"), "stufe": e.wert("stufe"),
            "thema": e.wert("thema"), "orga": e.wert("orga"),
            "faellig": e.wert("faellig"), "dauer": e.zahl("dauer"),
            "ueberfaellig": (heute - faellig).days,
        })
    liste.sort(key=lambda a: (-a["ueberfaellig"], a["titel"]))
    return liste


def fristen(v: Vault, heute: date | None = None) -> list[dict]:
    """Organisationspflichten, aufgeteilt nach Art.

    ``vorlauf`` entscheidet, ob eine Pflicht überhaupt schon auftauchen darf.
    Ein Nachweis mit Frist 2028 hat 2026 auf der Startseite nichts zu suchen —
    ohne diese Bremse steht dauerhaft alles im Blick, und dann bedeutet „im
    Blick" nichts mehr.
    """
    heute = heute or date.today()
    liste = []
    for e in v.organisation():
        if e.wert("stand") in {"erledigt", "entfaellt"}:
            continue
        frist = _datum(e.wert("frist"))
        tage = (frist - heute).days if frist else None
        vorlauf = e.zahl("vorlauf")
        liste.append({
            "id": e.id, "titel": e.titel, "art": e.wert("art"),
            "stand": e.wert("stand"), "frist": e.wert("frist"),
            "frist_art": e.wert("frist_art") or "unbekannt",
            "tage": tage,
            "soll": e.zahl("soll"), "ist": e.zahl("ist"),
            "einheit": e.wert("einheit"), "stelle": e.wert("stelle"),
            "regel": e.wert("regel"),
            # Ohne Frist ist nichts dringend, aber auch nichts erledigt.
            "sichtbar_auf_heute": bool(
                tage is not None and vorlauf is not None and tage <= vorlauf
            ),
        })
    liste.sort(key=lambda f: (f["tage"] is None, f["tage"] if f["tage"] is not None else 0))
    return liste


def im_blick(v: Vault, heute: date | None = None) -> list[dict]:
    """Höchstens drei Zeilen. Die Deckelung ist der ganze Trick.

    Sortiert nach Härte der Folge: Zulassung verlieren schlägt Frist verpassen
    schlägt Stoff nachholen. Eine Liste, die wächst, wird ignoriert.
    """
    heute = heute or date.today()
    kandidaten: list[tuple[int, dict]] = []

    for f in fristen(v, heute):
        if f["sichtbar_auf_heute"]:
            rang = 1 if f["frist_art"] == "hart" else 2
            kandidaten.append((rang, {
                "art": "frist", "titel": f["titel"],
                "hinweis": f"in {f['tage']} Tagen", "id": f["id"],
            }))

    for s in fachstand(v, heute):
        if s.rueckstand > 0:
            kandidaten.append((3, {
                "art": "rueckstand", "titel": s.name,
                "hinweis": f"{s.rueckstand} Themen ohne Notizen", "id": s.id,
            }))

    kandidaten.sort(key=lambda k: k[0])
    return [k[1] for k in kandidaten[:3]]


def zustand(v: Vault, heute: date | None = None) -> dict:
    """Alles, was die Oberfläche für „Heute" braucht, in einem Rutsch."""
    heute = heute or date.today()
    montag = heute - timedelta(days=heute.weekday())
    stand = fachstand(v, heute)
    return {
        "heute": heute.isoformat(),
        "woche_ab": montag.isoformat(),
        "block": blockuhr(v, heute),
        "termine": [t.__dict__ | {"tag": t.tag.isoformat(),
                                  "ersetzt": t.ersetzt.isoformat() if t.ersetzt else None}
                    for t in termine_der_woche(v, montag)],
        "online": online_ohne_slot(v),
        "aufgaben": aufgaben_heute(v, heute),
        "im_blick": im_blick(v, heute),
        "fristen": fristen(v, heute),
        "faecher": [
            s.__dict__ | {"hat_nenner": s.hat_nenner, "takt": s.takt, "ampel": s.ampel}
            for s in stand
        ],
        # Kein Wert bedeutet „nie abgeglichen", nicht „gerade abgeglichen".
        "abgleich": None,
    }
