# comdirect-Steuermitteilungen Investment-Ausschüttungen – Test 2026

## Ergebnis

Der rekursive, schreibgeschützte Lauf über
`C:\Users\chris\Desktop\history\comdirect\2026` prüfte 102 PDFs mit
`portfolio_v5.pdf_importer.parse_pdf()` und den registrierten Plugins. Es wurde
keine SQLite-Datenbank geöffnet oder verändert und kein Originalbeleg geändert.

| Ergebnis | Bericht vor dieser Änderung | Aktueller Lauf | Differenz |
|---|---:|---:|---:|
| Geprüfte PDFs | 102 | 102 | 0 |
| Erfolgreich | 57 | 62 | +5 |
| Fehlerhaft | 0 | 0 | 0 |
| Generischer Fallback | 45 | 40 | -5 |

Aktuelle Plugin-/Handler-Zusammenfassung:

| Plugin / Handler | PDFs |
|---|---:|
| comdirect.finanzreport / finanzreport | 10 |
| user.comdirect-ertraege / wertpapierkauf | 26 |
| user.comdirect-ertraege / vorabpauschale | 6 |
| user.comdirect-ertraege / investment_ausschuettung | 20 |
| generic.kontoauszug / generic | 40 |

## Neue Dokumentabdeckung

- 20 reale Belege (einschließlich identischer Dateipaare) wurden als separate
  Investment-Ausschüttungs-Steuermitteilungen erkannt.
- Davon sind 14 inländische und 6 ausländische Belege.
- Alle 20 wurden ohne Parserfehler strukturiert verarbeitet.
- Die zwei separaten Steuermitteilungen zu normalen Aktien-Dividenden (Fresenius
  und SAP) bleiben außerhalb dieses Auftrags generisch.

Der Nettounterschied zum gespeicherten Vorbericht beträgt nur fünf Dokumente,
weil der aktuelle Lauf 15 ältere Kaufabrechnungen mit defekter eingebetteter
Schrift (LS9AVX, A2H57N und LYX05A) bereits auf dem unveränderten `main`-Stand
generisch einordnet. Die vorliegende Änderung berührt deren Erkennungsregeln
nicht. Gegenüber dem aktuellen Parserstand wurden keine zuvor erkannten
Dokumente durch die neue Steuermitteilungsregel verdrängt.

## Referenzbeleg A0H074 vom 15.09.2026

| Feld | Extrahierter Wert |
|---|---:|
| ISIN / WKN | DE000A0H0744 / A0H074 |
| Stückzahl | 27,051 |
| Bruttoausschüttung | 9,10 EUR |
| Teilfreistellung | 30 % / 2,73 EUR |
| Steuerbemessungsgrundlage | 6,37 EUR |
| Kapitalertragsteuer | 1,59 EUR |
| Solidaritätszuschlag | 0,08 EUR |
| Kirchensteuer | 0,00 EUR |
| Gesamtsteuer | 1,67 EUR |
| Nettoauszahlung | 7,43 EUR |
| Datum / Valuta | 15.09.2026 / 15.09.2026 |

Die Steuerinformation wird im bestehenden `TaxEvent`-Modell abgelegt. Der
Parser erzeugt keine zweite Ausschüttung. Bei einer nachgewiesenen Steuer größer
null entsteht ausschließlich eine verknüpfte Steuerbuchung; bei dokumentierten
0,00 EUR bleibt das Ereignis cash-neutral. Fehlende Beträge werden nicht zu null
umgedeutet, sondern führen zur sicheren Ablehnung der strukturierten Verarbeitung.

## Abgleich und Dublettenschutz

- Ereignisidentität: Depot, ISIN, Datum, Brutto, Steuerbetrag und Belegreferenz.
- Steuerbuchung: gleiche stabile Ereignis-ID mit Suffix `-payment`.
- Wiederimport desselben Belegs zählt weder Steuerereignis noch Steuerbuchung
  doppelt; der vollständige PDF-Beleg bleibt archivierungsfähig.
- Mehrere Ausschüttungen desselben Fonds im selben Jahr bleiben eigenständige
  Ereignisse. Die bestehende Jahreskonfliktprüfung gilt weiterhin ausschließlich
  für Vorabpauschalen.
- Eine bereits vorhandene Ausschüttung bleibt unverändert; aus der separaten
  Steuermitteilung wird keine Nettoauszahlung erzeugt.

## Testnachweise

- Ziel- und Regressionstests: 148 bestanden, 0 fehlgeschlagen.
- Zwei bestehende Qt-Deprecation-Warnungen in `tax_detail_view.py`; ohne Bezug zu
  dieser Änderung.
- Realer rekursiver PDF-Lauf: 102 geprüft, 62 erfolgreich, 0 fehlerhaft,
  40 generisch.
