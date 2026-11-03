from portman_parsers.api import FinancialEvent


def possible_duplicate_events(events: tuple[FinancialEvent, ...]) -> tuple[tuple[str, str], ...]:
    seen: dict[tuple[object, ...], str] = {}
    duplicates: list[tuple[str, str]] = []
    for event in events:
        signature = (
            event.kind, event.event_date,
            tuple((item.amount, item.currency, item.account_ref) for item in event.cash_movements),
            tuple((item.security_id, item.quantity) for item in event.security_movements),
        )
        if signature in seen:
            duplicates.append((seen[signature], event.event_id))
        else:
            seen[signature] = event.event_id
    return tuple(duplicates)

