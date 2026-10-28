# Portman V09 – Interaktive Konfliktbehandlung beim Import

Datum: 28.10.2026
Branch: `main`
Ausgangscommit: `1016e13125a983628ee825c47aa798b41302f539`

## Ergebnis

Der bestehende atomare V09-Import wurde um eine geführte, ausschließlich für den aktuellen Importvorgang geltende Konflikt- und Warnungspolitik ergänzt. Die vorhandenen Revisions-, Supersession-, Undo-, Backup- und Transaktionsmechanismen werden unverändert weiterverwendet. Es wurden keine direkten SQL-Überschreibungen und keine Änderungen an Parsern oder produktiven Datenbanken vorgenommen.

## Dialoglayout „Eintrag schon vorhanden“

Der Dialog zeigt einen Zähler im Format `Konflikt n von m` und stellt folgende Werte nebeneinander dar:

| Feld | Vorhandene Buchung | Neue Buchung |
| --- | --- | --- |
| Datum | Ja | Ja |
| Konto | Ja | Ja |
| Wertpapier / ISIN | Ja | Ja |
| Betrag | Ja | Ja |
| Gebühren | Ja | Ja |
| Steuer | Ja | Ja |
| Dokumentquelle | Ja | Ja |

Abweichende Werte werden farblich hervorgehoben. Die Schaltflächen sind beschriftet und per Tastaturkürzel erreichbar:

- **Alte überschreiben**: übernimmt die neue Buchung und nutzt die vorhandene revisionssichere Supersession.
- **Alte behalten**: lässt die vorhandene Buchung unverändert und überspringt die neue Buchung.
- **Abbrechen**: beendet den Wizard vor jeder schreibenden Operation.

Die frühere neue Auswahl „Beide behalten“ wird nicht mehr angeboten, da sie nicht dem geforderten Zweierentscheid entspricht. Bereits gespeicherte alte Importsitzungen mit dieser Entscheidung bleiben fortsetzbar.

## Entscheidungsregeln

Pro Konflikt stehen drei Reichweiten zur Verfügung:

- Nur diesen Eintrag bearbeiten
- Alle gleichartigen Konflikte genauso behandeln
- Bei jedem Konflikt nachfragen

„Gleichartig“ bedeutet: gleiche Art des Identitätstreffers, gleiche Buchungsart und gleiche Menge abweichender fachlicher Vergleichsfelder. Dadurch wird beispielsweise eine Betragsabweichung nicht ungeprüft auf einen Konflikt mit abweichender Steuerstruktur übertragen.

Die Regeln werden ausschließlich im Speicher des aktuellen `ImportWizard` gehalten. Sie werden weder in globalen Einstellungen noch in späteren Importvorgängen gespeichert. Eine sichtbare Statuszeile zeigt Anzahl der aktiven Konflikt- und Warnungsregeln sowie unterdrückte Warnungsanzeigen.

Identische Datensätze werden anhand aller fachlichen Buchungsfelder unter Ausschluss reiner Speichermetadaten erkannt und automatisch mit „Neue überspringen“ behandelt. Dabei wird kein Dialog geöffnet.

## Warnungen und kritische Fehler

Fachlich nichtkritische Warnungen erhalten eine getrennte Entscheidungspolitik:

- **Übernehmen**: Hinweis akzeptieren und fortfahren.
- **Bei jedem entsprechenden Hinweis nachfragen**: keine Regel anlegen.
- **Anzeige ignorieren**: weitere Anzeigen derselben Meldungsart im aktuellen Import unterdrücken.

Das Ignorieren betrifft ausschließlich die Anzeige. Der ursprüngliche Eintrag in `ImportBatch.warnings` bleibt erhalten und wird über die bestehenden Importergebnisse weiterhin protokolliert. Es wird dadurch keine Buchung verworfen.

Kritische Fehler bleiben blockierend. Insbesondere Batchfehler und Validierungsfehler erreichen weiterhin die unveränderten Prüfungen in `ImportSession.apply()` beziehungsweise `ImportSession.commit()` und führen zum Rollback der gesamten äußeren Transaktion.

## Wiederverwendete Sicherheitsmechanismen

- `ImportSession.conflicts()` für Identität und Kandidatenermittlung
- `ImportSession.resolve()` für validierte Entscheidungen
- `ImportSession._record_replacements()` für revisionssichere Supersession
- `transaction(..., commit=True)` für die atomare Gesamtverarbeitung
- Revisionsprüfung gegen Änderungen seit der Vorschau
- Quelldatei-Hashprüfung vor dem Schreiben
- verifiziertes Datenbankbackup vor dem Commit
- bestehendes `RepositoryV09.undo_import()` für die Wiederherstellung ersetzter Buchungen

Dialoge werden ausschließlich aus dem GUI-Thread geöffnet. Ein expliziter Laufzeitwächter blockiert Dialogaufrufe aus Hintergrundthreads.

## Geänderte Dateien dieser Aufgabe

- `src/portman/import_conflict_actions.py`
- `src/portman/import_ui_v09.py`
- `tests/test_import_bulk_and_history.py`
- `tests/test_import_conflict_ui.py`
- `test_reports/portman_v09_import_conflict_ui.md`

Die bereits vorher vorhandenen lokalen GUI-Redesign-Änderungen wurden erhalten und nicht zurückgesetzt.

## Technischer Sicherungsstand

Vor den Änderungen wurden die drei bereits vorhandenen betroffenen Dateien außerhalb des Repositorys gesichert:

`C:\Users\chris\Desktop\Portman_Import_Conflict_Backup_20261028`

Das Manifest `SHA256_MANIFEST.csv` wurde nach Abschluss erneut verifiziert. Ergebnis: **3/3 Dateien stimmen in Dateigröße und SHA-256 überein**.

## Tests

Gezielte Konflikt-, Revisions- und Wizardtests:

```text
107 passed, 1 skipped, 3 subtests passed
```

Die neuen Regressionstests decken ab:

- identischen Reimport ohne Dialog;
- abweichenden Reimport mit Überschreiben;
- abweichenden Reimport mit Behalten der alten Buchung;
- Regel für alle gleichartigen Konflikte;
- erneute Nachfrage bei jedem Konflikt;
- gemischte Konfliktarten;
- weiterhin protokollierte ignorierte Warnungen;
- blockierende kritische Fehler;
- Abbruch vor Schreiboperationen;
- Undo nach interaktiv gewähltem Ersetzen;
- GUI-Thread-Sicherheit;
- Pflichtfelder und Hervorhebung im Alt/Neu-Dialog.

Statische Prüfungen:

```powershell
python -m compileall -q src
python -m ruff check src --select F
```

Ergebnis: erfolgreich, Ruff meldet `All checks passed!`.

Vollständige Regression:

```powershell
python -m pytest -q --basetemp tmp/pytest_import_conflicts
```

Ergebnis:

```text
1234 passed, 16 skipped, 2 warnings, 5 subtests passed in 553.17s
```

Die zwei Warnungen betreffen die bereits vorhandene, als veraltet markierte Qt-Methode `QSortFilterProxyModel.invalidateFilter()` in `src/portman/tax_detail_view.py`. Diese Datei wurde nicht geändert.

## Offene Risiken

1. Bei mehreren möglichen Gegenbelegen bleibt die bestehende explizite Kandidatenauswahl erforderlich; ein Ersatz darf weiterhin nicht automatisch geraten werden.
2. Die Klassifikation gleichartiger Konflikte ist bewusst konservativ. Unterschiedliche Abweichungsfelder führen zu einer erneuten Nachfrage.
3. Der Experten-/GUI-Redesign-Diff liegt weiterhin uncommittet im selben Arbeitsbaum. Beim Commit müssen ausschließlich die unten genannten Konfliktdateien ausgewählt werden.
4. Eine kurze manuelle Windows-Abnahme mit Tastaturbedienung und realem Qt-Renderer ist zusätzlich zu den Offscreen-Tests empfehlenswert.

## Commit-Vorbereitung

Für einen separaten lokalen Commit dieser Aufgabe sind ausschließlich vorgesehen:

```text
src/portman/import_conflict_actions.py
src/portman/import_ui_v09.py
tests/test_import_bulk_and_history.py
tests/test_import_conflict_ui.py
test_reports/portman_v09_import_conflict_ui.md
```

Keine PDFs, SQLite-Dateien, privaten Auditdaten oder temporären Verzeichnisse sind Bestandteil dieser Auswahl. Es wurde kein Commit und kein Push ausgeführt.
