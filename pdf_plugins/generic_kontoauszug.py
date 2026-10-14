"""Fallback plugin for document storage and conservative statement tables."""
from portfolio_v5.pdf_plugins import Detection
from pdf_plugins._generic_document import parse_generic_document
from pdf_plugins._statement_classification import classify_document


class GenericStatementPlugin:
    plugin_id = 'generic.kontoauszug'
    bank_name = 'Allgemeiner PDF-Import'
    version = '2.0'
    document_types = 'Kontoauszüge und Dokumentablage'

    def detect(self, document):
        kind = classify_document([page.text for page in document.pages])
        return [Detection(.70, kind, 'generic', 'Generischer, prüfpflichtiger PDF-Import')]

    def parse(self, document, detection, context):
        return parse_generic_document(document, context.batch)


plugin = GenericStatementPlugin()
