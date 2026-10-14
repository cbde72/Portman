"""Auditable EUR estimates; replace the securities category, never add it twice."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
import urllib.request
import xml.etree.ElementTree as ET

ECB_URL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'


def fetch_fx():
    with urllib.request.urlopen(ECB_URL, timeout=12) as response:
        root = ET.fromstring(response.read())
    day = next(node for node in root.iter() if 'time' in node.attrib)
    date.fromisoformat(day.attrib['time'])
    rates = {node.attrib['currency']: str(Decimal(node.attrib['rate'])) for node in day
             if 'currency' in node.attrib}
    if not rates or any(not Decimal(v).is_finite() or Decimal(v) <= 0 for v in rates.values()):
        raise ValueError('Ungültige EZB-Wechselkurse')
    return {'date': day.attrib['time'], 'rates': rates, 'source': ECB_URL}


def eur_value(amount, currency, fx, today):
    if currency == 'EUR': return amount
    if currency in ('GBp', 'GBX'): amount /= 100; currency = 'GBP'
    if not fx or not 0 <= (today - date.fromisoformat(fx['date'])).days <= 7:
        return None
    rate = Decimal(fx.get('rates', {}).get(currency, '0'))
    return amount / rate if rate.is_finite() and rate > 0 else None


def current_wealth(repo, account=None, today=None):
    today = today or date.today(); baseline = repo.wealth_summary(today.isoformat(), account)
    period = baseline['period']; fx = repo.market.fx(); records = repo.market.records()
    balances = baseline.get('rows', [])
    groups = defaultdict(list)
    for p in repo.holdings(today.isoformat(), account): groups[p['account']].append(p)
    snapshots = [s for s in repo.snapshots(account) if s['effective_date'] <= today.isoformat()]
    for s in snapshots: groups.setdefault(s['account'], [])
    rows = []
    for b in balances:
        value = Decimal(b['value']) * (-1 if b['category'] == 'Schulden' else 1)
        rows.append({'account': b['account'], 'category': b['category'], 'original': value,
                     'value': value, 'source': b.get('source') or 'Importierter Kontosaldo', 'date': b.get('state_date', b.get('effective_date', b.get('period', ''))),
                     'note': 'Gespeicherter Saldo; kein Live-Banksaldo', 'currency': 'EUR'})
    # Index once instead of rescanning all rows/snapshots per account.
    securities_by_account = defaultdict(list)
    for r in rows:
        if r['category'] == 'Wertpapiere':
            securities_by_account[r['account']].append(r)
    snapshots_by_account = defaultdict(list)
    for s in snapshots:
        snapshots_by_account[s['account']].append(s)
    removed_rows = set()
    details = []
    for name, positions in groups.items():
        target = securities_by_account.get(name, [])
        reasons = []; valued = []; dates = []
        details_start = len(details)
        for p in positions:
            d = p.get('as_of')
            if not d or not 0 <= (today - date.fromisoformat(d)).days <= 45 or (period and d[:7] < period):
                reasons.append('Bestand veraltet oder ohne genaues Datum'); continue
            record = records.get(p['key'], {}); data = record.get('data', {}); manual = record.get('manual', {})
            fields = manual.get('fields', {})
            if 'price' in fields:
                price, currency, stamp = fields['price'], fields.get('currency'), manual['as_of']
                source = manual['source']
            else:
                price, currency, stamp = data.get('metrics', {}).get('price'), data.get('currency'), data.get('quote_time', '')[:10]
                source = data.get('source_url', '')
            value = None
            if price is not None and stamp and 0 <= (today - date.fromisoformat(stamp)).days <= 7 and stamp >= d and p.get('quantity') is not None:
                value = eur_value(Decimal(str(price)) * Decimal(p['quantity']), currency, fx, today)
            note = (f"{p['quantity']} × {price} {currency}; "
                    + ('EUR-Kurs' if currency == 'EUR' else f"EZB {fx['date']}, Fremdwährung je EUR: {fx['rates'].get('GBP' if currency in ('GBp', 'GBX') else currency)}"
                       + ('; 100 Pence = 1 GBP' if currency in ('GBp', 'GBX') else ''))
                    if value is not None else 'Importierter Depotwert; Kurs/Wechselkurs fehlt oder ist älter als Bestand')
            if value is None:
                if p.get('value') is None:
                    reasons.append('Kein belegter Kurswert für den fortgeschriebenen Bestand'); continue
                if p.get('currency') != 'EUR': reasons.append('Positionswährung nicht umrechenbar'); continue
                value = Decimal(p['value']); stamp = p.get('quote_date') or d; source = p['source']
                note = p.get('valuation_note', note)
            value = value.quantize(Decimal('.01'))
            valued.append(value); dates.append(stamp)
            details.append({**p, 'estimated_value': value, 'valuation_date': stamp, 'valuation_source': source,
                            'valuation_note': note, 'quote_currency': currency or p.get('currency', '')})
        # A partial/old account must never silently replace its complete overview balance.
        latest = {}
        for s in snapshots_by_account.get(name, ()):
            latest[s['depot']] = s
        if any(not s['complete'] for s in latest.values()): reasons.append('Unvollständiger Depotstand')
        for s in latest.values():
            d = s['as_of']
            if not d or not 0 <= (today - date.fromisoformat(d)).days <= 45 or (period and d[:7] < period):
                reasons.append('Bestand veraltet oder ohne genaues Datum')
        if reasons:
            for r in target: r['note'] = '; '.join(sorted(set(reasons))) + ' – Kontosaldo beibehalten'
            for p in details[details_start:]:
                p['valuation_note'] += ' · NICHT in Gesamtschätzung übernommen'
            continue
        if not valued and not latest: continue
        if not dates: dates = [s['as_of'] for s in latest.values()]
        value = sum(valued, Decimal(0))
        original = sum((r['original'] for r in target), Decimal(0)) if target else None
        removed_rows.update(id(r) for r in target)
        rows.append({'account': name, 'category': 'Wertpapiere', 'original': original, 'value': value,
                     'source': 'Depotbewertung', 'date': min(dates) + ' bis ' + max(dates),
                     'currency': 'EUR', 'note': 'Ersetzt den Wertpapier-Kontosaldo; enthält ggf. importierte Ersatzwerte'})
    if removed_rows:
        rows = [r for r in rows if id(r) not in removed_rows]
    total = sum((r['value'] for r in rows), Decimal(0)) if rows else None
    return {'value': total, 'baseline': baseline['value'], 'period': period, 'rows': rows, 'positions': details,
            'fx_date': fx.get('date') if fx else None,
            'missing_accounts': [a for a in repo.accounts() if (account is None or a == account) and not any(r['account'] == a for r in rows)]}
