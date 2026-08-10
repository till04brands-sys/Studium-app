"""Den Vault lesen und zeilenweise zurückschreiben.

Die Regeln stehen in CLAUDE.md §11 und sind hier nicht verhandelbar:

- Gelesen wird nur, was unter ``## Einträge`` steht. Darüber ist Dokumentation;
  stünde das Beispiel aus der Anleitung im Ergebnis, wäre es ein echter Termin.
- Geschrieben wird **eine Zeile**, nie die Datei. Was Obsidian oder Jarvis
  parallel geändert haben, bleibt dadurch Zeichen für Zeichen stehen.
- Vor jedem Schreiben wird die Datei neu eingelesen und der Hash *genau der
  Zeile* geprüft, die geändert werden soll. Nicht der Dateihash — sonst
  blockieren sich App und Obsidian bei jeder unbeteiligten Änderung.
- Fehlende Werte sind ``None``, nie ``0``. Leer heißt „nicht gemessen", null
  heißt „gemessen, war null". Bei Zahlen, an denen die Prüfungszulassung
  hängt, ist das kein akademischer Unterschied.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

# [schluessel:: wert] — der Wert darf leer sein und endet an der Klammer.
_FELD = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)::\s*([^\]]*)\]")
_EINTRAEGE = re.compile(r"^##\s+Einträge\s*$", re.MULTILINE)


class VaultFehler(Exception):
    """Etwas am Vault stimmt nicht — Datei fehlt, Format kaputt."""


class Konflikt(VaultFehler):
    """Die Zeile wurde seit dem Lesen anderswo geändert.

    Kein Fehler im engeren Sinn, sondern der Normalfall bei drei Schreibern.
    Die App bietet daraufhin „neu laden" an, statt zu überschreiben.
    """


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Eintrag:
    """Eine Datenzeile aus einer Planer-Datei."""

    titel: str
    felder: dict[str, str]
    zeile: str                      # der Rohtext, unverändert
    nummer: int                     # 0-basiert, bezogen auf die ganze Datei
    quelle: Path
    pruefsumme: str = ""

    def __post_init__(self) -> None:
        if not self.pruefsumme:
            self.pruefsumme = _hash(self.zeile)

    @property
    def id(self) -> str | None:
        return self.felder.get("id") or None

    def wert(self, name: str) -> str | None:
        """Feldwert oder ``None``.

        Ein leeres Feld (``[frist::]``) gibt ausdrücklich ``None`` zurück:
        „unbekannt", nicht „leer eingetragen".
        """
        w = self.felder.get(name, "").strip()
        return w or None

    def zahl(self, name: str) -> int | None:
        w = self.wert(name)
        if w is None:
            return None
        try:
            return int(w)
        except ValueError:
            return None

    def liste(self, name: str) -> list[str]:
        w = self.wert(name)
        return [t.strip() for t in w.split(",") if t.strip()] if w else []


def felder_lesen(zeile: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _FELD.finditer(zeile)}


def titel_lesen(zeile: str) -> str:
    """Was zwischen dem Aufzählungsstrich und der ersten Klammer steht."""
    ohne_strich = re.sub(r"^\s*[-*]\s*", "", zeile)
    return ohne_strich.split("[")[0].strip()


def eintraege_lesen(pfad: Path) -> list[Eintrag]:
    """Alle Datenzeilen einer Planer-Datei.

    Zeilen, die nicht mit ``-`` beginnen, gelten als Fortsetzung der
    vorherigen — lange Einträge dürfen umbrochen werden, ohne zu zerfallen.
    """
    if not pfad.exists():
        raise VaultFehler(f"Datei fehlt: {pfad}")

    text = pfad.read_text(encoding="utf-8")
    treffer = _EINTRAEGE.search(text)
    if not treffer:
        raise VaultFehler(f"Keine Überschrift '## Einträge' in {pfad.name}")

    alle = text.split("\n")
    ab = text[: treffer.end()].count("\n") + 1

    eintraege: list[Eintrag] = []
    roh: list[str] = []
    start = ab

    def abschliessen() -> None:
        if not roh:
            return
        zeile = "\n".join(roh)
        eintraege.append(
            Eintrag(
                titel=titel_lesen(zeile),
                felder=felder_lesen(zeile),
                zeile=zeile,
                nummer=start,
                quelle=pfad,
            )
        )

    for i in range(ab, len(alle)):
        z = alle[i]
        blank = not z.strip()
        kommentar = z.lstrip().startswith("<!--")

        if z.lstrip().startswith("-") and not kommentar:
            abschliessen()
            roh, start = [z], i
        elif roh and not blank and not kommentar:
            roh.append(z)
        elif blank or kommentar:
            abschliessen()
            roh = []

    abschliessen()
    return eintraege


def frontmatter_lesen(pfad: Path) -> dict[str, str]:
    """Das YAML-Frontmatter, flach und ohne YAML-Bibliothek.

    Reicht für den Vault: dort stehen nur ``schluessel: wert`` und einfache
    Listen in eckigen Klammern. Werte in Anführungszeichen werden entpackt.
    """
    if not pfad.exists():
        raise VaultFehler(f"Datei fehlt: {pfad}")

    text = pfad.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}

    _, _, rest = text.partition("---\n")
    block, _, _ = rest.partition("\n---")

    daten: dict[str, str] = {}
    for zeile in block.split("\n"):
        if not zeile.strip() or zeile.lstrip().startswith("#"):
            continue
        schluessel, trenner, wert = zeile.partition(":")
        if not trenner:
            continue
        wert = wert.strip().strip('"').strip("'")
        daten[schluessel.strip()] = wert
    return daten


def liste_aus_frontmatter(wert: str | None) -> list[str]:
    """``[tb1, tb2]`` → ``['tb1', 'tb2']``. Leer bleibt leer."""
    if not wert:
        return []
    return [t.strip() for t in wert.strip("[]").split(",") if t.strip()]


def zeile_schreiben(pfad: Path, eintrag: Eintrag, neue_zeile: str) -> Eintrag:
    """Genau eine Zeile ersetzen, nachdem geprüft wurde, dass sie unverändert ist.

    Wirft ``Konflikt``, wenn jemand schneller war. Die App zeigt dann beide
    Fassungen — sie wählt nicht selbst.
    """
    aktuell = pfad.read_text(encoding="utf-8").split("\n")
    hoehe = eintrag.zeile.count("\n") + 1
    ist = "\n".join(aktuell[eintrag.nummer : eintrag.nummer + hoehe])

    if _hash(ist) != eintrag.pruefsumme:
        raise Konflikt(
            f"{pfad.name}, Zeile {eintrag.nummer + 1}: "
            "seit dem Lesen anderswo geändert"
        )

    aktuell[eintrag.nummer : eintrag.nummer + hoehe] = neue_zeile.split("\n")
    pfad.write_text("\n".join(aktuell), encoding="utf-8")

    return Eintrag(
        titel=titel_lesen(neue_zeile),
        felder=felder_lesen(neue_zeile),
        zeile=neue_zeile,
        nummer=eintrag.nummer,
        quelle=pfad,
    )


def feld_setzen(pfad: Path, eintrag: Eintrag, name: str, wert: str | None) -> Eintrag:
    """Ein Feld ändern, anlegen oder leeren; alles andere bleibt unberührt.

    ``wert=None`` schreibt ``[name::]`` — ausdrücklich „unbekannt", nicht
    „Feld weg". Ein entferntes Feld wäre nicht von „nie gesetzt" zu
    unterscheiden.
    """
    neu = wert or ""
    if name in eintrag.felder:
        zeile = _FELD.sub(
            lambda m: f"[{name}:: {neu}]".replace(":: ]", "::]")
            if m.group(1) == name
            else m.group(0),
            eintrag.zeile,
        )
    else:
        zusatz = f"[{name}:: {neu}]".replace(":: ]", "::]")
        zeile = f"{eintrag.zeile.rstrip()} {zusatz}"
    return zeile_schreiben(pfad, eintrag, zeile)


def zeile_anhaengen(pfad: Path, zeile: str) -> None:
    """Eine neue Zeile ans Ende der Einträge setzen.

    Kommentarblöcke am Dateiende (die Hinweise „noch keine Daten") bleiben
    stehen — die neue Zeile kommt davor.
    """
    text = pfad.read_text(encoding="utf-8")
    if not _EINTRAEGE.search(text):
        raise VaultFehler(f"Keine Überschrift '## Einträge' in {pfad.name}")

    alle = text.rstrip("\n").split("\n")
    ende = len(alle)
    while ende > 0 and (
        not alle[ende - 1].strip() or alle[ende - 1].lstrip().startswith("<!--")
    ):
        ende -= 1

    alle.insert(ende, zeile)
    pfad.write_text("\n".join(alle) + "\n", encoding="utf-8")


def csv_lesen(pfad: Path) -> list[dict[str, str | None]]:
    """CSV als Liste von Zeilen. Leere Zellen werden ``None``, nie ``0``."""
    if not pfad.exists():
        raise VaultFehler(f"Datei fehlt: {pfad}")
    with pfad.open(encoding="utf-8", newline="") as f:
        return [
            {k: (v.strip() or None) for k, v in reihe.items() if k}
            for reihe in csv.DictReader(f)
        ]


def csv_anhaengen(pfad: Path, reihe: dict[str, str], spalten: list[str]) -> None:
    puffer = io.StringIO()
    csv.DictWriter(puffer, fieldnames=spalten, extrasaction="ignore").writerow(reihe)
    with pfad.open("a", encoding="utf-8", newline="") as f:
        f.write(puffer.getvalue())


@dataclass
class Vault:
    """Zugriff auf die Dateien, die die Studium-App braucht."""

    wurzel: Path
    _zwischenspeicher: dict[Path, list[Eintrag]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.wurzel = Path(self.wurzel).expanduser()
        if not (self.wurzel / "CLAUDE.md").exists():
            raise VaultFehler(
                f"{self.wurzel} sieht nicht nach dem Vault aus — CLAUDE.md fehlt"
            )

    # -- Pfade ---------------------------------------------------------------
    @property
    def planer(self) -> Path:
        return self.wurzel / "Planer"

    @property
    def studium(self) -> Path:
        return self.planer / "Studium"

    def datei(self, name: str) -> Path:
        return self.planer / name

    # -- Lesen ---------------------------------------------------------------
    def eintraege(self, pfad: Path, frisch: bool = False) -> list[Eintrag]:
        if frisch or pfad not in self._zwischenspeicher:
            self._zwischenspeicher[pfad] = eintraege_lesen(pfad)
        return self._zwischenspeicher[pfad]

    def vergessen(self) -> None:
        """Zwischenspeicher leeren — vor jedem Schreibvorgang."""
        self._zwischenspeicher.clear()

    def aufgaben(self, bereich: str | None = "studium") -> list[Eintrag]:
        alle = self.eintraege(self.datei("Aufgaben.md"))
        if bereich is None:
            return alle
        return [e for e in alle if e.wert("bereich") == bereich]

    def termine(self, bereich: str | None = None) -> list[Eintrag]:
        alle = self.eintraege(self.datei("Kalender.md"))
        if bereich is None:
            return alle
        return [e for e in alle if e.wert("bereich") == bereich]

    def stundenplan(self) -> list[Eintrag]:
        return self.eintraege(self.datei("Stundenplan.md"))

    def lernstand(self) -> list[Eintrag]:
        return self.eintraege(self.studium / "Lernstand.md")

    def organisation(self) -> list[Eintrag]:
        return self.eintraege(self.studium / "Organisation.md")

    def pruefungen(self) -> list[Eintrag]:
        return self.eintraege(self.studium / "Pruefungen.md")

    def anwesenheit(self) -> list[dict[str, str | None]]:
        return csv_lesen(self.studium / "Anwesenheit.csv")

    def faecher(self) -> list[dict[str, str]]:
        ordner = self.studium / "Faecher"
        if not ordner.is_dir():
            raise VaultFehler(f"Fächerordner fehlt: {ordner}")
        gefunden = []
        for p in sorted(ordner.glob("*.md")):
            fm = frontmatter_lesen(p)
            fm["_datei"] = str(p)
            gefunden.append(fm)
        return gefunden

    def themenbloecke(self) -> list[dict[str, str]]:
        ordner = self.studium / "Themenbloecke"
        if not ordner.is_dir():
            raise VaultFehler(f"Themenblockordner fehlt: {ordner}")
        bloecke = []
        for p in sorted(ordner.glob("*.md")):
            fm = frontmatter_lesen(p)
            fm["_datei"] = str(p)
            bloecke.append(fm)
        return bloecke

    # -- Schreiben -----------------------------------------------------------
    def naechste_id(self, praefix: str) -> str:
        """Die nächste Nummer aus Zaehler.md, mit Sperrdatei.

        Ausdrücklich **kein** „höchste vorhandene plus eins" — genau das
        erzeugt Doppel-IDs, sobald zwei Schreiber unterwegs sind oder eine
        Zeile ins Archiv gewandert ist.
        """
        zaehler = self.planer / "Sync" / "Zaehler.md"
        sperre = zaehler.with_suffix(".lock")
        try:
            sperre.touch(exist_ok=False)
        except FileExistsError as fehler:
            raise VaultFehler(
                "Zaehler.md ist gesperrt — ein anderer Schreibvorgang läuft"
            ) from fehler
        try:
            for e in eintraege_lesen(zaehler):
                if e.wert("praefix") == praefix:
                    naechste = (e.zahl("letzte") or 0) + 1
                    zeile_schreiben(
                        zaehler,
                        e,
                        _FELD.sub(
                            lambda m: f"[letzte:: {naechste:04d}]"
                            if m.group(1) == "letzte"
                            else f"[wer:: app]"
                            if m.group(1) == "wer"
                            else m.group(0),
                            e.zeile,
                        ),
                    )
                    return f"{praefix}-{naechste:04d}"
            raise VaultFehler(f"Kein Zähler für Präfix '{praefix}'")
        finally:
            sperre.unlink(missing_ok=True)
