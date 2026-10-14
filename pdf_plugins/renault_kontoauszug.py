"""External Renault Bank statement detector and parser."""
import re

from portfolio_v5.pdf_plugins import Detection
from pdf_plugins._generic_document import parse_generic_document
from pdf_plugins._statement_bookings import HEADER


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
        return result


plugin = RenaultStatementPlugin()
