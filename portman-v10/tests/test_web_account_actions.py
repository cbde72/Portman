from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from portman_v10.application.contracts import AccountInput, InstrumentInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app

BASE_URL = "http://127.0.0.1:8765"
HEADERS = {"Origin": BASE_URL}


class WebAccountActionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        self.giro = self.store.save_account(AccountInput("Giro", "cash", "checking", "Bank", "EUR"), None)
        self.depot = self.store.save_account(AccountInput("Depot", "position", "depot", "Bank", reference_account_id=self.giro.account_id), None)
        self.fund = self.store.save_instrument(InstrumentInput("Indexfonds", "ETF", isin="DE0008474511"), None)
        workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(workflow.close)
        self.client = create_app(workflow, profile="test-web").test_client()

    def _page(self, account):
        return self.client.get(f"/accounts/{account.account_id}", base_url=BASE_URL).get_data(as_text=True)

    def _form_value(self, html, name):
        return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)

    def _post(self, account, action, **fields):
        html = self._page(account)
        data = {"_csrf_token": self._form_value(html, "_csrf_token"), **fields}
        if action == "openings" and "opening_id" not in fields:
            data["opening_id"] = self._form_value(html, "opening_id")
        return self.client.post(f"/accounts/{account.account_id}/{action}", base_url=BASE_URL, headers=HEADERS, data=data)

    def _positions(self):
        connection = self.store.connect()
        try:
            return connection.execute("SELECT account_id, currency, amount_decimal, instrument_id, quantity_decimal FROM positions ORDER BY account_id").fetchall()
        finally:
            connection.close()

    def test_cash_opening_uses_account_currency_and_exact_comma_amount(self):
        response = self._post(self.giro, "openings", effective_date="2025-12-31", amount="1234,56", note="Startsaldo")
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        page = self.client.get(response.headers["Location"], base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Eröffnungsbestand gespeichert: 2025-12-31 · 1234.56 EUR", page)
        rows = self._positions()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][1], rows[0][3]), ("EUR", None))
        opening_id = re.search(r"opened=([0-9a-f]+)", response.headers["Location"]).group(1)
        self.assertEqual(self.store.get_opening(opening_id).amount.text, "1234.56")

    def test_resubmitting_the_same_opening_form_creates_no_second_starting_balance(self):
        opening_id = self._form_value(self._page(self.giro), "opening_id")
        first = self._post(self.giro, "openings", opening_id=opening_id, effective_date="2025-12-31", amount="10")
        again = self._post(self.giro, "openings", opening_id=opening_id, effective_date="2025-12-31", amount="10")
        self.assertEqual((first.status_code, again.status_code), (303, 303))
        self.assertEqual(len(self._positions()), 1)
        self.assertNotEqual(self._form_value(self._page(self.giro), "opening_id"), opening_id)

    def test_quantity_opening_keeps_unknown_cost_unknown(self):
        response = self._post(self.depot, "openings", effective_date="2025-12-31", instrument_id=self.fund.instrument_id,
                              quantity="0,125", acquired_on="", acquisition_cost="", cost_currency="EUR")
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        opening_id = re.search(r"opened=([0-9a-f]+)", response.headers["Location"]).group(1)
        opening = self.store.get_opening(opening_id)
        self.assertEqual((opening.quantity.text, opening.instrument_id, opening.acquisition_cost, opening.cost_currency, opening.cost_basis_status),
                         ("0.125", self.fund.instrument_id, None, None, "unknown"))
        self.assertIn("Anschaffungskosten unbekannt", self.client.get(response.headers["Location"], base_url=BASE_URL).get_data(as_text=True))

    def test_invalid_openings_are_explained_on_the_account_page_and_store_nothing(self):
        for account, fields, message in (
            (self.giro, {"effective_date": "2025-12-31", "amount": "1.234,56"}, "ohne Tausendertrennzeichen"),
            (self.giro, {"effective_date": "2025-12-31", "amount": "abc"}, "kein gültiger Dezimalwert"),
            (self.giro, {"effective_date": "", "amount": "1"}, "Stichtag ist erforderlich"),
            (self.depot, {"effective_date": "2025-12-31", "instrument_id": self.fund.instrument_id, "quantity": "-1"}, "Eröffnungsmenge muss positiv sein"),
            (self.depot, {"effective_date": "2025-12-31", "instrument_id": "fehlt", "quantity": "1"}, "Eröffnungsinstrument nicht gefunden"),
        ):
            with self.subTest(message=message):
                response = self._post(account, "openings", **fields)
                html = response.get_data(as_text=True)
                self.assertIn(response.status_code, {400, 404})
                self.assertIn('id="action-error"', html)
                self.assertIn(message, html)
        self.assertEqual(self._positions(), [])

    def test_deactivate_requires_confirmation_and_current_revision(self):
        unconfirmed = self._post(self.giro, "deactivate", expected_revision=str(self.giro.revision))
        self.assertEqual(unconfirmed.status_code, 400)
        self.assertIn("Bestätigung anhaken", unconfirmed.get_data(as_text=True))
        stale = self._post(self.giro, "deactivate", expected_revision=str(self.giro.revision + 5), confirm="1")
        self.assertEqual(stale.status_code, 409)
        self.assertTrue(self.store.get_account(self.giro.account_id).active)

        done = self._post(self.giro, "deactivate", expected_revision=str(self.giro.revision), confirm="1")
        self.assertEqual(done.status_code, 303)
        self.assertFalse(self.store.get_account(self.giro.account_id).active)
        page = self.client.get(done.headers["Location"], base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Konto deaktiviert.", page)
        self.assertNotIn('id="deactivate-form"', page)
        self.assertIn("deaktiviert", self.client.get("/accounts", base_url=BASE_URL).get_data(as_text=True))

    def test_account_actions_require_session_token(self):
        for action, data in (("deactivate", {"expected_revision": "1", "confirm": "1"}), ("openings", {"effective_date": "2025-01-01", "amount": "1"})):
            with self.subTest(action=action):
                response = self.client.post(f"/accounts/{self.giro.account_id}/{action}", base_url=BASE_URL, headers=HEADERS, data=data)
                self.assertEqual(response.status_code, 403)
        self.assertTrue(self.store.get_account(self.giro.account_id).active)
        self.assertEqual(self._positions(), [])


if __name__ == "__main__":
    unittest.main()
