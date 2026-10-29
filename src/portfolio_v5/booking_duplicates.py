"""Match overlapping bank feeds one occurrence at a time, within one account."""
from collections import defaultdict
from decimal import Decimal
import re
import unicodedata

from .accounts import account_key
from .booking_details import DETAIL_FIELDS


def normalized(value):
    text = unicodedata.normalize('NFKD', value or '').casefold()
    return ''.join(c for c in text if c.isalnum())


def channel(tx):
    identifier = tx.get('external_id', '')
    if 'pdf-' in identifier or str(tx.get('source', '')).lower().endswith('.pdf'): return 'pdf'
    if '-booking-' in identifier or str(tx.get('source', '')).lower().endswith('.bank'): return 'online'
    return 'other'


def reference(value):
    value = normalized(value)
    return '' if not value.strip('0') or value in ('nonref', 'notprovided', 'nichtangegeben', 'none', 'null', 'unbekannt') else value


def security_identifiers(tx):
    text = ' '.join(str(tx.get(key) or '') for key in ('security', 'purpose', 'booking_text', 'raw_text')).upper()
    result = set(re.findall(r'(?<![A-Z0-9])[A-Z]{2}[A-Z0-9]{9}\d(?![A-Z0-9])', text))
    result.update('WKN:' + value for value in re.findall(r'\b(?:WKN|WPKNR)\s*:?\s*([A-Z0-9]{6})\b', text))
    return result


def same_booking(a, b):
    if a.get('value_date') and b.get('value_date') and a['value_date'] != b['value_date']: return False
    if a.get('counterparty_iban') and b.get('counterparty_iban') and normalized(a['counterparty_iban']) != normalized(b['counterparty_iban']): return False
    # Explicit business references outrank a coincidentally identical amount,
    # date and security. Two orders for the same instrument must stay separate.
    # ``transaction_reference`` is intentionally excluded: legacy importers
    # populate it from the (sometimes line-wrapped) bank reference.
    for field in ('order_id', 'document_reference', 'execution_ref'):
        left, right = reference(a.get(field)), reference(b.get(field))
        if left and right and left != right:
            return False
    ra, rb = reference(a.get('bank_reference')), reference(b.get('bank_reference'))
    if ra and rb and ra == rb: return True
    # comdirect prints a long online bank reference across two PDF lines.
    for full, short, pdf in ((ra, rb, b), (rb, ra, a)):
        if channel(pdf) == 'pdf' and len(short) >= 10 and full.startswith(short) and len(full) > len(short):
            text = normalized(pdf.get('raw_text') or pdf.get('purpose'))
            if full[len(short):] in text: return True
    if ra and rb: return False  # Different identified payments are not twins.
    # A trade confirmation and its statement row use different references, or
    # only one side has a reference.  Matching valuta, amount and an explicit
    # WKN/ISIN identify the same security settlement.
    security_a, security_b = security_identifiers(a), security_identifiers(b)
    if security_a and security_a & security_b:
        return True
    if channel(a) == channel(b) == 'online': return False
    texts_a = {normalized(a.get(k)) for k in ('purpose', 'booking_text')} - {''}
    texts_b = {normalized(b.get(k)) for k in ('purpose', 'booking_text')} - {''}
    shared = texts_a & texts_b
    # Amount/date or a generic name such as "Überweisung" never suffice.
    generic = {'uberweisung','uberweisungsgutschr','gutschrift','lastschrift','zahlung','kontoabschluss',
               'zinsen','gebuhr','gebuhren','sparfesttermingeld','lastschriftbelastung','lastschrifteinzug',
               'ubertraguberweisung','auszahlunggaa','zinsgutschrift','kontoabschluss','dauerauftrag'}
    generic.update(normalized(tx.get('operation')) for tx in (a,b))
    return any(len(text) >= 12 and text not in generic for text in shared)


def financial_key(tx, target=None):
    day = (tx.get('value_date') or tx['date']) if security_identifiers(tx) else tx['date']
    return (target or account_key(tx['account']), day, Decimal(tx['amount']), tx['currency'])


def consolidate_bookings(store, transactions):
    """Retain source records, count identified payments once; undo stays valid."""
    import json
    tables = {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def ref(tx):
        return json.dumps([tx['import_id'], tx['depot'], tx['external_id']], ensure_ascii=False, separators=(',', ':'))
    protected = set()
    for table, columns in (('transaction_classifications', ('ref',)), ('transfer_pairs', ('first_ref','second_ref')),
                           ('fee_links', ('aux_ref','fee_ref'))):
        if table in tables:
            for row in store.db.execute('SELECT ' + ','.join(columns) + ' FROM ' + table): protected.update(row)
    if 'transaction_supersessions' in tables:
        hidden = {tuple(r) for r in store.db.execute('''SELECT s.old_import,s.old_account,s.old_id
                  FROM transaction_supersessions s JOIN imports i ON i.id=s.new_import WHERE i.active=1''')}
        transactions = [t for t in transactions if (t['import_id'],t['depot'],t['external_id']) not in hidden]
    groups, result = defaultdict(list), []
    for tx in transactions:
        if tx['kind'] == 'BANK_BOOKING': groups[financial_key(tx)].append(tx)
        else: result.append(tx)
    for rows in groups.values():
        by_import = defaultdict(list)
        for tx in rows: by_import[tx['import_id']].append(tx)
        kept = []
        order = sorted(by_import, key=lambda iid: (not any(ref(t) in protected for t in by_import[iid]), iid))
        for iid in order:
            used, additions = set(), []
            for tx in by_import[iid]:
                match = next((i for i, old in enumerate(kept) if i not in used and same_booking(tx, old)
                              and not (ref(tx) in protected and ref(old) in protected)), None)
                if match is None:
                    additions.append(dict(tx)); continue
                used.add(match)
                primary = kept[match]
                if 'booking_sources' not in primary: primary['booking_sources'] = [dict(primary)]
                primary['booking_sources'].append(dict(tx))
                for field in DETAIL_FIELDS:
                    value = tx.get(field, '')
                    if value and len(value) > len(primary.get(field, '')): primary[field] = value
                # A security settlement notice can document fees and instrument
                # details missing from the account statement.  Keep one cash
                # movement while enriching it with the evidenced fields.
                for field in ('security', 'quantity', 'fees', 'gross_amount', 'price', 'price_currency',
                              'trade_date', 'pay_date', 'cash_account', 'depot_account', 'security_ref',
                              'order_id', 'venue', 'document_reference', 'transaction_reference'):
                    if primary.get(field) in (None, '') and tx.get(field) not in (None, ''):
                        primary[field] = tx[field]
                if not primary.get('fee_items') and tx.get('fee_items'):
                    primary['fee_items'] = tx['fee_items']
                if tx.get('field_sources'):
                    primary.setdefault('field_sources', {}).update({
                        key: value for key, value in tx['field_sources'].items()
                        if key not in primary.get('field_sources', {})})
            kept.extend(additions)
        result.extend(kept)
    from .settlement import consolidate_dividends
    return consolidate_dividends(store, result, protected)
