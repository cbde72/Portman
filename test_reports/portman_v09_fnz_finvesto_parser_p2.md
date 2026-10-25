# Portman V09 - FNZ / finvesto P2

## 1. Ausgangspunkt

- Branch: `fix/fnz-finvesto-parser-p2`
- Basis: `6aa0b9e74c7aabf1754e9631bc230b198039748b` (`origin/main`, inklusive PR #35)
- Unveränderte Baseline: PDF-Parser-Audit V2 vom 24.10.2026, Parser-Fingerprint `c4c46393ea9f4b82`
- Neuer ungecachter Teilaudit: 25.10.2026, Parser-Fingerprint `95b2e3362f3dc378`, OCR aktiv
- Originale: `history/fnz`; weder PDFs noch produktive Datenbank wurden verändert.

## 2. Inventar und Abgrenzung

Die Baseline enthält unter `fnz/` 22 physische PDFs mit 13 eindeutigen SHA-256-Inhalten. Die genannten 16 Fehlerpfade sind nicht 16 verschiedene Belege, sondern sieben eindeutige Umsatzabrechnungen. Umsatzabrechnung Nr. 88 liegt zehnmal byteidentisch vor. Daneben existieren fünf eindeutige generische Archivbelege und ein bereits erkannter Quartalsdepotauszug.

| Gruppe | Physische PDFs | Eindeutige SHA | Baseline |
|---|---:|---:|---|
| FNZ-Umsatzabrechnungen mit Fehler | 16 | 7 | `PARSER_ERROR` |
| Quartalsdepotauszug | 1 | 1 | `fnz.finvesto/depotauszug` |
| Konto-flex-Auszug ohne Umsatz | 3 | 3 | generische Archivierung |
| Ex-post-Kosteninformation | 1 | 1 | generische Archivierung, `MIFID_COST` |
| VL-Information | 1 | 1 | generische Archivierung |
| Gesamt | 22 | 13 | |

Die 24 globalen `PARSER_ERROR`-Fälle der V2-Baseline umfassen neben FNZ acht andere Dokumentpfade. FNZ selbst stellt 16 Fehlerpfade beziehungsweise sieben Fehlerinhalte.

## 3. Ursachenanalyse

Sechs eindeutige Umsatzabrechnungen enthielten vollständige, strukturierte Transaktionszeilen. Der Import wurde dennoch verworfen, sobald irgendeine Seite des Dokuments per OCR ergänzt worden war. Betroffen waren überwiegend reine Hinweis- und Rechtsseiten; die fachlich relevanten Tabellen blieben eingebetteter PDF-Text. Die pauschale Dokumentablehnung war daher nicht fachlich begründet.

Auszug Nr. 81 enthält eine USD-Ausschüttung mit 2,98 USD brutto, 0,54 USD Steuerabzug und 2,44 USD Netto-Wiederanlage. Der alte Parser verglich den Netto-Zahlungsbetrag unmittelbar mit dem Bruttoertrag und brach ab. Die Steuerkomponenten sind im Original in EUR angegeben: 0,45 EUR Kapitalertragsteuer, 0,02 EUR Solidaritätszuschlag und 0,00 EUR Kirchensteuer. Mit dem dokumentierten Kurs 1,153077 EUR/USD ergeben sich centgenau 0,52 USD, 0,02 USD und 0,00 USD, zusammen 0,54 USD.

Beim SQLite-Wiederimport trat außerdem ein fremder Fehler in `preserve_booking_ids` auf: Ohne vorhandene comdirect-/generische Altkennungen wurde trotzdem comdirect-spezifisch auf `purpose` zugegriffen. FNZ-`Transaction` besitzt dieses Feld nicht. Ein früher, semantisch neutraler Rücksprung begrenzt die Routine nun auf tatsächlich passende Altbuchungen.

## 4. Originalbeleg-Soll-Ist-Prüfung

Alle 13 verfügbaren eindeutigen PDFs wurden automatisiert verarbeitet und auf der ersten fachlich relevanten Seite gerendert und visuell geprüft. Die geforderte Stichprobe von 20 eindeutigen Originalen ist im Bestand nicht erreichbar; vorhanden sind nur 13. Alle sieben eindeutigen Fehlerbelege und alle sechs eindeutigen Regressionsbelege wurden einbezogen.

| SHA-256 (Kurzform) | Relativer Pfad | Typ / Handler nachher | Manuell belegte Sollwerte | Ergebnis / Maßnahme |
|---|---|---|---|---|
| `94366e5ec7b1` | `fnz/IndividuelleKosteninformationEx-postaggregiert-2026-07-06.pdf` | Kosteninformation / generisch | 21,37 EUR Gesamtkosten, keine Buchung | WARNING; bewusst Archiv-only, keine FNZ-Transaktion |
| `162c7e4fd574` | `fnz/OnlineAuszug-Nr4-2024-09-20.pdf` | Konto-flex-Auszug / generisch | Anfang/Ende 0,00 EUR, keine Umsätze | WARNING; Archiv-only korrekt |
| `5332958f0c63` | `fnz/OnlineAuszug-Nr4-2025-05-23.pdf` | Konto-flex-Auszug / generisch | Anfang/Ende 0,00 EUR, keine Umsätze | WARNING; Archiv-only korrekt |
| `bbba6c6cb39d` | `fnz/OnlineAuszug-Nr45-2023-12-29.pdf` | Umsatzabrechnung / `fnz.finvesto` | 2 Käufe, Ausschüttung, Wiederanlage; Bestand 1.435,48 EUR | PASS mit Audit-Hinweisen; 4 Ereignisse, Teilbestand |
| `0a838c06f94e` | `fnz/OnlineAuszug-Nr58-2025-03-28.pdf` | Umsatzabrechnung / `fnz.finvesto` | Kauf 40,00 EUR; Bestand 2.376,42 EUR | PASS mit Audit-Hinweisen; 1 Ereignis |
| `3a90058e1559` | `fnz/OnlineAuszug-Nr60-2025-05-01.pdf` | Umsatzabrechnung / `fnz.finvesto` | Kauf 39,92 + 0,08 EUR; Zahlung 40,00 EUR; Bestand 2.251,93 EUR | PASS mit Audit-Hinweisen; 1 Ereignis |
| `e201a415ae36` | `fnz/OnlineAuszug-Nr71-2025-12-24.pdf` | Umsatzabrechnung / `fnz.finvesto` | 2,46 USD Ausschüttung/Wiederanlage, Kauf 40,00 EUR; Bestand 3.186,70 EUR | PASS mit Audit-Hinweisen; 3 Ereignisse |
| `0163cc4b7536` | `fnz/OnlineAuszug-Nr79-2026-04-29.pdf` | Umsatzabrechnung / `fnz.finvesto` | Kauf 39,92 + 0,08 EUR; Zahlung 40,00 EUR; Bestand 3.572,26 EUR | PASS mit Audit-Hinweisen; 1 Ereignis |
| `d34c6d47a5cb` | `fnz/OnlineAuszug-Nr81-2026-06-24.pdf` | Umsatzabrechnung / `fnz.finvesto` | 2,98 USD brutto - 0,54 USD Steuer = 2,44 USD; Wiederanlage; Bestand 4.113,25 EUR | PASS; 2 Ereignisse, strukturierte Steuern |
| `4670bf637db7` | `fnz/OnlineAuszug-Nr88-2026-10-06.pdf` und 9 Kopien | Umsatzabrechnung / `fnz.finvesto` | Kauf/Zahlung 40,00 EUR; Bestand 4.430,49 EUR | PASS mit Audit-Hinweisen; 1 Ereignis, Kopien gruppiert |
| `a5bd8f49e15e` | `fnz/OnlineAuszug-Nr9-2023-08-22.pdf` | Konto-flex-Auszug / generisch | Anfang/Ende 0,00 EUR, keine Umsätze | WARNING; Archiv-only korrekt |
| `bd5a647f9e18` | `fnz/Quartalsdepotauszug-Nr87-2026-10-04.pdf` | Depotauszug / `fnz.finvesto` | 6,550662 Anteile, Wert 4.324,11 EUR | PASS; ein Snapshot. Kein separat ausgewiesener Depotgesamtwert, daher vorsätzlich nicht `complete` |
| `95d150a71ecd` | `fnz/VL-Information-2026-08-13.pdf` | VL-Information / generisch | reine Meldungsinformation, keine Buchung | WARNING; Archiv-only korrekt |

## 5. Buchungssemantik, Bestände und Steuern

- Käufe bleiben negative Depotereignisse. `Zahlungsbetrag aus Überweisung` wird nicht als zweite Kontobuchung erzeugt.
- Ausschüttung und Wiederanlage bleiben zwei getrennte, referenzierte Ereignisse mit entgegengesetztem Cash-Effekt; es entsteht kein zusätzlicher Cashflow.
- Transaktionsentgelt wird nur bei ausdrücklich ausgewiesenen 0,08 EUR gesetzt. Es wird nicht aus einer Differenz erfunden.
- Auszug Nr. 81 speichert Brutto, Netto, Gesamtsteuer und die drei Komponenten. Umrechnung erfolgt ausschließlich mit dem Belegkurs. Es wird kein separates, doppelt wirkendes Steuerereignis erzeugt.
- Freistellungsangaben werden nicht neu interpretiert und die globale FSA-Logik bleibt unverändert.
- Umsatzabrechnungen zeigen ausdrücklich nur Positionen mit Umsatz und werden deshalb als unvollständige Snapshots importiert. Es erfolgt keine erfundene Gesamtbestandsfortschreibung.
- Im vorhandenen Bestand gibt es nur ein Depot (`99129663176`) und einen Fonds (`IE0032077012`). Eine kontenübergreifende Saldenaddition findet nicht statt.
- Die drei Konto-flex-Auszüge enthalten keine Buchungen und jeweils 0,00 EUR Anfangs-/Endstand; es gibt daher keine zu importierende Saldenkette.

## 6. Implementierte Änderungen

1. `pdf_plugins/fnz_finvesto.py`
   - pauschale Ablehnung kompletter FNZ-Belege bei OCR auf einer beliebigen Seite entfernt;
   - strukturierte Erkennung des FNZ-Steuerblocks ergänzt;
   - Netto = Brutto - Steuern beziehungsweise Kaufzahlung = Kurswert + Entgelt centgenau validiert;
   - Steuerkomponenten nur mit dokumentiertem Wechselkurs umgerechnet und mit dem dokumentierten Gesamtsteuerabzug abgeglichen.
2. `src/portfolio_v5/comdirect_identity.py`
   - Kennungsübernahme beendet sich ohne passende alte comdirect-/generische Buchungen, statt fremde Transaktionstypen zu untersuchen.
3. `tests/test_phase_c_fnz.py`
   - OCR-Seiten bei gleichzeitig strukturierten FNZ-Zeilen;
   - Fremdwährungsausschüttung mit Steuerkomponenten;
   - temporäre SQLite-Persistenz, Wiederimport und gleiche wirtschaftliche Ereignisse bei anderem Containerhash.

## 7. Audit vorher / nachher

Der Audit wurde ohne Cache über alle 22 PDFs mit OCR ausgeführt. Der eingebaute `--compare`-Bericht konnte wegen unterschiedlicher relativer Wurzeln (`fnz/...` in der Gesamtbaseline gegen Dateiname im Teilaudit) keine Zeilen direkt paaren. Der belastbare Vergleich wurde deshalb per SHA-256 vorgenommen.

| Kennzahl | Baseline V2 | Nachher |
|---|---:|---:|
| Physische FNZ-Dateien | 22 | 22 |
| Eindeutige FNZ-SHA | 13 | 13 |
| FNZ-Fehlerpfade | 16 | 0 |
| Eindeutige fehlerhafte Inhalte | 7 | 0 |
| `fnz.finvesto/umsatzabrechnung` | 0 erfolgreich | 16 erfolgreich (7 SHA) |
| `fnz.finvesto/depotauszug` | 1 | 1 |
| Generische Fallbacks | 5 | 5, unverändert und fachlich Archiv-only |
| Neue Parserfehler | 0 | 0 |
| Neue wirtschaftliche Dubletten | 0 | 0 |
| Cache-Treffer | 0 | 0 |

Die verbleibenden Audit-Warnungen sind keine verschwiegenen Parserfehler: `QUANTITY_CONFLICT` vergleicht die einzelne Umsatzmenge mit dem nach Verbuchung ausgewiesenen Teilbestand; `UNCLASSIFIED_WARNING` stammt aus der bewusst konservativen Auditklassifikation. Der einmalige `NET_GROSS_MISMATCH` bei Nr. 45 entspricht dem belegten Entgelt von 0,08 EUR.

## 8. SQLite- und Idempotenzprüfung

Auf temporären SQLite-Datenbanken wurde nachgewiesen:

- Erstimport: drei wirtschaftliche Ereignisse aus dem synthetisch gekennzeichneten FNZ-Regressionstext;
- identischer Wiederimport: `duplicate`, keine neue Transaktion;
- anderer PDF-Containerhash mit denselben stabilen FNZ-Referenzen: null neue Transaktionen, drei unveränderte Ereignisse und ein unveränderter Teilsnapshot;
- Steuerereignisse: null zusätzliche Einträge;
- bestehende Rollback-, Reihenfolge-, Mehrkonto- und Persistenztests bleiben Bestandteil der Gesamtsuite.

## 9. Tests

- `python -m compileall -q src/portman src/portfolio_v5 pdf_plugins`: **PASS**
- `python -m ruff check src/portman src/portfolio_v5 pdf_plugins --select F`: **PASS**
- FNZ-/Persistenz-/Rollback-/Reihenfolgetests: **18 passed**
- gezielte FNZ- und IBAN-Identitätsregression nach finaler Guard-Korrektur: **7 passed**
- Gesamtsuite: **1178 passed, 15 skipped, 5 subtests passed**, 2 bestehende Qt-Deprecation-Warnungen; Laufzeit 487,07 s
- Ungecachter FNZ-Audit: **22/22 verarbeitet, 0 ERROR, 0 Cache-Treffer**

## 10. Grenzen und Risiken

- Es existieren nur 13 eindeutige FNZ-Originale, daher waren 20 eindeutige Originalprüfungen nicht möglich.
- Kein Beleg enthält Verkauf, Storno, Depotübertrag, Sparplanstorno oder mehrere FNZ-Depots. Solche Layouts wurden nicht erfunden und bleiben außerhalb dieses Fixes.
- Die Ex-post-Kosteninformation wird weiterhin durch den generischen, transaktionslosen Archivpfad behandelt. Eine FNZ-spezifische Kostendatenmodell-Erweiterung war nicht erforderlich.
- Der Quartalsdepotauszug weist keinen separaten Gesamtwert aus; der Parser markiert ihn deshalb konservativ nicht als vollständig.
- OCR-Warnungen bleiben sichtbar. Die Änderung unterdrückt sie nicht, sondern lässt nur nachweislich strukturierte Zeilen weiter fachlich validieren.

## 11. Gesamtbewertung

**PASS MIT HINWEISEN**: Alle sieben eindeutig interpretierbaren Fehlerinhalte beziehungsweise alle 16 physischen Fehlerpfade werden fachlich strukturiert importiert. Beträge, Vorzeichen, Gebühren, Steuerkomponenten, Wiederanlage und Teilbestände stimmen mit den Originalen überein. Keine zusätzliche Kontobuchung, kein doppeltes Steuerereignis und keine Abschwächung der Deduplizierung wurden eingeführt. Die Hinweise betreffen ausschließlich den kleinen realen Layoutbestand, bewusst archivierte Nicht-Transaktionsdokumente und konservativ fortbestehende Auditwarnungen.
