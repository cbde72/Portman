# Portman V09 – comdirect P2: Abschlussbericht

## 1. Ausgangsbasis und Umfang

- Branch: `fix/comdirect-remaining-parser-errors-p2`
- Basis: `b2b7370561dc` (`main`, einschließlich PR #27, #31, #32 und #33)
- Scope: zwölf physische PDFs, zwölf eindeutige SHA-256-Inhalte
- Produktionsdatenbanken und Original-PDFs wurden nicht verändert.
- Audit: isolierter, nicht gecachter Produktionsparser-Aufruf je PDF mit 90 Sekunden Timeout.

## 2. Ursachen und Korrekturen

### Kaufabrechnungen (6)

Alte comdirect-Sparplankäufe weisen auf der Geschäftsabrechnung die tatsächliche Bruchstückzahl
(`1,001`, `1,003`, `1,007` beziehungsweise `2,004`) aus. Die separate steuerliche Seite druckt
nur den ganzzahligen Anteil (`1` beziehungsweise `2`). Der Parser behandelte beide Angaben bisher
als gleichwertig und brach mit einem Stückzahlkonflikt ab.

Die Geschäftsabrechnung bleibt die Primärquelle. Eine abweichende ganzzahlige Steuerangabe wird
nur akzeptiert, wenn sie exakt dem ganzzahligen Anteil der positiven Bruchstückzahl entspricht und
die Primärangabe zuvor unabhängig durch `Stückzahl × Kurs = Kurswert` mit Centtoleranz bestätigt
wurde. Andere Konflikte werden weiterhin abgewiesen. Gebühren, Steuern und Deduplizierung wurden
nicht verändert.

### Inländische Dividenden (5)

Diese Layouts enthalten alle wirtschaftlich erforderlichen Brutto-, Steuerkomponenten- und
Nettoangaben, aber teilweise keinen FSA- und keinen Nach-Verlustverrechnung-Block. Diese beiden
Felder sind nun optional und bleiben bei fehlender Belegangabe `None`; es wird keine Null erfunden.
Die fünf Belege erzeugen jeweils genau ein Steuerereignis, ein Archivdokument und keine zweite
Dividenden- oder Kontobuchung.

Der Beleg `22fa34d3e010…` weist selbst Brutto `9,46 EUR`, abgeführte Steuern `0,00 EUR` und Netto
`6,96 EUR` aus. Diese beleginterne Differenz von `2,50 EUR` wird ausdrücklich gewarnt, nicht durch
eine Ausgleichsbuchung repariert und erzeugt keinen Cashflow.

### Vorabpauschale (1)

Der Beleg weist Vorabpauschale `2,22 EUR`, Teilfreistellung `0,67 EUR` und Steuerbemessungsgrundlage
`0,00 EUR` aus, jedoch keine einzelne FSA-Nutzungszeile. Die FSA-Nutzung und ein nicht ausdrücklich
belegter Verlustausgleich bleiben deshalb `None`. Es entsteht ein Steuerereignis und ein
Archivdokument, aber keine Steuer- oder Kontobuchung.

## 3. Referenzprüfung der Originale

| SHA-256 (kurz) | Typ | Belegwert / Ergebnis | Handler | Wirtschaftliches Ergebnis |
|---|---|---|---|---|
| `5b44a6aef63a` | Kauf | 1,001 × 24,5859 = 24,61 EUR | `wertpapierkauf` | 1 Kauf, 0,37 EUR Gebühr |
| `f685128a028d` | Kauf | 1,001 × 24,60 = 24,62 EUR | `wertpapierkauf` | 1 Kauf, 0,37 EUR Gebühr |
| `769f1d533bb1` | Kauf | 1,003 × 24,535 = 24,61 EUR; OCR | `wertpapierkauf` | 1 Kauf, 0,37 EUR Gebühr |
| `a9ef79b876b1` | Kauf | 1,003 × 24,54 = 24,61 EUR | `wertpapierkauf` | 1 Kauf, 0,37 EUR Gebühr |
| `4e8a1267b34c` | Kauf | 1,007 × 24,43577 = 24,61 EUR | `wertpapierkauf` | 1 Kauf, 0,37 EUR Gebühr |
| `e983d305def0` | Kauf | 2,004 × 24,579 = 49,26 EUR | `wertpapierkauf` | 1 Kauf, 0,74 EUR Gebühr |
| `8970ba907335` | Dividende | 13,18 − 3,48 = 9,70 EUR | `dividende_steuer_inland` | 1 Steuerereignis, 0 Cashflows |
| `42a1f01874ec` | Dividende | 3,88 − 1,02 = 2,86 EUR | `dividende_steuer_inland` | 1 Steuerereignis, 0 Cashflows |
| `9bab407933cf` | Dividende | 25,53 − 6,73 = 18,80 EUR | `dividende_steuer_inland` | 1 Steuerereignis, 0 Cashflows |
| `acd4da1f774d` | Dividende | 4,22 − 1,11 = 3,11 EUR | `dividende_steuer_inland` | 1 Steuerereignis, 0 Cashflows |
| `22fa34d3e010` | Dividende | Belegwiderspruch 9,46 − 0,00 ≠ 6,96 EUR | `dividende_steuer_inland` | Warnung, 1 Steuerereignis, 0 Cashflows |
| `221d2e58da76` | Vorabpauschale | 2,22 / 0,67 / 0,00 EUR; FSA fehlt | `vorabpauschale` | 1 Steuerereignis, 0 Cashflows |

Alle zwölf PDFs wurden zusätzlich visuell gegen die gerenderten Originalseiten geprüft. Da Poppler
in der Umgebung nicht installiert war, erfolgte die reine Sichtprüfung mit PDFium; die eigentliche
Parserprüfung nutzte unverändert den Produktionspfad.

## 4. Auditvergleich

| Kennzahl | Vorher | Nachher |
|---|---:|---:|
| Physische PDFs | 12 | 12 |
| Eindeutige SHA-256 | 12 | 12 |
| Parserfehler | 12 | 0 |
| Audit-Timeouts | nicht isoliert | 0 |
| Kauftransaktionen | 0 (Parserfehler) | 6 fachlich belegte Käufe |
| Cash-Transaktionen aus Steuerbelegen | 0 | 0 |
| Steuerereignisse aus Steuerbelegen | 0 (Parserfehler) | 6 |
| Archivierte Dokumente | 0 (Parserfehler) | 12 |
| Neue Steuer-/Gebührenbuchungen | 0 | 0 |
| Generische Fallbacks im P2-Scope | 0 | 0 |
| Handler-Regressionen im P2-Scope | 0 | 0 |

Auditdateien: `test_reports/pdf_parser_audit/comdirect_p2_isolated_after/audit.json` und
`files.csv`. Der Parser-Fingerprint änderte sich durch die Parserkorrektur; es wurde kein Cache
verwendet.

## 5. Persistenz- und Integritätsprüfung

Die bestehenden sowie ergänzten Regressionstests prüfen Import-Idempotenz, unterschiedliche
Belegreihenfolgen, bestehende Ausschüttungen, Steuer-/Cashflow-Verknüpfung, Konto- und
Depotzuordnung sowie temporäre SQLite-Repositories. Ergebnis:

- keine zweite Dividende und kein zusätzlicher Cashflow aus separaten Steuermitteilungen;
- keine erfundene FSA-Nutzung und keine erfundenen Verlustverrechnungswerte;
- dokumentierte Nullwerte bleiben von fehlenden Werten unterscheidbar;
- Kaufgebühren bleiben genau einmal mit der Kauftransaktion verknüpft;
- widersprüchliche Stückzahlen außerhalb des belegten Ganzzahl-Layouts werden weiter abgewiesen;
- wiederholte Imports bleiben idempotent; Konto-, Depot- und Performanceverhalten unverändert.

## 6. Qualitätssicherung

- `python -m compileall -q src/portman src/portfolio_v5 pdf_plugins tools/comdirect_p2_audit.py`: PASS
- `python -m ruff check src/portman src/portfolio_v5 pdf_plugins tools/comdirect_p2_audit.py --select F`: PASS
- gezielte comdirect-Regressionen: **51 passed**
- vollständige Testsuite: **1169 passed, 15 skipped, 5 subtests passed**
- zwei bestehende Qt-Deprecation-Warnungen in `tax_detail_view.py`; keine P2-Regression
- isolierter Originalbeleg-Audit: **12/12 verarbeitet, 0 Fehler, 0 Timeouts**

## 7. Risiken und Gesamtbewertung

Die Akzeptanz der gekürzten Steuerstückzahl ist bewusst eng und durch den Kurswertnachweis
abgesichert. Der widersprüchliche Dividendenbeleg bleibt als fachlicher Hinweis sichtbar; Portman
erfindet keinen Ausgleich. Ein strukturelles Datenbankschema wurde nicht geändert.

**Gesamtbewertung: PASS MIT HINWEISEN** – alle zwölf bisherigen Parserfehler sind im isolierten
Audit behoben; der beleginterne Brutto/Netto-Widerspruch wird korrekt transparent gehalten.
