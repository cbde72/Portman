import sqlite3

import pytest

from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.training import SafeRuleEngine, TrainingService, UnsafeRuleError, compare_values


def repository(tmp_path):
    repo = ReferenceRepository(tmp_path / "training.sqlite")
    repo.register_document("doc", "a" * 64, "private.pdf", "comdirect", "Wertpapierkauf")
    return repo


def annotation(repo, value="51,50", text="Settlement EUR 51,50"):
    return repo.create_annotation("doc", "user.comdirect-ertraege", "wertpapierkauf", 1, text,
                                  "events[0].trades[0].settlement_amount", value, "AMOUNT",
                                  "CORRECTED", "APPROVED", "alice")


def test_annotation_correction_missing_multiline_and_history(tmp_path):
    repo = repository(tmp_path); aid = annotation(repo, "51,50", "Zeile 1\nZeile 2 EUR 51,50")
    repo.update_annotation(aid, "52,00", "CORRECTED", "APPROVED", "bob", "second review")
    value = repo.annotation(aid)
    assert value["reference_value"] == "52,00" and "\n" in value["original_text"]
    missing = repo.create_annotation("doc", "p", "h", 1, "", "security.wkn", None, "MISSING", "MISSING", "APPROVED", "alice")
    assert repo.annotation(missing)["annotation_kind"] == "MISSING"
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT count(*) FROM annotation_history WHERE annotation_id=?", (aid,)).fetchone()[0] == 2


def test_golden_confirmation_is_versioned_and_reimport_does_not_overwrite(tmp_path):
    repo = repository(tmp_path)
    one = repo.create_golden("doc", "comdirect", "wertpapierkauf", "layout-a", "2.0", {"amount": "10"}, "alice")
    repo.decide_golden(one, "APPROVED", "alice", "checked")
    repo.save_run("doc", "user.comdirect-ertraege", "wertpapierkauf", "2.1", "1.5.0", {"amount": "99"}, (), 1)
    two = repo.create_golden("doc", "comdirect", "wertpapierkauf", "layout-a", "2.1", {"amount": "11"}, "bob", supersedes_id=one)
    assert repo.golden(one)["expectations"] == {"amount": "10"}
    assert repo.golden(one)["status"] == "APPROVED" and repo.golden(two)["version"] == 2


def test_safe_rule_suggestion_test_approval_and_rollback(tmp_path):
    repo = repository(tmp_path); service = TrainingService(repo)
    first = annotation(repo); candidate = service.suggest_rule(first, "alice")
    result = service.test_candidate(candidate, "alice")
    assert result["improved"] == 1 and not result["critical_cashflow_regression"]
    version1 = service.approve(candidate, "alice", "golden passed")
    second = annotation(repo, "60,00", "Settlement EUR 60,00")
    candidate2 = service.suggest_rule(second, "bob"); service.test_candidate(candidate2, "bob")
    version2 = service.approve(candidate2, "bob", "second golden passed")
    restored = repo.rollback_rule_version(version2, "bob", "regression outside corpus")
    assert version1 != version2 != restored


def test_unsafe_or_ambiguous_regex_is_rejected_and_no_code_execution_exists():
    engine = SafeRuleEngine()
    for pattern in ("(a+)+$", ".**", "(?=secret).*", "x" * 241):
        with pytest.raises(UnsafeRuleError): engine.validate_pattern(pattern)
    assert engine.suggest({"field_path": "x", "original_text": "unrelated", "reference_value": "42"}) is None
    with pytest.raises(UnsafeRuleError): engine.execute({"rule_type": "PYTHON", "pattern": "x"}, "x")


def test_numeric_comparison_normalizes_financial_scale():
    assert compare_values("0,63", "0,630")
    assert not compare_values("50,00", "51,50")


def test_cashflow_regression_blocks_release(tmp_path):
    repo = repository(tmp_path)
    aid = repo.create_annotation("doc", "p", "h", 1, "cash 10,00", "events[0].cash_movements[0].amount",
                                 "11,00", "AMOUNT", "CORRECTED", "APPROVED", "alice")
    candidate = repo.create_rule_candidate("doc", "p", "h", {"rule_type":"LITERAL_FIELD", "field_path":"events[0].cash_movements[0].amount", "pattern":"10,00"}, (aid,), "alice")
    service = TrainingService(repo); result = service.test_candidate(candidate, "alice")
    assert result["critical_cashflow_regression"]
    with pytest.raises(ValueError): service.approve(candidate, "alice", "must fail")
