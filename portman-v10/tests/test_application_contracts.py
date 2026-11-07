import unittest
from datetime import date

from portman_v10.application.contracts import (
    AccountInput, ApplicationError, CommitImport, ConflictDecision, ErrorCode,
    ExecuteRollback, ExemptionOrderInput, ImportStart, InstrumentIdentifier, InstrumentInput, RollbackSelection,
    OpeningBalanceInput, Search, ExactValue,
)
from portman_v10.application.fake_service import FakeService


class ApplicationContractTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()

    def _ready_import(self, document_id="demo-buy-note"):
        job = self.service.start_import(ImportStart((document_id,)))
        return job, self.service.get_import_preview(job.import_id)

    def test_synthetic_read_contracts_cover_accounts_search_detail_documents_overview_tax(self):
        accounts = self.service.list_accounts()
        self.assertEqual(accounts.data_revision, self.service.data_revision)
        self.assertTrue(any(not account.active for account in accounts.items))
        page = self.service.search_transactions(Search(account_ids=("demo-old-depot",), limit=1))
        self.assertEqual([row.event_id for row in page.items], ["synthetic-inactive-001"])
        detail = self.service.get_transaction("synthetic-buy-001")
        self.assertEqual(detail.components[1][1], ExactValue("1"))
        document = self.service.get_document("demo-buy-note")
        self.assertTrue(document.content.startswith(b"synthetic"))
        overview = self.service.get_overview(date(2025, 12, 31))
        self.assertEqual(overview.data_revision, accounts.data_revision)
        self.assertEqual({line.account_id for line in overview.lines}, set(self.service.accounts))
        tax = self.service.get_tax_summary("demo-tax-subject", 2025)
        self.assertEqual(tax.consumptions[0].meaning, "cumulative")
        self.assertIsNone(tax.available)

    def test_fake_import_list_exposes_summary_and_stable_page_contract(self):
        job = self.service.start_import(ImportStart(("demo-buy-note",)))
        page = self.service.list_imports(limit=1)
        self.assertEqual(page.items[0].import_id, job.import_id)
        self.assertEqual(page.items[0].job_id, job.job_id)
        self.assertEqual(page.items[0].filenames, ("Beispielkauf.txt",))
        self.assertEqual(page.items[0].candidate_count, 1)
        self.assertFalse(page.items[0].committed)
        preview = self.service.get_import_preview(job.import_id)
        self.service.commit_import(CommitImport(job.import_id, preview.revision, "fake-import-list-commit"))
        committed = self.service.list_imports().items[0]
        self.assertTrue(committed.committed)
        self.assertEqual(committed.job_status, "completed")

    def test_save_account_and_order_use_expected_revision(self):
        saved = self.service.save_account(AccountInput("Neues Demo", "cash", "checking", currency="EUR"), None)
        self.assertEqual(saved.revision, 1)
        with self.assertRaises(ApplicationError) as raised:
            self.service.save_account(AccountInput("Neues Demo", "cash", "checking", currency="EUR"), 0)
        self.assertEqual(raised.exception.code, ErrorCode.STALE_REVISION)
        order = self.service.save_exemption_order(ExemptionOrderInput("demo-tax-subject", 2026, date(2026, 1, 1), None, ExactValue("1000"), None))
        self.assertEqual(order.revision, 1)

    def test_master_data_names_and_symbols_are_not_identity_keys_in_fake(self):
        first_account = self.service.save_account(AccountInput("Same label", "cash", "checking", currency="EUR"), None)
        second_account = self.service.save_account(AccountInput("Same label", "cash", "checking", currency="EUR"), None)
        self.assertNotEqual(first_account.account_id, second_account.account_id)
        same_ticker = (InstrumentIdentifier("provider", "ticker", "XETRA", "ABC"),)
        first_instrument = self.service.save_instrument(InstrumentInput("Same label", "equity", identifiers=same_ticker), None)
        second_instrument = self.service.save_instrument(InstrumentInput("Same label", "equity", identifiers=same_ticker), None)
        self.assertNotEqual(first_instrument.instrument_id, second_instrument.instrument_id)

    def test_fake_opening_is_explicit_start_data_and_keeps_unknown_cost_unknown(self):
        opening = OpeningBalanceInput("fake-opening", "demo-depot", date(2025, 1, 1), instrument_id="demo-fund", quantity=ExactValue("2"))
        saved = self.service.record_opening(opening)
        self.assertEqual(saved, self.service.get_opening("fake-opening"))
        self.assertEqual(saved.source_kind, "manual")
        self.assertEqual(saved.history_scope, "starting_balance")
        self.assertEqual(saved.cost_basis_status, "unknown")
        self.assertIsNone(saved.acquisition_cost)

    def test_invalid_search_and_missing_cash_currency_fail(self):
        with self.assertRaises(ValueError):
            Search(minimum=ExactValue("10"), maximum=ExactValue("2"))
        with self.assertRaises(ValueError):
            Search(limit=0)
        with self.assertRaises(ValueError):
            AccountInput("Ohne Währung", "cash", "checking")

    def test_preview_decision_revision_and_unknown_account(self):
        job, preview = self._ready_import()
        updated = self.service.resolve_import_item(job.import_id, ConflictDecision(preview.items[0].candidate_id, "accept"), preview.revision)
        self.assertEqual(updated.revision, preview.revision + 1)
        with self.assertRaises(ApplicationError) as raised:
            self.service.resolve_import_item(job.import_id, ConflictDecision(preview.items[0].candidate_id, "accept"), preview.revision)
        self.assertEqual(raised.exception.code, ErrorCode.STALE_REVISION)
        with self.assertRaises(ApplicationError) as raised:
            self.service.resolve_import_item(job.import_id, ConflictDecision(preview.items[0].candidate_id, "assign_account", account_id="missing"), updated.revision)
        self.assertEqual(raised.exception.code, ErrorCode.UNRESOLVED_ACCOUNT)

    def test_commit_replay_is_idempotent_and_changed_input_rejected(self):
        job, preview = self._ready_import()
        command = CommitImport(job.import_id, preview.revision, "request-commit-1")
        first = self.service.commit_import(command)
        replay = self.service.commit_import(command)
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.event_ids, replay.event_ids)
        second_job, _ = self._ready_import("demo-dividend-note")
        with self.assertRaises(ApplicationError) as raised:
            self.service.commit_import(CommitImport(second_job.import_id, 1, "request-commit-1"))
        self.assertEqual(raised.exception.code, ErrorCode.REQUEST_ID_REUSED)

    def test_stale_commit_and_rollback_preview_then_replay(self):
        job, preview = self._ready_import()
        with self.assertRaises(ApplicationError) as raised:
            self.service.commit_import(CommitImport(job.import_id, preview.revision + 1, "stale"))
        self.assertEqual(raised.exception.code, ErrorCode.STALE_REVISION)
        report = self.service.commit_import(CommitImport(job.import_id, preview.revision, "valid"))
        rollback = self.service.preview_rollback(RollbackSelection((job.import_id,)))
        command = ExecuteRollback(rollback.plan_id, rollback.revision, "rollback-1")
        first = self.service.execute_rollback(command)
        self.assertEqual(first.removed_import_ids, (job.import_id,))
        self.assertTrue(self.service.execute_rollback(command).replayed)
        with self.assertRaises(ApplicationError) as raised:
            self.service.execute_rollback(ExecuteRollback(rollback.plan_id, rollback.revision, "rollback-2"))
        self.assertEqual(raised.exception.code, ErrorCode.STALE_REVISION)
        self.assertEqual(report.event_ids, rollback.affected_event_ids)

    def test_reused_request_id_for_rollback_with_other_command_fails(self):
        job, preview = self._ready_import()
        self.service.commit_import(CommitImport(job.import_id, preview.revision, "commit"))
        plan = self.service.preview_rollback(RollbackSelection((job.import_id,)))
        command = ExecuteRollback(plan.plan_id, plan.revision, "same-request")
        self.service.execute_rollback(command)
        with self.assertRaises(ApplicationError) as raised:
            self.service.execute_rollback(ExecuteRollback("different-plan", plan.revision, "same-request"))
        self.assertEqual(raised.exception.code, ErrorCode.REQUEST_ID_REUSED)

    def test_stable_pages_and_cursor_invalidated_by_revision_change(self):
        first = self.service.search_transactions(Search(limit=2))
        self.assertEqual(len(first.items), 2)
        self.assertIsNotNone(first.next_cursor)
        second = self.service.search_transactions(Search(limit=2, cursor=first.next_cursor))
        self.assertEqual(len(second.items), 2)
        self.assertFalse(set(row.event_id for row in first.items) & set(row.event_id for row in second.items))
        self.service.save_account(AccountInput("Revision Change", "cash", "checking", currency="EUR"), None)
        with self.assertRaises(ApplicationError) as raised:
            self.service.search_transactions(Search(limit=2, cursor=first.next_cursor))
        self.assertEqual(raised.exception.code, ErrorCode.STALE_REVISION)

    def test_account_page_cursor_also_tracks_revision(self):
        first = self.service.list_accounts(limit=2)
        self.assertIsNotNone(first.next_cursor)
        self.service.save_account(AccountInput("Another", "cash", "checking", currency="EUR"), None)
        with self.assertRaises(ApplicationError) as raised:
            self.service.list_accounts(first.next_cursor, 2)
        self.assertEqual(raised.exception.code, ErrorCode.STALE_REVISION)

    def test_start_import_requires_known_documents_and_nonempty_input(self):
        with self.assertRaises(ValueError):
            ImportStart(())
        with self.assertRaises(ApplicationError) as raised:
            self.service.start_import(ImportStart(("missing-document",)))
        self.assertEqual(raised.exception.code, ErrorCode.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
