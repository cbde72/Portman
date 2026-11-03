from collections import Counter

from portman_pdf_lab.application import AnalysisReport


def quality_summary(report: AnalysisReport) -> dict[str, object]:
    severities = Counter(issue.severity.value for issue in report.issues)
    return {
        "result_id": report.result.result_id,
        "events": len(report.result.events),
        "snapshots": len(report.result.snapshots),
        "issues": dict(sorted(severities.items())),
        "requires_review": bool(report.issues),
    }

