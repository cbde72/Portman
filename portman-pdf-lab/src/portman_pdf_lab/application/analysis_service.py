"""Small application boundary consuming only the public parser API."""

from dataclasses import dataclass
from time import perf_counter_ns

from portman_parsers.api import Issue, ParsedDocument, to_json_compatible
from portman_parsers.validation import validate_parsed_document


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    result: ParsedDocument
    issues: tuple[Issue, ...]
    duration_ns: int

    def to_dict(self) -> dict[str, object]:
        return to_json_compatible(self)


class AnalysisService:
    def analyse(self, result: ParsedDocument) -> AnalysisReport:
        started = perf_counter_ns()
        issues = validate_parsed_document(result)
        return AnalysisReport(result, issues, perf_counter_ns() - started)

