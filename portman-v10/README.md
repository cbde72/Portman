# Portman V10 – vollständiges Startpaket

Stand: 6. November 2026. Enthält einen schmalen Importprototyp und eine lokale Web-Testoberfläche für genau diesen Vorschaupfad. Noch keine Portfolioanwendung und keine technische V09-Sandbox. Der V10-Branch ist auf `origin` gepusht; es gibt kein Release und keinen Merge. Parser-PR #68 ist separat.

## Lokaler Integrationsstand

Das Paket ist im separaten Worktree
`C:\Users\chris\Desktop\programming\PortmanV10` auf dem
Branch `codex/portman-v10-foundation` integriert. Ausgangsstand ist
`origin/main` bei `816034a`; der V10-Branch wurde gepusht, aber nicht gemergt oder als Release veröffentlicht. Die
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
- docs/Schnittstelle.md, Datenmodell.md, Parserpruefung.md: fachliche Verträge und Grenzen der Teilimplementierung.
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

### Synthetischer Stammdaten- und Eröffnungsablauf

Mit der eigenen V10-Umgebung aus dem Paketordner:

    $env:PYTHONPATH = 'src'
    .\.venv\Scripts\python.exe scripts/demo_master_data.py

Das Terminalbeispiel legt in einer temporären SQLite-Datei Giro-, Tagesgeld-, Depot- und Kryptokonto sowie ein Wertpapier und einen Coin an. Es speichert Geld- und Mengeneröffnungen, schließt den Zugriff durch Wegwerfen des Stores und liest über eine neue Store-Instanz wieder. Jede Zeile zeigt erwarteten und tatsächlich gespeicherten Wert. Die temporäre Datenbank wird danach gelöscht. Es werden keine echten Daten verwendet.

### Echte comdirect-PDF-Vorschau (ohne Buchung)

Nach Installation des fest gepinnten Parsers in der eigenen V10-.venv:

    $env:PYTHONPATH = 'src'
    .\.venv\Scripts\python.exe scripts/demo_import_preview.py --pdf 'C:\Pfad\zum\Beleg.pdf'

Ohne `--data-dir` erstellt der Befehl ein isoliertes temporäres Datenverzeichnis. Für eine ausdrücklich gewünschte lokale Wiederöffnung kann ein separates Testverzeichnis angegeben werden. Das Original wird nur gelesen; in V10 werden Kopie, Job und normalisierte Vorschau gespeichert. Vorhandene Dateien im gewählten Datenverzeichnis werden nicht gelöscht.

Geprüfter synthetischer comdirect-Wertpapierkauf zeigt beispielsweise:

    Job: needs_review (1/1 Dokumente, Fortschritt 100%)
    Beleg: purchase.pdf | Typ: comdirect Wertpapierkauf | Paket/API: 0.7.0/0.6 | Plugin: user.comdirect-ertraege 2.0 | Handler: wertpapierkauf | Schema: 1.6.0 | Ergebnis: needs_review
    Wirkung cash: -126.5 EUR
    Wirkung quantity: 0.125 DE0008474511
    Detail fee/provision: 1.5 EUR (INCLUDED_IN_SETTLEMENT; keine zusätzliche Geld-/Mengenwirkung)
    Keine Buchung übernommen; es wurden keine produktiven Geld- oder Mengenpositionen angelegt.

Reale Dokumente wurden nicht zur Prüfung herangezogen. Bei unbekannter Konto-/Instrumentkennung bleibt die Zuordnung offen. Nur comdirect Wertpapierkauf hat den vollständigen Bewegungspfad; comdirect MiFID-Kosteninformation wird ausschließlich ohne Buchungsbewegung angezeigt, weitere erkannte Dokumenttypen bleiben nicht freigegeben.

### Lokale Web-Testoberfläche

Voraussetzungen in der V10-`.venv`: installierter Parser-Pin und Flask-Webabhängigkeit. Falls Flask fehlt, zuerst im Paketordner ausführen:

    .\.venv\Scripts\python.exe -m pip install -e '.[web]'

Start aus dem Paketordner mit PowerShell:

    .\start_v10_web.ps1

Das Skript nutzt nur `.venv`, prüft Flask und `portman-parsers`, startet ausschließlich auf `127.0.0.1:8765` und öffnet den Browser erst nach erfolgreicher Health-Prüfung. Es legt beziehungsweise verwendet `data/web-test/v10.sqlite` und `data/web-test/documents/`; vorhandene Dateien werden nicht gelöscht. Branch, Commit und Profil sind in der Seite sichtbar. Strg+C beendet den Server.

Prüfanleitung: Starten → Kauf-PDF auswählen → erkannte Geld-/Mengenwerte und Gebühr vergleichen → Original-PDF öffnen. Für eine Übernahme müssen Kandidaten ausdrücklich geprüft werden; offene Konflikte blockieren sie. Die Oberfläche ist ein isoliertes Testprofil. Fachliche Referenzzuordnung, transaktionaler Commit und Importbericht sind enthalten; vollständige Kontenübersicht, Buchungssuche und Rücknahme (V10-16) fehlen. Eine fehlende erkannte Bankreferenz bleibt bewusst offen.

Linux:

    PYTHONPATH=src python3 -m unittest discover -s tests -v

Python >=3.11 erforderlich. Die Unittests decken Verträge, Referenzfälle, den SQLite-Persistenzprototyp und den echten synthetischen comdirect-PDF-Vorschaupfad ab. Importcommit und Indexpflege sind mit synthetischen SQLite-Integrationsfällen geprüft, nicht produktiv freigegeben. Rücknahme und Nutzerabnahme bleiben offen.

`requirements-parser.txt` bindet den vollständigen Commit aus dem offenen
Parser-PR. `requirements-parser-local.txt` bietet denselben Inhalt aus dem
separaten Parser-Worktree für Offline- oder lokale Prüfungen. Beide Varianten
bauen ein Wheel und erzeugen keine editable Parserabhängigkeit.

## Bewusst keine weiteren Toolkonfigurationen

Keine erfundenen Modellnamen, API-Schlüssel, automatischen Multiagentenketten oder pauschal freigegebenen Shellrechte. OpenCode-/Claude-Berechtigungen und eine echte Sandbox werden passend zur installierten Version und Umgebung eingerichtet. Prompt-Caching wird nicht über diese Markdown-Dateien eingeschaltet; kompakte stabile Regeln unterstützen effiziente Kontextnutzung.

## Grenzen der lokalen Web-Testoberfläche

Der Webstarter unter `start_v10_web.ps1` öffnet den Import-, Prüf- und Übernahmeablauf mit getrenntem Testprofil. Kontenübersicht, Buchungssuche, vollständige Import-Rücknahme (V10-16) und Nutzerabnahme sind weiterhin offen.
