# Parserauftrag – Bearbeitungsstand

Abgleich mit `PortmanV10/portman-v10/docs/Parserauftrag.md` vom 9. November 2026.
Die Parserimplementierung liegt in `PortmanParserLab`; V10-Pin, Allowlist,
Importregeln und Weboberfläche sind nicht geändert.

## Abhakliste

- [x] **Arbeitsphase A – Bestandsmatrix:** 42 Registry-Handler mit Status,
  synthetisch belegten Varianten, DTO-/Feldbefund, Evidenz, Testabdeckung,
  Lücken und Confidence-Grenzen. Ausführbarkeit wird nicht als Formatfreigabe
  behandelt.
- [x] **V10-31-Auswahl:** Baader `wertpapierabrechnung` bleibt die ausgewählte
  Variante als Zweitbeleg zu einem existierenden Kauf/Verkauf. Parserhandler und
  synthetische Kauf-/Verkaufsfälle sind vorhanden. Das erweitert weder V10s
  Allowlist noch die Buchungswirkung.
- [x] **V10-40-Vertrag:** Gerichteter `ExchangeRate`-Wert mit exakter Decimal-
  Präzision, getrennten Währungen, fester Richtung und Evidence. Bank of
  Scotland liest ausdrücklich gelabelte Zeilen; der comdirect-Wertpapierhandler
  liefert zusätzlich genau einen klar gerichteten `1 Währung = Kurs Währung`
  Wert. Der bisherige ungerichtete Trade-Kurs bleibt davon getrennt.
- [x] **V10-52-Vertrag:** Gegenpartei und Zweck sind getrennte Rohtextfelder mit
  eigenen Evidence-IDs. Die bestehende Extraktion bleibt auf explizite Labels in
  derselben Bank-of-Scotland-Buchungszeile beschränkt.
- [x] **V10-24 / Abschnitt 4.4:** `TaxEvent` führt getrennte Evidence-IDs für
  Steuerjahr, steuerliches Zuflussdatum und ausdrücklich verbrauchten
  Freistellungsauftrag. Das Jahr stammt nur aus einem expliziten Steuerjahr oder
  dem belegten Zuflussdatum. Ein generischer Freistellungsauftragbetrag wird
  nicht als Verbrauch ausgegeben. Schema `1.7.0` wird mit leeren Zusatzfeldern
  auf `1.8.0` normalisiert.
- [x] **V10-74 / Abschnitt 4.5:** Ein ausdrücklich betiteltes
  Dividenden-/Ertragsstorno wird als `REVERSAL` ausgegeben. `ReversalDetails`
  trennt Originalreferenz, Ex-Tag, Zahltag, Geschäftstag, Valuta, Buchungstag
  und Stückzahl mit eigener Evidence vom Stornobeleg und dessen Referenz.
  Stornobetrag und Steuerkorrekturen bleiben getrennt; fehlende Originalangaben
  bleiben unbekannt. Normale Dividendengutschriften bleiben unverändert.
- [x] **V10-76 / Abschnitt 4.6:** Ein Datum in der comdirect-Verrechnungszeile
  wird nur bei eindeutiger Spaltenüberschrift `Valuta` oder `Buchungstag`
  übernommen. `FinancialEvent` behält Datumsart und Evidence; bei Wertpapier-
  geschäften wird ein Buchungstag separat vom Valutadatum ausgegeben. Unbeschriftete
  Datumswerte bleiben unbekannt. Synthetische Regressionen decken Einlösung,
  Kauf, Verkauf, Dividende und fehlende Datumsbedeutung ab.
- [x] **§5.1-Variantenbefund:** ING, Baader, Deka und FNZ sind anhand der
  vorhandenen positiven synthetischen Fälle sowie fachlichen Negativ-/Unbekannt-
  fällen einzeln dokumentiert. Zusätzliche Layouts bleiben ohne konkrete
  Einzelauswahl offen; fehlende negative Layout-Erkennung ist ausdrücklich
  benannt.
- [x] **V10-81 Finanzreport:** Betrag am Ende einer Zweckzeile schließt die
  richtige Buchung; ein neues Datumspaar trennt einen unvollständigen Block mit
  `INCOMPLETE_BOOKING` und eigener Fundstelle. Historische Parserpfade trennen
  ebenfalls; `BALANCE_MISMATCH` wird nicht korrigiert.
- [x] **V10-83 Finanzreport:** Name/WKN/gültige ISIN und eng formatierte
  Buchungsreferenzen werden mit Feldfundstellen ausgegeben. Fehlende/ungültige
  ISIN, ungültige/mehrdeutige Referenzen, Gehaltszeilen und JSON-Roundtrip sind
  synthetisch geprüft. Die Zeile bleibt eine Geldbuchung ohne Stückbewegung.
- [x] **V10-82 Parseranteil:** Unvollständige Buchungs- und Saldenmeldungen
  behalten eine Quellfundstelle; Buchungswarnungen bleiben ereignisbezogen,
  Kontosaldenmeldungen außerhalb einzelner Events. `Issue` hat kein eigenes
  `account_id`; eine solche Zuordnung wird nicht erfunden.
- [x] **V10-85 Parseranteil:** Depot-Snapshots liefern feldbezogene Fundstellen
  für Wertpapierkennung, Name, Stückzahl, Kurswert, Währung und erkannte
  Verwahrart. Ein USD-Stückkurs macht den Kurs UNKNOWN, verhindert aber nicht
  den belegten Bestand. Verwahrart ist ein neues optionales DTO-Feld.
- [x] **API-/Schema-Versionierung:** Paket/API `0.8.7` / `0.9`, Ergebnis-
  schema `1.9.0`; ältere Ergebnis-Schemata `1.5.0` bis `1.8.0` werden
  rückwärts normalisiert.
- [ ] **V10-Integration:** Parserpin, V10-Allowlist, Importregeln und Web-UI
  sind nicht geändert und bleiben separate V10-Arbeiten.

## Prüfung und Wheel

Prüfstand am 9. November 2026:

- Parsersuite: `337 passed`.
- Ruff: `python -m ruff check src tests` – sauber.
- `git diff --check` – sauber.
- Wheel gebaut: `portman_parsers-0.8.7-py3-none-any.whl`.
- Wheel in getrenntes Zielverzeichnis installiert; Import dort bestätigt
  Paket `0.8.7`, API `0.9`, Schema `1.9.0` und `DepotPosition.custody_type`.
- SHA-256: `19b62297cbee5678cc803c945b69a232d1e90553566248b0ffe5cc43c7fe5698`.

## Übergabegrenze

Keine echten Belege wurden hinzugefügt. Die synthetischen Ergebnisse belegen nur
die ausdrücklich genannten Textmuster, nicht alle comdirect-Layoutvarianten.
V10s dokumentierter Parserpin `0.7.0` / API `0.6` / Schema `1.6.0` muss separat
mit Paket `0.8.7` / API `0.9` / Schema `1.9.0` abgeglichen werden.
Die V10-Integration ist daher ausdrücklich kein abgeschlossener ParserLab-Schritt.
