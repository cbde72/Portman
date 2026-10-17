"""Baader Bank PDF plugin; loaded from the user-visible plugin directory."""
from portfolio_v5.pdf_plugins import Detection


class BaaderPdfPlugin:
    plugin_id = 'baader.pdf'
    bank_name = 'Baader Bank'
    version = '1.0'
    document_types = ('Quartalsaufstellung, Jahresdepotauszug, Wertpapierabrechnung, '
                      'Dividendenabrechnung, Vorabpauschale, Depotein-/auslieferung')

    def detect(self, document):
        from pdf_plugins._baader_core import is_baader_portfolio
        pages = [page.text for page in document.pages]
        if not is_baader_portfolio(pages):
            return []
        kinds = (('quartalsaufstellung', 'Baader Quartalsaufstellung', 'Quartalsaufstellung'),
                 ('jahresdepotauszug', 'Baader Jahresdepotauszug', 'Depotauszug per'),
                 ('dividende', 'Baader Dividendenabrechnung', 'Dividendenabrechnung'),
                 ('vorabpauschale', 'Baader Vorabpauschale', 'Vorabpauschale'),
                 ('depotuebertrag', 'Baader Depotein-/auslieferung', 'Depoteinlieferung'),
                 ('depotuebertrag', 'Baader Depotein-/auslieferung', 'Depotauslieferung'),
                 ('wertpapierabrechnung', 'Baader Wertpapierabrechnung', 'Wertpapierabrechnung:'))
        selected = next(((handler, title) for handler, title, marker in kinds if marker in document.text), None)
        if selected is None:
            return []
        handler, title = selected
        return [Detection(1.0, title, handler,
                          'Baader Bank, Depotnummer und Dokumentkopf erkannt')]

    def parse(self, document, detection, context):
        if any(page.used_ocr for page in document.pages):
            raise ValueError('Baader-Depotbelege benötigen eingebetteten Text zur sicheren Bestandsprüfung.')
        from pdf_plugins._baader_core import parse_baader_portfolio
        return parse_baader_portfolio(context.batch, [page.text for page in document.pages], document.content)


plugin = BaaderPdfPlugin()
