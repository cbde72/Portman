import importlib.util
from pathlib import Path

import pytest

from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage


ROOT = Path(__file__).resolve().parents[1]


def plugin():
    path = ROOT / 'pdf_plugins' / 'renault_kontoauszug.py'
    spec = importlib.util.spec_from_file_location('renault_p2_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def document(body, file_hash='renault-p2'):
    text = 'Renault Bank direkt\nBIC: RCIDDE3NPAY\n' + body
    return PdfDocument(Path('renault.pdf'), b'%PDF-renault', file_hash, (PdfPage(1, text),))


@pytest.mark.parametrize(('body', 'handler', 'kind'), [
    ('Zinsmitteilung\nZinsmitteilung Festgeld 130765701 - keine Steuerbescheinigung -\n'
     'IBAN: DE56 3052 0037 0130 7657 01\nZinsen: EUR 391,87\nEinbehaltene KapSt: EUR 97,97',
     'zinsmitteilung', 'Renault Zinsmitteilung'),
    ('Steuerbescheinigung\nwerden für das Kalenderjahr 2025 folgende Angaben bescheinigt:',
     'steuerbescheinigung', 'Renault Jahressteuerbescheinigung'),
    ('Freistellungsauftrag für Kapitalerträge\nDieser Auftrag gilt ab dem 01.01.2022',
     'freistellungsauftrag', 'Renault Freistellungsauftrag'),
    ('Filterparameter 90 Tage Buchungsdatum, absteigend\nUmsätze\nEUR+129.000,00(Endsaldo)',
     'umsatzuebersicht', 'Renault Umsatzübersicht'),
    ('Ihr Festgeld wird bald fällig\nDas Festgeld wird auf Ihr Tagesgeldkonto umgebucht.',
     'archiv', 'Renault Archivdokument'),
])
def test_non_statement_documents_are_classified_and_archived_without_booking(body, handler, kind):
    importer = plugin()
    source = document(body)
    detection = importer.detect(source)[0]
    batch = importer.parse(source, detection,
                           ParseContext(ImportBatch('renault.pdf', source.file_hash, source_sheet='PDF')))
    assert (detection.handler_id, batch.document_type) == (handler, kind)
    assert batch.transactions == []
    assert batch.tax_events == []
    assert len(batch.documents) == 1
    assert batch.documents[0].document_type == kind
    assert batch.warnings


def test_formal_statement_remains_booking_handler():
    importer = plugin()
    source = document('''Kontoauszug Nr. 1/2026
Kontonummer: 12345678
erstellt am 29.02.2026
Bu-Tag Wert Vorgang
alter Kontostand vom 31.01.2026 1.000,00 H
28.02. 28.02. Zins 10,00 H
neuer Kontostand vom 28.02.2026 1.010,00 H
EUR''')
    detection = importer.detect(source)[0]
    batch = importer.parse(source, detection,
                           ParseContext(ImportBatch('statement.pdf', source.file_hash, source_sheet='PDF')))
    assert detection.handler_id == 'kontoauszug'
    assert len(batch.transactions) == 1
    assert batch.transactions[0].amount == '10.00'
    assert batch.statements[0].closing_balance == '1010.00'
