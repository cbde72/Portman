"""Vorschau-Import einer Portfolio-Performance-XML-Datei (lesend, mit Zuordnung).

Die neutrale Vorschau löst Referenzen nach dem vollständigen Einlesen auf,
gleicht Wertpapiere (ISIN, dann Name) und Konten (normalisierter Name) gegen
den vorhandenen Bestand ab und markiert Dubletten über die PP-UUID, die
Portman-Referenz und einen fachlichen Fingerprint (Datum, Typ, Betrag,
Wertpapier). Geschrieben wird erst über :func:`save_pp_preview`.
"""
import xml.etree.ElementTree as ElementTree
from decimal import Decimal, InvalidOperation

from portfolio_v5.models import ImportBatch, BankTransaction, norm, digest

from .portfolio_performance_import import read_portfolio_performance_xml

CONTAINERS = {
    'securities': ('security',),
    'accounts': ('account', 'portfolio-account'),
    'portfolio-transactions': ('portfolio-transaction',),
    'transactions': ('transaction', 'portfolio-transaction'),
}

TRANSACTION_KINDS = {
    'buy': 'BUY', 'sell': 'SELL', 'delivery': 'SELL', 'purchase': 'BUY',
    'dividend': 'DIVIDEND', 'interest': 'INTEREST', 'fee': 'FEE', 'fees': 'FEE',
    'tax': 'TAX', 'taxes': 'TAX',
}

STORED_FIELDS = {'uuid', 'name', 'isin', 'wkn', 'ticker', 'currency'}


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _child(element, name):
    for candidate in element:
        if _local(candidate.tag) == name:
            return candidate
    return None


def _text(element, name, default=''):
    child = _child(element, name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _reference(element, name):
    child = _child(element, name)
    if child is None:
        return ''
    for attribute in ('reference', 'id', 'uuid'):
        value = child.attrib.get(attribute)
        if value:
            return value.strip()
    return (child.text or '').strip()


def _collect(root, container, singular):
    items = []
    for candidate in root.iter():
        if _local(candidate.tag) != container:
            continue
        for child in candidate:
            if _local(child.tag) in singular:
                items.append(child)
    return items


def parse_pp_xml(data):
    """Read a Portfolio Performance XML into neutral staging objects."""
    root = ElementTree.fromstring(data)
    version = root.attrib.get('version') or ''
    try:
        version = int(version) if version else None
    except ValueError:
        version = None
    securities = []
    for element in _collect(root, 'securities', CONTAINERS['securities']):
        securities.append({
            'uuid': _text(element, 'uuid') or element.attrib.get('id', ''),
            'name': _text(element, 'name'),
            'isin': _text(element, 'isin').upper(),
            'wkn': _text(element, 'wkn').upper(),
            'ticker': _text(element, 'ticker'),
            'currency': _text(element, 'currency') or 'EUR',
            'unknown_fields': sorted({_local(child.tag) for child in element}
                                     - STORED_FIELDS),
        })
    accounts = []
    for element in _collect(root, 'accounts', CONTAINERS['accounts']):
        accounts.append({
            'uuid': _text(element, 'uuid') or element.attrib.get('id', ''),
            'name': _text(element, 'name'),
            'currency': _text(element, 'currency') or 'EUR',
        })
    transactions = []
    for element in _collect(root, 'portfolio-transactions', CONTAINERS['portfolio-transactions']):
        transactions.append({
            'uuid': _text(element, 'uuid') or element.attrib.get('id', ''),
            'type': _text(element, 'type'),
            'date': _text(element, 'date')[:10],
            'amount': _text(element, 'amount'),
            'shares': _text(element, 'shares'),
            'fees': _text(element, 'fees'),
            'taxes': _text(element, 'taxes'),
            'currency': _text(element, 'currency') or 'EUR',
            'note': _text(element, 'note'),
            'account_uuid': _reference(element, 'account'),
            'security_uuid': _reference(element, 'security'),
        })
    return {'version': version, 'securities': securities, 'accounts': accounts,
            'transactions': transactions}


def _decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _amount_key(value):
    number = _decimal(value)
    if number is None:
        return ''
    return format(abs(number).normalize(), 'f')


def _signed_amount(kind, amount):
    number = _decimal(amount)
    if number is None:
        return None
    magnitude = abs(number)
    return -magnitude if kind in ('BUY', 'FEE', 'TAX') else magnitude


def _fingerprints(repo):
    fingerprints = {}
    for transaction in repo.transactions():
        key = (str(transaction.get('date') or ''), transaction.get('kind') or '',
               _amount_key(transaction.get('amount')), transaction.get('security') or '')
        fingerprints[key] = transaction.get('external_id') or ''
    return fingerprints


def build_preview(repo, parsed, source=''):
    """Match securities/accounts against the repository and flag duplicates."""
    positions = repo.current('9999-12-31')
    by_isin = {str(p.get('isin') or '').upper(): p for p in positions if p.get('isin')}
    by_name = {str(p.get('name') or ''): p for p in positions if p.get('name')}
    securities = {}
    for security in parsed['securities']:
        match = None
        if security['isin'] and security['isin'] in by_isin:
            match = by_isin[security['isin']]
        elif security['name'] and security['name'] in by_name:
            match = by_name[security['name']]
        securities[security['uuid']] = {
            **security, 'matched': match is not None,
            'matched_key': match['key'] if match else '',
            'matched_name': match['name'] if match else '',
        }
    known_accounts = {norm(name): name for name in repo.accounts()}
    accounts = {}
    for account in parsed['accounts']:
        accounts[account['uuid']] = {
            **account, 'assignment': known_accounts.get(norm(account['name'])),
        }
    fingerprints = _fingerprints(repo)
    external_ids = {value for value in fingerprints.values() if value}
    used = set()
    rows = []
    for transaction in parsed['transactions']:
        kind = TRANSACTION_KINDS.get(transaction['type'].casefold(), '')
        amount = _signed_amount(kind, transaction['amount'])
        security = securities.get(transaction['security_uuid'])
        account = accounts.get(transaction['account_uuid'])
        external_id = f"pp:{transaction['uuid']}" if transaction['uuid'] else ''
        security_label = (security or {}).get('matched_key') or (security or {}).get('isin') or ''
        fingerprint = (transaction['date'], kind, _amount_key(amount), security_label)
        status, duplicate_of = 'ok', ''
        if not kind or amount is None:
            status = 'invalid'
        elif security is None or (not security['matched'] and not security['isin']):
            status = 'unknown_security'
        elif account is None or not account['assignment']:
            status = 'unknown_account'
        if status == 'ok':
            if external_id and external_id in external_ids:
                status, duplicate_of = 'duplicate', external_id
            elif fingerprint in fingerprints:
                status, duplicate_of = 'duplicate', fingerprints[fingerprint]
            elif fingerprint in used:
                status, duplicate_of = 'duplicate', 'Dateidublette'
            else:
                used.add(fingerprint)
        rows.append({
            **transaction, 'kind': kind,
            'signed_amount': str(amount) if amount is not None else '',
            'account': (account or {}).get('assignment') or '',
            'account_name': (account or {}).get('name') or '',
            'security_key': (security or {}).get('matched_key') or '',
            'security_name': (security or {}).get('name') or '',
            'isin': (security or {}).get('isin') or '',
            'external_id': external_id, 'status': status, 'duplicate_of': duplicate_of,
        })
    summary = {
        'version': parsed['version'], 'source': source,
        'securities': len(parsed['securities']),
        'securities_matched': sum(1 for s in securities.values() if s['matched']),
        'accounts': len(parsed['accounts']),
        'accounts_matched': sum(1 for a in accounts.values() if a['assignment']),
        'transactions': len(rows),
        'importable': sum(1 for row in rows if row['status'] == 'ok'),
        'duplicates': sum(1 for row in rows if row['status'] == 'duplicate'),
        'unknown_security': sum(1 for row in rows if row['status'] == 'unknown_security'),
        'unknown_account': sum(1 for row in rows if row['status'] == 'unknown_account'),
        'invalid': sum(1 for row in rows if row['status'] == 'invalid'),
    }
    return {'version': parsed['version'], 'source': source,
            'securities': list(securities.values()), 'accounts': list(accounts.values()),
            'transactions': rows, 'summary': summary}


def preview_pp_xml(repo, data, source=''):
    return build_preview(repo, parse_pp_xml(data), source)


def preview_pp_file(repo, path):
    payload = read_portfolio_performance_xml(path)
    return build_preview(repo, parse_pp_xml(payload), str(path))


def save_pp_preview(repo, preview, account_map=None):
    account_map = account_map or {}
    entries = []
    for row in preview['transactions']:
        if row['status'] not in ('ok', 'unknown_account'):
            continue
        account = (account_map.get(row['account_uuid']) if row['account_uuid'] else '') or row['account']
        if not account:
            continue
        entries.append((row, account))
    if not entries:
        return {'imported': 0, 'external_ids': []}
    batch = ImportBatch(preview.get('source') or 'Portfolio Performance XML',
                        digest(preview.get('source') or 'pp'),
                        source_sheet='Portfolio Performance XML',
                        account_names=sorted({account for _, account in entries}))
    for row, account in entries:
        batch.transactions.append(BankTransaction(
            account, row['external_id'] or f"pp:{row['uuid']}", row['date'], row['kind'],
            row['signed_amount'], row['currency'], row['security_key'] or row['isin'],
            row['shares'] or None, fees=row['fees'] or None, taxes=row['taxes'] or None,
            purpose=row['note']))
    repo.commit_batches([batch])
    return {'imported': len(entries), 'external_ids': [row['external_id'] for row, _ in entries]}
