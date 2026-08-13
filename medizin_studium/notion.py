"""Notion über ein eigenes Token.

Der Chat-Connector reicht nicht: Er kennt weder ``last_edited_time`` noch
Webhooks, kann also nicht sagen, *was sich seit gestern geändert hat*
(``CLAUDE.md`` §14). Für den Kanal Notion → Vault braucht es deshalb einen
eigenen Zugang.

**Bewusst eine Verbindung („internal integration"), kein persönliches Token.**
Ein persönliches Token handelt als Till und sieht damit alles: Journal,
Gewohnheiten, Ziele, die ganze Physio-Ausbildung. Eine Verbindung sieht
ausschließlich, was ausdrücklich mit ihr geteilt wurde — hier also nur die
Vorlesungsnotizen. Der zusätzliche Klick beim Einrichten ist genau der Preis
dafür, und er ist ihn wert.

Geschrieben wird nur in einen markierten Abschnitt der Seite; Tills
handgeschriebener Teil wird nie angefasst (§14).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from .konfig import dienst, im_vault

BASIS = "https://api.notion.com/v1"
VERSION = "2022-06-28"          # Notion verlangt eine feste Fassung im Kopf
ZEITSCHRANKE = 15.0

# Nur dieser Abschnitt gehört der App. Alles darüber und darunter ist Tills.
ABSCHNITT = "Aus dem Vault (nicht von Hand ändern)"


class NotionFehler(Exception):
    """Kein Zugang, kein Netz, oder Notion sagt Nein."""


def token_datei() -> Path:
    return im_vault(dienst("notion").get("token", "Planer/Sync/notion-token.json"))


def token() -> str:
    pfad = token_datei()
    if not pfad.exists():
        raise NotionFehler(
            f"Kein Notion-Token. Erwartet in {pfad}\n"
            'Format: {"token": "ntn_…"}'
        )
    try:
        wert = json.loads(pfad.read_text(encoding="utf-8")).get("token", "").strip()
    except json.JSONDecodeError as fehler:
        raise NotionFehler(f"{pfad} ist kein gültiges JSON: {fehler}") from fehler
    if not wert:
        raise NotionFehler(f"{pfad} enthält kein Feld 'token'")
    return wert


def eingerichtet() -> bool:
    try:
        token()
        return True
    except NotionFehler:
        return False


def _ruf(weg: str, verfahren: str = "GET", nutzlast: dict | None = None) -> dict:
    anfrage = urllib.request.Request(
        f"{BASIS}{weg}",
        method=verfahren,
        data=json.dumps(nutzlast).encode("utf-8") if nutzlast is not None else None,
        headers={
            "Authorization": f"Bearer {token()}",
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITSCHRANKE) as antwort:
            return json.loads(antwort.read())
    except urllib.error.HTTPError as fehler:
        roh = fehler.read().decode("utf-8", "replace")
        try:
            meldung = json.loads(roh).get("message", roh)
        except json.JSONDecodeError:
            meldung = roh
        if fehler.code == 401:
            raise NotionFehler("Token wird abgelehnt — falsch oder zurückgezogen.") from fehler
        if fehler.code == 404:
            raise NotionFehler(
                "Nicht gefunden. Fast immer heißt das: Die Seite ist nicht mit der "
                "Verbindung geteilt (••• → Verbindungen)."
            ) from fehler
        raise NotionFehler(f"Notion antwortet mit {fehler.code}: {meldung}") from fehler
    except (urllib.error.URLError, TimeoutError, OSError) as fehler:
        raise NotionFehler(f"Notion nicht erreichbar: {fehler}") from fehler


def geteilt() -> list[dict]:
    """Was die Verbindung überhaupt sehen darf.

    Eine leere Liste ist der Normalfall direkt nach dem Anlegen — und die
    häufigste Ursache dafür, dass später alles „nicht gefunden" meldet.
    """
    antwort = _ruf("/search", "POST", {"page_size": 50})
    gefunden = []
    for treffer in antwort.get("results", []):
        titel = "(ohne Titel)"
        if treffer.get("object") == "database":
            teile = treffer.get("title") or []
            titel = "".join(t.get("plain_text", "") for t in teile) or titel
        else:
            for wert in (treffer.get("properties") or {}).values():
                if wert.get("type") == "title":
                    titel = "".join(t.get("plain_text", "")
                                    for t in wert.get("title", [])) or titel
                    break
        gefunden.append({
            "art": treffer.get("object"),
            "id": treffer.get("id"),
            "titel": titel,
            "geaendert": treffer.get("last_edited_time"),
            "url": treffer.get("url"),
        })
    return gefunden


def zustand() -> dict:
    """Für die Einstellungsseite. Wirft nie."""
    if not eingerichtet():
        return {"stand": "nicht_eingerichtet",
                "text": f"Kein Token in {token_datei()}"}
    try:
        geteilte = geteilt()
    except NotionFehler as fehler:
        return {"stand": "fehler", "text": str(fehler)}
    return {
        "stand": "ok" if geteilte else "nichts_geteilt",
        "geteilt": geteilte,
        "text": None if geteilte else
                "Das Token ist gültig, aber es ist nichts mit der Verbindung "
                "geteilt. In Notion: ••• → Verbindungen → Medizin-Studium.",
    }


def _main(argv: list[str]) -> int:
    befehl = argv[1] if len(argv) > 1 else "pruefen"
    if befehl != "pruefen":
        print("Befehle: pruefen")
        return 2

    print(f"Tokendatei: {token_datei()}")
    if not eingerichtet():
        print("  fehlt noch.")
        return 1
    try:
        wer = _ruf("/users/me")
    except NotionFehler as fehler:
        print(f"\n{fehler}\n")
        return 1
    art = wer.get("bot", {}).get("owner", {}).get("type")
    print(f"  Token gültig — {wer.get('name') or wer.get('id')}"
          f"{' (Verbindung, workspace-gebunden)' if art == 'workspace' else ''}")
    if art == "user":
        print("  ACHTUNG: Das ist ein persönliches Token. Es sieht alles, was du "
              "siehst — auch Journal, Ziele und Physio. Für diese App war eine "
              "Verbindung vorgesehen, die nur die Vorlesungsnotizen sieht.")

    geteilte = geteilt()
    if not geteilte:
        print("  Sichtbar: nichts.")
        print("  → In Notion die Datenbank öffnen, ••• oben rechts, "
              "Verbindungen, 'Medizin-Studium' hinzufügen.")
        return 1
    print(f"  Sichtbar: {len(geteilte)} Einträge")
    for g in geteilte[:20]:
        print(f"    {g['art']:<9} {g['titel'][:44]:<44} {g['id']}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
