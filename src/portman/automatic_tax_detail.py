"""Derive a read-only, auditable 32-column tax ledger from imported facts."""
from datetime import date
from decimal import Decimal, InvalidOperation

from portfolio_v5.accounts import account_key
from portfolio_v5.comdirect_tax_detail import COLUMNS, date_value
from .institutions import account_institution
from .income_basis import gross_income_amount
from .repository_v09 import reference


def _de(value):
    if value in (None, ''):
        return ''
    try:
        return format(Decimal(str(value)), 'f').replace('.', ',')
    except (InvalidOperation, ValueError):
        return str(value)


def _day(value):
    try:
        return date.fromisoformat(value).strftime('%d.%m.%Y')
    except (TypeError, ValueError):
        return ''


def _blank():
    return {column: '' for column in COLUMNS}


def _security(repository, value):
    row = repository.db.execute(
        'SELECT canonical_name,isin,wkn FROM security_master WHERE security_key=? OR isin=? OR wkn=?',
        (value, value, value)).fetchone()
    if not row:
        return value or '', value if value and len(value) <= 6 else ''
    return row['canonical_name'] or value or '', row['wkn'] or ''


def _tax_parts(tx):
    parts = {'Kapitalertragssteuer': '', 'Solidaritätszuschlag': '', 'Kirchensteuer': '',
             'Umsatz anrechenbarer Quellensteuer': ''}
    names = {'kapitalertragsteuer': 'Kapitalertragssteuer',
             'solidaritaetszuschlag': 'Solidaritätszuschlag', 'solidaritätszuschlag': 'Solidaritätszuschlag',
             'kirchensteuer': 'Kirchensteuer', 'quellensteuer': 'Umsatz anrechenbarer Quellensteuer'}
    for item in tx.get('tax_items') or []:
        kind = (item.get('kind') if isinstance(item, dict) else item.kind).casefold()
        amount = item.get('amount') if isinstance(item, dict) else item.amount
        if kind in names:
            parts[names[kind]] = _de(-abs(Decimal(str(amount))))
    return parts


def _row(values, *, external_id, institution, account, source_format, source,
         linked_event='', linked_transaction='', provenance=None, conflicts=None):
    values = {column: str(values.get(column, '') or '') for column in COLUMNS}
    missing = [column for column in COLUMNS if not values[column]]
    return {'external_id': external_id, 'institution': institution, 'account': account,
            'source_format': source_format, 'original_values': values,
            'source_reference': values['Referenznummer'], 'source': source,
            'tax_year': values['Steuerjahr'], 'tax_date': date_value(values, 'Steuerliches Datum'),
            'booking_date': date_value(values, 'Buchungstag'), 'document_date': '', 'income_year': '',
            'linked_tax_event_id': linked_event, 'linked_transaction_id': linked_transaction,
            'match_status': 'conflict' if conflicts else 'derived',
            'column_provenance': provenance or {}, 'missing_columns': missing,
            'conflicts': conflicts or []}


def _event_values(repository, event):
    values = _blank(); name, wkn = _security(repository, event.get('security_ref', ''))
    event_type = event.get('type')
    labels = {'vorabpauschale': 'Vorabpauschale', 'vorabpauschale_ausland': 'Vorabpauschale Ausland',
              'investment_ausschuettung_inland': 'Investment-Ausschüttung Inland',
              'investment_ausschuettung_ausland': 'Investment-Ausschüttung Ausland',
              'dividende_inland': 'Dividende Inland'}
    kind = labels.get(event_type, event_type or 'Steuerereignis')
    distribution = (str(event_type or '').startswith('investment_ausschuettung_')
                    or event_type == 'dividende_inland')
    gross = ((Decimal(str(event.get('taxable_income') or 0))
              + Decimal(str(event.get('partial_exemption_amount') or 0))) if distribution
             else event.get('advance_tax_base'))
    net = ((gross - Decimal(str(event.get('paid_taxes') or 0))) if distribution else
           (Decimal(str(event['taxable_income'])) - Decimal(str(event['paid_taxes']))
            if event.get('taxable_income') is not None and event.get('paid_taxes') is not None else None))
    values.update({'Steuerjahr': str(event.get('tax_year') or event.get('date', '')[:4]),
        'Buchungstag': _day(event.get('document_date') or event.get('date')),
        'Steuerliches Datum': _day(event.get('date')), 'Referenznummer': event.get('reference_no', ''),
        'Vorgang': kind, 'Stück/Nominale': _de(event.get('quantity')), 'Bezeichnung': name, 'WKN': wkn,
        'Betrag Brutto': _de(gross),
        'Gewinn/Verlust': _de(event.get('taxable_income')),
        'Gewinn Sonstige': _de(event.get('taxable_income')),
        'Verlust Sonstige': _de(-abs(Decimal(str(event['partial_exemption_amount'])))) if event.get('partial_exemption_amount') else '',
        'BMG nach VV': (_de(Decimal(str(event['taxable_income'])) - Decimal(str(event.get('loss_offset') or 0)))
                         if event.get('taxable_income') is not None else ''),
        'Veränderung FSA': _de(-abs(Decimal(str(event['used_exemption'])))) if event.get('used_exemption') else '',
        'BMG nach FSA': (_de(max(Decimal(), Decimal(str(event['taxable_income']))
                                      - Decimal(str(event.get('loss_offset') or 0))
                                      - Decimal(str(event['used_exemption']))))
                          if event.get('taxable_income') is not None and event.get('used_exemption') is not None else ''),
        'Kapitalertragssteuer': (_de(-abs(Decimal(str(event['capital_gains_tax']))))
                                  if event.get('capital_gains_tax') is not None else ''),
        'Solidaritätszuschlag': (_de(-abs(Decimal(str(event['solidarity_surcharge']))))
                                 if event.get('solidarity_surcharge') is not None else ''),
        'Kirchensteuer': (_de(-abs(Decimal(str(event['church_tax']))))
                          if event.get('church_tax') is not None else ''),
        'Summe Steuern': (_de(-abs(Decimal(str(event['paid_taxes']))))
                          if event.get('paid_taxes') is not None else ''),
        'Gewinn/Verlust nach Steuern': _de(net),
        'Umsatz anrechenbarer Quellensteuer': _de(event.get('creditable_withholding')),
        'Steuerbemessungsgrundlage': _de(event.get('taxable_income')),
        'Gewinn/Verlust Aktien (Saldo)': _de(event.get('equity_loss_pot_after')),
        'Gewinn/Verlust Sonstige (Saldo)': _de(event.get('other_loss_pot_after'))})
    return values


def _transaction_values(repository, tx, realized=None):
    values = _blank(); name, wkn = _security(repository, tx.get('security', ''))
    labels = {'DIVIDEND': 'Dividende', 'DISTRIBUTION': 'Ausschüttung', 'INTEREST': 'Zinsertrag',
              'SELL': 'Wertpapierverkauf', 'TAX': 'Steuerabzug', 'TAX_REFUND': 'Steuererstattung'}
    taxes = abs(Decimal(str(tx.get('taxes') or 0)))
    gross = gross_income_amount(tx) or tx.get('gross_amount')
    values.update({'Steuerjahr': tx.get('date', '')[:4], 'Buchungstag': _day(tx.get('date')),
        'Steuerliches Datum': _day(tx.get('date')), 'Referenznummer': tx.get('transaction_reference') or tx.get('external_id', ''),
        'Vorgang': labels[tx['kind']], 'Stück/Nominale': _de(tx.get('quantity')),
        'Bezeichnung': name or tx.get('counterparty', ''), 'WKN': wkn,
        'Betrag Brutto': _de(gross),
        'Summe Steuern': _de(-taxes if tx['kind'] != 'TAX_REFUND' else taxes),
        'Gewinn/Verlust nach Steuern': _de(tx.get('amount'))})
    values.update(_tax_parts(tx))
    if tx['kind'] in ('DIVIDEND', 'DISTRIBUTION', 'INTEREST') and gross is not None:
        values['Gewinn/Verlust'] = _de(gross)
        values['Gewinn Sonstige'] = _de(gross)
    if tx['kind'] == 'SELL' and realized is not None:
        values['Gewinn/Verlust'] = _de(realized)
    return values


def automatic_tax_detail_records(repository, imported):
    """Merge imported CSV rows with missing PDF events and tax-relevant transactions."""
    records = {row['account_key']: row for row in repository.account_records() if row['active']}
    linked_events = {row.get('linked_tax_event_id') for row in imported if row.get('linked_tax_event_id')}
    linked_transactions = {row.get('linked_transaction_id') for row in imported if row.get('linked_transaction_id')}
    result = []
    for row in imported:
        item = dict(row); values = item['original_values']
        item['column_provenance'] = {column: {'status': 'original', 'source': item.get('source', '')}
                                     for column in COLUMNS if values.get(column, '') != ''}
        item['missing_columns'] = [column for column in COLUMNS if values.get(column, '') == '']
        conflicts = []
        comparisons = {'Steuerbemessungsgrundlage': item.get('taxable_income'),
                       'Summe Steuern': item.get('paid_taxes')}
        for column, other in comparisons.items():
            if other not in (None, '') and values.get(column, ''):
                try:
                    original = abs(Decimal(values[column].replace('.', '').replace(',', '.')))
                    if original != abs(Decimal(str(other))):
                        conflicts.append(f'{column}: CSV {values[column]} / Beleg {_de(other)}')
                except InvalidOperation:
                    pass
        item['conflicts'] = conflicts
        if conflicts: item['match_status'] = 'conflict'
        result.append(item)
    events = repository.tax_events()
    all_transactions = repository.transactions()
    by_external = {tx.get('external_id'): tx for tx in all_transactions if tx.get('external_id')}
    fee_to_aux = {row['fee_ref']: row['aux_ref'] for row in repository.fee_links()}
    event_by_aux = {}
    for event in events:
        related_tx = by_external.get(event.get('related_transaction_id'))
        if related_tx is not None:
            related_ref = reference(related_tx)
            aux = (related_ref if related_tx.get('kind') in ('DIVIDEND', 'DISTRIBUTION')
                   else fee_to_aux.get(related_ref))
            if aux:
                event_by_aux[aux] = event
    for event in events:
        if event.get('external_id') in linked_events:
            continue
        if event in event_by_aux.values():
            continue
        account = event['account']; key = account_key(account); record = records.get(key, {})
        values = _event_values(repository, event)
        provenance = {column: {'status': 'document', 'source': event.get('source', '')}
                      for column in COLUMNS if values[column] != ''}
        result.append(_row(values, external_id='auto-event:'+event['external_id'],
            institution=account_institution(record, records), account=account,
            source_format='automatic_tax_event_v1', source=event.get('source', ''),
            linked_event=event['external_id'], provenance=provenance))
    related = {event.get('related_transaction_id') for event in events
               if event.get('related_transaction_id')}
    from .analysis_v09 import realized_profit
    realized_index = {}
    analysis_end = max((tx.get('date', '') for tx in all_transactions), default='9999-12-31')
    for gain in realized_profit(repository, '0001-01-01', analysis_end):
        key = (account_key(gain['account']), gain['date'], gain['security'], gain['proceeds'])
        realized_index.setdefault(key, []).append(gain.get('taxable_realized', gain.get('realized')))
    for tx in all_transactions:
        if tx.get('kind') not in ('DIVIDEND','DISTRIBUTION','INTEREST','SELL','TAX','TAX_REFUND'):
            continue
        if tx.get('kind') in ('TAX','TAX_REFUND') and not tx.get('affects_cash', True):
            continue
        ref = reference(tx)
        # A related dividend is the primary detail row and must be enriched by
        # its tax event.  Legacy related TAX rows remain suppressed.
        if ref in linked_transactions or (tx.get('external_id') in related and ref not in event_by_aux):
            continue
        gains = realized_index.get((account_key(tx['account']), tx['date'], tx.get('security', ''),
                                    abs(Decimal(str(tx['amount'])))), [])
        safe_gain = gains[0] if len(gains) == 1 else None
        values = _transaction_values(repository, tx, safe_gain)
        linked_event = event_by_aux.get(ref)
        if linked_event:
            event_values = _event_values(repository, linked_event)
            for column in ('Vorgang', 'BMG nach VV', 'Verlust Sonstige',
                           'Kapitalertragssteuer', 'Solidaritätszuschlag', 'Kirchensteuer',
                           'Steuerbemessungsgrundlage'):
                if event_values.get(column) not in (None, ''):
                    values[column] = event_values[column]
        record = records.get(account_key(tx['account']), {})
        provenance = {column: {'status': 'document', 'source': tx.get('source', '')}
                      for column in COLUMNS if values[column] != ''}
        result.append(_row(values, external_id='auto-tx:'+ref,
            institution=account_institution(record, records), account=tx['account'],
            source_format='automatic_transaction_v1', source=tx.get('source', ''),
            linked_event=linked_event.get('external_id', '') if linked_event else '',
            linked_transaction=ref, provenance=provenance))
    return sorted(result, key=lambda row: (row.get('tax_date', ''), row.get('external_id', '')))
