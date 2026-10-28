# Portman V09 – GUI-Redesign und systematische Entschlackung

Datum: 28.10.2026
Arbeitsverzeichnis: `C:\Users\chris\Desktop\programming\PortmanNL`
Branch: `main`
Ausgangscommit: `1016e13125a983628ee825c47aa798b41302f539`
`origin/main`: `1016e13125a983628ee825c47aa798b41302f539`

## 1. Ergebnis

Die Standardoberfläche wurde auf die fünf fachlichen Hauptbereiche **Übersicht**, **Depots**, **Konten**, **Transaktionen** und **Auswertungen** reduziert. Alle weiterhin benötigten Spezialfunktionen bleiben erreichbar: seltene und technische Funktionen wurden in einen persistenten Expertenmodus oder in fachlich passende Untermenüs verschoben. Der bestehende Dateiimport ist zusätzlich als hervorgehobene zentrale Aktion in der Seitennavigation verfügbar.

Es wurden keine Parser, OCR-Komponenten, Steuer-/FIFO-Berechnungen, Bewertungslogiken, Produktdaten oder produktiven Datenbanken verändert. Es erfolgten weder Commit noch Push.

## 2. Technischer Sicherungsstand

Vor den Änderungen wurden die betroffenen Code- und Testdateien außerhalb des Repositorys gesichert:

`C:\Users\chris\Desktop\Portman_GUI_Redesign_Backup_20261028_0015`

Das dortige `SHA256_MANIFEST.csv` wurde nach Abschluss erneut geprüft. Ergebnis: **16 von 16 Dateien stimmen hinsichtlich Existenz, Dateigröße und SHA-256-Prüfsumme überein**.

## 3. GUI-Inventar und Klassifikation

| Bereich/Funktion | Ausgangslage | Kategorie | Umsetzung |
| --- | --- | --- | --- |
| Übersicht | Fachliche Startseite | KEEP | Als erster Hauptbereich beibehalten |
| Depots | Bestände und Positionen | KEEP | Als Hauptbereich beibehalten |
| Konten | Kontoübersicht | KEEP | Als Hauptbereich beibehalten |
| Transaktionen | Historie/Buchungen | KEEP | Als Hauptbereich beibehalten |
| Auswertungen | Analysen und Diagramme | KEEP | Als Hauptbereich beibehalten |
| Grid, Performance, Erträge/Kosten, Markt, Rebalancing, ETF | Sechs zusätzliche direkte Navigationseinträge | MOVE | Unter „Weitere Auswertungen“ gebündelt; weiterhin erreichbar |
| Dateiimport | Über Menü erreichbar | KEEP / SIMPLIFY | Bestehende Aktion zusätzlich als zentraler blauer Import-Button verfügbar |
| Spezialimporte | Direkt in Standardmenüs sichtbar | MOVE | Im Expertenmodus verfügbar; bestehende Action-Verbindungen erhalten |
| Jobs, Wiederaufnahme, CSV-Profile und technische Importdetails | Standardmäßig sichtbar | MOVE | In den Expertenmodus verschoben |
| Markt-Zugangsdaten, Kurshistorie, Factsheets und ISIN-Namenssuche | Technische Spezialfunktionen | MOVE | In den Expertenmodus verschoben |
| Dock-/Bereichsschalter | 15 Einträge direkt im Ansicht-Menü | SIMPLIFY | Unter „Bereiche und Fenster“ zusammengefasst und dem Expertenmodus zugeordnet |
| Tabellen-/Graphen-Menü | Technische Darstellungsauswahl | MOVE | Im Expertenmodus verfügbar |
| Zeitraumsteuerung | In fachlich unpassenden Ansichten dauerhaft sichtbar | SIMPLIFY | Nur noch in Analyseansichten sichtbar |
| Tagesnavigation | Häufig benötigte Navigation | KEEP | Vorheriger Tag, Heute und nächster Tag bleiben standardmäßig verfügbar |
| Wochen-/Monatsnavigation | Seltenere Navigation | MOVE | Im Expertenmodus verfügbar |
| Positionsspalten | Neue Tabellen starteten mit vielen Detailspalten | SIMPLIFY | Weniger Standardspalten bei neuen/unbekannten Einstellungen; vorhandene Benutzerpräferenzen bleiben maßgeblich |
| Kopieren, Filtern, Konflikt- und Warnungsdetails | Fachlich und operativ notwendig | KEEP | Unverändert erreichbar |
| Importdialog | Mehrere technisch benannte Schritte | SIMPLIFY | Vier verständliche Arbeitsschritte; Detailtabs und Quellname bleiben erhalten |
| Layout-Preset-Auswahl in Toolbar und Menü | Doppelte Bedienmöglichkeit | REMOVE_DUPLICATE | Toolbar-Duplikat entfernt; Menüfunktion bleibt erhalten |
| Theme, Fenster-, Dock- und Tabelleneinstellungen | Persistente Benutzereinstellungen | KEEP | Bestehende Persistenz beibehalten |

## 4. Neue Bedienhierarchie

Standardmodus:

1. Übersicht
2. Depots
3. Konten
4. Transaktionen
5. Auswertungen
6. Weitere Auswertungen als kompaktes Untermenü
7. Zentraler Import-Button

Expertenmodus:

- Aktivierung über `Ansicht → Expertenfunktionen anzeigen`
- Einstellung wird in den bestehenden Anwendungseinstellungen gespeichert
- Blendet Spezialimporte, technische Importwerkzeuge, Markt-/ETF-Werkzeuge, Detailansichten, Kapitalmaßnahmen, erweiterte Zeitraumnavigation und Dock-Verwaltung ein
- Entfernt keine QAction und ersetzt keine bestehende Signalverbindung

## 5. Importablauf

Die Tabs des bestehenden Importdialogs wurden ohne Änderung der Importlogik fachlich neu benannt:

1. `Dateien auswählen`
2. `Konten zuordnen`
3. `Buchungen prüfen`
4. `Validierung · <Quelle>`

Original-/Hinweisdetails und MiFID-II-Kosten bleiben als Detailtabs erreichbar. Der Quellname, beispielsweise Baader, comdirect oder ING, bleibt im Validierungstab sichtbar.

## 6. Vorher-/Nachher-Nachweis

- Vorher: `test_reports/gui_redesign/before.png`
  SHA-256: `1159688FFA5657570A170CFAC6128FFB7B1DADB22FD2F6195523E87658D2B346`
- Nachher: `test_reports/gui_redesign/after.png`
  SHA-256: `CF9A2CF0AA2CC6E33F95FEDE206B6C8FC1770EEAE4A64AA338DF147609D51D17`

Die Screenshots wurden mit einer realen `MainWindow`-Instanz und einer synthetischen Testdatenbank erzeugt. Wegen des Offscreen-Qt-Renderings können Schriftzeichen in der Bilddatei eingeschränkt dargestellt sein; Aufbau, Sichtbarkeit und Anordnung sind prüfbar.

## 7. Geänderte Dateien

Produktionscode:

- `src/portman/workspace.py`
- `src/portman/theme.py`
- `src/portman/gui/shell_menus.py`
- `src/portman/gui/content_docks.py`
- `src/portman/gui/appearance.py`
- `src/portman/gui/main_window_v09.py`
- `src/portman/preferences_v09.py`
- `src/portman/import_preview.py`

Tests:

- `tests/test_gui_components.py`
- `tests/test_baader_dialog.py`
- `tests/test_comdirect_banking.py`
- `tests/test_ing_banking.py`

Dokumentation/Nachweis:

- `test_reports/gui_redesign/before.png`
- `test_reports/gui_redesign/after.png`
- `test_reports/portman_v09_gui_redesign_20261028.md`

Code-/Testdiff ohne Bericht und Bilder: **12 Dateien, 193 Ergänzungen, 41 Entfernungen**.

## 8. Automatisierte Sicherheits- und Funktionstests

Gezielte GUI- und Importdialogtests:

```text
85 passed in 31.67s
```

Zusätzliche gezielte GUI-/Funktionssuite während der Umsetzung:

```text
119 passed, 2 skipped
```

Syntaxprüfung:

```powershell
python -m compileall -q src
```

Ergebnis: erfolgreich, keine Ausgabe.

Ruff-Namens- und Importprüfung:

```powershell
python -m ruff check src --select F
```

Ergebnis: `All checks passed!`

Vollständige Regression:

```powershell
python -m pytest -q --basetemp tmp/pytest_gui_cleanup_final
```

Ergebnis:

```text
1225 passed, 16 skipped, 2 warnings, 5 subtests passed in 578.35s
```

Die zwei Warnungen stammen aus der bereits vorhandenen Verwendung von `QSortFilterProxyModel.invalidateFilter()` in `src/portman/tax_detail_view.py`. Diese Datei wurde im Redesign nicht geändert.

Der neue Reichweitentest prüft insbesondere:

- exakt fünf sichtbare Hauptnavigationseinträge,
- sichtbaren und verbundenen zentralen Import,
- verborgene Expertenaktionen im Standardmodus,
- vollständige Erreichbarkeit der geprüften Legacy-Aktionen im Expertenmodus,
- vorhandene Signalempfänger der geprüften Aktionen,
- persistierten Expertenmodus,
- korrekte Zuordnung weiterer Analyseseiten zu „Auswertungen“,
- kontextabhängige Sichtbarkeit der Zeitraumsteuerung.

## 9. Git- und Datenschutzprüfung

- Branch und `origin/main` standen zu Beginn beide auf `1016e13125a983628ee825c47aa798b41302f539`.
- Bestehende unversionierte Auditberichte, PDFs, SQLite-/Temporärdaten und Cleanup-Werkzeuge wurden nicht verändert oder zur Aufnahme vorgesehen.
- Die produktive Datenbank `data/v09/portfolio.sqlite` wurde nicht geöffnet, migriert oder verändert.
- Keine Original-PDFs oder privaten Auditdaten gehören zur vorgeschlagenen Commit-Auswahl.
- `git diff --check` meldet keine Diff-Fehler; lediglich Hinweise auf eine zukünftige CRLF-zu-LF-Normalisierung bei vier vorhandenen Arbeitskopien.

## 10. Risiken und Grenzen

1. Eine visuelle manuelle Abnahme unter dem regulären Windows-Qt-Renderer bleibt sinnvoll, da die automatisierten Screenshots im Offscreen-Modus erzeugt wurden.
2. Bereits gespeicherte Tabellenpräferenzen haben absichtlich Vorrang. Die reduzierte Standardspaltenauswahl wirkt daher vor allem auf neue bzw. noch nicht konfigurierte Tabellen.
3. Der Expertenmodus steuert Sichtbarkeit, nicht Berechtigungen. Das entspricht dem Ziel einer übersichtlicheren GUI und ist keine Sicherheitsgrenze.
4. Die zwei Qt-Deprecation-Warnungen sind technisch offen, aber unabhängig vom Redesign und ohne Testausfall.

## 11. Release-Empfehlung

Die Änderungen sind aufgrund der vollständigen grünen Regression, der geprüften Aktionsreichweite und des extern verifizierten Sicherungsstands **für eine lokale Commit-Erstellung freigabefähig**. Vor einem späteren Push wird eine kurze visuelle Windows-Abnahme im Standard- und Expertenmodus empfohlen.

Es wurde bewusst kein Commit und kein Push ausgeführt.
