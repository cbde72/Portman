from dataclasses import replace
from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from portman_v10.application.contracts import AccountIdentifier, AccountInput, InstrumentInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.preview_codec import encode_preview
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app
from synthetic_pdf import make_text_pdf

BASE_URL = "http://127.0.0.1:8765"
HEADERS = {"Origin": BASE_URL, "Referer": BASE_URL + "/imports"}
PURCHASE_TEXT = """comdirect
Wertpapierkauf
Depotnummer: 123456
Stk. 0,125 Fonds DE0008474511
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Valuta 01.07.2026
DE00 0000 0000 0000 0000 01"""


class WebRollbackTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        cash = self.store.save_account(AccountInput("comdirect Giro", "cash", "checking", "comdirect", "EUR",
                                                    identifiers=(AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),)), None)
        self.store.save_account(AccountInput("comdirect Depot", "position", "depot", "comdirect", reference_account_id=cash.account_id,
                                             identifiers=(AccountIdentifier("depot_number", "comdirect", "123456"),)), None)
        self.store.save_instrument(InstrumentInput("Indexfonds", "ETF", isin="DE0008474511"), None)
        self.workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(self.workflow.close)
        self.client = create_app(self.workflow, profile="test-web").test_client()
        self.token = re.search(r'name="_csrf_token" value="([^"]+)"', self._get("/").get_data(as_text=True)).group(1)

    def _get(self, path):
        return self.client.get(path, base_url=BASE_URL)

    def _post(self, path, **data):
        return self.client.post(path, base_url=BASE_URL, headers=HEADERS, data={"_csrf_token": self.token, **data})

    def _count(self, table):
        connection = self.store.connect()
        try:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            connection.close()

    def _committed_import(self):
        response = self.client.post("/imports", data={"_csrf_token": self.token, "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "kauf.pdf")},
                                    content_type="multipart/form-data", base_url=BASE_URL, headers=HEADERS)
        job = self.workflow.wait(response.headers["Location"].rsplit("/", 1)[-1], timeout=15)
        preview = self.workflow.get_import_preview(job.import_id)
        item = replace(preview.items[0], review_status="complete_candidate", missing_fields=(), warnings=(), conflicts=())
        self.store.replace_import_preview_items(job.import_id, preview.revision, encode_preview(replace(preview, items=(item,))))
        self.assertEqual(self._post(f"/imports/{job.import_id}/review", candidate_id=item.candidate_id,
                                    candidate_revision=item.revision, decision="accept").status_code, 303)
        revision = self.workflow.get_import_preview(job.import_id).revision
        committed = self._post(f"/imports/{job.import_id}/commit", preview_revision=revision, request_id="web-commit-1")
        self.assertEqual(committed.status_code, 303, committed.get_data(as_text=True))
        self.assertEqual(self._count("events"), 1)
        return job

    def test_select_preview_execute_and_replay_rollback_from_import_list(self):
        job = self._committed_import()
        listing = self._get("/imports").get_data(as_text=True)
        self.assertIn(f'name="import_id" value="{job.import_id}"', listing)

        preview = self._post("/rollbacks/preview", import_id=job.import_id)
        html = preview.get_data(as_text=True)
        self.assertEqual(preview.status_code, 200, html)
        self.assertIn("Vorschau – noch nichts zurückgenommen", html)
        self.assertIn("<li>kauf.pdf</li>", html)
        self.assertIn("comdirect Giro", html)
        self.assertIn("-126.5", html)
        self.assertIn("Indexfonds", html)
        self.assertEqual(self._count("events"), 1)  # Vorschau ändert keine Buchungen

        fields = {name: re.search(rf'name="{name}" value="([^"]+)"', html).group(1) for name in ("plan_id", "expected_revision", "request_id")}
        executed = self._post("/rollbacks/execute", **fields)
        self.assertEqual(executed.status_code, 200, executed.get_data(as_text=True))
        self.assertIn("Zurückgenommen.", executed.get_data(as_text=True))
        self.assertEqual((self._count("events"), self._count("positions")), (0, 0))

        replayed = self._post("/rollbacks/execute", **fields)
        self.assertEqual(replayed.status_code, 200)
        self.assertIn("bereits ausgeführt", replayed.get_data(as_text=True))

        listing = self._get("/imports").get_data(as_text=True)
        self.assertIn("Zurückgenommen", listing)
        self.assertNotIn(f'name="import_id" value="{job.import_id}"', listing)

    def test_import_page_offers_rollback_preview_after_commit(self):
        job = self._committed_import()
        html = self._get(f"/jobs/{job.job_id}").get_data(as_text=True)
        self.assertIn("Diesen Import zurücknehmen (Vorschau)", html)
        preview = self._post("/rollbacks/preview", import_id=job.import_id, return_to=f"/jobs/{job.job_id}")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Rücknahme ausführen", preview.get_data(as_text=True))

    def test_invalid_selection_unconfirmed_all_and_missing_token_change_nothing(self):
        self._committed_import()
        empty = self._post("/rollbacks/preview")
        self.assertEqual(empty.status_code, 400)
        self.assertIn("mindestens einen übernommenen Import", empty.get_data(as_text=True))
        unconfirmed = self._post("/rollbacks/preview", all_imports="1")
        self.assertEqual(unconfirmed.status_code, 400)
        self.assertIn("Bestätigung anhaken", unconfirmed.get_data(as_text=True))
        confirmed = self._post("/rollbacks/preview", all_imports="1", confirm_all="1")
        self.assertEqual(confirmed.status_code, 200)
        self.assertIn("<li>kauf.pdf</li>", confirmed.get_data(as_text=True))
        forged = self.client.post("/rollbacks/execute", base_url=BASE_URL, headers=HEADERS, data={"plan_id": "x", "expected_revision": "1", "request_id": "r"})
        self.assertEqual(forged.status_code, 403)
        self.assertIn("Rücknahme abgelehnt", forged.get_data(as_text=True))
        stale = self._post("/rollbacks/execute", plan_id="unbekannt", expected_revision="1", request_id="web-x")
        self.assertIn(stale.status_code, {400, 404, 409})
        self.assertIn("Rücknahme nicht ausgeführt", stale.get_data(as_text=True))
        self.assertEqual(self._count("events"), 1)


if __name__ == "__main__":
    unittest.main()
