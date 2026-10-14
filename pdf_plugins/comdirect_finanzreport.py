"""External comdirect Finanzreport plugin for old and current layouts."""
from portfolio_v5.pdf_plugins import Detection
from pdf_plugins._comdirect_finanzreport_core import is_finanzreport, parse_finanzreport


class ComdirectFinanzreportPlugin:
    plugin_id = 'comdirect.finanzreport'
    bank_name = 'comdirect'
    version = '2.0'
    document_types = 'Finanzreport (altes und aktuelles Layout)'

    def detect(self, document):
        return ([Detection(1.0, 'comdirect Finanzreport', 'finanzreport',
                           'Bankname und Finanzreport-Kopf erkannt')]
                if is_finanzreport([page.text for page in document.pages]) else [])

    def parse(self, document, detection, context):
        if any(page.used_ocr for page in document.pages):
            raise ValueError('comdirect Finanzreport: gescannte Seiten bitte einzeln in der Vorschau prüfen.')
        return parse_finanzreport(context.batch, [page.text for page in document.pages], document.content)


plugin = ComdirectFinanzreportPlugin()
