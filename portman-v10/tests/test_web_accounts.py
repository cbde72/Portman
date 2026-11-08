from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from portman_v10.application.contracts import AccountIdentifier, AccountInput, InstrumentInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app
from synthetic_pdf import make_text_pdf

BASE_URL = "http://127.0.0.1:8765"
SAME_ORIGIN = {"Origin": BASE_URL, "Referer": BASE_URL + "/accounts"}
PURCHASE_TEXT = """comdirect
Wertpapierkauf
Depotnummer: 123456
Stk. 0,125 Fonds DE0008474511
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Valuta 01.07.2026
DE00 0000 0000 0000 0000 01"""


class WebAccountTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data_dir = Path(temporary.name)
        self.store = SQLiteStore(self.data_dir / "v10.sqlite")
        self.store.migrate()
        self.workflow = ImportWorkflow(self.store, self.data_dir)
        self.addCleanup(self.workflow.close)
        self.client = create_app(self.workflow, branch="test-branch", commit="abc1234", profile="test-web").test_client()

    def _token(self):
        html = self.client.get("/accounts", base_url=BASE_URL).get_data(as_text=True)
        return re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)

    def _post(self, **fields):
        data = {"_csrf_token": self._token(), **fields}
        return self.client.post("/accounts", data=data, base_url=BASE_URL, headers=SAME_ORIGIN)

    def _accounts(self):
        return {account.name: account for account in self.store.list_accounts().items}

    def _create_linked_pair(self):
        cash = self._post(account_type="checking", name="comdirect Giro", institution="comdirect", currency="eur", iban="DE00 0000 0000 0000 0000 01")
        self.assertEqual(cash.status_code, 303, cash.get_data(as_text=True))
        giro = self._accounts()["comdirect Giro"]
        depot = self._post(account_type="depot", name="comdirect Depot", institution="comdirect", depot_number=" 123456 ", reference_account_id=giro.account_id)
        self.assertEqual(depot.status_code, 303, depot.get_data(as_text=True))
        return giro, self._accounts()["comdirect Depot"]

    def test_create_cash_account_and_linked_depot_persist_after_reload(self):
        giro, depot = self._create_linked_pair()
        self.assertEqual((giro.kind, giro.subtype, giro.currency, giro.institution), ("cash", "checking", "EUR", "comdirect"))
        self.assertEqual(giro.identifiers, (AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),))
        self.assertEqual((depot.kind, depot.subtype, depot.currency, depot.reference_account_id), ("position", "depot", None, giro.account_id))
        self.assertEqual(depot.identifiers, (AccountIdentifier("depot_number", "comdirect", "123456"),))

        html = self.client.get("/accounts", base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("IBAN DE00000000000000000001 (comdirect)", html)
        self.assertIn("Depotnummer 123456 (comdirect)", html)
        depot_row = re.search(r"<tr>\s*<td><a [^>]*>comdirect Depot</a></td>.*?</tr>", html, re.S).group(0)
        self.assertIn("<td>comdirect Giro</td>", depot_row)
        self.assertIn("test-web", html)

        # Neues Store-Objekt auf derselben Datei: Daten liegen tatsächlich im Profil.
        reopened = SQLiteStore(self.data_dir / "v10.sqlite")
        self.assertEqual({account.name for account in reopened.list_accounts().items}, {"comdirect Giro", "comdirect Depot"})

    def test_comdirect_purchase_preview_assigns_iban_and_depot_number_from_web_accounts(self):
        giro, depot = self._create_linked_pair()
        self.store.save_instrument(InstrumentInput("Indexfonds", "fund", isin="DE0008474511"), None)
        response = self.client.post(
            "/imports",
            data={"_csrf_token": self._token(), "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "kauf.pdf")},
            content_type="multipart/form-data", base_url=BASE_URL, headers=SAME_ORIGIN,
        )
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        job = self.workflow.wait(response.headers["Location"].rsplit("/", 1)[-1], timeout=15)
        preview = self.workflow.get_import_preview(job.import_id)
        movements = {movement.movement_type: movement for item in preview.items for movement in item.movements}
        self.assertEqual((movements["cash"].account_id, movements["cash"].account_assignment), (giro.account_id, "exact_identifier"))
        self.assertEqual((movements["quantity"].account_id, movements["quantity"].account_assignment), (depot.account_id, "exact_identifier"))
        html = self.client.get(response.headers["Location"], base_url=BASE_URL).get_data(as_text=True)
        self.assertNotIn("nicht zugeordnet", html)

    def test_edit_passes_revision_and_keeps_only_checked_identifiers(self):
        giro, _depot = self._create_linked_pair()
        extra = AccountIdentifier("account_number", "comdirect", "987")
        giro = self.store.save_account(AccountInput(giro.name, "cash", "checking", "comdirect", "EUR", account_id=giro.account_id,
                                                     identifiers=(*giro.identifiers, extra)), giro.revision)
        edit_html = self.client.get(f"/accounts/{giro.account_id}/edit", base_url=BASE_URL).get_data(as_text=True)
        self.assertIn(f'name="expected_revision" value="{giro.revision}"', edit_html)
        self.assertIn('name="keep_identifier" value="0" checked', edit_html)

        common = {"account_id": giro.account_id, "institution": "comdirect", "currency": "EUR", "iban": "DE00000000000000000001"}
        kept = self._post(account_type="settlement", name="Verrechnung", expected_revision=str(giro.revision), keep_identifier="0", **common)
        self.assertEqual(kept.status_code, 303, kept.get_data(as_text=True))
        updated = self.store.get_account(giro.account_id)
        self.assertEqual((updated.name, updated.subtype, updated.revision), ("Verrechnung", "settlement", giro.revision + 1))
        self.assertIn(extra, updated.identifiers)

        dropped = self._post(account_type="settlement", name="Verrechnung", expected_revision=str(updated.revision), **common)
        self.assertEqual(dropped.status_code, 303)
        self.assertEqual(self.store.get_account(giro.account_id).identifiers, (AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),))

    def test_stale_revision_is_rejected_without_change(self):
        giro, _depot = self._create_linked_pair()
        response = self._post(account_type="checking", account_id=giro.account_id, expected_revision=str(giro.revision - 1 or 99),
                              name="Überschrieben", institution="comdirect", currency="EUR")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Revision ist veraltet", response.get_data(as_text=True))
        self.assertEqual(self.store.get_account(giro.account_id), giro)

    def test_validation_errors_come_from_application_rules_and_store_nothing(self):
        giro, depot = self._create_linked_pair()
        cases = (
            ({"account_type": "depot", "name": "Depot 2", "institution": "comdirect", "reference_account_id": depot.account_id}, "Referenzkonto muss ein Geldkonto sein"),
            ({"account_type": "checking", "name": "Ohne Bank", "currency": "EUR", "iban": "DE11"}, "Bank als Kennungskontext"),
            ({"account_type": "checking", "name": "Ohne Währung", "institution": "x"}, "Währung"),
            ({"account_type": "bausparen", "name": "Unbekannt", "currency": "EUR"}, "gültige Kontoart"),
            ({"account_type": "crypto", "name": "Wallet", "institution": "x", "reference_account_id": depot.account_id}, "Referenzkonto muss ein Geldkonto sein"),
        )
        for fields, message in cases:
            with self.subTest(fields=fields):
                response = self._post(**fields)
                self.assertEqual(response.status_code, 400)
                html = response.get_data(as_text=True)
                self.assertIn(message, html)
                self.assertIn(f'value="{fields["name"]}"', html)
        self.assertEqual(set(self._accounts()), {"comdirect Giro", "comdirect Depot"})

    def test_account_post_requires_session_token_and_local_origin(self):
        self._token()
        missing = self.client.post("/accounts", data={"account_type": "checking", "name": "X", "currency": "EUR"}, base_url=BASE_URL, headers=SAME_ORIGIN)
        self.assertEqual(missing.status_code, 403)
        self.assertIn("Kontenpflege abgelehnt", missing.get_data(as_text=True))
        foreign = self.client.post("/accounts", data={"_csrf_token": self._token(), "account_type": "checking", "name": "X", "currency": "EUR"},
                                   base_url=BASE_URL, headers={"Origin": "http://evil.example"})
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual(self.store.list_accounts().items, ())

    def test_savings_fixed_term_and_crypto_accounts_can_be_created_and_edited(self):
        giro, _depot = self._create_linked_pair()
        for fields in (
            {"account_type": "savings", "name": "Tagesgeld", "institution": "Bank A", "currency": "EUR", "iban": "DE22 2222"},
            {"account_type": "fixed_term", "name": "Festgeld", "institution": "Bank A", "currency": "USD"},
            {"account_type": "crypto", "name": "Wallet", "institution": "Börse", "depot_number": "W-1", "reference_account_id": giro.account_id},
        ):
            with self.subTest(fields["account_type"]):
                self.assertEqual(self._post(**fields).status_code, 303)
        accounts = self._accounts()
        self.assertEqual((accounts["Tagesgeld"].kind, accounts["Tagesgeld"].subtype, accounts["Tagesgeld"].identifiers),
                         ("cash", "savings", (AccountIdentifier("iban", "bank a", "DE222222"),)))
        self.assertEqual((accounts["Festgeld"].subtype, accounts["Festgeld"].currency), ("fixed_term", "USD"))
        wallet = accounts["Wallet"]
        self.assertEqual((wallet.kind, wallet.subtype, wallet.currency, wallet.reference_account_id), ("position", "crypto", None, giro.account_id))
        self.assertEqual(wallet.identifiers, (AccountIdentifier("account_number", "börse", "W-1"),))

        html = self.client.get("/accounts", base_url=BASE_URL).get_data(as_text=True)
        self.assertNotIn("nicht in dieser Maske", html)
        for label in ("<td>Tagesgeld</td>", "<td>Festgeld</td>", "<td>Kryptokonto</td>"):
            self.assertIn(label, html)
        edit_html = self.client.get(f"/accounts/{wallet.account_id}/edit", base_url=BASE_URL).get_data(as_text=True)
        self.assertIn('<option value="crypto" selected>Kryptokonto</option>', edit_html)
        self.assertIn('name="depot_number" value="W-1"', edit_html)

        tagesgeld = accounts["Tagesgeld"]
        changed = self._post(account_type="fixed_term", account_id=tagesgeld.account_id, expected_revision=str(tagesgeld.revision),
                             name="Tagesgeld", institution="Bank A", currency="EUR", iban="DE222222")
        self.assertEqual(changed.status_code, 303)
        self.assertEqual(self.store.get_account(tagesgeld.account_id).subtype, "fixed_term")
        self.assertEqual(self.client.get("/accounts/unbekannt/edit", base_url=BASE_URL).status_code, 404)


if __name__ == "__main__":
    unittest.main()
