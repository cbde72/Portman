# Testmatrix Importer

## Phase-A-Regressionsmatrix

| Risiko | Testnachweis | Erwartete Invariante |
|---|---|---|
| Sammelzahlung für mehrere Trades | `test_aggregate_cash_payment_is_fully_consumed_by_multiple_trades` | Geldseite verschwindet erst bei insgesamt vollständiger Zuordnung |
| Teilzuordnung / Rest | `test_partial_link_neutralizes_only_allocated_cash_share_and_respects_boundaries` | nur Anteil neutralisiert, Original unverändert |
| Vollständige Zuordnung | `test_direct_giro_purchase_is_uniquely_reconciled_and_counted_once` | ein wirtschaftlicher BUY |
| Mehrfachimport | `test_manual_link_survives_duplicate_reimport` und bestehende PDF-/Banktests | Link bleibt, zweiter Import `duplicate` |
| Gleicher Betrag, verschiedene Wertpapiere | `test_one_cash_booking_is_not_automatically_used_for_two_equal_purchases` | Konflikt, kein automatischer Link |
| Dividende plus Gutschrift | `test_income_or_tax_notice_and_cash_evidence_count_once[DIVIDEND]` | ein Ertrag |
| Steuer plus Belastung | `test_income_or_tax_notice_and_cash_evidence_count_once[TAX]` | ein Steuerflow |
| Gegenrichtung | parametrisierte automatische und manuelle Richtungstests | BUY/SELL/DIVIDEND/TAX/FEE abgewiesen |
| Überzuordnung | `test_manual_partial_allocations_respect_both_available_amounts` | beide Restbeträge geschützt |
| TWR/Dietz/XIRR | `test_partial_settlement_matches_reference_twr_dietz_and_xirr` | identisch zum bereinigten Referenzszenario |
| Fehlende Position | `test_missing_position_is_rejected_by_total_and_position_count` | kein vollständiger Snapshot |
| Fehlerhafte Summe | derselbe Test | Import zurückgestellt |
| Doppelte Position | `test_duplicate_position_prevents_snapshot_import` | Import zurückgestellt |
| Bestand ohne Kontrollsumme | `test_generic_position_table_is_partial_without_completeness_proof` | `complete=False` |
| Historische Deka-Tabelle ohne Aggregat | `test_legacy_deka_table_without_aggregate_proof_is_partial` | `complete=False` |
| Fehlende PDF-Seite | `test_missing_last_pdf_page_cannot_create_complete_statement` | Saldenprüfung bricht ab |

## Fixture-Regeln

Neue Bankbelege werden unter
`tests/fixtures/importers/<bank>/<dokumenttyp>/<layoutversion>/` abgelegt. Zu
jeder Quelle gehören erwartete normalisierte Daten, Warnungen, Saldo/Bestand,
Layoutmetadaten und Provenienz/Freigabe. Personen-, Konto-, Depot- und
Dokumentreferenzen müssen vor einem öffentlichen Commit entfernt sein.

Manipulationsvarianten umfassen fehlende Seiten/Minuszeichen, vertauschte
Dezimalzeichen, falsche Währung/ISIN, fehlende Steuerteile, abgeschnittene
Zeilen, doppelte Referenzen und falsche Summen.

Für jede weitere Phase sind gezielte Tests, danach Ruff/Compile-Prüfung und die
vollständige pytest-Suite erforderlich. Renditetests vergleichen Bestände,
Salden, Einstand, Gewinn, Dividende, Steuer, Gebühr, TWR, Modified Dietz, XIRR
und Gesamtvermögen vor/nach Wiederholungsimport.

Phase-A-Abschlusslauf (Python 3.13.9, pytest 8.4.2, PySide6 6.9.2): **961
bestanden, 9 übersprungen, 0 fehlgeschlagen** in 293,82 Sekunden. Der gezielte
Integritätslauf ergab 122 bestandene und 6 übersprungene Tests. Ruff,
`py_compile` und `git diff --check` waren erfolgreich.

## Phase-B-Regressionsmatrix

| Fall | Fixture / Test | Invariante |
|---|---|---|
| comdirect Verkauf | `comdirect/verkauf/compact-v1`; `test_comdirect_sale_is_depot_event_with_positive_cash_direction` | SELL positiv, Gebühr aus Brutto/Netto, PDF cash-neutral |
| comdirect Gegenrichtung | `test_comdirect_sale_rejects_debit_direction` | Verkauf mit Belastung wird hart abgewiesen |
| ING Verkauf | `ing/verkauf/current-v1`; `test_ing_sale_extracts_fee_and_positive_net_amount` | Kurswert minus Gebühr = Gutschrift |
| ING Vorabpauschale | `ing/vorabpauschale/current-v1`; `test_ing_advance_tax_separates_tax_basis_from_cash_debit` | Steuerbasis und tatsächliche Belastung bleiben getrennt |
| Vorabpauschale V09 | `test_advance_tax_events.py` | Vollständig/teilweise freigestellte und besteuerte Fälle; Zufluss-, Ertrags- und Belegdatum getrennt; Steuerkomponenten und Geldzahlung verknüpft; Depotbuchungsansicht cash-neutral; Dubletten je Depot/ISIN/Ertragsjahr verhindert |
| ING Steuererstattung | `ing/steuererstattung/current-v1`; `test_ing_tax_refund_has_positive_economic_direction` | positive Erstattung, Komponenten vollständig |
| Manipulierte Steuerkorrektur | `test_ing_tax_refund_rejects_inconsistent_components` | abweichende Summe wird nicht importiert |
| ING Original-Verkäufe | lokaler, nicht eingecheckter Prüflauf über zwei Belege | beide SELL positiv; mit/ohne Gebühr abgestimmtes Brutto/Netto; Depot- und Zahlungskonto vorhanden |
| comdirect Kauf-Stückzahl | `test_comdirect_trade_prefers_business_quantity_for_both_text_layouts`, `test_comdirect_trade_uses_positive_tax_quantity_only_after_value_check`, `test_comdirect_trade_rejects_when_both_quantity_sources_are_missing` plus lokale Originalbelege LS9AVX/ETF039 | Geschäftsabrechnung (`Nennwert`/`Zum Kurs von`) hat Vorrang; steuerliche `Stk.` nur positiv und nach Prüfung. Stückzahl × Kurs wird kaufmännisch auf Cent gerundet; höchstens 0,01 EUR Abweichung zum Kurswert ist zulässig, Widersprüche und fehlende Angaben brechen den Import konkret ab. |

Die Fixtures sind synthetisch und anonymisiert; jede Fixture enthält einen
Provenienznachweis. Nicht durch eine Fixture belegte Varianten werden in der
Abdeckungsmatrix nicht als unterstützt bezeichnet.

Phase-B-Abschlusslauf (Python 3.14, 17.10.2026): **970 bestanden, 9
übersprungen, 5 Subtests bestanden, 0 fehlgeschlagen** in 340,56 Sekunden.
Der gezielte Importer-/Settlement-/Performance-Lauf ergab 84 bestandene Tests
und 2 bestandene Subtests. Ruff, `py_compile` und `git diff --check` waren
erfolgreich. Die Finanzinvarianten für Bestand, Geldsaldo, Einstand,
realisierten Gewinn sowie TWR, Modified Dietz und XIRR werden durch die
bestehenden End-to-End-Regressionsszenarien zusammen mit den neuen
Cashflow-Richtungs- und Doppelerfassungsfällen abgedeckt.

Nachprüfung mit den lokal bereitgestellten Dokumenten: **972 bestanden, 9
übersprungen, 5 Subtests bestanden, 0 fehlgeschlagen** in 326,45 Sekunden.
Der Zuwachs umfasst die gebührenfreie ING-Verkaufsvariante und die sichere
Abweisung nicht lesbarer comdirect-Stückzahlen.

Die vom Nutzer lokal unter `history/comdirect` und `history/ing`
bereitgestellten Originale bleiben außerhalb des Repositories. Es werden weder
Dateinamen noch Personen-, Konto-, Depot- oder Dokumentnummern committed.

## Phase-C-Regressionsmatrix

| Fall | Fixture / Test | Invariante |
|---|---|---|
| Baader Dividende | `test_baader_dividend_keeps_net_gross_and_tax_components_consistent` | Netto plus Steuer = Brutto; PDF cash-neutral |
| Baader Vorabpauschale | `test_baader_advance_tax_separates_basis_and_debit` | Bemessungsgrundlage und tatsächliche Belastung getrennt |
| Baader Depotbestand | `test_baader_annual_statement_requires_matching_depot_total` | vollständig nur bei passendem Depotwert |
| Baader Übertrag | `test_baader_delivery_is_quantity_only_transfer` | Menge ohne erfundenen Geldfluss |
| FNZ Ausschüttung/Wiederanlage | `fnz/umsatzabrechnung/fnz-current-v1`; `test_distribution_reinvestment_and_purchase_are_three_economic_events` | Ertrag und Kauf getrennt, eindeutige IDs |
| FNZ Teilbestand | derselbe Test | Umsatzabrechnung bleibt `complete=False` |
| FNZ Depotbestand | `fnz/depotauszug/fnz-current-v1`; zwei Summenkontrolltests | vollständig nur bei abgestimmter Gesamtsumme |
| Deka Wiederanlage | `test_deka_distribution_and_reinvestment_are_linked_and_cash_neutral` | verknüpfter DIVIDEND/BUY, Summe null |
| Deka Altformat | `test_deka_historical_annual_statement_layout_is_detected` | Jahresdepotauszug trotz historischer Textersetzung erkannt |

Lokale, nicht eingecheckte Verifikation: 12 FNZ-PDFs, 37 Deka-PDFs sowie je
drei repräsentative Baader-Belege für Kauf/Verkauf, Dividende,
Vorabpauschale, Jahresdepotauszug und Depotübertrag. Sämtliche Originale
bleiben außerhalb des Repositories; Dateinamen und personenbezogene Referenzen
werden nicht dokumentiert. Portfolio Performance wurde am Commit
`805c20dff5d999e987675181b4f1d82f81df10c0` nur als fachliche Referenz genutzt.

Phase-C-Abschlusslauf (Python 3.14, 17.10.2026): **981 bestanden, 9
übersprungen, 5 Subtests bestanden, 0 fehlgeschlagen** in 306,44 Sekunden.
Der gezielte Importer-/Settlement-/Performance-Lauf ergab 45 bestandene Tests
und 2 bestandene Subtests. Ruff, `py_compile` und `git diff --check` waren
erfolgreich. Es wurde keine Performanceverbesserung behauptet; Phase C ändert
keinen gemessenen Massenschreibpfad.

## Phase-D-Regressionsmatrix

| Fall | Fixture / Test | Invariante |
|---|---|---|
| Renault Zins/Steuer | `renault/kontoauszug/verified-v1`; `test_renault_classifies_interest_tax_and_transfer_without_changing_cash_sum` | Zins, KapESt und Soli getrennt; Cashsumme unverändert |
| Renault Storno/Erstattung | `test_renault_storno_and_tax_refund_keep_economic_direction` | negativer Zinsstorno und positive Steuererstattung |
| Renault FinTS | `test_renault_fints_uses_same_explicit_cash_classification` | gleiche Fachtypen wie PDF, stabile alte Buchungs-ID |
| BoS Zins/Steuer/Saldo | `bank_of_scotland/kontoauszug/verified-v1`; `test_bank_of_scotland_statement_classifies_rows_and_reconciles_balance` | Anfang + Buchungen = Ende |
| Fehlende Seite/falscher Saldo | zwei BoS-Manipulationstests | kein vollständiger Import |
| Überlappende Auszüge | `test_overlapping_statement_rows_have_stable_ids_and_do_not_duplicate` | identische Buchung nur einmal |
| Interner Transfer | `test_internal_transfer_scoped_cashflow` | nach Paarung kein externer Beitrag |
| TWR/XIRR | `test_partial_settlement_matches_reference_twr_dietz_and_xirr` | Referenzrenditen bleiben unverändert |

Lokale, nicht eingecheckte Verifikation: 200 Renault- und 75 Bank-of-Scotland-
PDFs. Die Originale, Dateinamen und personenbezogenen Daten bleiben außerhalb
des Repositories. Fachliche Portfolio-Performance-Referenz ist Commit
`805c20dff5d999e987675181b4f1d82f81df10c0`.

Phase-D-Abschlusslauf (Python 3.14, 17.10.2026): **988 bestanden, 9
übersprungen, 5 Subtests bestanden, 0 fehlgeschlagen** in 343,28 Sekunden.
Der erweiterte Ziellauf ergab 61 bestandene Tests. Ruff, `py_compile` und
`git diff --check` waren erfolgreich. Phase D verändert keinen gemessenen
Massenschreibpfad; daher wird keine Performanceverbesserung behauptet.
