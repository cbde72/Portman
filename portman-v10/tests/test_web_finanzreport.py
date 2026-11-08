from dataclasses import replace
from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from portman_v10.application.contracts import AccountIdentifier, AccountInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.preview_codec import encode_preview
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app
from synthetic_pdf import make_text_pdf

BASE_URL = "http://127.0.0.1:8765"
REPORT = ("comdirect\nFinanzreport Nr. 124 per 01.07.2026\nGirokonto DE00000000000000000001\nAlter Saldo 01.06.2026 100,00\n"
          "01.07.2026 01.07.2026 Habenzinsen +10,00\n01.07.2026 01.07.2026 Kartenzahlung -2,50\nNeuer Saldo 01.07.2026 107,50")
OVERLAP = "comdirect\nFinanzreport Nr. 125 per 01.07.2026\nGirokonto DE00000000000000000001\n01.07.2026 01.07.2026 Habenzinsen +10,00"
UNMATCHED_BUTTON = 'value="accept_unmatched"'


class WebFinanzreportTests(unittest.TestCase):
    """accept_unmatched laut Schnittstelle.md: ausdrückliche Entscheidung je Zeile, danach ausdrücklich übernehmen."""

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        self.cash = self.store.save_account(AccountInput("Giro", "cash", "checking", "comdirect", "EUR",
                                                         identifiers=(AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),)), None)
        self.workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(self.workflow.close)
        self.client = create_app(self.workflow, profile="test-web").test_client()
        home = self.client.get("/", base_url=BASE_URL).get_data(as_text=True)
        self.token = re.search(r'name="_csrf_token" value="([^"]+)"', home).group(1)
        self.headers = {"Origin": BASE_URL, "Referer": f"{BASE_URL}/jobs/x"}

    def _upload(self, text, name):
        response = self.client.post("/imports", data={"_csrf_token": self.token, "pdf": (BytesIO(make_text_pdf(text)), name)},
                                    content_type="multipart/form-data", base_url=BASE_URL, headers={"Origin": BASE_URL})
        job_url = response.headers["Location"]
        import_id = self.workflow.wait(job_url.rsplit("/", 1)[-1], timeout=15).import_id
        return job_url, import_id

    def _page(self, job_url):
        return self.client.get(job_url, base_url=BASE_URL).get_data(as_text=True)

    def _review(self, import_id, item, decision):
        return self.client.post(f"/imports/{import_id}/review", base_url=BASE_URL, headers=self.headers, data={
            "_csrf_token": self.token, "candidate_id": item.candidate_id, "candidate_revision": item.revision, "decision": decision})

    def _commit(self, import_id, request_id):
        revision = self.workflow.get_import_preview(import_id).revision
        return self.client.post(f"/imports/{import_id}/commit", base_url=BASE_URL, headers=self.headers,
                                data={"_csrf_token": self.token, "preview_revision": revision, "request_id": request_id})

    def _events(self):
        connection = self.store.connect()
        try:
            return connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            connection.close()

    def test_rows_offer_explicit_unmatched_acceptance_and_commit_stays_locked_until_decided(self):
        job_url, import_id = self._upload(REPORT, "finanzreport.pdf")
        items = self.workflow.get_import_preview(import_id).items
        self.assertEqual(len(items), 2)
        html = self._page(job_url)
        self.assertEqual(html.count(UNMATCHED_BUTTON), 2)
        self.assertIn("Referenzlose Reportzeile", html)
        self.assertIn("Alle 2 referenzlosen Reportzeilen als neue Buchung übernehmen", html)
        self.assertIn("disabled>Übernehmen</button>", html)

        self.assertEqual(self._review(import_id, items[0], "accept_unmatched").status_code, 303)
        html = self._page(job_url)
        self.assertIn("Prüfentscheidung gespeichert: Als neue Buchung ohne Bankreferenz vorgemerkt", html)
        self.assertEqual(html.count(UNMATCHED_BUTTON), 1, "entschiedene Zeile bietet den Knopf nicht erneut an")
        self.assertIn("disabled>Übernehmen</button>", html, "zweite Zeile ist noch offen")

        self.assertEqual(self._review(import_id, items[1], "accept_unmatched").status_code, 303)
        html = self._page(job_url)
        self.assertIn("offene Konflikte/Zuordnungen 0", html)
        self.assertNotIn("Prüfen: Bankreferenz fehlt", html)
        self.assertIn('<button type="submit" >Übernehmen</button>', html)
        self.assertEqual(self._events(), 0, "Entscheidung bucht noch nichts")

        committed = self._commit(import_id, "web-finanzreport")
        self.assertEqual(committed.status_code, 303, committed.get_data(as_text=True))
        self.assertEqual(self._events(), 2)

    def test_bulk_unmatched_marks_all_rows_then_commit_books_them(self):
        job_url, import_id = self._upload(REPORT, "finanzreport.pdf")
        revision = self.workflow.get_import_preview(import_id).revision
        response = self.client.post(f"/imports/{import_id}/accept-all", base_url=BASE_URL, headers=self.headers,
                                    data={"_csrf_token": self.token, "preview_revision": revision, "mode": "unmatched"})
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        self.assertIn("accepted=2", response.headers["Location"])
        decisions = {value.decision.decision for value in self.workflow.get_import_preview(import_id).decisions}
        self.assertEqual(decisions, {"accept_unmatched"})
        self.assertEqual(self._events(), 0)
        self.assertEqual(self._commit(import_id, "web-finanzreport-bulk").status_code, 303)
        self.assertEqual(self._events(), 2)

    def test_overlapping_row_is_not_offered_as_new_but_can_be_linked(self):
        _, first = self._upload(REPORT, "finanzreport.pdf")
        for item in self.workflow.get_import_preview(first).items:
            self.assertEqual(self._review(first, item, "accept_unmatched").status_code, 303)
        self.assertEqual(self._commit(first, "web-first").status_code, 303)

        job_url, second = self._upload(OVERLAP, "finanzreport-125.pdf")
        item = self.workflow.get_import_preview(second).items[0]
        self.assertTrue(item.conflicts)
        html = self._page(job_url)
        self.assertNotIn(UNMATCHED_BUTTON, html)
        self.assertIn("nicht neu buchen, sondern zuordnen oder ignorieren", html)
        self.assertNotIn("referenzlosen Reportzeilen als neue Buchung", html)

        refused = self._review(second, item, "accept_unmatched")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("nicht neu buchen", refused.get_data(as_text=True))

        self.assertEqual(self._review(second, item, "link").status_code, 303)
        html = self._page(job_url)
        self.assertIn("offene Konflikte/Zuordnungen 0", html)
        self.assertEqual(self._commit(second, "web-link").status_code, 303)
        self.assertEqual(self._events(), 2, "zugeordnete Wiederholung erzeugt keinen neuen Vorgang")

    def test_row_without_cash_account_explains_why_it_cannot_be_booked(self):
        job_url, import_id = self._upload(REPORT, "finanzreport.pdf")
        preview = self.workflow.get_import_preview(import_id)
        unassigned = replace(preview.items[0], movements=(replace(preview.items[0].movements[0], account_id=None, account_assignment="unresolved"),))
        self.store.replace_import_preview_items(import_id, preview.revision, encode_preview(replace(preview, items=(unassigned, preview.items[1]))))
        html = self._page(job_url)
        self.assertEqual(html.count(UNMATCHED_BUTTON), 1)
        self.assertIn("Geldkonto nicht zugeordnet", html)
        self.assertIn("Alle 1 referenzlosen Reportzeilen", html)
        refused = self._review(import_id, self.workflow.get_import_preview(import_id).items[0], "accept_unmatched")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(self.workflow.get_import_preview(import_id).decisions, ())

    def test_unmatched_is_refused_for_other_document_types(self):
        job_url, import_id = self._upload(REPORT, "finanzreport.pdf")
        preview = self.workflow.get_import_preview(import_id)
        other = replace(preview.items[0], plugin_id="user.comdirect-ertraege", handler_id="wertpapierkauf", kind="BUY")
        self.store.replace_import_preview_items(import_id, preview.revision, encode_preview(replace(preview, items=(other,))))
        self.assertNotIn(UNMATCHED_BUTTON, self._page(job_url))
        refused = self._review(import_id, self.workflow.get_import_preview(import_id).items[0], "accept_unmatched")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("nur für referenzlose Finanzreportzeilen", refused.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
