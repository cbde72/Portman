# Portman V09 – Baader-Dividendenstorno

## Ergebnis

**PASS.** Die drei offenen Fehlerpfade sind Archivkopien desselben
Stornobelegs (SHA-256 `911f472ff70c…`). Der zugehörige Originalbeleg wurde
gefunden (SHA-256 `3647e345abf1…`) und vollständig gegen das Storno geprüft.

## Belegabgleich

| Merkmal | Original | Storno | Bewertung |
|---|---|---|---|
| Belegdatum | 17.02.2024 | 27.02.2024 | Folgedokument |
| Vorgangsnummer | 26172813 | 26172813 | identisch |
| Referenznummer | 524443206 | 526758625 | dokumentindividuell |
| Depot | 3128164001 | 3128164001 | identisch |
| ISIN / WKN | US0378331005 / 865985 | US0378331005 / 865985 | identisch |
| Wertpapier | Apple Inc. | Apple Inc. | identisch |
| Stückzahl | 4,125 | 4,125 | identisch |
| Ex-Tag | 09.02.2024 | 09.02.2024 | identisch |
| Zahltag / Valuta | 15.02.2024 | 15.02.2024 | identisch |
| Umrechnungskurs | EUR/USD 1,07733 | EUR/USD 1,07733 | identisch |
| Brutto | 0,99 USD / 0,92 EUR | 0,99 USD / 0,92 EUR | identisch |
| US-Quellensteuer | 0,14 EUR | 0,14 EUR | vollständig rückgängig gemacht |
| Netto | 0,78 EUR Gutschrift | Storno derselben Gutschrift | vollständig rückgängig gemacht |

Beide Seiten beider PDFs wurden gerendert und visuell geprüft. Auf Seite 2
reduziert das Storno den Quellensteuertopf um genau die zuvor eingestellten
0,14 EUR.

## Implementierung

Der Parser erzeugt für den verifizierten Stornobeleg eine `DIVIDEND`-Buchung
mit `is_reversal=True`:

- Netto `-0.78 EUR`
- Brutto `-0.92 EUR`
- Quellensteuer `-0.14 EUR`
- externe ID `baader-income-526758625`
- Gegenbuchungsreferenz `baader-income-524443206`

Original und Storno ergeben damit sowohl netto als auch bei der Steuer exakt
0,00 EUR. `affects_cash=False` bleibt unverändert, sodass keine zusätzliche
Kontobuchung neben dem vorhandenen Baader-Kontoumsatz entsteht.

Weil der Stornobeleg die ursprüngliche Referenznummer nicht abdruckt, ist nur
dieses anhand beider Originale vollständig geprüfte Paar freigeschaltet.
Unbekannte oder in einem Pflichtfeld abweichende Baader-Stornos werden weiterhin
abgelehnt. Damit wird keine unsichere allgemeine Zuordnungsheuristik eingeführt.

## Audit und Tests

Der ungecachete V2-Teilaudit verarbeitet alle drei physischen Stornokopien
(ein eindeutiger SHA-Inhalt) mit dem Baader-Dividendenhandler:

| Kennzahl | Vorher | Nachher |
|---|---:|---:|
| Physische Fehlerpfade | 3 | 0 |
| Eindeutige Fehler-SHA | 1 | 0 |
| Cachetreffer | – | 0 |
| Parserfehler | 3 | 0 |
| Neue wirtschaftliche Buchungen je eindeutiger Storno-SHA | 0 | 1 Gegenbuchung |
| Nettoeffekt zusammen mit Original | – | 0,00 EUR |
| Quellensteuereffekt zusammen mit Original | – | 0,00 EUR |

Die verbleibende Audit-Warnung `DIVIDEND_TAX` weist transparent auf die
enthaltene Quellensteuer hin. Dass der generische Auditvergleich denselben
Wechsel `ERROR/CANCELLATION` zu `WARNING/DIVIDEND_TAX` zugleich als Verbesserung
und Regression auflistet, ist ein Klassifikationsartefakt des Runners, keine
Handler- oder Buchungsregression.

Ausgeführt wurden Compileall, Ruff `--select F`, gezielte Parser-, Persistenz-,
Idempotenz- und Negativtests sowie die vollständige Pytest-Suite. Original-PDFs
und produktive Datenbanken blieben unverändert; die Integrationsprüfung nutzt
ausschließlich eine temporäre SQLite-Datenbank.
