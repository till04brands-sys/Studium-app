# Medizin-Studium

Studien-App für den Modellstudiengang Humanmedizin der HHU Düsseldorf.

Läuft als lokales Programm auf dem Mac und liest den Obsidian-Vault
`~/Documents/2.Brain/Tills 2.Gehirn`. Der Vault ist die Quelle der Wahrheit —
die App ist eine Sicht darauf und schreibt nur, was angeklickt wurde.

## Starten

```bash
python3 -m medizin_studium
```

Dann <http://127.0.0.1:8770> öffnen.

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
