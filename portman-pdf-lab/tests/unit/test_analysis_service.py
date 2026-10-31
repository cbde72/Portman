from portman_pdf_lab.analysis import quality_summary
from portman_pdf_lab.application import AnalysisService
from portman_pdf_lab.demo import synthetic_purchase


def test_application_analyses_public_parser_result():
    report = AnalysisService().analyse(synthetic_purchase())
    assert not report.issues
    assert report.duration_ns >= 0
    assert quality_summary(report)["requires_review"] is False


def test_analysis_report_is_json_compatible():
    report = AnalysisService().analyse(synthetic_purchase())
    data = report.to_dict()
    assert data["result"]["events"][0]["cash_movements"][0]["amount"] == "-103.00"

