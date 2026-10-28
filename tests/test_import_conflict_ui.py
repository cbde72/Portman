import os
import json
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import (QApplication, QAbstractButton, QComboBox, QDialog,
                               QLabel, QLineEdit, QTableWidget)
from portfolio_v5.models import (BankTransaction, ImportBatch, TaxDetailRecord,
                                 TaxEvent, ValidationIssue)

from portman.import_conflict_actions import (
    BookingConflictDialog,
    AdvanceTaxConflictDialog,
    ImportDecisionPolicy,
    WarningNotice,
    WarningDecisionDialog,
    identical_conflict,
    persistent_warning_rows,
    remove_persistent_warning,
    reset_persistent_warnings,
    resolve_conflicts_interactively,
    resolve_advance_tax_conflicts_interactively,
    resolve_warnings_interactively,
    warning_notice,
)
from portman.import_v09 import ImportSession
from portman.repository_v09 import RepositoryV09
from portman.settings_storage import StorageV07


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def booking(path="source.pdf", external="tx-1", amount="100", fees="1", taxes="2"):
    return ImportBatch(path, path, transactions=[BankTransaction(
        "Giro", external, "2026-10-01", "BANK_BOOKING", amount, "EUR",
        fees=fees, taxes=taxes, purpose="Test")], account_names=["Giro"])


def job():
    return SimpleNamespace(progress=SimpleNamespace(emit=lambda *args: None),
                           isInterruptionRequested=lambda: False)


def advance_tax_batch(path="advance.pdf", external="advance-new", taxable="10.00",
                      transaction=False, detail=False):
    batch = ImportBatch(path, path, tax_events=[TaxEvent(
        external, "Depot Test", "vorabpauschale", "2021-01-04",
        income_year="2020", security_ref="IE00BKM4GZ66",
        advance_tax_base="12.00", taxable_income=taxable)])
    if transaction:
        batch.transactions = [BankTransaction(
            "Depot Test", path + "-booking", "2021-01-04", "BANK_BOOKING",
            "5.00", "EUR", purpose="Andere Buchung")]
    if detail:
        batch.tax_details = [TaxDetailRecord(
            path + "-detail", "comdirect", "Depot Test", "CSV", {},
            linked_tax_event_id=external)]
    return batch


def prepare_depot(repo):
    repo.save_account("Depot Test", {"kind": "Depot", "institution": "comdirect"})


def conflict(amount="101", external="tx-1", source="new.pdf"):
    old = vars(booking().transactions[0]).copy()
    old.update(source="old.pdf", import_id=1, depot="Giro")
    new = vars(booking(source, external, amount).transactions[0]).copy()
    return {"key": source + external, "old": old, "new": new, "source": source,
            "id_match": external == "tx-1", "candidate_count": 1}


def wizard_for(conflicts):
    table = QTableWidget(len(conflicts), 2)
    for row, item in enumerate(conflicts):
        combo = QComboBox()
        combo.addItem("Bitte entscheiden", None)
        combo.addItem("Neue überspringen", "skip")
        if item["old"]["import_id"] >= 0:
            combo.addItem("Alte ersetzen", "replace")
        table.setCellWidget(row, 0, combo)
        table.setCellWidget(row, 1, QLineEdit())
    return SimpleNamespace(conflicts=conflicts, conflict_table=table,
                           import_decision_policy=ImportDecisionPolicy())


class FakeConflictDialog:
    actions = []
    scopes = []
    calls = 0

    def __init__(self, conflict, current, total, parent=None):
        type(self).calls += 1
        self.action = type(self).actions.pop(0)
        self.scope = QComboBox()
        self.scope.addItem("once", "once")
        self.scope.addItem("all", "all")
        self.scope.addItem("ask", "ask")
        self.scope.setCurrentIndex(self.scope.findData(type(self).scopes.pop(0)))

    def exec(self):
        return QDialog.DialogCode.Accepted


class CancelConflictDialog(FakeConflictDialog):
    def __init__(self, *args, **kwargs):
        pass

    def exec(self):
        return QDialog.DialogCode.Rejected


class FakeWarningDialog(FakeConflictDialog):
    pass


class FakeAdvanceTaxDialog:
    action = "ignore"
    accepted = True
    calls = 0

    def __init__(self, conflict, current, total, parent=None):
        type(self).calls += 1

    def exec(self):
        return (QDialog.DialogCode.Accepted if type(self).accepted
                else QDialog.DialogCode.Rejected)


def configure(dialog, actions, scopes):
    dialog.actions = list(actions)
    dialog.scopes = list(scopes)
    dialog.calls = 0


def test_dialog_compares_required_fields_and_highlights_differences(app):
    dialog = BookingConflictDialog(conflict(), 3, 12)
    table = dialog.findChild(QTableWidget)
    assert dialog.windowTitle() == "Eintrag schon vorhanden"
    assert table.horizontalHeaderItem(1).text() == "Vorhandene Buchung"
    assert [table.item(row, 0).text() for row in range(table.rowCount())] == [
        "Datum", "Konto", "Wertpapier / ISIN", "Betrag", "Gebühren", "Steuer", "Dokumentquelle"]
    assert table.item(3, 1).background().color().name() == "#fff0bd"
    dialog.close()


def test_identical_reimport_is_skipped_without_question(app):
    item = conflict(amount="100")
    assert identical_conflict(item)
    wizard = wizard_for([item])
    configure(FakeConflictDialog, ["replace"], ["once"])
    assert resolve_conflicts_interactively(wizard, FakeConflictDialog)
    assert wizard.conflict_table.cellWidget(0, 0).currentData() == "skip"
    assert FakeConflictDialog.calls == 0


@pytest.mark.parametrize(("action", "expected"), [("replace", "replace"), ("skip", "skip")])
def test_changed_reimport_maps_overwrite_or_keep_old(app, action, expected):
    wizard = wizard_for([conflict()])
    configure(FakeConflictDialog, [action], ["once"])
    assert resolve_conflicts_interactively(wizard, FakeConflictDialog)
    assert wizard.conflict_table.cellWidget(0, 0).currentData() == expected
    if action == "replace":
        assert wizard.conflict_table.cellWidget(0, 1).text()


def test_rule_for_all_applies_only_to_same_conflict_kind(app):
    items = [conflict(source="one.pdf"), conflict(source="two.pdf"),
             conflict(amount="102", external="other", source="three.pdf")]
    wizard = wizard_for(items)
    configure(FakeConflictDialog, ["skip", "replace"], ["all", "once"])
    assert resolve_conflicts_interactively(wizard, FakeConflictDialog)
    assert [wizard.conflict_table.cellWidget(i, 0).currentData() for i in range(3)] == [
        "skip", "skip", "replace"]
    assert FakeConflictDialog.calls == 2
    assert len(wizard.import_decision_policy.conflict_rules) == 1


def test_ask_each_conflict_never_creates_rule(app):
    wizard = wizard_for([conflict(source="one.pdf"), conflict(source="two.pdf")])
    configure(FakeConflictDialog, ["skip", "replace"], ["ask", "ask"])
    assert resolve_conflicts_interactively(wizard, FakeConflictDialog)
    assert FakeConflictDialog.calls == 2
    assert not wizard.import_decision_policy.conflict_rules


def test_ignored_warning_remains_in_report_and_is_not_a_booking_decision(app):
    warnings = ["Hinweis: eins", "Hinweis: zwei"]
    wizard = SimpleNamespace(import_decision_policy=ImportDecisionPolicy())
    configure(FakeWarningDialog, ["ignore"], ["all"])
    assert resolve_warnings_interactively(wizard, warnings, FakeWarningDialog)
    assert warnings == ["Hinweis: eins", "Hinweis: zwei"]
    assert wizard.import_decision_policy.ignored_warning_count == 2
    assert wizard.import_decision_policy.warning_rules == {"Hinweis": "ignore"}


def test_critical_batch_error_blocks_atomic_import(tmp_path, app):
    repo = RepositoryV09(tmp_path / "critical.sqlite", backups=False)
    try:
        batches = [booking(), ImportBatch("bad.pdf", "bad", errors=["Nicht endlicher Betrag"])]
        session = ImportSession(repo.store.path, batches)
        with pytest.raises(ValueError, match="Nicht endlicher Betrag"):
            session.commit(job(), batches, {})
        assert repo.transactions() == []
    finally:
        repo.close()


def test_cancel_happens_before_any_write(tmp_path, app):
    repo = RepositoryV09(tmp_path / "cancel.sqlite", backups=False)
    try:
        repo.commit_batches([booking()])
        incoming = booking("new.pdf", amount="101")
        session = ImportSession(repo.store.path, [incoming])
        wizard = wizard_for(session.conflicts([incoming]))
        assert not resolve_conflicts_interactively(wizard, CancelConflictDialog)
        assert len(repo.transactions()) == 1
    finally:
        repo.close()


def test_interactive_replace_remains_undoable(tmp_path, app):
    repo = RepositoryV09(tmp_path / "undo.sqlite", backups=False)
    try:
        repo.commit_batches([booking()])
        incoming = booking("new.pdf", external="tx-2", amount="100")
        session = ImportSession(repo.store.path, [incoming])
        conflicts = session.conflicts([incoming])
        wizard = wizard_for(conflicts)
        configure(FakeConflictDialog, ["replace"], ["once"])
        assert resolve_conflicts_interactively(wizard, FakeConflictDialog)
        decisions = {item["key"]: {"action": "replace",
            "reason": wizard.conflict_table.cellWidget(row, 1).text()}
            for row, item in enumerate(conflicts)}
        result = session.commit(job(), [incoming], decisions)
        assert repo.transactions()[0]["external_id"].startswith("tx-2")
        repo.undo_import(result[0]["id"])
        assert repo.transactions()[0]["external_id"] == "tx-1"
    finally:
        repo.close()


def test_dialog_policy_rejects_background_thread(app):
    wizard = wizard_for([conflict()])
    errors = []

    def run():
        try:
            resolve_conflicts_interactively(wizard, FakeConflictDialog)
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start(); thread.join()
    assert len(errors) == 1
    assert "GUI-Thread" in str(errors[0])


def test_warning_dialog_explicitly_separates_message_from_booking(app):
    dialog = WarningDecisionDialog("Zulässige Abweichung", 1, 2)
    assert dialog.windowTitle() == "Importhinweis"
    assert any("keine Buchung" in label.text() for label in dialog.findChildren(QLabel))
    dialog.close()


def coded_notice(code="CACHE_FRESHNESS", plugin="comdirect", message="Zwischenspeicher aktuell"):
    return WarningNotice(message, f"{plugin}:{code}", plugin, code,
                         code.replace("_", " ").title(), True)


def persistent_wizard(settings=None, save=None):
    return SimpleNamespace(import_decision_policy=ImportDecisionPolicy(),
        persistent_warning_rules=dict((settings or {}).get("ignored_import_warnings", {})),
        save_persistent_warning_rules=save or (lambda rules: None))


def test_warning_dialog_has_four_keyboard_reachable_choices(app):
    dialog = WarningDecisionDialog(coded_notice(), 1, 1)
    texts = [button.text() for button in dialog.findChildren(QAbstractButton)]
    assert any("&Übernehmen" in text for text in texts)
    assert any("&Nachfragen" in text for text in texts)
    assert any("&Ignorieren" in text for text in texts)
    assert any("&zukünftigen" in text for text in texts)
    future = next(button for button in dialog.findChildren(QAbstractButton)
                  if "zukünftigen" in button.text())
    assert future.isEnabled()
    dialog.close()


def test_persistent_rule_survives_settings_reload_and_suppresses_same_type(tmp_path, app):
    storage = StorageV07(tmp_path)
    settings = storage.load_settings()

    def save(rules):
        settings["ignored_import_warnings"] = dict(rules)
        storage.save_settings(settings)

    first = persistent_wizard(settings, save)
    configure(FakeWarningDialog, ["ignore_future"], ["once"])
    notice = coded_notice()
    assert resolve_warnings_interactively(first, [notice], FakeWarningDialog)
    assert first.import_decision_policy.ignored_warning_count == 1
    assert storage.load_settings()["ignored_import_warnings"] == {
        notice.key: {"plugin": "comdirect", "code": "CACHE_FRESHNESS",
                     "category": "Cache Freshness"}}

    restarted = persistent_wizard(storage.load_settings())
    configure(FakeWarningDialog, [], [])
    assert resolve_warnings_interactively(restarted, [notice], FakeWarningDialog)
    assert FakeWarningDialog.calls == 0
    assert restarted.import_decision_policy.ignored_warning_count == 1


def test_persistent_rule_only_suppresses_same_plugin_and_code(app):
    settings = {"ignored_import_warnings": {
        "comdirect:CACHE_FRESHNESS": {"plugin": "comdirect", "code": "CACHE_FRESHNESS",
                                       "category": "Cache Freshness"}}}
    wizard = persistent_wizard(settings)
    configure(FakeWarningDialog, ["ask", "ask"], ["once", "once"])
    notices = [coded_notice(plugin="ing"), coded_notice(code="HISTORY_RANGE_INFO")]
    assert resolve_warnings_interactively(wizard, notices, FakeWarningDialog)
    assert FakeWarningDialog.calls == 2
    assert wizard.import_decision_policy.ignored_warning_count == 0


def test_warning_is_preserved_when_persistently_suppressed(app):
    issue = ValidationIssue("CACHE_FRESHNESS", "warning", "Vollständiger interner Hinweis")
    batch = booking()
    batch.plugin_id = "user.comdirect"
    batch.warnings = [issue]
    notice = warning_notice(batch, issue)
    settings = {"ignored_import_warnings": {
        notice.key: {"plugin": notice.plugin, "code": notice.code,
                     "category": notice.category}}}
    wizard = persistent_wizard(settings)
    assert resolve_warnings_interactively(wizard, [notice], FakeWarningDialog)
    assert batch.warnings == [issue]
    assert str(batch.warnings[0]) == "Vollständiger interner Hinweis"


def test_remove_one_and_reset_all_persistent_rules():
    settings = {"ignored_import_warnings": {
        "comdirect:CACHE_FRESHNESS": {"plugin": "comdirect", "code": "CACHE_FRESHNESS"},
        "ing:HISTORY_RANGE_INFO": {"plugin": "ing", "code": "HISTORY_RANGE_INFO"}}}
    assert [row["key"] for row in persistent_warning_rows(settings)] == [
        "comdirect:CACHE_FRESHNESS", "ing:HISTORY_RANGE_INFO"]
    assert remove_persistent_warning(settings, "comdirect:CACHE_FRESHNESS")
    assert list(settings["ignored_import_warnings"]) == ["ing:HISTORY_RANGE_INFO"]
    assert reset_persistent_warnings(settings) == 1
    assert persistent_warning_rows(settings) == []


def test_critical_warning_code_cannot_be_persistently_ignored(app):
    batch = booking()
    batch.plugin_id = "user.comdirect"
    notice = warning_notice(batch, ValidationIssue(
        "DATABASE_ERROR", "error", "Datenbankoperation fehlgeschlagen"))
    assert not notice.persistable
    dialog = WarningDecisionDialog(notice, 1, 1)
    future = next(button for button in dialog.findChildren(QAbstractButton)
                  if "zukünftigen" in button.text())
    assert not future.isEnabled()
    dialog.close()
    wizard = persistent_wizard()
    configure(FakeWarningDialog, ["ignore_future"], ["once"])
    with pytest.raises(ValueError, match="darf nicht dauerhaft ignoriert"):
        resolve_warnings_interactively(wizard, [notice], FakeWarningDialog)


def test_suppressed_count_reaches_result_but_warning_stays_in_import_report(tmp_path, app):
    repo = RepositoryV09(tmp_path / "result.sqlite", backups=False)
    try:
        batch = booking()
        batch.warnings = ["Aus dem comdirect-Zwischenspeicher: vollständig protokollierter Hinweis"]
        session = ImportSession(repo.store.path, [batch])
        session.suppressed_warning_count = 1
        result = session.commit(job(), [batch], {})[0]
        assert result["suppressed_warnings"] == 1
        report = json.loads(repo.imports()[0]["report"])
        assert report["warnings"] == [
            "Aus dem comdirect-Zwischenspeicher: vollständig protokollierter Hinweis"]
    finally:
        repo.close()


def test_advance_tax_conflict_is_found_before_simulation_and_shows_two_choices(tmp_path, app):
    repo = RepositoryV09(tmp_path / "advance-dialog.sqlite", backups=False)
    try:
        prepare_depot(repo)
        repo.commit_batches([advance_tax_batch("old.pdf", "advance-old")])
        session = ImportSession(repo.store.path, [advance_tax_batch()])
        conflicts = session.advance_tax_conflicts(session.batches)
        assert len(conflicts) == 1
        assert conflicts[0]["identical"]
        dialog = AdvanceTaxConflictDialog(conflicts[0], 1, 1)
        texts = [button.text() for button in dialog.findChildren(QAbstractButton)]
        assert any("&Ignorieren" in text for text in texts)
        assert any("&Abbrechen" in text for text in texts)
        dialog.close()
    finally:
        repo.close()


def test_differing_advance_tax_values_are_reported_explicitly(tmp_path):
    repo = RepositoryV09(tmp_path / "advance-different.sqlite", backups=False)
    try:
        prepare_depot(repo)
        repo.commit_batches([advance_tax_batch("old.pdf", "advance-old")])
        session = ImportSession(repo.store.path, [
            advance_tax_batch("changed.pdf", "advance-changed", "11.00")])
        conflict = session.advance_tax_conflicts(session.batches)[0]
        assert not conflict["identical"]
        assert conflict["differences"] == ["taxable_income"]
    finally:
        repo.close()


def test_ignore_advance_tax_keeps_other_booking_and_removes_dependent_detail(tmp_path):
    repo = RepositoryV09(tmp_path / "advance-ignore.sqlite", backups=False)
    try:
        prepare_depot(repo)
        repo.commit_batches([advance_tax_batch("old.pdf", "advance-old")])
        incoming = advance_tax_batch(transaction=True, detail=True)
        session = ImportSession(repo.store.path, [incoming])
        conflict = session.advance_tax_conflicts([incoming])[0]
        results = session.commit(job(), [incoming], {
            conflict["key"]: {"action": "ignore", "reason": "Sichtprüfung"}})
        assert results[0]["status"] == "imported"
        assert len(repo.tax_events()) == 1
        assert len(repo.transactions()) == 1
        assert repo.store.model_records(kind="tax_details") == []
        report = json.loads(repo.imports()[0]["report"])
        assert any("Vorabpauschale" in warning for warning in report["warnings"])
    finally:
        repo.close()


def test_advance_tax_cancel_keeps_decisions_and_performs_no_write(tmp_path, app):
    repo = RepositoryV09(tmp_path / "advance-cancel.sqlite", backups=False)
    try:
        prepare_depot(repo)
        repo.commit_batches([advance_tax_batch("old.pdf", "advance-old")])
        incoming = advance_tax_batch()
        session = ImportSession(repo.store.path, [incoming])
        conflicts = session.advance_tax_conflicts([incoming])
        wizard = SimpleNamespace(decisions={"booking-choice": {"action": "skip"}})
        FakeAdvanceTaxDialog.accepted = False
        assert not resolve_advance_tax_conflicts_interactively(
            wizard, conflicts, FakeAdvanceTaxDialog)
        assert wizard.decisions == {"booking-choice": {"action": "skip"}}
        assert len(repo.imports()) == 1
    finally:
        FakeAdvanceTaxDialog.accepted = True
        repo.close()


def test_advance_tax_ignore_decision_is_reused_without_second_dialog(tmp_path, app):
    repo = RepositoryV09(tmp_path / "advance-reuse.sqlite", backups=False)
    try:
        prepare_depot(repo)
        repo.commit_batches([advance_tax_batch("old.pdf", "advance-old")])
        session = ImportSession(repo.store.path, [advance_tax_batch()])
        conflicts = session.advance_tax_conflicts(session.batches)
        wizard = SimpleNamespace(decisions={})
        FakeAdvanceTaxDialog.calls = 0
        assert resolve_advance_tax_conflicts_interactively(
            wizard, conflicts, FakeAdvanceTaxDialog)
        assert FakeAdvanceTaxDialog.calls == 1
        assert resolve_advance_tax_conflicts_interactively(
            wizard, conflicts, FakeAdvanceTaxDialog)
        assert FakeAdvanceTaxDialog.calls == 1
    finally:
        repo.close()


def test_unhandled_advance_tax_and_normal_database_errors_remain_blocking(tmp_path):
    repo = RepositoryV09(tmp_path / "advance-blocking.sqlite", backups=False)
    try:
        prepare_depot(repo)
        repo.commit_batches([advance_tax_batch("old.pdf", "advance-old")])
        incoming = advance_tax_batch()
        session = ImportSession(repo.store.path, [incoming])
        with pytest.raises(ValueError, match="ausdrücklich entscheiden"):
            session.simulate(job(), [incoming], {})
        bad = booking("bad.pdf")
        bad.errors = ["Normaler Datenbank- oder Validierungsfehler"]
        bad_session = ImportSession(repo.store.path, [bad])
        with pytest.raises(ValueError, match="Normaler Datenbank"):
            bad_session.simulate(job(), [bad], {})
        assert len(repo.imports()) == 1
    finally:
        repo.close()
