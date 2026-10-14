"""One-step Renault statement import using the existing account suggestions."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import re

from portfolio_v5.accounts import account_key
from pdf_plugins._statement_bookings import AMOUNT, HEADER, parse_bookings, statement_end
from portfolio_v5.models import money, parse_date
from pdf_plugins._generic_document import analyse_pages


def is_renault_statement(text):
    if re.search(r'Renault|RCI\s+Banque', text, re.I):
        return True
    # Newer statements carry the brand as artwork. Their selectable account
    # header still contains the bank BIC; do not use a counterparty's BIC.
    for page in re.split(r'--- Seite \d+ ---\n', text):
        header = []
        for line in page.splitlines():
            if HEADER.search(line):
                break
            header.append(line)
        if re.search(r'\bBIC\s*:?\s*RCIDDE3N(?:PAY|XXX)?\b', '\n'.join(header), re.I):
            return True
    return False


def prepare_renault_batch(repository, original):
    batch = deepcopy(original)
    if batch.errors:
        raise ValueError('; '.join(batch.errors))
    if batch.source_sheet != 'PDF' or batch.document_type != 'Kontoauszug':
        raise ValueError('Kein Kontoauszug; Datei ausgelassen.')
    if not is_renault_statement(batch.pdf_text):
        raise ValueError('Kein Renault-Kontoauszug erkannt.')
    pages = re.split(r'--- Seite \d+ ---\n', batch.pdf_text)[1:]
    _, warnings, _ = parse_bookings(pages, analyse_pages)
    # An impossible value date must not drop a balanced statement: booking dates
    # determine the period, and the parser leaves the unknown value date blank.
    warnings = [warning for warning in warnings if not (
        'Valuta' in warning and 'kein gültiges Kalenderdatum' in warning)]
    if batch.pdf_reviewed:
        # The corrected amounts are reconciled with the original balances below.
        warnings = [warning for warning in warnings if 'Saldenprüfung weicht um' not in warning]
    if batch.pdf_reviewed and batch.transactions and all(
            tx.value_date and parse_date(tx.value_date) == tx.value_date for tx in batch.transactions):
        warnings = [warning for warning in warnings if not ('Valuta' in warning and 'kein gültiges Kalenderdatum' in warning)]
    if warnings:
        raise ValueError('Auszug benötigt Prüfung: ' + '; '.join(warnings))
    owners = {tx.account for tx in batch.transactions}
    if len(owners) != 1:
        raise ValueError('Kein eindeutiges Buchungskonto erkannt.')
    owner = next(iter(owners))
    suggestion = next((s for s in repository.import_account_suggestions(batch) if s['name'] == owner), None)
    target = batch.account_assignments.get(account_key(owner)) if batch.pdf_reviewed else None
    target = target or (suggestion['target_key'] if suggestion else None)
    if not target:
        raise ValueError('Konto nicht eindeutig zugeordnet. Bitte Kontonummer in den Kontodetails hinterlegen.')
    target_name = next((r['name'] for r in repository.account_records() if r['account_key'] == target and r['active']), None)
    if target_name is None:
        raise ValueError('Das gewählte Zielkonto ist nicht mehr aktiv.')
    # Replace only a complete, reconciled statement period, including quiet days.
    opening = re.findall(r'alter Kontostand vom\s*(\d{2}\.\d{2}\.\d{4})', batch.pdf_text, re.I)
    end = statement_end(batch.pdf_text)
    if len(opening) != 1 or end is None or not re.search(r'neuer Kontostand', batch.pdf_text, re.I):
        raise ValueError('Auszugszeitraum nicht eindeutig erkannt.')
    day, month, year = map(int, opening[0].split('.'))
    start = date(year, month, day) + timedelta(days=1)
    if start > end or any(not start.isoformat() <= tx.date <= end.isoformat() for tx in batch.transactions):
        raise ValueError('Buchungsdaten passen nicht zum Auszugszeitraum.')
    balances = []
    for line in batch.pdf_text.splitlines():
        if re.search(r'(?:alter|neuer) Kontostand', line, re.I):
            match = AMOUNT.search(line)
            if match:
                sign = -1 if match['before'] == '-' or match['after'] in ('S', '-') else 1
                balances.append(Decimal(money(match['number'])) * sign)
    if len(balances) != 2 or balances[0] + sum((Decimal(tx.amount) for tx in batch.transactions), Decimal(0)) != balances[1]:
        raise ValueError('Anfangssaldo, Buchungen und Endsaldo konnten nicht abgestimmt werden.')
    if not batch.pdf_reviewed and any(e.get('ocr') for e in batch.pdf_booking_evidence):
        raise ValueError('Gescannten Auszug bitte über den allgemeinen PDF-Import prüfen.')
    batch.account_assignments = {account_key(owner): target}
    batch.documents = [doc for doc in batch.documents if doc.account == owner]
    batch.account_names = [owner]
    batch.force_import = True
    batch.replace_bank_bookings = [
        {key: tx[key] for key in ('import_id', 'depot', 'external_id')}
        for tx in repository.transactions()
        if tx['account'] == target_name and tx['kind'] == 'BANK_BOOKING'
        and start.isoformat() <= tx['date'] <= end.isoformat()]
    return batch


def import_renault_batches(repository, batches):
    results = []
    for batch in batches:
        try:
            prepared = prepare_renault_batch(repository, batch)
            results.extend(repository.commit_batches([prepared]))
        except ValueError as error:
            results.append({'path': batch.path, 'status': 'error', 'errors': [str(error)]})
    return results
