# Portman V09 – Dead-Code-Cleanup

## 1. Executive Summary

Das Repository wurde konservativ mit Ruff, AST-/Tokenanalyse, Hashvergleich und projektweiter
Referenzsuche untersucht. Vier zweifelsfrei unbenutzte Symbole wurden entfernt: eine historische,
nicht exportierte V07-Initialisierungsfunktion und drei nie gelesene Konstanten. Registrierte
Renderer, Plugins, Qt-Callbacks, Migrationen und Kompatibilitätsadapter blieben erhalten. Es gab
keine Architektur-, Parser-, OCR-, Buchungs- oder Berechnungsänderung.

## 2. Ausgangszustand

- Branchbasis: `main` bei `9e53b79` (identisch mit `origin/main`, PR #39).
- Isolierter Worktree; lokale unversionierte Finanz- und Auditdaten im Hauptarbeitsbaum wurden
  weder gelesen noch verändert.
- Laufende Prozesse: kein Audit, pytest oder Ruff; nur VS-Code-isort-LSP.
- 369 Python-Dateien, 3.211 Funktionen/Methoden, 266 Klassen, 58.828 Python-Zeilen.
- `compileall`: PASS; Ruff `--select F`: 0 Befunde.
- Vollsuite mit isoliertem Temp-Verzeichnis: 1.195 bestanden, 15 übersprungen, ein
  umgebungsbedingter Fehler, weil die im Test erwartete Worktree-`.venv` nicht existiert;
  Laufzeit 418,94 s. Der erste Versuch gegen das globale Temp-Verzeichnis war wegen
  `WinError 5` nicht verwertbar.
- Vulture war nicht installiert und wurde nicht nachinstalliert.

## 3. Erkennungsmethodik

Analysiert wurden `src/`, `pdf_plugins/`, `tools/` und `tests/` mittels Ruff-F-Regeln,
`compileall`, AST-Inventar, Python-Tokenhäufigkeiten, SHA-256-Dateivergleich und `rg`-Suche.
Zusätzlich wurden Decorator-Registrierung, Plugin-Discovery, `importlib`, `getattr`/`setattr`,
Qt-Signalverbindungen, Re-Exports, CLI-Einstiegspunkte und Migrationsaufrufe manuell geprüft.
Eine reine Null-Referenz-Suche war ausdrücklich nicht entscheidend.

## 4. Kandidatenliste

| Datei | Symbol | Zeilen vorher | Kategorie | Referenzen | Dynamische Verwendung | Konfidenz | Risiko | Maßnahme |
|---|---|---:|---|---|---|---|---|---|
| `src/portman/persistence.py` | `initialize_v07` | 76–103 | Legacy/Dead Code | keine im gesamten Repository | kein Export, Registry-, CLI- oder Reflection-Hinweis | Hoch | Niedrig | DELETE |
| `src/portman/dynamic_renderer.py` | `SQUARIFY_AVAILABLE` | 29 | Unused Constant | nur Definition | keine | Hoch | Niedrig | DELETE |
| `pdf_plugins/comdirect_ertraege.py` | `MIFID_COST_MARKER` | 47 | Unused Constant | nur Definition | keine; Plugin verwendet spezifische Marker | Hoch | Niedrig | DELETE |
| `pdf_plugins/ing_wertpapiere.py` | `EXECUTION` | 58 | Duplicate/Unused Constant | nur Definition | keine; `EXECUTION_DAY` deckt beide Formen ab | Hoch | Niedrig | DELETE |
| `src/portman/dynamic_renderer.py` | `render_line` | 397 | Registry callback | Decoratorregistrierung | `_RENDERERS['line']` | Hoch | Hoch | KEEP |
| `src/portman/dynamic_renderer.py` | `render_area` | 451 | Registry callback | Decoratorregistrierung | `_RENDERERS['area']` | Hoch | Hoch | KEEP |
| `src/portman/dynamic_renderer.py` | `render_barh`, `render_bar`, `render_pie` | 580–670 | Registry callbacks | Decoratorregistrierung | Auswahl über Diagrammkonfiguration | Hoch | Hoch | KEEP |
| `src/portman/dynamic_renderer.py` | `render_scatter`, `render_candlestick`, `render_heatmap` | 678–927 | Registry callbacks | Decoratorregistrierung | Auswahl über Diagrammkonfiguration | Hoch | Hoch | KEEP |
| `src/portman/dynamic_renderer.py` | `render_boxplot`, `render_violin`, `render_histogram` | 1016–1084 | Registry callbacks | Decoratorregistrierung | Auswahl über Diagrammkonfiguration | Hoch | Hoch | KEEP |
| `src/portman/dynamic_renderer.py` | `render_treemap`, `render_radar`, `render_comparison` | 1184–1292 | Registry callbacks | Decoratorregistrierung | Auswahl über Diagrammkonfiguration | Hoch | Hoch | KEEP |
| `src/portman/renault_pdf_import.py` | Kompatibilitäts-Re-Export | 1–2 | Legacy Adapter | GUI, Preview und Tests | Stern-Re-Export des externen Plugins | Hoch | Hoch | KEEP |
| `src/portman/persistence.py` | `migrate_v07` | 76 ff. nach Cleanup | Migration | RepositoryV07, Schema-V08, Restore | datenbankversionsabhängig | Hoch | Hoch | KEEP |
| `src/portman/schema_previous.py` | V08-Migration | Modul | Legacy Migration | V09-Schemaaufbau | datenbankversionsabhängig | Hoch | Hoch | KEEP |
| `src/portman/gui/window_shell.py` | V06-Basisklasse | Modul | Legacy/Compatibility | V09-Entrypoint und GUI-Tests | Monkeypatch-/Basisklassenpfad | Hoch | Hoch | KEEP |
| `src/portman/repository_base.py` | `RepositoryV07` | Klasse | Legacy Base | `RepositoryV09`, Importjobs | Vererbung | Hoch | Hoch | KEEP |
| `pdf_plugins/*` | globale `plugin`-Objekte | jeweils Modulende | Plugin registration | Discovery statt Direktimport | dateibasierte Plugin-Discovery | Hoch | Hoch | KEEP |
| `tests/test_history_batch.py` | vier übersprungene Legacy-Tests | markierte Tests | Legacy tests | pytest collection | dokumentieren entfernte UI-Pfade | Mittel | Niedrig | REVIEW |
| historische Auditwerkzeuge außerhalb Git | V1/V2-Suite | lokal/unversioniert | Legacy tools | nicht Teil des Branchstands | lokale Auditbasis | Hoch | Hoch | REVIEW, nicht angefasst |

## 5. Entfernte Bestandteile

- `initialize_v07`: 28 Funktionszeilen plus Trennzeilen. Die aktive V09-Initialisierung erfolgt über
  `storage_v09.initialize`; `migrate_v07` bleibt für alte Datenbanken erhalten.
- `SQUARIFY_AVAILABLE`: nie gelesen; die interne Treemap-Implementierung benötigt kein
  `squarify`-Paket.
- `MIFID_COST_MARKER`: nie gelesen; die aktiven MiFID-Erkennungsregeln bleiben unverändert.
- `EXECUTION`: durch das tatsächlich verwendete, allgemeinere `EXECUTION_DAY` redundant.

## 6. Bewusst beibehaltene Komponenten

Alle Renderer, Plugin-Entrypoints, V07/V08-Schemamigrationen, Repository-Basisklassen,
GUI-Kompatibilitätsschichten und Renault-Re-Exports bleiben bestehen. Versionsnamen allein wurden
nicht als Löschbegründung verwendet. Private Auditdaten, Original-PDFs, Datenbanken, Logs und
lokale Backups wurden nicht angefasst.

## 7. Dynamische Abhängigkeiten

`dynamic_renderer` registriert Funktionen per Decorator; PDF-Plugins werden aus Dateien entdeckt;
Qt-Slots werden überwiegend über `signal.connect(method)` gebunden. GUI-Kompatibilität nutzt
Monkeypatching und Lazy Imports. Mehrere Modelle und Repositoryadapter verwenden `getattr` und
Vererbung. Diese Mechanismen erklären zahlreiche scheinbar niedrige statische Referenzzahlen.

## 8. Vorher-/Nachher-Kennzahlen

| Kennzahl | Vorher | Nachher |
|---|---:|---:|
| Python-Dateien | 369 | 369 |
| Funktionen/Methoden | 3.211 | 3.210 |
| Klassen | 266 | 266 |
| Python-Zeilen | 58.828 | 58.795 |
| geprüfte Hochkonfidenz-Kandidaten | 4 | 0 offen |
| entfernte Funktionen | 0 | 1 |
| entfernte Klassen | 0 | 0 |
| entfernte Konstanten | 0 | 3 |
| Git-Diff | – | 3 Einfügungen, 36 Löschungen |
| Ruff-F-Warnungen | 0 | 0 |

Die drei Einfügungen und vier der Löschungen in `dynamic_renderer.py` sind eine angepasste
Kommentarformatierung; netto wurden 33 Python-Zeilen entfernt.

## 9. Testergebnisse

- Vorher: `compileall` PASS; Ruff PASS; 1.195 passed, 15 skipped, 1 umgebungsbedingter Fehler.
- Gezielte Nachher-Suite: 230 passed, 1 skipped in 60,67 s.
- Gezielte Abdeckung: dynamische Renderer, Chart-Templates, Plugin-Discovery, comdirect MiFID und
  Ausschüttung, comdirect PDFs, ING-Banking, PDF-Audit-V3, Startup, V05-Kompatibilität und V09.
- Zusätzliche Domänensuite: 105 passed, 2 skipped in 45,44 s; Plugin-Discovery, Reimport,
  Transaktionsidentitäten, Modelle, Steuern, Cash-Importer, GUI, PDF-Audit und Portfolio-Transfer.
- Vollständige Nachher-Suite: 1.195 passed, 15 skipped, derselbe einzelne umgebungsbedingte
  `.venv`-Fehler, 2 Deprecation-Warnungen und 5 bestandene Subtests in 492,27 s. Damit sind
  Ergebnis und Fehlerbild gegenüber der Baseline unverändert.

## 10. Risiken und offene Punkte

`initialize_v07` könnte theoretisch von nicht im Repository vorhandenem Fremdcode importiert
worden sein; es war jedoch kein öffentlicher Export und die Anwendung besitzt einen nachweislich
anderen Initialisierungspfad. Übersprungene historische Tests sollten separat bewertet, nicht im
Rahmen dieses kleinen Cleanups entfernt werden. Vulture könnte später in einer isolierten
Entwicklungsumgebung ergänzt werden.

## 11. Weitere Empfehlungen

Die breite `TEXT_EXTRACTION`-Klassifikation des Auditwerkzeugs und größere Legacy-Architekturen
sollten in eigenen Änderungen behandelt werden. Für Renderer und Plugins wäre eine explizite,
maschinell prüfbare Registry-Dokumentation hilfreicher als symbolbasierte Dead-Code-Werkzeuge.
