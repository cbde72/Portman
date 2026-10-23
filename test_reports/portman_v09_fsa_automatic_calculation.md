# Portman V09 – Automatische FSA-Berechnung ohne CSV-Import

Stand: 23.10.2026  
Branch: `fix/automatic-fsa-from-tax-events`  
Bewertung: **PASS MIT HINWEISEN**

## Ergebnis

Portman berechnet den institutsweit gemeinsamen Freistellungsauftrag nun aus der bereits gespeicherten steuerpflichtigen Ertragsbasis. Ein Import der comdirect-Steuerdetail-CSV ist nicht erforderlich.

| Kennzahl comdirect 2026 | Vorher | Nachher ohne Steuerdetail-CSV |
|---|---:|---:|
| Steuerpflichtige Erträge | 523,07 EUR | 523,07 EUR |
| Hinterlegter FSA | 411,00 EUR | 411,00 EUR |
| Verbrauchter FSA | 200,80 EUR (nur direkt belegte PDF-Felder) | 411,00 EUR (Portman-Berechnung) |
| Verbleibender FSA | 210,20 EUR | 0,00 EUR |
| BMG nach FSA | 0,00 EUR/unvollständig | 112,07 EUR |

Die 523,07 EUR bestehen aus 314,33 EUR Investment-Ausschüttungen, 192,24 EUR Vorabpauschalen, 8,56 EUR inländischen Dividenden und 7,94 EUR Habenzinsen. Die Beträge sind im vorhandenen Portman-Datenbestand enthalten und werden ohne Referenz-CSV ermittelt.

## Ursache und Korrektur

Die bisherige Übersicht bevorzugte den in einzelnen PDF-Ereignissen ausdrücklich genannten FSA-Verbrauch (200,80 EUR). Erträge ohne separates `used_exemption`-Feld erhöhten den Verbrauch daher nicht. Zusätzlich zog eine ältere Ersatzformel die Teilfreistellung erneut von `capital_income` ab, obwohl `taxable_income` und damit `capital_income` bereits die Bemessungsgrundlage nach Teilfreistellung enthalten.

Die neue zentrale Funktion `calculate_fsa()` berechnet:

1. steuerpflichtige Erträge auf der bereits nach Teilfreistellung gespeicherten Basis,
2. abzüglich belegter vorrangiger Verlustverrechnung,
3. FSA-Verbrauch als Minimum aus verfügbarem FSA und anrechenbarem Ertrag,
4. Rest-FSA und BMG nach FSA ohne erneuten Teilfreistellungsabzug.

Die Berechnung erfolgt einmal je Institut und Jahr. Bei mehreren Konten wird kein gemeinsamer Restbetrag auf Kontoebene vervielfacht. Bankseitig belegter, manuell erfasster und von Portman berechneter Verbrauch bleiben unterscheidbar.

## Datenquellen und Status

- `institution_tax_years`: verbindlicher FSA je Institut/Jahr
- `tax_events`: steuerpflichtige PDF-Bemessungsgrundlagen, Teilfreistellung, belegte Verlustverrechnung und Steuern
- Finanzreport-Transaktionen: eindeutig erkannte Dividenden und Habenzinsen
- vorhandene Steuer-/Dividendenverknüpfungen: Ausschluss doppelter wirtschaftlicher Erfassung
- Steuerdetail-CSV: weiterhin optionale Bankreferenz, nicht Voraussetzung der Berechnung

Die Jahresübersicht zeigt zusätzlich steuerpflichtige Erträge, FSA, Verbrauch, Rest, BMG nach FSA und den Berechnungsstatus. Die bestehenden elf Vergleichskennzahlen bleiben erhalten. Die allgemeine Steuerübersicht zeigt nun ebenfalls BMG nach FSA und FSA-Status.

## SQL- und Integritätsnachweis

Die produktive Datenbank wurde ausschließlich über `mode=ro` und `PRAGMA query_only=ON` gelesen. Die Programmlogik wurde nur auf einer durch die SQLite-Backup-API erzeugten temporären Kopie ausgeführt.

```sql
PRAGMA query_only=ON;
PRAGMA integrity_check;

SELECT institution, year, exemption, used_exemption
FROM institution_tax_years
WHERE institution_key = 'comdirect' AND year = 2026;
-- Comdirect | 2026 | 411.00 | ''

SELECT kind, COUNT(*)
FROM import_model_records
GROUP BY kind;
-- tax_events | 24

SELECT COUNT(*) FROM transactions;
-- 367
```

Vor und nach der Berechnung blieben 367 Transaktionen und 24 Steuerereignisse bestehen. Es werden keine Buchungen, Steuerwerte, Cashflows, Bestände, Einstandskosten oder Performancedaten geschrieben oder verändert.

## Fachliche Grenzen

Bei mehreren Ausschüttungs-Steuermitteilungen ist `loss_offset` im Originalbeleg nicht ausdrücklich befüllt. Portman berechnet deshalb zwar den fachlich plausiblen FSA-Verbrauch von 411,00 EUR aus der vollständigen steuerpflichtigen Basis, kennzeichnet ihn aber als **„berechnet; Steuer-/Verlustdaten nicht vollständig nachgewiesen“**. Der Wert wird nicht als bankseitig bestätigt ausgegeben. Belegte Nullwerte bleiben von unbekannten Werten unterscheidbar.

Die PASS-Bewertung ohne Vorbehalt wäre erst möglich, wenn die vorrangige Verlustverrechnung für alle Ereignisse bankseitig vollständig belegt ist. Daher lautet die Gesamtbewertung **PASS MIT HINWEISEN**.

## Tests

- Zieltests Steuerübersicht, Jahresübersicht, comdirect-Steuer-PDFs und Steuerdetailabgleich: **53 bestanden**
- Vollständige Pytest-Suite: **1120 bestanden, 12 übersprungen** in 465,61 s
- Geprüft wurden insbesondere vollständiger, teilweiser und nicht verbrauchter FSA, belegte Nullwerte, unbekannte Verlustdaten, Verlustverrechnung vor FSA, keine doppelte Teilfreistellung, gemeinsamer FSA über mehrere Konten, Institute und Jahre sowie PDF-/Finanzreport-Dublettenschutz.

Es wurden keine produktive Datenbank, Original-PDFs oder wirtschaftlichen Buchungen verändert.
