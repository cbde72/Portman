"""Baader Bank PDF plugin; loaded from the user-visible plugin directory."""
from portfolio_v5.pdf_plugins import Detection


class BaaderPdfPlugin:
    plugin_id = 'baader.pdf'
    bank_name = 'Baader Bank'
    version = '1.0'
    document_types = 'Quartalsaufstellung, Wertpapierabrechnung'

    def detect(self, document):
        from pdf_plugins._baader_core import is_baader_portfolio
        pages = [page.text for page in document.pages]
        if not is_baader_portfolio(pages):
            return []
        handler = 'quartalsaufstellung' if 'Quartalsaufstellung' in document.text else 'wertpapierabrechnung'
        title = 'Baader Quartalsaufstellung' if handler == 'quartalsaufstellung' else 'Baader Wertpapierabrechnung'
        return [Detection(1.0, title, handler,
                          'Baader Bank, Depotnummer und Dokumentkopf erkannt')]

    def parse(self, document, detection, context):
        if any(page.used_ocr for page in document.pages):
            raise ValueError('Baader-Depotbelege benötigen eingebetteten Text zur sicheren Bestandsprüfung.')
        from pdf_plugins._baader_core import parse_baader_portfolio
        return parse_baader_portfolio(context.batch, [page.text for page in document.pages], document.content)


plugin = BaaderPdfPlugin()
