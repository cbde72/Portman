from dataclasses import replace
from pathlib import Path

import pytest

from portman_parsers.api import ParsedDocument
from portman_parsers.rules import ProfileStore, RuleEngine, RuleMode, RuleProfile, RuleProfileError, RuleSafetyError


def result():
    return ParsedDocument("result", "doc", "user.comdirect-ertraege", "2.0", "wertpapierkauf",
                          attributes={"existing": "ORIGINAL"})


def profile(rules, version=1):
    return RuleProfile("comdirect.user", "comdirect", "user.comdirect-ertraege", "Kauf", "wertpapierkauf",
                       "annotated", version, "2.0", tuple(rules), approved_by="alice").sealed()


def test_standard_is_bit_identical_and_needs_no_profile():
    original = result(); extended = RuleEngine().apply(original, "Extra ABC123", None, RuleMode.STANDARD)
    assert extended.standard_result is original
    assert extended.standard_result.to_json() == original.to_json()
    assert not extended.decisions and extended.profile_id is None


def test_fill_missing_proposes_overlay_without_mutating_dto():
    p = profile(({"rule_id":"r1","rule_type":"REGEX_FIELD","field_path":"attributes.wkn",
                  "pattern":r"Extra (?P<value>[A-Z0-9]{6})","normalizer":"UPPER","strategy":"FILL_MISSING"},))
    original = result(); extended = RuleEngine().apply(original, "Extra ABC123", p, RuleMode.EXTENDED)
    assert original.attributes.get("wkn") is None
    assert extended.decisions[0].effective_value == "ABC123"
    assert extended.decisions[0].provenance == "rule-profile:comdirect.user@1"


def test_existing_value_is_not_overwritten_without_approved_override():
    fill = profile(({"rule_id":"r1","rule_type":"LITERAL_FIELD","field_path":"attributes.existing",
                     "pattern":"NEW","normalizer":"TEXT","strategy":"FILL_MISSING"},))
    proposed = RuleEngine().apply(result(), "NEW", fill, RuleMode.EXTENDED).decisions[0]
    assert proposed.effective_value == "ORIGINAL" and proposed.conflict
    override = profile(({**fill.rules[0], "strategy":"APPROVED_OVERRIDE"},), 2)
    approved = RuleEngine().apply(result(), "NEW", override, RuleMode.EXTENDED).decisions[0]
    assert approved.effective_value == "NEW" and approved.standard_value == "ORIGINAL"


def test_yaml_roundtrip_hash_activation_deactivation_and_restart(tmp_path):
    store = ProfileStore(tmp_path / "profiles"); p = profile(({"rule_id":"r1","rule_type":"LITERAL_FIELD","field_path":"attributes.x","pattern":"X","normalizer":"TEXT","strategy":"FILL_MISSING"},))
    path = store.save(p); loaded = store.load(path)
    assert loaded.profile_hash == p.profile_hash
    store.activate(p)
    restarted = ProfileStore(tmp_path / "profiles")
    assert restarted.active(p.parser_id, p.handler_id, p.document_type, p.layout_variant, p.parser_version).profile_hash == p.profile_hash
    restarted.deactivate(p.parser_id, p.handler_id, p.document_type, p.layout_variant)
    assert restarted.active(p.parser_id, p.handler_id, p.document_type, p.layout_variant) is None


def test_export_import_and_invalid_profiles_are_controlled(tmp_path):
    p = profile(({"rule_id":"r1","rule_type":"LITERAL_FIELD","field_path":"attributes.x","pattern":"X","normalizer":"TEXT","strategy":"FILL_MISSING"},))
    first = ProfileStore(tmp_path / "one"); exported = first.export_profile(p, tmp_path / "export.yaml")
    second = ProfileStore(tmp_path / "two"); assert second.import_profile(exported).profile_hash == p.profile_hash
    text = exported.read_text(encoding="utf-8").replace("schema_version: 1", "schema_version: 99")
    bad = tmp_path / "bad.yaml"; bad.write_text(text, encoding="utf-8")
    with pytest.raises(RuleProfileError): second.load(bad)
    unknown = profile(({"rule_id":"r1","rule_type":"PYTHON","field_path":"x","pattern":"X","normalizer":"TEXT","strategy":"FILL_MISSING"},))
    with pytest.raises(RuleSafetyError): RuleEngine().validate_profile(unknown)
