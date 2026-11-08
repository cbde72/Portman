from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app

BASE_URL = "http://127.0.0.1:8765"


class WebLayoutAndScriptPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        store = SQLiteStore(data_dir / "v10.sqlite")
        store.migrate()
        workflow = ImportWorkflow(store, data_dir)
        self.addCleanup(workflow.close)
        self.client = create_app(workflow, profile="test-web").test_client()

    def _home(self):
        response = self.client.get("/", base_url=BASE_URL)
        html = response.get_data(as_text=True)
        nonce = re.search(r"script-src 'self' 'nonce-([A-Za-z0-9_-]+)'", response.headers["Content-Security-Policy"]).group(1)
        return html, nonce

    def test_upload_script_carries_the_nonce_the_csp_allows(self):
        html, nonce = self._home()
        scripts = re.findall(r"<script([^>]*)>", html)
        self.assertEqual(scripts, [f' nonce="{nonce}"'] * 2, "jedes Skript braucht die Nonce, sonst blockiert die CSP es")
        self.assertIn("getElementById('upload-status')", html)
        self.assertIn("a[data-more-for]", html)
        self.assertNotIn("'unsafe-inline'", self.client.get("/", base_url=BASE_URL).headers["Content-Security-Policy"].split("style-src")[0])

    def test_enhancement_markers_point_at_existing_elements(self):
        templates = Path(__file__).resolve().parents[1] / "src" / "portman_v10" / "web" / "templates"
        for name, table_id in (("account.html", "booking-list"), ("imports.html", "import-list")):
            with self.subTest(template=name):
                source = (templates / name).read_text(encoding="utf-8")
                self.assertIn(f'<table id="{table_id}">', source)
                self.assertIn(f'id="next-page" data-more-for="{table_id}" href=', source)
        rollback = (templates / "rollback.html").read_text(encoding="utf-8")
        self.assertRegex(rollback, r"execute_rollback_route'\) \}\}\" data-confirm=\"Rücknahme jetzt ausführen\?")

    def test_nonce_changes_with_every_response(self):
        self.assertNotEqual(self._home()[1], self._home()[1])

    def test_layout_marks_the_current_page_in_the_navigation(self):
        for path, label in (("/", "Import"), ("/imports", "Importe"), ("/overview", "Übersicht"),
                            ("/accounts", "Konten &amp; Depots"), ("/instruments", "Instrumente")):
            with self.subTest(path=path):
                html = self.client.get(path, base_url=BASE_URL).get_data(as_text=True)
                self.assertEqual(re.findall(r'aria-current="page">([^<]+)<', html), [label])
                self.assertIn("Datenbankprofil: test-web", html)


if __name__ == "__main__":
    unittest.main()
