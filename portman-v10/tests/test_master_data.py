import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from portman_v10.application.contracts import (
    AccountIdentifier,
    AccountInput,
    ApplicationError,
    ErrorCode,
    InstrumentIdentifier,
    InstrumentInput,
    OpeningBalanceInput,
)
from portman_v10.domain.values import ExactValue
from portman_v10.infrastructure.sqlite_store import EventDocumentInput, EventInput, PersistedEventInput, PositionInput, SQLiteStore


class MasterDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="portman-v10-master-data-")
        self.database = Path(self.temporary.name) / "master-data.sqlite"
        self.store = SQLiteStore(self.database)
        self.store.migrate()

    def tearDown(self):
        self.temporary.cleanup()

    def _revision(self) -> int:
        connection = self.store.connect()
        try:
            return connection.execute("SELECT data_revision FROM app_state WHERE singleton=1").fetchone()[0]
        finally:
            connection.close()

    def _account(self, name: str, kind: str = "cash", subtype: str = "checking", currency: str | None = "EUR", **kwargs):
        return self.store.save_account(AccountInput(name, kind, subtype, currency=currency, **kwargs))

    def test_accounts_create_read_update_deactivate_and_reopen(self):
        giro = self._account("Demo Giro", identifiers=(AccountIdentifier("bank_account", "demo-bank", "acct-001"),))
        savings = self._account("Demo Tagesgeld", subtype="savings")
        depot = self._account("Demo Depot", "position", "depot", None, reference_account_id=giro.account_id)
        self.assertEqual(depot.reference_account_id, giro.account_id)
        self.assertEqual(giro.identifiers[0].value, "acct-001")
        changed = self.store.save_account(AccountInput("Giro Hauptkonto", "cash", "checking", institution="Demo Bank", currency="EUR", account_id=giro.account_id, identifiers=giro.identifiers), giro.revision)
        self.assertEqual(changed.revision, giro.revision + 1)
        with self.assertRaises(ApplicationError) as raised:
            self.store.save_account(AccountInput("Veralteter Name", "cash", "checking", currency="EUR", account_id=giro.account_id), giro.revision)
        self.assertEqual(raised.exception.code, ErrorCode.STALE_REVISION)
        inactive = self.store.deactivate_account(savings.account_id, savings.revision)
        self.assertFalse(inactive.active)
        reopened = SQLiteStore(self.database)
        self.assertEqual(reopened.get_account(giro.account_id), changed)
        self.assertFalse(reopened.get_account(savings.account_id).active)
        self.assertIn(savings.account_id, {item.account_id for item in reopened.list_accounts().items})

    def test_each_account_subtype_is_paired_with_its_agreed_kind(self):
        cash = ("checking", "savings", "fixed_term", "settlement")
        positions = ("depot", "crypto")
        for subtype in cash:
            with self.subTest(subtype=subtype):
                self.assertEqual(self._account(f"cash-{subtype}", subtype=subtype).currency, "EUR")
        for subtype in positions:
            with self.subTest(subtype=subtype):
                item = self._account(f"position-{subtype}", "position", subtype, None)
                self.assertIsNone(item.currency)
        for invalid in (
            lambda: AccountInput("Bad cash", "cash", "depot", currency="EUR"),
            lambda: AccountInput("Bad position", "position", "crypto", currency="EUR"),
            lambda: AccountInput("Missing cash currency", "cash", "checking"),
        ):
            with self.assertRaises(ValueError):
                invalid()

    def test_reference_account_must_exist_be_cash_and_remain_cash(self):
        with self.assertRaises(ApplicationError) as raised:
            self._account("Bad reference", "position", "depot", None, reference_account_id="missing")
        self.assertEqual(raised.exception.code, ErrorCode.NOT_FOUND)
        depot = self._account("Depot", "position", "depot", None)
        with self.assertRaises(ApplicationError) as raised:
            self._account("Wallet", "position", "crypto", None, reference_account_id=depot.account_id)
        self.assertEqual(raised.exception.code, ErrorCode.VALIDATION_ERROR)
        cash = self._account("Cash")
        self._account("Depot with reference", "position", "depot", None, reference_account_id=cash.account_id)
        with self.assertRaises(ApplicationError) as raised:
            self.store.save_account(AccountInput("Now a depot", "position", "depot", account_id=cash.account_id), cash.revision)
        self.assertEqual(raised.exception.code, ErrorCode.VALIDATION_ERROR)

    def test_account_identifiers_are_contextual_and_failed_update_is_atomic(self):
        first = self._account("Bank A", identifiers=(AccountIdentifier("account_number", "bank-a", "123"),))
        self._account("Bank B", identifiers=(AccountIdentifier("account_number", "bank-b", "123"),))
        before_revision = self._revision()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_account(AccountInput("Partial update", "cash", "checking", currency="EUR", account_id=first.account_id, identifiers=(
                AccountIdentifier("account_number", "bank-a", "duplicate"),
                AccountIdentifier("account_number", "bank-a", "duplicate"),
            )), first.revision)
        self.assertEqual(self.store.get_account(first.account_id).name, "Bank A")
        self.assertEqual(self.store.get_account(first.account_id).revision, first.revision)
        self.assertEqual(self._revision(), before_revision)

    def test_instrument_crud_keeps_exchange_context_and_never_matches_by_name(self):
        ticker_xetra = InstrumentIdentifier("provider-one", "ticker", "XETRA", "ABC")
        ticker_nyse = InstrumentIdentifier("provider-one", "ticker", "NYSE", "ABC")
        created = self.store.save_instrument(InstrumentInput("Example Corp", "equity", isin="DE0000000001", identifiers=(ticker_xetra, ticker_nyse)))
        same_name = self.store.save_instrument(InstrumentInput("Example Corp", "equity"))
        self.assertNotEqual(created.instrument_id, same_name.instrument_id)
        read = SQLiteStore(self.database).get_instrument(created.instrument_id)
        self.assertEqual(read.isin, "DE0000000001")
        self.assertEqual(set(read.identifiers), {ticker_xetra, ticker_nyse})
        changed = self.store.save_instrument(InstrumentInput("Example Corp Ltd.", "equity", isin="DE0000000001", instrument_id=created.instrument_id, identifiers=(ticker_xetra, ticker_nyse)), created.revision)
        self.assertEqual(changed.revision, created.revision + 1)
        with self.assertRaises(ApplicationError) as raised:
            self.store.save_instrument(InstrumentInput("Stale edit", "equity", instrument_id=created.instrument_id), created.revision)
        self.assertEqual(raised.exception.code, ErrorCode.STALE_REVISION)
        with self.assertRaises(ApplicationError) as raised:
            self.store.save_instrument(InstrumentInput("Unknown", "equity", instrument_id="unknown-id"))
        self.assertEqual(raised.exception.code, ErrorCode.NOT_FOUND)
        with self.assertRaises(ValueError):
            InstrumentIdentifier("provider", "ticker", "", "ABC")

    def test_context_migration_preserves_existing_instrument_identifiers(self):
        previous_migrations = Path(self.temporary.name) / "previous-migrations"
        previous_migrations.mkdir()
        source = self.store.migrations_dir
        for name in ("0001_initial.sql", "0002_opening_balances.sql"):
            (previous_migrations / name).write_bytes((source / name).read_bytes())
        prior_database = Path(self.temporary.name) / "upgrade.sqlite"
        prior_store = SQLiteStore(prior_database, previous_migrations)
        self.assertEqual(prior_store.migrate(), ("0001_initial.sql", "0002_opening_balances.sql"))
        connection = prior_store.connect()
        try:
            connection.execute("INSERT INTO accounts VALUES ('migration-cash', 'Migration cash', 'cash', 'checking', NULL, 'EUR', NULL, 1, 1)")
            connection.execute("INSERT INTO instruments VALUES ('migration-instrument', 'Imported identifier', 'equity', 1)")
            connection.execute("INSERT INTO instrument_identifiers(identifier_id, instrument_id, provider, identifier_type, value) VALUES ('migration-key', 'migration-instrument', 'legacy-provider', 'ticker', 'ABC')")
        finally:
            connection.close()
        upgraded = SQLiteStore(prior_database)
        self.assertEqual(upgraded.migrate(), ("0003_master_data_context.sql", "0004_import_workflow.sql", "0005_import_commit.sql"))
        migrated = upgraded.get_instrument("migration-instrument")
        self.assertEqual(migrated.identifiers, (InstrumentIdentifier("legacy-provider", "ticker", "unspecified", "ABC"),))

    def test_openings_round_trip_exact_money_known_and_unknown_costs(self):
        giro = self._account("Opening Giro")
        wallet = self._account("Opening Wallet", "position", "crypto", None)
        coin = self.store.save_instrument(InstrumentInput("Demo Coin", "cryptoasset", identifiers=(InstrumentIdentifier("demo-network", "contract", "ethereum-mainnet", "0xsynthetic"),)))
        money = OpeningBalanceInput("opening-money", giro.account_id, date(2025, 1, 1), currency="EUR", amount=ExactValue("-12345678901234567890.123456789012345678"))
        quantity = OpeningBalanceInput("opening-coin", wallet.account_id, date(2025, 1, 2), instrument_id=coin.instrument_id, quantity=ExactValue("0.000000000000000123"), acquired_on=date(2022, 5, 4), acquisition_cost=ExactValue("103.01"), cost_currency="EUR")
        unknown = OpeningBalanceInput("opening-unknown", wallet.account_id, date(2025, 1, 3), instrument_id=coin.instrument_id, quantity=ExactValue("2"))
        saved_money = self.store.record_opening(money)
        saved_quantity = self.store.record_opening(quantity)
        saved_unknown = self.store.record_opening(unknown)
        reopened = SQLiteStore(self.database)
        self.assertEqual(reopened.get_opening("opening-money"), saved_money)
        self.assertEqual(reopened.get_opening("opening-coin"), saved_quantity)
        self.assertEqual(reopened.get_opening("opening-unknown"), saved_unknown)
        self.assertEqual(saved_money.amount, money.amount)
        self.assertEqual(saved_quantity.quantity, quantity.quantity)
        self.assertEqual(saved_quantity.acquired_on, date(2022, 5, 4))
        self.assertEqual(saved_quantity.acquisition_cost, ExactValue("103.01"))
        self.assertEqual(saved_unknown.cost_basis_status, "unknown")
        self.assertIsNone(saved_unknown.acquisition_cost)
        self.assertEqual(saved_unknown.source_kind, "manual")
        self.assertEqual(saved_unknown.history_scope, "starting_balance")

    def test_opening_is_start_position_not_purchase_or_fabricated_counterpost(self):
        giro = self._account("Opening Cash")
        self.store.record_opening(OpeningBalanceInput("opening-cash", giro.account_id, date(2025, 1, 1), currency="EUR", amount=ExactValue("50")))
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT kind FROM events").fetchall()[0][0], "opening_balance")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events WHERE kind='buy'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM balance_index").fetchone()[0], 0)
        finally:
            connection.close()

    def test_opening_rejects_currency_account_and_instrument_mismatches(self):
        eur = self._account("EUR account")
        depot = self._account("Depot", "position", "depot", None)
        instrument = self.store.save_instrument(InstrumentInput("Share", "equity"))
        with self.assertRaises(ApplicationError) as raised:
            self.store.record_opening(OpeningBalanceInput("wrong-currency", eur.account_id, date(2025, 1, 1), currency="USD", amount=ExactValue("1")))
        self.assertEqual(raised.exception.code, ErrorCode.VALIDATION_ERROR)
        with self.assertRaises(ApplicationError) as raised:
            self.store.record_opening(OpeningBalanceInput("wrong-kind", eur.account_id, date(2025, 1, 1), instrument_id=instrument.instrument_id, quantity=ExactValue("1")))
        self.assertEqual(raised.exception.code, ErrorCode.VALIDATION_ERROR)
        with self.assertRaises(ApplicationError) as raised:
            self.store.record_opening(OpeningBalanceInput("missing-instrument", depot.account_id, date(2025, 1, 1), instrument_id="missing", quantity=ExactValue("1")))
        self.assertEqual(raised.exception.code, ErrorCode.NOT_FOUND)
        with self.assertRaises(ValueError):
            OpeningBalanceInput("zero-units", depot.account_id, date(2025, 1, 1), instrument_id=instrument.instrument_id, quantity=ExactValue("0"))

    def test_opening_increments_data_revision_and_leaves_existing_index_stale(self):
        cash = self._account("Indexed cash")
        current = self._revision()
        self.store.put_balance_index(account_id=cash.account_id, currency="EUR", instrument_id=None, as_of=date(2025, 1, 1), value=ExactValue("100"), rational_value=None, completeness="complete", data_revision=current)
        self.store.record_opening(OpeningBalanceInput("opening-indexed-cash", cash.account_id, date(2025, 1, 2), currency="EUR", amount=ExactValue("10")))
        self.assertEqual(self._revision(), current + 1)
        connection = self.store.connect()
        try:
            stored_index_revision = connection.execute("SELECT data_revision FROM balance_index").fetchone()[0]
            self.assertEqual(stored_index_revision, current)
            self.assertNotEqual(stored_index_revision, self._revision())
        finally:
            connection.close()

    def test_booking_change_advances_revision_and_does_not_relabel_old_index(self):
        cash = self._account("Booked cash")
        current = self._revision()
        self.store.put_balance_index(account_id=cash.account_id, currency="EUR", instrument_id=None, as_of=date(2025, 1, 1), value=ExactValue("100"), rational_value=None, completeness="complete", data_revision=current)
        effective = date(2025, 1, 2)
        record = PersistedEventInput(
            EventInput("manual-posting-event", "manual_adjustment", effective),
            (PositionInput("manual-posting", cash.account_id, effective, currency="EUR", amount=ExactValue("5")),),
        )
        self.store.save_event(record)
        self.assertEqual(self._revision(), current + 1)
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT data_revision FROM balance_index").fetchone()[0], current)
        finally:
            connection.close()

    def test_failed_update_rolls_back_data_and_revision(self):
        cash = self._account("Atomic account")
        before_revision = self._revision()
        effective = date(2025, 1, 1)
        invalid = PersistedEventInput(
            EventInput("invalid-posting-event", "manual_adjustment", effective),
            (PositionInput("invalid-posting", cash.account_id, effective, currency="EUR", amount=ExactValue("1")),),
            # A nonexistent document violates its FK after the event and position inserts.
            event_documents=(EventDocumentInput("missing-document", "primary"),),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_event(invalid)
        self.assertEqual(self._revision(), before_revision)
        self.assertIsNone(self.store.load_event("invalid-posting-event"))

    def test_history_is_retained_when_account_is_deactivated(self):
        cash = self._account("Historical account")
        self.store.record_opening(OpeningBalanceInput("historical-opening", cash.account_id, date(2025, 1, 1), currency="EUR", amount=ExactValue("9")))
        deactivated = self.store.deactivate_account(cash.account_id, cash.revision)
        self.assertFalse(deactivated.active)
        self.assertEqual(SQLiteStore(self.database).get_opening("historical-opening").account_id, cash.account_id)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.transaction() as connection:
                connection.execute("DELETE FROM accounts WHERE account_id=?", (cash.account_id,))


if __name__ == "__main__":
    unittest.main()
