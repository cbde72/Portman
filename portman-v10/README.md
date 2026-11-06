# Portman V10 – vollständiges Startpaket

Stand: 6. November 2026. Enthält Anweisungen, Konfiguration und vorbereitetes Grundgerüst. Noch keine startbare Portfolio- oder Webanwendung, kein angelegter Remote-Branch und keine technische V09-Sandbox.

## Lokaler Integrationsstand

Das Paket ist im separaten Worktree
`C:\Users\chris\Desktop\programming\PortmanNL-portman-v10-foundation` auf dem
lokalen Branch `codex/portman-v10-foundation` integriert. Ausgangsstand ist
`origin/main` bei `816034a`; es wurde nichts veröffentlicht oder gemergt. Die
Ausführungsumgebung besitzt uneingeschränkten Dateisystemzugriff. Worktree,
Branch und diese Regeln sind organisatorische Grenzen, keine technische
Sandbox. Die tatsächlich installierte Parserquelle und deren abweichender
Quellstand sind in `docs/Parserpruefung.md` dokumentiert.

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

    powershell -NoProfile -File scripts/Run-Checks.ps1

Oder direkt:

    $env:PYTHONPATH = 'src'
    python -m unittest discover -s tests -v

Linux:

    PYTHONPATH=src python3 -m unittest discover -s tests -v

Python >=3.11 erforderlich. Vier vorhandene Tests prüfen nur erste Vertragsgrundlagen. Sie sind kein Nachweis für Import, Rücknahme oder Geschwindigkeit. Der Python-Testlauf wurde bei der Paketerstellung unter Linux ausgeführt; PowerShell-Skript und VS-Code-Aufgabe dort nicht ausgeführt.

## Bewusst keine weiteren Toolkonfigurationen

Keine erfundenen Modellnamen, API-Schlüssel, automatischen Multiagentenketten oder pauschal freigegebenen Shellrechte. OpenCode-/Claude-Berechtigungen und eine echte Sandbox werden passend zur installierten Version und Umgebung eingerichtet. Prompt-Caching wird nicht über diese Markdown-Dateien eingeschaltet; kompakte stabile Regeln unterstützen effiziente Kontextnutzung.

## Spätere Testbarkeit

Nach jedem abgeschlossenen Schritt Referenzablauf und kurze Prüfanleitung. Sobald der Webserver implementiert ist, wird ein echter Ein-Klick-Starter ergänzt, der die Testdatenbank nutzt und den Browser öffnet. Einen funktionslosen Webstarter enthält dieses Paket ausdrücklich nicht.
