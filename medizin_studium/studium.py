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
from dataclasses import dataclass, field
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
    # Die Kennung desselben Termins in der Fremdquelle. Ohne sie stünde jedes
    # gespiegelte Training zweimal im Raster — einmal aus dem Vault, einmal
    # frisch aus Google.
    extern_id: str | None = None

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
            extern_id=e.wert("gcal"),
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
    bloecke: list[str] = field(default_factory=list)
    eigene_klausur: str | None = None
    anwesenheit: dict = field(default_factory=dict)

    @property
    def hat_nenner(self) -> bool:
        """Gibt es überhaupt eine Stoffliste?"""
        return self.themen_gesamt > 0

    @property
    def lerntage_noetig(self) -> int | None:
        """Ein Lerntag je Thema, das noch nicht bei Anki angekommen ist.

        Die Annahme „ein Thema = ein Lerntag" ist grob, aber sie steht in der
        Oberfläche daneben. Alles Feinere wäre erfunden — es gibt keine Daten
        darüber, wie lange Till je Thema tatsächlich braucht.
        """
        return self.ohne_anki if self.hat_nenner else None

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


def anwesenheit_je_fach(v: Vault, block: str | None = None) -> dict[str, dict]:
    """Gezählte Termine je Fach aus ``Anwesenheit.csv``.

    ``erfasst`` ist die wichtigste Zahl: ein Tag ohne Zeile gilt als **nicht
    erfasst**, nie als gefehlt. Ohne diese Unterscheidung meldete die App
    Fehltage, die nur Lücken in der Erfassung sind — und daran hängt die
    Prüfungszulassung.
    """
    zaehler: dict[str, dict] = {}
    for reihe in v.anwesenheit():
        fach = (reihe.get("fach") or "").strip()
        if not fach:
            continue
        if block and (reihe.get("block") or "").strip() not in ("", block):
            continue
        stand = zaehler.setdefault(fach, {
            "erfasst": 0, "anwesend": 0, "gefehlt": 0,
            "entschuldigt": 0, "nicht_pflicht": 0,
        })
        stand["erfasst"] += 1
        status = (reihe.get("status") or "").strip()
        if status in stand:
            stand[status] += 1
    return zaehler


def fachstand(v: Vault, heute: date | None = None) -> list[Fachstand]:
    heute = heute or date.today()
    themen = v.lernstand()
    bloecke = {b.get("id"): b for b in v.themenbloecke()}
    anwesend = anwesenheit_je_fach(v)

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
            bloecke=liste_aus_frontmatter(f.get("bloecke")),
            eigene_klausur=f.get("klausur") or None,
            anwesenheit=anwesend.get(fid, {}),
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
            "beginn": b.get("beginn"),
            "ende": b.get("ende"),
            "tage_bis_beginn": (beginn - heute).days if heute < beginn else 0,
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


def querverbindungen(v: Vault) -> list[dict]:
    """Themen, die in mehreren Fächern auf derselben Wiki-Seite landen.

    Es gibt kein Feld „Querverbindung" im Vault, und eines zu erfinden hieße,
    Till müsste es pflegen. Stattdessen wird abgeleitet: verweisen Themen aus
    zwei verschiedenen Fächern auf dieselbe `wiki`-Seite, ist das die
    Querverbindung. Fächerübergreifend gestellte Fragen hängen genau daran.
    """
    nach_seite: dict[str, set[str]] = {}
    for t in v.lernstand():
        seite, fach = t.wert("wiki"), t.wert("fach")
        if seite and fach:
            nach_seite.setdefault(seite, set()).add(fach)
    return sorted(
        ({"titel": seite, "faecher": sorted(faecher)}
         for seite, faecher in nach_seite.items() if len(faecher) > 1),
        key=lambda q: (-len(q["faecher"]), q["titel"]),
    )


def landebahn(v: Vault, heute: date | None = None) -> dict:
    """Wie viele Lerntage jedes Fach noch braucht — gegen die Zeit gestellt.

    Die Balkenlänge ist ausdrücklich **nicht** Fortschritt. Ein Fortschrittsbalken
    wächst mit dem Semester von allein und sagt nichts darüber, ob es reicht.
    """
    heute = heute or date.today()
    stand = fachstand(v, heute)
    uhr = blockuhr(v, heute)
    # Bezug ist die Blockklausur, nicht der erstbeste Termin, den ein Fach
    # zufällig trägt. Med. Terminologie hat einen eigenen, früheren — der darf
    # nicht zum Maßstab für alle anderen werden.
    bis_klausur = uhr["tage_bis_klausur"] if uhr else None

    zeilen = [
        {"id": s.id, "name": s.name, "tage": s.lerntage_noetig,
         "platzhalter": s.platzhalter, "ampel": s.ampel,
         "tage_bis_klausur": s.tage_bis_klausur,
         "eigener_termin": s.eigene_klausur}
        for s in stand if s.hat_nenner
    ]
    zeilen.sort(key=lambda z: -(z["tage"] or 0))
    summe = sum(z["tage"] or 0 for z in zeilen)
    return {
        "hat_nenner": bool(zeilen),
        "zeilen": zeilen,
        "summe_tage": summe if zeilen else None,
        "tage_bis_klausur": bis_klausur,
        # Kein Urteil ohne beide Zahlen. „Reicht" oder „reicht nicht" braucht
        # einen Nenner; ohne Stoffliste steht hier nichts.
        "reicht": None if not zeilen or bis_klausur is None else summe <= bis_klausur,
    }


def block_zustand(v: Vault, heute: date | None = None) -> dict:
    """Alles für die Seite „Block"."""
    heute = heute or date.today()
    uhr = blockuhr(v, heute)
    stand = fachstand(v, heute)
    laufend = uhr["id"] if uhr else None

    def als_dict(s: Fachstand) -> dict:
        return s.__dict__ | {"hat_nenner": s.hat_nenner, "takt": s.takt,
                             "ampel": s.ampel, "lerntage_noetig": s.lerntage_noetig}

    aktiv = [s for s in stand if not laufend or laufend in s.bloecke]
    ruhend = [s for s in stand if laufend and laufend not in s.bloecke]

    return {
        "heute": heute.isoformat(),
        "block": uhr,
        "faecher": [als_dict(s) for s in aktiv],
        "ruhend": [als_dict(s) for s in ruhend],
        # Fächer mit eigenem Termin laufen nicht in der Blockklausur mit.
        "eigene_klausuren": [als_dict(s) for s in stand if s.eigene_klausur],
        "landebahn": landebahn(v, heute),
        "querverbindungen": querverbindungen(v),
        "anwesenheit_erfasst": sum(
            (s.anwesenheit or {}).get("erfasst", 0) for s in stand
        ),
        "maengel": list(v.maengel),
    }


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
            # Geht mit zur Oberfläche und beim Abhaken wieder zurück. Ohne
            # diesen Umweg prüfte der Server nur gegen seinen eigenen Lesevorgang
            # von einer Millisekunde vorher — und überschriebe stillschweigend,
            # was Obsidian in der Zwischenzeit an derselben Zeile geändert hat.
            "pruefsumme": e.pruefsumme,
        })
    liste.sort(key=lambda a: (-a["ueberfaellig"], a["titel"]))
    return liste


def _fenster_stand(von: date | None, bis: date | None, heute: date) -> str:
    if von is None and bis is None:
        return "unbekannt"
    if von and heute < von:
        return "offen"
    if bis and heute > bis:
        return "vorbei"
    return "laeuft"


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
            "regel": e.wert("regel"), "beleg": e.wert("beleg"),
            "fenster_von": e.wert("fenster_von"),
            "fenster_bis": e.wert("fenster_bis"),
            # offen / laeuft / vorbei — bei Anmeldungen zählt das Fenster,
            # nicht ein Stichtag. Ein verpasstes Fenster ist nicht dasselbe
            # wie eine verpasste Frist: es kommt wieder.
            "fenster_stand": _fenster_stand(
                _datum(e.wert("fenster_von")), _datum(e.wert("fenster_bis")), heute),
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


def _minuten(zeit: str) -> int:
    stunde, minute = zeit.split(":")
    return int(stunde) * 60 + int(minute)


def naechster_termin(liste: list[Termin], jetzt: datetime) -> dict | None:
    """Der laufende Termin, sonst der nächste. ``None``, wenn nichts kommt.

    ``None`` heißt hier „nichts erfasst", nicht „nichts los". Die Oberfläche
    schreibt das auch so hin — der Unterschied ist bei leerem Vault der ganze
    Punkt.
    """
    heute, uhr = jetzt.date(), jetzt.hour * 60 + jetzt.minute
    kommend: list[tuple[int, Termin, bool]] = []
    for t in liste:
        if t.status in {"entfaellt", "fehler"} or t.von is None:
            continue
        beginn = (t.tag - heute).days * 1440 + _minuten(t.von)
        ende = beginn + (_minuten(t.bis) - _minuten(t.von) if t.bis else 60)
        if ende <= uhr:
            continue
        kommend.append((beginn, t, beginn <= uhr))
    if not kommend:
        return None
    kommend.sort(key=lambda k: k[0])
    beginn, t, laeuft = kommend[0]
    return {
        "titel": t.titel, "tag": t.tag.isoformat(), "von": t.von, "bis": t.bis,
        "ort": t.ort, "fach": t.fach, "bereich": t.bereich, "quelle": t.quelle,
        "laeuft": laeuft, "minuten_bis": max(0, beginn - uhr),
    }


def _als_dict(t: Termin) -> dict:
    return t.__dict__ | {
        "tag": t.tag.isoformat(),
        "ersetzt": t.ersetzt.isoformat() if t.ersetzt else None,
    }


def punktekonto(v: Vault, fach_id: str) -> dict:
    """Ergebnisse eines Fachs über alle Blöcke.

    Für die Ärztliche Zwischenprüfung zählen **60 % je Fach kumuliert über
    alle Blöcke**, nicht je Klausur. Ein Block mit 52 % ist deshalb kein
    Durchfallen, solange die Summe stimmt — und ein Block mit 61 % keine
    Entwarnung. Genau deshalb wird hier summiert und nicht gemittelt.
    """
    zeilen = []
    punkte = maxpunkte = 0
    for e in v.pruefungen():
        if e.wert("fach") != fach_id:
            continue
        p, m = e.zahl("punkte"), e.zahl("max_punkte")
        zeilen.append({
            "id": e.id, "block": e.wert("block"), "art": e.wert("art"),
            "datum": e.wert("datum"), "punkte": p, "max_punkte": m,
            "prozent": round(p / m * 100, 1) if p is not None and m else None,
            "bestanden": e.wert("bestanden"), "versuch": e.zahl("versuch"),
            # Ohne Rohwerte ist das Ergebnis offen, nicht null.
            "offen": p is None or m is None,
        })
        if p is not None and m:
            punkte += p
            maxpunkte += m
    zeilen.sort(key=lambda z: (z["datum"] or "", z["versuch"] or 0))
    return {
        "zeilen": zeilen,
        "punkte": punkte if maxpunkte else None,
        "max_punkte": maxpunkte or None,
        "prozent": round(punkte / maxpunkte * 100, 1) if maxpunkte else None,
        "reicht": (punkte / maxpunkte >= 0.6) if maxpunkte else None,
    }


def _material(v: Vault, ordner: str | None) -> list[dict]:
    """Dateien im Materialordner. Nur lesen — ``Quellen/`` ist tabu (§1)."""
    if not ordner:
        return []
    pfad = v.wurzel / ordner
    if not pfad.is_dir():
        return []
    gefunden = []
    for datei in sorted(pfad.iterdir()):
        if datei.name.startswith(".") or datei.is_dir():
            continue
        gefunden.append({
            "name": datei.name,
            "typ": (datei.suffix.lstrip(".") or "?").upper(),
            "groesse": datei.stat().st_size,
        })
    return gefunden


def fach_detail(v: Vault, fach_id: str, heute: date | None = None) -> dict | None:
    """Alles zu einem Fach. ``None``, wenn es das Fach nicht gibt."""
    heute = heute or date.today()
    stand = next((s for s in fachstand(v, heute) if s.id == fach_id), None)
    if stand is None:
        return None
    roh = next((f for f in v.faecher() if f.get("id") == fach_id), {})

    themen = []
    for t in v.lernstand():
        if t.wert("fach") != fach_id:
            continue
        termin = _datum(t.wert("termin"))
        erreicht = [s for s in STUFEN if t.wert(s)]
        themen.append({
            "id": t.id, "titel": t.titel, "termin": t.wert("termin"),
            "quelle": t.wert("quelle"), "relevanz": t.wert("relevanz"),
            "stufen": {s: t.wert(s) for s in STUFEN},
            "erreicht": erreicht,
            "wiki": t.wert("wiki"), "karten": t.zahl("karten"),
            # „Rückstand" heißt: Vorlesung war, Notizen fehlen. Nicht
            # „irgendeine Stufe fehlt" — Loci ist laut Lernsystem freiwillig.
            "rueckstand": bool(termin and termin <= heute and not t.wert("notizen")),
        })
    themen.sort(key=lambda t: (t["termin"] or "9999", t["titel"]))

    return {
        "id": stand.id, "name": stand.name,
        "platzhalter": stand.platzhalter,
        "themen_gesamt": stand.themen_gesamt, "stufen": stand.stufen,
        "hat_nenner": stand.hat_nenner, "rueckstand": stand.rueckstand,
        "aeltestes_offen": stand.aeltestes_offen,
        "tage_bis_klausur": stand.tage_bis_klausur, "takt": stand.takt,
        "ampel": stand.ampel, "ohne_anki": stand.ohne_anki,
        "bloecke": stand.bloecke, "eigene_klausur": stand.eigene_klausur,
        "anwesenheit": stand.anwesenheit,
        "anwesenheit_regel": roh.get("anwesenheit_regel") or None,
        "pruefungsform": roh.get("pruefungsform") or None,
        "versuche_max": roh.get("versuche_max") or None,
        "dozent": roh.get("dozent") or None,
        "ort": roh.get("ort") or None,
        "anki_deck": stand.anki_deck,
        "material_ordner": roh.get("material_ordner") or None,
        "material": _material(v, roh.get("material_ordner")),
        "punktekonto": punktekonto(v, fach_id),
        "themen": themen,
        "optionale_stufen": sorted(OPTIONALE_STUFEN),
        "maengel": list(v.maengel),
    }


# ---------------------------------------------------------------------------
# Seite Orga
# ---------------------------------------------------------------------------

def einrichtung(v: Vault, dienste: dict) -> list[dict]:
    """Was noch fehlt, damit die App etwas zu rechnen hat.

    Sechs Schritte, und keiner davon braucht den amtlichen Stundenplan — sonst
    stünde die App bis Oktober still. ``dienste`` reicht der Server herein; er
    weiß, ob Google und Anki antworten, diese Schicht soll das nicht wissen.
    """
    themen = v.lernstand()
    schritte = [
        {"schluessel": "google", "titel": "Google-Kalender verbinden",
         "fertig": dienste.get("google") == "ok",
         "hilfe": "Damit die Woche zeigt, was wirklich ansteht."},
        {"schluessel": "stundenplan", "titel": "Stundenplan eintragen",
         "fertig": bool(v.stundenplan()),
         "hilfe": "Wiederkehrende Veranstaltungen als Serien."},
        {"schluessel": "faecher", "titel": "Fächer bestätigen",
         "fertig": bool(v.faecher()) and not any(
             _ja(f.get("platzhalter")) for f in v.faecher()),
         "hilfe": "Acht Platzhalter stehen bereit — sie sind noch geraten."},
        {"schluessel": "lernstand", "titel": "Stofflisten anlegen",
         "fertig": bool(themen),
         "hilfe": "Ein Thema je Vorlesung. Ohne sie gibt es keinen Nenner."},
        {"schluessel": "anki", "titel": "Anki-Decks anlegen",
         "fertig": dienste.get("anki") == "ok",
         "hilfe": "Schema Medizin::<Fach>, Block und Thema als Schlagwörter."},
        {"schluessel": "anwesenheit", "titel": "Anwesenheit erfassen",
         "fertig": bool(v.anwesenheit()),
         "hilfe": "Daran hängt die Prüfungszulassung."},
    ]
    return schritte


def orga_zustand(v: Vault, heute: date | None = None, dienste: dict | None = None) -> dict:
    """Alles für die Seite „Orga".

    Die Aufteilung ist der Punkt: Eine Frist hat ein Datum, ein Nachweis hat
    ein Zählwerk, eine Anmeldung hat ein Fenster. In einer Liste vermischt
    hilft keine der drei Sorten weiter.
    """
    heute = heute or date.today()
    alle = fristen(v, heute)
    schritte = einrichtung(v, dienste or {})
    return {
        "heute": heute.isoformat(),
        "fristen": [f for f in alle if f["art"] not in ("nachweis", "anmeldung")],
        "nachweise": [f for f in alle if f["art"] == "nachweis"],
        "anmeldungen": [f for f in alle if f["art"] == "anmeldung"],
        "einrichtung": schritte,
        "einrichtung_offen": sum(1 for s in schritte if not s["fertig"]),
        "maengel": list(v.maengel),
    }


# ---------------------------------------------------------------------------
# Seite Eingang
# ---------------------------------------------------------------------------

def eingang_zustand(v: Vault) -> dict:
    """Vorschläge und Konflikte, gruppiert nach Art.

    Konflikte stehen bewusst zuoberst: Solange einer offen ist, ist die
    betroffene Zeile für automatische Aufträge gesperrt.
    """
    vorschlaege = [
        s for s in v.vorschlaege()
        if s.get("stand", "offen") in ("offen", "spaeter")
    ]
    konflikte = [
        {"id": e.id, "titel": e.titel, "datei": e.wert("datei"),
         "zeile": e.wert("zeile"), "art": e.wert("art"),
         "hier": e.wert("hier"), "dort": e.wert("dort"),
         "quelle": e.wert("quelle"), "stand": e.wert("stand"),
         "pruefsumme": e.pruefsumme}
        for e in v.konflikte() if e.wert("stand") not in ("entschieden", "erledigt")
    ]

    gruppen: dict[str, list] = {}
    for s in vorschlaege:
        gruppen.setdefault(s.get("art", "sonstiges"), []).append(s)

    return {
        "konflikte": konflikte,
        "gruppen": [
            {"art": art, "n": len(liste), "eintraege": liste}
            for art, liste in sorted(gruppen.items())
        ],
        "offen": len(vorschlaege) + len(konflikte),
        "spaeter": sum(1 for s in vorschlaege if s.get("stand") == "spaeter"),
        "maengel": list(v.maengel),
    }


def zustand(
    v: Vault,
    heute: date | None = None,
    jetzt: datetime | None = None,
    extern: list[Termin] | None = None,
) -> dict:
    """Alles, was die Oberfläche für „Heute" braucht, in einem Rutsch.

    ``extern`` sind Termine aus fremden Quellen — heute Google Calendar. Sie
    kommen fertig übersetzt herein, damit diese Schicht nichts über HTTP oder
    OAuth wissen muss.
    """
    heute = heute or date.today()
    jetzt = jetzt or datetime.now()
    montag = heute - timedelta(days=heute.weekday())
    stand = fachstand(v, heute)
    aus_vault = termine_der_woche(v, montag)

    # Der Vault gewinnt bei Doppelungen: Seine Zeile trägt die stabile ID und
    # die Notizen (Trainingssätze etwa), die in Google gar nicht stehen.
    gespiegelt = {t.extern_id for t in aus_vault if t.extern_id}
    frisch = [t for t in (extern or [])
              if (t.id or "").removeprefix("gcal:") not in gespiegelt]

    alle = aus_vault + frisch
    alle.sort(key=lambda t: (t.tag, t.von or "00:00"))
    return {
        "heute": heute.isoformat(),
        "jetzt": jetzt.strftime("%H:%M"),
        "woche_ab": montag.isoformat(),
        "block": blockuhr(v, heute),
        "termine": [_als_dict(t) for t in alle],
        "naechster": naechster_termin(alle, jetzt),
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
        # Fehlende Dateien reisen bis in die Anzeige mit. Eine leere Liste
        # heißt „nichts erfasst", eine fehlende Datei heißt etwas anderes.
        "maengel": list(v.maengel),
    }
