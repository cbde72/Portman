import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from portman_v10.domain.rational import RationalAmount
from portman_v10.domain.values import ExactValue
from portman_v10.infrastructure.sqlite_store import (
    AcquisitionLotInput, ComponentInput, ContributionInput, DocumentInput, EventDocumentInput,
    EventInput, PersistedEventInput, PositionInput, SQLiteStore,
    LotAllocationInput,
)
from reference_cases import SCENARIOS


class SQLiteStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="portman-v10-sqlite-")
        self.database = Path(self.temporary.name) / "test.sqlite"
        self.store = SQLiteStore(self.database)
        self.assertEqual(self.store.migrate(), ("0001_initial.sql", "0002_opening_balances.sql", "0003_master_data_context.sql", "0004_import_workflow.sql", "0005_import_commit.sql", "0006_rollback_plans.sql"))
        self.assertEqual(self.store.migrate(), ())
        self._seed_reference_entities()

    def tearDown(self):
        self.temporary.cleanup()

    def _seed_reference_entities(self):
        connection = self.store.connect()
        try:
            for account_id, kind, subtype, currency in (
                ("demo-giro", "cash", "checking", "EUR"),
                ("demo-savings", "cash", "savings", "EUR"),
                ("demo-depot", "position", "depot", None),
                ("demo-depot-a", "position", "depot", None),
                ("demo-depot-b", "position", "depot", None),
            ):
                connection.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (account_id, account_id, kind, subtype, "Synthetische Bank", currency, None, 1, 1))
            connection.execute("INSERT INTO instruments VALUES ('demo-fund', 'Beispielfonds', 'fund', 1)")
            connection.execute("INSERT INTO tax_subjects VALUES ('demo-owner', 'synthetic-context', 'Synthetische Person')")
            for account_id in ("demo-giro", "demo-savings", "demo-depot", "demo-depot-a", "demo-depot-b"):
                connection.execute("INSERT INTO tax_subject_accounts VALUES ('demo-owner', ?)", (account_id,))
            connection.commit()
        finally:
            connection.close()

    def _persist_scenario(self, scenario):
        now = datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()
        evidence_imports = {item.import_id for item in scenario.evidence if item.import_id}
        connection = self.store.connect()
        try:
            for import_id in evidence_imports:
                connection.execute("INSERT OR IGNORE INTO imports(import_id, started_at, status, preview_revision) VALUES (?, ?, 'committed', 1)", (import_id, now))
            connection.commit()
        finally:
            connection.close()
        digest = hashlib.sha256(scenario.scenario_id.encode()).hexdigest()
        document = DocumentInput(f"doc-{scenario.scenario_id}", digest, f"{scenario.scenario_id}.txt", f"docs/{scenario.scenario_id}.txt", "text/plain", now)
        positions = tuple(
            PositionInput(
                f"{scenario.scenario_id}-position-{index}", posting.account,
                posting.effective_date,
                currency=posting.asset if posting.asset in {"EUR", "USD"} else None,
                amount=ExactValue(posting.amount) if posting.asset in {"EUR", "USD"} else None,
                instrument_id=posting.asset if posting.asset not in {"EUR", "USD"} else None,
                quantity=ExactValue(posting.amount) if posting.asset not in {"EUR", "USD"} else None,
            )
            for index, posting in enumerate(scenario.postings)
        )
        source_indices = [index for index, posting in enumerate(scenario.postings) if posting.amount.startswith("-") and posting.asset not in {"EUR", "USD"}]
        destination_account = next((posting.account for posting in scenario.postings if posting.amount.startswith("+") and posting.asset not in {"EUR", "USD"}), None)
        lots = tuple(AcquisitionLotInput(lot.lot_id, scenario.postings[source_indices[index]].account, "demo-fund", ExactValue(lot.quantity), lot.acquired, ExactValue(lot.total_cost) if lot.total_cost is not None else None, lot.cost_currency) for index, lot in enumerate(scenario.lots))
        allocations = tuple(LotAllocationInput(positions[source_indices[index]].position_id, lot.lot_id, scenario.postings[source_indices[index]].account, destination_account, ExactValue(lot.quantity), RationalAmount.from_decimal(lot.total_cost) if lot.total_cost is not None else None) for index, lot in enumerate(scenario.lots))
        components = tuple(ComponentInput(f"{scenario.scenario_id}-component-{index}", detail.kind, ExactValue(detail.amount) if detail.amount is not None else None, detail.currency) for index, detail in enumerate(scenario.details))
        contributions = []
        for evidence_index, evidence in enumerate(scenario.evidence):
            if evidence.import_id:
                for field_name in sorted(evidence.fields):
                    contributions.append(ContributionInput(f"{scenario.scenario_id}-source-{evidence_index}-{field_name}", "import", "event", scenario.scenario_id, field_name, "set", now, import_id=evidence.import_id, document_id=document.document_id, value_text=dict(evidence.values).get(field_name)))
            if evidence.manual:
                for field_name in sorted(evidence.fields):
                    contributions.append(ContributionInput(f"{scenario.scenario_id}-manual-{field_name}", "manual", "event", scenario.scenario_id, field_name, "set", now, document_id=document.document_id, value_text=dict(evidence.values).get(field_name)))
        event = EventInput(scenario.scenario_id, scenario.kind, positions[0].effective_date, "complete" if scenario.complete else "incomplete", f"Synthetischer Vorgang {scenario.scenario_id}")
        self.store.save_event(PersistedEventInput(event, positions, components, (document,), (EventDocumentInput(document.document_id, "primary"),), tuple(contributions), lots, allocations))

    def test_persist_and_reopen_all_four_synthetic_reference_events(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario.scenario_id):
                self._persist_scenario(scenario)
                reopened = SQLiteStore(self.database).load_event(scenario.scenario_id)
                self.assertIsNotNone(reopened)
                self.assertEqual(len(reopened.positions), len(scenario.postings))
                self.assertEqual(len(reopened.components), len(scenario.details))
                self.assertEqual(reopened.document_ids, (f"doc-{scenario.scenario_id}",))
                self.assertGreater(len(reopened.contributions), 0)
                self.assertEqual(len(reopened.lots), len(scenario.lots))
                self.assertEqual(len(reopened.lot_allocations), len(scenario.lots))
                for stored_lot, lot in zip(reopened.lots, scenario.lots, strict=True):
                    self.assertEqual(stored_lot.lot_id, lot.lot_id)
                    self.assertEqual(stored_lot.quantity, ExactValue(lot.quantity))
                    self.assertEqual(stored_lot.acquired_on, lot.acquired)
                    self.assertEqual(stored_lot.original_cost, ExactValue(lot.total_cost) if lot.total_cost is not None else None)
                    self.assertEqual(stored_lot.cost_currency, lot.cost_currency)
                for stored_allocation, lot in zip(reopened.lot_allocations, scenario.lots, strict=True):
                    self.assertEqual(stored_allocation.cost, RationalAmount.from_decimal(lot.total_cost) if lot.total_cost is not None else None)
                for stored, posting in zip(reopened.positions, scenario.postings, strict=True):
                    self.assertEqual((stored.account_id, stored.effective_date), (posting.account, posting.effective_date))
                    self.assertEqual(stored.amount or stored.quantity, ExactValue(posting.amount))

    def test_exact_decimal_round_trip_and_rational_index_value(self):
        self._persist_scenario(SCENARIOS[0])
        stored = SQLiteStore(self.database).load_event(SCENARIOS[0].scenario_id)
        self.assertEqual(stored.positions[0].quantity, ExactValue("2"))
        connection = self.store.connect()
        try:
            revision = connection.execute("SELECT data_revision FROM app_state WHERE singleton=1").fetchone()[0]
        finally:
            connection.close()
        self.store.put_balance_index(account_id="demo-depot", currency=None, instrument_id="demo-fund", as_of=SCENARIOS[0].postings[0].effective_date, value=None, rational_value=RationalAmount(100, 3), completeness="complete", data_revision=revision)
        with self.assertRaises(ValueError):
            self.store.put_balance_index(account_id="demo-depot", currency=None, instrument_id="demo-fund", as_of=SCENARIOS[0].postings[0].effective_date, value=None, rational_value=RationalAmount(100, 3), completeness="complete", data_revision=revision + 1)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute(
                "SELECT value_rational FROM balance_index WHERE account_id='demo-depot' AND asset_key='INSTRUMENT:demo-fund' AND as_of=?",
                (SCENARIOS[0].postings[0].effective_date.isoformat(),),
            ).fetchone()[0], "100/3")
        finally:
            connection.close()

    def test_large_money_crypto_precision_and_rational_lot_share_round_trip(self):
        now = datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()
        amount = ExactValue("123456789012345678901234567890.000000000000000001")
        quantity = ExactValue("0.000000000000000001")
        document = DocumentInput("exact-doc", hashlib.sha256(b"exact").hexdigest(), "exact.txt", "docs/exact.txt", "text/plain", now)
        record = PersistedEventInput(
            EventInput("exact-event", "synthetic", SCENARIOS[0].postings[0].effective_date),
            (
                PositionInput("exact-money", "demo-giro", SCENARIOS[0].postings[0].effective_date, currency="EUR", amount=amount),
                PositionInput("exact-crypto", "demo-depot", SCENARIOS[0].postings[0].effective_date, instrument_id="demo-fund", quantity=quantity),
            ),
            documents=(document,),
        )
        self.store.save_event(record)
        stored = SQLiteStore(self.database).load_event("exact-event")
        positions_by_id = {position.position_id: position for position in stored.positions}
        self.assertEqual(positions_by_id["exact-money"].amount, amount)
        self.assertEqual(positions_by_id["exact-crypto"].quantity, quantity)

    def test_invalid_double_kind_position_and_broken_foreign_key_are_rejected(self):
        bad_position = PositionInput("bad-position", "demo-giro", SCENARIOS[0].postings[0].effective_date, currency="EUR", amount=ExactValue("1"), instrument_id="demo-fund", quantity=ExactValue("1"))
        record = PersistedEventInput(EventInput("bad-event", "bad", bad_position.effective_date), (bad_position,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_event(record)
        broken_reference = PositionInput("broken-position", "missing-account", SCENARIOS[0].postings[0].effective_date, currency="EUR", amount=ExactValue("1"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_event(PersistedEventInput(EventInput("broken-event", "bad", broken_reference.effective_date), (broken_reference,)))

    def test_database_rejects_wrong_account_kind_update_bad_component_numbers_and_lot_source(self):
        scenario = SCENARIOS[3]
        self._persist_scenario(scenario)
        connection = self.store.connect()
        try:
            position_id = f"{scenario.scenario_id}-position-0"
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE positions SET currency='EUR', amount_decimal='1', instrument_id=NULL, quantity_decimal=NULL WHERE position_id=?", (position_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO event_components(component_id, event_id, component_type, amount_decimal, currency) VALUES ('invalid-number-component', ?, 'fee', 'not-a-number', 'EUR')", (scenario.scenario_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO lot_allocations(event_id, position_id, lot_id, source_account_id, destination_account_id, quantity_decimal, cost_rational) VALUES (?, ?, 'demo-lot-1', 'demo-depot-b', 'demo-depot-a', '1', '40/1')", (scenario.scenario_id, position_id))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE lot_allocations SET source_account_id='demo-depot-b' WHERE event_id=? AND position_id=?", (scenario.scenario_id, position_id))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO acquisition_lots(lot_id, instrument_id, account_id, original_quantity_decimal) VALUES ('negative-lot', 'demo-fund', 'demo-depot-a', '-1')")
        finally:
            connection.close()

    def test_failed_component_rolls_back_preceding_event_and_positions_atomically(self):
        posting = SCENARIOS[0].postings[0]
        position = PositionInput("atomic-position", posting.account, posting.effective_date, instrument_id=posting.asset, quantity=ExactValue(posting.amount))
        bad_component = ComponentInput("atomic-component", "unsupported-type", ExactValue("1"), "EUR")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_event(PersistedEventInput(EventInput("atomic-event", "buy", posting.effective_date), (position,), (bad_component,)))
        self.assertIsNone(SQLiteStore(self.database).load_event("atomic-event"))

    def test_document_restriction_preserves_shared_event_provenance(self):
        scenario = SCENARIOS[0]
        self._persist_scenario(scenario)
        connection = self.store.connect()
        try:
            connection.execute("INSERT INTO events(event_id, kind, booking_date, completeness, revision) VALUES ('second-evidence-event', 'confirmation', '2025-11-12', 'complete', 1)")
            connection.execute("INSERT INTO event_documents(event_id, document_id, source_role) VALUES ('second-evidence-event', ?, 'confirmation')", (f"doc-{scenario.scenario_id}",))
        finally:
            connection.close()
        connection = self.store.connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM documents WHERE document_id = ?", (f"doc-{scenario.scenario_id}",))
        finally:
            connection.close()
        self.assertIsNotNone(self.store.load_event(scenario.scenario_id))
        self.assertIsNotNone(self.store.load_event("second-evidence-event"))

    def test_identifier_values_are_contextual_not_globally_unique(self):
        connection = self.store.connect()
        try:
            connection.execute("INSERT INTO account_identifiers(identifier_id, account_id, identifier_type, context, value) VALUES ('id-a', 'demo-giro', 'bank_ref', 'year-2025', '123')")
            connection.execute("INSERT INTO account_identifiers(identifier_id, account_id, identifier_type, context, value) VALUES ('id-b', 'demo-savings', 'bank_ref', 'year-2025', '123')")
        finally:
            connection.close()

    def test_migration_failure_rolls_back_ddl_and_migration_record(self):
        migration_dir = Path(self.temporary.name) / "broken-migrations"
        migration_dir.mkdir()
        (migration_dir / "0001_broken.sql").write_text("CREATE TABLE should_rollback(value TEXT);\nINSERT INTO missing_table VALUES ('failure');\n", encoding="utf-8")
        broken_path = Path(self.temporary.name) / "broken.sqlite"
        broken_store = SQLiteStore(broken_path, migration_dir)
        with self.assertRaises(sqlite3.OperationalError):
            broken_store.migrate()
        connection = broken_store.connect()
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("should_rollback", tables)
            self.assertNotIn("schema_migrations", tables)
        finally:
            connection.close()

    def test_schema_has_durable_operation_key_and_shared_revision_index(self):
        connection = self.store.connect()
        try:
            operation_columns = {row["name"] for row in connection.execute("PRAGMA table_info(operations)")}
            self.assertTrue({"request_id", "input_hash", "result_text", "completed_at"}.issubset(operation_columns))
            operation_pk = [row["name"] for row in sorted(connection.execute("PRAGMA table_info(operations)"), key=lambda row: row["pk"]) if row["pk"]]
            self.assertEqual(operation_pk, ["request_id"])
            index_columns = {row["name"] for row in connection.execute("PRAGMA table_info(balance_index)")}
            self.assertTrue({"data_revision", "value_decimal", "value_rational", "as_of"}.issubset(index_columns))
            contribution_columns = {row["name"] for row in connection.execute("PRAGMA table_info(import_contributions)")}
            self.assertTrue({"import_id", "document_id", "source_kind", "field_name", "previous_value_text", "value_text"}.issubset(contribution_columns))
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)
        finally:
            connection.close()

    def test_fixed_term_and_exemption_history_and_consumption_sources_persist(self):
        scenario = SCENARIOS[0]
        self._persist_scenario(scenario)
        connection = self.store.connect()
        try:
            connection.execute("INSERT INTO accounts VALUES ('demo-term', 'Demo Festgeld', 'cash', 'fixed_term', 'Synthetische Bank', 'EUR', NULL, 1, 1)")
            connection.execute("INSERT INTO fixed_term_details VALUES ('demo-term', '2025-01-01', '2026-01-01', '3.25')")
            connection.execute("INSERT INTO exemption_orders VALUES ('order-1', 'demo-owner', 2025, '2025-01-01', NULL, '1000', 1)")
            connection.execute("INSERT INTO exemption_orders VALUES ('order-2', 'demo-owner', 2025, '2025-06-01', NULL, '1200', 2)")
            connection.execute("INSERT INTO tax_consumption_statements VALUES ('consumption-1', 'demo-owner', 2025, 'cumulative', '2.4', '2025-12-31', 'complete')")
            connection.execute("INSERT INTO tax_consumption_sources VALUES ('consumption-1', ?, NULL, 'primary')", (f"doc-{scenario.scenario_id}",))
            connection.commit()
            self.assertEqual(connection.execute("SELECT agreed_rate_decimal FROM fixed_term_details WHERE account_id='demo-term'").fetchone()[0], "3.25")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exemption_orders WHERE tax_subject_id='demo-owner' AND tax_year=2025").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tax_consumption_sources WHERE statement_id='consumption-1'").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
