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
| ING Steuererstattung | `ing/steuererstattung/current-v1`; `test_ing_tax_refund_has_positive_economic_direction` | positive Erstattung, Komponenten vollständig |
| Manipulierte Steuerkorrektur | `test_ing_tax_refund_rejects_inconsistent_components` | abweichende Summe wird nicht importiert |

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
