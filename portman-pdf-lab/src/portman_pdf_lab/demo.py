"""Synthetic end-to-end demonstration without bank or personal data."""

from datetime import date
from decimal import Decimal

from portman_parsers.api import (
    Account,
    AccountBalance,
    AccountFunction,
    AccountType,
    CashMovement,
    CashStatus,
    CostEvent,
    Depot,
    DepotAccountLink,
    DepotPosition,
    DepotSnapshot,
    Evidence,
    FeeAllocation,
    FeeEffect,
    FeeEvent,
    FieldValue,
    FinancialEvent,
    ParsedDocument,
    ReviewStatus,
    AllocationStatus,
    SecurityMovement,
    TaxComponent,
    TaxEvent,
)

from .application import AnalysisService
from .analysis import account_view, depot_account_link_view, depot_view, fee_cost_view, quality_summary


def synthetic_purchase() -> ParsedDocument:
    evidence = Evidence("ev-price", "doc-demo", 1, "settlement", "Zu Ihren Lasten EUR 103.00")
    depot_evidence = Evidence("ev-depot", "doc-demo", 1, "depot_number", "Depot 4711")
    account_evidence = Evidence("ev-account", "doc-demo", 1, "iban", "DE00000000000000000001")
    balance_evidence = Evidence("ev-balance", "doc-demo", 2, "balance", "Saldo EUR 1000.00")
    position_evidence = Evidence("ev-position", "doc-demo", 2, "position", "1 Stück EUR 100.00")
    link_evidence = Evidence("ev-link", "doc-demo", 1, "settlement_account", "Verrechnungskonto")
    fee_evidence = Evidence("ev-fee", "doc-demo", 1, "fee", "Provision EUR 2.00")
    verified = ReviewStatus.VERIFIED
    depot = Depot(
        "depot-demo",
        bank_name=FieldValue.from_pdf("Synthetic Bank", 1, "ev-depot", review_status=verified),
        depot_name=FieldValue.manual("Demo Depot"),
        depot_number=FieldValue.from_pdf("4711", 1, "ev-depot", review_status=verified),
        base_currency=FieldValue.from_pdf("EUR", 1, "ev-depot"),
    )
    cash_account = Account(
        "account-demo",
        bank_name=FieldValue.from_pdf("Synthetic Bank", 1, "ev-account", review_status=verified),
        account_name=FieldValue.manual("Primäres Verrechnungskonto"),
        account_type=FieldValue.from_pdf(AccountType.GIRO, 1, "ev-link"),
        iban=FieldValue.from_pdf("DE00000000000000000001", 1, "ev-account", review_status=verified),
        currency=FieldValue.from_pdf("EUR", 1, "ev-account"),
        functions=(FieldValue.manual(AccountFunction.PAYMENT), FieldValue.manual(AccountFunction.SETTLEMENT)),
    )
    tax_account = Account(
        "account-tax-demo",
        bank_name=FieldValue.from_pdf("Synthetic Bank", 1, "ev-account"),
        account_name=FieldValue.manual("Steuer-Verrechnungskonto"),
        account_type=FieldValue.from_pdf(AccountType.OTHER, 1, "ev-link"),
        iban=FieldValue.unknown(),
        currency=FieldValue.from_pdf("EUR", 1, "ev-account"),
        functions=(FieldValue.manual(AccountFunction.TAX),),
    )
    links = (
        DepotAccountLink("link-primary", depot.depot_id, cash_account.account_id,
                         FieldValue.from_pdf("PRIMARY_SETTLEMENT", 1, "ev-link", review_status=verified)),
        DepotAccountLink("link-tax", depot.depot_id, tax_account.account_id,
                         FieldValue.from_pdf("TAX_SETTLEMENT", 1, "ev-link")),
    )
    balance = AccountBalance(
        "balance-demo", cash_account.account_id,
        FieldValue.from_pdf(date(2026, 10, 30), 2, "ev-balance"),
        FieldValue.from_pdf(Decimal("1000.00"), 2, "ev-balance", review_status=verified),
        FieldValue.from_pdf("EUR", 2, "ev-balance"),
    )
    snapshot = DepotSnapshot(
        "snapshot-demo", depot.depot_id,
        FieldValue.from_pdf(date(2026, 10, 30), 2, "ev-position"),
        (DepotPosition(
            "position-demo",
            FieldValue.from_pdf("DE0000000001", 2, "ev-position"),
            FieldValue.from_pdf(Decimal("1"), 2, "ev-position"),
            market_value=FieldValue.from_pdf(Decimal("100.00"), 2, "ev-position"),
            currency=FieldValue.from_pdf("EUR", 2, "ev-position"),
        ),),
        FieldValue.from_pdf(Decimal("100.00"), 2, "ev-position"),
        FieldValue.from_pdf("EUR", 2, "ev-position"),
    )
    cash = CashMovement("cash-demo", "event-demo", Decimal("-103.00"), "EUR",
                        CashStatus.ACTUAL, "synthetic-account", (evidence.evidence_id,),
                        account_id=cash_account.account_id,
                        linked_security_movement_id="security-demo")
    security = SecurityMovement("security-demo", "event-demo", "DE0000000001",
                                Decimal("1"), (evidence.evidence_id,), depot_id=depot.depot_id,
                                linked_cash_movement_id=cash.movement_id)
    cost = CostEvent("cost-demo", "event-demo", "fee", Decimal("2.00"), "EUR",
                     cash_movement_id=cash.movement_id, evidence_ids=(evidence.evidence_id,))
    tax = TaxEvent("tax-demo", "event-demo", "transaction_tax",
                   (TaxComponent("transaction_tax", Decimal("1.00"), "EUR"),),
                   cash_movement_id=cash.movement_id, evidence_ids=(evidence.evidence_id,))
    fee = FeeEvent(
        "fee-demo", "trading", "commission", Decimal("2.00"), "EUR", date(2026, 10, 30),
        FeeEffect.INCLUDED_IN_SETTLEMENT, "doc-demo", "synthetic-bank", depot.depot_id,
        cash_account.account_id, "DE0000000001", "event-demo", cash.movement_id,
        "synthetic-order-1", allocations=(
            FeeAllocation("DEPOT", depot.depot_id, AllocationStatus.VERIFIED, (fee_evidence.evidence_id,)),
            FeeAllocation("ACCOUNT", cash_account.account_id, AllocationStatus.VERIFIED,
                          (fee_evidence.evidence_id,)),
        ), evidence_ids=(fee_evidence.evidence_id,))
    event = FinancialEvent("event-demo", "doc-demo", "BUY", date(2026, 10, 30),
                           (cash,), (security,), (tax,), (cost,), evidence_ids=(evidence.evidence_id,),
                           fee_events=(fee,))
    return ParsedDocument("result-demo", "doc-demo", "demo.synthetic", "0.1", "purchase",
                          events=(event,), evidence=(evidence, depot_evidence, account_evidence,
                                                    balance_evidence, position_evidence, link_evidence,
                                                    fee_evidence),
                          depots=(depot,), accounts=(cash_account, tax_account),
                          depot_snapshots=(snapshot,), account_balances=(balance,),
                          depot_account_links=links)


def run_demo() -> dict[str, object]:
    report = AnalysisService().analyse(synthetic_purchase())
    return {
        "analysis": report.to_dict(),
        "quality": quality_summary(report),
        "depot_view": depot_view(report.result),
        "account_view": account_view(report.result),
        "depot_account_link_view": depot_account_link_view(report.result),
        "fee_cost_view": fee_cost_view(report.result),
    }

    Depot,
    DepotAccountLink,
    DepotPosition,
    DepotSnapshot,
    FieldValue,
    ReviewStatus,
