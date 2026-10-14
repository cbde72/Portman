"""Keep booking identities when rereading the exact same PDF with a new reader."""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
import json
import re

from .accounts import account_key


def preserve_booking_ids(store, batch):
    if not batch.file_hash or not batch.transactions or batch.source_sheet != 'PDF':
        return batch
    imports = [r['id'] for r in store.db.execute(
        "SELECT id FROM imports WHERE active=1 AND json_extract(report,'$.source_sha256')=? ORDER BY id",
        (batch.file_hash,))]
    if not imports:
        return batch
    previous = {}
    for iid in imports:
        targets = {r['source_key']: r['account_key'] for r in store.db.execute(
            'SELECT source_key,account_key FROM import_account_links WHERE import_id=?', (iid,))}
        for row in store.db.execute('SELECT payload FROM transactions WHERE import_id=? ORDER BY id', (iid,)):
            tx = json.loads(row['payload'])
            source = account_key(tx['account'])
            if (tx['external_id'].startswith(('comdirect-pdf-', 'pdf-booking-')) and
                    targets.get(source, source) == batch.account_assignments.get(source, source)):
                previous[(tx['account'], tx['external_id'])] = tx
    result = deepcopy(batch)
    def key(tx):
        return tx['account'], tx['date'], tx.get('value_date', ''), Decimal(tx['amount'])
    old_groups, new_groups = defaultdict(list), defaultdict(list)
    for tx in previous.values():
        old_groups[key(tx)].append(tx)
    for tx in result.transactions:
        new_groups[key(vars(tx))].append(tx)
    for signature, incoming in new_groups.items():
        old = old_groups[signature]
        if len(old) == len(incoming):
            # Identical file bytes, source account, target, dates, amount and
            # multiplicity: retain the original table order and duplicate count.
            pairs = zip(incoming, old)
        else:
            # Previously only part of this amount/date group was selected.
            # Reuse only textual matches; do not guess which occurrence it was.
            matches = defaultdict(list)
            for tx in old:
                matches[re.sub(r'\s+', '', tx.get('purpose', ''))].append(tx)
            pairs = []
            for tx in incoming:
                candidates = matches[re.sub(r'\s+', '', tx.purpose)]
                if candidates:
                    pairs.append((tx, candidates.pop(0)))
        for tx, previous_tx in pairs:
            tx.external_id = previous_tx['external_id']
    # Older readers stored a Konto number where the current reader knows the
    # IBAN. Supersede the old occurrence only for the same file and target.
    def canonical(source):
        if source.startswith('IBAN DE'): return source[-10:].lstrip('0')
        if source.startswith('Konto '): return source[6:].lstrip('0')
        return source
    aliases = defaultdict(list)
    for old in store.transactions():
        if old['import_id'] in imports and old['kind'] == 'BANK_BOOKING':
            aliases[(canonical(old['depot']), account_key(old['account']), old['date'],
                     old.get('value_date',''), Decimal(old['amount']))].append(old)
    incoming_aliases = defaultdict(list)
    for tx in result.transactions:
        source = account_key(tx.account)
        target = result.account_assignments.get(source, source)
        incoming_aliases[(canonical(tx.account), target, tx.date, tx.value_date, Decimal(tx.amount))].append(tx)
    for signature, incoming in incoming_aliases.items():
        existing = [t for t in aliases.get(signature, []) if t['depot'] != incoming[0].account]
        if len(existing) == len(incoming):
            for old in existing:
                ref = dict(import_id=old['import_id'], depot=old['depot'], external_id=old['external_id'])
                if ref not in result.replace_bank_bookings: result.replace_bank_bookings.append(ref)
    return result
