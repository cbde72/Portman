from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from portman_parsers.api import AccountType, PdfDocument, PdfPage
from portman_parsers.plugins import BankOfScotlandPlugin
from portman_parsers.plugins.bank_of_scotland import BankOfScotlandParseError


TEXT = (Path(__file__).parents[1] / "fixtures" / "bank_of_scotland" /
        "tagesgeld_statement.txt").read_text(encoding="utf-8")


def document(text=TEXT, pages=None):
    pages = pages or (PdfPage(1, text, "synthetic#1"),)
    return PdfDocument("doc-bos", "synthetic-hash", pages, "synthetic.pdf")


def parse(text=TEXT, pages=None):
    plugin = BankOfScotlandPlugin(); doc = document(text, pages)
    detection = plugin.detect(doc)[0]
    return plugin.parse(doc, detection)


def test_tagesgeld_statement_end_to_end():
    result = parse()
    assert result.accounts[0].account_type.value == AccountType.TAGESGELD
    assert result.accounts[0].holder_name.value == "Erika Mustermann"
    assert [item.amount.value for item in result.account_balances] == [Decimal("1000.00"), Decimal("907.36")]
    assert sum((item.cash_movements[0].amount for item in result.events), Decimal()) == Decimal("-92.64")
    assert not result.issues


def test_interest_and_tax_components_are_separate_economic_events():
    result = parse()
    assert [item.kind for item in result.events] == ["TRANSFER", "INTEREST_CREDIT", "TAX_DEBIT", "TAX_DEBIT"]
    assert result.events[1].cash_movements[0].amount == Decimal("10.00")
    assert {item.tax_events[0].kind for item in result.events[2:]} == {
        "capital_gains_tax", "solidarity_surcharge"}


def test_fee_debit_and_refund_are_modeled():
    text = TEXT.replace(
        "31.12.2026 31.12.2026 Solidaritätszuschlag 0,14",
        "30.12.2026 30.12.2026 Bankentgelt 1,00\n31.12.2026 31.12.2026 Gebührenerstattung 1,00\n31.12.2026 31.12.2026 Solidaritätszuschlag 0,14")
    result = parse(text)
    fees = [fee for event in result.events for fee in event.fee_events]
    assert [item.effect.value for item in fees] == ["ACTUAL_BOOKED", "REFUND"]


def test_festgeld_is_supported_when_explicitly_printed():
    result = parse(TEXT.replace("Tagesgeld", "Festgeld"))
    assert result.accounts[0].account_type.value == AccountType.FESTGELD


def test_balance_difference_is_reported_without_correction_booking():
    result = parse(TEXT.replace("Neuer Saldo: 907,36", "Neuer Saldo: 908,36"))
    assert {item.code for item in result.issues} == {"BALANCE_MISMATCH"}
    assert len(result.events) == 4


def test_missing_account_data_is_rejected():
    text = "\n".join(line for line in TEXT.splitlines()
                     if not line.startswith(("Kontonummer:", "IBAN:")))
    with pytest.raises(BankOfScotlandParseError, match="Kontonummer"):
        parse(text)


def test_unknown_layout_is_not_detected():
    assert BankOfScotlandPlugin().detect(document("Bank of Scotland unknown")) == ()


def test_mult_page_statement_preserves_page_evidence():
    lines = TEXT.splitlines(); split = next(i for i, line in enumerate(lines) if line.startswith("31.12.2026"))
    header = "Buchungstag Wertstellung Beschreibung Soll Haben"
    pages = (PdfPage(1, "\n".join(lines[:split]), "p1"),
             PdfPage(2, header + "\n" + "\n".join(lines[split:]), "p2"))
    result = parse(pages=pages)
    assert {item.page_number for item in result.evidence if item.field == "booking"} == {1, 2}


def test_reimport_is_deterministic():
    assert parse().to_json() == parse().to_json()
