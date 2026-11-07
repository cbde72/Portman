from dataclasses import replace
from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from portman_v10.application.contracts import AccountIdentifier, AccountInput, ApplicationError, ErrorCode, InstrumentInput
from portman_v10.infrastructure.import_workflow import ImportWorkflow
from portman_v10.infrastructure.preview_codec import encode_preview
from portman_v10.infrastructure.sqlite_store import SQLiteStore
from portman_v10.web.server import create_app
from synthetic_pdf import make_text_pdf

BASE_URL = "http://127.0.0.1:8765"
PURCHASE_TEXT = """comdirect
Wertpapierkauf
Depotnummer: 123456
Stk. 0,125 Fonds DE0008474511
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50
Valuta 01.07.2026
DE00 0000 0000 0000 0000 01"""
HINT = "ohne Entscheidung"


class ImportDecisionFeedbackTests(unittest.TestCase):
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
        self.store.save_instrument(InstrumentInput("Indexfonds", "fund", isin="DE0008474511"), None)
        self.workflow = ImportWorkflow(self.store, data_dir)
        self.addCleanup(self.workflow.close)
        self.client = create_app(self.workflow, profile="test-web").test_client()
        token_page = self.client.get("/", base_url=BASE_URL).get_data(as_text=True)
        self.token = re.search(r'name="_csrf_token" value="([^"]+)"', token_page).group(1)

        response = self.client.post("/imports", data={"_csrf_token": self.token, "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "kauf.pdf")},
                                    content_type="multipart/form-data", base_url=BASE_URL, headers={"Origin": BASE_URL})
        self.job_url = response.headers["Location"]
        job = self.workflow.wait(self.job_url.rsplit("/", 1)[-1], timeout=15)
        self.import_id = job.import_id
        # Prüfbarer, vollständiger Kandidat wie in test_web_preview: Entscheidung ist der einzige offene Punkt.
        preview = self.workflow.get_import_preview(self.import_id)
        self.item = replace(preview.items[0], review_status="complete_candidate", missing_fields=(), warnings=(), conflicts=())
        self.preview = replace(preview, items=(self.item,))
        self.store.replace_import_preview_items(self.import_id, preview.revision, encode_preview(self.preview))
        self.headers = {"Origin": BASE_URL, "Referer": f"{BASE_URL}/jobs/x"}

    def _events(self):
        connection = self.store.connect()
        try:
            return connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            connection.close()

    def _commit(self, request_id):
        revision = self.workflow.get_import_preview(self.import_id).revision
        return self.client.post(f"/imports/{self.import_id}/commit", base_url=BASE_URL, headers=self.headers,
                                data={"_csrf_token": self.token, "preview_revision": revision, "request_id": request_id})

    def test_undecided_candidate_is_marked_and_blocks_commit_button(self):
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Prüfen: Entscheidung fehlt", html)
        self.assertIn('id="undecided-hint"', html)
        self.assertIn("Noch 1 Kandidat ohne Entscheidung", html)
        self.assertIn("disabled>Übernehmen</button>", html)

    def _review(self, candidate, decision):
        return self.client.post(f"/imports/{self.import_id}/review", base_url=BASE_URL, headers=self.headers, data={
            "_csrf_token": self.token, "candidate_id": candidate.candidate_id, "candidate_revision": candidate.revision, "decision": decision,
        })

    def test_needs_review_candidate_can_only_be_ignored_and_then_no_longer_blocks(self):
        current = self.workflow.get_import_preview(self.import_id)
        blocked = replace(current.items[0], candidate_id=current.items[0].candidate_id + "-nr", review_status="needs_review")
        self.store.replace_import_preview_items(self.import_id, current.revision, encode_preview(replace(current, items=(self.item, blocked))))
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("noch nicht zur Übernahme freigegeben", html)
        self.assertIn("Vorgangstyp nicht freigegeben; „Ignorieren“ wählen", html)
        self.assertIn("Ignorieren (nicht buchen)", html)
        self.assertIn("Noch 2 Kandidaten ohne Entscheidung", html)

        refused = self._review(blocked, "accept")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("kann nur ignoriert werden", refused.get_data(as_text=True))
        self.assertEqual(self.workflow.get_import_preview(self.import_id).decisions, ())

        self.assertEqual(self._review(blocked, "ignore").status_code, 303)
        self.assertEqual(self._review(self.item, "accept").status_code, 303)
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertNotIn("Entscheidung fehlt", html)
        self.assertNotIn("Ignorieren (nicht buchen)", html)
        self.assertIn("Prüfentscheidung gespeichert: Kandidat ignoriert", html)
        self.assertIn("offene Konflikte/Zuordnungen 0", html)
        self.assertIn('<button type="submit" >Übernehmen</button>', html)

        committed = self._commit("web-mixed-ignore")
        self.assertEqual(committed.status_code, 303, committed.get_data(as_text=True))
        self.assertEqual(self._events(), 1)

    def test_commit_without_decision_reports_on_same_import_page_and_books_nothing(self):
        response = self._commit("web-no-decision")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Bad Request", html)
        self.assertIn('id="action-error"', html)
        self.assertIn("Übernahme nicht ausgeführt: Jeder Buchungskandidat muss ausdrücklich angenommen oder ignoriert werden", html)
        self.assertIn("Noch 1 Kandidat ohne Entscheidung – unten rot markiert.", html)
        self.assertIn("Importprüfung", html)
        self.assertIn("Kandidat prüfen / annehmen", html)
        self.assertEqual(self._events(), 0)

    def _reimport_same_pdf(self):
        """Ersten Import buchen, dasselbe PDF erneut einreichen: Kandidat trägt den Dubletten-Hinweis auf den Vorgang."""
        self._review(self.item, "accept")
        self.assertEqual(self._commit("web-first").status_code, 303)
        response = self.client.post("/imports", data={"_csrf_token": self.token, "pdf": (BytesIO(make_text_pdf(PURCHASE_TEXT)), "kauf-nochmal.pdf")},
                                    content_type="multipart/form-data", base_url=BASE_URL, headers={"Origin": BASE_URL})
        job_url = response.headers["Location"]
        import_id = self.workflow.wait(job_url.rsplit("/", 1)[-1], timeout=15).import_id
        preview = self.workflow.get_import_preview(import_id)
        item = preview.items[0]
        self.assertTrue(item.conflicts and item.conflicts[0].related_event_id, "Wiederimport muss auf den gebuchten Vorgang zeigen")
        item = replace(item, review_status="complete_candidate", missing_fields=(), warnings=())
        self.store.replace_import_preview_items(import_id, preview.revision, encode_preview(replace(preview, items=(item,))))
        return job_url, import_id, self.workflow.get_import_preview(import_id).items[0]

    def test_link_as_complement_clears_the_duplicate_hint_and_enables_commit(self):
        job_url, import_id, item = self._reimport_same_pdf()
        message = item.conflicts[0].message
        before = self.client.get(job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn(f'class="check-point">Prüfen: {message}', before)
        self.assertIn("disabled>Übernehmen</button>", before)

        linked = self.client.post(f"/imports/{import_id}/review", base_url=BASE_URL, headers=self.headers, data={
            "_csrf_token": self.token, "candidate_id": item.candidate_id, "candidate_revision": item.revision, "decision": "link"})
        self.assertEqual(linked.status_code, 303)
        after = self.client.get(job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Prüfentscheidung gespeichert: Als Ergänzungsbeleg zugeordnet", after)
        self.assertNotIn(f"Prüfen: {message}", after)
        self.assertIn("offene Konflikte/Zuordnungen 0", after)
        self.assertNotIn("Vor der Übernahme müssen alle", after)
        self.assertIn('<button type="submit" >Übernehmen</button>', after)

        preview_revision = self.workflow.get_import_preview(import_id).revision
        committed = self.client.post(f"/imports/{import_id}/commit", base_url=BASE_URL, headers=self.headers, data={
            "_csrf_token": self.token, "preview_revision": preview_revision, "request_id": "web-link"})
        self.assertEqual(committed.status_code, 303, committed.get_data(as_text=True))
        self.assertEqual(self._events(), 1, "Ergänzungsbeleg erzeugt keinen zweiten Vorgang")

    def test_accept_does_not_clear_a_duplicate_hint(self):
        job_url, import_id, item = self._reimport_same_pdf()
        self.client.post(f"/imports/{import_id}/review", base_url=BASE_URL, headers=self.headers, data={
            "_csrf_token": self.token, "candidate_id": item.candidate_id, "candidate_revision": item.revision, "decision": "accept"})
        html = self.client.get(job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn(f"Prüfen: {item.conflicts[0].message}", html)
        self.assertIn("offene Konflikte/Zuordnungen 1", html)
        self.assertIn("disabled>Übernehmen</button>", html)

    def _accept_all(self, revision=None):
        if revision is None:
            revision = self.workflow.get_import_preview(self.import_id).revision
        return self.client.post(f"/imports/{self.import_id}/accept-all", base_url=BASE_URL, headers=self.headers,
                                data={"_csrf_token": self.token, "preview_revision": revision})

    def _with_extra_candidates(self):
        """Ein weiterer bereiter Kandidat, einer mit fehlender Angabe, einer nur ignorierbar, eine Information."""
        current = self.workflow.get_import_preview(self.import_id)
        ready = replace(self.item, candidate_id=self.item.candidate_id + "-b")
        missing = replace(self.item, candidate_id=self.item.candidate_id + "-m", missing_fields=("Stückzahl",))
        blocked = replace(self.item, candidate_id=self.item.candidate_id + "-nr", review_status="needs_review")
        info = replace(self.item, candidate_id=self.item.candidate_id + "-i", review_status="information")
        self.store.replace_import_preview_items(self.import_id, current.revision,
                                               encode_preview(replace(current, items=(self.item, ready, missing, blocked, info))))
        return ready, missing, blocked

    def test_accept_all_takes_only_ready_candidates_and_lands_at_commit(self):
        ready, missing, blocked = self._with_extra_candidates()
        self._review(ready, "ignore")
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("Alle 1 bereiten Kandidaten annehmen", html)
        self.assertIn("2 weitere Kandidaten brauchen eine Einzelentscheidung", html)

        response = self._accept_all()
        self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
        self.assertTrue(response.headers["Location"].endswith("?accepted=1#commit-area"), response.headers["Location"])
        decisions = {value.candidate_id: value.decision.decision for value in self.workflow.get_import_preview(self.import_id).decisions}
        self.assertEqual(decisions, {self.item.candidate_id: "accept", ready.candidate_id: "ignore"},
                         "ignorierte bleiben ignoriert; unvollständige, gesperrte und Informationen werden nicht angenommen")
        page = self.client.get(response.headers["Location"].split("#")[0], base_url=BASE_URL).get_data(as_text=True)
        self.assertIn("1 Kandidat angenommen. Noch nicht gebucht", page)
        self.assertNotIn('id="accept-all-form"', page)
        self.assertEqual(self._events(), 0, "Alle annehmen bucht nichts")

    def test_accept_all_refuses_an_outdated_page(self):
        stale_revision = self.workflow.get_import_preview(self.import_id).revision
        self._review(self.item, "ignore")
        response = self._accept_all(stale_revision)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Vorschau hat sich seit dem Laden der Seite geändert", response.get_data(as_text=True))
        decisions = {value.candidate_id: value.decision.decision for value in self.workflow.get_import_preview(self.import_id).decisions}
        self.assertEqual(decisions, {self.item.candidate_id: "ignore"})

    def test_accept_all_then_commit_books_the_ready_candidate(self):
        self.assertEqual(self._accept_all().status_code, 303)
        self.assertEqual(self._commit("web-accept-all").status_code, 303)
        self.assertEqual(self._events(), 1)

    def test_accept_all_requires_session_token(self):
        revision = self.workflow.get_import_preview(self.import_id).revision
        denied = self.client.post(f"/imports/{self.import_id}/accept-all", base_url=BASE_URL, headers=self.headers,
                                  data={"_csrf_token": "falsch", "preview_revision": revision})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.workflow.get_import_preview(self.import_id).decisions, ())

    def test_decision_returns_to_the_decided_candidate_not_the_page_top(self):
        for decision in ("accept", "ignore"):
            with self.subTest(decision=decision):
                candidate = self.workflow.get_import_preview(self.import_id).items[0]
                response = self._review(candidate, decision)
                self.assertEqual(response.status_code, 303)
                location = response.headers["Location"]
                self.assertTrue(location.endswith(f"#candidate-{candidate.candidate_id}"), location)
                page = self.client.get(location.split("#", 1)[0], base_url=BASE_URL, follow_redirects=True).get_data(as_text=True)
                self.assertIn(f'<section id="candidate-{candidate.candidate_id}">', page)

    def test_accepted_candidate_clears_hint_and_enables_commit(self):
        accepted = self.client.post(f"/imports/{self.import_id}/review", base_url=BASE_URL, headers=self.headers, data={
            "_csrf_token": self.token, "candidate_id": self.item.candidate_id, "candidate_revision": self.item.revision, "decision": "accept",
        })
        self.assertEqual(accepted.status_code, 303)
        html = self.client.get(self.job_url, base_url=BASE_URL).get_data(as_text=True)
        self.assertNotIn(HINT, html)
        self.assertNotIn("Entscheidung fehlt", html)
        self.assertIn("<button type=\"submit\" >Übernehmen</button>", html)

    def test_rejected_review_decision_is_reported_on_import_page(self):
        # Veraltete Vorschau entsteht nur bei gleichzeitiger Änderung; hier gezielt aus der Anwendungsschicht ausgelöst.
        stale = ApplicationError(ErrorCode.STALE_REVISION, "Vorschau-Revision ist veraltet")
        with patch.object(self.workflow, "resolve_import_item", side_effect=stale):
            response = self.client.post(f"/imports/{self.import_id}/review", base_url=BASE_URL, headers=self.headers, data={
                "_csrf_token": self.token, "candidate_id": self.item.candidate_id, "candidate_revision": self.item.revision, "decision": "accept",
            })
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn('id="action-error"', html)
        self.assertIn("Prüfentscheidung nicht gespeichert: Vorschau-Revision ist veraltet", html)
        self.assertIn("Prüfen: Entscheidung fehlt", html)
        self.assertEqual(self.workflow.get_import_preview(self.import_id).decisions, ())


if __name__ == "__main__":
    unittest.main()
