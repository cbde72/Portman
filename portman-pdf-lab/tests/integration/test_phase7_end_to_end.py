from pathlib import Path

from portman_parsers.rules import ProfileStore, RuleProfile
from portman_pdf_lab.application.pdf_analysis import analyse_pdf
from portman_pdf_lab.synthetic_pdf import create_demo_pdf


TEXT="""comdirect
Wertpapierkauf
Stk. 0,125 Beispiel ETF, WKN / ISIN: ABC123 / DE0008474511
Valuta 04.02.2026
Zu Ihren Lasten EUR 126,50
Neues Layoutmerkmal TRAIN42"""


def test_standard_extended_compare_restart_and_independent_export(tmp_path):
    pdf=create_demo_pdf(tmp_path / "comdirect.pdf", TEXT)
    store=ProfileStore(tmp_path / "profiles")
    standard_before=analyse_pdf(pdf, "STANDARD", store)
    assert standard_before["rule_mode_effective"] == "STANDARD" and "rule_decisions" not in standard_before
    detection=standard_before["detection"]
    profile=RuleProfile("comdirect.training", "comdirect", detection["plugin_id"], detection["document_type"],
        detection["handler_id"], "annotated", 1, detection["plugin_version"],
        ({"rule_id":"training-1","rule_type":"REGEX_FIELD","field_path":"attributes.training_value",
          "pattern":r"Neues Layoutmerkmal (?P<value>TRAIN\d+)","normalizer":"TEXT","strategy":"FILL_MISSING"},),
        approved_by="tester", approval_reason="synthetic golden passed").sealed()
    store.save(profile); store.activate(profile)
    extended=analyse_pdf(pdf, "EXTENDED", store)
    assert extended["rule_mode_effective"] == "EXTENDED"
    assert extended["rule_decisions"][0]["effective_value"] == "TRAIN42"
    standard_after=analyse_pdf(pdf, "STANDARD", store)
    assert standard_after["result"] == standard_before["result"]
    compare=analyse_pdf(pdf, "COMPARE", ProfileStore(tmp_path / "profiles"))
    assert compare["rule_comparison"][0]["standard"] is None and compare["rule_comparison"][0]["extended"] == "TRAIN42"
    exported=store.export_profile(profile, tmp_path / "portable.yaml")
    independent=ProfileStore(tmp_path / "independent"); loaded=independent.import_profile(exported); independent.activate(loaded)
    repeated=analyse_pdf(pdf, "EXTENDED", independent)
    assert repeated["rule_decisions"] == extended["rule_decisions"]
