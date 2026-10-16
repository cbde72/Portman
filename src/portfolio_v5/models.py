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


def _number(value, *, number_format):
    """Parse a number without guessing a single three-digit separator.

    Numeric values are already unambiguous.  Text can be ``auto`` (only
    unambiguous forms), ``de`` (1.234,56), ``en`` (1,234.56), or
    ``canonical`` (1234.56 without grouping).
    """
    if value is None or text(value) in ('', '-', '--'):
        return None
    if isinstance(value, (float, int, Decimal)):
        result = Decimal(str(value))
    else:
        raw = text(value).replace('\u00a0', '').replace(' ', '').replace('−', '-')
        raw = re.sub(r'(EUR|€|Stück|Stueck|%)', '', raw, flags=re.I)
        if number_format not in ('auto', 'de', 'en', 'canonical'):
            raise ValueError(f'Unbekanntes Zahlenformat: {number_format!r}')
        if number_format == 'canonical':
            if ',' in raw or not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', raw):
                raise ValueError(f'Keine kanonische Dezimalzahl: {value!r}')
        elif number_format in ('de', 'en'):
            decimal_mark, grouping_mark = (',', '.') if number_format == 'de' else ('.', ',')
            signless = raw.lstrip('+-')
            parts = signless.split(decimal_mark)
            if len(parts) > 2 or grouping_mark in (parts[1] if len(parts) == 2 else ''):
                raise ValueError(f'Ungültige Zahl im Format {number_format}: {value!r}')
            integer = parts[0]
            if grouping_mark in integer and not re.fullmatch(
                    rf'\d{{1,3}}(?:{re.escape(grouping_mark)}\d{{3}})+', integer):
                raise ValueError(f'Ungültige Tausendergruppen: {value!r}')
            raw = raw.replace(grouping_mark, '').replace(decimal_mark, '.')
        else:
            comma, dot = raw.count(','), raw.count('.')
            if comma and dot:
                number_format = 'de' if raw.rfind(',') > raw.rfind('.') else 'en'
                return _number(value, number_format=number_format)
            mark = ',' if comma else '.' if dot else ''
            if mark:
                if raw.count(mark) > 1:
                    if not re.fullmatch(rf'[+-]?\d{{1,3}}(?:{re.escape(mark)}\d{{3}})+', raw):
                        raise ValueError(f'Uneindeutige Tausendergruppen: {value!r}')
                    raw = raw.replace(mark, '')
                else:
                    fraction = raw.rsplit(mark, 1)[1]
                    if len(fraction) == 3:
                        raise ValueError(
                            f'Uneindeutiges Zahlenformat {value!r}; Format de, en oder canonical angeben')
                    raw = raw.replace(mark, '.')
        try:
            result = Decimal(raw)
        except (InvalidOperation, ValueError):
            raise ValueError(f'Ungültige Zahl: {value!r}')
    if not result.is_finite():
        raise ValueError(f'Nicht endliche Zahl: {value!r}')
    return plain_number(result.normalize())


def parse_decimal(value, locale='de_DE'):
    """Parse a decimal using an explicit source locale.

    ``locale='auto'`` is reserved for sources without reliable metadata and
    rejects a single separator followed by three digits as ambiguous.
    """
    formats = {'de_DE': 'de', 'de': 'de', 'en_US': 'en', 'en': 'en',
               'canonical': 'canonical', 'auto': 'auto', None: 'auto'}
    if locale not in formats:
        raise ValueError(f'Nicht unterstütztes Zahlen-Locale: {locale!r}')
    return _number(value, number_format=formats[locale])


_CURRENCY_DECIMALS = {
    'BHD': 3, 'CLF': 4, 'JPY': 0, 'JOD': 3, 'KWD': 3, 'OMR': 3, 'TND': 3,
    'BTC': 8, 'ETH': 18,
}


def parse_money(value, currency='EUR', *, locale='de_DE'):
    """Parse and round a monetary amount to the currency's minor unit."""
    currency = text(currency).upper()
    if not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError(f'Ungültige Währung: {currency!r}')
    raw = value
    if isinstance(value, str):
        raw = re.sub(rf'(?i)(?:{re.escape(currency)}|€|\$|£|¥)', '', value).strip()
    parsed = parse_decimal(raw, locale=locale)
    if parsed is None:
        return None
    decimals = _CURRENCY_DECIMALS.get(currency, 2)
    quantum = Decimal(1).scaleb(-decimals)
    return str(Decimal(parsed).quantize(quantum))


def parse_quantity(value, precision=12, *, locale='de_DE'):
    """Parse a quantity without silently rounding excess fractional digits."""
    if not isinstance(precision, int) or precision < 0:
        raise ValueError('Mengenpräzision muss eine nichtnegative Ganzzahl sein')
    parsed = parse_decimal(value, locale=locale)
    if parsed is None:
        return None
    decimal = Decimal(parsed)
    fractional_digits = max(0, -decimal.normalize().as_tuple().exponent)
    if fractional_digits > precision:
        raise ValueError(
            f'Menge {value!r} hat {fractional_digits} Nachkommastellen; maximal {precision} zulässig')
    return plain_number(decimal.normalize())


def number(value, *, number_format='auto'):
    """Compatibility wrapper; new importers should use ``parse_decimal``."""
    locales = {'de': 'de_DE', 'en': 'en_US', 'canonical': 'canonical', 'auto': 'auto'}
    if number_format not in locales:
        raise ValueError(f'Unbekanntes Zahlenformat: {number_format!r}')
    return parse_decimal(value, locale=locales[number_format])


def money(value, *, number_format='auto'):
    """Compatibility wrapper for EUR amounts; use ``parse_money`` in new code."""
    locales = {'de': 'de_DE', 'en': 'en_US', 'canonical': 'canonical', 'auto': 'auto'}
    if number_format not in locales:
        raise ValueError(f'Unbekanntes Zahlenformat: {number_format!r}')
    return parse_money(value, 'EUR', locale=locales[number_format])


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
    # Explicit multiplication convention: amount in ``from`` currency times
    # fx_rate equals the amount in ``to`` currency. Keyword-only preserves all
    # historical positional constructor calls.
    fx_from_currency: str = field(default='', kw_only=True)
    fx_to_currency: str = field(default='', kw_only=True)

    def __post_init__(self):
        if self.tax_items and self.taxes is None:
            tax_total = _documented_component_total(self.tax_items)
            if tax_total is not None:
                self.taxes = money(tax_total)
        if self.solidarity_tax is None:
            solidarity = [item.amount for item in self.tax_items
                          if norm(item.kind) in ('solidaritaetszuschlag', 'solidaritytax', 'solz', 'soli')]
            if solidarity:
                self.solidarity_tax = money(sum((Decimal(value) for value in solidarity), Decimal(0)))
        if self.fee_items and self.fees is None:
            fee_total = _documented_component_total(self.fee_items)
            if fee_total is not None:
                self.fees = money(fee_total)
        enrich_tax_details(self)
        # Deliberately not a dataclass field: existing constructors and serialized
        # records stay unchanged. Missing detail rows are unknown, never zero.
        self._component_consistency_problems = _component_consistency_problems(self)


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


def _documented_component_total(items):
    """Sum documented items, or return unknown if any amount is unusable."""
    total = Decimal(0)
    for item in items or ():
        raw = item.get('amount') if isinstance(item, dict) else getattr(item, 'amount', None)
        try:
            amount = Decimal(raw)
            if not amount.is_finite():
                return None
        except (InvalidOperation, TypeError, ValueError):
            return None
        total += amount
    return total


def _component_consistency_problems(tx):
    """Compare totals only when detail positions were actually documented."""
    problems = []
    tolerance = Decimal('0.011')
    for items_name, total_name, label in (
            ('tax_items', 'taxes', 'Steuer'), ('fee_items', 'fees', 'Gebühren')):
        items = getattr(tx, items_name, None)
        declared = getattr(tx, total_name, None)
        if not items or declared in (None, ''):
            # No detail list means unknown coverage, not a sum of zero.
            continue
        documented = _documented_component_total(items)
        try:
            aggregate = Decimal(declared)
            aggregate_valid = aggregate.is_finite()
        except (InvalidOperation, TypeError, ValueError):
            aggregate_valid = False
        if documented is None or not aggregate_valid:
            continue  # Field-specific validation reports the malformed number.
        difference = aggregate - documented
        if abs(difference) > tolerance:
            problems.append(
                f'{label}summe widersprüchlich: Gesamt {aggregate:.2f}, dokumentierte Einzelpositionen '
                f'{documented:.2f}, Differenz {difference:.2f}; Einzelpositionen können unvollständig '
                'oder die Gesamtsumme kann falsch sein')
    return problems


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

    def component_total(items, field_name):
        total = Decimal(0)
        valid = True
        for index, item in enumerate(items or (), 1):
            raw = item.get('amount') if isinstance(item, dict) else getattr(item, 'amount', None)
            try:
                parsed = Decimal(raw)
                if not parsed.is_finite():
                    raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError):
                problems.append(
                    f'{field_name}[{index}].amount: ungültige oder nicht endliche Dezimalzahl {raw!r}')
                valid = False
                continue
            if re.search(r'[eE]', str(raw)):
                problems.append(f'{field_name}[{index}].amount: Exponentschreibweise {raw!r}')
            total += parsed
        return total if valid else None

    component_total(getattr(tx, 'tax_items', ()), 'tax_items')
    component_total(getattr(tx, 'fee_items', ()), 'fee_items')
    tolerance = Decimal('0.011')
    problems.extend(_component_consistency_problems(tx))
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
        if tx.kind == Kind.TAX and amount > 0 and not tx.is_reversal:
            problems.append('Steuerzahlung muss als negativer Geldbetrag gebucht werden')
        if tx.kind == Kind.TAX_REFUND and amount < 0 and not tx.is_reversal:
            problems.append('Steuererstattung muss als positiver Geldbetrag gebucht werden')
        if tx.kind == Kind.FEE and amount > 0 and not tx.is_reversal:
            problems.append('Gebührenbuchung muss als negativer Geldbetrag gebucht werden')
        taxes = values.get('taxes')
        if taxes is not None and taxes >= 0 and not (tx.is_reversal or tx.kind == Kind.TAX_REFUND):
            for name, label in (('withholding_tax', 'Quellensteuer'), ('solidarity_tax', 'Solidaritätszuschlag')):
                component = values.get(name)
                if component is not None and component > taxes + tolerance:
                    problems.append(f'{label} übersteigt die ausgewiesene Gesamtsteuer')
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
                if all(abs(candidate - amount) > tolerance for candidate in candidates):
                    rendered = ' oder '.join(f'{candidate:.2f}' for candidate in candidates)
                    problems.append(f'Brutto/Netto passt nicht: erwartet {rendered}, Betrag {amount}')
        rate = values.get('fx_rate')
        fx_from = text(getattr(tx, 'fx_from_currency', '')).upper()
        fx_to = text(getattr(tx, 'fx_to_currency', '')).upper()
        explicit_fx = bool(fx_from or fx_to)
        if explicit_fx:
            if not fx_from or not fx_to:
                problems.append('Explizites Währungspaar benötigt Ausgangs- und Zielwährung')
            if rate is None:
                problems.append('Explizites Währungspaar benötigt einen Devisenkurs')
            if fx_from and not re.fullmatch(r'[A-Z]{3}', fx_from):
                problems.append(f'Ungültige FX-Ausgangswährung: {fx_from!r}')
            if fx_to and not re.fullmatch(r'[A-Z]{3}', fx_to):
                problems.append(f'Ungültige FX-Zielwährung: {fx_to!r}')
            if fx_from and tx.original_currency and fx_from != tx.original_currency.upper():
                problems.append('FX-Ausgangswährung widerspricht der Währung des Originalbetrags')
            if fx_to and tx.currency and fx_to != tx.currency.upper():
                problems.append('FX-Zielwährung widerspricht der Buchungswährung')
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
            original, gross = values['original_amount'], values['gross_amount']
            if explicit_fx:
                if abs(original * rate - gross) > tolerance:
                    problems.append(
                        'Expliziter Devisenkurs passt nicht: Originalbetrag × Kurs ergibt nicht den Bruttobetrag')
            elif abs(original / rate - gross) > tolerance:
                problems.append(
                    'Historischer Devisenkurs passt nicht: Originalbetrag ÷ Kurs ergibt nicht den Bruttobetrag')
        if {'price', 'quantity', 'gross_amount'} <= values.keys() and tx.kind in (Kind.BUY, Kind.SELL):
            if abs(values['price'] * values['quantity'] - values['gross_amount']) > tolerance:
                problems.append('Kurs x Stückzahl passt nicht zum Kurswert')
        advance_base = getattr(tx, 'advance_tax_base', None)
        advance_currency = text(getattr(tx, 'advance_tax_currency', '')).upper()
        if advance_base is not None and not advance_currency:
            problems.append('Vorabpauschale benötigt eine explizite Währung aus der Importquelle')
        elif advance_currency and not re.fullmatch(r'[A-Z]{3}', advance_currency):
            problems.append(f'Ungültige Währung der Vorabpauschale: {advance_currency!r}')
        if advance_currency and advance_base is None:
            problems.append('Währung der Vorabpauschale ohne strukturierte Steuerbasis')
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
