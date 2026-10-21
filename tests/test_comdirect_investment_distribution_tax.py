import importlib.util
from pathlib import Path

from portfolio_v5.models import BankTransaction, ImportBatch, Kind
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage
from portman.repository_v09 import RepositoryV09


ROOT = Path(__file__).resolve().parents[1]


def plugin():
    path = ROOT / 'pdf_plugins' / 'comdirect_ertraege.py'
    spec = importlib.util.spec_from_file_location('comdirect_distribution_tax_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def notice(*, origin='Inländische', day='15.09.2026', value_day=None, reference='1IINP4025ZX000SB',
           gross='9,10', partial='2,73', taxable='6,37', kapst='1,59', soli='0,08',
           church='0,00', paid='1,67', net='7,43'):
    value_day = value_day or day
    text = f'''comdirect bank AG
Datum: {day}
Depotnummer: 476492400
Referenz-Nummer: {reference}
Steuerliche Behandlung: {origin} Investment-Ausschüttung vom {day}
Stk. 27,051 IS.DJ AS.PAC.S.D.50 U.ETF, WKN/ISIN: A0H074/DE000A0H0744
Zu Ihren Gunsten vor Steuern: EUR {gross}
Steuerbemessungsgrundlage (1) EUR {taxable}
Kapitalertragsteuer EUR -{kapst}
Solidaritätszuschlag EUR -{soli}
Kirchensteuer EUR {church}
abgeführte Steuern EUR -{paid}
Zu Ihren Gunsten nach Steuern: EUR {net}
Die Gutschrift erfolgt mit Valuta {value_day} auf Konto EUR mit der IBAN DE71200411330476492440
Investment-Ausschüttung EUR {gross}
Teilfreistellung (30%) EUR -{partial}
Steuerbemessungsgrundlage vor Verlustverrechnung EUR {taxable}
'''
    return PdfDocument(Path('distribution-tax.pdf'), b'%PDF-test\n%%EOF', 'distribution-tax',
                       (PdfPage(1, text),))


def parse(source):
    importer = plugin()
    detection = importer.detect(source)[0]
    batch = ImportBatch(str(source.path), source.file_hash, source_sheet='PDF')
    return detection, importer.parse(source, detection, ParseContext(batch))


def test_reference_notice_is_structured_without_second_distribution():
    detection, batch = parse(notice())
    event, tax = batch.tax_events[0], batch.transactions[0]
    assert detection.handler_id == 'investment_ausschuettung'
    assert event.type == 'investment_ausschuettung_inland'
    assert (event.security_ref, event.quantity, event.date, event.document_date) == (
        'DE000A0H0744', '27.051', '2026-09-15', '2026-09-15')
    assert (event.partial_exemption_rate, event.partial_exemption_amount,
            event.taxable_income) == ('30', '2.73', '6.37')
    assert (event.capital_gains_tax, event.solidarity_surcharge,
            event.church_tax, event.paid_taxes) == ('1.59', '0.08', '0.00', '1.67')
    assert (tax.kind, tax.amount, tax.taxes, tax.account) == (
        Kind.TAX, '-1.67', '1.67', 'IBAN DE71200411330476492440')
    assert not any(tx.kind in (Kind.DIVIDEND, Kind.DISTRIBUTION) for tx in batch.transactions)
    assert batch.securities[0].wkn == 'A0H074'
    assert batch.documents[0].content_b64


def test_foreign_notice_and_documented_zero_remain_cash_neutral():
    _, batch = parse(notice(origin='Ausländische', gross='9,10', partial='0,00', taxable='9,10',
                            kapst='0,00', soli='0,00', paid='0,00', net='9,10'))
    event = batch.tax_events[0]
    assert event.type == 'investment_ausschuettung_ausland'
    assert (event.partial_exemption_amount, event.paid_taxes) == ('0.00', '0.00')
    assert batch.transactions == []
    assert event.related_transaction_id == ''


def test_foreign_notice_preserves_distinct_treatment_and_value_dates():
    _, batch = parse(notice(origin='Ausländische', day='27.02.2026', value_day='02.03.2026'))
    event, payment = batch.tax_events[0], batch.transactions[0]
    assert event.date == '2026-02-27'
    assert (payment.date, payment.value_date) == ('2026-02-27', '2026-03-02')


def test_existing_distribution_is_not_duplicated_and_reimport_is_idempotent(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 476492400', {'kind': 'Depot', 'institution': 'comdirect'})
        repo.save_account('IBAN DE71200411330476492440', {'kind': 'Verrechnungskonto'})
        income = BankTransaction(
            'Depot 476492400', 'income-existing', '2026-09-15', Kind.DIVIDEND, '9.10', 'EUR',
            security='DE000A0H0744', quantity='27.051', gross_amount='9.10', income_basis='gross',
            cash_account='IBAN DE71200411330476492440', document_reference='INCOME-REF')
        repo.commit_batches([ImportBatch('income.pdf', 'income', source_sheet='PDF', transactions=[income])])
        _, first = parse(notice())
        first.documents = []
        first_result = repo.commit_batches([first])[0]
        assert first_result.get('transactions') == 1, first_result
        _, duplicate = parse(notice())
        duplicate.documents = []
        result = repo.commit_batches([duplicate])[0]
        assert result['transactions'] == 0
        transactions = repo.transactions()
        assert sum(tx['kind'] == Kind.DIVIDEND for tx in transactions) == 1
        assert sum(tx['kind'] == Kind.TAX for tx in transactions) == 1
        assert len(repo.tax_events()) == 1
    finally:
        repo.close()


def test_multiple_distributions_in_one_tax_year_remain_distinct(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 476492400', {'kind': 'Depot', 'institution': 'comdirect'})
        repo.save_account('IBAN DE71200411330476492440', {'kind': 'Verrechnungskonto'})
        _, first = parse(notice(day='15.06.2026', reference='1OINIWDRSH0002OL'))
        _, second = parse(notice(day='15.09.2026', reference='1IINP4025ZX000SB'))
        first.documents = second.documents = []
        assert repo.commit_batches([first])[0]['status'] == 'imported'
        assert repo.commit_batches([second])[0]['status'] == 'imported'
        assert len(repo.tax_events()) == 2
        assert sum(tx['kind'] == Kind.TAX for tx in repo.transactions()) == 2
    finally:
        repo.close()
