import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.pdf_bookings import parse_bookings
from portfolio_v5.pdf_importer import analyse_pages


def parse(*pages):
    return parse_bookings(pages, analyse_pages)


def test_soll_haben_year_boundary_and_no_balance_bookings():
    transactions, warnings, evidence = parse('''Konto-Nr.: 12345678
EUR-Konto
Bu-Tag Wert Vorgang
alter Kontostand vom 30.12.2025 100,00 H
31.12. 31.12. Einzahlung 25,00 H
02.01. 02.01. Gebuehr 5,00 S
neuer Kontostand vom 31.01.2026 120,00 H''')
    assert [(t.date, t.amount) for t in transactions] == [('2025-12-31', '25.00'), ('2026-01-02', '-5.00')]
    assert not warnings
    assert evidence[0]['page'] == 1
    assert all(t.kind == 'BANK_BOOKING' for t in transactions)


def test_multiple_accounts_same_page_and_counterparty_does_not_switch():
    transactions, warnings, _ = parse('''Konto-Nr.: 12345678
EUR
Buchungstag Valuta Betrag
01.09.2026 01.09.2026 Transfer +15,00
IBAN: DE89370400440532013000
neuer Kontostand vom 30.09.2026 15,00 H
Konto-Nr.: 87654321
EUR
Buchungstag Valuta Betrag
02.09.2026 02.09.2026 Einkauf -9,00
neuer Kontostand vom 30.09.2026 91,00 H''')
    assert [(t.account, t.amount) for t in transactions] == [('Konto 12345678', '15.00'), ('Konto 87654321', '-9.00')]
    assert not warnings


def test_columns_and_ambiguous_amount():
    header = 'Buchungstag   Erlaeuterungen       Valuta       Belastung       Gutschrift'
    debit = '01.09.2026    Einkauf             01.09.2026    10,00'
    credit = '02.09.2026    Eingang             02.09.2026                    20,00'
    transactions, warnings, _ = parse('Konto: 12345678\nEUR\n' + '\n'.join([header, debit, credit]))
    assert [t.amount for t in transactions] == ['-10.00', '20.00']
    transactions, warnings, _ = parse('Konto: 12345678\nEUR\nBuchungstag Betrag\n01.09.2026 Unklar 10,00')
    assert not transactions
    assert any('Vorzeichen' in warning for warning in warnings)


def test_duplicate_ids_stable_and_genuine_twins_preserved():
    text = 'Konto: 12345678\nEUR\nBuchungstag Betrag\n01.09.2026 Eingang +10,00\n01.09.2026 Eingang +10,00'
    first, _, _ = parse(text)
    second, _, _ = parse(text)
    assert len({t.external_id for t in first}) == 2
    assert [t.external_id for t in first] == [t.external_id for t in second]


@pytest.mark.parametrize('row', ['31.02.2026 Ungueltig +1,00', '01.09. OhneJahr +1,00', '01.09.2026 Unklar -1,00 H'])
def test_invalid_rows_not_imported(row):
    transactions, warnings, _ = parse('Konto: 12345678\nEUR\nBuchungstag Betrag\n' + row)
    assert not transactions
    assert warnings


def test_balance_mismatch_and_unknown_currency():
    text = 'Konto: 12345678\nEUR\nBuchungstag Betrag\nalter Kontostand vom 01.09.2026 100,00 H\n02.09.2026 Eingang +10,00\nneuer Kontostand vom 30.09.2026 120,00 H'
    transactions, warnings, _ = parse(text)
    assert len(transactions) == 1
    assert any('Saldenprüfung' in warning for warning in warnings)
    assert not parse(text.replace('EUR', 'USD'))[0]


def test_ambiguous_account_and_invalid_iban():
    for header in ['Konto: 12345678\nKonto: 87654321', 'IBAN: DE00370400440532013000']:
        transactions, warnings, _ = parse(header + '\nEUR\nBuchungstag Betrag\n01.09.2026 Eingang +10,00')
        assert not transactions
        assert warnings


def test_non_calendar_value_date_preserves_booking_for_review():
    transactions, warnings, _ = parse('Konto: 12345678\nEUR\nBu-Tag Wert Vorgang\n'
        '27.02. 30.02. Abschluss 10,00 H\nneuer Kontostand vom 27.02.2026 10,00 H')
    assert transactions[0].date == '2026-02-27'
    assert transactions[0].value_date == ''
    assert transactions[0].amount == '10.00'
    assert any('30.02.' in warning for warning in warnings)


def test_transfer_word_is_not_mistaken_for_balance():
    transactions, warnings, _ = parse('Konto: 12345678\nEUR\nBuchungstag Betrag\n01.09.2026 Übertrag vom Girokonto +10,00')
    assert len(transactions) == 1
    assert not warnings


def test_unknown_account_on_next_page_does_not_inherit_previous():
    first = 'Konto: 12345678\nEUR\nBuchungstag Betrag\n01.09.2026 Eingang +10,00'
    second = 'EUR\nBuchungstag Betrag\n02.09.2026 Eingang +20,00'
    transactions, warnings, _ = parse(first, second)
    assert len(transactions) == 1
    assert any('Quellkonto' in warning for warning in warnings)


def test_ocr_box_reconstruction():
    from portfolio_v5.pdf_ocr import layout_text
    text, confidence = layout_text(
        [[[0, 0], [90, 0], [90, 20], [0, 20]], [[200, 1], [260, 1], [260, 21], [200, 21]]],
        ['01.09.2026', '+10,00'], [.99, .91])
    assert text.splitlines() == ['01.09.2026          +10,00']
    assert confidence == .91
