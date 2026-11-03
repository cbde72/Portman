# Portman PDF Lab – technische Grundlage (Phase 2)

**Datum:** 30.10.2026  
**Aktives Repository:** `C:\Users\chris\Desktop\programming\PortmanNL`  
**Analysierter Stand:** `8eb0091bdd95cce40ee4ea35469e14ec139e2c8e`  
**Grundlage:** `C:\Users\chris\Desktop\Portman_PDF_Lab_Plugin_Abhaengigkeitsaudit_20261030.md` (Phase 1, Referenzstand `b9b14defbbf669aef1e5f303662a85e4c5168fa7`)  
**Umfang:** acht freigegebene Parsergruppen; `pbb_direkt.py` und `baader_krypto.py` ausdrücklich ausgeschlossen.

## 1. Ergebnis und verbindliche Entscheidung

Der analysierte Stand enthält **33 eindeutige Handler** in den acht freigegebenen Gruppen. Die Parserlogik ist fachlich weitgehend wiederverwendbar, aber nicht als Paket isoliert: praktisch alle Plugins hängen an `portfolio_v5.models`; mehrere zusätzlich an `booking_details`, `accounts` oder `importers`. Der Import über `portfolio_v5.pdf_plugins` lädt außerdem unnötig Registry und TOML-Konfiguration mit.

Für `portman-parsers` werden die Parseralgorithmen und eng zugehörigen Helper übernommen, jedoch gegen ein neues, portman-unabhängiges DTO/API angepasst. V09-Modelle, Store, Repository, GUI und Import-Commitlogik werden nicht übernommen. `portman-pdf-lab` konsumiert ausschließlich die öffentliche API von `portman-parsers`.

In dieser Phase wurden keine Parser migriert, keine GUI gebaut und keine vorhandenen Parser- oder Testfunktionen verändert.

## 2. Methode und Grenzen

- Statische Inventur aller `Detection.handler_id`-Erzeuger und aller `parse()`-Verzweigungen.
- Rekursive AST-Importanalyse einschließlich bedingter/lokaler Imports.
- Abgleich gegen konkrete Testfunktionen und synthetische Textfixtures.
- Charakterisierungslauf mit bestehenden Tests, ohne Sollwerte oder Testcode zu ändern.
- Keine privaten PDFs untersucht und kein echter PDF-Korpus in Git aufgenommen.
- Ein vorhandener Test ist ein Verhaltensnachweis für das jeweilige synthetische Beispiel, aber kein Nachweis vollständiger Layout-, Jahres- oder OCR-Abdeckung.
- Phase 1 und Phase 2 beziehen sich auf verschiedene Commits. Maßgeblich für die folgende Übernahmeliste ist der oben genannte Phase-2-Stand.

## 3. Vollständige Handler-Inventur

### 3.1 comdirect – 10 Handler

| Plugin | Handler | Erkennung | Parsepfad / Ergebnis |
|---|---|---|---|
| `user.comdirect-ertraege` | `dividendengutschrift` | `Abrechnung Dividendengutschrift` plus Settlementzeile | gemeinsamer Ertragspfad; Dividende, Steuern, Gebühren, Dokument |
| `user.comdirect-ertraege` | `ertragsgutschrift` | `Abrechnung Ertragsgutschrift` plus Settlementzeile | gemeinsamer Ertragspfad; Fonds-/Wertpapierertrag |
| `user.comdirect-ertraege` | `einloesung` | `Abrechnung Einlösung` plus Settlementzeile | gemeinsamer Ertragspfad; sonstige Bankbuchung |
| `user.comdirect-ertraege` | `kosteninformation_mifid_ii` | Kosteninformation, Wertpapier und Gesamtkosten | `_mifid_cost_information`; Kostenreport, ausdrücklich kein Cashflow |
| `user.comdirect-ertraege` | `investment_ausschuettung` | kompakte Steuerseite mit Investment-Ausschüttung und Kennung | `_investment_distribution_tax`; Steuerereignis/Referenzbeleg |
| `user.comdirect-ertraege` | `dividende_steuer_inland` | inländische Dividenden-Steuermitteilung und Kennung | `_dividend_tax`; Steuerereignis/Referenzbeleg |
| `user.comdirect-ertraege` | `vorabpauschale` | Titel und Wertpapierkennung | `_advance_tax`; Steuerereignis, nur belegte Steuerzahlung |
| `user.comdirect-ertraege` | `wertpapierkauf` | normaler oder kompakter beschädigter Trade-Text | `_trade`; Kauf, Gebühren, Steuern, Settlement |
| `user.comdirect-ertraege` | `wertpapierverkauf` | normaler oder kompakter beschädigter Trade-Text | `_trade`; Verkauf, Gebühren, Steuern, Settlement |
| `comdirect.finanzreport` | `finanzreport` | comdirect und `Finanzreport Nr.` | Cashkonten, Buchungen, Salden, Depot-Snapshot; alter und neuer Layoutpfad |

Hinweis: `_comdirect_fast.py` erzeugt keinen weiteren Handler. Es ist ein alternativer PDF-Importer-Fastpath für `finanzreport`. `_comdirect_depot.py` ist der Depotteil desselben Handlers.

### 3.2 Baader – 6 eindeutige Handler

| Handler | Marker | Core-Zweig / Ergebnis |
|---|---|---|
| `quartalsaufstellung` | `Quartalsaufstellung` | vollständiger Depot-Snapshot mit Summenprüfung |
| `jahresdepotauszug` | `Depotauszug per` | Jahres-Snapshot mit Depotwertprüfung |
| `dividende` | `Dividendenabrechnung` | Ertrag; Storno nur für verifizierte Fälle |
| `vorabpauschale` | `Vorabpauschale` | Steuerereignis und belegte Zahlung |
| `depotuebertrag` | `Depoteinlieferung` **oder** `Depotauslieferung` | bestandswirksamer Transfer ohne erfundenen Cashflow |
| `wertpapierabrechnung` | `Wertpapierabrechnung:` | interner Untertyp Kauf/Verkauf; Trade, Gebühren und Settlement |

Die sieben Markerzeilen in `baader.py` ergeben sechs Handler, da Ein- und Auslieferung absichtlich dieselbe Handler-ID verwenden.

### 3.3 ING – 6 Handler

| Handler | Ergebnis |
|---|---|
| `dividendengutschrift` | Dividende mit Brutto/Netto, Steuer und Referenzen |
| `kauf` | Kauf, Gebühren, Ausführung und Settlement |
| `verkauf` | Verkauf, Gebühren, Steuer und positives Netto-Settlement |
| `vorabpauschale` | Steuerbasis getrennt von tatsächlicher Belastung |
| `steuerverrechnung` | Erstattung/Belastung mit Komponentenprüfung |
| `jahresdepotauszug` | Snapshot mit Positionsanzahl und Gesamtkurswertprüfung |

### 3.4 Deka – 1 Handler

| Handler | Varianten / Ergebnis |
|---|---|
| `quartalsbericht` | Erkennt `Quartalsbericht` und `Jahresdepotauszug`; Depotübersicht/Snapshot sowie Umsatzblöcke für Ausschüttung und Wiederanlage |

### 3.5 FNZ / Finvesto – 2 Handler

| Handler | Ergebnis |
|---|---|
| `umsatzabrechnung` | Kauf, Ausschüttung, Wiederanlage, Gebühren, Steuern und Fremdwährung |
| `depotauszug` | Depot-Snapshot mit Gesamtwertprüfung |

### 3.6 Renault – 6 Handler

| Handler | Wirkung |
|---|---|
| `kontoauszug` | generische Buchungstabellenextraktion plus Renault-Salden-/Periodenprüfung |
| `zinsmitteilung` | nur Archivierung; keine doppelte Zins-/Steuerbuchung |
| `steuerbescheinigung` | nur Archivierung; kein zusätzliches Steuerereignis |
| `freistellungsauftrag` | nur Archivierung; keine FSA-Nutzung ableiten |
| `umsatzuebersicht` | nur Archivierung; keine überlappenden Buchungen erzeugen |
| `archiv` | Renault-Dokument ohne belegte Buchungstabelle, nur Archivierung |

Der generische Fallback ist eine eigene Parsergruppe und wird nicht Renault zugerechnet.

### 3.7 Bank of Scotland – 1 Handler

| Handler | Ergebnis |
|---|---|
| `kontoauszug` | Tages-/Festgeldbuchungen, Kontometadaten, Salden und Summenabgleich |

### 3.8 Generischer Dokument-Fallback – 1 Handler

| Handler | Klassifikationen | Wirkung |
|---|---|---|
| `generic` | Kontoauszug, Steuerbescheinigung, Zinsmitteilung, Wertpapierabrechnung, Depotauszug, Kosteninformation, Wertpapierinformation, Produktinformation, unbekannt | Dokumentablage; nur bei Klassifikation `Kontoauszug` Versuch der Buchungstabellenextraktion; immer prüfpflichtig |

**Verbindliche Gesamtsumme: 33 eindeutige Handler** (comdirect 10, Baader 6, ING 6, Deka 1, FNZ 2, Renault 6, Bank of Scotland 1, generisch 1).

## 4. Transitive Abhängigkeiten

### 4.1 Gemeinsamer API-Pfad

Alle Wrapper importieren `Detection` über `portfolio_v5.pdf_plugins`. Dessen `__init__.py` importiert nicht nur `api.py`, sondern auch `registry.py`; die Registry importiert `config.py`, und `config.py` wiederum zahlreiche V09-Modelle. Dadurch wird selbst für einen reinen Parserimport unnötig Discovery-/TOML-Code geladen.

Bereinigte Kette:

```text
plugin
└─ portfolio_v5.pdf_plugins
   ├─ api.py ── portfolio_v5.models.ImportBatch
   └─ registry.py
      └─ config.py ── portfolio_v5.models (Balance, Transaction, Snapshot, ...)
```

Entscheidung: In `portman-parsers` importieren Plugins ausschließlich aus einer schlanken öffentlichen API. Registry und optionale Profilparser dürfen keine Importzeit-Abhängigkeit der DTOs sein.

### 4.2 Closure pro Parsergruppe

| Gruppe | Parserinterne Closure | V09-Abhängigkeiten | Standardbibliothek |
|---|---|---|---|
| comdirect Erträge | nur `comdirect_ertraege.py` | `models`, `accounts.account_key`, API | `base64`, `datetime`, `decimal`, `re` |
| comdirect Finanzreport | Wrapper, `_comdirect_finanzreport_core`, `_comdirect_finanzreport_legacy`, `_comdirect_depot`, `_finanzreport_help` | `models`, `booking_details.enrich_details`, API | `base64`, `collections`, `decimal`, `re` |
| Baader | Wrapper, `_baader_core` | `models`, `importers.asset_type`, API | `base64`, `decimal`, `re` |
| ING | `ing_wertpapiere.py` | `models`, `booking_details.extract_bank_reference`, API | `base64`, `decimal`, `re` |
| Deka | `deka_quartalsbericht.py` | `models`, `booking_details.extract_bank_reference`, API | `base64`, `decimal`, `re` |
| FNZ | `fnz_finvesto.py` | `models`, API | `base64`, `decimal`, `re` |
| Renault | Wrapper, `_generic_document`, `_statement_classification`, `_statement_bookings` | `models`, `booking_details.classify_cash_booking/enrich_details`, API | `base64`, `collections`, `datetime`, `decimal`, `re` |
| Bank of Scotland | Plugin-Datei | `models`, `booking_details.classify_cash_booking/enrich_details`, API | `base64`, `decimal`, `re` |
| generisch | Wrapper, `_generic_document`, `_statement_classification`, `_statement_bookings` | `models`, `booking_details.classify_cash_booking/enrich_details`, API | `base64`, `collections`, `datetime`, `decimal`, `re` |

### 4.3 Alternative Importpfade, nicht Teil des reinen Plugin-Closures

| Datei | tatsächliche Rolle | Entscheidung |
|---|---|---|
| `_comdirect_fast.py` | Optimierung in `portfolio_v5.pdf_importer`; baut selbst `ImportBatch` und liest extrahierten PDF-Text | Nicht in Parserkern kopieren; als neuer Extraktionsadapter/Benchmark später neu implementieren |
| `_renault_import.py` | Repository-/Commit-Orchestrierung, Korrekturen und Batch-Import | Nicht in `portman-parsers`; fachlich relevante Periodenprüfung als Testspezifikation nutzen |
| `portfolio_v5.pdf_importer` | PDF-Lesen, OCR-Entscheidung, Pluginaufruf, V09-Validierung | Neu als Extraktions-/Orchestrierungsschicht; kein V09-Import |
| `portfolio_v5.pdf_ocr`, `pdf_text` | OCR und Textrekonstruktion | Separate optionale Adapter; nicht transitiv durch Parser-DTOs laden |

### 4.4 Externe Pakete

Die Parserdateien selbst benötigen nur die Python-Standardbibliothek. PDF/OCR-Pakete (`pypdf`, `pymupdf`, `pypdfium2`, `rapidocr`, `onnxruntime`) gelangen über V09-Importerpfade in den Graphen, nicht über die fachlichen Regex-/Mappingalgorithmen. Office-Pakete (`openpyxl`, `xlrd`) stammen aus dem allgemeinen `importers.py` und sind für Baader nur wegen `asset_type` transitiv sichtbar. Das ist eine unnötige Abhängigkeit.

## 5. Test-zu-Handler-Matrix

Legende: **direkt** = Handler/Parsepfad mit konkretem Beispiel geprüft; **indirekt** = Corepfad geprüft, aber Handler-ID/Detection nicht immer Gegenstand; **Lücke** = kein handlergenauer Charakterisierungstest gefunden.

| Gruppe / Handler | vorhandene Charakterisierung | Status / Lücke |
|---|---|---|
| comdirect `dividendengutschrift` | `test_comdirect_income_keeps_reference_for_later_assignment` | direkt; nur ein Layout |
| comdirect `ertragsgutschrift` | gemeinsamer Ertragspfad im vorgenannten Testbestand | indirekt; eigener Detection-/Golden-Test fehlt |
| comdirect `einloesung` | keine eigene Testfunktion gefunden | **Lücke** |
| comdirect `kosteninformation_mifid_ii` | gesamte `test_comdirect_mifid_cost.py`, einschließlich 23 reale lokale PDFs wenn vorhanden | direkt; reale Dateien sind umgebungsabhängig |
| comdirect `investment_ausschuettung` | `test_comdirect_investment_distribution_tax.py` | direkt, breit |
| comdirect `dividende_steuer_inland` | Tests für inländische Dividende in derselben Datei | direkt |
| comdirect `vorabpauschale` | `test_comdirect_vorabpauschale_*`, `test_phase_b_importers.py` | direkt |
| comdirect `wertpapierkauf` | `test_comdirect_trade_*`, `test_phase_b_importers.py` | direkt |
| comdirect `wertpapierverkauf` | `test_phase_b_importers.py`, kompakte Fixture | direkt |
| comdirect `finanzreport` | `test_comdirect_pdf.py`, `test_comdirect_simple_import.py`, `test_security_names.py` | direkt; alte/neue Layouts und Fastpath |
| Baader `quartalsaufstellung` | `test_quarter_checks_total_and_retains_statement_date` | direkt |
| Baader `jahresdepotauszug` | `test_baader_annual_statement_requires_matching_depot_total` | direkt |
| Baader `dividende` | `test_baader_dividend_keeps_*`, `test_baader_dividend_reversal.py` | direkt |
| Baader `vorabpauschale` | `test_baader_advance_tax_separates_basis_and_debit` | direkt |
| Baader `depotuebertrag` | `test_baader_delivery_is_quantity_only_transfer` | direkt; Gegenrichtung separat fehlt |
| Baader `wertpapierabrechnung` | `test_baader_trade_semantics.py`, `test_trade_uses_execution_day_*` | direkt; Kauf/Verkauf intern abgedeckt |
| ING `dividendengutschrift` | keine handlergenaue Funktion im ausgewählten Kernbestand | **Lücke** |
| ING `kauf` | keine handlergenaue Funktion im ausgewählten Kernbestand | **Lücke** |
| ING `verkauf` | `test_ing_sale_*`, Fixture `ing/verkauf/current-v1` | direkt |
| ING `vorabpauschale` | `test_ing_advance_tax_*`, Fixture `ing/vorabpauschale/current-v1` | direkt |
| ING `steuerverrechnung` | `test_ing_tax_refund_*`, Fixture `ing/steuererstattung/current-v1` | direkt |
| ING `jahresdepotauszug` | keine handlergenaue Funktion gefunden | **Lücke** |
| Deka `quartalsbericht` | `test_deka_missing_turnover_is_partial_snapshot`, `test_phase_c_baader_deka.py` | direkt; Quartal und historischer Jahresauszug |
| FNZ `umsatzabrechnung` | `test_phase_c_fnz.py`, Fixture `fnz/umsatzabrechnung` | direkt |
| FNZ `depotauszug` | `test_phase_c_fnz.py`, Fixture `fnz/depotauszug` | direkt |
| Renault `kontoauszug` | `test_renault_statement_uses_external_plugin`, `test_phase_d_cash_importers.py`, `test_renault_pdf_import.py` | direkt; alt/neu und BIC-Erkennung |
| Renault `zinsmitteilung` | parametrisierter `test_non_statement_documents_are_classified_*` | direkt |
| Renault `steuerbescheinigung` | derselbe parametrisierte Test | direkt |
| Renault `freistellungsauftrag` | derselbe parametrisierte Test | direkt |
| Renault `umsatzuebersicht` | derselbe parametrisierte Test | direkt |
| Renault `archiv` | derselbe parametrisierte Test | direkt |
| Bank of Scotland `kontoauszug` | `test_phase_d_cash_importers.py`, verifizierte Textfixture | direkt; Mehrseiten-/Fehlerfälle |
| generisch `generic` | `test_pdf_bookings.py`, `test_import_document_tags.py`, generische Registrytests | indirekt bis direkt für Klassifikation/Buchungskern; eigener End-to-End-Golden fehlt |

### 5.1 Verbindliche Testlücken vor Produktfreigabe

1. comdirect `einloesung` mit vollständiger wirtschaftlicher Sollannotation.
2. comdirect `ertragsgutschrift` als eigener Detection- und Parsefall.
3. ING `dividendengutschrift`, `kauf` und `jahresdepotauszug` als handlergenaue Goldens.
4. Baader Depot**aus**lieferung zusätzlich zur Einlieferung.
5. Generischer Fallback als End-to-End-Fall für Archivdokument und Kontoauszug, jeweils mit explizitem Reviewstatus.
6. Für alle produktiv behaupteten Layoutjahre ein freigegebener, anonymisierter Referenzfall; Dateinamen oder Regex-Unit-Tests allein genügen nicht.

## 6. Wiederverwendbarer Code und unnötige Abhängigkeiten

### 6.1 Wiederverwenden

- Parsereigene Erkennungsregexe, Plausibilitäts- und Summenprüfungen.
- `_statement_bookings.py` als gemeinsamer, bankneutraler Kontoauszugskern.
- `_statement_classification.py` für konservative Dokumentklassifikation.
- `_finanzreport_help.py` und die Core-/Legacy-Trennung des Finanzreports.
- Baader-Core einschließlich strenger Bestands- und Stornoprüfungen.
- Bestehende synthetische Fixtures und unveränderte Charakterisierungserwartungen.
- Registry-Auswahlregeln: Mindestkonfidenz, deterministische Priorität und Ambiguitätsfehler.

### 6.2 Entkoppeln oder ersetzen

| Abhängigkeit | Problem | Ersatz in `portman-parsers` |
|---|---|---|
| `portfolio_v5.models` | großer V09-Datentypblock; Parser erzeugen persistenznahe Objekte | versionierte Parser-DTOs und reine Konverter |
| `portfolio_v5.pdf_plugins.__init__` | zieht Registry und Config bereits beim API-Import ein | schlankes `portman_parsers.api` ohne Seiteneffekte |
| `portfolio_v5.booking_details` | mischt Referenzextraktion, Cashklassifikation und V09-`TaxItem` | kleine reine Module `references` und `cash_classification` |
| `portfolio_v5.accounts.account_key` | Kontonormalisierung an V09-Konvention gekoppelt | parserinterne, dokumentierte Account-ID-Normalisierung |
| `portfolio_v5.importers.asset_type` | zieht CSV/XML/Office-Importer transitiv ein | kleine autonome Assetklassifikation oder neutrales `UNKNOWN` |
| `base64` in jedem Parser | Dokumentbinärdaten werden in Fachobjekte eingebettet | Quell-Blob/Hash außerhalb des Parserergebnisses verwalten; Evidence-Referenzen nutzen |
| Registry-Dateisystem-Discovery | lädt beliebige `.py`-Dateien und erschwert Negativauswahl | explizite Paket-Entry-Points/Allowlist für acht Gruppen |
| V09-Repository-/Storecode | Commit, Deduplizierung und GUI-Kontext vermischt | getrennte Consumer-/Lab-Persistenz, Parser bleibt rein |

## 7. Verbindliche Übernahmeliste

### 7.1 Unverändert übernehmen

Hier bedeutet „unverändert“: Inhalt zunächst bytegleich als Charakterisierungs- oder Spezifikationsbasis kopieren; Paketpfade dürfen erst in einem gesonderten Adaptionsschritt geändert werden.

- Relevante synthetische Textfixtures unter `tests/fixtures/importers/` für comdirect, ING, FNZ, Renault und Bank of Scotland.
- Parserbezogene Testfälle zunächst als unveränderte Charakterisierungssuite, insbesondere:
  - `tests/test_pdf_plugins.py`
  - `tests/test_pdf_bookings.py`
  - `tests/test_comdirect_pdf.py`
  - `tests/test_comdirect_mifid_cost.py`
  - `tests/test_comdirect_investment_distribution_tax.py`
  - `tests/test_phase_b_importers.py`
  - `tests/test_phase_c_baader_deka.py`
  - `tests/test_phase_c_fnz.py`
  - `tests/test_phase_d_cash_importers.py`
  - `tests/test_renault_p2_documents.py`
  - `tests/test_baader_dividend_reversal.py`
- `pdf_plugins/_finanzreport_help.py` ist fachlich rein genug für eine erste bytegleiche Übernahme; sein einzelner `parse_date`-Import wird anschließend minimal auf die neue Utility-API umgestellt.

### 7.2 Minimal anpassen

- `pdf_plugins/comdirect_ertraege.py`
- `pdf_plugins/comdirect_finanzreport.py`
- `pdf_plugins/_comdirect_finanzreport_core.py`
- `pdf_plugins/_comdirect_finanzreport_legacy.py`
- `pdf_plugins/_comdirect_depot.py`
- `pdf_plugins/baader.py`
- `pdf_plugins/_baader_core.py`
- `pdf_plugins/ing_wertpapiere.py`
- `pdf_plugins/deka_quartalsbericht.py`
- `pdf_plugins/fnz_finvesto.py`
- `pdf_plugins/renault_kontoauszug.py`
- `pdf_plugins/bank_of_scotland_kontoauszug.py`
- `pdf_plugins/generic_kontoauszug.py`
- `pdf_plugins/_generic_document.py`
- `pdf_plugins/_statement_bookings.py`
- `pdf_plugins/_statement_classification.py`

Erlaubte Minimalanpassungen: Importpfade, Konstruktion neuer DTOs, Evidence statt eingebettetem Base64, explizite Pluginmetadaten und Entfernung V09-spezifischer Persistenzfelder. Fachliche Regexe, Vorzeichen, Rundungen und Validierungsbedingungen bleiben zunächst unverändert.

### 7.3 Neu implementieren

- Öffentliche DTOs: `PdfDocument`, `PdfPage`, `Detection`, `ParsedDocument`, Event-/Snapshot-/Cost-/Tax-DTOs, `Evidence`, `Issue`.
- Versionsschema und JSON-Serialisierung ohne V09-Modelle.
- Schlanke Registry mit expliziter Allowlist und deterministischer Auswahl.
- Parserinterne Utilities für Datum, Geld, Zahl, Digest, ISIN und Korrekturwerte.
- Reine Referenzextraktion und Cashbuchungsklassifikation aus den benötigten Teilen von `booking_details.py`.
- Kleine Asset-Typklassifikation ohne allgemeinen Office-/CSV-/XML-Importer.
- PDF-Text-/OCR-Adapter und optionaler comdirect-Fastpath; keine Importzeitpflicht für OCR.
- Lab-spezifisches lokales Referenzrepository, Reviewstatus, Diff/Fingerprint und Qualitätsmetriken.
- Fehlende Goldens aus Abschnitt 5.1.
- Packaging, Entry-Points, Release- und Kompatibilitätsprüfungen für `portman-parsers`.

### 7.4 Ausschließen

- `pdf_plugins/pbb_direkt.py`
- `pdf_plugins/baader_krypto.py`
- `pdf_plugins/example_plugin.py` und TOML-Beispiel aus dem produktiven Parserpaket
- `pdf_plugins/_renault_import.py` (V09-Repository-/Commit-Orchestrierung)
- `pdf_plugins/_comdirect_fast.py` in seiner aktuellen V09-Form
- `src/portfolio_v5/pdf_importer.py`, `models.py`, `accounts.py`, `importers.py` als übernommene Module
- `src/portfolio_v5/pdf_plugins/config.py` bis ein konkreter Bedarf an TOML-Profilen beschlossen ist
- V09-Store, Repositories, Settlement-/Import-Commitlogik, GUI, Dialoge und globale Zustände
- `src/Gui/PortMan_V09.py` und sämtliche V09-Änderungen

## 8. Technische Negativabsicherung

`pbb_direkt` und `baader_krypto` dürfen nicht nur organisatorisch, sondern technisch fehlen:

1. Eine feste Allowlist enthält ausschließlich die Plugin-IDs der acht freigegebenen Gruppen.
2. Kein rekursives Laden beliebiger Python-Dateien aus `pdf_plugins/`.
3. Packaging-Test prüft, dass beide ausgeschlossenen Module weder im Wheel noch in Entry-Points vorkommen.
4. Importgraph-Test schlägt fehl, wenn ein freigegebenes Modul eines der ausgeschlossenen Module importiert.
5. Registrytest prüft, dass Texte dieser beiden Plugins keinen Kandidaten aus der Distribution liefern.

## 9. Verifikation dieser Phase

Ausgeführt wurde der unveränderte Charakterisierungssatz:

```text
tests/test_pdf_plugins.py
tests/test_phase_b_importers.py
tests/test_phase_c_baader_deka.py
tests/test_phase_c_fnz.py
tests/test_phase_d_cash_importers.py
tests/test_renault_p2_documents.py
tests/test_pdf_bookings.py
tests/test_comdirect_pdf.py
tests/test_comdirect_mifid_cost.py
tests/test_comdirect_investment_distribution_tax.py
tests/test_baader_dividend_reversal.py
```

Ergebnis mit isoliertem Test-Tempverzeichnis: **140 bestanden in 36,33 s**. Ein erster Lauf hatte bereits 116 Tests bestanden; 24 Setups waren ausschließlich wegen `PermissionError` auf `C:\Users\chris\AppData\Local\Temp\pytest-of-chris` blockiert. Nach Umleitung des pytest-Basetemp in das aktive Projekt bestanden dieselben 140 Tests vollständig.

Die grüne Suite belegt die Konsistenz des aktuellen Quellstands für die ausgewählten Charakterisierungen. Sie schließt die in Abschnitt 5.1 genannten Abdeckungslücken nicht.

## 10. Abnahmekriterien für den Start von Phase 3

Phase 3 darf mit der Paketgerüsterstellung beginnen, wenn folgende Festlegungen beibehalten werden:

- 33 Handler sind die vollständige Ausgangsmenge; neue Handler benötigen einen eigenen Fachentscheid.
- Die sechs dokumentierten Testlücken werden vor produktiver Freigabe geschlossen.
- Parser-DTOs enthalten keine V09-Store-/GUI-Typen.
- Geldwerte bleiben `Decimal`, Währung und Vorzeichenkonvention sind explizit.
- Archiv-, Steuer- und Kostenbelege erzeugen keine unbelegten Cashflows.
- `pbb_direkt` und Baader-Krypto bleiben außerhalb von Source-Distribution, Wheel, Registry und Tests der freigegebenen Gruppe.
- Die bestehenden Charakterisierungstests werden zunächst nicht fachlich umgedeutet; Abweichungen benötigen einen dokumentierten Entscheid und einen Baseline-Diff.

Damit liegt eine belastbare, datei- und handlergenaue Grundlage für die getrennte Erstellung von `portman-parsers` und `portman-pdf-lab` vor.
