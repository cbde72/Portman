from portman_pdf_lab.analysis.quality import reference_quality_summary
from portman_pdf_lab.reviews.models import ReviewStatus


def test_quality_has_no_metric_without_reference_basis():
    summary = reference_quality_summary([])
    assert summary.score is None
    assert summary.status is ReviewStatus.NOT_REVIEWED


def test_technical_result_is_not_automatically_approved():
    summary = reference_quality_summary([{"matches": True}, {"matches": False}])
    assert summary.score == 0.5
    assert summary.status is ReviewStatus.NOT_REVIEWED
