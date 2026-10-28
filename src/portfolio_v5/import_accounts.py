"""Source identities and narrowly scoped reusable import-account suggestions."""
import re
import json
from pathlib import Path
from .accounts import account_key, account_name


def import_sources(batch):
    sources = {}
    for kind, values in [('Depotstände', batch.snapshots), ('Salden', batch.balances),
                         ('Transaktionen', batch.transactions),
                         ('Buchungsbelege', batch.booking_evidence), ('Dokumente', batch.documents)]:
        for value in values:
            if value.account == 'Archiv':
                continue
            key = account_key(value.account)
            item = sources.setdefault(key, {'key': key, 'name': value.account, 'kinds': set(), 'count': 0})
            item['kinds'].add(kind); item['count'] += 1
    for kind, values in [('Steuerereignisse', batch.tax_events), ('Steuerdetails', batch.tax_details),
                         ('Kosteninformationen', batch.cost_reports)]:
        for value in values:
            key = account_key(value.account)
            item = sources.setdefault(key, {'key': key, 'name': value.account, 'kinds': set(), 'count': 0})
            item['kinds'].add(kind); item['count'] += 1
    for name in batch.account_names:
        key = account_key(name)
        sources.setdefault(key, {'key': key, 'name': name, 'kinds': {'Kontoname'}, 'count': 0})
    return sorted(sources.values(), key=lambda r: r['name'].casefold())


def required_target_kind(source):
    """Return the account kind mandated by the imported facts, if any."""
    return 'Depot' if source['kinds'] & {'Steuerereignisse', 'Steuerdetails', 'Kosteninformationen'} else ''


def target_compatible(record, required_kind):
    if not required_kind:
        return True
    return json.loads(record.get('details') or '{}').get('kind') == required_kind


def rule_scope(path):
    path = Path(path).resolve()
    # Remove date tokens, but preserve identifiers/account numbers and directories.
    family = re.sub(r'(?<!\d)(?:19|20)\d{2}[-_.]?(?:0[1-9]|1[0-2])(?:[-_.]?(?:0[1-9]|[12]\d|3[01]))?(?!\d)', '{datum}', path.stem)
    family = re.sub(r'(?<!\d)(?:0[1-9]|[12]\d|3[01])[._-](?:0[1-9]|1[0-2])[._-](?:19|20)\d{2}(?!\d)', '{datum}', family)
    # Export timestamps following a date are also variable, not bank identifiers.
    family = re.sub(r'(\{datum\})[-_]\d{4,6}$', r'\1-{zeit}', family)
    return str(path.parent).casefold() + '/' + family.casefold() + path.suffix.lower()


def pdf_account_match(name, records, *, required_kind='', bank=''):
    """Match bank identifiers in account details or complete numbers in names."""
    match = re.fullmatch(r'(IBAN|Konto|Depot)\s+(.+)', name, re.I)
    if not match:
        return None, ''

    def iban(value):
        return re.sub(r'\s+', '', str(value or '')).upper()

    def number(value):
        value = re.sub(r'[\s.\-]', '', str(value or '')).upper()
        return (value.lstrip('0') or '0') if value.isdigit() else value

    def german_number(value):
        if not re.fullmatch(r'DE\d{20}', value):
            return ''
        if int(value[4:] + '1314' + value[2:4]) % 97 != 1:
            return ''
        return number(value[-10:])

    kind, identifier = match.groups()
    source_iban = iban(identifier) if kind.upper() == 'IBAN' else ''
    source_number = german_number(source_iban) if source_iban else number(identifier)
    exact, numbers, names = set(), set(), set()
    for key, record in records.items():
        if not record['active']:
            continue
        if not target_compatible(record, required_kind):
            continue
        details = json.loads(record.get('details') or '{}')
        stored_iban = iban(details.get('iban'))
        if source_iban and stored_iban == source_iban:
            exact.add(key)
        # An explicit different IBAN rules out a match on its account suffix.
        if source_iban and stored_iban and source_iban != stored_iban:
            continue
        stored_numbers = {number(details.get('number'))}
        if kind.casefold() != 'depot':
            stored_numbers.add(german_number(stored_iban))
        if source_number and source_number in stored_numbers:
            numbers.add(key)
        # Compare entire digit runs, so 5884205500 does not match 15884205500.
        name_numbers = {number(token) for token in re.findall(r'\d+', record['name'])}
        if source_number and source_number in name_numbers:
            names.add(key)
    matches = exact or (numbers | names)
    if len(matches) == 1:
        target = next(iter(matches))
        reason = ('IBAN stimmt mit Kontodetails überein' if exact else
                  'Kontonummer stimmt mit Kontodetails überein' if target in numbers else
                  'Kontonummer im Kontonamen gefunden')
        return target, reason
    if matches:
        return None, 'Kontokennung passt zu mehreren vorhandenen Konten – bitte Ziel wählen'
    # comdirect appends a two-digit subaccount identifier to depot numbers on
    # tax notices.  This is deliberately bank-, source- and target-specific:
    # no digit is removed generically, and only one existing Depot may match.
    if bank == 'comdirect' and kind.casefold() == 'depot' and identifier.isdigit():
        subaccount_matches = set()
        for key, record in records.items():
            if not record['active'] or not target_compatible(record, 'Depot'):
                continue
            details = json.loads(record.get('details') or '{}')
            candidates = {number(details.get('number'))}
            candidates.update(number(token) for token in re.findall(r'\d+', record['name']))
            if any(candidate and identifier == candidate + identifier[-2:]
                   for candidate in candidates):
                subaccount_matches.add(key)
        if len(subaccount_matches) == 1:
            return next(iter(subaccount_matches)), 'comdirect-Depotnummer mit Unterkontokennung stimmt eindeutig überein'
        if subaccount_matches:
            return None, 'comdirect-Depotkennung passt zu mehreren Depots – bitte Ziel wählen'
    return None, ''


def tax_depot_from_cash_account(source, batch, records):
    """Infer one tax-event depot through its documented settlement IBAN.

    This is intentionally restricted to the parser's generic comdirect depot
    placeholder.  Explicit depot numbers continue through pdf_account_match,
    and ambiguous or missing links always remain a manual decision.
    """
    if source['name'].casefold() != 'comdirect depot' \
            or not source['kinds'] & {'Steuerereignisse', 'Steuerdetails'}:
        return None, ''
    cash_names = {event.cash_account for event in batch.tax_events
                  if account_key(event.account) == source['key'] and event.cash_account}
    if len(cash_names) != 1:
        return None, ('Keine eindeutige IBAN im Steuerbeleg – bitte Depot wählen'
                      if cash_names else '')
    cash_key, cash_reason = pdf_account_match(next(iter(cash_names)), records)
    if not cash_key:
        return None, (cash_reason or
                      'Verrechnungskonto zur belegten IBAN nicht gefunden – bitte Depot wählen')
    linked = set()
    for key, record in records.items():
        if not record['active']:
            continue
        details = json.loads(record.get('details') or '{}')
        if details.get('kind') == 'Depot' and details.get('cash_account_key') == cash_key:
            linked.add(key)
    if len(linked) == 1:
        return next(iter(linked)), 'Depot über eindeutig erkanntes Verrechnungskonto vorgeschlagen'
    if linked:
        return None, 'Mehrere Depots nutzen das erkannte Verrechnungskonto – bitte Depot wählen'
    return None, 'Kein Depot mit dem erkannten Verrechnungskonto verknüpft – bitte Depot wählen'


def suggest_accounts(store, batch):
    records = store._account_view()
    rules = {r['source_key']: r['account_key'] for r in store.db.execute(
        'SELECT * FROM import_account_rules WHERE scope=?', (rule_scope(batch.path),))}
    depot_mappings = store._depot_mappings()
    suggestions = []
    for source in import_sources(batch):
        key = source['key']
        target_kind = required_target_kind(source)
        rule = rules.get(key)
        if rule is not None:
            record = records.get(rule, {})
            target = rule if record.get('active') and target_compatible(record, target_kind) else None
            reason = ('Gespeicherte Importregel' if target else
                      'Gespeichertes Zielkonto ist gelöscht oder kein Depot – bitte neu wählen')
        else:
            banks = [name for name in ('comdirect', 'renault', 'baader', 'ing')
                     if re.search(r'\b' + name + r'\b', batch.pdf_text, re.I)]
            bank = banks[0] if len(banks) == 1 else ''
            target, reason = tax_depot_from_cash_account(source, batch, records)
            if not reason:
                target, reason = pdf_account_match(
                    source['name'], records, required_kind=target_kind, bank=bank
                ) if batch.source_sheet == 'PDF' else (None, '')
            if not reason:
                target = depot_mappings.get(key, key)
                if target in records and not target_compatible(records[target], target_kind):
                    target = None
            if reason:
                pass
            elif target in records and records[target]['active']:
                reason = 'Vorhandene Depotzuordnung' if target != key else 'Passender Kontoname'
            elif target in records:
                target = None; reason = 'Konto gelöscht – bitte Zielkonto wählen'
            else:
                parent = account_key(source['name'].split('/', 1)[0])
                if parent in records and records[parent]['active']:
                    target = parent; reason = 'Passendes übergeordnetes Konto'
                else:
                    target = None; reason = 'Kein bestehendes Konto erkannt – Konto aus Quelle anlegen oder Ziel wählen'
        suggestions.append({**source, 'target_key': target, 'reason': reason,
                            'new_name': (account_name(source['name'])
                                         if key not in records and not target_kind else None),
                            'required_kind': target_kind,
                            'remembered': key in rules, 'scope': rule_scope(batch.path)})
    return suggestions
