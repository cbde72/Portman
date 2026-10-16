# Portman V09 – Datenqualität und Laufzeitperformance

Stand: 16. Oktober 2026 · Branch `codex/data-quality-performance-audit`

## Priorisierte Befunde

| Priorität | Befund | Reproduktion | Ergebnis |
|---|---|---|---|
| P0 | Importblockaden wurden in `storage.py` und `pdf_importer.py` anhand deutscher Meldungstexte erkannt. Textänderungen konnten die fachliche Schwere verändern. | Nicht endlichen Buchungsbetrag importieren und Meldungstext ändern. | Behoben durch `ValidationIssue.code`, `severity` und `field`. |
| P1 | `_valuation_series()` sowie Wallet- und Transferpfade luden alle Zeilen aus `wallet_daily_values`, auch für ein einzelnes Depot. | Benchmark mit 10.000 relevanten Snapshots und 100.000 Wallet-Zeilen. | Behoben durch indexgestützte, in 900 IDs gestückelte Abfragen. |
| P1 | Vollständige, teilweise und fehlerhafte Importergebnisse waren nur indirekt aus Warnungen, Fehlern und Snapshot-Flags erkennbar. | Batch mit `Snapshot.complete=False`. | Abgeleiteter Status `complete`, `partial`, `invalid`; keine neue Serialisierung. |
| P1 | Zahlen-, Steuer-, FX- und Vorabpauschalenregeln waren in älteren Ständen teilweise heuristisch. | Grenzfälle in `test_models_v2.py`. | Explizite Locale-/FX-Felder, Komponentenprüfung und strukturierte Vorabpauschalen sind im Ausgangsstand enthalten und regressionsgeprüft. |
| P2 | Snapshot-/Positions-Grundvalidierung existiert weiterhin sowohl in PDF-Vorprüfung als auch in der gemeinsamen Speicherpipeline. | Vergleich `_validate_plugin_batch()` mit `Store.import_batch()`. | Verbleibendes Risiko; eine spätere Vereinheitlichung sollte einen eigenen strukturierten Snapshot-Befundtyp verwenden. |
| P2 | OCR-Laufzeit hängt stark von Dokument, Rendering und lokalem Modell ab und ist mit synthetischen Text-PDFs nicht repräsentativ. | OCR-Cache-Tests und Suite-Dauern. | Cache-Identität ist inhaltlich abgesichert; keine unbelegte Laufzeitänderung vorgenommen. |

## Patch 1 – stabile Validierungsbefunde

Ursache: Fachliche Steuerung war an übersetzbare Meldungstexte gekoppelt.

Geändert:

- `src/portfolio_v5/models.py`
- `src/portfolio_v5/storage.py`
- `src/portfolio_v5/pdf_importer.py`
- `tests/test_models_v2.py`

Auswirkung:

- Jeder Transaktionsbefund besitzt stabilen Code, Schweregrad und optionalen Feldbezug.
- Befunde bleiben Unterklassen von `str`; bestehende Anzeigen, Logs und Aufrufer funktionieren weiter.
- Blockierende Importfehler werden ausschließlich über `severity == "error"` bestimmt.
- `ImportBatch.quality_status` ist berechnet und verändert weder Dataclass-Felder noch JSON-Payloads.

Risiko: Snapshot- und Positionsbefunde sind noch nicht auf denselben strukturierten Typ umgestellt.

## Patch 2 – selektives Laden historischer Wallet-Werte

Ursache: Drei Laufzeitpfade führten `SELECT * FROM wallet_daily_values` aus. Bei einem gefilterten Depot wuchs Laufzeit und Speicherbedarf mit der gesamten Datenbank.

Geändert:

- `src/portman/wallet_valuation.py`
- `src/portman/performance_service.py`
- `src/portman/portfolio_transfer.py`
- `tests/test_wallet_valuation.py`

Auswirkung:

- Es werden nur Werte relevanter Snapshot-IDs geladen.
- Abfragen nutzen den bestehenden Primärschlüssel `(snapshot_id, security_key)`.
- Chunks mit maximal 900 Parametern bleiben unter üblichen SQLite-Parametergrenzen.
- Bewertungs-, Rendite- und Rundungsformeln wurden nicht geändert.
- Keine Datenbankmigration und kein zusätzlicher Index erforderlich.

## Benchmark

Aufruf:

```text
python benchmarks/benchmark_valuation_series.py --size small --repetitions 5
python benchmarks/benchmark_valuation_series.py --size medium --repetitions 5
python benchmarks/benchmark_valuation_series.py --size large --repetitions 5
```

Gemessen wurde der Median auf derselben Maschine und Python-Umgebung. Jeder Fall enthält zehnmal mehr globale Wallet-Zeilen als für das betrachtete Depot relevante Snapshots.

| Größe | Relevante Snapshots | Wallet-Zeilen | Vorher | Nachher | Verbesserung |
|---|---:|---:|---:|---:|---:|
| klein | 200 | 2.000 | 0,0091 s | 0,0021 s | 77 % |
| mittel | 2.000 | 20.000 | 0,0779 s | 0,0314 s | 60 % |
| groß | 10.000 | 100.000 | 0,3679 s | 0,1205 s | 67 % |

Der Benchmark bildet gezielt den nachgewiesenen SQL-/Bestandsengpass ab. Start, GUI und OCR werden durch die vollständige Testsuite mit Dauerreport beobachtet; ohne reproduzierbaren produktionstypischen Engpass wurden dort keine spekulativen Änderungen vorgenommen.

Der Dauerreport des vollständigen Laufs weist als größten Integrationspfad die komplette V09-Fensterinitialisierung mit rund 60 Sekunden aus. Theme-/Qt-Initialisierung folgt mit rund 18 Sekunden. Diese Tests bündeln viele GUI-Komponenten und isolieren noch keinen einzelnen Produktionsengpass; deshalb wurde daraus in diesem Patch keine riskante Startlogik-Änderung abgeleitet. Ein Folgebenchmark sollte Fensteraufbau, initiale Repository-Abfragen und erstes Chart-Rendering getrennt instrumentieren.

## Importer- und Cache-Audit

- PDF-Plugins werden bei nahezu gleicher Erkennung verschiedener Handler nicht automatisch ausgewählt.
- Unvollständige Snapshots ersetzen keine vollständigen Bestände (`complete=False`).
- Dubletten mit widersprüchlichen stabilen Belegreferenzen werden getrennt gehalten.
- Datei-, OCR- und Workbook-Caches berücksichtigen Inhalt beziehungsweise Änderungsidentität.
- Importvorschau, Rollback, Sicherung und Kontozuordnung bleiben unverändert.
- Fehlerhafte numerische Werte und cash-wirksame Vorabpauschalen blockieren vor dem Schreiben.

## Verbleibende Risiken

1. Importprofile müssen ihr Zahlen-Locale korrekt deklarieren; ein falsch deklariertes Quellformat kann nicht allein aus dem Wert erkannt werden.
2. Historische FX-Datensätze ohne explizites Paar behalten absichtlich die alte Divisionskonvention.
3. OCR-Benchmarks benötigen einen freigegebenen, repräsentativen und anonymisierten Dokumentkorpus.
4. Für einen Gesamtportfolio-Aufruf sind naturgemäß alle zugehörigen Wallet-Werte relevant; der Gewinn entsteht vor allem bei Depotfiltern und Exportteilmengen.
5. Eine spätere Vereinheitlichung der Snapshot-/Positionsvalidierung sollte separat erfolgen, damit Importprofile nicht unbeabsichtigt strenger werden.
