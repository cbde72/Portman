# Portman V09 – Code-Cleanup Phase 3

## 1. Ausgangsstand und Branch-Abhängigkeit

- `main`: `d4f02a8ff099195d60f8f99c7a2370cd0c360183`. Darin sind Phase 2 per Squash-Commit `339d1fc` (PR #28) und Phase 1 per Squash-Commit `d4f02a8` (PR #29) integriert.
- Phase-3-Branch: `refactor/v09-import-persistence-phase3`.
- Am 25.10.2026 wurde der Branch nach dem Retargeting von PR #31 sauber auf diesem `main` rekonstruiert. Zuvor wurde der vollständige alte Stand `d7aa57e` als Remote-Branch `safety/v09-import-persistence-phase3-pre-main-20261025` gesichert.
- Ausschließlich die fünf Phase-3-Commits wurden neu abgespielt. Phase-1- und Phase-2-Dateien erscheinen dadurch nicht erneut im PR-Diff; `repository_v09.py` bleibt unverändert.
- PR #31 zielt nun direkt auf `main`; es besteht keine gestapelte Branch-Abhängigkeit mehr.
- Separater Worktree und isolierte Temp-Umgebung: `.worktrees/v09-import-persistence-phase3`, `.test-tmp`.

## 2. SQL-Trace-Charakterisierung

Die Tests verwenden `sqlite3.Connection.set_trace_callback()`. Flüchtige UTC-Importzeitstempel werden ersetzt; alle übrigen SQL-Texte und ihre Reihenfolge fließen in einen SHA-256-Golden-Digest ein. Dadurch bleiben Tabellen, Spalten, Werte, Reihenfolge und Triggeraufrufe sichtbar.

Golden Trace des repräsentativen Mehrkonto-/Mehrdepotimports:

- 18 SELECT-Ereignisse;
- 101 von SQLite einschließlich Triggerausführungen gemeldete INSERT-Ereignisse;
- genau ein BEGIN und COMMIT;
- Digest `57a54c2cadd1287e2ca779ac9e1bf61105872cc59e65aab54499b06e76a419bd`;
- fachliches Ergebnis: 1 Import, 2 Snapshots, 1 Saldo, 2 Transaktionen, 1 Steuerereignis, 2 Depotzuordnungen und 3 Konten.

Erfasste Fälle:

| Fall | Nachweis |
| --- | --- |
| Erfolgreicher Einzelimport | Golden Trace und Ergebniszustand |
| Mehrere Batches in einer Transaktion | äußerer `transaction()`-Rollbacktest |
| Wiederholter Import | Duplicate-Test ohne INSERT |
| Gleicher Inhalt, anderer Name | Duplicate mit neuem Pfad |
| Veränderter Inhalt | zweiter aktiver Import |
| Fehlende Kontozuordnung | Validierungsfehler ohne Write |
| Mehrere Konten | Golden Trace: Depot A/B und Cash A |
| Mehrere Depots | zwei Snapshot-/Depotzuordnungen |
| Ungültige Transaktion | `NaN`, kein Write |
| Ungültiger Snapshot | ungültiges Datum, kein Write |
| Steuerereignis | persistierter Model-Record |
| Kauf/Verkauf | BUY und SELL im Golden Trace |
| Gebühren/Steuern | Fees/Taxes in den Transaktionspayloads; bestehende Linktests |
| Fehler mitten in Persistenz | Triggerfehler vor Transaktionsinsert |
| Vollständiger Rollback | alle sieben geprüften Tabellen bleiben leer |

Vor und nach der Modularisierung bestehen der Golden Digest, Operationszahlen und fachliche Zustände unverändert.

## 3. Konfliktmatrix für `ImportSession.resolve()`

| Ausgangszustand / Eingang | Konflikt | Entscheidung | Ergebnis | Datenbankänderung / Meldung |
| --- | --- | --- | --- | --- |
| Neuer Import | keiner | keine | unverändert ausgewählt | erst beim späteren Commit |
| Bestehende gleiche Referenz | ID/Betrag | keine/ungültig | abgewiesen | keine; „ausdrücklich entscheiden“ |
| Bestehende gleiche Referenz | ID/Betrag | skip | neue Buchung entfernt | keine |
| Bestehende gleiche Referenz | ID/Betrag | keep | übernommen, deterministisch umbenannt | erst beim Commit |
| Bestehende Buchung | ID/Betrag | replace + Grund | Supersession vorbereitet, neue ID | erst beim Commit |
| Replace ohne Grund | ID/Betrag | replace | abgewiesen | keine; Begründung erforderlich |
| Mehrere Kandidaten | mehrdeutig | replace ohne `old_ref` | abgewiesen | explizite Auswahl erforderlich |
| Mehrere Kandidaten | mehrdeutig | replace mit gültigem `old_ref` | genau ein Ersatz | erst beim Commit |
| Falscher `old_ref` | veraltet | replace | abgewiesen | Kandidat passt nicht mehr |
| Zwei neue Dateien | Überlappung | replace | abgewiesen | nur Behalten/Überspringen erlaubt |
| Zwei neue Dateien | Überlappung | skip | zweite Buchung entfernt | keine |
| Widersprüchliche Gruppenwahl | gleiche neue Buchung | skip + keep | abgewiesen | keine |
| Doppelte IDs in einer Datei | interne Kollision | – | abgewiesen | bestehender `conflicts()`-Test |
| Ungültige Kontozuordnung | Mappingfehler | – | Validierung wie zuvor | keine |
| Abbruch/Mehrbatchfehler | Laufzeitfehler | – | atomarer Rollback | keine Teilpersistenz |

Die neuen Matrix-Tests liefen vor der Produktionsänderung mit `16 passed, 1 skipped`. Der Skip betrifft ausschließlich einen Gruppenfall, den die aktuelle Kandidatenaggregation bereits zu einem Konflikt zusammenfasst; das bestehende Gruppenvalidierungsverhalten bleibt zusätzlich im Code und in der Gesamtsuite erhalten.

## 4. Architektur vorher/nachher

Vorher enthielt `Store.import_batch()` nach abgeschlossener Phase 2 weiterhin den gesamten SQL-Block für Quellarchiv, Konten, Importkopf, Dokumente, Snapshots, Salden, Transaktionen und Coverage. Danach koordiniert die Methode dieselben Schritte innerhalb desselben `with self.db`-Blocks über vier kohärente Helfer:

1. `_persist_import_sources_and_accounts()`
2. `_persist_import_header_and_documents()`
3. `_persist_snapshots_and_balances()`
4. `_persist_transactions_and_coverage()`

Kein Helfer öffnet oder committet eine Transaktion. Es gibt keine neue Connection, kein Schemawissen außerhalb von `storage.py` und keine veränderte Constraint-Behandlung.

`ImportSession.resolve()` delegiert nun Gruppenvalidierung, Kandidatenauswahl, Keep-Rename-Regel, Aktionssammlung und Anwendung auf die Kopie an klar benannte interne Helfer. Konfliktprioritäten, Standardentscheidungen, Fehlermeldungen und der deterministische ID-Suffix bleiben unverändert.

## 5. Metriken

| Funktion | C901 vorher | C901 nachher | Zeilen vorher | Zeilen nachher |
| --- | ---: | ---: | ---: | ---: |
| `Store.import_batch()` | 29 | 5 | 133 | 33 |
| `ImportSession.resolve()` | 21 | 1 | 55 | 8 |

- Neue interne Helfer: vier Persistenzhelfer und fünf Konflikthelfer.
- Neue öffentliche Schnittstellen: keine.
- Neue Modulabhängigkeiten: keine; Helfer verbleiben in ihren bisherigen Modulen.
- SQL-Zugriffe: Golden Trace unverändert; Benchmark jeweils 302 Reads und 1.189 von SQLite/Triggern gemeldete Writes für 20 Batches.
- Der zusätzliche Codeumfang besteht aus Charakterisierung, Benchmark und benannten internen Verantwortlichkeiten; kein Produktionszweig wurde nur zur Metrikverbesserung entfernt.

## 6. Reproduzierbarer Importbenchmark

Werkzeug: `tools/benchmark_import_phase3.py`, je drei frische temporäre SQLite-Datenbanken mit je 20 Batches, vier Depots, Snapshot und Kauf pro Batch. Gemessen werden `perf_counter`, `tracemalloc`, Trace-Reads/Writes und persistierte Datensätze.

| Stand | Median gesamt | Median/Batch | Reads | Writes | Peak Memory | Datensätze |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Phase-2-Ausgangscode | 0,12845 s | 0,006422 s | 302 | 1.189 | 1.120.045 B | 60 |
| Phase 3 | 0,09229 s | 0,004615 s | 302 | 1.189 | 1.119.093 B | 60 |

Ein Mikrobbenchmark beweist keine allgemeine Beschleunigung; er zeigt aber keine relevante Regression. Prüfungen und V09-Nachverarbeitung wurden nicht ausgelassen.

## 7. Fachliche Integrität, Idempotenz und Rollback

- Importresultate und stabile Tabellenzustände werden zusätzlich zum Trace verglichen.
- Duplicate-Import erzeugt keine fachlichen Inserts.
- Ein absichtlich mitten in der Persistenz ausgelöster SQLite-Fehler endet mit ROLLBACK und leeren Zieltabellen.
- Zwei erfolgreiche Store-Aufrufe werden durch den bestehenden Import-Transaktionsproxy gemeinsam zurückgerollt.
- Bestehende comdirect-, Gebühren-, Steuer-, FSA-, Performance-, Saldo-, Supersession- und Reihenfolgetests bleiben unverändert Bestandteil der Vollsuite.
- Produktive Datenbanken und Originaldokumente wurden nicht verwendet.

## 8. Prüfstatus

Erfolgreich ausgeführt:

- SQL-/Konfliktcharakterisierung vor Refactoring: `16 passed, 1 skipped`.
- Gezielte Persistenz-, Phase-2- und Atomaritätstests nach Refactoring: `18 passed`.
- V09- und Konflikttests nach Refactoring: `81 passed, 1 skipped`.
- SQL-Golden-Trace nach Refactoring: identisch.
- Benchmark: drei Messungen pro Stand.
- `python -m compileall -q src/portman src/portfolio_v5`: erfolgreich.
- `python -m ruff check src/portman src/portfolio_v5 --select F`: ohne Befund.
- Vollständige C901-Erfassung: 131 bestehende projektweite Treffer; die beiden Zielfunktionen sind nicht mehr enthalten.
- Vollständige Pytest-Suite nach dem sauberen Neuaufbau auf `main`: `1147 passed, 15 skipped` in 443,49 Sekunden.

Noch auszuführen: keine für die definierte Abnahme.

Nicht ausgeführt:

- Tests gegen produktive Datenbanken oder Original-PDFs (aus Sicherheitsgründen ausdrücklich ausgeschlossen).
- Separate laufende PDF-Parser-V2-Suite (nicht berührt; keine Dateien in ihrem Bereich geändert).

## 9. Risiken und weitere Vereinfachungen

- Die vier Persistenzhelfer greifen absichtlich direkt auf dieselbe Connection zu. Eine Repository-Abstraktion darüber würde eine unnötige Schicht und Transaktionsrisiko schaffen.
- Die vollständige SQL-Sequenz ist bewusst streng; legitime spätere Queryoptimierungen müssen den Golden Trace samt fachlichem Vergleich ausdrücklich aktualisieren.
- `ImportSession.conflicts()` bleibt komplex und zustandsbehaftet. Eine Phase 4 sollte zuerst Kandidatenindex und Cachevertrag separat charakterisieren.
- Die Phase-1-/Phase-2-Stapelung muss beim Merge von PR #28 sauber auf den dann aktuellen `main` aufgelöst werden; Phase 3 verändert die überlappende `repository_v09.py` nicht.
