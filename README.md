# Medizin-Studium

Studien-App für den Modellstudiengang Humanmedizin der HHU Düsseldorf.

Läuft als lokales Programm auf dem Mac und liest den Obsidian-Vault
`~/Vault/2.Brain/Tills 2.Gehirn`. Der Vault ist die Quelle der Wahrheit —
die App ist eine Sicht darauf und schreibt nur, was angeklickt wurde.

Vault und Projekt liegen bewusst **nicht** in `~/Documents`: macOS verweigert
dort jedem Hintergrundprozess den Zugriff, und der tägliche Schnappschuss
läuft im Hintergrund.

## Starten

```bash
python3 -m medizin_studium
```

Dann <http://127.0.0.1:8770> öffnen.

## Täglicher Schnappschuss

`~/Vault/Studium-unterwegs.html` ist eine Lese-Ansicht für unterwegs — eine
einzige Datei, Stil und Schriften eingebettet, ohne Klausurergebnisse und ohne
Anwesenheit. Sie wird dreimal täglich neu geschrieben:

```bash
cp betrieb/de.tillbrands.studium-schnappschuss.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/de.tillbrands.studium-schnappschuss.plist
```

Protokoll: `~/Library/Logs/studium-schnappschuss.log`. Von Hand bauen geht mit
`python3 -m medizin_studium.schnappschuss`.

**Warum nichts davon in `~/Documents` liegen darf:** macOS gibt einem von
launchd gestarteten Prozess keinen Zugriff auf `~/Documents`, `~/Desktop`,
`~/Downloads` und iCloud Drive. Der erste Versuch scheiterte an der eigenen
`pyvenv.cfg`, bevor auch nur eine Zeile eigener Code lief. Aus dem Terminal
gestartet fällt das nie auf — dort erbt der Befehl die Zustimmung des
Terminals.

Scheitert ein Lauf, bleibt die vorhandene Datei stehen. Sie rechnet ihr Alter
beim Öffnen selbst aus und sagt ab 36 Stunden, dass sie überholt ist.

## Was hier NICHT liegt

Der Vault und alle Zugangsdaten. Dieses Repository enthält ausschließlich
Programmcode. Siehe `.gitignore`.

## Aufbau

| Datei | Zweck |
|---|---|
| `medizin_studium/vault.py` | Vault lesen und zeilenweise schreiben |
| `medizin_studium/server.py` | lokaler HTTP-Server |
| `medizin_studium/web/` | Oberfläche |
| `entwurf/` | Design-Entwurf als Referenz (nicht ausgeliefert) |
