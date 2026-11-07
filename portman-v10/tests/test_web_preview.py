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


PURCHASE_TEXT = """comdirect
Wertpapierkauf
Depotnummer: 123456
Stk. 0,125 Fonds DE0008474511
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Valuta 01.07.2026
DE00 0000 0000 0000 0000 01"""


class ImportWebPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name)
        self.store = SQLiteStore(self.data_dir / "v10.sqlite")
        self.store.migrate()
        self.cash = self.store.save_account(AccountInput(
            "comdirect Giro", "cash", "checking", "comdirect", "EUR",
            identifiers=(AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),),
        ), None)
        self.depot = self.store.save_account(AccountInput(
            "comdirect Depot", "position", "depot", "comdirect",
            identifiers=(AccountIdentifier("depot_number", "comdirect", "123456"),),
        ), None)
        self.instrument = self.store.save_instrument(InstrumentInput("Indexfonds", "fund", isin="DE0008474511"), None)
        self.workflow = ImportWorkflow(self.store, self.data_dir)
        self.addCleanup(self.workflow.close)
        self.app = create_app(self.workflow, branch="codex/portman-v10-foundation", commit="abc1234", profile="test-web")
        self.client = self.app.test_client()
        self.base_url = "http://127.0.0.1:8765"

    def _submit(self, content=None, filename="purchase.pdf"):
        content = content if content is not None else make_text_pdf(PURCHASE_TEXT)
        response = self.client.post(
            "/imports",
            data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(content), filename)},
            content_type="multipart/form-data",
            base_url=self.base_url,
            headers={"Origin": "http://127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/"},
        )
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        job_url = response.headers["Location"]
        job_id = job_url.rsplit("/", 1)[-1]
        job = self.workflow.wait(job_id, timeout=15)
        return job, job_url

    def _csrf_token(self):
        html = self.client.get("/", base_url=self.base_url).get_data(as_text=True)
        match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_upload_job_preview_original_and_no_booking(self):
        source = make_text_pdf(PURCHASE_TEXT + "\n<script>alert(1)</script>")
        job, job_url = self._submit(source, "<img src=x onerror=alert(1)>.pdf")
        self.assertEqual(job.state, "needs_review")
        page = self.client.get(job_url)
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Importvorschau – noch nicht gebucht", html)
        self.assertIn("codex/portman-v10-foundation", html)
        self.assertIn("abc1234", html)
        self.assertIn("Indexfonds — ISIN DE0008474511", html)
        self.assertEqual(html.count("<strong>Wertpapier:</strong>"), 1)
        self.assertIn("comdirect Giro", html)
        self.assertIn("-126.5 EUR", html)
        self.assertIn("0.125", html)
        self.assertIn("1.5 EUR", html)
        self.assertIn("Exakte Kennung", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)
        self.assertNotIn("<td>Unbekannt</td>", html)
        self.assertNotIn("Belegkennung:", html)
        self.assertIn('disabled>Übernehmen</button>', html)
        self.assertIn("Vorschau bereit – Angaben müssen geprüft werden.", html)

    def test_review_decision_uses_session_csrf_and_does_not_book(self):
        from dataclasses import replace
        from portman_v10.infrastructure.preview_codec import encode_preview

        job, job_url = self._submit()
        preview = self.workflow.get_import_preview(job.import_id)
        item = replace(preview.items[0], review_status="complete_candidate", missing_fields=(), warnings=(), conflicts=())
        preview = replace(preview, items=(item,))
        self.store.replace_import_preview_items(job.import_id, preview.revision, encode_preview(preview))
        html = self.client.get(job_url).get_data(as_text=True)
        self.assertIn('name="_csrf_token"', html)
        self.assertRegex(html, r'<form method="post" action="/imports/[^\"]+/commit">\s*<input type="hidden" name="_csrf_token"')
        token = self._csrf_token()
        origin_headers = {"Origin": self.base_url, "Referer": f"{self.base_url}/imports/{job.import_id}"}
        for form_data, headers in (
            ({"candidate_id": item.candidate_id, "decision": "accept"}, origin_headers),
            ({"_csrf_token": "wrong", "candidate_id": item.candidate_id, "decision": "accept"}, origin_headers),
            ({"_csrf_token": token, "candidate_id": item.candidate_id, "decision": "accept"}, {**origin_headers, "Origin": "http://evil.example", "Referer": "http://evil.example/"}),
        ):
            denied = self.client.post(f"/imports/{job.import_id}/review", data=form_data, base_url=self.base_url, headers=headers)
            self.assertEqual(denied.status_code, 403)
            self.assertIn("Prüfentscheidung abgelehnt", denied.get_data(as_text=True))
        current = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(current.decisions, ())

        accepted = self.client.post(
            f"/imports/{job.import_id}/review",
            data={"_csrf_token": token, "candidate_id": item.candidate_id, "candidate_revision": item.revision, "decision": "accept"},
            base_url=self.base_url,
            headers=origin_headers,
        )
        self.assertEqual(accepted.status_code, 303, accepted.get_data(as_text=True))
        updated_redirect = self.client.get(accepted.headers["Location"], base_url=self.base_url)
        self.assertEqual(updated_redirect.status_code, 302)
        updated = self.client.get(updated_redirect.headers["Location"], base_url=self.base_url)
        self.assertEqual(updated.status_code, 200)
        updated_html = updated.get_data(as_text=True)
        self.assertIn("Prüfentscheidung gespeichert: Kandidat angenommen", updated_html)
        self.assertIn("Noch nicht gebucht", updated_html)
        self.assertEqual(self.workflow.get_import_preview(job.import_id).decisions[0].decision.decision, "accept")
        rejected_commit = self.client.post(
            f"/imports/{job.import_id}/commit",
            data={"preview_revision": preview.revision, "request_id": "missing-token-commit"},
            base_url=self.base_url,
            headers=origin_headers,
        )
        self.assertEqual(rejected_commit.status_code, 403)
        self.assertIn("Übernahme abgelehnt", rejected_commit.get_data(as_text=True))
        self.assertEqual(self.workflow.get_import_preview(job.import_id).decisions[0].decision.decision, "accept")
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)
        finally:
            connection.close()

    def test_realistic_comdirect_buy_keeps_open_account_and_instrument_reasons_visible(self):
        text = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: A2H57N
ISIN: LU1681041973
St. 0,25 AIS-AM.E.H.D.F.EOC
Zu Ihren Lasten EUR 49,92
Valuta 02.05.2025"""
        job, url = self._submit(make_text_pdf(text), "synthetic-comdirect-buy.pdf")
        preview = self.workflow.get_import_preview(job.import_id)
        item = preview.items[0]
        self.assertEqual(dict(item.references)["security_isin"], "LU1681041973")
        self.assertEqual(dict(item.references)["security_wkn"], "A2H57N")
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn("Stückzahl fehlt", html)
        self.assertIn("A2H57N", html)
        self.assertIn("Prüfen: eindeutige V10-Kontozuordnung", html)
        self.assertNotIn('name="decision" value="accept"', html)

    def test_unmapped_comdirect_security_identity_and_receipt_reference_are_shown_once(self):
        from dataclasses import replace
        from portman_v10.infrastructure.preview_codec import encode_preview

        data_dir = self.data_dir / "without-instrument"
        data_dir.mkdir()
        store = SQLiteStore(data_dir / "v10.sqlite")
        store.migrate()
        store.save_account(AccountInput(
            "comdirect Giro", "cash", "checking", "comdirect", "EUR",
            identifiers=(AccountIdentifier("iban", "comdirect", "DE00000000000000000001"),),
        ))
        store.save_account(AccountInput(
            "comdirect Depot", "position", "depot", "comdirect",
            identifiers=(AccountIdentifier("depot_number", "comdirect", "123456"),),
        ))
        workflow = ImportWorkflow(store, data_dir)
        try:
            app = create_app(workflow, branch="test", commit="fixture", profile="unmapped-instrument")
            client = app.test_client()
            home = client.get("/", base_url=self.base_url).get_data(as_text=True)
            token = re.search(r'name="_csrf_token" value="([^"]+)"', home).group(1)
            source_text = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: LS9AVX
ISIN: DE000LS9AVX3
Nennwert Zum Kurs von
St. 0,007 EUR 3.471,31
Kurswert : EUR 24,30
Valuta 01.07.2026
Zu Ihren Lasten EUR 24,30
Steuerliche Behandlung: Wertpapierkauf Nr. 91182283 vom 01.07.2026
Stk. 0,007 LANG+SCHWARZ O.E. INDEX , WKN / ISIN: LS9AVX / DE000LS9AVX3
IBAN DE00000000000000000001"""
            response = client.post(
                "/imports",
                data={"_csrf_token": token, "pdf": (BytesIO(make_text_pdf(source_text)), "unmapped.pdf")},
                content_type="multipart/form-data",
                base_url=self.base_url,
                headers={"Origin": self.base_url, "Referer": f"{self.base_url}/"},
            )
            self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
            job = workflow.wait(response.headers["Location"].rsplit("/", 1)[-1], 15)
            preview = workflow.get_import_preview(job.import_id)
            item = preview.items[0]
            self.assertEqual([(m.movement_type, m.amount.text) for m in item.movements], [("cash", "-24.3"), ("quantity", "0.007")])
            self.assertEqual(item.movements[1].instrument_name, "LANG+SCHWARZ O.E. INDEX")
            self.assertEqual(dict(item.references)["security_isin"], "DE000LS9AVX3")
            self.assertEqual(item.movements[1].instrument_id, None)

            updated_item = replace(item, movements=tuple(
                replace(movement, account_reference="V476492400") if movement.movement_type == "quantity" else movement
                for movement in item.movements
            ))
            store.replace_import_preview_items(job.import_id, preview.revision, encode_preview(replace(preview, items=(updated_item,))))
            html = client.get(response.headers["Location"]).get_data(as_text=True)
            self.assertIn("LANG+SCHWARZ O.E. INDEX — ISIN DE000LS9AVX3", html)
            self.assertIn("Stammdatenzuordnung: Zuordnung offen", html)
            self.assertIn("comdirect Giro", html)
            self.assertIn("comdirect Depot", html)
            self.assertNotIn("<td>Unbekannt</td>", html)
            table = re.search(r"<table>.*?</table>", html, re.S).group(0)
            self.assertNotIn("V476492400", table)
            self.assertIn("Mengenbewegung: V476492400", html)

            wkn_item = replace(updated_item, references=tuple(
                (key, "LS9AVX" if key == "security_wkn" else None if key == "security_isin" else value)
                for key, value in updated_item.references
            ))
            store.replace_import_preview_items(job.import_id, preview.revision, encode_preview(replace(preview, items=(wkn_item,))))
            wkn_html = client.get(response.headers["Location"]).get_data(as_text=True)
            self.assertIn("LANG+SCHWARZ O.E. INDEX — WKN LS9AVX", wkn_html)
        finally:
            workflow.close()

    def test_instrument_match_issue_is_visible_and_clears_on_new_preview(self):
        source_text = """comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: LS9AVX
ISIN: DE000LS9AVX3
Nennwert Zum Kurs von
St. 0,007 EUR 3.471,31
Kurswert : EUR 24,30
Valuta 01.07.2026
Zu Ihren Lasten EUR 24,30
Steuerliche Behandlung: Wertpapierkauf Nr. 91182283 vom 01.07.2026
Stk. 0,007 LANG+SCHWARZ O.E. INDEX , WKN / ISIN: LS9AVX / DE000LS9AVX3
IBAN DE00000000000000000001"""
        source = make_text_pdf(source_text)

        _job, url = self._submit(source, "instrument-review.pdf")
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn("Kein V10-Instrument für ISIN DE000LS9AVX3 vorhanden", html)
        self.assertIn('class="check-point">Prüfen: Kein V10-Instrument für ISIN DE000LS9AVX3 vorhanden', html)
        self.assertIn("color: #b00020; font-weight: 700", html)

        matched = self.store.save_instrument(InstrumentInput("Lang & Schwarz", "equity", isin="DE000LS9AVX3"))
        job, url = self._submit(source, "instrument-review-rematched.pdf")
        html = self.client.get(url).get_data(as_text=True)
        preview = self.workflow.get_import_preview(job.import_id)
        self.assertEqual(preview.items[0].instrument_ids, (matched.instrument_id,))
        self.assertIn("Stammdatenzuordnung: Zugeordnet", html)
        self.assertNotIn("Kein V10-Instrument für ISIN DE000LS9AVX3 vorhanden", html)

        self.store.save_instrument(InstrumentInput("Other WKN owner", "equity", isin="DE0004444444", wkn="LS9AVX"))
        _job, url = self._submit(source, "instrument-conflict.pdf")
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn("Widersprüchliche ISIN/WKN", html)
        self.assertIn('class="check-point">Prüfen: Widersprüchliche ISIN/WKN', html)

        self.store.save_instrument(InstrumentInput("Duplicate ISIN", "equity", isin="DE000LS9AVX3"))
        _job, url = self._submit(source, "instrument-ambiguous.pdf")
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn("Mehrere V10-Instrumente für ISIN DE000LS9AVX3 vorhanden", html)
        self.assertIn('class="check-point">Prüfen: Mehrere V10-Instrumente', html)

    def test_home_page_shows_profile_and_persistent_notice(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Importvorschau – noch nicht gebucht", html)
        self.assertIn("test-web", html)
        self.assertIn("multipart/form-data", html)
        self.assertIn("bereit zum Hochladen", html)
        self.assertIn("wird hochgeladen", html)
        self.assertIn("hochgeladen. Importvorschau wird erstellt", html)
        self.assertIn("xhr.status", html)

    def test_parser_availability_and_information_wording_are_present(self):
        template = (Path(__file__).parents[1] / "src" / "portman_v10" / "web" / "templates" / "job.html").read_text(encoding="utf-8")
        self.assertIn("Parser noch nicht ausführbar", template)
        self.assertIn("Information – keine Buchung", template)
        self.assertIn("Prüfung nötig", template)

    def test_unrecognized_document_is_explained_and_has_no_candidate(self):
        job, job_url = self._submit(make_text_pdf("unbekannte Beispielbank\nMitteilung"), "unknown.pdf")
        self.assertEqual(job.state, "needs_review")
        html = self.client.get(job_url).get_data(as_text=True)
        self.assertIn("unknown.pdf", html)
        self.assertIn("Importvorschau – noch nicht gebucht", html)

    def test_unreleased_comdirect_sale_is_review_only_in_web_preview(self):
        source = make_text_pdf("comdirect\nWertpapierverkauf\nStk. 1,000 Fonds DE0008474511\nZu Ihren Gunsten EUR 10,00\nDepotnummer: 123456\nIBAN DE00000000000000000001\nValuta 01.07.2026")
        job, job_url = self._submit(source, "sale-review.pdf")
        self.assertEqual(job.state, "needs_review")
        html = self.client.get(job_url).get_data(as_text=True)
        self.assertIn("Prüfung nötig", html)
        self.assertIn("Bankreferenz fehlt oder ist nicht eindeutig", html)
        self.assertNotIn('name="decision" value="accept"', html)

    def test_parser_failure_shows_concrete_error_and_retry_link(self):
        job, job_url = self._submit(b"kein gueltiges PDF", "broken.pdf")
        self.assertEqual(job.state, "failed")
        html = self.client.get(job_url).get_data(as_text=True)
        self.assertIn("fehlgeschlagen", html)
        self.assertIn("Bitte erneut versuchen", html)
        self.assertIn("broken.pdf", html)
        self.assertIn("retry-upload", html)

    def test_unmatched_depot_is_clearly_shown_as_open(self):
        text = PURCHASE_TEXT.replace("Depotnummer: 123456", "Depotnummer: 999999")
        job, job_url = self._submit(make_text_pdf(text), "unmatched.pdf")
        self.assertEqual(job.state, "needs_review")
        html = self.client.get(job_url).get_data(as_text=True)
        self.assertIn("Zuordnung offen", html)
        self.assertIn("999999", html)

    def test_upload_validation_size_and_unknown_document_errors(self):
        local_headers = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/"}
        local_headers["X-Test-Session"] = "unused"
        no_file = self.client.post("/imports", data={"_csrf_token": self._csrf_token()}, content_type="multipart/form-data", headers=local_headers)
        self.assertEqual(no_file.status_code, 400)
        self.assertIn("Bitte eine PDF-Datei auswählen", no_file.get_data(as_text=True))

        wrong_extension = self.client.post(
            "/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(b"not pdf"), "statement.txt")}, content_type="multipart/form-data", headers=local_headers,
        )
        self.assertEqual(wrong_extension.status_code, 400)
        self.assertIn("Endung .pdf", wrong_extension.get_data(as_text=True))

        empty = self.client.post(
            "/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(b""), "empty.pdf")}, content_type="multipart/form-data", headers=local_headers,
        )
        self.assertEqual(empty.status_code, 400)
        self.assertIn("Datei ist leer", empty.get_data(as_text=True))

        self.app.config["MAX_CONTENT_LENGTH"] = 512
        oversized = self.client.post(
            "/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(b"x" * 2048), "large.pdf")}, content_type="multipart/form-data", headers=local_headers,
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertIn("50 MiB", oversized.get_data(as_text=True))

        unknown_job = self.client.get("/jobs/not-a-job")
        self.assertEqual(unknown_job.status_code, 404)
        unknown_document = self.client.get("/documents/C:%5CWindows%5Cwin.ini")
        self.assertEqual(unknown_document.status_code, 404)

    def test_rejects_untrusted_host(self):
        response = self.client.get("/", headers={"Host": "external.example"})
        self.assertEqual(response.status_code, 400)

    def test_rejects_cross_origin_upload(self):
        response = self.client.post("/imports", headers={"Origin": "http://external.example", "Host": "127.0.0.1:8765"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("nur von der geöffneten lokalen V10-Seite", response.get_data(as_text=True))

    def test_http_403_is_not_reported_as_success_and_same_file_can_be_retried(self):
        file_bytes = make_text_pdf(PURCHASE_TEXT)
        rejected = self.client.post("/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(file_bytes), "retry.pdf")}, content_type="multipart/form-data",
                                    headers={"Host": "127.0.0.1:8765", "Origin": "http://evil.example"})
        self.assertEqual(rejected.status_code, 403)
        self.assertIn("Upload nur von der geöffneten lokalen V10-Seite erlaubt", rejected.get_data(as_text=True))
        accepted = self.client.post("/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(file_bytes), "retry.pdf")}, content_type="multipart/form-data",
                                    headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/"})
        self.assertEqual(accepted.status_code, 303)
        job_id = accepted.headers["Location"].rsplit("/", 1)[-1]
        self.workflow.wait(job_id, timeout=15)
        feedback = self.client.get(accepted.headers["Location"]).get_data(as_text=True)
        self.assertIn("Importvorschau – noch nicht gebucht", feedback)
        self.assertIn("Vorschau bereit – Angaben müssen geprüft werden", feedback)

    def test_accepts_same_origin_browser_form_headers_with_matching_scheme_host_and_port(self):
        response = self.client.post("/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "browser.pdf")},
                                    content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/"})
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))

    def test_referer_fallback_is_allowed_but_missing_or_invalid_origin_headers_are_denied(self):
        origin_only = self.client.post(
            "/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "origin-only.pdf")},
            content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(origin_only.status_code, 303, origin_only.get_data(as_text=True))
        fallback = self.client.post("/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "referer.pdf")},
                                    content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/source/page?tab=import"})
        self.assertEqual(fallback.status_code, 303, fallback.get_data(as_text=True))
        missing = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "no-origin.pdf")}, content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "", "Referer": ""})
        self.assertEqual(missing.status_code, 403)
        mismatch = self.client.post("/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "wrong-port.pdf")},
                                    content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8766"})
        self.assertEqual(mismatch.status_code, 403)
        no_headers_with_page_token = self.client.post(
            "/imports",
            data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "no-referrer.pdf")},
            content_type="multipart/form-data",
            base_url=self.base_url,
        )
        self.assertEqual(no_headers_with_page_token.status_code, 303, no_headers_with_page_token.get_data(as_text=True))
        no_headers_without_page_token = self.client.post(
            "/imports", data={"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "no-token.pdf")},
            content_type="multipart/form-data", base_url=self.base_url,
        )
        self.assertEqual(no_headers_without_page_token.status_code, 403)

    def test_null_origin_with_session_token_is_allowed(self):
        client = self.app.test_client()
        html = client.get("/", base_url=self.base_url).get_data(as_text=True)
        token = re.search(r'name="_csrf_token" value="([^"]+)"', html).group(1)
        response = client.post(
            "/imports", base_url=self.base_url,
            data={"_csrf_token": token, "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "null-origin.pdf")},
            content_type="multipart/form-data", headers={"Origin": "null"},
        )
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))

    def test_missing_or_wrong_token_and_wrong_host_are_rejected_without_starting_import(self):
        token = self._csrf_token()
        connection = self.store.connect()
        try:
            before = connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
        finally:
            connection.close()
        for supplied, host in ((None, "127.0.0.1:8765"), ("wrong", "127.0.0.1:8765"), (token, "evil.example")):
            data = {"pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "rejected.pdf")}
            if supplied is not None:
                data["_csrf_token"] = supplied
            response = self.client.post("/imports", data=data, content_type="multipart/form-data",
                                        headers={"Host": host, "Origin": "null"})
            self.assertIn(response.status_code, (400, 403))
        connection = self.store.connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0], before)
        finally:
            connection.close()

    def test_foreign_origin_stays_blocked_even_with_local_form_token_and_logs_only_origin_metadata(self):
        token = self._csrf_token()
        with self.assertLogs("portman_v10.web.server", level="WARNING") as captured:
            response = self.client.post(
                "/imports",
                data={"_csrf_token": token, "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "foreign.pdf")},
                content_type="multipart/form-data",
                headers={"Host": "127.0.0.1:8765", "Origin": "http://evil.example", "Referer": "http://evil.example/upload"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertIn("Origin='http://evil.example'", captured.output[0])
        self.assertIn("Referer='http://evil.example/upload'", captured.output[0])
        self.assertIn("Host='127.0.0.1:8765'", captured.output[0])
        self.assertNotIn("Cookie", captured.output[0])

    def test_same_origin_value_with_path_is_not_valid_origin_but_is_valid_referer(self):
        valid_referer = self.client.post("/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "referer-path.pdf")},
                                         content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Referer": "http://127.0.0.1:8765/a/page?return=1"})
        self.assertEqual(valid_referer.status_code, 303, valid_referer.get_data(as_text=True))
        invalid_origin = self.client.post("/imports", data={"_csrf_token": self._csrf_token(), "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "origin-path.pdf")},
                                          content_type="multipart/form-data", headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765/a/page"})
        self.assertEqual(invalid_origin.status_code, 403)


if __name__ == "__main__":
    unittest.main()
