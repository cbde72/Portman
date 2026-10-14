import json
import re
from collections import defaultdict
from decimal import Decimal
from portfolio_v5.models import valid_isin

from .chart_cache import cached_series
from .institutions import account_institution


def purchase_flows(repo):
    return cached_series(repo, ('depot_purchase_flows',), lambda: _purchase_flows(repo))


def _purchase_flows(repo):
    records = {r['account_key']: r for r in repo.account_records()}
    banks = {}
    for record in records.values():
        institution = account_institution(record, records).casefold()
        bank = 'comdirect' if 'comdirect' in institution else 'ing' if re.match(r'ing\b', institution) else None
        if bank:
            banks[record['name']] = bank
    securities = {}
    for snap in repo.snapshots():
        if snap['account'] not in banks:
            continue
        for p in json.loads(snap['payload'])['positions']:
            for identifier in (p.get('isin'), 'WKN:' + p['wkn'] if p.get('wkn') else ''):
                if identifier:
                    securities.setdefault((banks[snap['account']], identifier), set()).add(snap['account'])
    transactions = repo.transactions()
    direct = defaultdict(list)
    for t in transactions:
        if t['kind'] == 'BUY':
            direct[t['account']].append({**t, 'amount': str(-abs(Decimal(t['amount'])))})
    result = []
    for tx in transactions:
        bank = banks.get(tx['account'])
        if not bank or tx['kind'] != 'BANK_BOOKING' or Decimal(tx['amount']) >= 0:
            continue
        text = ' '.join(str(tx.get(k) or '') for k in ('purpose', 'booking_text', 'operation')).upper()
        if any(word in text for word in ('STORNO', 'GEBÜHR', 'ENTGELT', 'STEUER', 'DIVIDEND', 'ERTRAG', 'VERKAUF')):
            continue
        if bank == 'ing':
            if not ('WP.ABRECHNUNG' in text and 'KAUF' in text):
                continue
        elif not ('WERTPAPIERE' in text or ('WPKNR:' in text and 'ISIN:' in text)):
            continue
        compact = re.sub(r'\s+', '', text)
        wkn = re.search(r'WPKNR:\s*([A-Z0-9]{6})', text)
        identifiers = {identifier for provider, identifier in securities
                       if provider == bank and not identifier.startswith('WKN:') and identifier in compact}
        if wkn:
            identifiers.add('WKN:' + wkn[1])
        parsed_isin = re.search(r'ISIN\s*:?\s*([A-Z]{2}[A-Z0-9]{9}\d)', text)
        if parsed_isin and valid_isin(parsed_isin[1]):
            identifiers.add(parsed_isin[1])
        matches = {account for identifier in identifiers
                   for account in securities.get((bank, identifier), set())}
        # A holding in the same bank must identify exactly one destination depot.
        if len(matches) != 1:
            continue
        account = next(iter(matches))
        security = next(iter(sorted(identifiers, key=lambda v: v.startswith('WKN:'))))
        buyers = direct.get(account)
        duplicate = next((i for i, t in enumerate(buyers) if t.get('security') in identifiers
               and Decimal(t['amount']) == Decimal(tx['amount'])
               and ({t['date'], t.get('value_date')} - {None, ''})
                   & ({tx['date'], tx.get('value_date')} - {None, ''})
               and (not t.get('bank_reference') or not tx.get('bank_reference')
                    or t['bank_reference'] == tx['bank_reference'])), None) if buyers else None
        if duplicate is not None:
            direct[account].pop(duplicate)
            continue
        result.append({**tx, 'account': account, 'kind': 'BUY', 'security': security,
            'cash_account': tx['account'], 'performance_source': 'Kaufzahlung auf ' + tx['account'],
            'affects_cash': False})
    return result
