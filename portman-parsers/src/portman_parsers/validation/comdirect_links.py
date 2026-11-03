"""Conservative cross-document linking for comdirect tax and cash evidence."""
from dataclasses import dataclass
from portman_parsers.api import FinancialEvent, Issue, IssueNature, IssueSeverity
from portman_parsers.utilities import stable_id

@dataclass(frozen=True, slots=True)
class EventLink:
    left_event_id: str
    right_event_id: str
    matched_features: tuple[str, ...]

def link_comdirect_events(events: tuple[FinancialEvent, ...]) -> tuple[tuple[EventLink, ...], tuple[Issue, ...]]:
    links=[]; issues=[]
    for i,left in enumerate(events):
        for right in events[i+1:]:
            left_tax=left.tax_events[0] if left.tax_events else None; right_tax=right.tax_events[0] if right.tax_events else None
            features=[]
            if left.event_date and left.event_date==right.event_date: features.append("date")
            if left_tax and right_tax and left_tax.isin and left_tax.isin==right_tax.isin: features.append("isin")
            if left_tax and right_tax and left_tax.depot_id and left_tax.depot_id==right_tax.depot_id: features.append("depot")
            if len(features)>=2: links.append(EventLink(left.event_id,right.event_id,tuple(features)))
    linked={x for link in links for x in (link.left_event_id,link.right_event_id)}
    for event in events:
        if event.tax_events and event.event_id not in linked:
            issues.append(Issue(stable_id("issue",event.event_id,"tax-link"),"COMDIRECT_TAX_LINK_UNRESOLVED",IssueSeverity.WARNING,"Tax information could not be linked unambiguously; amount alone is insufficient.",event_id=event.event_id,nature=IssueNature.UNSECURED_ASSIGNMENT))
    return tuple(links),tuple(issues)
