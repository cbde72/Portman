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
