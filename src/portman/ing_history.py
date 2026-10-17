"""Historical ING data: capability-driven retrieval, no completeness claims."""
import base64
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
import hashlib
from pathlib import Path
import re

from portfolio_v5.models import BankDocument, BankTransaction, ImportBatch, digest
from portfolio_v5.booking_details import classify_cash_booking
from .bank_history_range import ALL_HISTORY_START
from .ing_banking import (BankingError, Cancelled, decimal_value, SOURCE,
                          safe_diagnostic, reset_diagnostic, check_bank_response)


def iso_date(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    raise BankingError('Die Bankantwort enthält kein eindeutiges Buchungsdatum.')


def parse_transactions(rows, account, start, end, *, source_prefix='ing'):
    result = []
    occurrences = Counter()
    for row in rows:
        data = row.data
        # MT940 `date` is value date; guessed_entry_date resolves the booking year.
        booked = iso_date(data.get('guessed_entry_date') or data.get('entry_date') or data.get('date'))
        value_date = iso_date(data.get('date'))
        if not start.isoformat() <= booked <= end.isoformat():
            continue
        amount = data.get('amount')
        currency = getattr(amount, 'currency', None) or data.get('currency')
        if not currency or not re.fullmatch(r'[A-Z]{3}', str(currency)):
            raise BankingError('Eine Kontobuchung hat keine gültige Währung.')
        amount = str(decimal_value(getattr(amount, 'amount', None)).normalize())
        def clean(key):
            value = data.get(key)
            if value is None:
                return ''
            if isinstance(value, (list, tuple)):
                value = ' '.join(str(item) for item in value)
            return ' '.join(str(value).split())
        bank_reference = next((clean(key) for key in ('bank_reference', 'end_to_end_reference',
            'customer_reference', 'transaction_reference', 'mandate_reference') if clean(key)), '')
        transaction = BankTransaction(account, '', booked, 'BANK_BOOKING', amount, currency,
            value_date=value_date, purpose=clean('purpose'), counterparty=clean('applicant_name'),
            bank_reference=bank_reference, document_reference=bank_reference)
        # Not every ING booking has a unique bank reference (e.g. NONREF).
        # Content + occurrence per identical booking preserves genuine twins and
        # stays stable across repeated/overlapping queries of whole booking days.
        identity = digest({k: v for k, v in asdict(transaction).items() if k not in
                           ('row', 'external_id', 'operation', 'booking_text', 'counterparty_iban', 'counterparty_bic', 'raw_text')})
        occurrences[identity] += 1
        transaction.external_id = f'{source_prefix}-booking-{identity}-{occurrences[identity]}'
        transaction.counterparty_iban = clean('applicant_iban')
        transaction.counterparty_bic = clean('applicant_bic')
        transaction.operation = clean('transaction_details')
        transaction.booking_text = clean('purpose')
        transaction.raw_text = str(data.get('transaction_details') or '') + '\n' + str(data.get('purpose') or '')
        if source_prefix == 'renault':
            classify_cash_booking(transaction)
        result.append(transaction)
    return sorted(result, key=lambda t: (t.date, t.external_id))


def document_from_bytes(account, external_id, title, document_date, data):
    if not isinstance(data, bytes) or not data.startswith(b'%PDF-') or b'%%EOF' not in data[-4096:]:
        raise BankingError('Kein vollständiges PDF-Dokument geliefert; Dokument wurde nicht übernommen.')
    return BankDocument(account, external_id, title, document_date,
                        base64.b64encode(data).decode('ascii'))


def fetch_history(client, account, ops, source, path, checked, progress, *, start, end, documents,
                  source_sheet=SOURCE, source_prefix='ing'):
    from fints.client import FinTSOperations as Op
    from fints.formals import StatementFormat
    from fints.exceptions import FinTSClientPINError, FinTSSCARequiredError, FinTSClientTemporaryAuthError, FinTSUnsupportedOperation
    fatal = (Cancelled, FinTSClientPINError, FinTSSCARequiredError, FinTSClientTemporaryAuthError)
    batches = []
    def batch_for(suffix):
        batch = ImportBatch(str(Path(path).with_name(Path(path).stem + '-' + suffix + '.bank')),
                            '', account_names=[source], source_sheet=source_sheet)
        batches.append(batch)
        return batch

    if start is not None:
        batch = batch_for('umsaetze')
        requested_start = 'gesamte verfügbare Historie' if start == ALL_HISTORY_START else start.isoformat()
        batch.warnings.append(f'Angefordert: {requested_start} bis {end.isoformat()}. '
            'Die verfügbare Historie hängt von der Bank ab. Die Antwort bestätigt keine lückenlose Historie. '
            'Buchungen werden nicht automatisch als Wertpapierkäufe oder Dividenden eingestuft.')
        if not (ops.get(Op.GET_TRANSACTIONS) or ops.get(Op.GET_TRANSACTIONS_XML)):
            batch.errors.append('Umsatzabruf ist für dieses Konto über FinTS nicht freigegeben.')
        else:
            progress(f'Umsätze für {source} werden abgerufen …')
            try:
                reset_diagnostic(client)
                rows = checked(client.get_transactions(account,
                    start_date=None if start == ALL_HISTORY_START else start,
                    end_date=end, include_pending=False))
                check_bank_response(client)
                if rows is None:
                    raise BankingError('Keine verwertbare Umsatzantwort erhalten.')
                batch.transactions = parse_transactions(rows, source, start, end, source_prefix=source_prefix)
                batch.history_end = end.isoformat()
                if not batch.transactions:
                    batch.warnings.append('Keine neuen gebuchten Umsätze im angeforderten Zeitraum geliefert.')
                else:
                    dates = [t.date for t in batch.transactions]
                    batch.warnings.append(f'Geliefert: {len(dates)} Buchungen, {min(dates)} bis {max(dates)}. '
                        'Bei nachträglich geändertem Buchungstext ohne stabile Bank-ID kann ein zusätzlicher Eintrag entstehen.')
            except fatal:
                raise
            except BankingError as error:
                batch.errors.append(str(error) + ' ' + safe_diagnostic(client, 'Kontoumsätze abrufen', error))
            except Exception as error:
                batch.errors.append('Umsatzabruf fehlgeschlagen; andere Abrufteile können separat übernommen werden. '
                                    + safe_diagnostic(client, 'Kontoumsätze abrufen', error))
        batch.file_hash = digest([asdict(t) for t in batch.transactions])

    if documents:
        notice = batch_for('dokumentstatus')
        notice.warnings.append('Elektronische Kontoauszüge sind nicht die vollständige ING-Post-Box. '
                               'Steuerunterlagen und Wertpapierabrechnungen gegebenenfalls dort herunterladen.')
        if not ops.get(Op.GET_STATEMENT):
            notice.errors.append('Kein unterstützter Kontoauszugsabruf freigegeben. Dokumente bitte aus der ING-Post-Box herunterladen und im Bankarchiv hinzufügen.')
        else:
            progress(f'Kontoauszüge für {source} werden gesucht …')
            try:
                statements = checked(client.get_statements(account))
                seen = set()
                for statement in statements:
                    checked(None)
                    year, number = statement.year, statement.statement_number
                    created = statement.date_created
                    if isinstance(created, datetime):
                        created = created.date()
                    if isinstance(created, date) and (created > end or (start is not None and created < start)):
                        continue
                    if not year and isinstance(statement.date_created, date):
                        year = statement.date_created.year
                    if not year or number is None or not statement.collection_possible:
                        notice.warnings.append('Ein gemeldeter Auszug ist nicht abholbar oder besitzt keine eindeutige Jahres-/Nummerangabe.')
                        continue
                    year, number = int(year), int(number)
                    if not 1900 <= year <= date.today().year or not 0 <= number <= 99999:
                        raise BankingError('Ungültige Kontoauszugskennung in der Bankantwort.')
                    if (year, number) in seen:
                        continue
                    seen.add((year, number))
                    batch = batch_for(f'auszug-{year}-{number}')
                    try:
                        progress(f'Kontoauszug {year}/{number} für {source} wird abgerufen …')
                        response = checked(client.get_statement(account, number, year, format=StatementFormat.PDF))
                        if response is None or (getattr(response, 'account_iban', None) and account.iban
                                                and response.account_iban != account.iban):
                            raise BankingError('Kontoauszug fehlt oder gehört zu einem anderen Konto.')
                        created = iso_date(statement.date_created) if isinstance(statement.date_created, date) else ''
                        document = document_from_bytes(source, f'{year}-{number}', f'Kontoauszug {year}/{number}', created, response.data)
                        batch.documents.append(document)
                        batch.file_hash = digest(asdict(document))
                    except fatal:
                        raise
                    except BankingError as error:
                        batch.errors.append(str(error))
                    except Exception:
                        batch.errors.append('Dieser Kontoauszug konnte nicht als PDF abgerufen werden.')
                notice.errors.append(f'{len(seen)} abholbare Auszüge gemeldet. Die einzelnen Ergebnisse stehen separat in der Vorschau. '
                                     'Dieser Statushinweis wird nicht importiert.')
            except fatal:
                raise
            except FinTSUnsupportedOperation:
                notice.errors.append('Die Bank bietet keine unterstützte Auszugsliste an. Kein vollständiger Dokumentenabruf möglich.')
            except BankingError as error:
                notice.errors.append(str(error))
            except Exception:
                notice.errors.append('Die Kontoauszugsliste konnte nicht abgerufen werden.')
    return batches


def local_document_batch(path, account):
    path = Path(path)
    data = path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    document = document_from_bytes(account, 'local-' + checksum, path.name, '', data)
    return ImportBatch(str(path), checksum, documents=[document], account_names=[account],
        source_sheet=SOURCE, warnings=['Manuell aus der ING-Post-Box hinzugefügt; Dokumentdatum noch nicht ermittelt.'])
