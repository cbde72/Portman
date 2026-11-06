# Parserprüfung – 6. November 2026

## Fixierter V10-Stand

V10 bindet `portman-parsers` reproduzierbar an den vollständigen Commit
`816034a09bd71d092fed4fc30e245a4baadfe3f0`, den nach einem Fetch aktuellen
Stand von `origin/main`. Die Bindung steht in `requirements-parser.txt` als
Git-URL mit `subdirectory=portman-parsers`. In der V10-Umgebung wird daraus eine
nicht-editable Installation erzeugt; es besteht kein Verweis auf den
veränderlichen ursprünglichen Checkout `PortmanNL`.

Das Paket hat Version `0.6.0`, verlangt Python >=3.11 und deklariert
`pypdf>=6,<7` sowie `PyYAML>=6,<7`. Die Projektlizenz ist MIT. Für
`plugins/comdirect_pp.py` gilt gemäß `NOTICE_COMDIRECT_PP.md` die mitgelieferte
EPL-1.0. Es gibt keine Python-Paket-Entry-Points oder Konsolenskripte. Der
öffentliche Einstieg ist programmatisch:

```python
from portman_parsers.registry import default_registry

registry = default_registry()
detection = registry.select(document)
result = registry.parse(document, detection) if detection is not None else None
```

`default_registry()` registriert deterministisch eine feste Allowlist.
`select()` verwendet standardmäßig `Decimal("0.70")` als Mindestkonfidenz und
meldet gleich starke Treffer verschiedener Handler als Mehrdeutigkeit.
`parse()` lehnt unbekannte und nur als Metadaten vorhandene Handler ausdrücklich
ab.

## Handler auf `origin/main`

Die fixierte Allowlist enthält 42 Handler in zehn Plugin-IDs. Davon sind 22 als
`IMPLEMENTED` registriert und über konkrete Plugin-Klassen ausführbar:

- `user.comdirect-ertraege` 2.0: neun Handler.
- `comdirect.finanzreport` 3.0: `finanzreport`.
- `portfolio-performance.comdirect` `pp-c08d5053`: neun Handler.
- `fnz.finvesto` 2.0: `umsatzabrechnung` und `depotauszug`.
- `user.bank-of-scotland-kontoauszug` 1.0: `kontoauszug`.

Baader, ING, Deka, Renault und der generische Kontoauszug sind in diesem Stand
nur Metadaten. `pbb_direkt` und `baader_krypto` sind blockiert.

## Unterschied zum ursprünglichen Checkout

Der ursprüngliche Arbeitsbereich steht auf `bdc8eb8`. Gegenüber dem fixierten
Stand enthält er 19 geänderte Parser-/Testdateien mit 2.901 Ergänzungen und 94
Entfernungen. Fachlich relevant sind insbesondere:

- ausführbare Baader-Handler aus `70b2da1`,
- ausführbare ING-Handler aus `3252b56`,
- ein unabhängiger Deka-Handler aus `e01ee08`,
- strengere FNZ-Evidence-Validierung aus `29d0fff`,
- mehrere comdirect-Korrekturen für historische Finanzreports, Evidence,
  Gebühren, Schriftentschlüsselung und Mengenextraktion.

Diese Änderungen werden nicht pauschal übernommen. Für V10-01 bis V10-04 genügt
`origin/main`, weil noch kein produktiver Parseradapter implementiert wird. Vor
V10-12 muss für den zuerst angebundenen Dokumenttyp gezielt entschieden werden,
welche der oben genannten Commits benötigt werden; dieser Parserstand ist dann
separat auf einen vollständigen Commit zu fixieren und erneut zu testen.

## Öffentlicher Vertrag

`API_VERSION` ist `0.6`. Eingabe ist ein `PdfDocument`; Erkennung liefert eine
`Detection`. `ParsedDocument` enthält Events, Snapshots, Evidence, Issues,
Konten, Depots, Salden, Depotstände, Kontoverknüpfungen und
Vorabpauschalen-Daten. Relevante DTOs sind insbesondere `FinancialEvent`,
`CashMovement`, `SecurityMovement`, `SecurityTrade`, `TaxEvent`, `TaxComponent`,
`FeeEvent`, `CostEvent`, `AccountBalance` und `DepotSnapshot`.

Beträge und Mengen sind `Decimal`. Fehlende Werte werden durch `MissingValue`
oder `FieldValue` dargestellt, nicht als Nullbetrag. Steuer- und
Kostenkomponenten erzeugen nicht selbstständig eine Geldbewegung;
Bestandsnachweise sind keine synthetischen Käufe. Evidence-IDs sowie Dokument-
und Parseridentitäten müssen beim Mapping erhalten bleiben. Ein späterer
V10-Adapter gehört ausschließlich in `infrastructure`; Parser-DTOs dürfen nicht
in Domain oder Anwendungsschnittstelle durchsickern.

## Ausgeführte Prüfung

Installation und Prüfungen liefen mit
`C:\Users\chris\Desktop\programming\PortmanV10\portman-v10\.venv\Scripts\python.exe`.
Der installierte Parser liegt unter `.venv\Lib\site-packages\portman_parsers`;
`direct_url.json` weist exakt den oben genannten Commit und das Unterverzeichnis
`portman-parsers` aus.

Die Parser-Suite des fixierten Worktrees ergab 196 bestandene und einen
übersprungenen Test in 4,45 Sekunden. Übersprungen wurde ausschließlich der
optionale PDFium-Test, weil `pypdfium2` nicht installiert ist. Die vier
vorhandenen V10-Vertragstests sind ebenfalls bestanden.
