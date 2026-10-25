# Portman V09 – Baader-Handelsbetragssemantik P1

## Gesamtbewertung

**PASS MIT HINWEISEN.** Die Baader-Kaufbeträge sind nun als negative Nettoabflüsse gespeichert, Verkäufe bleiben positive Nettozuflüsse. Alle 532 pfadbezogenen Baader-Befunde `BUY_POSITIVE` und `NET_GROSS_MISMATCH` (176 eindeutige Kauf-PDFs) sind beseitigt. Es entstanden keine neuen Parserfehler, Fallbacks, Handleränderungen, Transaktionen oder Cashflows. Eine eindeutige Dividenden-Stornierung bleibt bewusst offen.

## Ausgangslage und Ursache

- Basis: `origin/main` bei `c039cce` (PR #31 bereits integriert), eigener Worktree und Branch `fix/baader-trade-amount-semantics`.
- Neueste unveränderte V2-Baseline: `test_reports/pdf_parser_audit/run_001`, vollständiger Lauf vom 24.10.2026, Parser-Fingerprint `c4c46393ea9f4b82`.
- Die globale Baseline meldete 532 `BUY_POSITIVE` und 536 `NET_GROSS_MISMATCH`. Davon entfielen jeweils 532 auf Baader. Die übrigen vier Brutto-/Netto-Befunde gehören nicht zum Baader-Parser.
- `_baader_core.parse_baader_portfolio()` prüfte bereits korrekt, dass ein Kauf `Zu Lasten` und ein Verkauf `Zu Gunsten` abgerechnet wird. Der anschließend erzeugte `Transaction.amount` übernahm den auf dem PDF positiv gedruckten Absolutbetrag jedoch für beide Geschäftsarten positiv.
- Das projektweite Modell definiert `amount` als signierten Netto-Cashflow einschließlich Gebühren und Steuern: Kauf negativ, Verkauf positiv. `transaction_validation()` meldete daher zu Recht beide Warnungen. Eine Lockerung der globalen Validierung wäre fachlich falsch gewesen.

### Semantik vorher/nachher

| Geschäft | PDF-Ausweis | Vorher `amount` | Nachher `amount` | Gleichung |
|---|---|---:|---:|---|
| Kauf | `Zu Lasten` als positiver Druckwert | positiv | negativ | `-(Kurswert + Gebühren + Steuern)` |
| Verkauf | `Zu Gunsten` als positiver Druckwert | positiv | positiv | `Kurswert - Gebühren - Steuern` |

`gross_amount`, `fees`, `taxes`, Stückzahl, ISIN, Referenzen, Depotkonto und Verrechnungskonto bleiben unverändert. `affects_cash=False` bleibt ebenfalls unverändert: Der Wertpapierumsatz liefert Einstand/Veräußerung und Performancefluss, erzeugt aber keine zusätzliche Kontobuchung. Das Verrechnungskonto wird weiterhin als `cash_account` dokumentiert (`Baader Konto 3128164005` in den vorhandenen Originalen).

## Originalbelege

Es wurden 24 eindeutige Wertpapierabrechnungen manuell anhand des Originaltexts geprüft; vier repräsentative Layouts (Kauf mit Gebühr, steuerpflichtiger Verkauf, Nullerlös-Verkauf, Kauf ohne Gebühr) zusätzlich visuell gerendert. Der vollständige automatisierte Abgleich umfasste anschließend alle 181 eindeutigen Handels-SHA (176 Käufe, 5 Verkäufe) beziehungsweise alle 547 archivierten Handelsdateien.

Alle vorhandenen Handelsbelege betreffen `Baader Depot 3128164001` mit `Baader Konto 3128164005`. Ein zweites echtes Depot ist im Datenbestand nicht vorhanden; die Depotisolation ist deshalb zusätzlich synthetisch mit zwei Depotnummern getestet.

In der Tabelle bedeutet `Betrag` jeweils `PDF → Parser vorher → Soll/nachher`; Gebühren und Steuern sind in EUR und wurden am Original abgeglichen. Pfade sind relativ zum Scanroot `C:/Users/chris/Desktop/history`.

| # | SHA-256 (Präfix) | Typ/Jahr | Betrag EUR | Gebühr/Steuer | Originalbeleg |
|---:|---|---|---|---:|---|
| 1 | `303e109aa2c7` | Verkauf 2024 | 429,29 → 429,29 → 429,29 | 1,00 / 38,29 | `baader/.../20241017/...378124201...pdf` |
| 2 | `4c003b2c3591` | Verkauf 2024 | 13,07 → 13,07 → 13,07 | 1,00 / 0,39 | `baader/.../20241025/...381037822...pdf` |
| 3 | `dfc0181aae2e` | Verkauf 2025 | 0,00 → 0,00 → 0,00 | 0,05 / 0,00 | `baader/.../20250218/...438771607...pdf` |
| 4 | `a80b90af91f2` | Verkauf 2025 | 1.008,93 → 1.008,93 → 1.008,93 | 0,00 / 147,47 | `baader/.../20251029/...569344087...pdf` |
| 5 | `7e371e0ec461` | Verkauf 2025 | 233,05 → 233,05 → 233,05 | 1,00 / 0,00 | `baader/.../20251101/...571193474...pdf` |
| 6 | `627a9df3aa0e` | Kauf 2023 | 99,95 → 99,95 → -99,95 | 0,00 / 0,00 | `baader/.../20231009/...234180487...pdf` |
| 7 | `53b5131231de` | Kauf 2023 | 99,88 → 99,88 → -99,88 | 0,00 / 0,00 | `baader/.../20231009/...234234218...pdf` |
| 8 | `8f0b8a0f235e` | Kauf 2023 | 99,76 → 99,76 → -99,76 | 0,00 / 0,00 | `baader/.../20231009/...234243898...pdf` |
| 9 | `2b37b05bb9f8` | Kauf 2023 | 49,90 → 49,90 → -49,90 | 0,00 / 0,00 | `baader/.../20231009/...234243921...pdf` |
| 10 | `7d4adc3e9dc7` | Kauf 2024 | 49,78 → 49,78 → -49,78 | 0,00 / 0,00 | `baader/.../20240108/...265843322...pdf` |
| 11 | `29f4dda86d12` | Kauf 2024 | 49,96 → 49,96 → -49,96 | 0,00 / 0,00 | `baader/.../20240108/...265976170...pdf` |
| 12 | `a4d092937bc6` | Kauf 2024 | 99,91 → 99,91 → -99,91 | 0,00 / 0,00 | `baader/.../20240108/...265991728...pdf` |
| 13 | `af4d51b0d07b` | Kauf 2024 | 49,95 → 49,95 → -49,95 | 0,00 / 0,00 | `baader/.../20240108/...266088108...pdf` |
| 14 | `536b07ebceab` | Kauf 2025 | 49,99 → 49,99 → -49,99 | 0,00 / 0,00 | `baader/.../20250102/...414318659...pdf` |
| 15 | `8cd41d57f299` | Kauf 2025 | 100,00 → 100,00 → -100,00 | 0,00 / 0,00 | `baader/.../20250107/...417670075...pdf` |
| 16 | `30b1d8418796` | Kauf 2025 | 49,91 → 49,91 → -49,91 | 0,00 / 0,00 | `baader/.../20250107/...417854389...pdf` |
| 17 | `b9efef1ef735` | Kauf 2025 | 49,90 → 49,90 → -49,90 | 0,00 / 0,00 | `baader/.../20250107/...417945149...pdf` |
| 18 | `5f5d055ff3d5` | Kauf 2026 | 49,98 → 49,98 → -49,98 | 0,00 / 0,00 | `baader/.../20260106/...607964115...pdf` |
| 19 | `cfe2424964b2` | Kauf 2026 | 99,94 → 99,94 → -99,94 | 0,00 / 0,00 | `baader/.../20260106/...608059775...pdf` |
| 20 | `b3357ddef6fb` | Kauf 2026 | 49,86 → 49,86 → -49,86 | 0,00 / 0,00 | `baader/.../20260106/...608148090...pdf` |
| 21 | `19993ed72b09` | Kauf 2023 | 134,38 → 134,38 → -134,38 | 1,00 / 0,00 | `baader/.../20231013/...235278301...pdf` |
| 22 | `232faebc0ca2` | Kauf 2024 | 479,20 → 479,20 → -479,20 | 1,00 / 0,00 | `baader/.../20241002/...371036326...pdf` |
| 23 | `eda0e69365ad` | Kauf 2024 | 25,88 → 25,88 → -25,88 | 1,00 / 0,00 | `baader/.../20241003/...371358241...pdf` |
| 24 | `6170021382d2` | Kauf 2024 | 131,35 → 131,35 → -131,35 | 1,00 / 0,00 | `baader/.../20241218/...409112590...pdf` |

Die fünf Verkäufe decken steuerpflichtige, steuerfreie, gebührenpflichtige und einen Nullerlös-Fall ab. Die Käufe decken vier Jahre, Bruchstücke, ganze Stücke sowie gebührenfreie und gebührenpflichtige Varianten ab. In den 176 eindeutigen Kaufbelegen kam kein realer Kauf mit Steuerkomponente vor; diese unterstützte Gleichung ist daher durch einen gezielten Charakterisierungstest abgesichert.

## Codeänderung und Auswirkungen

- Geändert wurde nur die Erzeugung von `amount` in `pdf_plugins/_baader_core.py`: Der bereits geprüfte positive PDF-Abrechnungsbetrag wird für `Kauf` negiert und für `Verkauf` beibehalten.
- Die öffentliche Parser-API, externe IDs (`baader-trade-<Depot>-<Referenz>`), Dokumentidentitäten, Kontozuordnung, Deduplizierung und Persistenz bleiben unverändert.
- Keine globale Validierung, Performanceformel, Steuerlogik, Datenbankstruktur oder anderer Bankparser wurde geändert.
- Einstandskosten und FIFO verwenden bereits den Absolutbetrag. Die Performance-Normalisierung ist vorzeichenstabil (`BUY` wird zu `-abs(amount)`, `SELL` zu `abs(amount)`); Vorher/Nachher-Performanceflüsse sind daher identisch.
- `affects_cash=False` verhindert weiterhin jede zusätzliche Cashbuchung. Der signierte Betrag beschreibt die wirtschaftliche Richtung, nicht eine neue Kontobewegung.

## Regressionstests

`tests/test_baader_trade_semantics.py` und die angepassten bestehenden Tests prüfen:

1. Kauf ohne Gebühr, mit Gebühr und mit Steuerkomponente.
2. Verkauf ohne Gebühr, mit Gebühr und mit Steuerabzug.
3. Nicht zahlungswirksame Depottransaktion und Cashflow-Vorzeichen.
4. Brutto-/Netto-Gleichung mit Centwerten.
5. Stückzahl, Einstandskosten, FIFO und Performancefluss.
6. Doppel-/Wiederholungsimport.
7. Isolation zweier Baader-Depots.
8. Widersprüchliche Belastungsrichtung und Betragsgleichung.
9. Bewusste Ablehnung eines Stornos.

Fokussierter Lauf: **53 bestanden**.

## V2-Vergleich

Frischer gezielter Lauf mit unverändertem V2-Runner, ohne Cache, über den gesamten in der Baseline als `baader.pdf` erkannten Scope:

| Prüfung | Vorher | Nachher |
|---|---:|---:|
| Dateien / eindeutige SHA | 746 / 252 | 746 / 252 |
| Wertpapierabrechnungen | 547 | 547 |
| `BUY_POSITIVE` (Baader) | 532 Pfade / 176 SHA | 0 / 0 |
| `NET_GROSS_MISMATCH` (Baader) | 532 Pfade / 176 SHA | 0 / 0 |
| Transaktionen | 723 | 723 |
| Parserfehler im erneut gelaufenen Scope | 0 | 0 |
| Generische Fallbacks | 0 | 0 |
| Handler-/Pluginänderungen | – | 0 |
| Cache-Treffer | – | 0 |
| Regressionen | – | 0 |
| Verbesserte Dateien | – | 532 |

Die 532 Kauftransaktionen änderten ausschließlich das Vorzeichen von `amount`; 176 eindeutige Dokumentinhalte sind betroffen. Betragsbetrag, Gebühren, Steuern und `affects_cash` blieben gleich. Die Warnmeldungszahl sank von 2.367 auf 1.303, genau um 1.064 Meldungen (je Kauf eine Vorzeichen- und eine Brutto/Netto-Warnung). Verbleibend sind 173 pfadbezogene Hinweise zu Dividenden/Steuern und 10 bereits vorhandene unklassifizierte Warnungen; es kam keine neue Warnung hinzu.

## Storno und offene Hinweise

Die in der globalen V2-Auswertung als drei Baader-Parserfehler bezeichneten Fälle sind drei Archivpfade desselben Dokuments, SHA-Präfix `911f472ff70c`. Es handelt sich um eine Dividendenabrechnung `STORNO` vom 27.02.2024 für Apple, 4,125 Stück, 0,92 EUR brutto, 0,14 EUR US-Quellensteuer und 0,78 EUR ausgewiesene Gutschrift.

Das Dokument nennt keine maschinenlesbar eindeutige Referenz auf die zu stornierende Ursprungsbuchung. Ohne den nachweislich passenden Originalbeleg könnte der Parser eine falsche oder doppelte Gegenbuchung erzeugen. Die bestehende Fehlermeldung „Baader-Stornobeleg muss mit der ursprünglichen Abrechnung abgeglichen werden“ bleibt daher fachlich korrekt offen. Der gezielte `--plugin baader.pdf`-V2-Lauf kann diese drei Baselinezeilen wegen des erwarteten Parsefehlers und deshalb fehlenden Pluginfelds nicht auswählen; sie wurden separat nach SHA, Originaltext und visuellem Rendering geprüft.

## Qualitätssicherung

- `python -m compileall -q src/portman src/portfolio_v5 pdf_plugins`: **PASS**
- `python -m ruff check ... --select F`: **PASS**
- Fokussierte Pytest-Auswahl: **53 bestanden**
- Vollständige Suite: **1.158 bestanden, 15 übersprungen in 547,89 s**
- V2-Baader-Neulauf: **746/746 verarbeitet, 0 Cache, 0 Fehler im ausgewählten Scope, 0 Regressionen**

Es wurden ausschließlich temporäre SQLite-Datenbanken der Tests verwendet. Produktive Datenbanken und Original-PDFs wurden nicht verändert.
