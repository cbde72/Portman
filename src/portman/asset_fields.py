"""Explicit field types. Empty input means unknown, never zero."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

# field: (caption, type). Tax facts are documented inputs, not tax advice/rules.
FIELDS = {
    'security': {
        'official_name': ('Offizieller Wertpapiername', 'text'),
        'issuer_name': ('Emittent', 'text'), 'issuer_lei': ('LEI des Emittenten', 'lei'),
        'instrument_currency': ('Instrumentenwährung (keine Handelswährung)', 'currency'),
        'primary_mic': ('Primärbörse (MIC)', 'mic'),
        'sector': ('Sektor', 'text'), 'industry': ('Branche', 'text'), 'country': ('Land', 'text'),
        'esg_rating': ('ESG-Rating', 'text'), 'esg_provider': ('ESG-Anbieter', 'text'),
        'esg_date': ('ESG-Stichtag', 'date'), 'notes': ('Notizen', 'text'), 'tags': ('Tags', 'text'),
    },
    'listing': {
        'figi': ('FIGI der Notierung', 'figi'), 'composite_figi': ('Composite FIGI', 'figi'),
        'share_class_figi': ('Share Class FIGI', 'figi'), 'valid_to': ('Gültig bis', 'date'),
    },
    'position': {
        'cash_account': ('Verrechnungskonto-ID', 'text'), 'custody_type': ('Verwahrart', 'text'),
        'custody_location': ('Verwahrort', 'text'), 'blocked_quantity': ('Gesperrte Stücke', 'nonnegative'),
        'status': ('Status (aktiv / verkauft / übertrag)', 'status'), 'notes': ('Depotnotizen', 'text'),
    },
    'trade': {
        'execution_time': ('Ausführungszeit (ISO, mit Zeitzone)', 'timestamp'),
        'execution_price': ('Belegter Ausführungskurs', 'nonnegative'),
        'fees': ('Belegte Gebühren (in Buchungswährung)', 'nonnegative'),
        'gross_income': ('Bruttoertrag (in Buchungswährung)', 'nonnegative'),
        'net_income': ('Nettoertrag (in Buchungswährung)', 'nonnegative'),
        'capital_gains_tax': ('Kapitalertragsteuer', 'nonnegative'), 'solidarity_tax': ('Soli', 'nonnegative'),
        'church_tax': ('Kirchensteuer', 'nonnegative'), 'withholding_tax': ('Quellensteuer', 'nonnegative'),
        'withholding_country': ('Quellenstaat (ISO)', 'country'),
        'withholding_tax_rate': ('Quellensteuersatz (%)', 'percent'),
        'tax_rate': ('Effektiver Steuersatz (%)', 'percent'),
        'fx_rate': ('1 Buchungswährung = … Basiswährung', 'positive'),
        'base_currency': ('Basiswährung für Wechselkurs', 'currency'), 'notes': ('Buchungsnotiz', 'text'),
    },
    'tax': {
        'tax_cost': ('Belegter steuerlicher Einstand', 'nonnegative'),
        'currency': ('Währung der Steuerbeträge', 'currency'),
        'tax_status': ('Steuerstatus laut Beleg', 'text'),
        'partial_exemption': ('Teilfreistellung (%) laut Beleg', 'percent'),
        'withholding_credit': ('Anrechenbare Quellensteuer', 'nonnegative'),
        'advance_tax_base': ('Vorabpauschale laut Beleg', 'nonnegative'),
        'loss_category': ('Verlustverrechnungskategorie laut Beleg', 'text'),
        'notes': ('Steuerliche Erläuterung', 'text'),
    },
}


def validate(scope, values):
    if scope not in FIELDS or set(values) - set(FIELDS[scope]): raise ValueError('Unbekannte Stammdatenfelder.')
    result = {}
    for field, raw in values.items():
        value = '' if raw is None else str(raw).strip()
        if not value: continue
        caption, kind = FIELDS[scope][field]
        try:
            if kind in ('nonnegative', 'positive', 'percent'):
                number = Decimal(value.replace(',', '.'))
                if not number.is_finite() or number < 0 or (kind == 'positive' and number == 0) or (kind == 'percent' and number > 100):
                    raise ValueError()
                value = str(number)
            elif kind == 'date': value = date.fromisoformat(value).isoformat()
            elif kind == 'timestamp':
                stamp = datetime.fromisoformat(value)
                if stamp.tzinfo is None: raise ValueError()
                value = stamp.isoformat()
            elif kind in ('currency', 'country', 'mic', 'lei', 'figi'):
                value = value.upper()
                pattern = {'currency': r'[A-Z]{3}', 'country': r'[A-Z]{2}', 'mic': r'[A-Z0-9]{4}',
                           'lei': r'[A-Z0-9]{18}[0-9]{2}', 'figi': r'[A-Z0-9]{11}[0-9]'}[kind]
                if not re.fullmatch(pattern, value): raise ValueError()
            elif kind == 'status' and value not in ('aktiv', 'verkauft', 'übertrag'): raise ValueError()
            if len(value) > 10000: raise ValueError()
        except (ValueError, InvalidOperation):
            raise ValueError(f'{caption}: ungültiger Wert.') from None
        result[field] = value
    if scope == 'trade' and bool(result.get('fx_rate')) != bool(result.get('base_currency')):
        raise ValueError('Wechselkurs und Basiswährung gemeinsam angeben.')
    if scope == 'tax' and any(k in result for k in ('tax_cost', 'withholding_credit', 'advance_tax_base')) and not result.get('currency'):
        raise ValueError('Währung der Steuerbeträge fehlt.')
    return result
