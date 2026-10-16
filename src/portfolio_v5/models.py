from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
import hashlib
import json
import re
import unicodedata


def text(value):
    return '' if value is None else str(value).strip()


def norm(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', text(value).lower()).encode('ascii', 'ignore').decode())


def plain_number(value):
    """Return a finite Decimal without exponent notation."""
    return format(Decimal(str(value)), 'f')


def number(value):
    """Excel numeric values are numeric; text exports use German number notation."""
    if value is None or text(value) in ('', '-', '--'):
        return None
    if isinstance(value, (float, int, Decimal)):
        result = Decimal(str(value))
    else:
        raw = text(value).replace('\u00a0', '').replace(' ', '').replace('−', '-')
        raw = re.sub(r'(EUR|€|Stück|Stueck|%)', '', raw, flags=re.I)
        if ',' in raw:
            raw = raw.replace('.', '').replace(',', '.')
        elif re.fullmatch(r'[+-]?\d{1,3}(\.\d{3})+', raw):
            raw = raw.replace('.', '')
        try:
            result = Decimal(raw)
        except InvalidOperation:
            raise ValueError(f'Ungültige Zahl: {value!r}')
    if not result.is_finite():
        raise ValueError(f'Nicht endliche Zahl: {value!r}')
    return plain_number(result.normalize())


def money(value):
    parsed = number(value)
    return None if parsed is None else str(Decimal(parsed).quantize(Decimal('.01')))


def correction_number(value):
    """Editor/internal decimal strings: a dot is never a grouping heuristic."""
    if value is None or str(value).strip() == '':
        return None
    raw = str(value).strip().replace(' ', '').replace('\u00a0', '')
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        raise ValueError('Ungültige Zahl. Beispiel: 6,847 (ohne Tausendertrennzeichen).') from None
    if not parsed.is_finite():
        raise ValueError('Bitte eine endliche Zahl eingeben.')
    return plain_number(parsed)


def parse_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = text(value)
    for pattern, fmt in [(r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'), (r'\d{2}\.\d{2}\.\d{4}', '%d.%m.%Y')]:
        match = re.search(pattern, raw)
        if match:
            try:
                return datetime.strptime(match.group(), fmt).date().isoformat()
            except ValueError:
                pass
    return None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


class Kind:
    BANK_BOOKING = 'BANK_BOOKING'
    DIVIDEND = 'DIVIDEND'
    DISTRIBUTION = 'DISTRIBUTION'
    BUY = 'BUY'
    SELL = 'SELL'
    REDEMPTION = 'REDEMPTION'
    INTEREST = 'INTEREST'
    TAX = 'TAX'
    TAX_REFUND = 'TAX_REFUND'
    ADVANCE_LUMP_SUM = 'ADVANCE_LUMP_SUM'
    TRANSFER = 'TRANSFER'
    TRANSFER_IN = 'TRANSFER_IN'
    TRANSFER_OUT = 'TRANSFER_OUT'
    DEPOSIT = 'DEPOSIT'
    WITHDRAWAL = 'WITHDRAWAL'
    FEE = 'FEE'
    REVERSAL = 'REVERSAL'
    SPLIT = 'SPLIT'


INCOME_KINDS = {Kind.DIVIDEND, Kind.DISTRIBUTION, Kind.REDEMPTION, Kind.INTEREST}
OUTFLOW_KINDS = {Kind.BUY}
TRANSACTION_KINDS = {value for name, value in vars(Kind).items() if not name.startswith('_')}
REVIEW_STATES = ('offen', 'geprueft', 'verworfen')


@dataclass
class TaxItem:
    kind: str
    amount: str
    rate: str | None = None
    original_amount: str | None = None
    original_currency: str | None = None
    country: str | None = None


@dataclass
class FeeItem:
    kind: str
    amount: str


@dataclass
class SecurityInfo:
    key: str
    identifier_type: str = 'isin'
    isin: str = ''
    wkn: str = ''
    symbol: str = ''
    name: str = ''
    name_aliases: list[str] = field(default_factory=list)
    asset_class: str = 'Sonstiges'
    distribution: str = ''
    domicile: str = ''
    quote_currency: str = ''
    custody_type: str = ''
    custody_country: str = ''
    custodian: str = ''


@dataclass
class AccountInfo:
    key: str
    account_type: str = ''
    bank_name: str = ''
    iban: str = ''
    bic: str = ''
    bank_code: str = ''
    account_no: str = ''
    customer_no: str = ''
    currency: str = 'EUR'
    owners: list[str] = field(default_factory=list)
    linked_account: str = ''


@dataclass
class AccountStatement:
    account: str
    statement_no: str = ''
    period_start: str = ''
    period_end: str = ''
    opening_balance: str | None = None
    opening_date: str = ''
    closing_balance: str | None = None
    closing_date: str = ''
    currency: str = 'EUR'
    closed: bool = False
    external_id: str = ''


@dataclass
class TaxEvent:
    external_id: str
    account: str
    type: str
    date: str
    tax_year: str = ''
    security_ref: str = ''
    quantity: str | None = None
    currency: str = 'EUR'
    taxable_income: str | None = None
    advance_tax_base: str | None = None
    partial_exemption_amount: str | None = None
    used_exemption: str | None = None
    allowance_before: str | None = None
    allowance_after: str | None = None
    withholding_pot_before: str | None = None
    withholding_pot_after: str | None = None
    creditable_withholding: str | None = None
    per_unit: str | None = None
    after_partial_exemption: str | None = None
    partial_exemption_rate: str | None = None
    refund_kapst: str | None = None
    refund_solz: str | None = None
    refund_kist: str | None = None
    reference_no: str = ''
    related_transaction_id: str = ''


@dataclass
class CostItem:
    security_ref: str
    service_costs: str | None = None
    inducements: str | None = None
    product_costs: str | None = None
    fx_costs: str | None = None
    total: str | None = None


@dataclass
class CostReport:
    external_id: str
    account: str
    period_start: str
    period_end: str
    currency: str = 'EUR'
    items: list[CostItem] = field(default_factory=list)
    overhead_costs: str | None = None
    total_costs: str | None = None
    ongoing_pct: str | None = None
    entry_exit_pct: str | None = None
    avg_capital: str | None = None
    turnover_volume: str | None = None


@dataclass
class CorporateEvent:
    external_id: str
    account: str
    type: str
    security_ref: str = ''
    event_date: str = ''
    record_date: str = ''
    registration_deadline: str = ''
    location: str = ''
    eligible_quantity: str | None = None


@dataclass
class Position:
    key: str
    name: str
    isin: str = ''
    wkn: str = ''
    asset_type: str = 'Sonstiges'
    quantity: str | None = None
    cost: str | None = None
    value: str | None = None
    currency: str = 'EUR'
    quote_date: str | None = None
    row: int = 0
    security_ref: str = ''
    price: str | None = None
    price_currency: str = ''
    price_basis: str = ''
    sub_account: str = ''
    owner: str = ''
    restriction: str = ''
    restriction_until: str = ''
    cost_per_unit: str | None = None
    acquisition_date: str = ''
    performance_amount: str | None = None
    performance_since: str = ''
    custody_type: str = ''
    custody_country: str = ''


@dataclass
class Snapshot:
    account: str
    period: str
    as_of: str | None
    sheet: str
    positions: list[Position] = field(default_factory=list)
    complete: bool = True
    date_basis: str = 'document'
    warnings: list[str] = field(default_factory=list)
    reported_total_value: str | None = None
    reported_position_count: int | None = None
    statement_type: str = ''
    statement_no: str = ''

    @property
    def effective_date(self):
        # Unknown day sorts at the start of its month; precision remains explicit.
        return self.as_of or self.period + '-01'


@dataclass
class Balance:
    period: str
    category: str
    account: str
    value: str
    sheet: str
    row: int
    priority: int = 20


@dataclass
class Transaction:
    account: str
    external_id: str
    date: str
    kind: str
    amount: str
    currency: str
    security: str = ''
    quantity: str | None = None
    fees: str | None = None
    taxes: str | None = None
    row: int = 0
    gross_amount: str | None = None
    original_amount: str | None = None
    original_currency: str = ''
    fx_rate: str | None = None
    tax_items: list[TaxItem] = field(default_factory=list)
    fee_items: list[FeeItem] = field(default_factory=list)
    price: str | None = None
    price_currency: str = ''
    per_share_amount: str | None = None
    per_share_currency: str = ''
    trade_date: str = ''
    pay_date: str = ''
    ex_date: str = ''
    executed_at: str = ''
    fiscal_period_start: str = ''
    fiscal_period_end: str = ''
    cash_account: str = ''
    depot_account: str = ''
    security_ref: str = ''
    group_id: str = ''
    related_ids: list[str] = field(default_factory=list)
    is_reversal: bool = False
    reverses_external_id: str = ''
    order_id: str = ''
    execution_ref: str = ''
    venue: str = ''
    order_subtype: str = ''
    document_reference: str = ''
    field_sources: dict[str, str] = field(default_factory=dict)
    review_state: str = 'offen'
    # Appended to preserve the positional constructor contract of older importers.
    solidarity_tax: str | None = None
    withholding_tax: str | None = None
    withholding_country: str = ''
    withholding_tax_rate: str | None = None
    tax_rate: str | None = None
    transaction_reference: str = ''
    # Tax basis documented by the bank. This is not the debited tax amount.
    advance_tax_base: str | None = None
    advance_tax_currency: str = ''

    def __post_init__(self):
        if self.tax_items and self.taxes is None:
            self.taxes = money(sum((Decimal(item.amount) for item in self.tax_items), Decimal(0)))
        if self.solidarity_tax is None:
            solidarity = [item.amount for item in self.tax_items
                          if norm(item.kind) in ('solidaritaetszuschlag', 'solidaritytax', 'solz', 'soli')]
            if solidarity:
                self.solidarity_tax = money(sum((Decimal(value) for value in solidarity), Decimal(0)))
        if self.fee_items and self.fees is None:
            self.fees = money(sum((Decimal(item.amount) for item in self.fee_items), Decimal(0)))
        enrich_tax_details(self)
        enrich_advance_tax_details(self)


@dataclass
class BankTransaction(Transaction):
    """Unclassified booked cash movement; never inferred to be a security trade."""
    value_date: str = ''
    purpose: str = ''
    counterparty: str = ''
    bank_reference: str = ''
    operation: str = ''
    booking_text: str = ''
    counterparty_iban: str = ''
    counterparty_bic: str = ''
    raw_text: str = ''
    affects_cash: bool = True
    performance_depot_key: str = ''
    gross_income: str | None = None
    gross_currency: str = ''
    income_basis: str = 'net'


def enrich_tax_details(tx):
    """Promote source-tax metadata to stable booking fields without guessing amounts."""
    withholding = [item for item in tx.tax_items
                   if norm(item.kind) in ('quellensteuer', 'withholdingtax', 'auslaendischequellensteuer')]
    if tx.withholding_tax is None and withholding:
        tx.withholding_tax = money(sum((Decimal(item.amount) for item in withholding), Decimal(0)))
    if tx.withholding_tax_rate is None:
        rates = [item.rate for item in withholding if item.rate not in (None, '')]
        if len(set(rates)) == 1:
            tx.withholding_tax_rate = correction_number(rates[0])
            tx.field_sources['withholding_tax_rate'] = 'Steuersatz im Beleg'
        elif tx.withholding_tax is not None:
            gross = tx.gross_amount
            if gross not in (None, '') and Decimal(gross) > 0:
                tx.withholding_tax_rate = money(Decimal(tx.withholding_tax) * Decimal(100) / Decimal(gross))
                tx.field_sources['withholding_tax_rate'] = 'Berechnet: Quellensteuer ÷ Bruttobetrag × 100'
    if not tx.withholding_country:
        countries = [item.country.strip().upper() for item in withholding if item.country]
        if len(set(countries)) == 1:
            tx.withholding_country = countries[0]
            tx.field_sources['withholding_country'] = 'Quellenstaat im Beleg'
    if tx.tax_rate is None and tx.taxes is not None:
        gross = tx.gross_amount
        if gross in (None, '') and hasattr(tx, 'gross_income') and tx.gross_currency == tx.currency:
            gross = tx.gross_income
        if gross not in (None, '') and Decimal(gross) > 0:
            tx.tax_rate = money(Decimal(tx.taxes) * Decimal(100) / Decimal(gross))
            tx.field_sources['tax_rate'] = 'Berechnet: Steuern gesamt ÷ Bruttobetrag × 100'
    if not tx.transaction_reference:
        tx.transaction_reference = getattr(tx, 'bank_reference', '') or tx.document_reference


def enrich_advance_tax_details(tx):
    """Extract an explicitly labelled Vorabpauschale without treating it as tax paid."""
    if tx.advance_tax_base is not None:
        tx.advance_tax_base = money(tx.advance_tax_base)
        tx.advance_tax_currency = (tx.advance_tax_currency or tx.currency).upper()
        return
    text = ' '.join(str(getattr(tx, field, '') or '') for field in
                    ('purpose', 'booking_text', 'operation', 'raw_text'))
    amount = r'(?P<amount>\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})'
    currency = r'(?P<currency>EUR|USD|GBP|CHF)'
    patterns = (
        re.compile(r'Vorabpauschale\b.{0,80}?' + amount + r'\s*' + currency, re.I),
        re.compile(currency + r'\s*' + amount + r'.{0,80}?\bVorabpauschale\b', re.I),
    )
    match = next((pattern.search(text) for pattern in patterns if pattern.search(text)), None)
    if match:
        tx.advance_tax_base = money(match.group('amount'))
        tx.advance_tax_currency = match.group('currency').upper()
        tx.field_sources['advance_tax_base'] = 'Vorabpauschale im Importbeleg'


@dataclass
class BankDocument:
    account: str
    external_id: str
    title: str
    date: str
    content_b64: str = field(repr=False)
    media_type: str = 'application/pdf'
    document_type: str = ''
    bank_name: str = ''
    document_no: str = ''
    page_count: int | None = None
    extraction_method: str = ''
    linked_ids: list[str] = field(default_factory=list)


def valid_isin(value):
    """Validate the ISO 6166 shape and Luhn check digit for manual corrections."""
    import re
    if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', value): return False
    digits = ''.join(str(ord(c) - 55) if c.isalpha() else c for c in value)
    total = 0
    for index, digit in enumerate(reversed(digits)):
        number = int(digit) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    return total % 10 == 0


def check_transaction(tx):
    """Return convention violations without changing imported data."""
    problems = []
    if tx.kind not in TRANSACTION_KINDS:
        problems.append(f'Unbekannte Buchungsart: {tx.kind!r}')
    for name in ('amount', 'quantity', 'fees', 'taxes', 'solidarity_tax', 'withholding_tax',
                 'withholding_tax_rate', 'tax_rate', 'gross_amount', 'price', 'fx_rate'):
        value = getattr(tx, name, None)
        if value is not None and re.search(r'[eE]', str(value)):
            problems.append(f'{name}: Exponentschreibweise {value!r}')
    for name in ('date', 'trade_date', 'value_date', 'pay_date', 'ex_date'):
        value = getattr(tx, name, '')
        if value:
            try:
                parsed_date = date.fromisoformat(value)
                if parsed_date.isoformat() != value:
                    raise ValueError
            except (TypeError, ValueError):
                problems.append(f'{name}: kein gültiges ISO-Datum {value!r}')
    if tx.review_state not in REVIEW_STATES:
        problems.append(f'Unbekannter Prüfstatus: {tx.review_state!r}')
    values = {}
    for name in ('amount', 'quantity', 'fees', 'taxes', 'solidarity_tax', 'withholding_tax',
                 'withholding_tax_rate', 'tax_rate', 'gross_amount', 'original_amount',
                 'price', 'fx_rate', 'advance_tax_base'):
        value = getattr(tx, name, None)
        if value is None:
            continue
        try:
            parsed = Decimal(value)
            if not parsed.is_finite():
                raise InvalidOperation
            values[name] = parsed
        except (InvalidOperation, TypeError, ValueError):
            problems.append(f'{name}: ungültige oder nicht endliche Dezimalzahl {value!r}')
    try:
        amount = values['amount']
        if tx.kind in OUTFLOW_KINDS and amount > 0:
            problems.append('Kauf mit positivem Betrag (Abfluss muss negativ sein)')
        if tx.kind in INCOME_KINDS and amount < 0 and not tx.is_reversal:
            problems.append('Ertrag mit negativem Betrag (nur bei Storno zulässig)')
        for name in ('fees', 'taxes', 'solidarity_tax'):
            value = values.get(name)
            if value is not None and value < 0 and not (tx.is_reversal or tx.kind == Kind.TAX_REFUND):
                problems.append(f'{name} muss ein positiver Abzugsbetrag sein')
        if 'gross_amount' in values:
            gross = values['gross_amount']
            taxes, fees = values.get('taxes', Decimal(0)), values.get('fees', Decimal(0))
            if tx.kind == Kind.BUY:
                expected = -(gross + taxes + fees)
            elif tx.kind in INCOME_KINDS | {Kind.SELL, Kind.TAX_REFUND}:
                expected = gross - taxes - fees
            elif tx.kind == Kind.REVERSAL:
                # A generic reversal can refer to either an inflow or an
                # outflow. Accept only one of those two documented identities.
                expected = gross - taxes - fees
            else:
                expected = None
            if expected is not None:
                candidates = [expected]
                # Historical cancellation documents occur both with signed
                # gross/components and with the original positive components.
                if tx.is_reversal or tx.kind == Kind.REVERSAL:
                    candidates.append(-expected)
                if tx.kind == Kind.REVERSAL:
                    purchase = -(gross + taxes + fees)
                    candidates.extend((purchase, -purchase))
                if all(abs(candidate - amount) > Decimal('0.011') for candidate in candidates):
                    rendered = ' oder '.join(f'{candidate:.2f}' for candidate in candidates)
                    problems.append(f'Brutto/Netto passt nicht: erwartet {rendered}, Betrag {amount}')
        rate = values.get('fx_rate')
        if rate is not None:
            if rate <= 0:
                problems.append('Devisenkurs muss endlich und größer als null sein')
            if tx.original_amount is None:
                problems.append('Devisenkurs ohne Fremdwährungsbetrag ist nicht eindeutig')
            if not tx.original_currency:
                problems.append('Devisenkurs ohne Fremdwährung ist nicht eindeutig')
            elif tx.original_currency.upper() == tx.currency.upper() and rate != 1:
                problems.append('Devisenkurs für identische Währungen muss 1 sein')
        if {'original_amount', 'fx_rate', 'gross_amount'} <= values.keys() and rate > 0:
            if abs(values['original_amount'] / rate - values['gross_amount']) > Decimal('0.011'):
                problems.append('Fremdwährungsbetrag / Devisenkurs passt nicht zum Bruttobetrag')
        if {'price', 'quantity', 'gross_amount'} <= values.keys() and tx.kind in (Kind.BUY, Kind.SELL):
            if abs(values['price'] * values['quantity'] - values['gross_amount']) > Decimal('0.011'):
                problems.append('Kurs x Stückzahl passt nicht zum Kurswert')
        if tx.kind == Kind.ADVANCE_LUMP_SUM:
            if amount:
                problems.append('Vorabpauschale ist eine Steuerbasis und keine zusätzliche Geldbuchung')
            if values.get('taxes', Decimal(0)):
                problems.append('Vorabpauschale darf nicht als tatsächlich gezahlte Steuer gespeichert werden')
            if getattr(tx, 'affects_cash', False):
                problems.append('Vorabpauschale darf den Geldbestand nicht verändern')
    except KeyError:
        # The field-specific diagnostic above already identifies an invalid amount.
        pass
    return problems


@dataclass
class ImportBatch:
    path: str
    file_hash: str
    snapshots: list[Snapshot] = field(default_factory=list)
    balances: list[Balance] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    account_names: list[str] = field(default_factory=list)
    account_assignments: dict[str, str] = field(default_factory=dict)
    remember_assignments: list[str] = field(default_factory=list)

    source_sheet: str = ''
    force_import: bool = False
    documents: list[BankDocument] = field(default_factory=list)
    new_accounts: list[str] = field(default_factory=list)
    pdf_text: str = field(default='', repr=False)
    pdf_booking_evidence: list[dict] = field(default_factory=list)
    document_type: str = ''
    pdf_reviewed: bool = False
    replace_bank_bookings: list[dict] = field(default_factory=list)
    history_end: str = ''
    plugin_id: str = ''
    plugin_version: str = ''
    plugin_handler: str = ''
    detection_confidence: float | None = None
    securities: list[SecurityInfo] = field(default_factory=list)
    accounts: list[AccountInfo] = field(default_factory=list)
    statements: list[AccountStatement] = field(default_factory=list)
    tax_events: list[TaxEvent] = field(default_factory=list)
    cost_reports: list[CostReport] = field(default_factory=list)
    events: list[CorporateEvent] = field(default_factory=list)

    def summary(self):
        return {'path': self.path, 'snapshots': len(self.snapshots),
                'positions': sum(len(s.positions) for s in self.snapshots),
                'balances': len(self.balances), 'transactions': len(self.transactions), 'documents': len(self.documents),
                'securities': len(self.securities), 'accounts': len(self.accounts), 'statements': len(self.statements),
                'tax_events': len(self.tax_events), 'cost_reports': len(self.cost_reports), 'events': len(self.events),
                'warnings': self.warnings + [f'{s.sheet}: {w}' for s in self.snapshots for w in s.warnings],
                'errors': self.errors, 'history_end': self.history_end}
