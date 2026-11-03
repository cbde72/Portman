# Portman PDF Lab – PDF-Audit V3: Ergebnisbericht

- Werkzeug: `portman-pdf-lab/tools/pdf_audit_v3.py`
- Referenz: `tools/pdf_audit_v3.py` (V09) – **unverändert**
- Ausgangsbranch: `fix/pdf-lab-run-on-folder-crash` (enthält den PDFium-Batch-Fix `b6e4f40`, PR #50; dieser ist noch **nicht** in `codex/transfers-corporate-actions-gui` enthalten)
- Zielbranch des Pull Requests: `codex/transfers-corporate-actions-gui`
- Parserkern: ausschließlich `portman-parsers`

## 1. Wiederverwendete Komponenten

| Komponente | Verwendung |
|---|---|
| `portman_pdf_lab.application.pdf_analysis.analyse_pdf` | einzige Analysefunktion je PDF (Extraktion, Erkennung, Parsing, Validierung, Rule-Engine, Sichten) |
| `portman_pdf_lab.application.batch_csv.export_batch_csv` | erzeugt `parser_fields.csv` und `fields_description.csv` (eine Zeile je PDF, dynamische Spalten, Trainingsspalten rechts) |
| `flatten_evidence_values` | ausschließlich evidence-gestützte fachliche Werte; Duplikat dieser Logik wurde vermieden |
| `TrainingExportReader` | echte Read-only-SQLite-Verbindung (`mode=ro`, `PRAGMA query_only=ON`), legt keine DB an |
| `portman_parsers.registry.default_registry` | automatische Parserauswahl bzw. erzwungener Parser |
| `portman_parsers.validation.validate_parsed_document` | Issues/Plausibilitätsprüfungen |
| `portman_parsers.rules.ProfileStore` | Regelprofile nur lesend; ohne vorhandenes Verzeichnis wird kein Verzeichnis angelegt |
| `portman_pdf_lab.field_catalog_adapter.import_factual_catalog` | Feldbeschreibungen aus dem vorhandenen YAML-Katalog, geschrieben nur in eine Kopie unter `--output` |
| `portman_pdf_lab.synthetic_pdf.create_demo_pdf` | Testdaten (nicht personenbezogen) |

Nicht verwendet: `RepositoryV09`, `portfolio_v5.pdf_importer.parse_pdf`, `analyse_and_store()`, `ReferenceRepository`, PySide6, jede schreibende SQLite-Operation.

## 2. Neu entstandener Code

| Datei | Inhalt |
|---|---|
| `portman-pdf-lab/tools/pdf_audit_v3.py` | Audit-Tool: CLI, Verzeichnisscan, Kindprozess-Isolation, Klassifikation, Qualitätskennzahlen, Resume, Baseline, Ausgabe |
| `portman-pdf-lab/tests/integration/test_pdf_audit_v3.py` | 25 Tests (siehe Abschnitt 8) |

Bewusst **nicht** neu implementiert: PDF-Extraktion, Parser, Erkennung, Validierung, Feldklassifikation (Evidence), CSV-Feldlogik.

## 3. CLI-Aufruf

```powershell
.\.venv\Scripts\python.exe -X utf8 `
  .\portman-pdf-lab\tools\pdf_audit_v3.py `
  --root "C:\Users\chris\Desktop\history" `
  --output ".\test_reports\pdf_lab_audit_v3" `
  --timeout 120 `
  --no-cache
```

| Argument | Bedeutung |
|---|---|
| `--root` | rekursiv zu scannendes Verzeichnis (`*.pdf`, Groß-/Kleinschreibung egal) |
| `--output` | **einziger** Schreibort; muss außerhalb von `--root` liegen |
| `--baseline` | früheres **PDF-Lab**-`audit.json`; V09-Audits werden abgewiesen |
| `--timeout` | Sekunden je Kindprozess (Standard 120) |
| `--allow-ocr` | aus Kompatibilität akzeptiert; PDF Lab führt kein OCR aus, `OCR_REQUIRED` wird als Befund gemeldet |
| `--no-cache` / `--resume` | schließen sich aus; `--resume` nutzt `progress.json` |
| `--training-database` | optionale Trainingsdatenbank, ausschließlich lesend |
| `--rule-mode` | `STANDARD` (Default) oder `EXTENDED` |
| `--plugin-id` | erzwingt einen Parser; Default ist die automatische Auswahl |
| `--field-catalog` | YAML-Beschreibungskatalog (nur lesend) |
| `--description-store` | bestehende `field-descriptions.v1.json`, wird nur kopiert |
| `--profile-dir` | Regelprofilverzeichnis (nur lesend) |

Exit-Code: `0` ohne Fehler/Timeout/Absturz/Mehrdeutigkeit, sonst `1`. Nicht unterstützte Dokumente und OCR-Hinweise sind Befunde, keine Abstürze.

## 4. Ausgabedateien

```text
<output>/
    audit.json                  vollständiger strukturierter Bericht
    report.md                   menschenlesbarer Bericht
    files.csv                   eine Zeile je gefundenem PDF
    transactions.csv            je Finanzereignis eine Zeile (Buchungsmodell erhalten)
    findings.csv                alle Issues und Auditbefunde
    progress.json               Resume-Zwischenstand
    parser_fields.csv           Run-On-Folder-Export, 1 Zeile je PDF
    fields_description.csv      Beschreibungen zum Feldkatalog
    delta.csv                   Baseline-Differenzen (leer ohne Baseline)
    field-catalog-mapping.json  Katalog-zu-DTO-Zuordnung (Auditnachweis)
    description-store/          Kopie des Beschreibungsspeichers (nie der Originalkatalog)
```

`files.csv` enthält alle V09-Spalten in gleicher Reihenfolge und ergänzt `bank`, `fields`, `exit_code`, `error`. `documents` und `archive_only` bleiben leer, weil PDF Lab diese V09-Konzepte nicht besitzt (keine erfundenen Daten). `snapshots` zählt `depot_snapshots` (das PDF-Lab-Äquivalent) plus das veraltete Snapshot-DTO.

## 5. Prozessisolation

- Jede PDF läuft in einem eigenen Kindprozess (`sys.executable -X utf8 <tool> --worker …`), nie in-process.
- Begrenzte Parallelität: `min(4, CPU-Anzahl)` Threads, die jeweils einen Kindprozess starten.
- Ergebnisübertragung über eine JSON-Datei je Kindprozess (kein stdout-Protokoll, keine Kodierungsprobleme auf Windows); Logs sind auf die letzten 2 000 Bytes begrenzt und werden nach der Auswertung gelöscht.
- Timeout beendet den Kindprozess (`subprocess.run(timeout=…)`) und meldet `TIMEOUT` inklusive PDF-Pfad.
- Exit-Code wird im Fehlerfall als Dezimal- bzw. `0x…`-Wert protokolliert (`exit_code` in `files.csv`, `audit.json`).
- Absturz, Parserfehler, mehrdeutige Erkennung, beschädigte Datei und fehlende Leserechte erzeugen je genau eine Zeile und brechen den Audit nicht ab.
- Kein PySide6-Import im Worker (eigener Test).

## 6. Unterschiede zum V09-Audit

| Aspekt | V09 | PDF Lab |
|---|---|---|
| Parser | `portfolio_v5.pdf_importer.parse_pdf` | `portman_parsers` über `analyse_pdf` |
| Buchungsmodell | flache `transactions`/`tax_events`/`snapshots` | `FinancialEvent` mit `cash_movements`, `security_movements`, `trades`, `fee_events`, `tax_events`, `cost_events` |
| Statuswerte | `PASS/INFO/WARNING/ERROR/TIMEOUT` | zusätzlich `PARSED/UNSUPPORTED/OCR_REQUIRED/AMBIGUOUS/WORKER_CRASH/DUPLICATE` |
| Issue-Codes | Regex-Klassifikation der Warntexte | maschinenlesbare Parser-Codes plus Auditcodes |
| Snapshots | Depotaufstellungen | `depot_snapshots` (neues DTO) |
| `documents`/`archive_only` | vorhanden | nicht vorhanden → leer |
| `parser_fields.csv`/`fields_description.csv` | nicht vorhanden | vorhanden (Run-On-Folder-Export) |
| Baseline | Schema 3, `files` | Schema 1 + `audit_tool`, gegenseitig abgewiesen |
| OCR | optional aktiv | nicht implementiert, nur `OCR_REQUIRED`-Befund |

## 7. Feldzuordnung V09 ↔ PDF Lab

Matching-Schlüssel für einen automatischen Vergleich ist `sha256`; ersatzweise `path`.

### 7.1 `files.csv`

| V09-Feld | PDF-Lab-Feld | Einstufung |
|---|---|---|
| `path` | `path` | direkt vergleichbar (relativer POSIX-Pfad) |
| `sha256` | `sha256` | direkt vergleichbar (Identitätsschlüssel) |
| `bytes` | `bytes` | direkt vergleichbar |
| `duplicate_of` | `duplicate_of` | direkt vergleichbar |
| `status` | `status` | fachlich äquivalent, andere Vokabeln |
| `severity` | `severity` | direkt vergleichbar (`PASS/INFO/WARNING/ERROR/TIMEOUT`) |
| `plugin` | `plugin` | direkt vergleichbar (`plugin_id`) |
| `handler` | `handler` | direkt vergleichbar (`handler_id`) |
| `document_type` | `document_type` | direkt vergleichbar |
| `transactions` | `transactions` (Anzahl Finanzereignisse) | fachlich äquivalent, anderes Zählmodell (Ereignis statt Buchung) |
| `tax_events` | `tax_events` | fachlich äquivalent (Anzahl Steuerereignisse) |
| `snapshots` | `snapshots` | fachlich äquivalent (`depot_snapshots` + Legacy) |
| `documents` | – | nur V09 |
| `archive_only` | – | nur V09 |
| `ocr_indications` | `ocr_indications` | teilweise vergleichbar (nur `OCR_REQUIRED`, kein OCR-Lauf) |
| `duration_s` | `duration_s` | direkt vergleichbar (Kindprozesslaufzeit) |
| `issue_codes` | `issue_codes` | fachlich äquivalent, andere Codesystematik |
| – | `bank`, `fields`, `exit_code`, `error` | nur PDF Lab |

### 7.2 `transactions.csv`

| V09-Feld | PDF-Lab-Feld | Einstufung |
|---|---|---|
| `path`, `sha256` | `path`, `sha256` | direkt vergleichbar |
| `external_id` | `event_id` / `bank_reference` | fachlich verwandt, **nicht identisch**: `event_id` ist eine stabile ID, `bank_reference` die gedruckte Referenz |
| `kind` | `kind` | fachlich äquivalent |
| `date` | `event_date` | fachlich äquivalent |
| `value_date` | `trades[].value_date`, `tax_events[].value_date` | fachlich äquivalent, verschachtelt |
| `amount` | `amount` (nur bei genau einer Geldbewegung) | fachlich äquivalent; mehrere Bewegungen bleiben in `cash_movements` |
| `currency` | `currency` | direkt vergleichbar |
| `security` | `security` | fachlich äquivalent |
| `security_ref` | `isin`, `wkn` | fachlich äquivalent, getrennt statt kombiniert |
| `quantity` | `quantity` | fachlich äquivalent |
| `gross_amount` | `gross_amount` | direkt vergleichbar |
| `fees` | `fee_events` / `fee_count` | fachlich äquivalent (Liste statt Summe) |
| `taxes` | `tax_events` / `tax_count` | fachlich äquivalent (Liste statt Summe) |
| `fee_items` | `fee_events` | fachlich äquivalent |
| `tax_items` | `tax_events[].components` | fachlich äquivalent |
| `is_reversal` | `reversal_of_event_id` (nicht leer) | fachlich äquivalent |
| `reverses_external_id` | `reversal_of_event_id` | fachlich äquivalent |
| `affects_cash` | `cash_movements` vorhanden | fachlich äquivalent |
| `cash_account`, `depot_account` | `cash_movements[].account_ref`, `security_movements[].depot_id` | fachlich äquivalent |
| – | `cash_status`, `side`, `cost_count`, `cost_events`, `security_movements` | nur PDF Lab |

### 7.3 Nicht vergleichbar

- V09 `documents` (Archivbelege) und `archive_only` haben kein PDF-Lab-Gegenstück.
- V09 kennt keine Evidence-IDs und keine fachlichen Feldpfade; ein feldweiser Vergleich erfolgt über `parser_fields.csv` gegen V09-`audit.json`-Einzelwerte und ist nur für dort vorhandene Felder möglich.
- V09-OCR-Qualitätsangaben (Sicherheit, Layoutwarnungen) existieren in PDF Lab nicht.
- `parser_fields.csv` und `fields_description.csv` besitzen kein V09-Pendant.

### 7.4 Identitätsprüfung

Beide Audits verwenden denselben Dateiinhalt als Grundlage. `sha256` ist in beiden `files.csv` enthalten und identisch für dieselbe Datei; Test 23 prüft das über zwei unabhängige Läufe derselben Datei. Ein Vergleichswerkzeug kann daher primär über `sha256` und sekundär über `path` joinen.

## 8. READ-ONLY-Nachweis

Umgesetzt und durch Tests abgesichert:

1. **Keine produktive DB**: Das Werkzeug importiert weder `RepositoryV09` noch `portfolio_v5` oder `ReferenceRepository`. Einziger DB-Zugriff ist `TrainingExportReader` mit `sqlite3.connect("file:…?mode=ro", uri=True)` und `PRAGMA query_only=ON`.
2. **Keine DB-Erzeugung**: Ein nicht existierender `--training-database`-Pfad erzeugt eine Warnung, aber keine Datei (Test 20).
3. **Regelprofile**: Ohne vorhandenes Profilverzeichnis wird `NoProfiles` verwendet; es entsteht kein Verzeichnis (Test „extended mode without profile directory“). `activate()`/`save()` werden nie aufgerufen.
4. **Feldkatalog**: Der YAML-Katalog wird nur gelesen. Beschreibungen landen in `--output/description-store/…`; der Katalog und der `data/`-Ordner bleiben byte-identisch (Test 22).
5. **Alle Ausgaben unter `--output`**: inklusive `.work/` (nach dem Lauf gelöscht), `progress.json`, `delta.csv`.
6. **Kein GUI-Start**: eigener Subprozess-Test prüft, dass `PySide6` nach dem Laden des Tools und der Analysefunktion nicht importiert ist.
7. **Keine Parser-Persistenz**: `analyse_pdf` ist rein funktional; es gibt keinen Aufruf von `analyse_and_store()` (per Code-Suche und Testsuite bestätigt).

## 9. Performance-Ergebnisse

Gemessen mit `.venv` (Python 3.13.9), 4 parallelen Kindprozessen, `--timeout 120`, `--no-cache`, ohne Trainingsdatenbank.

Korpus: `C:\Users\chris\Desktop\history` (3 739 PDFs, rund 519 MB).

| Kennzahl | Wert |
|---|---:|
| PDFs physisch | 3 739 |
| PDFs eindeutig (SHA-256) | 2 708 |
| Duplikate | 1 031 |
| Wandzeit gesamt | 1 302,22 s (ca. 21,7 min) |
| Durchsatz (eindeutig analysiert) | 2,08 PDFs/s |
| Durchsatz (physisch, inkl. Hashing) | 2,87 PDFs/s |
| Laufzeit je PDF: Ø / p50 / p95 / p99 / max | 1,886 / 1,478 / 3,983 / 7,077 / 86,538 s |
| Summe Kindprozesslaufzeit | 5 106,06 s (ca. 3,9-fache Wandzeit bei 4 Workern) |
| Timeouts | 0 |
| Native Abstürze (Kindprozess) | 0 |
| Fehler beim Verzeichnisscan | 0 |

Statusverteilung: 1 273 `PARSED`, 927 `UNSUPPORTED`, 487 `ERROR`, 21 `OCR_REQUIRED`, 1 031 `DUPLICATE`. Parsererkennungsquote 47,01 %, technische Erfolgsquote 47,01 %. 124 geparste Dokumente enthielten keine evidence-gestützten fachlichen Werte; insgesamt wurden 26 734 Feldwerte, 1 089 Finanzereignisse, 505 Wertpapiergeschäfte, 634 Steuerereignisse und 181 Gebührenpositionen erkannt. Der langsamste Einzellauf (86,5 s) blieb deutlich unter dem Zeitlimit von 120 s.

Fehlerbild der 487 `ERROR`-Zeilen: 283 × `ValueError: account_id identities must be unique`, 195 × `PasswordProtectedPdfError` (passwortgeschützte PDFs), 7 × `BankOfScotlandParseError`, 2 × `FnzFinvestoParseError`. Kein Fehler brach den Lauf ab; jede Datei erhielt genau eine Zeile mit Pfad und Fehlertext.

**Einordnung:** Der Lauf erfolgte im Arbeitsbaum inklusive einer lokalen, **nicht zu diesem PR gehörenden** Änderung an `portman-parsers/src/portman_parsers/plugins/comdirect.py` (Finanzreport-Erweiterung). Die 283 ValueError stammen aus dieser Erweiterung und sind ein Parser-/Fachbefund, kein Fehler des Audit-Werkzeugs. Die Performance- und Isolationswerte (Wandzeit, Laufzeiten, 0 Timeouts, 0 Abstürze, eine Zeile je Datei) sind davon unabhängig; die fachlichen Quoten spiegeln diesen lokalen Parserstand und sind keine Aussage über den PR-Stand.

Ohne Referenzwerte wird keine Feldgenauigkeit behauptet; die Qualitätskennzahlen sind technische Erfolgsquote und Vollständigkeitsindikatoren.

## 10. Tests

Neue Suite `portman-pdf-lab/tests/integration/test_pdf_audit_v3.py` (25 Tests, alle grün):

| # | Anforderung | Test |
|---|---|---|
| 1 | ein PDF | `test_single_pdf_produces_all_result_files` |
| 2 | mehrere PDFs | `shared`-Fixture, `test_quality_…` |
| 3 | rekursive Verzeichnisse | `test_every_pdf_gets_one_row_with_recursive_discovery_and_sha_duplicate` |
| 4 | verschiedene Banken | `test_quality_separates_technical_success_from_completeness` (Bankgruppe) |
| 5 | nicht unterstützter Typ | `test_unsupported_and_broken_documents_do_not_stop_the_audit` |
| 6 | beschädigtes PDF | derselbe Test |
| 7 | Parserexception | `test_parser_exception_and_ambiguity_are_classified_without_aborting` |
| 8 | Prozessabsturz | `test_native_process_crash_is_isolated_and_reports_path` |
| 9 | Timeout | `test_timeout_terminates_child_and_is_reported` |
| 10 | mehrfache Ausführung | `test_repeated_runs_are_byte_identical_in_csv_outputs` |
| 11 | Resume | `test_resume_reuses_successful_rows_and_reruns_failed_ones`, `test_resume_is_rejected_when_rule_mode_changes` |
| 12 | Baseline | `test_baseline_comparison_reports_no_changes_for_identical_input`, `test_baseline_detects_new_and_removed_paths`, `test_v09_audit_is_rejected_as_baseline` |
| 13 | gleiche Dateien, andere Namen | `…sha_duplicate` |
| 14 | CSV-Felder | `test_transactions_and_findings_are_written` |
| 15 | dynamische Spalten | `test_parser_fields_csv_has_one_row_per_pdf_and_dynamic_columns` |
| 16 | mehrere Finanzereignisse | `test_multiple_events_and_tax_document_without_booking` |
| 17 | Steuerdokument ohne Buchung | derselbe Test |
| 18 | Wert gleich null | `test_zero_values_and_missing_evidence_are_handled_by_classification` |
| 19 | fehlende Evidence | derselbe Test |
| 20 | Trainingsdaten vorhanden/nicht | `test_training_database_is_optional_and_read_only` |
| 21 | SQLite unverändert | derselbe Test (Byte-Vergleich) |
| 22 | Feldkataloge unverändert | `test_field_catalog_and_data_folder_are_not_modified` |
| 23 | Dokumentidentität | `…sha_duplicate` + `test_worker_result_is_json_and_does_not_import_gui` |
| 24 | Windows-Fehlerbehandlung | `test_pdf_names_with_spaces_and_umlauts_are_supported`, `test_output_inside_root_and_unknown_plugin_are_rejected` |
| 25 | reproduzierbare Reihenfolge | `…recursive_discovery…`, `test_repeated_runs_are_byte_identical_in_csv_outputs` |

Zusätzlich ausgeführt:

- `portman-parsers/tests`: **147 passed**
- `portman-pdf-lab/tests`: **171 passed** (146 bestehende + 25 neue)

Lint: `python -m ruff check` über beide neuen Dateien – ohne Befund (Regel `F`).

## 11. Noch offene Punkte

- **PR #50 / PDFium-Fix**: `b6e4f40` ist auf `fix/pdf-lab-run-on-folder-crash`, aber nicht auf `codex/transfers-corporate-actions-gui`. Der PR gegen den Integrationsbranch enthält daher diesen Fix implizit; die Reihenfolge der Merges muss beachtet werden.
- `--allow-ocr` ist aus CLI-Kompatibilität vorhanden, hat aber keine Wirkung. OCR ist im Parserkern nicht als Audit-Funktion verfügbar.
- `documents` und `archive_only` bleiben leer; ein PDF-Lab-Äquivalent existiert nicht.
- Ein automatischer V09↔PDF-Lab-Vergleicher ist bewusst nicht Teil dieses Auftrags; die Zuordnung in Abschnitt 7 ist die Grundlage dafür.
- Feldgenauigkeit ist ohne bestätigte Referenzwerte nicht ausgewiesen; dafür wäre eine Trainingsdatenbank mit `reference_values`/`golden_tests` nötig.
- Mehrdeutige Parserzuordnung ist implementiert, tritt im Testkorpus aber nur synthetisch auf.
- Der Vollaudit zeigt einen **Parser-/Fachbefund außerhalb dieses PRs**: 283 comdirect-Finanzreports scheitern an `ValueError: account_id identities must be unique`. Ursache ist die lokale, nicht committete Finanzreport-Erweiterung in `portman-parsers/.../comdirect.py`; das Audit klassifiziert sie korrekt als `ERROR` mit Pfad und Fehlertext. Zusätzlich sind 195 PDFs passwortgeschützt (`PasswordProtectedPdfError`).
- `--resume` und `--baseline` prüfen den Parser-Fingerprint inklusive der Quelldateien. Ändert sich das lokale Parser-Arbeitsverzeichnis, werden frühere `progress.json`/Baselines bewusst verworfen – das ist gewollt, erschwert aber Ad-hoc-Vergleiche über Codeänderungen hinweg.
