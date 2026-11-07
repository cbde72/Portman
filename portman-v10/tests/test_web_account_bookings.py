from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from portman_v10.application.contracts import (
    AccountInput, ApplicationError, ErrorCode, TransactionPage, TransactionSummary,
)
from portman_v10.domain.values import ExactValue
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app

BASE_URL = "http://127.0.0.1:8765"


class WebAccountBookingTests(unittest.TestCase):
    """Kontoseite nutzt ausschließlich search_transactions(Search) aus dem Anwendungsvertrag."""

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        self.giro = self.store.save_account(AccountInput("Giro", "cash", "checking", "comdirect", "EUR"), None)
        self.store.deactivate_account(self.giro.account_id, self.giro.revision)
        workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(workflow.close)
        self.client = create_app(workflow, profile="test-web").test_client()
        self.queries = []

    def _search_returning(self, *pages):
        pages = list(pages)

        def search(_store, query):
            self.queries.append(query)
            result = pages.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return patch.object(SQLiteStore, "search_transactions", search, create=True)

    def _get(self, path):
        return self.client.get(path, base_url=BASE_URL)

    def test_account_names_in_list_link_to_account_page(self):
        html = self._get("/accounts").get_data(as_text=True)
        self.assertIn(f'<a href="/accounts/{self.giro.account_id}">Giro</a>', html)
        self.assertEqual(self._get("/accounts/unbekannt").status_code, 404)

    def test_bookings_of_deactivated_account_are_shown_with_exact_amounts_and_next_page(self):
        first = TransactionPage((
            TransactionSummary("e2", date(2026, 7, 2), "DIVIDEND", "Ausschüttung <b>Fonds</b>", (self.giro.account_id,), amount=ExactValue("17.61"), currency="EUR"),
            TransactionSummary("e1", date(2026, 7, 1), "BUY", "Kauf Fonds", (self.giro.account_id,), amount=None, currency="EUR"),
        ), "7:100", 7)
        second = TransactionPage((TransactionSummary("e0", date(2025, 1, 1), "BUY", "Alt", amount=ExactValue("-1.005"), currency="EUR"),), None, 7)
        with self._search_returning(first, second):
            html = self._get(f"/accounts/{self.giro.account_id}").get_data(as_text=True)
            self.assertIn("deaktiviert", html)
            self.assertIn("17.61 EUR", html)
            self.assertIn("Unbekannt EUR", html)
            self.assertIn("Ausschüttung &lt;b&gt;Fonds&lt;/b&gt;", html)
            self.assertLess(html.index("2026-07-02"), html.index("2026-07-01"))
            self.assertIn(f'href="/accounts/{self.giro.account_id}?cursor=7:100"', html)
            more = self._get(f"/accounts/{self.giro.account_id}?cursor=7:100").get_data(as_text=True)
        self.assertIn("-1.005 EUR", more)
        self.assertNotIn('id="next-page"', more)
        self.assertIn("zum Anfang", more)
        self.assertEqual([query.account_ids for query in self.queries], [(self.giro.account_id,)] * 2)
        self.assertTrue(all(query.include_inactive_accounts for query in self.queries))
        self.assertEqual([query.cursor for query in self.queries], [None, "7:100"])

    def test_empty_account_and_stale_cursor(self):
        stale = ApplicationError(ErrorCode.STALE_REVISION, "Suche neu beginnen")
        with self._search_returning(TransactionPage((), None, 1), stale):
            self.assertIn("Keine Buchungen für dieses Konto.", self._get(f"/accounts/{self.giro.account_id}").get_data(as_text=True))
            response = self._get(f"/accounts/{self.giro.account_id}?cursor=1:100")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Buchungen haben sich geändert; bitte von vorn laden.", response.get_data(as_text=True))

    @unittest.skipIf(hasattr(SQLiteStore, "search_transactions"), "Datenkern bietet die Buchungssuche bereits an")
    def test_missing_core_search_is_explained_instead_of_failing(self):
        response = self._get(f"/accounts/{self.giro.account_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Buchungssuche (V10-27) ist im Datenkern noch nicht umgesetzt", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
