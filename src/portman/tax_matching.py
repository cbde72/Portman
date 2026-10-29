"""Conservative, read-only matching of tax notices to cash bookings."""
from datetime import date
from decimal import Decimal, InvalidOperation

from portfolio_v5.accounts import account_key


def _amount(value):
    try:
        return abs(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _days(left, right):
    try:
        return abs((date.fromisoformat(left) - date.fromisoformat(right)).days)
    except (TypeError, ValueError):
        return 9999


def _security_refs(repository, value, cache):
    value = str(value or '').strip().upper()
    if not value:
        return set()
    if value in cache:
        return cache[value]
    refs = {value}
    row = repository.db.execute(
        'SELECT security_key,isin,wkn FROM security_master '
        'WHERE upper(security_key)=? OR upper(isin)=? OR upper(wkn)=?',
        (value, value, value)).fetchone()
    if row:
        refs.update(str(row[key]).strip().upper() for key in ('security_key', 'isin', 'wkn') if row[key])
    # A clean import can legitimately leave security_master with the WKN key
    # from a Finanzreport while the settlement/tax PDFs carry the ISIN.  The
    # imported security evidence already contains the authoritative bridge;
    # use it for read-only matching instead of requiring a later master-data
    # repair or a particular document order.
    aliases = cache.get('__imported_aliases__')
    if aliases is None:
        aliases = {}
        store = getattr(repository, 'store', None)
        records = store.model_records(kind='securities') if store is not None else []
        for record in records:
            security = record.get('payload', record)
            identifiers = {str(security.get(field) or '').strip().upper()
                           for field in ('key', 'isin', 'wkn')}
            identifiers.discard('')
            expanded = set(identifiers)
            expanded.update(identifier.removeprefix('ISIN:').removeprefix('WKN:')
                            for identifier in identifiers)
            for identifier in expanded:
                aliases.setdefault(identifier, set()).update(expanded)
        cache['__imported_aliases__'] = aliases
    refs.update(aliases.get(value, ()))
    for identifier in tuple(refs):
        refs.update(aliases.get(identifier, ()))
    cache[value] = refs
    return refs


def _scored_candidates(repository, events=None, transactions=None):
    events = list(events if events is not None else repository.tax_events())
    transactions = list(transactions if transactions is not None else repository.transactions())
    cash = [tx for tx in transactions if tx.get('kind') in ('DIVIDEND', 'DISTRIBUTION')]
    account_aliases = {row['account_key']: row['account_key'] for row in repository.account_records()}
    account_aliases.update({account_key(row['name']): row['account_key']
                            for row in repository.account_records()})
    def account_identity(value):
        key = account_key(value or '')
        return account_aliases.get(key, key)
    security_cache = {}
    candidates = {}
    for event in events:
        if event.get('type') not in ('investment_ausschuettung_inland',
                                     'investment_ausschuettung_ausland', 'dividende_inland'):
            continue
        event_refs = _security_refs(repository, event.get('security_ref'), security_cache)
        if not event_refs:
            continue
        gross = _amount(event.get('gross_income'))
        if gross is None:
            taxable, partial = _amount(event.get('taxable_income')), _amount(event.get('partial_exemption_amount'))
            gross = taxable + (partial or Decimal()) if taxable is not None else None
        paid = _amount(event.get('paid_taxes')) or Decimal()
        net = gross - paid if gross is not None else None
        event_depot = account_identity(event.get('account', ''))
        scored = []
        for tx in cash:
            tx_refs = _security_refs(repository, tx.get('security') or tx.get('security_ref'), security_cache)
            if not event_refs.intersection(tx_refs):
                continue
            reference_text = ' '.join(str(tx.get(key) or '') for key in
                                      ('transaction_reference', 'bank_reference', 'document_reference',
                                       'purpose', 'booking_text'))
            exact_reference = bool(event.get('reference_no') and
                                   event['reference_no'] in reference_text)
            tx_depot = account_identity(
                tx.get('performance_depot_key') or tx.get('depot_account') or tx.get('account', ''))
            cash_account_match = (not tx.get('performance_depot_key') and not tx.get('depot_account')
                                  and account_identity(tx.get('account', '')) == account_identity(
                                      event.get('cash_account', '')))
            if event_depot and tx_depot and event_depot != tx_depot and not cash_account_match:
                continue
            distance = min(_days(event.get('date'), tx.get('date')),
                           _days(event.get('date'), tx.get('value_date')))
            if distance > 4:
                continue
            tx_gross = _amount(tx.get('gross_income') or tx.get('gross_amount'))
            tx_net = _amount(tx.get('amount'))
            gross_match = gross is not None and tx_gross is not None and abs(gross - tx_gross) <= Decimal('.01')
            net_match = net is not None and tx_net is not None and abs(net - tx_net) <= Decimal('.01')
            if not (gross_match or net_match):
                continue
            tx_tax = _amount(tx.get('taxes'))
            if tx_tax is not None and paid and abs(tx_tax - paid) > Decimal('.01'):
                continue
            score = 10 if exact_reference else 0
            score += 4 if gross_match else 3
            score += 2 if distance == 0 else 1
            scored.append((score, tx))
        if scored:
            candidates[event['external_id']] = scored
    return candidates


def tax_event_cash_candidates(repository, events=None, transactions=None):
    """Return every strongly evidenced cash representation per tax event.

    Multiple documents can describe the same payment.  They all have to be
    suppressed from the tax-basis sum even though only one may be selected as
    the canonical event link.
    """
    return {event_id: [tx for _score, tx in scored]
            for event_id, scored in _scored_candidates(repository, events, transactions).items()}


def match_tax_events(repository, events=None, transactions=None):
    """Return unique event-id -> economic dividend/distribution booking matches.

    A candidate must agree on security, depot (or exact cash-account bank
    reference), a close date and a documented gross or net amount. Ties and
    reused cash bookings remain deliberately unmatched instead of creating an
    unsafe canonical association.
    """
    scored_candidates = _scored_candidates(repository, events, transactions)
    candidates = {}
    for event_id, scored in scored_candidates.items():
        best = max(score for score, _tx in scored)
        winners = [tx for score, tx in scored if score == best]
        if len(winners) == 1:
            candidates[event_id] = winners[0]
    used = {}
    for event_id, tx in candidates.items():
        identity = tx.get('external_id') or id(tx)
        used.setdefault(identity, []).append(event_id)
    return {event_id: tx for event_id, tx in candidates.items()
            if len(used[tx.get('external_id') or id(tx)]) == 1}
