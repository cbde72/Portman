"""Simple, GUI-independent projections for depot and account demonstration views."""

from portman_parsers.api import ParsedDocument, to_json_compatible


def depot_view(result: ParsedDocument) -> list[dict[str, object]]:
    snapshots_by_depot: dict[str, list[object]] = {}
    for snapshot in result.depot_snapshots:
        snapshots_by_depot.setdefault(snapshot.depot_id, []).append(snapshot)
    return [to_json_compatible({
        "depot": depot,
        "snapshots": tuple(snapshots_by_depot.get(depot.depot_id, ())),
        "linked_account_ids": tuple(link.account_id for link in result.depot_account_links
                                    if link.depot_id == depot.depot_id),
        "security_movements": tuple(movement for event in result.events
                                    for movement in event.security_movements
                                    if movement.depot_id == depot.depot_id),
        "events": tuple(event for event in result.events if any(
            movement.depot_id == depot.depot_id for movement in event.security_movements)),
        "fees": tuple(fee for event in result.events for fee in event.fee_events
                      if fee.depot_id == depot.depot_id),
        "open_assignments": tuple(issue for issue in result.issues
                                  if "ASSIGNMENT" in issue.code),
    }) for depot in result.depots]


def account_view(result: ParsedDocument) -> list[dict[str, object]]:
    balances_by_account: dict[str, list[object]] = {}
    for balance in result.account_balances:
        balances_by_account.setdefault(balance.account_id, []).append(balance)
    return [to_json_compatible({
        "account": account,
        "balances": tuple(balances_by_account.get(account.account_id, ())),
        "linked_depot_ids": tuple(link.depot_id for link in result.depot_account_links
                                  if link.account_id == account.account_id),
        "cash_movements": tuple(movement for event in result.events
                                for movement in event.cash_movements
                                if movement.account_id == account.account_id),
        "events": tuple(event for event in result.events if any(
            movement.account_id == account.account_id for movement in event.cash_movements)),
        "interest_events": tuple(event for event in result.events
                                 if event.kind in {"INTEREST_CREDIT", "INTEREST_DEBIT"}
                                 and any(movement.account_id == account.account_id
                                         for movement in event.cash_movements)),
        "tax_events": tuple(tax for event in result.events for tax in event.tax_events
                            if any(movement.account_id == account.account_id
                                   for movement in event.cash_movements)),
        "fees": tuple(fee for event in result.events for fee in event.fee_events
                      if fee.account_id == account.account_id),
        "issues": result.issues,
    }) for account in result.accounts]


def depot_account_link_view(result: ParsedDocument) -> list[dict[str, object]]:
    depots = {item.depot_id: item for item in result.depots}
    accounts = {item.account_id: item for item in result.accounts}
    return [to_json_compatible({
        "link": link,
        "depot": depots[link.depot_id],
        "account": accounts[link.account_id],
        "account_type": accounts[link.account_id].account_type,
        "account_functions": accounts[link.account_id].functions,
        "settlement_role": link.role,
    }) for link in result.depot_account_links]

