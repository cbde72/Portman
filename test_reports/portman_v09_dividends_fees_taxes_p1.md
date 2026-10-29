# Portman V09 – P1 Dividenden, Gebühren und Steuern

Stand: 29.10.2026  
Branch: `codex/p1-dividends-fees-taxes`  
Basis: `origin/main` / `08f29cc`

## Offene oder fehlerhafte Funktionen (Bestandsprüfung vor der Korrektur)

| Bereich | Status vor Prüfung | Nachweis / Codefundstelle | Ergebnis dieser Aufgabe |
|---|---|---|---|
| comdirect Bruttoabrechnung plus Netto-Finanzreport | **fehlerhaft** | `portfolio_v5.settlement.consolidate_dividends()` (`src/portfolio_v5/settlement.py:231`) gruppierte nur gleiche Beträge und Stichtage. Vier reale besteuerte Ausschüttungen blieben deshalb doppelt. | Eindeutiger Abgleich über Konto, Währung, ISIN/WKN, Brutto-/Nettobetrag und höchstens drei Tage; Finanzreport bleibt Primärbuchung. |
| Steuerbeleg zu Bruttogutschrift ohne Depotfeld | **fehlerhaft** | `portman.tax_matching.match_tax_events()` (`src/portman/tax_matching.py:63`) verglich das Cashkonto fälschlich direkt mit dem Depot. | Kontonamen und Kontoschlüssel werden kanonisiert; ein dokumentiertes Cashkonto darf den fehlenden Depotschlüssel ersetzen. |
| Belegte Steuer bei Bruttogutschrift ohne späteren Finanzreport | **fehlerhaft** | `portfolio_v5.settlement.performance_transactions()` (`src/portfolio_v5/settlement.py:375`) verwarf jede cash-neutrale Steuerhilfszeile. | Nur bei genau einer referenzgleichen Bruttogutschrift bleibt die belegte Steuer in der wirtschaftlichen Sicht erhalten; bei vorhandener Nettozeile bleibt sie ausgeschlossen. |
| Historische Kaufgebühren ohne Ausführungsbeleg | **teilweise umgesetzt / Datenlücke** | `portman.fee_analysis.fee_rows()` (`src/portman/fee_analysis.py:44`) kennzeichnet 519 produktive Käufe korrekt als `unbekannt`. | Keine Schätzung und keine Codeänderung. Für eine Vervollständigung fehlen historische Originalabrechnungen. |
| Nachträgliche Depotgebührenerstattungen | **fehlend für die vorhandenen Belegfamilien** | Das Modell kennt `FEE`, aber keinen belegten produktiven Erstattungsfall; `Transaction`/Validierung in `src/portfolio_v5/models.py:564` und `:883`. | Mangels Echtdaten nicht implementiert. Positive Beträge werden nicht spekulativ als Gebührenerstattung klassifiziert. |
| Historische Verlusttopfsalden außerhalb vorhandener Bankdaten | **teilweise umgesetzt / Datenlücke** | `TaxEvent` besitzt Verlusttopffelder (`src/portfolio_v5/models.py:281`); die Jahresansicht zeigt nur dokumentierte Salden. | Keine Rückrechnung aus FIFO oder Performance, da dies steuerlich nicht beweissicher wäre. |

## Funktionsklassifikation

| Fachfunktion | Status nach Prüfung | Nachweis |
|---|---|---|
| Brutto-/Nettodividenden und Ausschüttungen | **abgeschlossen** | Strukturierte Felder und Plausibilisierung in `BankTransaction`/`transaction_validation`; wirtschaftliche Sicht in `settlement.py:231` und `:375`. |
| Wiederanlagen | **abgeschlossen** | Deka/FNZ trennen Ausschüttung und Kauf; Regressionen `tests/test_phase_c_baader_deka.py:95`, `tests/test_phase_c_fnz.py:35`. |
| Dividendenstornos | **abgeschlossen für belegte Parserfamilien** | Baader-Storno hebt die Originalbuchung exakt auf: `tests/test_baader_dividend_reversal.py:32`. |
| Dividenden-/Steuererstattungen | **abgeschlossen für belegte Parserfamilien** | `TAX_REFUND` mit positiver Richtung und Komponentenvalidierung; ING-/Renault-Regressionen. |
| Inländische und ausländische Quellensteuer | **abgeschlossen** | Einzelkomponenten, Land und Satz im Transaktionsmodell; konservative Aggregation in `tax_overview.py:56`. |
| Wertpapier-, Depot- und Cashkontozuordnung | **abgeschlossen** | Eindeutige Depot-/Cash-Verknüpfung und ISIN/WKN-Brücke; unklare Treffer bleiben offen. |
| PDF-Steuerbeleg versus Cashbuchung | **abgeschlossen nach Korrektur** | `tax_matching.py:63`, `repository_v09.py:217`, neue Regressionen und 126-PDF-Akzeptanz. |
| Kauf-/Verkaufsprovisionen und Handels-/Abwicklungsgebühren | **abgeschlossen, soweit belegt** | Nicht-cashwirksame Belege werden über `repository_v09.py:124` genau einer Cashbuchung angereichert. |
| Depotgebühren | **abgeschlossen für vorhandene Belastungen** | Wertpapierbezogene Verwahrentgelte werden als `FEE` zugeordnet; Performance zählt den Betrag einmal. |
| Gebühren in Einstand, Verkaufsergebnis und Performance | **abgeschlossen** | Nettozahlung bleibt führend; Gebührennebenfeld wird nicht erneut addiert. FIFO: `analysis_v09.py:216`; Doppellink-Test `tests/test_settlement.py:219`. |
| Kapitalertragsteuer, Soli, Kirchensteuer | **abgeschlossen** | Getrennte Komponenten und belegte Nullwerte; Jahresaggregation in `tax_overview.py:56`. |
| Verlustverrechnung und Teilfreistellung | **teilweise umgesetzt** | Teilfreistellung ist vollständig; Verlusttöpfe nur bei bankseitigem Nachweis, bewusst ohne Schätzung. |
| Automatische FSA-Berechnung ohne CSV | **abgeschlossen** | `calculate_fsa()` (`tax_overview.py:32`), Regression `tests/test_tax_annual_summary.py:158`. |
| Vorabpauschale und Verkaufsanrechnung | **abgeschlossen** | FIFO-Anrechnung und zeitliche Verbrauchslogik, u. a. `tests/test_v09.py:599`. |
| Steuererstattungen, Stornos, historische Sonderfälle | **abgeschlossen für belegte Daten** | Separate Richtungs-/Komponentenprüfung sowie Vor-2018- und Vorabpauschalenfälle. |
| SQLite-Persistenz und Dublettenschutz | **abgeschlossen** | Rohdaten bleiben unverändert; `booking_details`, `fee_links`, Tax-Events und Quelldokumente sind getrennt und idempotent. |
| Depotübersicht und Performance | **abgeschlossen nach Korrektur** | Nur wirtschaftliche Flows; cash-neutrale Belege werden nur dann berücksichtigt, wenn sie einen sonst fehlenden belegten Steuerabfluss darstellen. |

## Nachgewiesene Fehler und Korrekturen

Die realen comdirect-Daten enthalten für vier besteuerte Ausschüttungen sowohl
eine Brutto-Ertragsabrechnung als auch eine Nettozeile im Finanzreport. Die
alte Konsolidierung verlangte denselben Betrag und behandelte diese Belege
daher als zwei Erträge. Zusätzlich konnte ein Steuerereignis eine
Bruttogutschrift ohne bereits gesetztes `performance_depot_key` nicht über das
dokumentierte Cashkonto erkennen.

Die Korrektur arbeitet ausschließlich in der abgeleiteten wirtschaftlichen
Sicht. Rohtransaktionen, Original-PDFs, Salden und gespeicherte Referenzen
werden nicht geändert. Eine Zusammenführung erfolgt nur bei genau einem
beiderseits eindeutigen Treffer. Bereits geschützte Finanzreportzeilen behalten
ihre Referenz und bestehende Steuerlinks.

Für den Oktoberfall ohne späteren Finanzreport belegen die PDFs 20,25 EUR
Brutto und 3,74 EUR Steuer. Die Performance berücksichtigt daher 16,51 EUR
netto. Sobald eine Netto-Finanzreportzeile vorhanden ist, wird dieselbe
Steuerhilfszeile weiterhin ausgeschlossen.

## Wirtschaftliche Vorher-/Nachherwerte

| Kennzahl (temporärer vollständiger Neuimport 2026) | Vorher | Nachher |
|---|---:|---:|
| Steuerlicher Ertrag | 940,77 EUR | 523,07 EUR |
| Verbrauchter FSA | 411,00 EUR | 411,00 EUR |
| Bemessungsgrundlage nach FSA | 529,77 EUR | 112,07 EUR |
| Kapitalertragsteuer | 28,02 EUR | 28,02 EUR |
| Solidaritätszuschlag | 1,51 EUR | 1,51 EUR |
| Kirchensteuer | 0,00 EUR | 0,00 EUR |
| Effektive Transaktionen | 373 | 369 |
| Rohtransaktionen in SQLite | 389 | 389 |
| Wirtschaftliche Oktober-Ausschüttung | 20,25 EUR brutto ohne Steuerabfluss | 16,51 EUR netto (20,25 − 3,74) |
| `booking_details` / Steuerlinks | 37 / 4 | 37 / 4 |
| Käufe / Gebühren / FIFO-Daten | unverändert | unverändert |

Die Reduktion um vier effektive Zeilen entfernt ausschließlich die vier
doppelten Bruttoabrechnungen. Es werden weder Käufe noch Gebührenbelege oder
FIFO-Tranchen entfernt. Kauf-Cashflow 2026 bleibt −1.607,38 EUR und separate
Depotgebühren bleiben −6,35 EUR.

## Produktive Read-only-Prüfung

`data/v09/portfolio.sqlite` wurde ausschließlich mit SQLite-URI `mode=ro`
geöffnet. Repository-Auswertungen liefen auf einer SQLite-Backup-Kopie unter
`.tmp`; die produktive Datei und Original-PDFs blieben unverändert.

- `PRAGMA integrity_check`: `ok`
- 680 Imports, 8.170 Rohtransaktionen, 89 Steuerereignisse
- 2026: 523,07 EUR steuerpflichtiger Ertrag, 411,00 EUR FSA,
  112,07 EUR BMG nach FSA, 29,53 EUR Steuern einschließlich 1,51 EUR Soli
- alle produktiven BUY-/DIVIDEND-/FEE-/TAX-Zeilen besitzen eine eindeutige
  wirtschaftliche Depotzuordnung
- fünf Steuerhilfsbuchungen sind cash-neutral
- 519 historische Käufe bleiben wegen fehlender Gebührenbelege ausdrücklich
  `unbekannt` und werden nicht als 0,00 EUR behandelt

## Echtdaten- und Regressionstests

- 126 unveränderte comdirect-PDFs, 117 eindeutige Batches
- beide Importreihenfolgen: Finanzreports zuerst und Belege zuerst
- je Lauf 38 `booking_evidence`, 37 `booking_details`, vier Steuerlinks,
  keine doppelten `(account, external_id)` und `foreign_key_check` ohne Befund
- Wiederimport bleibt idempotent
- Echtdaten-Akzeptanz: **2 bestanden**
- gezielte Dividenden-/Steuer-/Performance-Suite: **70 bestanden**
- Settlement-Suite einschließlich Brutto/Netto-Randfall: **33 bestanden**
- vollständige Pytest-Suite: **1.264 bestanden, 19 übersprungen, 0 Fehler**
  in 463,89 Sekunden

## Verbleibende offene Punkte

1. Historische Kaufgebühren können ohne Originalabrechnung nicht fachlich
   ergänzt werden. Portman zeigt sie korrekt als unbekannt.
2. Nachträgliche Depotgebührenerstattungen sind in den vorhandenen Daten nicht
   belegt. Eine automatische Klassifikation ohne Referenzbeleg wäre unsicher.
3. Verlustverrechnungstöpfe bleiben außerhalb vorhandener Bankdaten unbekannt;
   eine Rekonstruktion aus Portfolio-FIFO wäre nicht gleichbedeutend mit dem
   steuerlichen Banktopf.

