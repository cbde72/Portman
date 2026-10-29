"""Evidence-aware comparable coverage, unit replay and contribution reports."""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from html import escape
from pathlib import Path
import json
from .repository_v09 import reference
from portfolio_v5.accounts import account_key

ZERO = Decimal(0)


def transfer_candidates(repo):
    paired = {p[k] for p in repo.transfer_pairs(include_invalid=True) for k in ('first_ref', 'second_ref')}
    index = defaultdict(list)
    result = []
    for tx in repo.transactions():
        if reference(tx) in paired or tx.get('security') or tx['kind'] not in ('BANK_BOOKING','DEPOSIT','WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT'): continue
        amount = Decimal(tx['amount'])
        if not amount: continue
        for other in index[(tx['currency'], -amount)]:
            if other['account'] != tx['account'] and abs((date.fromisoformat(tx['date'])-date.fromisoformat(other['date'])).days) <= 3:
                result.append((other, tx))
        index[(tx['currency'], amount)].append(tx)
    return result


def change_analysis(repo, start, end, account=None):
    date.fromisoformat(start); date.fromisoformat(end)
    if start >= end: raise ValueError('Der Beginn muss vor dem Ende liegen.')
    first = {(p['depot'],p['key']): p for p in repo.holdings(start)}
    last = {(p['depot'],p['key']): p for p in repo.holdings(end)}
    boundaries = {}
    for s in repo.snapshots():
        for day in (start,end):
            if s['effective_date'] <= day: boundaries[(s['depot'],day)] = s
    def complete(depot, day):
        s = boundaries.get((depot,day))
        return bool(s and s['complete'] and s['as_of'] == day)
    def units(p, depot, day):
        return Decimal(p['quantity']) if p and p.get('quantity') is not None else ZERO if not p and complete(depot,day) else None
    def value(p, depot, day):
        return Decimal(p['value']) if p and p.get('value') is not None else ZERO if not p and complete(depot,day) else None
    txs = [t for t in repo.transactions(account) if start < t['date'] <= end]
    replay_txs=[t for t in repo.transactions() if start<t['date']<=end]
    expected = {k: units(p,k[0],start) for k,p in first.items()}
    movements = defaultdict(lambda: ZERO)
    unknown_keys = set(); unknown = []
    actions = repo.actions(start,end)
    events = [(t['date'], 1000000+i, 'tx', t) for i,t in enumerate(replay_txs)]
    # Recorded sequence < 1,000,000 is before that day's bookings; larger is after.
    events += [(a['day'], a['sequence'], 'action', a) for a in actions]
    changed_by_action = set()
    for day, sequence, kind, item in sorted(events, key=lambda e: (e[0],e[1])):
        key = (item.get('depot',item.get('account')), item.get('security'))
        if kind == 'tx':
            if item['kind'] not in ('BUY','SELL','TRANSFER_IN','TRANSFER_OUT'): continue
            if item.get('quantity') is None or not item.get('security'):
                unknown.append(item); unknown_keys.add(key[0]); continue
            delta = abs(Decimal(item['quantity'])) * (-1 if item['kind'] in ('SELL','TRANSFER_OUT') else 1)
            movements[key] += delta
            initial = expected.get(key, ZERO if complete(key[0],start) else None)
            expected[key] = initial + delta if initial is not None else None
        else:
            changed_by_action.add(key)
            q = expected.get(key, ZERO if complete(key[0],start) else None)
            if item['kind'] == 'SPLIT': expected[key] = q * Decimal(item['ratio']) if q is not None else None
            else:
                target = (item['target_depot'] or key[0], item['target'] or key[1]); changed_by_action.add(target)
                moved = Decimal(item['units']) if item['kind'] == 'TRANSFER' else q
                before = expected.get(target, ZERO if complete(target[0],start) else None)
                expected[target] = before + moved * Decimal(item['ratio']) if before is not None and moved is not None else None
                expected[key] = q - moved if q is not None and moved is not None else None
    positions = []
    coverage = {}
    for key in sorted(first.keys() | last.keys() | movements.keys() | expected.keys()):
        a,b = first.get(key),last.get(key); p = b or a or {}
        position_account=p.get('account') or (boundaries.get((key[0],end)) or boundaries.get((key[0],start)) or {}).get('account')
        if account and account_key(position_account or '')!=account_key(account): continue
        qa,qb = units(a,key[0],start),units(b,key[0],end)
        va,vb = value(a,key[0],start),value(b,key[0],end)
        predicted = expected.get(key,qa)
        difference = qb - predicted if qb is not None and predicted is not None else None
        name = p.get('account') or (boundaries.get((key[0],end)) or {}).get('account')
        if name not in coverage: coverage[name] = bool(name and repo.has_coverage(name,start,end))
        verified = coverage[name] and complete(key[0],start) and complete(key[0],end) and key[0] not in unknown_keys
        status = 'Stückzahl fehlt' if difference is None else 'Abweichung' if difference else 'Abgestimmt' if verified else 'Rechnerisch passend'
        if not verified: status += ' · Nachweise unvollständig'
        price = fx = None
        ca,cb = (a or {}).get('currency'),(b or {}).get('currency')
        r0 = repo.historical_rate(ca,start) if ca else None
        r1 = repo.historical_rate(cb,end) if cb else None
        if qa and qb and va is not None and vb is not None and ca == cb and r0 is not None and r1 is not None and key not in changed_by_action:
            price = qa * (vb/qb - va/qa) * r0
            # EUR-valued evidence does not reveal a security's local-currency FX share.
            fx = qa * (vb/qb) * (r1-r0) if ca!='EUR' else None
        positions.append(dict(depot=key[0],key=key[1],name=p.get('name',key[1]),category=p.get('asset_type','Unbekannt'),
            account=position_account,
            before=va,after=vb,change=vb-va if va is not None and vb is not None and ca == cb else None,
            currency=cb or ca or 'Unbekannt',opening_units=qa,booked_units=movements[key],expected_units=predicted,closing_units=qb,
            difference=difference,status=status,price_effect=price,fx_effect=fx,source_before=(a or {}).get('source'),source_after=(b or {}).get('source')))
        cost0,cost1=(a or {}).get('cost'),(b or {}).get('cost')
        positions[-1]['book_profit_change']=(vb-Decimal(cost1))-(va-Decimal(cost0)) if va is not None and vb is not None and cost0 is not None and cost1 is not None and Decimal(cost0)>0 and Decimal(cost1)>0 and ca==cb else None
    accounts = []
    totals = [repo.wealth_summary(day,account) for day in (start,end)]
    comparable = ZERO; comparable_count = 0; comparable_categories = defaultdict(lambda: [ZERO,ZERO])
    for name in ([account] if account else repo.accounts()):
        a,b = [repo.wealth_summary(day,name) for day in (start,end)]
        reasons=[]
        same = a['value'] is not None and b['value'] is not None
        if not same: reasons.append('Anfangs- oder Endwert fehlt')
        ad,bd=a.get('dates',[]),b.get('dates',[])
        if not ad or not bd or any(len(x)!=10 for x in ad+bd): reasons.append('Datumsgenauigkeit fehlt')
        elif max((date.fromisoformat(start)-date.fromisoformat(x)).days for x in ad)>45 or max((date.fromisoformat(end)-date.fromisoformat(x)).days for x in bd)>45: reasons.append('Beleg älter als 45 Tage')
        opening={p['depot'] for p in first.values() if account_key(p['account'])==account_key(name)}
        closing={p['depot'] for p in last.values() if account_key(p['account'])==account_key(name)}
        if opening!=closing: reasons.append('Depotabdeckung verändert')
        currencies={p.get('currency','EUR') for p in list(first.values())+list(last.values()) if account_key(p['account'])==account_key(name)}
        if currencies-{'EUR'}: reasons.append('Fremdwährungswerte separat prüfen')
        same=not reasons
        delta = b['value']-a['value'] if same else None
        accounts.append(dict(account=name,before=a['value'],after=b['value'],change=delta,
                             status='Vergleichbar' if same else '; '.join(reasons),dates_before=ad,dates_after=bd))
        if same:
            comparable += delta; comparable_count += 1
            for cat in a['categories'].keys() & b['categories'].keys():
                comparable_categories[cat][0] += a['categories'][cat]; comparable_categories[cat][1] += b['categories'][cat]
    a,b = totals
    categories = [dict(category=c,before=a['categories'].get(c),after=b['categories'].get(c),
        comparable_before=comparable_categories[c][0] if c in comparable_categories else None,
        comparable_after=comparable_categories[c][1] if c in comparable_categories else None)
        for c in sorted(a['categories'].keys() | b['categories'].keys())]
    delta = b['value']-a['value'] if a['value'] is not None and b['value'] is not None else None
    paired = {p[k] for p in repo.transfer_pairs() for k in ('first_ref','second_ref')}
    cash = defaultdict(lambda: ZERO); internal = defaultdict(lambda: ZERO); income = defaultdict(lambda: ZERO)
    fee_links={(r['aux_ref'],r['field']) for r in repo.fee_links()}
    for tx in txs:
        if not tx.get('affects_cash', True): continue
        if reference(tx) in paired:
            internal[tx['currency']] += Decimal(tx['amount']); continue
        if tx['currency'] == 'EUR': cash[tx['kind']] += Decimal(tx['amount'])
        else: unknown.append(tx)
        # A dedicated fee/tax row is counted once; auxiliary fields on that row are ignored.
        for kind, field in (('DIVIDEND',None),('INTEREST',None),('FEE','fees'),('TAX','taxes')):
            amount = Decimal(tx['amount']) if tx['kind'] == kind else -abs(Decimal(tx[field])) if field and tx.get(field) is not None else None
            if amount is not None and tx['kind']!=kind and field:
                if (reference(tx),field) in fee_links: continue
            if amount is not None: income[(tx['date'][:7],tx['account'],tx.get('security',''),kind,tx['currency'])] += amount
    explained = {k:cash[k] for k in ('DEPOSIT','WITHDRAWAL','DIVIDEND','INTEREST','FEE','TAX')}
    contributions=defaultdict(lambda:dict(price_effect=None,fx_effect=None,book_profit_change=None,positions=0,known_profit_positions=0))
    for row in positions:
        bucket=contributions[(row['category'],row['currency'])]; bucket['positions']+=1
        for field in ('price_effect','fx_effect','book_profit_change'):
            if row[field] is not None: bucket[field]=(bucket[field] or ZERO)+row[field]
        if row['book_profit_change'] is not None: bucket['known_profit_positions']+=1
    result=dict(positions=positions,accounts=accounts,categories=categories,change=delta,
        comparable_change=comparable if comparable_count else None,comparable_accounts=comparable_count,
        explained=explained,residual=delta-sum(explained.values(),ZERO) if delta is not None else None,
        transactions=txs,unclassified=sum(t['kind']=='BANK_BOOKING' and reference(t) not in paired for t in txs),unknown=len(unknown),
        internal=dict(internal),income=[dict(month=k[0],account=k[1],security=k[2],kind=k[3],currency=k[4],amount=v) for k,v in sorted(income.items())],
        start=start,end=end,scope=account or 'Alle Konten',revision=repo.revision(),actions=actions,
        contributions=[dict(category=k[0],currency=k[1],**v) for k,v in sorted(contributions.items())])
    result['fee_candidates']=fee_candidates(repo,txs)
    # Wealth bridge only accounts for explicit cash flows; valuation remains a separate estimate.
    external=sum((v for k,v in explained.items() if k in ('DEPOSIT','WITHDRAWAL')),ZERO)
    earnings=sum((v for k,v in explained.items() if k in ('DIVIDEND','INTEREST')),ZERO)
    costs=sum((v for k,v in explained.items() if k in ('FEE','TAX')),ZERO)
    valuation=sum((r['price_effect']+(r['fx_effect'] or ZERO) for r in positions if r['price_effect'] is not None),ZERO)
    result['bridge']=[dict(label='Anfangsvermögen',amount=totals[0]['value']),dict(label='Externe Zahlungen',amount=external),dict(label='Erträge',amount=earnings),
                      dict(label='Separat gebuchte Kosten',amount=costs),dict(label='Belegte Kurs-/FX-Näherung',amount=valuation),dict(label='Ungeklärter Rest',amount=delta-external-earnings-costs-valuation if delta is not None else None),dict(label='Endvermögen',amount=totals[1]['value'])]
    result['profit']=realized_profit(repo,start,end,account)
    result['quality']=dict(positions=len(positions),quantity_known=sum(r['difference'] is not None for r in positions),price_known=sum(r['price_effect'] is not None for r in positions),fx_known=sum(r['fx_effect'] is not None for r in positions),profit_known=sum(r['book_profit_change'] is not None for r in positions),comparable_accounts=comparable_count,accounts=len(accounts))
    result['fx_sources']=[dict(r) for r in repo.db.execute('SELECT * FROM historical_fx WHERE day<=? ORDER BY day,currency',(end,))]
    return result


def grouped_contributions(data,dimension):
    groups=defaultdict(lambda:dict(change=None,book_profit_change=None,price_effect=None,fx_effect=None,known=0,total=0))
    for row in data['positions']:
        key=(row.get(dimension) or 'Unbekannt',row['currency']); g=groups[key]; g['total']+=1
        if row['change'] is not None: g['known']+=1
        for field in ('change','book_profit_change','price_effect','fx_effect'):
            if row[field] is not None: g[field]=(g[field] or ZERO)+row[field]
    return [dict(group=k[0],currency=k[1],**v) for k,v in sorted(groups.items())]


def fee_candidates(repo,txs=None):
    # Only valid links prove "already counted": an invalidated link brings
    # the double count — and with it the candidate — back into scope.
    txs=repo.transactions() if txs is None else txs; links=repo.fee_links()
    linked={(r['aux_ref'],r['field']) for r in links}; used={r['fee_ref'] for r in links}; index=defaultdict(list)
    def day(t):
        for key in ('value_date','date'):
            value=t.get(key)
            if not value: continue
            try: return date.fromisoformat(value)
            except (TypeError, ValueError): continue
        return None
    for t in txs:
        if t['kind'] in ('FEE','TAX') and reference(t) not in used: index[(t['account'],t['currency'],t['kind'],abs(Decimal(t['amount'])))].append(t)
    out=[]
    for t in txs:
        for field,kind in (('fees','FEE'),('taxes','TAX')):
            if t['kind']==kind or t.get(field) is None or (reference(t),field) in linked: continue
            for other in index[(t['account'],t['currency'],kind,abs(Decimal(t[field])))]:
                # Buchungs- und Valutatag dürfen wie im Belegabgleich bis zu
                # drei Tage auseinanderliegen; ein exakter Tag treibt sonst
                # einen dauerhaften stillen Doppelzähler.
                other_day, own_day = day(other), day(t)
                if other_day is None or own_day is None or abs((other_day-own_day).days) > 3: continue
                out.append(dict(aux_ref=reference(t),fee_ref=reference(other),field=field,account=t['account'],day=t['date'],amount=t[field],currency=t['currency'],source=t['source'],other_source=other['source']))
    return out


def realized_profit(repo,start,end,account=None):
    """FIFO from documented buys; never infer missing opening acquisition costs."""
    lots=defaultdict(list); rows=[]; uncertain=set()
    def security_key(value):
        row=repo.db.execute('SELECT security_key FROM security_master WHERE security_key=? OR isin=? OR wkn=?',
                            (value,value,value)).fetchone()
        return row['security_key'] if row else value
    advance_tax=defaultdict(list)
    for event in repo.tax_events(account):
        if event.get('type') not in ('vorabpauschale','vorabpauschale_ausland'):
            continue
        try:
            quantity=abs(Decimal(str(event.get('quantity') or 0)))
            credit=abs(Decimal(str(event.get('taxable_income') or 0)))
        except Exception:
            continue
        if quantity and credit:
            advance_tax[(account_key(event['account']),security_key(event.get('security_ref','')))].append(
                {'date':event.get('date',''),'quantity':quantity,'credit':credit})
    actions=repo.actions('0001-01-01',end)
    trades=[t for t in repo.transactions(account) if t['date']<=end and t['kind'] in ('BUY','SELL','TRANSFER_IN','TRANSFER_OUT')]
    paired_transfer_refs={pair[key] for pair in repo.security_transfer_pairs() for key in ('out_ref','in_ref')}
    trades=[t for t in trades if reference(t) not in paired_transfer_refs]
    daily=defaultdict(list)
    for t in trades: daily[(t['depot'],t.get('security',''),t['currency'],t['date'])].append(t)
    def execution_order(t):
        stamp=t.get('executed_at') or ''
        try:
            parsed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if parsed.utcoffset() is None: raise ValueError
            return (0, parsed.timestamp())
        except (TypeError, ValueError):
            return (1, '')
    ambiguous_days=set()
    for key, items in daily.items():
        orders=[execution_order(t) for t in items]
        if len(items)>1 and (any(order[0] for order in orders) or len(set(orders)) != len(orders)):
            ambiguous_days.add(key)
    def eur_value(t):
        amount=abs(Decimal(t['amount']))
        currency=t['currency'].upper()
        if currency == 'EUR': return amount
        from_currency=(t.get('fx_from_currency') or '').upper()
        to_currency=(t.get('fx_to_currency') or '').upper()
        rate=t.get('fx_rate')
        if rate is not None and from_currency == currency and to_currency == 'EUR':
            return amount*Decimal(rate)
        documented=repo.documented_rate(currency,t['date'])
        return amount*documented if documented is not None else None
    def tax_credit(t,quantity):
        if not quantity:
            return None
        pools=advance_tax[(account_key(t['account']),security_key(t.get('security','')))]
        total=ZERO
        for pool in pools:
            if pool['date']>t['date'] or not pool['quantity']:
                continue
            used=min(quantity,pool['quantity'])
            total+=pool['credit']*used/pool['quantity']
            pool['credit']-=pool['credit']*used/pool['quantity']
            pool['quantity']-=used
        return total
    def append_sale(t,cost,known,quantity=None,cost_eur=None,eur_known=False):
        credit=tax_credit(t,quantity)
        realized=abs(Decimal(t['amount']))-cost if known else None
        proceeds_eur=eur_value(t)
        realized_eur=proceeds_eur-cost_eur if eur_known and proceeds_eur is not None else None
        if realized_eur is not None: fx_status='belegt'
        elif proceeds_eur is None: fx_status='unbekannter EUR-Kurs'
        else: fx_status='unbekannte EUR-Kostenbasis'
        rows.append(dict(date=t['date'],account=t['account'],security=t.get('security',''),currency=t['currency'],
            proceeds=abs(Decimal(t['amount'])),cost=cost if known else None,realized=realized,
            report_currency='EUR',proceeds_eur=proceeds_eur,cost_eur=cost_eur if eur_known else None,
            realized_eur=realized_eur,fx_status=fx_status,
            advance_tax_credit=credit,
            taxable_realized=(realized-credit if realized is not None and credit is not None else None),
            status='FIFO · Buchungsbeträge, Gebührenkonvention des Belegs' if known else 'Unbekannt · Stückzahl, Kennung, Anfangsbestand, Abdeckung, Tagesreihenfolge oder Kapitalmaßnahme prüfen',source=t['source']))
    events=[(t['date'],1000000,execution_order(t),'trade',t) for t in trades]
    events += [(a['day'],a['sequence'],(0,''),'action',a) for a in actions]
    for _, _, _, event_kind, t in sorted(events,key=lambda e:(e[0],e[1],e[2])):
        if event_kind == 'action':
            matching=[key for key in lots if key[:2] == (t['depot'],t['security'])]
            if t['kind']=='SPLIT':
                ratio=Decimal(t['ratio'])
                for key in matching:
                    for lot in lots[key]:
                        lot[0] *= ratio
                        lot[1] /= ratio
                        if lot[3] is not None: lot[3] /= ratio
                if not matching:
                    uncertain.add((t['depot'],t['security'],'EUR'))
                continue
            if t['kind'] in ('SPINOFF','RIGHTS'):
                ratio=Decimal(t['ratio']); allocation=Decimal(t['cost_ratio'])
                if not matching:
                    uncertain.add((t['depot'],t['target'],'EUR'))
                for key in matching:
                    target=(t['target_depot'] or t['depot'],t['target'],key[2])
                    created=[]
                    for lot in lots[key]:
                        created.append([lot[0]*ratio,lot[1]*allocation/ratio,lot[2],
                            lot[3]*allocation/ratio if lot[3] is not None else None])
                        lot[1]*=(1-allocation)
                        if lot[3] is not None: lot[3]*=(1-allocation)
                    lots[target].extend(created); lots[target].sort(key=lambda lot:lot[2])
                    if key in uncertain: uncertain.add(target)
                continue
            if t['kind']=='CAPITAL_REPAYMENT':
                for key in matching:
                    if key[2] != (t.get('cost_currency') or 'EUR'): continue
                    quantity=sum((lot[0] for lot in lots[key]),ZERO); reduction=Decimal(t['cost_amount'])
                    total=sum((lot[0]*lot[1] for lot in lots[key]),ZERO)
                    if not quantity or reduction > total: uncertain.add(key); continue
                    per_unit=reduction/quantity
                    for lot in lots[key]: lot[1]-=per_unit
                continue
            target_depot=t['target_depot'] or t['depot']; target_security=t['target'] or t['security']
            if not matching:
                uncertain.add((target_depot,target_security,'EUR'))
                continue
            ratio=Decimal(t['ratio'])
            for key in matching:
                source_uncertain=key in uncertain
                remaining=sum((lot[0] for lot in lots[key]),ZERO) if t['kind']=='MERGER' else Decimal(t['units'])
                moved=[]
                while remaining and lots[key]:
                    lot=lots[key][0]; used=min(remaining,lot[0])
                    moved.append([used*ratio,lot[1]/ratio,lot[2],lot[3]/ratio if lot[3] is not None else None]); remaining-=used; lot[0]-=used
                    if not lot[0]: lots[key].pop(0)
                target=(target_depot,target_security,key[2])
                lots[target].extend(moved)
                lots[target].sort(key=lambda lot: lot[2])
                if remaining or source_uncertain:
                    uncertain.add(target)
                if remaining:
                    uncertain.add(key)
            continue
        key=(t['depot'],t.get('security',''),t['currency']); q=Decimal(t['quantity']) if t.get('quantity') is not None else None
        if not q or not key[1] or (*key,t['date']) in ambiguous_days: uncertain.add(key)
        if t['kind'].startswith('TRANSFER'): uncertain.add(key); continue
        if not q:
            if t['kind']=='SELL' and start<t['date']<=end: append_sale(t,None,False)
            continue
        q=abs(q)
        if t['kind']=='BUY':
            value_eur=eur_value(t)
            lots[key].append([q,abs(Decimal(t['amount']))/q,t['date'],value_eur/q if value_eur is not None else None]); continue
        remaining=q; cost=ZERO; cost_eur=ZERO; eur_known=True
        while remaining and lots[key]:
            lot=lots[key][0]; used=min(remaining,lot[0]); cost+=used*lot[1]
            if lot[3] is None: eur_known=False
            else: cost_eur+=used*lot[3]
            remaining-=used; lot[0]-=used
            if not lot[0]: lots[key].pop(0)
        if start<t['date']<=end:
            known=not remaining and key not in uncertain and repo.has_coverage(t['account'],'0001-01-01',end)
            # Full-lifetime coverage is intentionally strict; an explicit empty baseline also qualifies.
            if not remaining and key not in uncertain and not known:
                snaps=[s for s in repo.snapshots(t['account']) if s['depot']==key[0] and s['complete'] and s.get('as_of') and s['effective_date']<=t['date']]
                empty=[s for s in snaps if not json.loads(s['payload'])['positions']]
                known=any(repo.has_coverage(t['account'],s['effective_date'],end) and not any(x['date']<=s['effective_date'] and x['depot']==key[0] and x.get('security')==key[1] for x in repo.transactions(t['account'])) for s in empty)
            append_sale(t,cost,known,q,cost_eur,known and eur_known)
        else:
            # Earlier sales have already consumed their proportional tax credit,
            # even when the selected report period starts later.
            tax_credit(t,q)
    return rows


def recurring_candidates(repo):
    from statistics import median
    confirmed={(account_key(r['account']),r['description'].casefold(),r['currency'],Decimal(r['amount']),r['interval_days']) for r in repo.db.execute('SELECT * FROM recurring_rules')}
    groups=defaultdict(list)
    for t in repo.transactions():
        if t['kind'] not in ('BUY','BANK_BOOKING','DEPOSIT','WITHDRAWAL'): continue
        description=t.get('security') or t.get('counterparty') or t.get('purpose') or ''
        if description: groups[(t['account'],description.casefold(),t['currency'],Decimal(t['amount']))].append(t)
    result=[]
    for (account,description,currency,amount),rows in groups.items():
        days=sorted({r['date'] for r in rows})
        if len(days)<3: continue
        intervals=[(date.fromisoformat(b)-date.fromisoformat(a)).days for a,b in zip(days,days[1:])]; period=round(median(intervals))
        if (account_key(account),description,currency,amount,period) in confirmed: continue
        if any(abs(period-target)<=3 for target in (7,14,30,90,365)) and all(abs(x-period)<=4 for x in intervals):
            result.append(dict(account=account,description=description,currency=currency,amount=format(amount.normalize(),'f'),interval_days=period,refs=[reference(r) for r in rows]))
    return result


def export_report(data, destination):
    def val(x): return 'Unbekannt' if x is None else escape(str(x))
    sections = []
    for title,key,columns in [('Konten','accounts',['account','before','after','change','status']),
                              ('Positionen / Beiträge','positions',['depot','name','before','after','change','currency','book_profit_change','price_effect','fx_effect','status','source_before','source_after']),
                              ('Beiträge nach Anlageklasse','contributions',['category','currency','book_profit_change','price_effect','fx_effect','known_profit_positions','positions']),
                              ('Erträge und Kosten','income',['month','account','security','kind','currency','amount'])]:
        sections.append('<h2>'+title+'</h2><table><tr>'+''.join('<th>'+c+'</th>' for c in columns)+'</tr>'+''.join('<tr>'+''.join('<td>'+val(r.get(c))+'</td>' for c in columns)+'</tr>' for r in data[key])+'</table>')
    payload = '<!doctype html><meta charset="utf-8"><title>PortMan 09 · Auswertung</title><style>body{font:14px system-ui;margin:32px}table{border-collapse:collapse}td,th{padding:7px;border:1px solid #bbb;text-align:left}</style>'
    payload += '<h1>PortMan 09 · Auswertung</h1><p>'+val(data['scope'])+' · '+val(data['start'])+' bis '+val(data['end'])+' · Datenrevision '+val(data['revision'])+'</p>'
    payload += '<p>Dokumentierte Vermögensänderung; keine Rendite. Vergleichbare Konten: '+val(data['comparable_accounts'])+'. Kurs-/Währungseffekte beziehen sich auf Anfangsstückzahlen; historische Devisenkurse höchstens sieben Tage alt. Bei ausschließlich in EUR vorliegenden Werten ist der Fremdwährungsanteil nicht separat bestimmbar. Fehlende Werte bleiben unbekannt. Kapitalmaßnahmen und unklassifizierte Buchungen gesondert prüfen. Gebührennebenfelder werden anhand von Datum, Konto, Wertpapier, Währung und Betrag mit separaten Gebührenbuchungen abgeglichen.</p>'
    Path(destination).write_text(payload+''.join(sections),encoding='utf-8')
