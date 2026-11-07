from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from portman_v10.application.contracts import ApplicationError, ErrorCode, ImportPage, ImportSummary
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app
from synthetic_pdf import make_text_pdf

BASE_URL = "http://127.0.0.1:8765"


class WebImportListTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        self.workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(self.workflow.close)
        self.client = create_app(self.workflow, profile="test-web").test_client()

    def _get(self, path):
        return self.client.get(path, base_url=BASE_URL)

    def _upload(self, filename, text):
        html = self._get("/").get_data(as_text=True)
        token = re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)
        response = self.client.post("/imports", data={"_csrf_token": token, "pdf": (BytesIO(make_text_pdf(text)), filename)},
                                    content_type="multipart/form-data", base_url=BASE_URL, headers={"Origin": BASE_URL})
        self.assertEqual(response.status_code, 303)
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        self.workflow.wait(job_id, timeout=15)
        return job_id

    def test_empty_profile(self):
        html = self._get("/imports").get_data(as_text=True)
        self.assertIn("Noch keine Importe im Testprofil.", html)
        self.assertIn('href="/imports"', self._get("/").get_data(as_text=True))

    def test_real_uploads_are_listed_newest_first_with_link_to_import_page(self):
        first = self._upload("erster.pdf", "comdirect\nWertpapierkauf\nStk. 1 Fonds DE0008474511")
        second = self._upload("<i>zweiter.pdf", "Unbekanntes Dokument")
        html = self._get("/imports").get_data(as_text=True)
        self.assertIn(f'href="/jobs/{first}"', html)
        self.assertIn(f'href="/jobs/{second}"', html)
        self.assertIn("&lt;i&gt;zweiter.pdf", html)
        self.assertNotIn("<i>zweiter", html)
        self.assertLess(html.index(f"/jobs/{second}"), html.index(f"/jobs/{first}"))
        self.assertIn("Vorschau, nicht übernommen", html)

    def test_status_labels_rolled_back_marker_and_paging(self):
        rows = (
            ImportSummary("i2", "j2", "2026-11-07T10:00:00.123+00:00", "rolled_back", "completed", ("b.pdf",), 1, True),
            ImportSummary("i1", "j1", "2026-11-06T09:00:00+00:00", "committed", "completed", ("a.pdf",), 2, True),
        )
        pages = [ImportPage(rows, "5:100", 5), ImportPage((), None, 5)]
        calls = []

        def fake_list(_store, cursor=None, limit=100):
            calls.append((cursor, limit))
            return pages.pop(0)
        with patch.object(SQLiteStore, "list_imports", fake_list):
            html = self._get("/imports").get_data(as_text=True)
            self._get("/imports?cursor=5:100")
        self.assertIn("2026-11-07 10:00:00", html)
        self.assertIn("Zurückgenommen", html)
        self.assertIn('class="rolled-back"', html)
        self.assertIn("Übernommen", html)
        self.assertIn('href="/imports?cursor=5:100"', html)
        self.assertEqual(calls, [(None, 100), ("5:100", 100)])

    def test_stale_cursor_asks_to_reload(self):
        stale = ApplicationError(ErrorCode.STALE_REVISION, "Importliste wurde geändert")
        with patch.object(SQLiteStore, "list_imports", side_effect=stale):
            response = self._get("/imports?cursor=1:100")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Importliste hat sich geändert; bitte von vorn laden.", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
