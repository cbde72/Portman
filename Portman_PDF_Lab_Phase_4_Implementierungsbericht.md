# Portman PDF Lab – Phase-4-Implementierungsbericht

**Datum:** 30.10.2026  
**Pakete:** `portman-parsers 0.5.0`, `portman-pdf-lab 0.5.0`  
**API:** `0.5`  
**Schema:** `1.4.0`  
**Ausgangsstand:** Phase 3 mit 60 bestandenen Tests

## 1. Implementierte Funktionen

- Unabhängige lokale PDF-Extraktion mit SHA-256, Seitenreihenfolge und
  Seitenreferenzen.
- Kontrollierte Behandlung beschädigter und passwortgeschützter PDFs.
- `OCR_REQUIRED` für Seiten ohne nutzbare Textschicht; OCR bleibt optional.
- Erster ausführbarer End-to-End-Parser: Bank of Scotland Kontoauszug.
- Einzeldatei-CLI, rekursiver sequenzieller Batchlauf und JSON-Export.
- Strukturierte Berichte für Konten, Depots, Links, Gebühren, Issues und
  getrennte Laufzeitstufen.

## 2. Konto- und Depotmodell

`AccountType` trennt `GIRO`, `TAGESGELD`, `FESTGELD` und `OTHER`.
`AccountFunction` modelliert unabhängig `PAYMENT`, `SAVINGS`, `SETTLEMENT`,
`DIVIDEND`, `FEES` und `TAX`. Dadurch kann ein Girokonto gleichzeitig
Abrechnungskonto sein, ohne ein künstliches Verrechnungskonto anzulegen.

`DepotType.WERTPAPIER` bleibt vom Geldkonto getrennt. `DepotAccountLink`
enthält Rolle, `valid_from`, `valid_until`, `is_default` sowie die vorhandene
Feldprovenienz. Unterstützt und getestet sind separate Abrechnungskonten,
Girokonten als Settlementkonto, ein Girokonto für zwei Depots, mehrere Konten
je Depot, zeitlicher Kontowechsel sowie fehlende/widersprüchliche Zuordnung.

## 3. Bank-of-Scotland-Parser

Plugin-ID und Handler bleiben kompatibel:
`user.bank-of-scotland-kontoauszug/kontoauszug`, Pluginversion `1.0`.
Die Registry markiert ausschließlich diesen einen der 33 Handler als
implementiert. Die übrigen 32 Handler bleiben `NOT_IMPLEMENTED`.

Extrahiert werden Bank, Kontoart, Kontonummer, IBAN, BIC, Inhaber, Währung,
Auszugsnummer/-datum, Buchungs-/Wertstellungsdatum, Text, Betrag, Vorzeichen,
Zinsen, Steuerkomponenten, Gebühren/Erstattungen sowie Anfangs-/Endsaldo.
Bank of Scotland erzeugt kein Depot.

## 4. Unterstützte Layouts

- Tagesgeld: freigegebene synthetische Charakterisierung des vorhandenen
  Soll/Haben-Tabellenlayouts, ein- und mehrseitig.
- Festgeld: gleiches Tabellenlayout bei explizitem `Festgeld`-Marker,
  synthetisch geprüft.
- Unbekannte Layouts werden nicht erkannt; Tabellenzeilen ohne Tabellenkopf
  werden kontrolliert abgelehnt.

Es liegen weiterhin keine anonymisierten, ausdrücklich freigegebenen realen
Bank-of-Scotland-PDFs im neuen Projekt vor. Eine produktive Layoutfreigabe und
weitere historische Layoutvarianten sind deshalb fachlich ausstehend.

## 5. Gebühren und Steuern

Steuerzeilen werden als eigene `TaxEvent`s mit tatsächlicher Cashbewegung
modelliert. Kapitalertragsteuer, Solidaritätszuschlag und Kirchensteuer sind
unterscheidbar. Bankentgelte erzeugen `FeeEvent.ACTUAL_BOOKED`, ausdrücklich
erkannte Erstattungen `FeeEvent.REFUND`. Evidence und Konto-/Transaktionsbezug
bleiben erhalten. Informatorische oder geschätzte Kosten erzeugen weiterhin
keinen Cashflow.

## 6. Vorabpauschale und steuerliche Ereignisse

`TaxEvent` ist ein eigenständiges steuerliches Ereignis. Es hält die aus dem
PDF übernommenen Werte unverändert und unterscheidet Bemessungsgrundlage,
Vorabpauschale vor Teilfreistellung, steuerpflichtigen Betrag, ausgewiesene
Steuerschuld und tatsächlich einbehaltene Steuer. Depot, ISIN, Steuerjahr,
steuerliches Zuflussdatum, Bank, Konto und Evidence sind separat referenzierbar;
Buchungs- und Wertstellungsdatum bleiben vom Zuflussdatum getrennt.

`TaxRuleSet` und `StatutoryBaseRate` bilden jahres- und optional bankspezifische
Regeln mit Quellenreferenz ab. Die separate `AdvanceTaxCalculation` prüft
Basisertrag, Wertsteigerungsbegrenzung, Ausschüttungen, monatsgenaue Kürzung bei
Erwerb im laufenden Jahr und Teilfreistellung. Freistellungsauftrag und
Verlustverrechnung sind getrennte Eingaben. Unbekannte Angaben bleiben
`MissingValue`; insbesondere werden weder Nullwerte noch ein Kirchensteuersatz
unterstellt. Kapitalertragsteuer, Solidaritätszuschlag und gegebenenfalls
Kirchensteuer werden als getrennte Komponenten geführt.

Die Prüfrechnung überschreibt keine PDF-Werte. Differenzen werden typisiert in
`AdvanceTaxCalculation.differences` gespeichert. Eine Berechnung erhält nur mit
bestätigtem Dokumentbezug und Quellenregel die entsprechende Freigabe;
synthetische oder unbelegte Berechnungen bleiben `SYNTHETIC_ONLY` beziehungsweise
`NOT_APPROVED`.

Eine Vorabpauschale erzeugt niemals selbst eine Geldbewegung. Nur eine bereits
belegte tatsächliche Steuerbelastung darf über ihre ID mit einem vorhandenen
`CashMovement` des tatsächlichen Giro- oder Verrechnungskontos verknüpft werden.
Konto, Betrag, Status und Buchungsart werden dabei validiert; ein separates
Verrechnungskonto wird nicht vorausgesetzt. Die Deduplizierung über
Bank/Depot/ISIN/Steuerjahr verhindert eine zweite Steuerwirkung aus
Steuermitteilung, Wertpapierbeleg und Kontoauszug.

`AdvanceTaxCarryforward` führt die bereits berücksichtigte Vorabpauschale für
eine spätere Fondsveräußerung nachvollziehbar fort. Sie ist weder Anschaffung
noch Wertpapierbewegung und erzeugt keinen Cashflow.

Die Handler `vorabpauschale` für comdirect, Baader und ING bleiben reine
Registry-Metadaten und `NOT_IMPLEMENTED`. Bank of Scotland bleibt der einzige
aktive Phase-4-Parser; seine bestehende Parserfunktion wurde nicht um einen
Vorabpauschalen-Handler erweitert.

## 7. Geldfluss- und Saldenvalidierung

Cashbewegungen verwenden die Phase-3-Vorzeichenkonvention. Der Parser prüft:

```text
Endsaldo = Anfangssaldo + Summe der Cashbewegungen
```

Bei Abweichung entsteht `BALANCE_MISMATCH` mit Differenz; es wird keine
Korrekturbuchung erzeugt. IDs sind dokument- und inhaltsstabil, sodass ein
Wiederholungsimport identische Ergebnisse liefert.

Interne Transfers können zwei verknüpfte Seiten besitzen. Bei nur einer
belegten Seite wird keine Gegenseite erfunden. `deduplicate_cash_movements`
bevorzugt eine tatsächliche Kontobuchung gegenüber einem erwarteten Settlement
mit derselben Identität und verhindert doppelte Geldwirkung.

## 8. Depot-Konto-Zuordnung

`resolve_depot_account` berücksichtigt Rolle, Gültigkeitszeitraum, explizite
Transaktionszuordnung und Defaultregel. Die Defaultregel ist nur Vorauswahl.
Bei Mehrdeutigkeit, fehlender oder widersprüchlicher Zuordnung bleibt das Konto
offen und ein typisiertes Issue wird erzeugt.

## 9. Evidence-Qualität

Bank-of-Scotland-Evidence enthält Dokument-ID, SHA-256, Seite, Feld,
Textfundstelle, Parser-ID, Handler, Parserversion und Reviewstatus. PDF-Felder
referenzieren zwingend existierende Evidence derselben Seite. Mathematische
Konsistenz wird nicht als externe Ground-Truth-Bestätigung ausgegeben.

## 10. Tests

Gesamtergebnis: **102 Tests bestanden** (`portman-parsers`: 90,
`portman-pdf-lab`: 12).

Neu abgedeckt sind Tages-/Festgeld, Zinsen, Steuern, Gebühren, Mehrseitenbeleg,
Saldenabgleich/-abweichung, fehlende Kontodaten, unbekanntes Layout,
deterministischer Reimport, Text-PDF, OCR-Pflicht, beschädigte/verschlüsselte
PDFs, Kontoarten/-funktionen, alle geforderten Depot-Konto-Fälle, interne
Transfers, Settlement-Deduplizierung, PDF-CLI, JSON-Export und resilienter Batch.

Zusätzlich sind synthetisch geprüft: mehrere Teilfreistellungen,
Freistellungsauftrag, Verlustverrechnung, Erwerb im laufenden Jahr,
Ausschüttungen, Wertsteigerungsbegrenzung, fehlende Eingaben,
Vorabpauschale ohne Steuerbelastung, belegte Steuerzahlung über ein konkretes
Konto, abweichende Roh- und Rechenwerte, Bank-/Jahresregelwerke,
Steuerdubletten sowie die cash- und bestandsneutrale Fortschreibung.

## 11. Performance

Gemessen in der isolierten Python-3.14-Umgebung, inklusive realer pypdf-Lektüre:

| Stufe | synthetisches 1-Seiten-PDF |
|---|---:|
| Extraktion | 13,704 ms |
| Erkennung | 0,345 ms |
| Parsing | 13,311 ms |
| Validierung | 0,060 ms |
| Bericht | 1,191 ms |
| Gesamt | 35,211 ms |

Separater Extraktionsvergleich: 1 Seite/1.331 Byte **3,151 ms**;
10 Seiten/2.813 Byte **31,849 ms**. Einzelmessungen sind reproduzierbare
synthetische Orientierungswerte, keine Produktionsbenchmarks.

## 12. Abhängigkeiten

Neue Laufzeitabhängigkeit: `pypdf>=6,<7`. Begründung: schlanke Pure-Python-
Bibliothek für Seitenzugriff, Textschicht, Verschlüsselungs- und Fehlererkennung.
OCR-, GUI-, Datenbank- oder Webframeworks wurden nicht hinzugefügt.

## 13. Isolationstest

Beide Wheels wurden gebaut und außerhalb des Repositorys unter
`C:\Users\chris\Desktop\PortmanPDFLabPhase4Isolation` in eine frische venv
installiert. `PYTHONPATH` war leer. Dort wurden ein synthetisches PDF erzeugt,
vollständig analysiert und `report.json` geschrieben.

Ergebnis: Plugin `user.bank-of-scotland-kontoauszug`, vier Ereignisse, keine
geladenen Module mit Präfix `portfolio_v5`, `portman` oder `pdf_plugins`.
CLI, Parser, PDF-Lesen und JSON-Export funktionierten ohne V09-Dateizugriff.

## 14. Offene Probleme

- Reale, anonymisierte und freigegebene Referenz-PDFs fehlen weiterhin.
- Festgeld ist nur für das belegte gemeinsame Tabellenmuster synthetisch
  charakterisiert; produktionstaugliche Layoutfreigabe steht aus.
- Zinssatz und Zinsperiode werden nur dann künftig strukturiert, wenn eindeutige
  reale Druckmuster freigegeben sind; aktuell wird nichts geschätzt.
- OCR-Engine, periodenübergreifende Batch-Deduplizierung und dauerhafte
  Review-Persistenz bleiben spätere Aufgaben.

## 15. Empfehlung Phase 5

1. Freigegebene reale Bank-of-Scotland-Goldens annotieren und Layoutvertrag
   härten.
2. FNZ/Finvesto als nächsten klar abgegrenzten Parser migrieren.
3. Batchübergreifende Dokument-/Buchungsidentität und Review-Repository bauen.
4. Erst danach OCR-Adapter und weitere Banken parallelisieren.

## 16. V09-Unverändertheit

`pdf_plugins/bank_of_scotland_kontoauszug.py` wurde ausschließlich gelesen und
nicht verändert. Ebenso unverändert blieben `src/portfolio_v5`,
`src/Gui/PortMan_V09.py`, sämtliche vorhandenen `pdf_plugins`, V09-Tests,
Datenbanken, Benutzerdateien und Portman V10. Alle Phase-4-Änderungen liegen in
den neuen Projekten sowie neuen Dokumentationsdateien. Es wurden keine Commits,
Pushes oder Merges ausgeführt.
