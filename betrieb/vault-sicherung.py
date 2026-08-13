#!/usr/bin/env python3
"""Verschlüsselte Sicherung des Vaults — täglich, versioniert, außer Haus.

**Warum es das gibt.** Bis zum 13.08.2026 lag der Vault in ``~/Documents`` und
wurde von iCloud gespiegelt. Das sah aus wie eine Sicherung, war aber keine:
Eine Spiegelung überträgt auch das Löschen und auch den Schaden. Nach dem
Umzug nach ``~/Vault`` spiegelt niemand mehr etwas — und Time Machine ist auf
diesem Rechner gar nicht eingerichtet. Der Vault existierte damit genau einmal.

**Warum verschlüsselt.** Das Ziel liegt in iCloud Drive, damit die Sicherung
einen Plattenschaden übersteht. Im Vault stehen Blutwerte, Journal und
Prüfungsergebnisse; die gehen Apple nichts an. Verschlüsselt wird deshalb
*vor* dem Ablegen, mit einem Schlüssel, den nur Till kennt.

**Warum feste Dateinamen.** macOS lässt einen Hintergrunddienst in geschützte
Ordner *schreiben* und die selbst geschriebenen Dateien zurücklesen — aber
nicht den Ordner durchsuchen. Eine Rotation, die erst nachsieht, was da liegt,
wäre also unmöglich. Stattdessen sieben Wochentage und zwölf Monate, die sich
selbst überschreiben: konstant viele Dateien, kein Auflisten nötig.

**Was hier absichtlich fehlt: der Schlüssel.** Er steht in einer Datei, die
Till selbst anlegt. Ohne sie läuft nichts, und das ist die Absicht — eine
Sicherung, deren Schlüssel im selben Repository liegt, ist keine.

Aufruf: ``python3 betrieb/vault-sicherung.py``. Nur Standardbibliothek plus
``tar`` und ``openssl`` aus dem System, damit die Sicherung auch dann läuft,
wenn an der App etwas kaputt ist.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

HEIM = Path.home()

QUELLE = Path(os.environ.get("SICHERUNG_QUELLE", HEIM / "Vault/2.Brain"))
LOKAL = Path(os.environ.get("SICHERUNG_LOKAL", HEIM / "Vault/Sicherungen"))
AUSSER_HAUS = Path(os.environ.get(
    "SICHERUNG_ICLOUD",
    HEIM / "Library/Mobile Documents/com~apple~CloudDocs/Vault-Sicherungen",
))
SCHLUESSEL = Path(os.environ.get("SICHERUNG_SCHLUESSEL", HEIM / ".vault-sicherung-schluessel"))

WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Kein Geschmack, sondern Mindestmaß: Unter 20 Zeichen ist eine Passphrase
# gegen jemanden, der die Datei in Ruhe angreifen kann, keine Hürde.
MINDESTLAENGE = 20

# Ein Archiv, das plötzlich einen erheblichen Teil weniger enthält, ist eher
# ein Fehler als ein aufgeräumter Vault. Dann lieber nichts überschreiben.
MINDESTANTEIL = 0.9


class SicherungFehler(Exception):
    """Es wurde nichts abgelegt — mit Begründung."""


def sag(text: str) -> None:
    print(text, flush=True)


def schluessel_pruefen() -> None:
    if not SCHLUESSEL.exists():
        raise SicherungFehler(
            f"Kein Schlüssel in {SCHLUESSEL}.\n"
            "  Einmalig anlegen (der Befehl zeigt ihn dir zum Notieren):\n"
            "    openssl rand -base64 32 | tee ~/.vault-sicherung-schluessel\n"
            "    chmod 600 ~/.vault-sicherung-schluessel\n"
            "  Schreib ihn dir an eine zweite Stelle. Geht diese Datei mit der\n"
            "  Platte verloren, ist jede Sicherung unlesbar."
        )
    rechte = SCHLUESSEL.stat().st_mode & 0o077
    if rechte:
        raise SicherungFehler(
            f"{SCHLUESSEL} ist auch für andere lesbar. Abhilfe:\n"
            f"    chmod 600 {SCHLUESSEL}"
        )
    erste = SCHLUESSEL.read_text(encoding="utf-8").splitlines()[:1]
    if not erste or len(erste[0].strip()) < MINDESTLAENGE:
        raise SicherungFehler(
            f"Der Schlüssel in {SCHLUESSEL} ist kürzer als {MINDESTLAENGE} Zeichen "
            "oder leer."
        )


def dateien_zaehlen(wurzel: Path) -> int:
    anzahl = 0
    for _, _, dateien in os.walk(wurzel):
        anzahl += len(dateien)
    return anzahl


def _lauf(befehl: list[str], **mehr) -> subprocess.CompletedProcess:
    fertig = subprocess.run(befehl, capture_output=True, text=True, **mehr)
    if fertig.returncode != 0:
        kurz = (fertig.stderr or fertig.stdout or "").strip().splitlines()
        raise SicherungFehler(
            f"{Path(befehl[0]).name} scheiterte "
            f"({fertig.returncode}): {kurz[0] if kurz else 'ohne Meldung'}"
        )
    return fertig


def packen_und_verschluesseln(ziel: Path) -> None:
    """Packen und Verschlüsseln in einem Rutsch, ohne Klartext auf der Platte.

    Das unverschlüsselte Archiv würde sonst — und sei es nur für Sekunden — im
    Dateisystem liegen. Es ist der ganze Vault an einem Stück; das ist die eine
    Datei, die man am wenigsten herumliegen lassen will.
    """
    with ziel.open("wb") as raus:
        tar = subprocess.Popen(
            ["/usr/bin/tar", "--exclude", ".DS_Store", "-czf", "-",
             "-C", str(QUELLE.parent), QUELLE.name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        ossl = subprocess.Popen(
            ["/usr/bin/openssl", "enc", "-aes-256-cbc", "-salt",
             "-pbkdf2", "-iter", "200000", "-pass", f"file:{SCHLUESSEL}"],
            stdin=tar.stdout, stdout=raus, stderr=subprocess.PIPE,
        )
        tar.stdout.close()          # sonst bekommt tar kein SIGPIPE
        ossl_fehler = ossl.communicate()[1]
        tar_fehler = tar.stderr.read()
        tar.stderr.close()
        tar.wait()

    if ossl.returncode != 0:
        raise SicherungFehler(f"openssl scheiterte: {ossl_fehler.decode(errors='replace')[:200]}")
    if tar.returncode != 0:
        raise SicherungFehler(f"tar scheiterte: {tar_fehler.decode(errors='replace')[:200]}")


def pruefen(archiv: Path, erwartet: int) -> int:
    """Wieder aufmachen und durchzählen.

    Ohne diesen Schritt merkt man erst im Ernstfall, dass die Sicherung nichts
    taugt — und dann ist es zu spät, sie zu wiederholen.
    """
    ossl = subprocess.Popen(
        ["/usr/bin/openssl", "enc", "-d", "-aes-256-cbc",
         "-pbkdf2", "-iter", "200000", "-pass", f"file:{SCHLUESSEL}",
         "-in", str(archiv)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    tar = subprocess.Popen(
        ["/usr/bin/tar", "-tzf", "-"],
        stdin=ossl.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    ossl.stdout.close()
    inhalt = tar.communicate()[0].decode("utf-8", "replace")
    ossl.wait()
    if tar.returncode != 0:
        raise SicherungFehler("Das Archiv ließ sich nicht wieder entpacken.")

    # Verzeichniseinträge enden auf "/" und zählen nicht als Datei.
    gefunden = sum(1 for z in inhalt.splitlines() if z and not z.endswith("/"))
    if gefunden < erwartet * MINDESTANTEIL:
        raise SicherungFehler(
            f"Das Archiv enthält {gefunden} Dateien, im Vault liegen "
            f"{erwartet}. Nichts überschrieben — die vorhandene Sicherung "
            "ist mehr wert als diese."
        )
    return gefunden


def _fingerabdruck(pfad: Path) -> str:
    kessel = hashlib.sha256()
    with pfad.open("rb") as f:
        for stueck in iter(lambda: f.read(1 << 20), b""):
            kessel.update(stueck)
    return kessel.hexdigest()


def ablegen(fertig: Path, namen: list[str]) -> list[str]:
    """Lokal und außer Haus. Das eine ist schnell zurückgespielt, das andere
    überlebt die Platte.

    Nach jedem Schreiben wird die abgelegte Datei zurückgelesen und verglichen.
    Geprüft wurde bis hierher nur die Zwischendatei; was beim Kopieren kaputt
    geht — volle Platte, abbrechendes iCloud — fiele sonst erst im Ernstfall
    auf. Ein Hintergrunddienst darf seine eigenen Dateien auch in geschützten
    Ordnern zurücklesen, genau dafür ist das gemessen worden.
    """
    soll = _fingerabdruck(fertig)
    abgelegt = []
    for ordner, wohin in ((LOKAL, "lokal"), (AUSSER_HAUS, "iCloud")):
        try:
            ordner.mkdir(parents=True, exist_ok=True)
            geschrieben = []
            for name in namen:
                ziel = ordner / name
                ziel.write_bytes(fertig.read_bytes())
                if _fingerabdruck(ziel) != soll:
                    raise SicherungFehler(
                        f"{ziel} kam anders an, als sie losgeschickt wurde"
                    )
                geschrieben.append(name)
            abgelegt.append(f"{wohin}: {', '.join(geschrieben)} · geprüft")
        except (OSError, SicherungFehler) as fehler:
            # Ein unerreichbares iCloud darf die lokale Sicherung nicht
            # verhindern - und umgekehrt.
            sag(f"  {wohin} fehlgeschlagen: {fehler}")
    return abgelegt


ANLEITUNG = """So spielst du eine Sicherung zurück
===================================

Die Dateien hier sind mit AES-256 verschluesselt. Ohne deinen Schluessel sind
sie wertlos - auch fuer dich. Er steht (oder stand) in ~/.vault-sicherung-schluessel;
hoffentlich auch an einer zweiten Stelle.

    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \\
      -in vault-Mo.tar.gz.enc | tar -xzf - -C /pfad/zum/wiederherstellen

Es fragt dann nach dem Schluessel. Steht er noch in der Datei, geht auch:

    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \\
      -pass file:$HOME/.vault-sicherung-schluessel \\
      -in vault-Mo.tar.gz.enc | tar -xzf - -C /pfad/zum/wiederherstellen

vault-Mo bis vault-So sind die letzten sieben Tage, vault-monat-01 bis -12 die
Monatsstaende. Was hier liegt, ist immer der Stand des jeweils letzten Laufs.

Ein Hinweis fuer den Ernstfall: Umlaute in Dateinamen kommen in einer anderen
Unicode-Form zurueck, als sie auf der Platte standen ("u" plus Trema statt "ue"
als ein Zeichen). Auf einem Mac ist das egal, dort meint beides dieselbe Datei.
Auf einem Linux-Rechner waeren es zwei verschiedene - dort also besser nicht
zurueckspielen, sonst finden die Verweise zwischen den Notizen einander nicht
mehr.

Erst hineinsehen, ohne etwas auszupacken:

    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \\
      -pass file:$HOME/.vault-sicherung-schluessel \\
      -in vault-Mo.tar.gz.enc | tar -tzf - | head
"""


def anleitung_hinlegen() -> None:
    """Neben die Sicherung, nicht in sie hinein.

    Eine Sicherung, deren Rueckweg man erst suchen muss, wird im Ernstfall
    nicht zurueckgespielt.
    """
    for ordner in (LOKAL, AUSSER_HAUS):
        try:
            ordner.mkdir(parents=True, exist_ok=True)
            (ordner / "WIEDERHERSTELLEN.txt").write_text(ANLEITUNG, encoding="utf-8")
        except OSError:
            pass


def main() -> int:
    heute = date.today()
    sag(f"\n[{datetime.now().replace(microsecond=0)}] Vault-Sicherung")

    try:
        schluessel_pruefen()
        if not QUELLE.is_dir():
            raise SicherungFehler(f"Quelle fehlt: {QUELLE}")

        erwartet = dateien_zaehlen(QUELLE)
        namen = [f"vault-{WOCHENTAGE[heute.weekday()]}.tar.gz.enc"]
        if heute.day == 1:
            namen.append(f"vault-monat-{heute.month:02d}.tar.gz.enc")

        LOKAL.mkdir(parents=True, exist_ok=True)
        griff, zwischen = tempfile.mkstemp(dir=LOKAL, prefix=".", suffix=".tmp")
        os.close(griff)
        zwischenweg = Path(zwischen)
        try:
            packen_und_verschluesseln(zwischenweg)
            gefunden = pruefen(zwischenweg, erwartet)
            groesse = zwischenweg.stat().st_size / 1048576
            sag(f"  {gefunden} von {erwartet} Dateien · {groesse:.1f} MB verschlüsselt")
            for zeile in ablegen(zwischenweg, namen):
                sag(f"  {zeile}")
            anleitung_hinlegen()
        finally:
            zwischenweg.unlink(missing_ok=True)

    except SicherungFehler as fehler:
        sag(f"  Abgebrochen: {fehler}")
        sag("  Die vorhandenen Sicherungen bleiben unangetastet.")
        return 1
    except Exception as fehler:
        sag(f"  Fehlgeschlagen: {type(fehler).__name__}: {fehler}")
        sag("  Die vorhandenen Sicherungen bleiben unangetastet.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
