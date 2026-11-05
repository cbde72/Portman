from portman_parsers.api import FinancialEvent, MissingValue


def possible_duplicate_events(events: tuple[FinancialEvent, ...]) -> tuple[tuple[str, str], ...]:
    seen: dict[tuple[object, ...], str] = {}
    duplicates: list[tuple[str, str]] = []
    for event in events:
        security_identity = tuple((item.security_id, item.quantity) for item in event.security_movements)
        if not security_identity and not isinstance(event.security_isin, MissingValue):
            security_identity = ((event.security_isin, None),)
        signature = (
            event.kind, event.event_date,
            tuple((item.amount, item.currency, item.account_ref) for item in event.cash_movements),
            security_identity,
        )
        if signature in seen:
            duplicates.append((seen[signature], event.event_id))
        else:
            seen[signature] = event.event_id
    return tuple(duplicates)

