"""External Renault Bank statement detector and parser."""
import re
from decimal import Decimal

from portfolio_v5.models import AccountStatement, digest, money, parse_date
from portfolio_v5.pdf_plugins import Detection
from pdf_plugins._generic_document import parse_generic_document
from pdf_plugins._statement_bookings import AMOUNT, HEADER, statement_end


class RenaultStatementPlugin:
    plugin_id = 'renault.kontoauszug'
    bank_name = 'Renault Bank direkt'
    version = '2.0'
    document_types = 'Kontoauszug (altes und aktuelles Layout)'

    def detect(self, document):
        matched = bool(re.search(r'Renault|RCI\s+Banque', document.text, re.I))
        if not matched:
            for page in document.pages:
                header = []
                for line in page.text.splitlines():
                    if HEADER.search(line):
                        break
                    header.append(line)
                if re.search(r'\bBIC\s*:?\s*RCIDDE3N(?:PAY|XXX)?\b', '\n'.join(header), re.I):
                    matched = True
                    break
        return [Detection(.98, 'Kontoauszug', 'kontoauszug', 'Renault/RCI-Kennung erkannt')] if matched else []

    def parse(self, document, detection, context):
        result = parse_generic_document(document, context.batch)
        if result.document_type != 'Kontoauszug':
            raise ValueError('Renault-Dokument erkannt, aber keine unterstützte Buchungstabelle gefunden.')
        mismatch = next((warning for warning in result.warnings if 'Saldenprüfung weicht um' in warning), None)
        if mismatch:
            raise ValueError(mismatch)
        owners = {tx.account for tx in result.transactions}
        balance_lines = [line for line in document.text.splitlines()
                         if re.search(r'(?:alter|neuer)\s+Kontostand', line, re.I)]
        balances = []
        for line in balance_lines:
            amount = AMOUNT.search(line)
            if amount:
                sign = -1 if amount['before'] == '-' or amount['after'] in ('S', '-') else 1
                balances.append(Decimal(money(amount['number'])) * sign)
        closing = statement_end(document.text)
        opening = re.search(r'alter\s+Kontostand\s+vom\s*(\d{2}\.\d{2}\.\d{4})', document.text, re.I)
        if len(owners) == 1 and len(balances) == 2 and opening and closing:
            account = next(iter(owners))
            statement_no = re.search(r'Kontoauszug\s*(?:Nr\.)?\s*([\d/]+)', document.text, re.I)
            start = parse_date(opening.group(1))
            result.statements.append(AccountStatement(
                account=account, statement_no=statement_no.group(1) if statement_no else '',
                period_start=start, period_end=closing.isoformat(), opening_balance=str(balances[0]),
                opening_date=start, closing_balance=str(balances[1]), closing_date=closing.isoformat(),
                currency='EUR', external_id='pdf-renault-statement-' + digest([
                    account, statement_no.group(1) if statement_no else '', closing.isoformat()])))
        return result


plugin = RenaultStatementPlugin()
