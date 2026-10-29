"""Separate cash ownership from the depot earning a security payment."""
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from .accounts import account_key
from .models import digest, valid_isin


def kind_of(tx):
    kind = tx.get('kind', '')
    return {'dividend': 'DIVIDEND', 'dividende': 'DIVIDEND', 'dividenden': 'DIVIDEND',
            'kauf': 'BUY', 'verkauf': 'SELL'}.get(kind.casefold(), kind)


def portfolio_cash_kind(tx):
    """Classify explicit security cash events conservatively from bank wording."""
    kind = kind_of(tx)
    if kind != 'BANK_BOOKING':
        return kind
    text = ' '.join(str(tx.get(key) or '') for key in ('purpose','booking_text','operation','raw_text')).casefold()
    if any(word in text for word in ('dividende', 'ausschüttung', 'ausschuettung', 'ertragsgutschrift')):
        return 'DIVIDEND'
    if any(word in text for word in ('quellensteuer', 'kapitalertragsteuer', 'kirchensteuer',
                                     'solidaritätszuschlag', 'vorabpauschale')):
        return 'TAX'
    if any(word in text for word in ('ordergebühr', 'ordergebuehr', 'transaktionsgebühr', 'transaktionsgebuehr', 'orderprovision')):
        return 'FEE'
    return kind


def infer_security_booking(store, tx, context=None):
    """Infer a security booking only from a unique, evidenced holding match."""
    if kind_of(tx) != 'BANK_BOOKING' or tx.get('performance_depot_key'):
        return None
    text = ' '.join(str(tx.get(key) or '') for key in
                    ('purpose', 'booking_text', 'operation', 'raw_text')).upper()
    income_wording = any(word in text for word in
                         ('KUPON', 'ERTRAEGNISGUTSCHRIFT', 'ERTRAGSGUTSCHRIFT'))
    fee_wording = any(word in text for word in
                      ('VERWAHRENTGELT', 'WERTPAPIERENTGELT', 'DEPOTENTGELT'))
    if 'WERTPAPIER' not in text and not income_wording and not fee_wording:
        return None
    if 'STORNO' in text:
        return None
    compact = re.sub(r'\s+', '', text)
    identifiers = set(re.findall(r'(?<![A-Z0-9])[A-Z]{2}[A-Z0-9]{9}\d(?![A-Z0-9])', text))
    identifiers.update('WKN:' + value for value in re.findall(
        r'\b(?:WKN|WPKNR)\s*:?\s*([A-Z0-9]{6})\b', text))
    explicit_security = str(tx.get('security') or '').removeprefix('ISIN:')
    if explicit_security:
        identifiers.add(explicit_security)
    parsed_isins = sorted(value for value in identifiers if not value.startswith('WKN:') and valid_isin(value))
    # Loading and decoding every depot snapshot for every bank transaction made
    # startup quadratic for larger portfolios.  A caller processing a batch can
    # pass one context dictionary so the immutable lookup data is decoded once.
    context = context if context is not None else {}
    prepared = context.get('security_booking_lookup')
    if prepared is None:
        records = {r['account_key']: r for r in store.account_records() if r['active']}
        by_name = {account_key(r['name']): r['account_key'] for r in records.values()}
        cash_by_depot = {}
        for key, record in records.items():
            details = json.loads(record['details'])
            cash_by_depot[key] = {value for value in
                (details.get('cash_account_key'), *(details.get('cash_account_keys') or [])) if value}
        positions_by_depot = {}
        for snapshot in store.snapshots():
            depot_key = by_name.get(account_key(snapshot['account']))
            if depot_key in records:
                for position in json.loads(snapshot['payload'])['positions']:
                    security = (position.get('isin') or position.get('key') or
                                ('WKN:' + position['wkn'] if position.get('wkn') else ''))
                    # The same holding can first be imported under ``WKN:...``
                    # and receive its ISIN only in a later snapshot.  Group by
                    # WKN when available so this history remains one candidate
                    # instead of becoming an artificial ambiguous match.
                    identity = (depot_key, ('WKN:' + position['wkn'])
                                if position.get('wkn') else security)
                    # Historical snapshots repeat the same position hundreds of
                    # times. Merge identifiers because later snapshots may add
                    # an ISIN or WKN to an already known security.
                    known = positions_by_depot.setdefault(identity, dict(position))
                    for field in ('isin', 'wkn', 'key', 'name'):
                        if position.get(field):
                            known[field] = position[field]
        positions = [(depot_key, position) for (depot_key, _), position
                     in positions_by_depot.items()]
        prepared = records, by_name, cash_by_depot, positions
        context['security_booking_lookup'] = prepared
    records, by_name, cash_by_depot, positions = prepared
    cash_key = by_name.get(account_key(tx['account']), account_key(tx['account']))
    exact_matches, global_exact_matches = set(), set()
    name_matches, global_name_matches = set(), set()
    normalized_text = re.sub(r'\s+', ' ', text)
    for depot_key, position in positions:
        linked = depot_key == cash_key or cash_key in cash_by_depot[depot_key]
        position_ids = {value for value in (
            position.get('isin'),
            'WKN:' + position['wkn'] if position.get('wkn') else '',
            position.get('key', ''),
        ) if value}
        known_isin = position.get('isin') or ''
        known_wkn = position.get('wkn') or ''
        known_name = re.sub(r'\s+', ' ', str(position.get('name') or '').upper()).strip()
        exact = (bool(position_ids & identifiers)
                 or bool(known_isin and known_isin in compact)
                 or bool(known_wkn and re.search(r'(?<![A-Z0-9])' + re.escape(known_wkn)
                                               + r'(?![A-Z0-9])', text)))
        by_position_name = bool(len(known_name) >= 6 and known_name in normalized_text)
        if exact or by_position_name:
            security = (parsed_isins[0] if len(parsed_isins) == 1 else
                        position.get('isin') or position.get('key') or ('WKN:' + position['wkn']))
            match = (depot_key, security)
            target, global_target = ((exact_matches, global_exact_matches) if exact
                                     else (name_matches, global_name_matches))
            global_target.add(match)
            if linked: target.add(match)
    # During import preview the bank's raw account name may not yet have been
    # mapped to the saved cash account. A globally unique depot/security match
    # is still deterministic and can safely drive the preview assignment.
    matches = exact_matches or name_matches
    global_matches = global_exact_matches or global_name_matches
    if not matches and len(global_matches) == 1:
        matches = global_matches
    if len(matches) != 1:
        return None
    amount = Decimal(tx['amount'])
    if not amount:
        return None
    depot_key, security = next(iter(matches))
    purchase_wording = 'WERTPAPIERE' in text and bool(parsed_isins)
    inferred_kind = ('FEE' if fee_wording else 'BUY' if purchase_wording
                     else ('DIVIDEND' if amount > 0 else 'BUY'))
    result = {'kind': inferred_kind, 'security': security,
              'performance_depot_key': depot_key,
              'assignment_source': 'Automatisch aus Wertpapierkennung oder Positionsname und Betrag'}
    if inferred_kind == 'FEE':
        result['fees'] = str(abs(amount))
    def german_number(pattern):
        match = re.search(pattern, text)
        if not match:
            return None
        return str(Decimal(match.group(1).replace('.', '').replace(',', '.')))
    if result['kind'] == 'DIVIDEND' and income_wording:
        quantity = german_number(r'DEPOTBESTAND\s*:\s*([0-9.]+(?:,[0-9]+)?)')
        gross = german_number(r'ABR\.?\s*BETRAG\s+BRUTTO\s+([0-9.]+(?:,[0-9]+)?)')
        taxes = german_number(r'STEUERABZUG\s+([0-9.]+(?:,[0-9]+)?)\s*-?')
        per_share = re.search(
            r'\b(?P<currency>[A-Z]{3})\s+(?P<amount>[0-9.]+(?:,[0-9]+)?)'
            r'(?=\s+(?:ABR\.?\s*BETRAG|KURSWERT|STEUERABZUG)|\s*$)', text)
        if quantity is not None: result['quantity'] = quantity
        if per_share:
            result.update(per_share_amount=str(Decimal(per_share.group('amount').replace('.', '').replace(',', '.'))),
                          per_share_currency=per_share.group('currency'))
            if gross is None and taxes is None:
                gross = str(amount)
        if gross is not None: result.update(gross_income=gross, gross_currency=tx.get('currency', 'EUR'), income_basis='net')
        if taxes is not None: result['taxes'] = taxes
    return result


def _security_owners(store):
    """security -> [(effective_date, account_key)] for every snapshot holding it."""
    records = [r for r in store.account_records() if r['active']]
    by_name = {account_key(r['name']): r['account_key'] for r in records}
    owners = defaultdict(list)
    for snap in store.snapshots():
        owner = by_name.get(account_key(snap['account']))
        if owner is None:
            continue
        for p in json.loads(snap['payload'])['positions']:
            security = p.get('isin') or p.get('key', '').removeprefix('ISIN:')
            if security:
                owners[security].append((snap['effective_date'], owner))
    return owners


def depot_candidates(store, tx, owners=None):
    records = [r for r in store.account_records() if r['active']]
    by_name = {account_key(r['name']): r['account_key'] for r in records}
    cash_key = by_name.get(account_key(tx['account']), account_key(tx['account']))
    candidates = []
    for record in records:
        details = json.loads(record['details'])
        cash_keys = {value for value in
            (details.get('cash_account_key'), *(details.get('cash_account_keys') or [])) if value}
        if cash_key in cash_keys:
            candidates.append(record)
    # A shared settlement account alone cannot identify the earning depot.
    if len(candidates) > 1 and tx.get('security'):
        security = tx['security'].removeprefix('ISIN:')
        if owners is None:
            owners = _security_owners(store)
        owners_for = {key for day, key in owners.get(security, ()) if day <= tx['date']}
        narrowed = [r for r in candidates if r['account_key'] in owners_for]
        if narrowed:
            candidates = narrowed
    return candidates


PORTFOLIO_CASH_KINDS = {'DIVIDEND', 'TAX', 'TAX_REFUND', 'FEE'}


def dividend_match(a, b):
    from .booking_duplicates import reference
    if a['account'] != b['account'] or a['currency'] != b['currency'] or Decimal(a['amount']) != Decimal(b['amount']):
        return False
    if a.get('import_id') == b.get('import_id'):
        return False
    da, db = a.get('value_date') or a['date'], b.get('value_date') or b['date']
    if da != db:
        return False
    if a.get('security') and b.get('security') and a['security'].removeprefix('ISIN:') != b['security'].removeprefix('ISIN:'):
        return False
    ra, rb = reference(a.get('bank_reference')), reference(b.get('bank_reference'))
    if ra and rb:
        return ra == rb
    security = a.get('security', '').removeprefix('ISIN:')
    if not security or not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', security):
        return False
    if kind_of(b) == 'DIVIDEND':
        return (b.get('security', '').removeprefix('ISIN:') == security
                and a.get('performance_depot_key', '') == b.get('performance_depot_key', ''))
    text = ' '.join(str(b.get(k) or '') for k in ('purpose', 'booking_text', 'raw_text')).upper()
    return security in re.sub(r'\s+', '', text) and any(word in text for word in ('DIVIDEND', 'AUSSCHÜTTUNG', 'ERTRAGSGUTSCHRIFT'))


def consolidate_dividends(store, transactions, protected=()):
    """Only unique, evidenced matches; all original source records remain stored."""
    from .booking_duplicates import reference, security_identifiers
    rows = [dict(t, kind=kind_of(t)) for t in transactions]
    for tx in rows:
        if tx['kind'] == 'DIVIDEND' and tx.get('booking_text', '') in ('comdirect Dividendengutschrift', 'comdirect Ertragsgutschrift'):
            tx['income_basis'] = 'gross'
    def is_protected(tx):
        return json.dumps([tx['import_id'], tx['depot'], tx['external_id']], ensure_ascii=False, separators=(',', ':')) in protected

    # A comdirect settlement notice states the gross distribution, while the
    # Finanzreport contains the actual net cash credit (often on the following
    # banking day).  They are two documents for one economic event.  Resolve
    # only a unique pair with the same account, currency and security evidence;
    # keep the Finanzreport amount and enrich it with the notice details.
    notice_indexes = [index for index, tx in enumerate(rows)
                      if tx['kind'] == 'DIVIDEND'
                      and tx.get('booking_text') in (
                          'comdirect Dividendengutschrift', 'comdirect Ertragsgutschrift')
                      and not is_protected(tx)]
    # A protected Finanzreport row remains the primary record and keeps its
    # stable reference (for example an existing tax link).  It is therefore
    # safe to attach an unprotected notice as evidence without rewriting the
    # protected booking itself.
    statement_indexes = [index for index, tx in enumerate(rows)
                         if tx['kind'] == 'BANK_BOOKING']
    inferred_statements = {}
    inference_context = {}
    for index in statement_indexes:
        inferred = infer_security_booking(store, rows[index], inference_context)
        if inferred and inferred.get('kind') == 'DIVIDEND':
            inferred_statements[index] = {**rows[index], **inferred}

    security_aliases = {}
    for snapshot in store.snapshots():
        for position in json.loads(snapshot['payload']).get('positions', []):
            identifiers = {str(value).upper() for value in (
                position.get('key'), position.get('isin'),
                'WKN:' + position['wkn'] if position.get('wkn') else '') if value}
            canonical = str(position.get('isin') or position.get('key') or '').upper()
            for identifier in identifiers:
                security_aliases[identifier] = canonical or identifier
    for record in store.model_records(kind='securities'):
        security = record['payload']
        identifiers = {str(value).upper() for value in (
            security.get('key'), security.get('isin'),
            'WKN:' + security['wkn'] if security.get('wkn') else '') if value}
        canonical = str(security.get('isin') or security.get('key') or '').upper()
        for identifier in identifiers:
            security_aliases[identifier] = canonical or identifier

    def canonical_security_ids(tx):
        return {security_aliases.get(identifier.upper(), identifier.upper())
                for identifier in security_identifiers(tx)}

    def notice_match(notice, statement):
        if (notice['account'] != statement['account']
                or notice.get('currency') != statement.get('currency')
                or notice.get('import_id') == statement.get('import_id')):
            return False
        notice_day = date.fromisoformat(notice.get('value_date') or notice['date'])
        statement_days = [date.fromisoformat(value) for value in
                          (statement.get('date'), statement.get('value_date')) if value]
        if not statement_days or min(abs((day - notice_day).days) for day in statement_days) > 3:
            return False
        notice_ids = canonical_security_ids(notice)
        statement_ids = canonical_security_ids(statement)
        if not notice_ids or not (notice_ids & statement_ids):
            return False
        notice_amount = abs(Decimal(notice['amount']))
        statement_net = abs(Decimal(statement['amount']))
        statement_gross = statement.get('gross_income') or statement.get('gross_amount')
        return (notice_amount == statement_net
                or (statement_gross not in (None, '')
                    and notice_amount == abs(Decimal(statement_gross))))

    notice_candidates = {index: [candidate for candidate, statement in inferred_statements.items()
                                 if notice_match(rows[index], statement)]
                         for index in notice_indexes}
    statement_candidates = defaultdict(list)
    for notice_index, candidates in notice_candidates.items():
        for statement_index in candidates:
            statement_candidates[statement_index].append(notice_index)
    premerged, used = {}, set()
    for notice_index, candidates in notice_candidates.items():
        if len(candidates) != 1 or len(statement_candidates[candidates[0]]) != 1:
            continue
        statement_index = candidates[0]
        notice, statement = rows[notice_index], inferred_statements[statement_index]
        merged = dict(statement)
        merged['booking_sources'] = (list(statement.get('booking_sources', [dict(rows[statement_index])]))
                                     + list(notice.get('booking_sources', [dict(notice)])))
        for field in ('quantity', 'per_share_amount', 'per_share_currency', 'gross_income',
                      'gross_currency', 'withholding_tax', 'withholding_country',
                      'withholding_tax_rate', 'tax_rate', 'document_reference'):
            if merged.get(field) in (None, '') and notice.get(field) not in (None, ''):
                merged[field] = notice[field]
        premerged[statement_index] = merged
        used.update((notice_index, statement_index))

    remaining = [tx for index, tx in enumerate(rows) if index not in used]
    rows = remaining + list(premerged.values())

    def match_key(tx):
        return tx['account'], tx['currency'], Decimal(tx['amount']), tx.get('value_date') or tx['date']
    groups = defaultdict(list)
    for index, tx in enumerate(rows):
        if tx['kind'] in ('DIVIDEND', 'BANK_BOOKING'):
            groups[match_key(tx)].append(index)
    used = set()
    for i, dividend in enumerate(rows):
        if i in used or dividend['kind'] != 'DIVIDEND':
            continue
        dividend['event_id'] = 'income-' + digest([dividend.get('depot', dividend['account']), dividend['external_id']])
        group = groups[match_key(dividend)]
        matches = [j for j in group if j != i and j not in used and not is_protected(rows[j])
                   and dividend_match(dividend, rows[j])]
        # Multiple occurrences on the same day require explicit reconciliation.
        if len(matches) != 1:
            if matches:
                dividend['reconciliation_required'] = True
            continue
        j = matches[0]
        rivals = [k for k in group if k != j and k not in used
                  and rows[k]['kind'] == 'DIVIDEND' and dividend_match(rows[k], rows[j])]
        if rivals != [i]:
            dividend['reconciliation_required'] = True
            continue
        other = rows[j]
        dividend['booking_sources'] = list(dividend.get('booking_sources', [dict(dividend)])) + list(other.get('booking_sources', [dict(other)]))
        # A statement proves the cash movement even when its notice is cash-neutral.
        dividend['affects_cash'] = dividend.get('affects_cash', True) or other.get('affects_cash', True)
        for field in ('gross_income', 'gross_currency', 'per_share_amount', 'per_share_currency',
                      'taxes', 'withholding_tax', 'solidarity_tax',
                      'withholding_country', 'withholding_tax_rate', 'tax_rate', 'bank_reference', 'document_reference',
                      'transaction_reference', 'performance_depot_key'):
            if dividend.get(field) in (None, '') and other.get(field) not in (None, ''):
                dividend[field] = other[field]
        if other.get('income_basis') == 'gross':
            dividend['income_basis'] = 'gross'
        used.add(j)
    return [tx for i, tx in enumerate(rows) if i not in used]


def performance_transactions(store, transactions, account=None):
    """Economic security cash flows, independent of affects_cash bookkeeping."""
    records = {r['account_key']: r for r in store.account_records() if r['active']}
    depot_names = {s['account'] for s in store.snapshots()}
    depot_names.update(r['name'] for r in records.values() if json.loads(r['details']).get('kind') == 'Depot')
    result = []
    # A settlement link describes two records of one economic event.  Prefer
    # the depot-side record for performance and keep the bank-side record only
    # as evidence.  The raw records remain untouched and visible in histories.
    from .transaction_reference import transaction_reference
    active_refs = {transaction_reference(tx) for tx in transactions}
    cash_allocations = defaultdict(Decimal)
    reconciled_notice_refs = set()
    try:
        for row in store.db.execute(
                "SELECT depot_ref,cash_ref,allocated_amount FROM transaction_reconciliations "
                "WHERE status IN ('matched','manual')"):
            # Only neutralize evidence that is inside the requested performance
            # boundary.  If one side is outside, the in-boundary cash flow must
            # remain visible instead of being silently consumed by a remote link.
            if row['depot_ref'] in active_refs and row['cash_ref'] in active_refs:
                cash_allocations[row['cash_ref']] += Decimal(row['allocated_amount'])
                reconciled_notice_refs.add(row['depot_ref'])
    except Exception:
        pass  # Older repositories without the additive reconciliation table.
    # A linked standalone FEE/TAX row only proves an amount already embedded
    # in its primary booking's net settlement (docs/fee_analysis.md).  Drop
    # such evidence rows from the flows — mirroring repository.fee_links()
    # validation — but only while both sides sit inside this boundary, so the
    # counted fee stays exactly the economic one.
    linked_fee_rows = set()
    try:
        links = [dict(row) for row in store.db.execute('SELECT aux_ref,field,fee_ref FROM fee_links')]
    except Exception:
        links = []  # Older repositories without the fee-link table.
    originals = {transaction_reference(tx): tx for tx in transactions}
    for link in links:
        aux, fee = originals.get(link['aux_ref']), originals.get(link['fee_ref'])
        field = link['field']
        if (not aux or not fee or link['aux_ref'] == link['fee_ref']
                or fee['kind'] != ('FEE' if field == 'fees' else 'TAX')):
            continue
        try:
            matches = (aux['account'] == fee['account'] and aux['currency'] == fee['currency']
                       and aux.get(field) is not None
                       and abs(Decimal(aux[field])) == abs(Decimal(fee['amount'])))
        except Exception:
            matches = False
        if matches:
            linked_fee_rows.add(link['fee_ref'])
    # A tax notice normally accompanies a Finanzreport row whose amount is
    # already net.  If the report is not available but a uniquely referenced
    # gross settlement notice is present, retain the cash-neutral tax helper
    # in the economic view so gross credit minus documented tax still yields
    # the proven net receipt.  Source rows and cash ledgers remain unchanged.
    gross_notice_tax_refs = set()
    by_external_id = {tx.get('external_id'): tx for tx in transactions if tx.get('external_id')}
    for record in store.model_records(kind='tax_events'):
        event = record['payload']
        paid = Decimal(str(event.get('paid_taxes') or 0))
        reference_no = str(event.get('reference_no') or '')
        tax = by_external_id.get(event.get('related_transaction_id'))
        if not tax or tax.get('kind') != 'TAX' or not paid or not reference_no:
            continue
        candidates = [tx for tx in transactions if tx.get('kind') == 'DIVIDEND'
                      and reference_no in {str(tx.get(field) or '') for field in
                                           ('bank_reference', 'document_reference',
                                            'transaction_reference')}
                      and abs(Decimal(str(tx.get('amount') or 0))) == abs(Decimal(str(
                          event.get('gross_income') or 0)))]
        if len(candidates) == 1:
            gross_notice_tax_refs.add(transaction_reference(tax))
    owners = None
    for original in transactions:
        ref = transaction_reference(original)
        if ref in linked_fee_rows:
            continue
        if (original.get('kind') in ('TAX', 'FEE')
                and not original.get('affects_cash', True)
                and ref not in reconciled_notice_refs
                and ref not in gross_notice_tax_refs):
            continue
        cash_allocation = cash_allocations.get(ref, Decimal())
        if cash_allocation:
            original_amount = Decimal(original['amount'])
            remaining = abs(original_amount) - cash_allocation
            if remaining < 0:
                raise ValueError('Geldbuchung ist durch Depotzuordnungen überbucht.')
            if not remaining:
                continue
            # This is an evaluation-only view of the unchanged source booking,
            # not a stored or invented transaction.  Auxiliary gross/tax/fee
            # values describe the original booking and must not be duplicated
            # on its residual share.
            original = dict(original, amount=str(remaining.copy_sign(original_amount)),
                            reconciliation_residual=True,
                            reconciliation_allocated=str(cash_allocation))
            for field in ('gross_income', 'fees', 'taxes', 'withholding_tax', 'solidarity_tax'):
                if field in original:
                    original[field] = None
        tx = dict(original, kind=kind_of(original))
        if tx['kind'] in ('BUY', 'SELL') and tx.get('performance_depot_key'):
            target = records.get(tx['performance_depot_key'])
            if not target or target['name'] not in depot_names:
                raise ValueError('Die Depotzuordnung eines Wertpapierkaufs ist nicht mehr gültig.')
            tx.update(account=target['name'], cash_account=original['account'],
                      performance_source=('Kauf' if tx['kind'] == 'BUY' else 'Verkauf')
                      + ' auf ' + original['account'])
        if tx['kind'] in PORTFOLIO_CASH_KINDS:
            explicit = tx.get('performance_depot_key')
            if owners is None:
                owners = _security_owners(store)
            candidates = depot_candidates(store, tx, owners) if tx.get('security') else []
            target = records.get(explicit) if explicit else None
            if explicit and (not target or target['name'] not in depot_names):
                raise ValueError('Die Depotzuordnung einer Dividende ist nicht mehr gültig.')
            if not explicit and tx['account'] not in depot_names:
                if len(candidates) == 1:
                    target = candidates[0]
                elif tx['kind'] == 'DIVIDEND' and (account is None or any(account_key(r['name']) == account_key(account) for r in candidates)):
                    raise ValueError('Dividende auf ' + tx['account'] + ': Depotzuordnung fehlt oder ist mehrdeutig. Bitte im Import auswählen.')
                else:
                    continue
            if target:
                tx.update(account=target['name'], cash_account=original['account'],
                          performance_source={'DIVIDEND': 'Dividende', 'TAX': 'Steuer',
                                              'TAX_REFUND': 'Steuererstattung', 'FEE': 'Gebühr'}[tx['kind']]
                          + ' auf ' + original['account'])
        if account and account_key(tx['account']) != account_key(account):
            continue
        if tx.get('reconciliation_required'):
            raise ValueError('Mehrere mögliche Belege für dieselbe Dividende. Bitte die doppelten Importe prüfen.')
        if tx['kind'] in ('BUY', 'SELL') and not tx.get('affects_cash', True):
            tx['amount'] = str(abs(Decimal(tx['amount'])) * (-1 if tx['kind'] == 'BUY' else 1))
        if tx.get('affects_cash', True) or tx['kind'] in (
                'DIVIDEND', 'TAX', 'TAX_REFUND', 'FEE', 'BUY', 'SELL', 'TRANSFER_IN', 'TRANSFER_OUT'):
            result.append(tx)
    return result
