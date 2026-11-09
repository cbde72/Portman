# Parserauftrag – Bearbeitungsstand

Abgleich mit `PortmanV10/portman-v10/docs/Parserauftrag.md` vom 9. November 2026.
Alle Änderungen dieser Bearbeitung liegen im Repository `PortmanParserLab`;
das V10-Repository wurde nicht geändert.

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
  Präzision, getrennten Währungen, fester Richtung und Evidence. Ausführung
  bleibt auf ausdrücklich belegte Bank-of-Scotland-Zeilen begrenzt.
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
- [x] **API-/Schema-Versionierung:** Paket `0.8.6`, API `0.8`, Ergebnis-
  schema `1.8.0`; ältere Ergebnis-Schemata `1.5.0`, `1.6.0` und `1.7.0`
  werden rückwärts normalisiert.
- [ ] **V10-Integration:** Parserpin, V10-Allowlist, Importregeln und Web-UI
  sind nicht geändert und bleiben separate V10-Arbeiten.

## Prüfung und Wheel

Prüfstand am 9. November 2026:

- Parsersuite: `321 passed`.
- Ruff: `python -m ruff check src tests` – sauber.
- `git diff --check` – sauber.
- Wheel gebaut: `portman_parsers-0.8.6-py3-none-any.whl`.
- Frische Installation in ein separates Zielverzeichnis erfolgreich; Import
  bestätigt Paket `0.8.6`, API `0.8`, Schema `1.8.0` und neues TaxEvent-Feld.
- SHA-256: `887359F34388207439548C108DFDE307852E39C1B9CA16D94E64EBD827B93596`.

## Übergabegrenze

Keine echten Belege wurden hinzugefügt. Die synthetischen Ergebnisse belegen nur
die ausdrücklich genannten Textmuster, nicht alle comdirect-Layoutvarianten.
V10s dokumentierter Parserpin `0.7.0` / API `0.6` / Schema `1.6.0` muss separat
mit Paket `0.8.6` / API `0.8` / Schema `1.8.0` abgeglichen werden.
Die V10-Integration ist daher ausdrücklich kein abgeschlossener ParserLab-Schritt.
