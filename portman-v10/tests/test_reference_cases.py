"""Fachliche Golden-Tests für synthetische V10-Referenzvorgänge."""
import unittest
from collections import defaultdict
from fractions import Fraction
from itertools import permutations

from portman_v10.domain.values import sum_decimal_text
from reference_cases import (
    BUY,
    DIVIDEND,
    INCOMPLETE_TRANSFER,
    OWN_TRANSFER,
    PARTIAL_LOT_SPLITS,
    REPEATING_COST_SPLIT,
    SCENARIOS,
    SECURITIES_TRANSFER,
    TAX_REFUND,
    TRANSFER_FEE,
    UNCLEAR_LOT_SPLIT,
    evidence_after_rollback,
    fact_after_rollback,
)


def deltas(scenario):
    grouped = defaultdict(list)
    for posting in scenario.postings:
        grouped[(posting.account, posting.asset)].append(posting.amount)
    return {key: sum_decimal_text(amounts) for key, amounts in grouped.items()}


class ReferenceCaseTests(unittest.TestCase):
    def test_purchase_posts_cash_and_security_once(self):
        self.assertEqual(deltas(BUY), {("demo-depot", "demo-fund"): "2", ("demo-giro", "EUR"): "-201"})
        self.assertEqual([detail.amount for detail in BUY.details], ["200", "1"])
        self.assertEqual(sum_decimal_text(["200", "1"]), "201")
        # Starting balances: 5 units / 1,000 EUR; closing balances: 7 / 799 EUR.
        self.assertEqual(sum_decimal_text(["5", deltas(BUY)[("demo-depot", "demo-fund")]]), "7")
        self.assertEqual(sum_decimal_text(["1000", deltas(BUY)[("demo-giro", "EUR")]]), "799")
        self.assertEqual([posting.effective_date.isoformat() for posting in BUY.postings], ["2025-11-10", "2025-11-12"])

    def test_dividend_net_only_is_cash_effect(self):
        self.assertEqual(deltas(DIVIDEND), {("demo-giro", "EUR"): "8"})
        details = {detail.kind: detail.amount for detail in DIVIDEND.details}
        self.assertEqual(details, {"gross": "10", "tax": "2"})
        self.assertEqual(sum_decimal_text([details["gross"], "-" + details["tax"]]), "8")
        self.assertEqual(sum_decimal_text(["100", deltas(DIVIDEND)[("demo-giro", "EUR")]]), "108")
        self.assertEqual(DIVIDEND.postings[0].effective_date.isoformat(), "2025-03-25")

    def test_own_transfer_conserves_total_without_external_flow(self):
        movement = deltas(OWN_TRANSFER)
        self.assertEqual(movement, {("demo-giro", "EUR"): "-100", ("demo-savings", "EUR"): "100"})
        self.assertEqual(sum_decimal_text(list(movement.values())), "0")
        self.assertEqual(sum_decimal_text(["1000", movement[("demo-giro", "EUR")]]), "900")
        self.assertEqual(sum_decimal_text(["250", movement[("demo-savings", "EUR")]]), "350")
        self.assertEqual([posting.effective_date.isoformat() for posting in OWN_TRANSFER.postings], ["2025-04-02", "2025-04-02"])

    def test_depot_transfer_preserves_each_acquisition_lot(self):
        movement = deltas(SECURITIES_TRANSFER)
        self.assertEqual(movement, {("demo-depot-a", "demo-fund"): "-2", ("demo-depot-b", "demo-fund"): "2"})
        self.assertEqual(sum_decimal_text(list(movement.values())), "0")
        self.assertEqual(sum_decimal_text(["8", movement[("demo-depot-a", "demo-fund")]]), "6")
        self.assertEqual(sum_decimal_text(["1", movement[("demo-depot-b", "demo-fund")]]), "3")
        self.assertTrue(all(posting.effective_date.isoformat() == "2025-09-15" for posting in SECURITIES_TRANSFER.postings))
        self.assertEqual([(lot.quantity, lot.acquired.isoformat(), lot.total_cost, lot.cost_currency) for lot in SECURITIES_TRANSFER.lots], [
            ("1", "2023-02-03", "40", "EUR"),
            ("1", "2024-06-17", "60", "EUR"),
        ])
        self.assertEqual([lot.acquired.isoformat() for lot in SECURITIES_TRANSFER.lots], ["2023-02-03", "2024-06-17"])

    def test_actual_transfer_fee_is_a_separate_posting(self):
        self.assertEqual(deltas(TRANSFER_FEE), {("demo-giro", "EUR"): "-1"})
        self.assertEqual(TRANSFER_FEE.related_event_id, OWN_TRANSFER.scenario_id)
        self.assertEqual(TRANSFER_FEE.details[0].amount, "1")
        combined_giro = sum_decimal_text([deltas(OWN_TRANSFER)[("demo-giro", "EUR")], deltas(TRANSFER_FEE)[("demo-giro", "EUR")]])
        self.assertEqual(combined_giro, "-101")
        self.assertEqual(sum_decimal_text([combined_giro, deltas(OWN_TRANSFER)[("demo-savings", "EUR")]]), "-1")
        self.assertEqual(sum_decimal_text(["1000", combined_giro]), "899")
        self.assertEqual(sum_decimal_text(["250", deltas(OWN_TRANSFER)[("demo-savings", "EUR")]]), "350")

    def test_missing_counterposting_and_costs_remain_unknown(self):
        self.assertFalse(INCOMPLETE_TRANSFER.complete)
        self.assertEqual(deltas(INCOMPLETE_TRANSFER), {("demo-depot-a", "demo-fund"): "-2"})
        self.assertNotIn(("demo-depot-b", "demo-fund"), deltas(INCOMPLETE_TRANSFER))
        lot = INCOMPLETE_TRANSFER.lots[0]
        self.assertIsNone(lot.acquired)
        self.assertIsNone(lot.total_cost)
        self.assertIsNone(lot.cost_currency)
        self.assertEqual(sum_decimal_text(["8", deltas(INCOMPLETE_TRANSFER)[("demo-depot-a", "demo-fund")]]), "6")
        self.assertEqual(sum_decimal_text(["1", "0"]), "1")  # Known Depot-B balance is unaffected; its transfer leg is unknown.

    def test_confirmation_order_and_source_rollback_keep_shared_and_manual_facts(self):
        confirmation = BUY.evidence[2]
        # Confirmation imports contribute evidence only, never another posting.
        self.assertEqual(len(BUY.postings), 2)
        evidence_order = lambda sources: frozenset(field for source in sources for field in source.fields)
        merged_fields = evidence_order(BUY.evidence)
        for import_order in permutations(BUY.evidence):
            self.assertEqual(evidence_order(import_order), merged_fields)
        self.assertIn("cash_posting", confirmation.fields)
        after_rollback = evidence_after_rollback(BUY, frozenset({"demo-import-trade", "demo-import-cash"}))
        self.assertIn("cash_posting", after_rollback)
        self.assertIn("user_note", after_rollback)
        self.assertNotIn("confirmation_only_note", evidence_after_rollback(BUY, frozenset({"demo-import-confirmation"})))
        self.assertEqual(fact_after_rollback(BUY, "account_assignment", frozenset({"demo-import-trade", "demo-import-cash", "demo-import-confirmation"})), "demo-giro-reviewed")

    def test_tax_refund_is_later_linked_cash_event(self):
        self.assertEqual(TAX_REFUND.related_event_id, DIVIDEND.scenario_id)
        self.assertEqual(deltas(TAX_REFUND), {("demo-giro", "EUR"): "0.4"})
        self.assertEqual(TAX_REFUND.postings[0].effective_date.isoformat(), "2025-08-04")
        self.assertEqual(deltas(DIVIDEND)[("demo-giro", "EUR")], "8")
        self.assertEqual(sum_decimal_text(["100", "8", deltas(TAX_REFUND)[("demo-giro", "EUR")]]), "108.4")

    def test_partial_lot_allocates_cost_proportionally_and_preserves_date_currency(self):
        split = PARTIAL_LOT_SPLITS[0]
        self.assertEqual(split.allocated_cost, Fraction("30.9"))
        self.assertEqual(split.remaining_cost, Fraction("72.1"))
        self.assertEqual(split.remaining_quantity, Fraction("7"))
        self.assertEqual(split.allocated_cost + split.remaining_cost, Fraction("103"))
        self.assertEqual(split.acquired.isoformat(), "2022-05-12")
        self.assertEqual(split.cost_currency, "EUR")

    def test_multiple_explicit_tranches_are_split_independently(self):
        self.assertEqual([split.tranche_id for split in PARTIAL_LOT_SPLITS], ["demo-tranche-103-eur", "demo-tranche-80-eur"])
        self.assertEqual(sum((Fraction(split.transferred_quantity) for split in PARTIAL_LOT_SPLITS), Fraction()), Fraction("5"))
        self.assertEqual(sum((split.allocated_cost for split in PARTIAL_LOT_SPLITS), Fraction()), Fraction("70.9"))
        self.assertEqual(sum((split.remaining_quantity for split in PARTIAL_LOT_SPLITS), Fraction()), Fraction("9"))
        self.assertEqual(sum((split.remaining_cost for split in PARTIAL_LOT_SPLITS), Fraction()), Fraction("112.1"))
        self.assertEqual(Fraction("70.9") + Fraction("112.1"), Fraction("183"))
        self.assertEqual([(split.acquired.isoformat(), split.cost_currency) for split in PARTIAL_LOT_SPLITS], [("2022-05-12", "EUR"), ("2023-08-09", "EUR")])

    def test_repeating_cost_share_is_exact_and_no_rounding_is_assumed(self):
        split = REPEATING_COST_SPLIT
        self.assertEqual(split.allocated_cost, Fraction(100, 3))
        self.assertEqual(split.remaining_cost, Fraction(200, 3))
        self.assertEqual(split.allocated_cost + split.remaining_cost, Fraction("100"))
        self.assertEqual(split.allocated_cost.denominator, 3)  # Not finitely representable as a decimal.

    def test_unclear_tranche_selection_keeps_cost_basis_unknown(self):
        self.assertFalse(UNCLEAR_LOT_SPLIT.tranche_selected)
        self.assertIsNone(UNCLEAR_LOT_SPLIT.allocated_cost)
        self.assertIsNone(UNCLEAR_LOT_SPLIT.remaining_cost)
        self.assertEqual(UNCLEAR_LOT_SPLIT.transferred_quantity, "3")

    def test_full_rollback_restores_original_lot_quantity_and_cost(self):
        for split in (*PARTIAL_LOT_SPLITS, REPEATING_COST_SPLIT):
            with self.subTest(tranche=split.tranche_id):
                restored_quantity = Fraction(split.transferred_quantity) + split.remaining_quantity
                restored_cost = split.allocated_cost + split.remaining_cost
                self.assertEqual(restored_quantity, Fraction(split.original_quantity))
                self.assertEqual(restored_cost, Fraction(split.original_cost))

    def test_all_primary_scenarios_have_synthetic_evidence(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario.scenario_id):
                self.assertTrue(scenario.scenario_id.startswith("synthetic-"))
                self.assertGreaterEqual(len(scenario.evidence), 2)
                self.assertTrue(all((source.import_id or source.manual) and source.fields for source in scenario.evidence))


if __name__ == "__main__":
    unittest.main()
