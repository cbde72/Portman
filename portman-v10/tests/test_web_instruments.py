from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from portman_v10.application.contracts import InstrumentIdentifier, InstrumentInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app


class WebInstrumentListTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        self.store = SQLiteStore(data_dir / "v10.sqlite")
        self.store.migrate()
        self.workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(self.workflow.close)
        self.client = create_app(self.workflow, profile="test-web").test_client()

    def _page(self):
        response = self.client.get("/instruments", base_url="http://127.0.0.1:8765")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_empty_profile_says_so(self):
        html = self._page()
        self.assertIn("Noch keine Instrumente im Testprofil.", html)
        self.assertIn("test-web", html)

    def test_lists_all_instruments_across_pages_with_identifiers_and_unknown_marker(self):
        self.store.save_instrument(InstrumentInput("Indexfonds", "fund", isin="DE0008474511"), None)
        self.store.save_instrument(InstrumentInput("Nur WKN", "stock", wkn="A2H57N",
                                                   identifiers=(InstrumentIdentifier("xetra", "ticker", "XETR", "ABC"),)), None)
        for number in range(501):  # mehr als eine Seite der Anwendungsschnittstelle
            self.store.save_instrument(InstrumentInput(f"Zz Fonds {number:03d}", "fund"), None)
        html = self._page()
        self.assertIn("503 Instrumente im Testprofil.", html)
        self.assertIn("<td>DE0008474511</td>", html)
        self.assertIn("<td>A2H57N</td>", html)
        self.assertIn("xetra/ticker ABC (XETR)", html)
        self.assertIn("Zz Fonds 500", html)
        self.assertLess(html.index("Indexfonds"), html.index("Nur WKN"))

    def _post_type(self, instrument, asset_type, revision=None, token=None):
        html = self._page()
        token = token if token is not None else re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)
        return self.client.post(f"/instruments/{instrument.instrument_id}/asset-type", base_url="http://127.0.0.1:8765",
                                headers={"Origin": "http://127.0.0.1:8765"},
                                data={"_csrf_token": token, "asset_type": asset_type,
                                      "expected_revision": str(instrument.revision if revision is None else revision)})

    def test_asset_type_is_changed_via_selection_and_keeps_name_and_identifiers(self):
        extra = InstrumentIdentifier("xetra", "ticker", "XETR", "ABC")
        instrument = self.store.save_instrument(InstrumentInput("Fonds", "security", isin="LU1681041973", wkn="A2H57N", identifiers=(extra,)), None)
        html = self._page()
        self.assertIn('<option value="security" selected disabled>security (nicht festgelegt)</option>', html)
        self.assertIn('<option value="ETF">ETF</option>', html)
        for value, label in (("stock", "Aktie"), ("certificate", "Zertifikat"), ("etc", "ETC"), ("real_estate", "Immobilie"), ("commodity", "Rohstoff")):
            self.assertIn(f'<option value="{value}">{label}</option>', html)

        response = self._post_type(instrument, "ETF")
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        updated = self.store.get_instrument(instrument.instrument_id)
        self.assertEqual((updated.name, updated.asset_type, updated.isin, updated.wkn, updated.identifiers, updated.revision),
                         ("Fonds", "ETF", "LU1681041973", "A2H57N", (extra,), instrument.revision + 1))
        page = self.client.get(response.headers["Location"], base_url="http://127.0.0.1:8765").get_data(as_text=True)
        self.assertIn("Art gespeichert: Fonds", page)
        self.assertIn('<option value="ETF" selected>ETF</option>', page)
        self.assertNotIn("nicht festgelegt", page)
        self.assertEqual(self._post_type(updated, "commodity").status_code, 303)
        self.assertEqual(self.store.get_instrument(instrument.instrument_id).asset_type, "commodity")

    def test_invalid_type_stale_revision_and_missing_token_change_nothing(self):
        instrument = self.store.save_instrument(InstrumentInput("Aktie AG", "stock", isin="DE0007164600"), None)
        invalid = self._post_type(instrument, "Bausparvertrag")
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("Bitte eine Art aus der Auswahlliste wählen.", invalid.get_data(as_text=True))
        stale = self._post_type(instrument, "ETF", revision=instrument.revision + 3)
        self.assertEqual(stale.status_code, 409)
        self.assertIn("Instrument wurde inzwischen geändert", stale.get_data(as_text=True))
        denied = self._post_type(instrument, "ETF", token="falsch")
        self.assertEqual(denied.status_code, 403)
        self.assertIn("Instrumentpflege abgelehnt", denied.get_data(as_text=True))
        self.assertEqual(self.store.get_instrument(instrument.instrument_id), instrument)

    def _save(self, **fields):
        token = re.search(r'name="_csrf_token" value="([^"]+)"', self._page()).group(1)
        return self.client.post("/instruments", base_url="http://127.0.0.1:8765", headers={"Origin": "http://127.0.0.1:8765"},
                                data={"_csrf_token": token, **fields})

    def test_create_instrument_normalizes_codes_and_refuses_duplicates_and_missing_codes(self):
        created = self._save(name="SAP SE", asset_type="stock", isin=" de0007164600 ", wkn="716460")
        self.assertEqual(created.status_code, 303, created.get_data(as_text=True))
        instrument = self.store.list_instruments().items[0]
        self.assertEqual((instrument.name, instrument.asset_type, instrument.isin, instrument.wkn), ("SAP SE", "stock", "DE0007164600", "716460"))
        for fields, message in (
            ({"name": "Doppelt", "asset_type": "stock", "isin": "DE0007164600"}, "ISIN DE0007164600 gehört bereits zu einem anderen Instrument."),
            ({"name": "Ohne Kennung", "asset_type": "ETF"}, "ISIN oder WKN ist erforderlich"),
            ({"name": "Falsche Art", "asset_type": "security", "isin": "LU1681041973"}, "Bitte eine Art aus der Auswahlliste wählen."),
        ):
            with self.subTest(message=message):
                response = self._save(**fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.get_data(as_text=True))
                self.assertIn(f'value="{fields["name"]}"', response.get_data(as_text=True))
        self.assertEqual(len(self.store.list_instruments().items), 1)

    def test_edit_keeps_identifiers_and_unlisted_type_and_checks_revision(self):
        extra = InstrumentIdentifier("xetra", "ticker", "XETR", "AIS")
        instrument = self.store.save_instrument(InstrumentInput("Alt", "security", isin="LU1681041973", identifiers=(extra,)), None)
        edit_html = self.client.get(f"/instruments/{instrument.instrument_id}/edit", base_url="http://127.0.0.1:8765").get_data(as_text=True)
        self.assertIn(f'name="expected_revision" value="{instrument.revision}"', edit_html)
        self.assertIn('<option value="security" selected>security (nicht festgelegt)</option>', edit_html)
        self.assertIn("xetra/ticker AIS (XETR)", edit_html)
        common = {"instrument_id": instrument.instrument_id, "asset_type": "security", "isin": "LU1681041973", "wkn": "A2H57N"}
        self.assertEqual(self._save(name="Neu", expected_revision=str(instrument.revision), **common).status_code, 303)
        updated = self.store.get_instrument(instrument.instrument_id)
        self.assertEqual((updated.name, updated.asset_type, updated.wkn, updated.identifiers), ("Neu", "security", "A2H57N", (extra,)))
        stale = self._save(name="Nochmal", expected_revision=str(instrument.revision), **common)
        self.assertEqual(stale.status_code, 409)
        self.assertIn("Instrument wurde inzwischen geändert", stale.get_data(as_text=True))
        self.assertEqual(self.store.get_instrument(instrument.instrument_id).name, "Neu")

    def test_prefilled_create_from_import_returns_only_to_local_import_page(self):
        html = self.client.get("/instruments/new?name=Fonds&isin=LU1681041973&return_to=/jobs/abc",
                               base_url="http://127.0.0.1:8765").get_data(as_text=True)
        self.assertIn('id="instrument-name" name="name" value="Fonds"', html)
        self.assertIn('name="isin" value="LU1681041973"', html)
        self.assertIn('name="return_to" value="/jobs/abc"', html)
        back = self._save(name="Fonds", asset_type="ETF", isin="LU1681041973", return_to="/jobs/abc")
        self.assertEqual((back.status_code, back.headers["Location"]), (303, "/jobs/abc"))
        for target in ("https://evil.example/", "//evil.example/jobs/x", "/jobs/..\\x"):
            with self.subTest(target=target):
                self.assertIn('name="return_to" value=""', self.client.get(f"/instruments/new?return_to={target}", base_url="http://127.0.0.1:8765").get_data(as_text=True))
        open_redirect = self._save(name="Zwei", asset_type="ETF", wkn="ABC123", return_to="https://evil.example/")
        self.assertTrue(open_redirect.headers["Location"].startswith("/instruments?saved="))

    def test_import_preview_offers_prefilled_create_link_only_when_commit_does_not_create(self):
        from io import BytesIO
        from synthetic_pdf import make_text_pdf
        token = re.search(r'name="_csrf_token" value="([^"]+)"', self._page()).group(1)
        text = "comdirect\nWertpapierkauf\nDepotnummer: 123456\nStk. 0,125 Fonds DE0008474511\nZu Ihren Lasten EUR 126,50\nValuta 01.07.2026"
        response = self.client.post("/imports", data={"_csrf_token": token, "pdf": (BytesIO(make_text_pdf(text)), "kauf.pdf")},
                                    content_type="multipart/form-data", base_url="http://127.0.0.1:8765", headers={"Origin": "http://127.0.0.1:8765"})
        job_id = response.headers["Location"].rsplit("/", 1)[-1]
        job = self.workflow.wait(job_id, timeout=15)
        resolution = {item.instrument_resolution for item in self.workflow.get_import_preview(job.import_id).items}
        html = self.client.get(response.headers["Location"], base_url="http://127.0.0.1:8765").get_data(as_text=True)
        if resolution == {"will_create"}:
            self.assertNotIn('class="create-instrument"', html)
        else:
            self.assertIn('class="create-instrument"', html)
            self.assertIn("isin=DE0008474511", html)
            self.assertIn(f"return_to=/jobs/{job_id}", html)

    def test_navigation_links_instruments_from_other_pages(self):
        for path in ("/", "/accounts"):
            with self.subTest(path=path):
                self.assertIn('href="/instruments"', self.client.get(path, base_url="http://127.0.0.1:8765").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
