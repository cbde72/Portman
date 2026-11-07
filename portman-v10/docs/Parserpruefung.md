# Parserprüfung – 6. November 2026

## Versionierter Funktionsstand

V10 verwendet den vollständig geprüften Parserfunktionsstand aus
`bdc8eb82ea2bd68a760f62716546e898a30023a6`. Der geprüfte Parserdiff wurde auf
`main` aufgesetzt und liegt im offenen PR #68 auf Branch
`codex/portman-parsers-0.7.0-main`, Kopfcommit
`227eaafb4fb49e4357006546a0855ea7a0668c0a`:

- Paketversion `0.7.0` in `pyproject.toml` und `portman_parsers.__version__`,
- aktualisierte README mit 35 ausführbaren und 7 reinen Metadaten-Handlern,
- Vertragstest für die Paketversion.

Die öffentliche `API_VERSION` bleibt `0.6`, das serialisierte Ergebnisschema
bleibt `1.6.0`. Zwischen der zuvor geprüften API und dem neuen Funktionsstand
wurden keine DTO- oder Serialisierungsverträge geändert; eine Erhöhung wäre
daher irreführend. Paketversion 0.7.0 kennzeichnet die zusätzlichen und
gehärteten Parserimplementierungen.

## Reproduzierbare Bindung

`requirements-parser.txt` enthält den Pin auf den vollständigen PR-Kopfcommit
über `https://github.com/cbde72/Portman`. Der Branch wurde gepusht und der
Commit ist remote auflösbar. Ein Release-Tag wurde nicht angelegt.

Für die lokale Prüfung bindet `requirements-parser-local.txt` denselben Commit
über den separaten Git-Worktree
`C:\Users\chris\Desktop\programming\PortmanParsers070Main`. Pip baut daraus ein
normales Wheel. Es entsteht weder eine editable Parserinstallation noch ein
Verweis auf den veränderlichen ursprünglichen Worktree `PortmanNL`.

Der Remote-Pin wurde in einer frischen Umgebung
`C:\Users\chris\AppData\Local\Temp\portman-v10-pr68-verify` installiert.
Pip löste den vollständigen Commit auf GitHub auf und installierte ein Wheel
`portman-parsers-0.7.0`. `direct_url.json` bestätigt URL
`https://github.com/cbde72/Portman.git` und Commit
`227eaafb4fb49e4357006546a0855ea7a0668c0a`.

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
- frische Remote-Installation in V10-`.venv` und 4 V10-Vertragstests bestanden,
- Ruff für die tatsächlich geänderten Python-Dateien: bestanden.

Die frische Remote-Umgebung verwendete Python 3.14.3 unter
`C:\Users\chris\AppData\Local\Temp\portman-v10-pr68-verify`. `direct_url.json`
bestätigt den Remote-Commit; der Import erfolgt aus deren `Lib\site-packages`.

Der vollständige Ruff-Lauf meldet 181 bereits im Basiscommit vorhandene
Pyflakes-Befunde, vor allem wegen des Sternimports in `comdirect.py` und
ungenutzter Altimporte. Sie wurden nicht im Versionierungsauftrag refaktoriert;
die vollständige Testsuite bleibt grün. Das unabhängige lesende Review fand
keine blockierenden oder mittleren Befunde. Sein niedriger Befund zur fehlenden
Kopplung von `__version__` und Distributionsmetadaten wurde im finalen Commit
durch einen zusätzlichen Vertragstest behoben.

## V10-Vorgangsabdeckung – Prüfung vom 7. November 2026

Quelle ist `default_registry()` aus der installierten Paketversion 0.7.0. Sie
führt 19 ausführbare comdirect-Handler in drei Plugins. „Ausführbar“ sagt nur,
dass der Parser einen Handler anbietet. V10 gibt Übernahme nur für die in der
Tabelle ausdrücklich freigegebenen Handler-/Ereigniskombinationen frei.

| Plugin / Handler | Tatsächlich gelieferter Vorgang | V10-Wirkung / Stand | Nachweis oder konkreter Rückhaltegrund |
|---|---|---|---|
| `user.comdirect-ertraege / wertpapierkauf` | `BUY`, Geld- und Mengenbewegung | Übernahme mit Parservorzeichen; Zuordnung zu Konto und Instrument sowie sichere Referenz erforderlich | Synthetischer Parser-PDF-Kauf; A2H57N-Original-PDF: `−49,92 EUR`, `+0,25 Stück`, ISIN `LU1681041973`, WKN `A2H57N`; in der vorhandenen lokalen V10-Testdatenbank fehlt der ISIN-Stammsatz |
| `user.comdirect-ertraege / wertpapierverkauf` | `SELL`, Geld- und negative Mengenbewegung | Übernahme bei vollständigen Zuordnungen und sicherer Referenz | Synthetischer echter Parserlauf und SQLite-Commit: `+100 EUR`, `−1 Stück`; ohne Referenz bleibt die Dublettenprüfung offen |
| `user.comdirect-ertraege / einloesung` | `REDEMPTION`, Geldgutschrift und negative Menge | Übernahme bei vollständigen Zuordnungen und sicherer Referenz | Synthetischer echter Parserlauf und SQLite-Commit; Rücknahme-/Korrekturfälle werden nicht als normale Einlösung freigegeben |
| `user.comdirect-ertraege / dividendengutschrift` | `DIVIDEND`, tatsächliche Geldgutschrift; keine Mengenbewegung | Übernahme nur der Nettogutschrift, wenn Konto und Referenz eindeutig sind | Echter Parserlauf und SQLite-Commit; `+3,68 EUR`, keine Depotposition; Parserwarnungen zu nicht benötigter Stückzahl/Instrumentidentität werden für diesen Vorgangstyp nicht als Kaufpflicht behandelt |
| `user.comdirect-ertraege / ertragsgutschrift` | `DIVIDEND`, tatsächliche Gutschrift | Übernahme nur der Geldbewegung, keine Mengenbewegung | Echter Parserlauf und SQLite-Commit; `+5 EUR`, keine Depotposition |
| `user.comdirect-ertraege / investment_ausschuettung` | `TAX_NOTICE`, Steuerdaten, keine tatsächliche Geld-/Mengenbewegung | Information, keine Buchung; Steuerbasis und Freistellungsverbrauch bleiben Details | Echte lokale Parserabrechnung und synthetischer Parser-PDF-Test; kein „Stückzahl fehlt“-/„Settlement fehlt“-Prüfpunkt |
| `user.comdirect-ertraege / dividende_steuer_inland` | `TAX_NOTICE`, tatsächliche Steuer-/Bemessungsfelder ohne Auszahlung | Information, keine Buchung | Synthetischer echter Parserlauf; Steuerkomponenten bleiben ohne zusätzliche Geldbewegung |
| `user.comdirect-ertraege / vorabpauschale` | `ADVANCE_TAX`, Steuerberechnung/-mitteilung | Information, keine Buchung; nur tatsächlich gelieferte Steuerfelder | Synthetischer echter Parserlauf; Freistellungsverbrauch/Bemessungsbasis werden nicht als Geldbewegung gebucht |
| `user.comdirect-ertraege / kosteninformation_mifid_ii` | Kosteninformation | Dokumentinformation, keine Buchung | Synthetischer echter Parser-PDF-Test; Kostenfelder zählen nicht als Position |
| `comdirect.finanzreport / finanzreport` | Salden/Bestände oder einzelne `CASH_BOOKING`-Zeilen | Salden/Bestände Information; Zeilen getrennt in der Vorschau, noch keine Übernahme | Echte Parser-PDF-Zeilen mit `+10 EUR` und `−2,50 EUR`, getrennten Quellen und Kontoabgleich. Übernahme bleibt offen: der Bericht liefert keine sichere Einzelreferenz, Beträge/Datum sind kein Dublettenschlüssel |
| `portfolio-performance.comdirect / wertpapierkauf` | PP-`BUY` | Zurückgehalten | Direkter öffentlicher Parservertrag liefert PP-Geldbewegung mit Status `EXPECTED`; V10 akzeptiert nur den präzisen user-Handler mit tatsächlicher Geldbewegung |
| `portfolio-performance.comdirect / wertpapierverkauf` | PP-`SELL`, teils mit Steuerdaten | Zurückgehalten; Steuerfall ohne Geldbewegung als Parserlücke | Echte lokale Steuermitteilung wurde als PP-Verkauf erkannt und lieferte `−21,826` Parsermenge ohne Geldbewegung. V10 verwirft die Menge als Bestandswirkung und zeigt „Parserlücke … keine tatsächliche Geldbewegung“ |
| `portfolio-performance.comdirect / einloesung` | PP-`REDEMPTION` | Zurückgehalten | Parserstatus/Settlement und tatsächliche Kontowirkung sind für den V10-Übernahmepfad nicht freigegeben |
| `portfolio-performance.comdirect / dividendengutschrift` | PP-`DIVIDEND` | Zurückgehalten | PP-Geldbewegung ist `EXPECTED`, nicht als tatsächliche Gutschrift buchbar |
| `portfolio-performance.comdirect / ertragsgutschrift` | PP-`DIVIDEND` | Zurückgehalten | PP-Geldbewegung ist `EXPECTED`, nicht als tatsächliche Gutschrift buchbar |
| `portfolio-performance.comdirect / investment_ausschuettung` | `TAX_NOTICE` oder vom Selektor fehlklassifizierter PP-Verkauf | Steuerereignis ohne Bewegungen: Information; alleinige Steuer+Mengenbewegung: Parserlücke | Direkter Registry-Parserlauf plus lokale fehlklassifizierte Steuermitteilung; keine synthetische Position |
| `portfolio-performance.comdirect / dividende_steuer_inland` | `TAX_NOTICE` | Information, keine Buchung | Öffentlicher Parservertrag; sofern Steuerereignis ohne tatsächliche Geldbewegung geliefert wird |
| `portfolio-performance.comdirect / vorabpauschale` | `ADVANCE_TAX` | Information, keine Buchung | Öffentlicher Parservertrag; keine Steuerbasis als Geldbewegung |
| `portfolio-performance.comdirect / finanzreport` | Snapshot-Information oder einzelne Reportereignisse | Snapshot Information; Reportbewegungen getrennt, aber noch nicht übernehmbar | Öffentlicher Parservertrag; fehlende sichere Einzelreferenz und PP-Status verhindern Dublettensicherheit |

### Fachliche Regeln der V10-Abbildung

- Die adapterseitigen Pflichtangaben hängen von tatsächlichen Bewegungen ab.
  Fehlende Stückzahl-/Settlementfelder blockieren nur Vorgänge, die eine
  Parser-Mengenbewegung bzw. Geldbewegung erwarten. Eine echte `DIVIDEND`-
  Gutschrift benötigt keine Stückzahl und erzeugt keine Depotposition.
- Steuerereignisse ohne echte Geldbewegung bleiben bewegungsneutral. Ein
  Parser-`SecurityMovement` zusammen mit Steuerdaten und ohne `CashMovement`
  ist keine belastbare Bestandsänderung; der Kandidat bleibt als konkrete
  Parserlücke offen und die strukturierte Parsermenge steht nur in den Details.
- Kauf, Verkauf und Einlösung verwenden Parservorzeichen. Gebühren und Steuern
  bleiben Komponenten; sie werden nicht zusätzlich zur Nettobewegung gebucht.
- Fehlende sichere Bankreferenz bleibt ein roter Prüfpunkt. Datum und Betrag
  werden nicht zum automatischen Zusammenführen verwendet.
- Tests laufen mit echter Registry-/Parser-API und synthetischen PDFs in
  temporären SQLite-Datenbanken. Die lokale A2H57N-PDF und die weiteren echten
  Referenzbelege blieben außerhalb des Repositories.

Die V10-Übernahme der beiden PP-Finanzreport-Aliase, sichere Ergänzung eines
Finanzreports zu Einzelbelegen und echte Kontoauszugszeilen sind weiterhin
offen. Sie sind nicht als „alle comdirect-Dokumente funktionieren“ gewertet.
