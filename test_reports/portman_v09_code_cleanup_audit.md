# Portman V09 – Code-Cleanup-Audit

Prüfdatum: 24.10.2026

Branch: `refactor/v09-code-cleanup`

Ausgangscommit: `f2a60f2a0c50573e8a8cd50394eed1743c089a9f`
(`Fix clean reimport tax reconciliation (#27)`)

## Ergebnis

Die erste risikoarme Cleanup-Phase ist abgeschlossen. Sie entfernt
nachweislich unbenutzten beziehungsweise unerreichbaren Code, reduziert einen
redundanten Datenbank-Read und vereinfacht kleine Kontrollflüsse. Fachliche
Berechnungen, öffentliche Datenverträge, Datenbankschema, Migrationen,
Import-Deduplizierung und Cashflow-Semantik wurden nicht geändert.

Die Arbeit erfolgte im separaten Worktree
`.worktrees/v09-code-cleanup`. Dadurch blieben der Haupt-Worktree und die
parallel laufende PDF-Parser-Testsuite V2 unberührt. Dateien unter
`pdf_plugins/`, PDF-Parser/-Registry, Textextraktion und OCR wurden weder
geändert noch formatiert.

## Modul- und Funktionsinventar

AST-Inventar des Ausgangsstands:

| Bereich | Python-Module | Codezeilen | Top-Level-Funktionen | Klassen | Methoden/verschachtelte Funktionen |
|---|---:|---:|---:|---:|---:|
| `src/portman/` | 187 | 29.687 | 437 | 163 | 1.069 |
| `src/portfolio_v5/` | 21 | 5.042 | 115 | 28 | 91 |
| **Gesamt** | **208** | **34.729** | **552** | **191** | **1.160** |

Die Aufrufanalyse berücksichtigte Quelltext und Tests sowie ausdrücklich 444
Stellen mit Reflection, dynamischen Attributzugriffen, Qt-Signalbindungen,
Plugin-Discovery oder dynamischem Import. Ein Symbol wurde nicht allein wegen
fehlender statischer Direktaufrufe als unbenutzt bewertet.

## Klassifizierte Funde

### Sicher entfernbar

| Fund | Aufrufnachweis | Maßnahme |
|---|---|---|
| `pathlib.Path` in `tax_detail_view.py` | Ruff F401 und keine `Path`-Verwendung im Modul | Import entfernt |
| Rückgabewert von `create_v09_menus()` | Nur einer lokalen Variable zugewiesen; Variable danach nie gelesen | unnötige lokale Variable entfernt |
| Parameter `menu` von `install_v09_workflows()` | einzige Aufrufstelle und Methodendefinition geprüft; Nutzung ausschließlich im unerreichbaren Fallback | Parameter entfernt |
| Fallback-Zweig für unbekannte Workflow-Labels | Schleife iteriert über drei feste Labels, die vollständig abgedeckt sind | unerreichbaren Zweig entfernt |
| doppelte Bearbeiten-Menü-Zweige | beide Zweige führten bytegleich dieselben Aktionen aus | zusammengeführt |

### Vereinfachbar und umgesetzt

| Fund | Änderung | Verhaltensnachweis |
|---|---|---|
| zwei direkt aufeinanderfolgende `account_records()`-Reads in der Steuerlink-Nachverarbeitung | einmal lesen, beide Alias-Maps aus demselben Snapshot bilden | identische Inhalte, weniger Repository-/SQLite-Arbeit |
| verschachtelte Qt-Typprüfung in `GlobalCopySupport.eventFilter()` | Bedingungen zusammengeführt | gleiche Kurzschluss- und Aufrufsemantik |
| imperative Ergebnisliste in `available_portfolios()` | kompakte, weiterhin sortierte Listenbildung | gleiche Standardportfolio-Position und Filterbedingung |

### Weitere Prüfung erforderlich

Diese Kandidaten wurden bewusst nicht geändert:

- Drei gleich aussehende Transaktionsreferenz-Helfer in `asset_registry.py`,
  `repository_v09.py` und `portfolio_v5/settlement.py`. Eine Zusammenführung
  würde Abhängigkeitsrichtungen zwischen Registry, Repository und
  Settlement-Schicht verändern; zuerst ist ein neutraler, stabiler
  Identitätsbaustein samt API-Test nötig.
- `run_job()` und die zugehörigen `closeEvent()`-Implementierungen in
  `import_jobs.py` und `jobs_v09.py`. Sie unterscheiden sich bei
  Job-Center-Registrierung, Abbruchtexten und dem Verhalten bei leerem
  Ergebnis. Sie sind daher nur strukturell ähnlich, nicht identisch.
- Mehrere `_decimal()`/`_number()`-Helfer. Die Null-, Leerwert-, Fehler- und
  Endlichkeitssemantik ist unterschiedlich und fachlich relevant.
- 130 Funktionen mit Ruff-Cyclomatic-Complexity über 10. Besonders auffällig
  sind `Store.import_batch`, Transaktionsvalidierung, Importvorschau,
  Steuerübersicht und Performanceanalyse. Diese Bereiche benötigen
  Charakterisierungstests und gehören nicht in eine risikoarme erste Phase.
- Ähnliche Qt-Model-Methoden (`rowCount`, `columnCount`) und
  `open_position()`-Slots. Kleine Implementierungen rechtfertigen derzeit
  keine zusätzliche Basisklasse oder Mixin-Abhängigkeit.

### Beibehalten

- `pdf_plugins/_comdirect_finanzreport_legacy.py`: wird vom aktuellen
  Finanzreport-Core bei erkanntem Altformat dynamisch importiert. Der Parser
  ist erreichbar und durch PDF-Dokumentation sowie Tests belegt.
- `src/portman/gui/window_compat.py`: wird von Startmodul, GUI-Controllern,
  Importfluss, Portfolio- und Plugin-Dialogen verwendet. Die verzögerten
  Importe sind notwendig, weil Tests die Globals in `window_shell` patchen.
- `HAS_WEBENGINE`: aktiver optionaler Capability-Schalter mit externer
  Browser-Fallbackanzeige, kein veraltetes Feature-Flag.
- `schema_previous.py`, Migrations- und Kompatibilitätsvalidierung: Bestandteil
  der unterstützten Datenbank-/Sicherungsstrecke; nicht als Laufzeit-Totcode
  entfernbar.
- Qt-Slots, Eventfilter und Plugin-Einstiegspunkte ohne offensichtlichen
  Direktaufruf: wegen Signalbindung, Reflection und Discovery beibehalten.

## Durchgeführte Vereinfachungen und Umfang

Geändert wurden fünf Produktionsmodule. Insgesamt wurden 23 bestehende
Codezeilen entfernt und 14 Zeilen eingesetzt; netto sind es **9 Codezeilen
weniger**. Es wurden keine Dateien, Tests oder öffentlichen Klassen entfernt.

Die Modulabhängigkeiten bleiben bis auf den entfernten unbenutzten
`pathlib.Path`-Import unverändert. Es kamen keine neuen Imports, Pakete,
Basisklassen oder Abhängigkeiten hinzu. Die interne Methode
`install_v09_workflows()` besitzt keinen unbenutzten Parameter mehr; die
vollständige projektweite Aufrufsuche ergab genau eine kontrollierte
Aufrufstelle.

## Verhaltensauswirkungen

- Fachliche Ergebnisse: unverändert.
- Persistierte Daten und Schema: unverändert.
- Import- und PDF-Verhalten: unverändert.
- GUI-Menüstruktur, Aktionen und Shortcuts: unverändert.
- Repository-Verhalten: gleicher Account-Snapshot, aber nur ein statt zwei
  direkt aufeinanderfolgender Reads.
- Portfolio-Reihenfolge: weiterhin Standardportfolio zuerst, danach sortierte
  gültige Zusatzportfolios.

## Qualitätssicherung

Statische Prüfung:

```text
python -m compileall -q src/portman src/portfolio_v5
python -m ruff check src/portman src/portfolio_v5 --select F
All checks passed!
```

Gezielte Tests:

```text
42 passed, 2 warnings in 11.56s
```

Abgedeckt wurden Steuerdetailansicht, comdirect-P1-Integrität,
Copy-Unterstützung und Portfolioverwaltung. Die Warnungen sind bestehende
Qt-Deprecation-Warnungen zu `invalidateFilter()`.

Vollständige Pytest-Suite:

```text
1121 passed, 14 skipped, 2 warnings, 5 subtests passed in 402.55s
```

Der erste Worktree-Lauf ergab `1120 passed` und genau einen umgebungsbedingten
Fehler: Der VS-Code-Konfigurationstest erwartet eine
`${workspaceFolder}/.venv/Scripts/python.exe`, während ein neuer Git-Worktree
keine eigene virtuelle Umgebung enthält. Nach einer lokalen, nicht
versionierten Junction auf die bestehende Projekt-`.venv` bestand der einzelne
Test und anschließend die vollständige Suite. Es wurde keine
VS-Code-Konfiguration geändert.

## Empfehlungen für Cleanup-Phase 2

1. Einen kleinen, schichtenneutralen Transaktionsreferenz-Helfer entwerfen und
   die drei identischen Implementierungen erst nach API-/Importzyklustests
   zusammenführen.
2. `Store.import_batch()` entlang atomarer Validierungs-, Mapping- und
   Persistenzphasen zerlegen; vorher Golden-Master-Tests für Ergebnisobjekte,
   Fehlertexte und Rollbackverhalten ergänzen.
3. GUI-Controller mit hoher Komplexität anhand klarer View-/Service-Grenzen
   verkleinern, ohne Qt-Slots oder Objektlebenszyklen umzubenennen.
4. Zahlenparser nur nach einer Semantikmatrix für `None`, Leerstring, Null,
   NaN/Infinity und ungültige Texte vereinheitlichen.
5. Erst nach Abschluss von PDF-Parser-Test V2 eine separate Parser-/Registry-
   Analyse durchführen; sie war ausdrücklich nicht Bestandteil dieser Phase.
