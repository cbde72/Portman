from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from portman_v10.application.contracts import AccountInput, BalanceLine, InstrumentInput, Overview
from portman_v10.domain.values import ExactValue
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.overview import shift
from portman_v10.web.server import create_app

BASE_URL = "http://127.0.0.1:8765"


class OverviewNavigationTests(unittest.TestCase):
    def test_day_week_and_year_steps(self):
        self.assertEqual(shift(date(2024, 2, 28), "day", 1), date(2024, 2, 29))
        self.assertEqual(shift(date(2024, 3, 1), "day", -1), date(2024, 2, 29))
        self.assertEqual(shift(date(2026, 1, 1), "week", -1), date(2025, 12, 25))
        self.assertEqual(shift(date(2024, 2, 29), "year", 1), date(2025, 2, 28))
        self.assertEqual(shift(date(2025, 2, 28), "year", -1, anchor_day=29), date(2024, 2, 29))

    def test_month_steps_keep_anchor_day_over_short_months(self):
        current, anchor, visited = date(2024, 1, 31), 31, []
        for _ in range(3):
            current = shift(current, "month", 1, anchor)
            visited.append(current)
        self.assertEqual(visited, [date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30)])
        self.assertEqual(shift(date(2026, 1, 15), "month", -1), date(2025, 12, 15))


class WebOverviewTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        self.giro = self.store.save_account(AccountInput("Giro", "cash", "checking", "Bank", "EUR"), None)
        self.depot = self.store.save_account(AccountInput("Altdepot", "position", "depot", "Bank"), None)
        self.store.deactivate_account(self.depot.account_id, self.depot.revision)
        self.fund = self.store.save_instrument(InstrumentInput("Indexfonds", "ETF", isin="DE0008474511"), None)
        workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(workflow.close)
        self.client = create_app(workflow, profile="test-web").test_client()

    def _get(self, path):
        return self.client.get(path, base_url=BASE_URL)

    def test_lines_show_exact_values_names_and_unknown_is_not_zero(self):
        calls = []

        def overview(_store, as_of, account_ids=()):
            calls.append((as_of, account_ids))
            return Overview(as_of, 42, (
                BalanceLine(self.giro.account_id, ExactValue("1234.56"), "EUR", None, "complete"),
                BalanceLine(self.depot.account_id, ExactValue("0.125"), None, self.fund.instrument_id, "incomplete"),
                BalanceLine(self.depot.account_id, None, None, self.fund.instrument_id, "unknown"),
            ))
        with patch.object(SQLiteStore, "get_overview", overview, create=True):
            html = self._get("/overview?date=2024-01-31&step=month").get_data(as_text=True)
        self.assertEqual(calls, [(date(2024, 1, 31), ())])
        self.assertIn("Stände am 2024-01-31", html)
        self.assertIn("1234.56", html)
        self.assertIn("0.125 Stück", html)
        self.assertIn("Indexfonds", html)
        self.assertIn(">Unbekannt</td>", html)
        self.assertNotIn(">0</td>", html)
        self.assertIn('class="check-point">unvollständig', html)
        self.assertIn("deaktiviert", html)
        self.assertLess(html.index("Giro"), html.index("Altdepot"))
        self.assertIn("Datenrevision 42", html)
        self.assertIn('href="/overview?date=2024-02-29&amp;step=month&amp;anchor=31"', html)
        self.assertIn('href="/overview?date=2023-12-31&amp;step=month&amp;anchor=31"', html)

    def test_anchor_survives_short_month_navigation(self):
        html = self._get("/overview?date=2024-02-29&step=month&anchor=31").get_data(as_text=True)
        self.assertIn('href="/overview?date=2024-03-31&amp;step=month&amp;anchor=31"', html)

    def test_invalid_date_falls_back_to_today_with_message(self):
        html = self._get("/overview?date=2024-13-01").get_data(as_text=True)
        self.assertIn("Ungültiges Datum", html)
        self.assertIn(f"Stände am {date.today().isoformat()}", html)

    @unittest.skipIf(hasattr(SQLiteStore, "get_overview"), "Datenkern bietet die Stichtagsübersicht bereits an")
    def test_missing_core_overview_is_explained(self):
        response = self._get("/overview")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Bestandsindex (V10-19 bis V10-21) ist im Datenkern noch nicht umgesetzt", response.get_data(as_text=True))
        self.assertIn('href="/overview"', self._get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
