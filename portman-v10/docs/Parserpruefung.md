# Parserprüfung – 6. November 2026

## Versionierter Funktionsstand

V10 verwendet den vollständig geprüften Parserfunktionsstand aus
`bdc8eb82ea2bd68a760f62716546e898a30023a6`. Darauf liegt ausschließlich der
Versionierungscommit `0c860ccbd91e7f6b4bec15743ce8e360b8050772`:

- Paketversion `0.7.0` in `pyproject.toml` und `portman_parsers.__version__`,
- aktualisierte README mit 35 ausführbaren und 7 reinen Metadaten-Handlern,
- Vertragstest für die Paketversion.

Die öffentliche `API_VERSION` bleibt `0.6`, das serialisierte Ergebnisschema
bleibt `1.6.0`. Zwischen der zuvor geprüften API und dem neuen Funktionsstand
wurden keine DTO- oder Serialisierungsverträge geändert; eine Erhöhung wäre
daher irreführend. Paketversion 0.7.0 kennzeichnet die zusätzlichen und
gehärteten Parserimplementierungen.

## Reproduzierbare Bindung

`requirements-parser.txt` enthält den vorgesehenen Pin auf den vollständigen
Commit über `https://github.com/cbde72/Portman`. Der Commit ist nur lokal und
wurde bewusst weder gepusht noch getaggt. Eine Abfrage des Remotes lieferte
keinen Treffer; die Remote-Anforderung ist daher derzeit nicht installierbar.

Für die lokale Prüfung bindet `requirements-parser-local.txt` denselben Commit
über den separaten Git-Worktree
`C:\Users\chris\Desktop\programming\PortmanParsers070`. Pip baut daraus ein
normales Wheel. Es entsteht weder eine editable Parserinstallation noch ein
Verweis auf den veränderlichen ursprünglichen Worktree `PortmanNL`.

## Ausführbare Handler

Die feste Allowlist enthält 42 Handler. In 0.7.0 sind 35 ausführbar:

- comdirect: neun Wertpapier-/Steuerhandler, Finanzreport und neun
  Portfolio-Performance-informierte Handler,
- Baader: Quartals- und Jahresdepotauszug, Dividende, Vorabpauschale,
  Depotübertrag und Wertpapierabrechnung,
- ING: Dividende, Kauf, Verkauf, Vorabpauschale, Steuerverrechnung und
  Jahresdepotauszug,
- Deka: Quartalsbericht/Jahresdepotauszug,
- FNZ/finvesto: Umsatzabrechnung und Depotauszug,
- Bank of Scotland: Kontoauszug.

Renaults sechs Handler und der generische Kontoauszug bleiben Metadaten.
`pbb_direkt` und `baader_krypto` bleiben blockiert. Ausführbar bedeutet eine
konkret registrierte und getestete Implementierung, nicht eine pauschale Zusage
für jedes historische Layout. Issues, Evidence und explizit unbekannte Werte
müssen im späteren V10-Adapter erhalten bleiben.

## Vertrag und Abhängigkeiten

Eingabe ist `PdfDocument`, die Erkennung liefert `Detection`, das Ergebnis
`ParsedDocument`. Relevante DTOs sind unter anderem `FinancialEvent`,
`CashMovement`, `SecurityMovement`, `SecurityTrade`, `TaxEvent`, `FeeEvent`,
`AccountBalance` und `DepotSnapshot`. Beträge und Mengen sind `Decimal`.
Steuer-/Kostenkomponenten erzeugen nicht selbstständig Geldbewegungen und
Bestandsnachweise keine synthetischen Käufe.

Pflichtabhängigkeiten bleiben `pypdf>=6,<7` und `PyYAML>=6,<7`. Das optionale
Extra `pypdfium2>=4,<6` unterstützt die Textfallback-Extraktion. Der synthetische
Baader-PDFium-Test ist bestanden. Eine Prüfung mit autorisierten realen,
beschädigten Baader-PDFs steht weiterhin aus; solche PDFs oder Kontodaten werden
nicht in Git aufgenommen.

## Prüfungen

Im separaten Parser-Worktree wurde mit Python 3.14.3 in einer eigenen `.venv`
ausgeführt:

- vollständige Parsersuite mit installiertem PDFium-Extra: 268 bestanden,
- Wheel-Build: `portman_parsers-0.7.0-py3-none-any.whl` erfolgreich,
- Versionsprüfung: Paket 0.7.0, API 0.6, Schema 1.6.0,
- Ruff für die tatsächlich geänderten Python-Dateien: bestanden.

Der vollständige Ruff-Lauf meldet 181 bereits im Basiscommit vorhandene
Pyflakes-Befunde, vor allem wegen des Sternimports in `comdirect.py` und
ungenutzter Altimporte. Sie wurden nicht im Versionierungsauftrag refaktoriert;
die vollständige Testsuite bleibt grün. Das unabhängige lesende Review fand
keine blockierenden oder mittleren Befunde. Sein niedriger Befund zur fehlenden
Kopplung von `__version__` und Distributionsmetadaten wurde im finalen Commit
durch einen zusätzlichen Vertragstest behoben.
