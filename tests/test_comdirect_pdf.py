import os
from decimal import Decimal
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import BankTransaction, ImportBatch
from pdf_plugins._comdirect_finanzreport_core import parse_finanzreport, is_finanzreport
from portman.repository import PortfolioRepository


def report():
    return ["""comdirect
Finanzreport Nr. 1 per 01.02.2021
Kundennummer 102 1234567
Girokonto DE89 3704 0044 0532 0130 00 +110,00
Girokonto
Buchungstag Vorgang Auftraggeber/Empfänger Buchungstext Ausgang
Valuta Referenz IBAN/BIC Eingang
Alter Saldo 31.12.2020 +100,00
04.01.2021 Überweisung Von Gegenkonto +20,00
05.01.2021 IBAN DE12500105170648489890
Referenz erster Teil
comdirect – eine Marke der Commerzbank AG
25449 Quickborn
""", """Finanzreport Nr. 1 per 01.02.2021 - Seite 2
Kundennummer 102 1234567
Buchungstag Vorgang Auftraggeber/Empfänger Buchungstext Ausgang
Valuta Referenz IBAN/BIC Eingang
Referenz zweiter Teil
01.02.2021 Belastung Einkauf -10,00
03.02.2021 Valuta
Neuer Saldo 01.02.2021 +110,00
Depot
Depotbestand EUR EUR EUR
WKN / Verwahrart Anzahl / Nominal letzter Währung Kurswert Kaufwert Gewinn / Verlust
Bezeichnung Kurs Stückzinsen
ABC123 / Girosammelverwahrung 2,000 10,000 USD 20,0018,00 +2,00
TEST FONDS +0,00
Gesamtkurswert 20,00 18,00 +2,00
Gesamtwert 20,00
"""]


def parsed(pages=None):
    from io import BytesIO
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    content = BytesIO()
    writer.write(content)
    return parse_finanzreport(ImportBatch('report.pdf', 'hash', source_sheet='PDF'), pages or report(), content.getvalue())


def test_finanzreport_accounts_continuations_values_and_reconciliation(tmp_path):
    assert is_finanzreport(report())
    b = parsed()
    assert len(b.transactions) == 2
    assert b.transactions[0].value_date == '2021-01-05'
    assert b.transactions[1].value_date == '2021-02-03'
    assert 'Referenz zweiter Teil' in b.transactions[0].purpose
    assert b.account_names == ['IBAN DE89370400440532013000', 'Depot 1234567']
    assert len(b.snapshots[0].positions) == 1
    position = b.snapshots[0].positions[0]
    assert (position.value, position.cost, position.currency) == ('20.00', '18.00', 'EUR')
    repo = PortfolioRepository(tmp_path / 'report.sqlite')
    try:
        repo.save_account('Giro', {'iban': 'DE89370400440532013000'})
        repo.save_account('Depot', {'number': '1234567'})
        b.account_assignments = {s['key']: s['target_key'] for s in repo.import_account_suggestions(b)}
        assert all(b.account_assignments.values())
        assert repo.commit_batches([b])[0]['status'] == 'imported'
        assert repo.commit_batches([b])[0]['status'] == 'duplicate'
        assert len(repo.transactions('Giro')) == 2
        assert not repo.holdings('2021-01-31')
        assert len(repo.holdings('2021-02-01', 'Depot')) == 1
        assert repo.store.balances_at('2021-01-01')[0]['effective_date'] == '2020-12-31'
        rows = {r['name']: r for r in repo.account_overview('2021-01-31')}
        assert rows['Giro']['balance'] == Decimal('120')
    finally:
        repo.close()


def test_missing_last_pdf_page_cannot_create_complete_statement():
    with pytest.raises(ValueError, match='Saldo|saldo|abgestimmt'):
        parsed(report()[:1])


def test_interest_closing_is_structured_and_classified(tmp_path):
    pages = ["""comdirect
Finanzreport Nr. 3 per 30.09.2026
Kundennummer 102 1234567
Tagesgeldkonto DE89 3704 0044 0532 0130 00 +2.002,52
Tagesgeldkonto
Buchungstag Vorgang Auftraggeber/Empfänger Buchungstext Ausgang
Valuta Referenz IBAN/BIC Eingang
Alter Saldo 30.06.2026 +2.000,00
30.09.2026 Kontoabschluss Abschluss Zinsen Kto 476492405EUR +2,52
30.09.2026 4K5C29FM4LJ8 von 30.06.2026 bis 30.09.2026
4I6C/4160 Habenzinsen
0,750% ab 30.06. 3,42 EUR
vom 30.06.2026 bis 30.09.2026
Kapitalertragsteuer 0,86- EUR
Solidaritätszuschlag 0,04- EUR
Abschlussrechnung 2,52 EUR
Saldo nach Abschluss
2.002,52 EUR
Neuer Saldo 30.09.2026 +2.002,52
"""]

    batch = parsed(pages)
    tx = batch.transactions[0]

    assert tx.kind == 'INTEREST'
    assert tx.amount == '2.52'
    assert (tx.gross_income, tx.gross_currency, tx.taxes, tx.withholding_tax) == ('3.42', 'EUR', '0.90', None)
    assert tx.tax_rate == '26.32'
    assert tx.solidarity_tax == '0.04'
    assert (tx.fiscal_period_start, tx.fiscal_period_end, tx.value_date) == (
        '2026-06-30', '2026-09-30', '2026-09-30')
    assert [(item.kind, item.amount) for item in tx.tax_items] == [
        ('kapitalertragsteuer', '0.86'), ('solidaritaetszuschlag', '0.04')]
    assert 'Konto 476492405' in tx.purpose
    assert 'Habenzinsen 0,750 %' in tx.purpose
    assert 'Kapitalertragsteuer 0,86 EUR' in tx.purpose
    assert 'Solidaritätszuschlag 0,04 EUR' in tx.purpose
    assert 'Saldo nach Abschluss 2.002,52 EUR' in tx.purpose
    assert tx.operation == 'Zinsgutschrift'
    assert tx.counterparty == 'comdirect'
    assert tx.document_reference == 'Zinsabschluss Konto 476492405 · 30.09.2026'

    repo = PortfolioRepository(tmp_path / 'interest.sqlite')
    try:
        repo.save_account('Tagesgeld', {'iban': 'DE89370400440532013000'})
        batch.account_assignments = {suggestion['key']: suggestion['target_key']
                                     for suggestion in repo.import_account_suggestions(batch)}
        assert repo.commit_batches([batch])[0]['status'] == 'imported'
        saved = repo.transactions('Tagesgeld')[0]
        assert saved['kind'] == 'INTEREST'
        assert (saved['gross_income'], saved['taxes'], saved['withholding_tax']) == ('3.42', '0.90', None)
        assert saved['tax_rate'] == '26.32'
        assert saved['solidarity_tax'] == '0.04'
        assert 'Habenzinsen 0,750 %' in saved['purpose']
    finally:
        repo.close()


def test_inconsistent_interest_closing_is_importable_but_requires_review():
    from pdf_plugins._comdirect_finanzreport_core import enrich_interest_closing
    tx = BankTransaction('Konto', '', '2026-09-30', 'BANK_BOOKING', '2.52', 'EUR',
        purpose='Abschluss Zinsen', raw_text=(
            'Abschluss Zinsen Kto 476492405 EUR XREF von 30.06.2026 bis 30.09.2026 Habenzinsen '
            '0,750% ab 30.06. 3,42 EUR vom 30.06.2026 bis 30.09.2026 '
            'Kapitalertragsteuer 0,80- EUR Abschlussrechnung 2,52 EUR'))
    batch = ImportBatch('report.pdf', 'hash')

    assert enrich_interest_closing(tx, batch)
    assert tx.kind == 'INTEREST'
    assert tx.gross_income == '3.42'
    assert tx.taxes == '0.80'
    assert tx.purpose.startswith('⚠ PRÜFUNG ERFORDERLICH')
    assert tx.field_sources['interest_reconciliation'].startswith('PRÜFUNG ERFORDERLICH:')
    assert batch.warnings[0].startswith('PRÜFUNG ERFORDERLICH:')


def test_interest_closing_supports_multiple_rate_components():
    from pdf_plugins._comdirect_finanzreport_core import enrich_interest_closing
    tx = BankTransaction('Konto', '', '2010-12-31', 'BANK_BOOKING', '21.23', 'EUR',
        purpose='Kontoabschluss', raw_text=(
            'Kontoabschluss Abschluss Zinsen Kto 476492405EUR 62E1100123427517/7126 '
            'von 30.09.2010 bis 31.12.2010 Habenzinsen '
            '2,000% ab 30.09. 3,06 EUR 1,000% ab 30.09. 1,23 EUR '
            '1,750% ab 11.10. 13,27 EUR 1,000% ab 11.10. 3,67 EUR '
            'Abschlussrechnung 21,23 EUR Saldo nach Abschluss 5.021,23 EUR'))
    batch = ImportBatch('report.pdf', 'hash')

    assert enrich_interest_closing(tx, batch)
    assert tx.kind == 'INTEREST'
    assert (tx.gross_income, tx.amount, tx.taxes) == ('21.23', '21.23', '0.00')
    assert 'Habenzinsen 2,000 % ab 30.09.: 3,06 EUR' in tx.purpose
    assert 'Habenzinsen 1,750 % ab 11.10.: 13,27 EUR' in tx.purpose
    assert 'Habenzinsen gesamt 21,23 EUR' in tx.purpose
    assert not batch.warnings


@pytest.mark.parametrize('old,new', [('+110,00', '+111,00'), ('20,00 18,00 +2,00', '21,00 18,00 +2,00'), ('20,0018,00 +2,00', '20,0018,00 +3,00')])
def test_incomplete_or_inconsistent_report_is_rejected(old, new):
    pages = [p.replace(old, new) for p in report()]
    with pytest.raises(ValueError):
        parsed(pages)


def test_skip_depot_excludes_snapshot_and_source(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.import_preview import ImportPreviewDialog
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'skip.sqlite')
    try:
        repo.save_account('Giro', {'iban': 'DE89370400440532013000'})
        repo.save_account('Depot', {'number': '1234567'})
        dialog = ImportPreviewDialog(repo, [parsed()])
        for _, source, combo, _ in dialog.mapping_rows:
            if source['name'].startswith('Depot '):
                combo.setCurrentIndex(combo.findData('__skip__'))
        batch = dialog.selected_batches()[0]
        assert not batch.snapshots
        assert batch.account_names == ['IBAN DE89370400440532013000']
        assert len(batch.transactions) == 2
        dialog.close()
    finally:
        repo.close()



def legacy_report():
    return ["""comdirect bank AG
Ihre Kontonummer: 1234567
Finanzreport Nr. 9 per 03.10.2007
Girokonto +105,00
Tagesgeldkonto 0,00
Girokonto ec Tages-/Wochenlimit
EUR 500,-
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo +100,00
Übertrag/Überweisung 27.09.2007 27.09.2007 +10,00
Zahlungszweck
Girokonto
comdirect bank AG
""", """Finanzreport Nr. 9 per 03.10.2007 - Seite 2
Kontonummer 1234567 / BLZ 20041133
Umsätze (Fortsetzung)
Buchungstag Valuta Soll / Haben
Kontoabschluss 28.09.2007 30.09.2007 -5,00
Abschluss Kontoführung
Konto 1234567/00 EUR
Neuer Saldo +105,00
Tagesgeldkonto
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo 0,00
Neuer Saldo 0,00
"""]


def test_legacy_report_is_detected_and_reconciled(tmp_path):
    b = parsed(legacy_report())
    assert len(b.transactions) == 2
    assert {t.account for t in b.transactions} == {'Konto 0123456700'}
    assert b.transactions[-1].value_date == '2007-09-30'
    assert [v.value for v in b.balances] == ['105.00', '0.00']
    assert len(b.balances) == 2  # undated opening balances are not invented
    assert not b.snapshots
    repo = PortfolioRepository(tmp_path / 'legacy.sqlite')
    try:
        repo.save_account('Giro', {'number': '0123456700'})
        repo.save_account('Altes Tagesgeld', {})
        suggestions = repo.import_account_suggestions(b)
        assert next(s for s in suggestions if s['name'].startswith('Konto '))['target_key'] == 'giro'
        unknown = next(s for s in suggestions if s['name'].startswith('comdirect '))
        assert unknown['target_key'] is None
        b.account_assignments = {s['key']: s['target_key'] or 'altes tagesgeld' for s in suggestions}
        assert repo.commit_batches([b])[0]['status'] == 'imported'
        assert repo.commit_batches([b])[0]['status'] == 'duplicate'
        assert len(repo.transactions('Giro')) == 2
        assert repo.store.balances_at('2007-10-02') == []
        assert len(repo.store.balances_at('2007-10-03')) == 2
    finally:
        repo.close()


def test_legacy_bad_balance_is_rejected():
    with pytest.raises(ValueError, match='Saldenprüfung'):
        parsed([p.replace('+105,00', '+106,00') for p in legacy_report()])



def test_legacy_owner_iban_comes_from_header_not_counterparty():
    pages = [p.replace('1234567', '5320130') for p in legacy_report()]
    pages[0] = pages[0].replace('Ihre Kontonummer:', 'IBAN: DE89 3704 0044 0532 0130 00\nIhre Kontonummer:')
    pages[0] = pages[0].replace('Zahlungszweck', 'Zahlungszweck IBAN: DE12500105170648489890')
    batch = parsed(pages)
    assert {t.account for t in batch.transactions} == {'IBAN DE89370400440532013000'}
    assert batch.balances[0].account == 'IBAN DE89370400440532013000'
    invalid = [p.replace('DE89 3704', 'DE00 3704') for p in pages]
    with pytest.raises(ValueError, match='ungültige IBAN'):
        parsed(invalid)

@pytest.mark.parametrize('factory', [report, legacy_report])
def test_report_accepts_vom_date(factory):
    batch = parsed([p.replace(' per ', ' vom ') for p in factory()])
    assert batch.transactions


def test_conflicting_report_dates_are_rejected():
    pages = report()
    pages[1] = pages[1].replace('per 01.02.2021', 'per 02.02.2021')
    with pytest.raises(ValueError, match='Nur einen vollständigen Report'):
        parsed(pages)


def test_balance_diagnostic_has_amounts_and_next_step():
    with pytest.raises(ValueError) as exc:
        parsed([p.replace('+110,00', '+111,00') for p in report()])
    message = str(exc.value)
    assert 'Anfangssaldo 100,00 EUR' in message
    assert 'Buchungen 10,00 EUR' in message
    assert 'Differenz 1,00 EUR' in message
    assert 'Lösung:' in message


def test_invalid_balance_date_is_explained():
    with pytest.raises(ValueError, match='Saldendatum auf Seite 1'):
        parsed([p.replace('31.12.2020', '32.12.2020') for p in report()])


def test_failed_pdf_report_keeps_text_but_no_partial_records(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from portfolio_v5 import pdf_importer
    pages = [p.replace('+110,00', '+111,00') for p in report()]
    reader = SimpleNamespace(is_encrypted=False)
    reader.pages = [SimpleNamespace(extract_text=lambda text=text, **kwargs: text, images=[]) for text in pages]
    monkeypatch.setattr(pdf_importer, 'PdfReader', lambda path: reader)
    path = tmp_path / 'report.pdf'
    path.write_bytes(b'test')
    batch = pdf_importer.parse_pdf(path)
    assert batch.document_type == 'comdirect Finanzreport'
    assert batch.errors and 'Lösung:' in batch.errors[0]
    assert 'Differenz 1,00 EUR' in batch.errors[0]
    assert batch.pdf_text
    assert not any([batch.transactions, batch.balances, batch.snapshots,
                    batch.documents, batch.account_names, batch.pdf_booking_evidence])

@pytest.mark.parametrize('stamp', ['32.01.2021', ''])
def test_missing_or_invalid_report_date_is_rejected(stamp):
    from pdf_plugins._finanzreport_help import report_date
    with pytest.raises(ValueError, match='Lösung:'):
        report_date('Finanzreport Nr. 1 per ' + stamp)


def test_missing_opening_balance_has_specific_solution():
    pages = [p.replace('Alter Saldo 31.12.2020 +100,00', '') for p in report()]
    with pytest.raises(ValueError, match='Anfangssaldo fehlt.*Vollständige Original-PDF'):
        parsed(pages)


@pytest.mark.parametrize('message,expected', [
    ('Finanzreport: ungültige Konto-IBAN.', 'Kontokopf'),
    ('Alter Finanzreport: Depotbestand in diesem Layout benötigt eine gesonderte Prüfung.', 'CSV/Excel'),
    ('Finanzreport: ungültiger Buchungstag.', 'Valuta'),
    ('Finanzreport: Kontoübersicht und Endsaldo widersprechen sich.', 'zusammengehörige Seiten'),
])
def test_report_solutions_match_the_problem(message, expected):
    from pdf_plugins._finanzreport_help import solution_for
    result = solution_for(message)
    assert result.startswith(message)
    assert 'Lösung:' in result and expected in result
