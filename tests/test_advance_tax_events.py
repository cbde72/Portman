import importlib.util
from pathlib import Path

import pytest

from portfolio_v5.models import ImportBatch
from portfolio_v5.pdf_plugins import ParseContext, PdfDocument, PdfPage
from portman.repository_v09 import RepositoryV09


ROOT = Path(__file__).resolve().parents[1]


def plugin():
    path = ROOT / 'pdf_plugins' / 'comdirect_ertraege.py'
    spec = importlib.util.spec_from_file_location('advance_tax_regression', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


def notice(*, used='70,00', after='0,00', kapst='0,00', soli='0,00', kist='0,00', paid='0,00',
           reference='ANONYMIZED2025'):
    payment = ('' if paid == '0,00' else
               '\nDie Belastung erfolgt mit Valuta 05.01.2026 auf Konto EUR mit der IBAN '
               'DE11 1111 1111 1111 1111 11')
    text = f'''comdirect bank AG
Datum: 19.01.2026
Referenz-Nummer: {reference}
Depotnummer: 123456789 00
Steuerliche Behandlung: Vorabpauschale Ausland vom 02.01.2026
Stk. 234,356 Muster ETF, WKN / ISIN: A111X9 / IE00BKM4GZ66
Steuerbemessungsgrundlage vor Verlustverrechnung EUR 70,00
in Anspruch genommener Freistellungsauftrag EUR {used}
Steuerbemessungsgrundlage nach Verlustverrechnung EUR {after}
Kapitalertragsteuer EUR {kapst}
Solidaritätszuschlag EUR {soli}
Kirchensteuer EUR {kist}
abgeführte Steuern EUR {paid}
Vorabpauschale EUR 100,00
Teilfreistellung (30%) EUR -30,00
Zu Ihren Lasten nach Steuern: EUR -{paid}{payment}
'''
    balances = '''Verrechnungssalden in EUR
Gewinne / Verluste aus Aktien sonstige Gewinne / Verluste anrechenbare ausländische Quellensteuer verfügbarer Freistellungsauftrag
2026
0,00
0,00
14,64
110,99
0,00
0,00
396,36
300,01
Hinweise zur Ermittlung der Steuerbemessungsgrundlage
'''
    return PdfDocument(Path('anonymous-tax.pdf'), b'%PDF-anonymous', 'anonymous-tax',
                       (PdfPage(1, text), PdfPage(2, balances)))


def parse(source, file_hash='anonymous-tax'):
    importer = plugin()
    detected = importer.detect(source)[0]
    return importer.parse(source, detected, ParseContext(
        ImportBatch(str(source.path), file_hash, source_sheet='PDF')))


def test_fully_exempt_advance_tax_is_a_cash_neutral_tax_event():
    batch = parse(notice())
    event = batch.tax_events[0]
    assert batch.transactions == []
    assert (event.date, event.income_year, event.document_date, event.tax_year) == (
        '2026-01-02', '2025', '2026-01-19', '2026')
    assert (event.advance_tax_base, event.partial_exemption_amount, event.taxable_income) == (
        '100.00', '30.00', '70.00')
    assert (event.used_exemption, event.loss_offset, event.paid_taxes) == ('70.00', '0.00', '0.00')
    assert (event.other_loss_pot_before, event.other_loss_pot_after,
            event.allowance_before, event.allowance_after) == ('14.64', '110.99', '396.36', '300.01')


def test_partly_exempt_advance_tax_links_the_real_tax_payment():
    batch = parse(notice(used='40,00', after='30,00', kapst='7,50', soli='0,41', paid='7,91'))
    event, payment = batch.tax_events[0], batch.transactions[0]
    assert (event.used_exemption, event.paid_taxes, event.related_transaction_id) == (
        '40.00', '7.91', payment.external_id)
    assert (payment.account, payment.amount, payment.kind, payment.affects_cash) == (
        'IBAN DE11111111111111111111', '-7.91', 'TAX', True)
    assert payment.depot_account == event.account == 'Depot 12345678900'


def test_taxed_advance_tax_keeps_tax_components_separate():
    batch = parse(notice(used='0,00', after='70,00', kapst='17,50', soli='0,96', paid='18,46'))
    event = batch.tax_events[0]
    assert (event.capital_gains_tax, event.solidarity_surcharge, event.church_tax,
            event.paid_taxes) == ('17.50', '0.96', '0.00', '18.46')
    assert [(item.kind, item.amount) for item in batch.transactions[0].tax_items] == [
        ('kapitalertragsteuer', '17.50'), ('solidaritaetszuschlag', '0.96'), ('kirchensteuer', '0.00')]


def test_tax_event_is_visible_in_depot_bookings_without_changing_holdings_or_cash(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 12345678900', {'kind': 'Depot', 'institution': 'comdirect'})
        batch = parse(notice())
        batch.documents = []
        assert repo.commit_batches([batch])[0]['status'] == 'imported'
        assert repo.transactions() == []
        assert repo.holdings() == []
        rows = repo.tax_event_bookings('Depot 12345678900')
        assert len(rows) == 1
        assert (rows[0]['kind'], rows[0]['amount'], rows[0]['affects_cash']) == (
            'VORABPAUSCHALE', '0.00', False)
        assert 'Ertragsjahr 2025' in rows[0]['purpose']
        assert repo.advance_tax_credit('Depot 12345678900', 'IE00BKM4GZ66') == 70
    finally:
        repo.close()


def test_depot_bookings_dialog_shows_advance_tax_event(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portman.account_bookings_dialog import AccountBookingsDialog

    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 12345678900', {'kind': 'Depot', 'institution': 'comdirect'})
        batch = parse(notice()); batch.documents = []
        repo.commit_batches([batch])
        dialog = AccountBookingsDialog(repo, 'Depot 12345678900')
        assert dialog.model.rowCount() == 1
        assert dialog.model.item(0, 2).text() == 'VORABPAUSCHALE · nur Depot'
        assert 'Ertragsjahr 2025' in dialog.model.item(0, 7).text()
        dialog.close()
    finally:
        repo.close()


def test_depot_bookings_classifies_each_tax_event_by_its_actual_type(tmp_path):
    from PySide6.QtWidgets import QApplication
    from portfolio_v5.models import ImportBatch, TaxEvent
    from portman.account_bookings_dialog import AccountBookingsDialog

    QApplication.instance() or QApplication([])
    depot = 'Depot 4764924'
    events = [
        TaxEvent(f'advance-{index}', depot, 'vorabpauschale_ausland', '2026-01-02',
                 income_year='2025', security_ref=security, advance_tax_base='10.00',
                 taxable_income='7.00', paid_taxes='0.00')
        for index, security in enumerate(('IE00BKM4GZ66', 'IE00B48X4842', 'LU1681041973'), 1)
    ] + [
        TaxEvent('sap', depot, 'dividende_inland', '2026-05-08',
                 security_ref='DE0007164600', taxable_income='4.49',
                 partial_exemption_amount='0.00', paid_taxes='0.00'),
        TaxEvent('fresenius', depot, 'dividende_inland', '2026-05-26',
                 security_ref='DE0005785604', taxable_income='4.07',
                 partial_exemption_amount='0.00', paid_taxes='0.00'),
        TaxEvent('etf-inland', depot, 'investment_ausschuettung_inland', '2026-09-15',
                 security_ref='DE000A0H0744', taxable_income='6.37',
                 partial_exemption_amount='2.73', paid_taxes='1.67'),
        TaxEvent('etf-foreign', depot, 'investment_ausschuettung_ausland', '2026-09-18',
                 security_ref='IE00B1FZS350', taxable_income='20.00',
                 partial_exemption_amount='8.00', paid_taxes='6.38'),
    ]
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account(depot, {'kind': 'Depot', 'institution': 'comdirect'})
        repo.commit_batches([ImportBatch('tax-events.pdf', 'tax-event-types', tax_events=events)])
        before = (repo.transactions(), repo.holdings())

        rows = repo.tax_event_bookings(depot)
        assert [row['kind'] for row in rows].count('VORABPAUSCHALE') == 3
        assert [row['kind'] for row in rows].count('DIVIDEND') == 2
        assert [row['kind'] for row in rows].count('DISTRIBUTION') == 2
        assert all('Vorabpauschale' not in row['purpose']
                   for row in rows if row['kind'] != 'VORABPAUSCHALE')
        assert next(row for row in rows if row['external_id'] == 'sap')['purpose'].startswith(
            'Dividende Inland')
        assert next(row for row in rows if row['external_id'] == 'etf-inland')['purpose'].startswith(
            'Investment-Ausschüttung Inland')

        dialog = AccountBookingsDialog(repo, depot)
        shown = [dialog.model.item(row, 2).text() for row in range(dialog.model.rowCount())]
        assert shown.count('VORABPAUSCHALE · nur Depot') == 3
        assert shown.count('DIVIDEND · nur Depot') == 2
        assert shown.count('DISTRIBUTION · nur Depot') == 2
        dialog.close()

        tax_kinds = {row['linked_tax_event_id']: row['original_values']['Vorgang']
                     for row in repo.tax_detail_records()}
        assert tax_kinds['sap'] == 'Dividende Inland'
        assert tax_kinds['etf-inland'] == 'Investment-Ausschüttung Inland'
        assert (repo.transactions(), repo.holdings()) == before == ([], [])
    finally:
        repo.close()


def test_duplicate_advance_tax_is_not_counted_twice(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 12345678900', {'kind': 'Depot', 'institution': 'comdirect'})
        first, duplicate = parse(notice(), 'first'), parse(notice(), 'second')
        first.documents = duplicate.documents = []
        assert repo.commit_batches([first])[0]['status'] == 'imported'
        assert repo.commit_batches([duplicate])[0]['status'] == 'imported'
        assert len(repo.tax_events('Depot 12345678900', income_year=2025)) == 1
    finally:
        repo.close()


def test_conflicting_advance_tax_for_same_depot_is_rejected(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 12345678900', {'kind': 'Depot', 'institution': 'comdirect'})
        first = parse(notice(), 'first'); first.documents = []
        conflict = parse(notice(used='69,00', reference='ANONYMIZED-CORRECTION'), 'conflict')
        conflict.documents = []
        repo.commit_batches([first])
        with pytest.raises(ValueError, match='Ertragsjahr 2025 bereits'):
            repo.store.import_batch(conflict)
    finally:
        repo.close()


def test_same_advance_tax_with_new_source_identity_is_idempotent(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 12345678900', {'kind': 'Depot', 'institution': 'comdirect'})
        first = parse(notice(reference='ANONYMIZED-ORIGINAL'), 'first')
        repeated = parse(notice(reference='ANONYMIZED-REDOWNLOAD'), 'second')
        first.documents = repeated.documents = []
        assert repo.commit_batches([first])[0]['status'] == 'imported'
        assert repo.commit_batches([repeated])[0]['status'] == 'imported'
        events = repo.tax_events('Depot 12345678900', income_year=2025)
        assert len(events) == 1
        assert events[0]['taxable_income'] == '70.00'
    finally:
        repo.close()


def test_comdirect_tax_subaccount_is_suggested_only_for_unique_depot(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot', 'institution': 'comdirect'})
        repo.save_account('Giro 476492400', {'kind': 'Girokonto', 'number': '0476492400'})
        batch = parse(notice())
        batch.account_names = ['Depot 476492400']
        batch.tax_events[0].account = 'Depot 476492400'
        batch.documents[0].account = 'Depot 476492400'
        batch.pdf_text = 'comdirect bank AG'
        suggestion = repo.import_account_suggestions(batch)[0]
        assert suggestion['target_key'] == 'depot 4764924'
        assert suggestion['required_kind'] == 'Depot'
        assert 'Unterkontokennung' in suggestion['reason']
    finally:
        repo.close()


def test_import_preview_shows_detected_and_assigned_tax_depot(tmp_path, qapp):
    from portman.import_preview import ImportPreviewDialog
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot'})
        batch = parse(notice())
        batch.account_names = ['Depot 476492400']
        batch.tax_events[0].account = 'Depot 476492400'
        batch.documents[0].account = 'Depot 476492400'
        batch.pdf_text = 'comdirect bank AG'
        dialog = ImportPreviewDialog(repo, [batch])
        source, combo = dialog.mapping_rows[0][1], dialog.mapping_rows[0][2]
        assert source['name'] == 'Depot 476492400'
        assert combo.currentText().startswith('Depot 4764924')
        selected = dialog.selected_batches()[0]
        assert selected.account_assignments == {'depot 476492400': 'depot 4764924'}
        dialog.close()
    finally:
        repo.close()


def test_tax_event_cannot_be_assigned_to_cash_account(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot'})
        repo.save_account('Giro 476492400', {'kind': 'Girokonto', 'number': '0476492400'})
        batch = parse(notice())
        batch.documents = []
        batch.account_assignments = {'depot 12345678900': 'giro 476492400'}
        with pytest.raises(ValueError, match='nur einem aktiven Depot'):
            repo.store.import_batch(batch)
    finally:
        repo.close()


def test_legacy_wrong_tax_assignment_has_safe_repair_preview(tmp_path):
    repo = RepositoryV09(tmp_path / 'portfolio.sqlite', backups=False)
    try:
        repo.save_account('Depot 4764924', {'kind': 'Depot'})
        repo.save_account('Giro 476492400', {'kind': 'Girokonto', 'number': '0476492400'})
        batch = parse(notice())
        batch.path = 'comdirect-tax.pdf'
        batch.documents = []
        batch.account_assignments = {'depot 12345678900': 'depot 4764924'}
        iid = repo.commit_batches([batch])[0]['id']
        with repo.db:
            repo.db.execute('UPDATE import_account_links SET account_key=? WHERE import_id=?',
                            ('giro 476492400', iid))
        issue = repo.tax_assignment_issues()[0]
        assert issue['target_name'] == 'Giro 476492400'
        assert issue['suggested_target_key'] is None  # source number is unrelated; never guess
        repo.reassign_imports([{'import_id': iid, 'source_key': issue['source_key'],
                                'target_key': 'depot 4764924'}])
        assert repo.tax_assignment_issues() == []
        assert repo.transactions() == [] and repo.holdings() == []
    finally:
        repo.close()
