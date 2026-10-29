# Portman V09 – Erneute SQLite-Abnahme nach PR #19

Prüfzeitpunkt: 22.10.2026, 17:19 CEST  
Branch/Stand: `main` / `55b2eda` (`Fix comdirect tax and fee reconciliation (#19)`)

## Ergebnis

**PASS.** Die SQLite-Datenintegritätskorrekturen wurden auf dem gemergten
Stand erneut abgenommen. Alle schreibenden Prüfungen verwendeten neu erzeugte
temporäre SQLite-Datenbanken. Produktive Datenbanken und Original-PDFs wurden
nicht verändert.

| Prüfung | Ergebnis |
|---|---:|
| Gezielte SQLite-Integration | 22 bestanden, 0 fehlgeschlagen |
| Vollständige Pytest-Suite | 1.073 bestanden, 9 übersprungen, 0 fehlgeschlagen |
| Rekursiv gelesene comdirect-PDFs | 102 |
| PDF-Parserfehler | 0 |
| Fachlich strukturierte PDFs | 79 |
| Generische Kosteninformationen | 23 |
| Finanzreport-Saldoidentitäten | 27/27 centgenau |

## SQLite-Kernabnahme

Ausgeführt wurden:

```text
tests/test_comdirect_p1_integrity.py
tests/test_comdirect_investment_distribution_tax.py
tests/test_import_options.py
tests/test_import_atomic.py
```

Ergebnis: `22 passed in 4.60s`.

Damit wurden erneut geprüft:

- Finanzreport zuerst und Belege zuerst;
- wiederholter Import ohne zusätzliche aktive Imports, Transaktionen,
  `booking_details` oder `booking_evidence`;
- Steuer-/Dividendenverknüpfung einschließlich Nullsteuer;
- Persistenz der Kaufgebühren an der vorhandenen Finanzreportbuchung;
- keine zweite Kauftransaktion und keine zweite Cashbelastung;
- Gebühren in den Performance-Transaktionen genau einmal.

Die Referenzgebühren bleiben strukturiert nachweisbar:

| Wertpapier | Gebühr |
|---|---:|
| A111X9 | 0,46 EUR |
| A0S9GB | 0,27 EUR |
| SAP / 716460 | 0,43 EUR |

## Vollständige Regression

Die gesamte Testsuite wurde mit einem neuen temporären Basisverzeichnis
ausgeführt.

```text
1073 passed, 9 skipped in 306.47s (0:05:06)
```

Es gab keine Fehlschläge und keine neue Warnungs- oder Fehlerklasse.

## Original-PDFs und Salden

Alle PDFs unter
`C:\Users\chris\Desktop\history\comdirect\2026` wurden erneut rekursiv mit
`portfolio_v5.pdf_importer.parse_pdf()` und den registrierten Plugins gelesen.

| Plugin/Dokumenttyp | Anzahl |
|---|---:|
| comdirect Finanzreport | 10 |
| Wertpapierabrechnung Kauf | 41 |
| Investment-Ausschüttung / Steuermitteilung | 20 |
| Vorabpauschale | 6 |
| Inländische Dividenden-Steuermitteilung | 2 |
| Generisches Dokument / Kosteninformation | 23 |
| **Gesamt** | **102** |

Alle 102 Dateien wurden ohne Parserfehler verarbeitet. Die neun
unterschiedlichen Finanzreports enthalten jeweils drei Konten. Ihre
Parserprüfung `Anfangssaldo + Buchungssumme = Endsaldo` ergab erneut 27 von 27
centgenaue Identitäten. Der zehnte Finanzreport ist das bereits bekannte
inhaltliche Duplikat und verändert dieses Ergebnis nicht.

## Schutz der produktiven Daten

- Keine produktive SQLite-Datei wurde als Testziel verwendet.
- Sämtliche Testdatenbanken lagen in pytest-spezifischen temporären
  Verzeichnissen.
- Keine Original-PDF wurde verändert.
- Es wurden im Rahmen dieser Wiederholungsabnahme keine fachlichen Daten
  migriert oder repariert.

