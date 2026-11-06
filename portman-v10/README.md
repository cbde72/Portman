# Portman V10 – vollständiges Startpaket

Stand: 6. November 2026. Enthält Anweisungen, Konfiguration und vorbereitetes Grundgerüst. Noch keine startbare Portfolio- oder Webanwendung und keine technische V09-Sandbox. Der Parserbranch wurde gepusht und PR #68 gegen `main` eröffnet; kein Merge oder Release-Tag.

## Lokaler Integrationsstand

Das Paket ist im separaten Worktree
`C:\Users\chris\Desktop\programming\PortmanV10` auf dem
lokalen Branch `codex/portman-v10-foundation` integriert. Ausgangsstand ist
`origin/main` bei `816034a`; V10 wurde nicht veröffentlicht oder gemergt. Die
Ausführungsumgebung besitzt uneingeschränkten Dateisystemzugriff. Worktree,
Branch und diese Regeln sind organisatorische Grenzen, keine technische
Sandbox. Der für V10 fixierte Parserstand ist im offenen Parser-PR enthalten;
der V10-Pin wurde in einer frischen Umgebung geprüft. Details stehen in
`docs/Parserpruefung.md`.

## Einrichten

1. ZIP in ein separates Arbeitsverzeichnis entpacken; vorhandene Dateien nicht blind überschreiben.
2. Bei Integration in cbde72/Portman den enthaltenen Ordner portman-v10/ auf einem eigenen Branch übernehmen. Regeln im Repository-Root erhalten, Widersprüche konkret klären.
3. VS Code direkt mit dem Ordner portman-v10/ öffnen. Codex/OpenCode/Claude dort starten. Das begrenzt allein noch keine Dateirechte.
4. docs/STARTAUFTRAG.md verwenden; docs/TASKS.md ist die Fortschrittsliste.

## Inhalte

- AGENTS.md: gemeinsame Regeln einschließlich effizienter Kontextnutzung, Review, V09-Grenzen und Nutzerprüfung.
- CLAUDE.md: importiert AGENTS.md, keine doppelte Architekturpflege.
- docs/BAUPLAN.md: konsolidierter Bauplan 3.2 einschließlich aller aktuellen Anforderungen.
- docs/TASKS.md: priorisierte Aufgaben mit Fertigkriterien und getrenntem Prüfnachweis.
- docs/Schnittstelle.md, Datenmodell.md, Parserpruefung.md: vorbereitete fachliche Verträge, keine fertige Implementierung.
- pyproject.toml, src/, tests/: eigenständiges Python-Grundgerüst ohne zusätzliche Laufzeitabhängigkeiten.
- scripts/Run-Checks.ps1: Windows-Prüfskript. .vscode/tasks.json: entsprechende VS-Code-Testaufgabe. .gitignore: Laufzeitdaten und Buildausgaben ausschließen.

## Vorhandene Prüfungen starten

Windows PowerShell aus dem Paketordner:

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e .
    .\.venv\Scripts\python.exe -m pip install -r requirements-parser.txt
    powershell -NoProfile -File scripts/Run-Checks.ps1

Oder direkt:

    $env:PYTHONPATH = 'src'
    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

Linux:

    PYTHONPATH=src python3 -m unittest discover -s tests -v

Python >=3.11 erforderlich. Vier vorhandene Tests prüfen nur erste Vertragsgrundlagen. Sie sind kein Nachweis für Import, Rücknahme oder Geschwindigkeit. Der Python-Testlauf wurde bei der Paketerstellung unter Linux ausgeführt; PowerShell-Skript und VS-Code-Aufgabe dort nicht ausgeführt.

`requirements-parser.txt` bindet den vollständigen Commit aus dem offenen
Parser-PR. `requirements-parser-local.txt` bietet denselben Inhalt aus dem
separaten Parser-Worktree für Offline- oder lokale Prüfungen. Beide Varianten
bauen ein Wheel und erzeugen keine editable Parserabhängigkeit.

## Bewusst keine weiteren Toolkonfigurationen

Keine erfundenen Modellnamen, API-Schlüssel, automatischen Multiagentenketten oder pauschal freigegebenen Shellrechte. OpenCode-/Claude-Berechtigungen und eine echte Sandbox werden passend zur installierten Version und Umgebung eingerichtet. Prompt-Caching wird nicht über diese Markdown-Dateien eingeschaltet; kompakte stabile Regeln unterstützen effiziente Kontextnutzung.

## Spätere Testbarkeit

Nach jedem abgeschlossenen Schritt Referenzablauf und kurze Prüfanleitung. Sobald der Webserver implementiert ist, wird ein echter Ein-Klick-Starter ergänzt, der die Testdatenbank nutzt und den Browser öffnet. Einen funktionslosen Webstarter enthält dieses Paket ausdrücklich nicht.
