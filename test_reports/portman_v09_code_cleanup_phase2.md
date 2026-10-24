# Portman V09 – Code-Cleanup Phase 2

## Arbeitsgrundlage

- Ausgangscommit: `f2a60f2a0c50573e8a8cd50394eed1743c089a9f` (`Fix clean reimport tax reconciliation (#27)`).
- Branch: `refactor/v09-import-architecture-cleanup`.
- Separater Worktree: `.worktrees/v09-import-architecture-cleanup`.
- Die Phase-1-Branchspitze `origin/refactor/v09-code-cleanup` ist kein Vorfahr von `origin/main`; Phase 2 basiert daher bewusst unverändert auf `origin/main` und übernimmt keine ungeprüften Phase-1-Änderungen.
- Python wird aus der vorhandenen Projektumgebung verwendet; `TEMP` und `TMP` zeigen für Tests auf das lokale Worktree-Verzeichnis `.test-tmp`, damit parallele Pytest-Läufe nicht kollidieren.
- Parser, Parser-Registry, OCR, Datenbankschema und Migrationen wurden nicht verändert.

## Aufrufhierarchie und Verantwortlichkeiten

Der geführte V09-GUI-Import läuft über:

`gui.import_flow.preview_parsed_import()` → Vorschau/Validierung → `ImportSession.resolve()` → `ImportSession.apply()` → `RepositoryV09.commit_batches()` → `RepositoryV07.commit_batches()` → `PortfolioRepository.commit_batches()` → `Store.import_batch()`.

`ImportSession.apply()` öffnet keine eigene Transaktion. Die aufrufende Vorschau umschließt Simulation bzw. Commit mit `transaction(...)`. `RepositoryV09.commit_batches()` normalisiert comdirect-Abrechnungen, delegiert die Persistenz und führt danach die V09-Nachverarbeitung für `booking_details`, Transaktionsabgleich sowie Steuer-/Gebührenlinks aus. Dadurch wird dieselbe Nachverarbeitung unabhängig von der Belegreihenfolge erneut angewendet.

Der spezielle comdirect-Finanzreportweg lautet:

`gui.import_flow` → `commit_reports()` → `RepositoryV09.commit_batches()` → derselbe Repository-/Store-Pfad.

`src/portman/import_jobs.py` besitzt daneben einen Legacy-/Jobpfad mit direktem `store.import_batch()`. Er verwendet einen eigenen Transaktionsproxy und ist nicht der geführte V09-GUI-Pfad. Eine Umstellung wurde wegen abweichender Callback- und Rollback-Semantik zurückgestellt.

## Bestandsaufnahme

| Bereich | Verantwortung / Seiteneffekt | Bewertung |
| --- | --- | --- |
| `Store.import_batch()` | Vorprüfung, Zuordnung, Deduplizierung, Identität, eine SQLite-Transaktion, Persistenz | sicher zerlegbar innerhalb unveränderter Reihenfolge |
| `RepositoryV09.commit_batches()` | V09-Normalisierung und idempotente Nachverarbeitung | beibehalten; fachlich sensibel und gut durch Integrationstests abgedeckt |
| `ImportSession.apply()` | Abbruchprüfung, Repository-Commit, Supersession, Fortschritt | Supersession-Aufbereitung vereinfachbar |
| `commit_reports()` | Repository-Lebenszyklus, optionales Backup, Commit | beibehalten; eigener äußerer Workflow, aber identischer Speicherpfad |
| Importvorschauen | Qt-Zustand, Auswahl und Kontozuordnung | weitere Prüfung; dynamische Signals/Slots und mehrere bankspezifische Dialoge |
| Transaktionsreferenz | identische JSON-Identität in drei Schichten | sicher vereinheitlichbar |

Statische Suche und Aufrufanalyse ergaben keine neu eingeführten zyklischen Abhängigkeiten. Der neue Referenzbaustein importiert nur `json`; `portfolio_v5.settlement`, `portman.asset_registry` und `portman.repository_v09` hängen einseitig davon ab.

## Durchgeführte Änderungen

`Store.import_batch()` wurde entlang beobachtbarer Verantwortlichkeiten zerlegt:

- `_prepare_import_accounts()`: Quellen, Zielkonten, Depotkompatibilität und Mapping von Kostenreports.
- `_validate_import_rows()`: Depotstichtage, ISIN-/Zahlprüfung sowie Buchungswarnungen und -fehler.
- `_deduplicate_tax_events()`: unveränderte externe ID-, Beleg- und Vorabpauschalenlogik.
- `_deduplicate_tax_details()`: unveränderte Detail-Deduplizierung und Duplicate-Rückgabe.
- `_prepare_import_identity()`: Payload, Dokumentvalidierung, Quellhash und stabiler Importdigest.

Die öffentliche Signatur, Rückgabewerte und Fehlermeldungen blieben erhalten. Sämtliche SQL-Schreiboperationen befinden sich weiterhin im ursprünglichen einzelnen `with self.db`-Block. Reihenfolge, frühe Duplicate-Rückgaben, Reads/Writes und Rollback-Grenzen wurden nicht verschoben.

Die drei Referenzimplementierungen hatten exakt dieselbe Semantik: keine Normalisierung von Groß-/Kleinschreibung, Leerraum oder Sonderzeichen; Fallback von `depot` auf `account` nur bei fehlendem Depot-Schlüssel; Pflichtfelder bleiben Pflichtfelder. Sie wurden in `portfolio_v5.transaction_reference.transaction_reference()` zusammengeführt. Die bisherigen Namen `asset_registry.transaction_ref` und `repository_v09.reference` bleiben als Aliase erhalten. Charakterisierungstests sichern Byteformat, Unicode, leeres Depot und historische `KeyError`-Semantik.

In `ImportSession.apply()` wurde ausschließlich die Prüfung und Persistenz von Buchungsersetzungen in `_record_replacements()` ausgelagert. Der Helfer ist statisch und wird über die Klasse aufgerufen, weil Integrationstests und kompatible Nicht-UI-Aufrufer `ImportSession.apply(None, ...)` verwenden. Fehlertexte und SQL-Reihenfolge sind unverändert.

## Komplexität und Umfang

Die zyklomatische Komplexität von `Store.import_batch()` sank laut Ruff C901 von 79 auf 29, die physische Methodengröße von 293 auf 133 Zeilen. Die verbleibende Komplexität liegt fast vollständig in der bewusst nicht verschobenen Persistenzphase. Eine weitere Aufteilung wäre erst sinnvoll, wenn Transaktions- und Query-Reihenfolge mit zusätzlichen SQL-Trace-Tests festgeschrieben ist.

In den produktiven Quelldateien wurden 168 Zeilen ergänzt und 102 entfernt. Hinzu kommen 140 Testzeilen und dieser Bericht. Die Nettozunahme entsteht durch benannte Verantwortlichkeiten, Charakterisierung und Dokumentation; drei fachliche Referenzduplikate wurden entfernt. Eine unbenutzte Importzeile wurde gelöscht. Öffentliche Schnittstellen kamen nicht hinzu; die neuen Helfer sind intern.

Die Zahl der SQLite-Zugriffe ist unverändert: Die Extraktion verschiebt vorhandene Anweisungen, fügt aber keine Abfrage und keinen Schreibzugriff hinzu. Die einzige neue Modulabhängigkeit zeigt von drei Verbrauchern auf den schichtenneutralen, ausschließlich von `json` abhängigen Referenzbaustein. Abhängigkeiten in Gegenrichtung und neue Zyklen entstanden nicht.

## Entfernte Funktionen und sichere Bereinigung

Es wurde keine Funktion oder Klasse gelöscht: Für keinen weiteren Kandidaten ließ sich die Nichtverwendung unter Berücksichtigung von Qt, Plugins, Reflection, `getattr()`, Konfiguration, Tests und externen Einstiegspunkten ausreichend beweisen. Entfernt wurden die drei identischen lokalen Referenzfunktionskörper; die zwei öffentlich importierbaren Namen bleiben als kompatible Aliase erhalten. Zusätzlich wurde der durch Ruff F401 nachgewiesene unbenutzte `Path`-Import aus `tax_detail_view.py` entfernt.

## Fehlerbehandlung, Rollback und dynamische Aufrufe

- `batch.errors`, bestehende `ValueError`-Texte und Warnungsreihenfolge bleiben unverändert.
- `PortfolioRepository.commit_batches()` übersetzt erwartete Batchfehler weiterhin in Ergebnisobjekte; `ImportSession.apply()` bricht den äußeren atomaren Ablauf weiterhin ab.
- Der GUI-Pfad nutzt nachweislich `RepositoryV09.commit_batches()` und damit V09-Nachverarbeitung.
- Qt-Signals/Slots, Plugin-Handler und Parserregistrierung wurden nicht umbenannt oder verschoben.
- Der dynamische kompatible Aufruf `ImportSession.apply(None, ...)` wurde explizit durch die Vollsuite erkannt und abgesichert.

## Nicht umgesetzte, riskante Kandidaten

- Aufteilung des SQL-Persistenzblocks in weitere Helfer: hoher Nutzen, aber Risiko einer veränderten Query-/Transaktionsreihenfolge; zuerst SQL-Trace-Charakterisierung ergänzen.
- Zusammenführung von `commit_reports()` und `ImportSession.apply()`: beide erreichen dasselbe Repository, besitzen aber unterschiedliche Backup-, Fortschritts-, Konflikt- und Fehlerverträge.
- Vereinheitlichung aller bankspezifischen `selected_batches()`-Methoden: ähnliche Oberfläche, jedoch abweichende Qt-Zustände und Zuordnungsregeln.
- Umbau von `ImportSession.resolve()` (C901 21): fachlich sensible Konflikt-/ID-Logik; separat mit Matrix-Tests bearbeiten.
- Direkter Legacy-Aufruf in `import_jobs.py`: weitere Prüfung erforderlich; nicht ohne vollständige Job-/Callback-Analyse auf RepositoryV09 umstellen.

## Qualitätssicherung

Fünf neue Golden-Master-/Charakterisierungstests wurden als erster Branch-Commit angelegt. Sie prüfen erfolgreichen Einzel-/Batchimport, Ergebnisformat, PDF-/Quelldublettenäquivalent, erzwungenen Wiederholungsimport, ungültige Transaktion, Fehler während der Persistenz, vollständigen Rollback, Konto-/Depotmapping, Performance-Depotmapping und zwei Importreihenfolgen. Derselbe Teststand lief auf dem Ausgangscode (`1ce0e06`, vor den Produktionsänderungen) mit `5 passed` und nach dem Refactoring mit `5 passed`.

Die übrigen geforderten Fälle werden durch bestehende, unverändert beibehaltene Tests charakterisiert:

- primäres/zusätzliches Verrechnungskonto sowie Kauf/Verkauf: `test_depot_booking_reconciliation.py`;
- Dividenden, Steuerereignisse und Gebühren: `test_comdirect_investment_distribution_tax.py`, `test_advance_tax_events.py`, `test_fee_links.py`;
- historische Datenbanken und Migration: bestehende Repository-/Migrationssuiten;
- Performancewerte, Positionen, Cashflows und Salden: Performance-, Settlement-, State-History- und Balance-Suiten;
- comdirect-Neuimport und beide Reihenfolgen aus PR #27: `test_comdirect_p1_integrity.py` und `test_comdirect_investment_distribution_tax.py`;
- GUI-Aktion, Atomarität und äußerer Rollback: `test_import_atomic.py`.

Ausgeführte Abschlussprüfungen:

- `python -m compileall -q src/portman src/portfolio_v5`: erfolgreich.
- `python -m ruff check src/portman src/portfolio_v5 --select F`: erfolgreich.
- Gezielte geänderte Import-/GUI-/comdirect-Suite: `33 passed`.
- Vollständige Pytest-Suite: `1131 passed, 14 skipped` in 479,90 Sekunden.

Der temporäre Vorher-/Nachher-Datenbankvergleich prüft stabile fachliche Payloads statt volatiler Importzeitstempel und IDs. Importresultate, Depotpositionen, Buchungen, Kontozuordnungen und Rollbackzustand waren identisch. Es wurden keine produktive Datenbank und keine Originalbelege geöffnet oder verändert.

## Verbleibende technische Schulden

- `Store.import_batch()` bleibt mit C901 29 oberhalb des Projektziels, weil die zusammenhängende Persistenzphase noch nicht künstlich zerlegt wurde.
- `_prepare_import_accounts()` (16), `_validate_import_rows()` (12), `_prepare_import_identity()` (12) und `_deduplicate_tax_events()` (11) bleiben fachlich kohäsiv, obwohl Ruff sie als komplex markiert.
- `ImportSession.resolve()` bleibt bei C901 21 und benötigt vor einem Umbau eine vollständige Konfliktmatrix.
- Die bankspezifischen Qt-Vorschauen besitzen ähnliche, aber nicht erwiesen identische Zustandsautomaten.

## Empfehlung für Phase 3

Als nächstes sollten SQL-Trace-Tests die exakte Schreib- und Read-Reihenfolge von `Store.import_batch()` charakterisieren. Danach kann die Persistenz in drei transaktionsinterne Helfer für Importkopf/Dokumente, Depotstände/Salden und Transaktionen/Coverage zerlegt werden. Separat sollte `ImportSession.resolve()` mit tabellarischen Konfliktfällen abgesichert werden, bevor dort Komplexität reduziert wird.
