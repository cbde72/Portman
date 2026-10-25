"""External Renault Bank statement and archive-document parser."""
import base64
import re
from decimal import Decimal

from portfolio_v5.models import AccountStatement, BankDocument, digest, money, parse_date
from portfolio_v5.pdf_plugins import Detection
from pdf_plugins._generic_document import parse_generic_document
from pdf_plugins._statement_bookings import AMOUNT, HEADER, statement_end


class RenaultStatementPlugin:
    plugin_id = 'renault.kontoauszug'
    bank_name = 'Renault Bank direkt'
    version = '2.0'
    document_types = ('Kontoauszug (altes und aktuelles Layout), Zinsmitteilung, '
                      'Jahressteuerbescheinigung und sonstige Renault-Postfachdokumente')

    ARCHIVE_TYPES = (
        ('zinsmitteilung', 'Renault Zinsmitteilung', r'\bZinsmitteilung\b'),
        ('steuerbescheinigung', 'Renault Jahressteuerbescheinigung',
         r'\b(?:Jahres-?Steuerbescheinigung|Steuerbescheinigung)\b'),
        ('freistellungsauftrag', 'Renault Freistellungsauftrag', r'\bFreistellungsauftrag\b'),
        ('umsatzuebersicht', 'Renault Umsatzübersicht',
         r'Filterparameter\s+\d+\s+Tage\s+Buchungsdatum.*?\bUmsätze\b'),
    )

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
        if not matched:
            return []
        for handler, label, pattern in self.ARCHIVE_TYPES:
            if re.search(pattern, document.text, re.I | re.S):
                return [Detection(.995, label, handler,
                                  f'Renault/RCI-Kennung und {label} erkannt')]
        explicit_statement = re.search(
            r'^\s*K\s*o\s*n\s*t\s*o\s*a\s*u\s*s\s*z\s*u\s*g'
            r'(?:\s+Nr\.?\s*[\d/]+)?\s*$', document.text, re.I | re.M)
        if explicit_statement:
            return [Detection(.98, 'Kontoauszug', 'kontoauszug',
                              'Renault/RCI-Kennung und Kontoauszugtitel erkannt')]
        return [Detection(.90, 'Renault Archivdokument', 'archiv',
                          'Renault/RCI-Kennung ohne belegte Buchungstabelle erkannt')]

    def parse(self, document, detection, context):
        if detection.handler_id != 'kontoauszug':
            return self._archive_only(document, detection, context.batch)
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

    def _archive_only(self, document, detection, batch):
        """Archive non-statements without creating inferred cash or tax records."""
        text = document.text
        iban = re.search(r'\bIBAN\s*:\s*(DE(?:\s*\d){20})\b', text, re.I)
        account = ('IBAN ' + re.sub(r'\s+', '', iban.group(1)).upper()
                   if iban else 'Archiv Renault Bank direkt')
        date_match = re.search(
            r'(?:\berstellt\s+am|\bDatum\b)\s*:?[ \t\r\n]*(\d{2}\.\d{2}\.\d{4})', text, re.I)
        if not date_match:
            date_match = re.search(r'\bvom\s+(\d{2}\.\d{2}\.\d{4})\b', text, re.I)
        document_date = parse_date(date_match.group(1)) if date_match else ''
        reference = re.search(r'\b(?:T|K)\d{8}\b', text)
        external_id = batch.file_hash + ':' + account
        batch.documents.append(BankDocument(
            account, external_id, document.path.name, document_date or '',
            base64.b64encode(document.content).decode('ascii'),
            document_type=detection.document_type, bank_name=self.bank_name,
            document_no=reference.group(0) if reference else '',
            page_count=len(document.pages), extraction_method='PDF-Text'))
        batch.account_names.append(account)
        batch.document_type = detection.document_type
        batch.pdf_text = '\n\n'.join(
            f'--- Seite {page.number} ---\n{page.text}' for page in document.pages)
        reason = {
            'zinsmitteilung': ('Zinsmitteilung wiederholt einen Kontoauszug; archiviert ohne zusätzliche '
                               'Zins-, Steuer- oder Kontobuchung.'),
            'steuerbescheinigung': ('Jahressteuerbescheinigung ist ein Steueraggregat; archiviert ohne '
                                    'zusätzliche Zins-, Steuer- oder Kontobuchung.'),
            'freistellungsauftrag': ('Freistellungsauftrag dokumentiert einen Auftrag, keine Nutzung; '
                                     'archiviert ohne Änderung der FSA-Aggregation.'),
            'umsatzuebersicht': ('Umsatzübersicht überlappt formale Kontoauszüge und belegt keinen eindeutigen '
                                 'Ersatzzeitraum; archiviert ohne doppelte Kontobuchungen.'),
            'archiv': 'Kein formaler Kontoauszug; archiviert ohne wirtschaftliche Buchung.',
        }[detection.handler_id]
        batch.warnings.append(reason)
        return batch


plugin = RenaultStatementPlugin()
