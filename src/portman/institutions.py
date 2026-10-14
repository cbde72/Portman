"""Institution grouping shared by storage operations and the account tree."""
import json
import re


def account_institution(record, records):
    """Prefer explicit details; inherit missing institutions from parent accounts."""
    aliases = {'comdirect': 'comdirect', 'ing': 'ING', 'ing diba': 'ING',
               'ing-diba': 'ING', 'finanzen zero': 'Finanzen zero',
               'finanzen.net zero': 'Finanzen zero', 'zero': 'Finanzen zero',
               'trade republic': 'Trade Republic', 'deka': 'Deka',
               'dkb': 'DKB', 'commerzbank': 'Commerzbank', 'deutsche bank': 'Deutsche Bank'}
    lineage, seen = [], set()
    while record and record['account_key'] not in seen:
        seen.add(record['account_key'])
        lineage.append(record)
        institution = ' '.join(json.loads(record['details']).get('institution', '').split())
        if institution:
            return institution
        record = records.get(record['parent_key'])
    for record in lineage:
        for prefix in sorted(aliases, key=len, reverse=True):
            if re.match(re.escape(prefix) + r'(?:\b|_)', record['name'].casefold()):
                return aliases[prefix]
    return 'Ohne Institut'

