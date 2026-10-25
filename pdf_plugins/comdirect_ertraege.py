"""comdirect Wertpapier-Erträge (Dividende, Ausschüttung, Einlösung); user plugin."""
import base64
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from portfolio_v5.models import (BankDocument, BankTransaction, CostItem, CostReport, FeeItem, Kind,
                                 SecurityInfo, TaxEvent, TaxItem, correction_number, digest, money,
                                 parse_date)
from portfolio_v5.pdf_plugins import Detection, PdfDocument, PdfPage
from portfolio_v5.accounts import account_key

DIVIDEND_KIND = Kind.DIVIDEND      # Dividenden und Fonds-Ausschüttungen
OTHER_KIND = Kind.BANK_BOOKING     # Einlösungen: einfache, nicht klassifizierte Gutschrift
# Hinweis: Die Dividenden-Zusammenführung (settlement.py) erkennt comdirect-Belege an booking_text
# 'comdirect Dividendengutschrift' / 'comdirect Ertragsgutschrift' und setzt income_basis='gross'.

HANDLERS = {
    'dividendengutschrift': dict(title='comdirect Dividendengutschrift', kind=DIVIDEND_KIND,
                                 marker=re.compile(r'Abrechnung\s*Dividendengutschrift')),
    'ertragsgutschrift': dict(title='comdirect Ertragsgutschrift', kind=DIVIDEND_KIND,
                              marker=re.compile(r'Abrechnung\s*Ertragsgutschrift')),
    'einloesung': dict(title='comdirect Einlösung', kind=OTHER_KIND,
                       marker=re.compile(r'Abrechnung\s*Einl[öo]sung')),
}

# Eine Zeile: <IBAN> EUR <Valuta> EUR <Betrag>. Unabhängig von der Zeilenreihenfolge,
# denn pypdf liefert diese Belege teils von unten nach oben, teils ohne Leerzeichen.
SETTLEMENT = re.compile(
    r'(?m)^[ \t]*(?P<iban>DE(?:[ \t]*\d){20})[ \t]+[A-Z]{3}[ \t]+'
    r'(?P<date>\d{2}\.\d{2}\.\d{4})[ \t]+(?P<currency>[A-Z]{3})[ \t]+(?P<amount>[0-9.]+,\d{2})[ \t]*$')
HOLDING = re.compile(r'(?m)^[ \t]*STK[ \t]*(?P<qty>\d[\d.]*(?:,\d+)?)(?P<rest>[^\n]*)$')
PER_LINE = re.compile(r'(?m)^[ \t]*per[ \t]+\d{2}\.\d{2}\.\d{4}[ \t]+(?P<rest>\S[^\n]*)$')
ISIN = re.compile(r'(?<![A-Za-z0-9])[A-Z]{2}[A-Z0-9]{9}\d')
FOREIGN = re.compile(r'(?:Bruttobetrag:|Kurswert\s*Einl[öo]sung)\s*(?P<currency>[A-Z]{3})\s+(?P<amount>[0-9.]+,\d{2})')
PER_SHARE = re.compile(
    r'(?P<c>[A-Z]{3})\s+(?P<r>[0-9.]+,\d+)\s+(?:Dividende|Ausschüttung)\s+pro\s+Stück'
    r'(?:\s+für\s+Geschäftsjahr\s+(?P<a>\d{2}\.\d{2}\.\d{2})\s+bis\s+(?P<b>\d{2}\.\d{2}\.\d{2}))?')
PAY_DATE = re.compile(r'zahlbar\s+ab\s*(?P<d>\d{2}\.\d{2}\.\d{4})')
FX_PAIR = re.compile(r'Devisenkurs:\s*(?P<pair>[A-Z]{3}/[A-Z]{3})\s+(?P<rate>[0-9.]+,\d+)')
DOMICILE = re.compile(r'Emissionsland:\s*(?P<c>[A-ZÄÖÜa-zäöüß][^\n]*?)\s*(?:\n|$)')
AMOUNT = r'[0-9]{1,3}(?:\.[0-9]{3})*,\d{2}|\d+,\d{2}'

# MiFID-II cost information ("Kosteninformation zum Wertpapiergeschäft").
# These PDFs are simulations only and must never create a transaction, cash
# flow, balance or depot position.
MIFID_COST_MARKER = re.compile(r'Kosteninformation\s+zum\s+Wertpapiergesch\w*', re.I)
MIFID_COST_TITLE = re.compile(
    r'Kosteninformation\s+zum\s+Wertpapiergesch\w*\s+'
    r'(?P<date>\d{2}\.\d{2}\.\d{4})\s*-\s*(?P<time>\d{2}:\d{2})', re.I)
MIFID_COST_SECURITY = re.compile(
    r'(?m)^(?P<name>[^\n]*\S[^\n]*)\n\s*WKN\s*:\s*(?P<wkn>[A-Z0-9]{6})', re.I)
MIFID_COST_ISIN = re.compile(r'\bISIN\s*:\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)', re.I)
MIFID_COST_SPARPLAN = re.compile(
    r'Sparplan\s*:\s*(?P<amount>' + AMOUNT + r')\s*EUR\s*mtl\.', re.I)
MIFID_COST_ANNUAL_SAVINGS = re.compile(
    r'Sparbetrag\s+pro\s+Jahr\s*:\s*(?P<amount>' + AMOUNT + r')\s*EUR', re.I)
MIFID_COST_VENUE = re.compile(r'Ausf.hrungsplatz\s*:\s*(?P<venue>[^\n]+)', re.I)
MIFID_COST_CURRENCY = re.compile(r'Abrechnung\s+in\s+(?P<currency>[A-Z]{3})', re.I)
MIFID_COST_CUSTOMER = re.compile(r'Kundennummer\s*:\s*(?P<number>\d[\d ]*\d)', re.I)
MIFID_COST_YEARS = re.compile(
    r'angenommene(?:n)?\s+Laufzeit\s+von\s+(?P<years>\d+)\s+Jahr(?:\(en\)|en)?'
    r'\s+und\s+einer\s+Haltedauer\s+von\s+(?P<holding>\d+)\s+Jahr', re.I)
MIFID_COST_TOTAL = re.compile(
    r'voraussichtlichen\s+Gesamtkosten\s+auf\s+(?P<amount>' + AMOUNT + r')\s+EUR'
    r'\s+und\s+reduzieren\s+die\s+Rendite\s+um\s+durchschnittlich\s+'
    r'(?P<pct>' + AMOUNT + r')\s*%', re.I | re.S)
MIFID_COST_PHASE_HEADERS = (
    ('kauf', True, re.compile(
        r'Kosten\s+des\s+Wertpapierkaufes\s*(?P<annual>,\s*pro\s+Jahr)?\s+'
        r'(?P<amount>' + AMOUNT + r')\s*EU\w*', re.I)),
    ('haltedauer', True, re.compile(
        r'Kosten\s+w\S*hrend\s+der\s+Haltedauer\s*\(pro\s+Jahr\)\s+'
        r'(?P<amount>' + AMOUNT + r')\s*EU\w*', re.I)),
    ('verkauf', False, re.compile(
        r'Kosten\s+des\s+Wertpapierverkaufes\s+(?P<amount>' + AMOUNT + r')\s*EU\w*', re.I)),
)
MIFID_COST_LINE = re.compile(
    r'^(?P<label>[^\n]*?\[(?:E|F|P)\](?:\d+)?)\s*(?P<amount>' + AMOUNT + r')\s*EU\w*\s*$', re.I | re.M)
MIFID_COST_MARKER_CATEGORY = {'E': 'eigen', 'F': 'fremd', 'P': 'produkt'}
MIFID_COST_DETAILS = {
    'service_costs': ('Dienstleistungskosten der Bank', True),
    'overhead_costs': ('Dienstleistungskosten fremd', True),
    'product_costs': ('Produktkosten (nach Zahlung von Dritten)', True),
    'inducements': ('Davon erhält die Bank von Dritten', False),
}
MIFID_COST_YEAR_ROW = re.compile(
    r'(?m)^(?P<label>Im\s+\d+\.\s+Jahr|Wertpapierverkauf)\s+'
    r'(?P<savings>' + AMOUNT + r')\s+EUR(?P<rest>[^\n]*)$', re.I)

# Older comdirect trade confirmations often have broken embedded fonts and are
# extracted without spaces.  These patterns therefore use stable ASCII labels
# and accept both compact and normally spaced text.
TRADE_MARKER = re.compile(r'Wertpapier(?P<type>kauf|verkauf)', re.I)
TRADE_FEES = {
    'provision': re.compile(r'Provision\s*:?\s*EUR\s*(?:-\s*)?(?P<a>' + AMOUNT + ')', re.I),
    'orderentgelt': re.compile(r'Orderentgelt\s*:?\s*EUR\s*(?:-\s*)?(?P<a>' + AMOUNT + ')', re.I),
    'handelsplatzgebuehr': re.compile(r'(?:Handelsplatzgeb.hr|B.rsengeb.hr)\s*:?\s*EUR\s*(?:-\s*)?(?P<a>' + AMOUNT + ')', re.I),
    'fremdspesen': re.compile(r'(?:Fremdspesen|fremde\s+Spesen)\s*:?\s*EUR\s*(?:-\s*)?(?P<a>' + AMOUNT + ')', re.I),
}
TRADE_LINE = re.compile(
    r'Stk\.\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s*(?P<name>.+?)\s*,?\s*WKN/ISIN\s*:\s*'
    r'(?P<wkn>[A-Z0-9]{6})\s*/\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)', re.I | re.S)
TRADE_DAY = re.compile(
    r'(?:Wertpapier(?P<type>kauf|verkauf)|(?P<generic>Gesch.ftsvorgang))\s*Nr\.?\s*'
    r'(?P<order>\d+)\s*vom\s*(?P<d>\d{2}\.\d{2}\.\d{4})', re.I)
TRADE_SETTLEMENT = re.compile(
    r'Valuta\s*(?P<d>\d{2}\.\d{2}\.\d{4}).{0,80}?IBAN\s*(?P<iban>DE\d{20})|'
    r'Valuta.{0,80}?(?P<iban2>DE\d{20})\s*EUR\s*(?P<d2>\d{2}\.\d{2}\.\d{4})', re.I | re.S)
TRADE_TOTAL = re.compile(r'ZuIhren(?P<direction>Lasten|Gunsten)(?:nach|vor)Steuern\s*:\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I)
TRADE_MARKET = re.compile(r'Kurswert\s*:?\s*EUR\s*(?P<a>' + AMOUNT + ')', re.I)
TRADE_EXECUTION = re.compile(
    r'Nennwert\s*Zum\s*(?:Misch)?Kurs\s*von\s*(?:St\.\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s*)?'
    r'EUR\s*(?P<price>\d[\d.]*(?:,\d+)?)\s*Kurswert\s*:?\s*EUR\s*(?P<market>' + AMOUNT + ')',
    re.I)
TRADE_DEPOT = re.compile(r'Depot(?:nummer|nr\.)\s*:?\s*(?P<n>\d+)', re.I)
TRADE_REFERENCE = re.compile(r'Referenz-Nummer\s*:\s*(?P<r>[A-Z0-9]+)', re.I)
TRADE_TAX_TOTAL = re.compile(r'abgef.hrteSteuern\s*:?\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I)
TRADE_TAX_ITEMS = {
    'kapitalertragsteuer': re.compile(r'Kapitalertragsteuer\s*:?\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I),
    'solidaritaetszuschlag': re.compile(r'Solidarit.tszuschlag\s*:?\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I),
    'kirchensteuer': re.compile(r'Kirchensteuer\s*:?\s*EUR\s*-?\s*(?P<a>' + AMOUNT + ')', re.I),
}

# Kurs und Stückzahl werden auf den ausgewiesenen Kurswert in Cent gerundet.
# Ein Cent Toleranz deckt ausschließlich Differenzen der gedruckten Kurspräzision ab;
# größere Abweichungen werden als widersprüchliche Abrechnung abgewiesen.
TRADE_VALUE_TOLERANCE = Decimal('0.01')


def _trade_value_difference(qty, price, market):
    calculated = (Decimal(qty) * Decimal(price)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return calculated, abs(calculated - Decimal(market))


def _trade_quantity(document, tax_security):
    """Primär Geschäftsabrechnung, sekundär nur eine positive steuerliche Stk.-Angabe."""
    executions = []
    for page in document.pages:
        compact = re.sub(r'[ \t]+', '', page.text)
        match = TRADE_EXECUTION.search(compact)
        if match:
            executions.append((page.number, match))
    if len(executions) > 1:
        raise ValueError('Mehrere Geschäftsabrechnungen mit Nennwert, Kurs und Kurswert erkannt.')

    tax_qty = correction_number(tax_security.group('qty')) if tax_security else None
    tax_qty = tax_qty if tax_qty is not None and Decimal(tax_qty) > 0 else None
    if executions:
        page_number, execution = executions[0]
        primary_qty = correction_number(execution.group('qty')) if execution.group('qty') else None
        price = correction_number(execution.group('price'))
        market = money(execution.group('market'))
        if primary_qty is not None and Decimal(primary_qty) <= 0:
            primary_qty = None
        if primary_qty is not None and tax_qty is not None and Decimal(tax_qty) != Decimal(primary_qty):
            raise ValueError(
                f'Stückzahlangaben widersprüchlich: Geschäftsabrechnung {primary_qty} Stück, '
                f'steuerliche Mitteilung {tax_qty} Stück.')
        qty = primary_qty or tax_qty
        if qty is None:
            raise ValueError('Stückzahl fehlt sowohl in der Geschäftsabrechnung als auch als positive Angabe '
                             'in der steuerlichen Mitteilung; Dokument nicht automatisch verbucht.')
        if price is None or market is None:
            raise ValueError(f'Ungültige Kurs- oder Kurswertangabe auf der Geschäftsabrechnung (Seite {page_number}).')
        calculated, difference = _trade_value_difference(qty, price, market)
        if difference > TRADE_VALUE_TOLERANCE:
            raise ValueError(
                f'Geschäftsabrechnung widersprüchlich: {qty} Stück × {price} EUR ergeben '
                f'{calculated:.2f} EUR, ausgewiesen sind {Decimal(market):.2f} EUR '
                f'(Toleranz {TRADE_VALUE_TOLERANCE:.2f} EUR).')
        source = ('comdirect Geschäftsabrechnung · Nennwert/Zum Kurs von' if primary_qty is not None
                  else 'comdirect steuerliche Mitteilung · Stk. (sekundär, gegen Geschäftsabrechnung geprüft)')
        return qty, price, market, page_number, source

    if tax_qty is None:
        raise ValueError('Stückzahl fehlt sowohl in der Geschäftsabrechnung als auch als positive Angabe '
                         'in der steuerlichen Mitteilung; Dokument nicht automatisch verbucht.')
    raise ValueError(f'Steuerliche Stückzahl {tax_qty} ist vorhanden, kann aber ohne Kurs und Kurswert '
                     'der Geschäftsabrechnung nicht plausibilisiert werden; Dokument nicht automatisch verbucht.')


def short_date(value):
    """'01.07.18' -> '2018-07-01' (zweistelliges Jahr; Belege ab 2000)."""
    if not value:
        return ''
    day, month, year = value.split('.')
    return f'{2000 + int(year):04d}-{month}-{day}'
# Rückfall bei defekter Schriftkodierung: nur der Name hinter dem Spaltenabstand ist lesbar.
NAME_AFTER_GAP = {
    'per': re.compile(r'(?m)^per[^\n]*?[ \t]{3,}(\S[^\n]*?)[ \t]*$'),
    'stk': re.compile(r'(?m)^STK[^\n]*?[ \t]{3,}(\S[^\n]*?)[ \t]*$'),
}

OCR_MIN_CONFIDENCE = 0.90   # je Textfeld (der Seitenwert ist der kleinste Einzelwert und zu grob)
QTY_TOKEN = re.compile(r'(?<![\d.,])\d[\d.]*,\d+(?![\d,])')
RATE = (re.compile(r'Einl[öo]sung\s+zum\s+Kurs\s+von\s+(?P<r>[0-9.]+,\d+)\s+[A-Z]{3}'),
        re.compile(r'[A-Z]{3}\s+(?P<r>[0-9.]+,\d+)\s+(?:Dividende|Ausschüttung)\s+pro\s+Stück'))
BASE = (re.compile(r'Kurswert\s*Einl[öo]sung\s+[A-Z]{3}\s+(?P<a>' + AMOUNT + ')'),
        re.compile(r'Bruttobetrag:\s*[A-Z]{3}\s+(?P<a>' + AMOUNT + ')'))

ADVANCE_TAX_TITLE = re.compile(
    r'Steuerliche\s+Behandlung:\s*Vorabpauschale\s+Ausland\s+vom\s+(?P<date>\d{2}\.\d{2}\.\d{4})', re.I)
ADVANCE_TAX_SECURITY = re.compile(
    r'Stk\.\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s+(?P<name>.+?)\s*,\s*WKN\s*/\s*ISIN:\s*'
    r'(?P<wkn>[A-Z0-9]{6})\s*/\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)', re.I)
ADVANCE_TAX_BASE = re.compile(r'Vorabpauschale\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_PARTIAL = re.compile(
    r'Teilfreistellung\s*\((?P<rate>[\d,.]+)%\)\s+EUR\s*-\s*(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_TAXABLE = re.compile(
    r'Steuerbemessungsgrundlage\s+vor\s+Verlustverrechnung(?:\s*\(\d+\))?\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_USED = re.compile(
    r'in\s+Anspruch\s+genommener\s+Freistellungsauftrag\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_AFTER = re.compile(
    r'Steuerbemessungsgrundlage\s+nach\s+Verlustverrechnung\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_DOCUMENT_DATE = re.compile(r'Datum:\s*(?P<d>\d{2}\.\d{2}\.\d{4})', re.I)
ADVANCE_TAX_COMPONENTS = {
    'capital_gains_tax': re.compile(r'Kapitalertragsteuer\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I),
    'solidarity_surcharge': re.compile(r'Solidarit.tszuschlag\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I),
    'church_tax': re.compile(r'Kirchensteuer\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I),
}
ADVANCE_TAX_PAID = re.compile(r'abgef.hrte\s+Steuern\s+EUR\s+(?P<a>' + AMOUNT + r')', re.I)
ADVANCE_TAX_SETTLEMENT = re.compile(
    r'(?:Belastung|Gutschrift)\s+erfolgt\s+mit\s+Valuta\s+(?P<d>\d{2}\.\d{2}\.\d{4})'
    r'.{0,100}?IBAN\s*(?P<iban>DE(?:\s*\d){20})', re.I | re.S)
ADVANCE_TAX_DEPOT = re.compile(r'Depotnummer:\s*(?P<n>\d+(?:\s+\d+)?)', re.I)
ADVANCE_TAX_REFERENCE = re.compile(r'Referenz-Nummer:\s*(?P<r>[A-Z0-9\s]+?)(?=Depotnummer:|\n\s*\n)', re.I)

# Separate comdirect tax notices for fund distributions are often extracted
# without spaces and with damaged umlaut encoding. The original text remains
# untouched as evidence; only a compact copy is used for field recognition.
INVESTMENT_TAX_TITLE = re.compile(
    r'SteuerlicheBehandlung:(?P<origin>Inl.ndische|Ausl.ndische)Investment-Aussch.ttungvom'
    r'(?P<date>\d{2}\.\d{2}\.\d{4})', re.I)
INVESTMENT_TAX_SECURITY = re.compile(
    r'Stk\.(?P<qty>\d[\d.]*(?:,\d+)?)(?P<name>.+?),WKN/ISIN:'
    r'(?P<wkn>[A-Z0-9]{6})/(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)', re.I)
INVESTMENT_TAX_GROSS = re.compile(r'ZuIhrenGunstenvorSteuern:EUR(?P<a>' + AMOUNT + r')', re.I)
INVESTMENT_TAX_PARTIAL = re.compile(
    r'Teilfreistellung\((?P<rate>[\d,.]+)%\)EUR-?(?P<a>' + AMOUNT + r')', re.I)
INVESTMENT_TAX_TAXABLE = re.compile(
    r'Steuerbemessungsgrundlage(?:vorVerlustverrechnung)?(?:\(\d+\))*EUR(?P<a>' + AMOUNT + r')', re.I)
INVESTMENT_TAX_TAXABLE_BEFORE = re.compile(
    r'SteuerbemessungsgrundlagevorVerlustverrechnung(?:\(\d+\))*EUR(?P<a>' + AMOUNT + r')', re.I)
INVESTMENT_TAX_USED = re.compile(
    r'inAnspruchgenommenerFreistellungsauftragEUR(?P<a>' + AMOUNT + r')', re.I)
INVESTMENT_TAX_AFTER = re.compile(
    r'SteuerbemessungsgrundlagenachVerlustverrechnungEUR(?P<a>' + AMOUNT + r')', re.I)
INVESTMENT_TAX_COMPONENTS = {
    'capital_gains_tax': re.compile(r'KapitalertragsteuerEUR-?(?P<a>' + AMOUNT + r')', re.I),
    'solidarity_surcharge': re.compile(r'Solidarit.tszuschlagEUR-?(?P<a>' + AMOUNT + r')', re.I),
    'church_tax': re.compile(r'KirchensteuerEUR-?(?P<a>' + AMOUNT + r')', re.I),
}
INVESTMENT_TAX_PAID = re.compile(r'abgef.hrteSteuernEUR-?(?P<a>' + AMOUNT + r')', re.I)
INVESTMENT_TAX_NET = re.compile(r'ZuIhrenGunstennachSteuern:EUR(?P<a>' + AMOUNT + r')', re.I)
INVESTMENT_TAX_SETTLEMENT = re.compile(
    r'DieGutschrifterfolgtmitValuta(?P<date>\d{2}\.\d{2}\.\d{4})aufKontoEURmitderIBAN'
    r'(?P<iban>DE\d{20})', re.I)
INVESTMENT_TAX_DEPOT = re.compile(r'Depotnummer:(?P<n>\d+)', re.I)
INVESTMENT_TAX_REFERENCE = re.compile(r'Referenz-Nummer:(?P<r>[A-Z0-9]{16})', re.I)
INVESTMENT_TAX_DOCUMENT_DATE = re.compile(r'Datum:(?P<d>\d{2}\.\d{2}\.\d{4})', re.I)

DIVIDEND_TAX_TITLE = re.compile(
    r'SteuerlicheBehandlung:Inl.ndischeDividendevom(?P<date>\d{2}\.\d{2}\.\d{4})', re.I)
DIVIDEND_TAX_SECURITY = re.compile(
    r'Stk\.(?P<qty>\d[\d.]*(?:,\d+)?)(?P<name>.+?),WKN/ISIN:'
    r'(?P<wkn>[A-Z0-9]{6})/(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)', re.I)
DIVIDEND_TAX_USED = re.compile(r'inAnspruchgenommenerFreistellungsauftragEUR(?P<a>' + AMOUNT + r')', re.I)
DIVIDEND_TAX_AFTER = re.compile(
    r'SteuerbemessungsgrundlagenachVerlustverrechnungEUR(?P<a>' + AMOUNT + r')', re.I)


def _advance_tax_balances(document):
    """Read the eight before/after balances in comdirect's reconciliation table."""
    fields = (
        'equity_loss_pot_before', 'equity_loss_pot_after',
        'other_loss_pot_before', 'other_loss_pot_after',
        'foreign_tax_pot_before', 'foreign_tax_pot_after',
        'allowance_before', 'allowance_after')
    for page in document.pages:
        start = re.search(r'Verrechnungssalden\s+in\s+EUR', page.text, re.I)
        end = re.search(r'Hinweise\s+zur\s+Ermittlung', page.text, re.I)
        if not start or not end:
            continue
        if start.end() < end.start():
            amounts = [money(value) for value in re.findall(AMOUNT, page.text[start.end():end.start()])]
            if len(amounts) >= 8:
                return dict(zip(fields, amounts[-8:]))
            continue

        # portfolio_v5.pdf_text may return the visual table from bottom to top.
        # Retained horizontal spacing still identifies the four columns.
        reversed_table = page.text[end.end():start.start()]
        after_split = re.split(r'nach\s+Ermittlung', reversed_table, maxsplit=1, flags=re.I)
        if len(after_split) != 2:
            continue
        before_split = re.split(r'vor\s+Ermittlung', after_split[1], maxsplit=1, flags=re.I)
        if len(before_split) != 2:
            continue

        def columns(fragment):
            result = {}
            for line in fragment.splitlines():
                for match in re.finditer(AMOUNT, line):
                    column = min(range(4), key=lambda index: abs(match.start() - (44, 87, 130, 170)[index]))
                    if abs(match.start() - (44, 87, 130, 170)[column]) <= 12:
                        result[column] = money(match.group())
            return result

        after_values, before_values = columns(after_split[0]), columns(before_split[0])
        if set(after_values) == set(before_values) == set(range(4)):
            amounts = [value for column in range(4)
                       for value in (before_values[column], after_values[column])]
            return dict(zip(fields, amounts))
    return {}


def ocr_holding(document, page, options):
    """Ergänzt ISIN und Stückzahl per lokaler OCR (portfolio_v5.pdf_ocr), nur bei Bedarf.
    Rückgabe: (gefundene Felder, OCR-Text, Hinweis). Nur Felder mit ausreichendem Vertrauen."""
    if not options.get('allow_ocr', True):
        return {}, '', 'OCR ist ausgeschaltet; fehlende Felder bleiben offen.'
    try:
        from portfolio_v5.pdf_ocr import ocr_page, ocr_page_regions
        ocr_text, _ = ocr_page(document.path, page.number - 1)
        regions = ocr_page_regions(document.path, page.number - 1)
    except Exception as error:   # OCR-Pakete fehlen, PDF nicht lesbar o. ä.
        return {}, '', f'OCR-Ergänzung nicht möglich: {error}'

    def confidence(token):
        return max((r['confidence'] for r in regions if token in r['text']), default=0.0)

    found = {}
    line = re.search(r'(?m)^[ \t]*STK\b(?P<rest>[^\n]*)$', ocr_text)
    if line:
        isin, qty = ISIN.search(line.group('rest')), QTY_TOKEN.search(line.group('rest'))
        if isin and confidence(isin.group()) >= OCR_MIN_CONFIDENCE:
            found['isin'] = (isin.group(), confidence(isin.group()))
        if qty and confidence(qty.group()) >= OCR_MIN_CONFIDENCE:
            found['qty'] = (correction_number(qty.group()), confidence(qty.group()))
    return found, ocr_text, None


def plausible(qty, text):
    """Stückzahl × Satz pro Stück ≈ Brutto/Kurswert. True/False, None wenn nicht prüfbar."""
    rate = next((m for m in (r.search(text) for r in RATE) if m), None)
    base = next((m for m in (b.search(text) for b in BASE) if m), None)
    if not (rate and base):
        return None
    expected = float(correction_number(rate.group('r'))) * float(qty)
    return abs(expected - float(money(base.group('a')))) <= 0.01


def split_name_wkn(rest):
    """Die WKN steht je nach Textextraktion vor oder hinter dem Namen, ggf. ohne Leerzeichen."""
    rest = ' '.join(rest.split())

    def is_wkn(token):
        return bool(re.fullmatch(r'[A-Z0-9]{6}', token)) and any(c.isdigit() for c in token)

    parts = rest.split()
    if parts and is_wkn(parts[-1]):
        return ' '.join(parts[:-1]), parts[-1]
    if parts and is_wkn(parts[0]):
        return ' '.join(parts[1:]), parts[0]
    glued = re.match(r'([A-Z0-9]{6})(?=[A-Za-z])(.+)$', rest)
    if glued and any(c.isdigit() for c in glued.group(1)):
        return glued.group(2).strip(), glued.group(1)
    return rest, ''


def _mifid_detail(text, label, with_percentage):
    """Exact MiFID detail value; an absent line stays None and never becomes zero."""
    amount = re.search(re.escape(label) + r'\s+(?P<amount>' + AMOUNT + r')\s+EUR', text, re.I)
    percentage = None
    if with_percentage and amount:
        tail = text[amount.end():amount.end() + 400]
        next_label = re.search(
            r'\n\s*(?:-\s*)?(?:Dienstleistungskosten|Produktkosten|Davon\s+erhält)', tail, re.I)
        if next_label:
            tail = tail[:next_label.start()]
        pct = re.search(r'(?P<pct>' + AMOUNT + r')\s*%\s*p\.a\.', tail, re.I)
        percentage = money(pct.group('pct')) if pct else None
    return (money(amount.group('amount')) if amount else None), percentage


def _mifid_cost_components(text, security_ref):
    """Keep every printed cost line, including its phase and original label."""
    phase = ''
    annual = None
    phase_totals = {}
    items = []
    for raw_line in text.splitlines():
        line = ' '.join(raw_line.split())
        if not line:
            continue
        matched_header = False
        for phase_id, phase_annual, pattern in MIFID_COST_PHASE_HEADERS:
            header = pattern.search(line)
            if header:
                if phase_id in phase_totals:
                    raise ValueError(f'Kostenblock {phase_id} ist mehrfach ausgewiesen.')
                phase = phase_id
                annual = (bool(header.groupdict().get('annual'))
                          if phase_id == 'kauf' else phase_annual)
                phase_totals[phase_id] = money(header.group('amount'))
                matched_header = True
                break
        if matched_header:
            continue
        cost_line = MIFID_COST_LINE.match(line)
        if not cost_line or not phase:
            continue
        label = ' '.join(cost_line.group('label').split())
        marker = re.search(r'\[(E|F|P)\]', label)
        if not marker:
            continue
        amount = money(cost_line.group('amount'))
        category = MIFID_COST_MARKER_CATEGORY[marker.group(1)]
        item = CostItem(
            security_ref=security_ref,
            total=amount,
            label=label,
            phase=phase,
            category=category,
            annual=annual,
            source_text=line)
        if category == 'eigen':
            item.service_costs = amount
        elif category == 'fremd':
            item.fx_costs = amount
        elif category == 'produkt':
            item.product_costs = amount
        if 'Zahlung von Dritten an die Bank' in label:
            item.inducements = amount
        items.append(item)

    missing = [phase_id for phase_id, _annual, _pattern in MIFID_COST_PHASE_HEADERS
               if phase_id not in phase_totals]
    if missing:
        raise ValueError('MiFID-II-Kostenblöcke fehlen: ' + ', '.join(missing))
    for phase_id, _annual, _pattern in MIFID_COST_PHASE_HEADERS:
        printed = Decimal(phase_totals[phase_id])
        calculated = sum((Decimal(item.total) for item in items if item.phase == phase_id),
                         Decimal('0'))
        if abs(printed - calculated) > Decimal('0.01'):
            raise ValueError(
                f'MiFID-II-Kostenblock {phase_id} widersprüchlich: gedruckt {printed:.2f} EUR, '
                f'Einzelpositionen {calculated:.2f} EUR.')
    return phase_totals, items


def _mifid_cost_projection(text):
    """The printed 1..n year table; it is informational and never booked."""
    rows = []
    for match in MIFID_COST_YEAR_ROW.finditer(text):
        rest = match.group('rest')
        pct_match = re.search(r'(?P<pct>-?(?:' + AMOUNT + r'))\s*%', rest)
        without_pct = re.sub(r'(?:-?(?:' + AMOUNT + r'))\s*%', '', rest)
        amounts = [money(value) for value in re.findall(AMOUNT, without_pct)]
        total = amounts[-1] if amounts else None
        purchase = amounts[0] if len(amounts) >= 3 else None
        holding = amounts[1] if len(amounts) >= 3 else None
        rows.append({
            'label': ' '.join(match.group('label').split()),
            'savings_cumulative': money(match.group('savings')),
            'purchase_costs': purchase,
            'holding_costs': holding,
            'total_costs': total,
            'return_impact_pct': money(pct_match.group('pct')) if pct_match else None,
        })
    return rows


def _mifid_period_end(period_start, years):
    if not period_start or not years:
        return period_start
    try:
        start = date.fromisoformat(period_start)
        end = date(start.year + years, start.month, start.day)
    except (ValueError, TypeError):
        return period_start
    return (end - timedelta(days=1)).isoformat()


def _mifid_filename_metadata(stem, file_hash):
    sparplan = re.search(r'Sparplan[_\s-]*Nr\.?[_\s-]*(?P<n>\d+)', stem, re.I)
    suffix = re.search(r'_(?P<ref>[A-Z0-9]{6})$', stem, re.I)
    return (sparplan.group('n') if sparplan else '',
            suffix.group('ref').upper() if suffix else file_hash[:6].upper())


def _mifid_information_type(text):
    """Classify the bank's stated perspective without deriving it from values."""
    if re.search(r'\b(?:Ex[ -]?post|nachtr.gliche|tats.chlich\s+angefallene)\b', text, re.I):
        return 'ex_post'
    if (re.search(r'\b(?:Ex[ -]?ante|Kostensimulation|geplante[ns]?\s+Wertpapiergesch.ft)\b', text, re.I)
            or MIFID_COST_TITLE.search(text)):
        return 'ex_ante'
    return 'unknown'


class ComdirectErtraegePlugin:
    plugin_id = 'user.comdirect-ertraege'
    bank_name = 'comdirect'
    version = '1.5'
    document_types = ('Dividendengutschrift, Ertragsgutschrift, Einlösung, Wertpapierabrechnung Kauf/Verkauf, '
                      'Steuermitteilung Vorabpauschale, Steuermitteilung Investment-Ausschüttung, '
                      'MiFID-II-Kosteninformation (Kostensimulation, keine Transaktion)')

    def detect(self, document):
        text = document.text
        if not re.search(r'comdirect', text, re.I):
            return []
        result = []
        if (MIFID_COST_TITLE.search(text) and MIFID_COST_SECURITY.search(text)
                and MIFID_COST_TOTAL.search(text)):
            result.append(Detection(
                0.99, 'comdirect MiFID-II-Kosteninformation – keine ausgeführte Transaktion',
                'kosteninformation_mifid_ii',
                'comdirect, MiFID-II-Kostensimulation und Gesamtkostenausweis erkannt'))
        compact = re.sub(r'\s+', '', text)
        investment_title = INVESTMENT_TAX_TITLE.search(compact)
        if investment_title and INVESTMENT_TAX_SECURITY.search(compact):
            origin = 'inländische' if investment_title.group('origin').lower().startswith('inl') else 'ausländische'
            result.append(Detection(0.99, f'comdirect Steuermitteilung {origin} Investment-Ausschüttung',
                                    'investment_ausschuettung',
                                    'comdirect, Investment-Ausschüttung und Wertpapierkennung erkannt'))
        dividend_tax_title = DIVIDEND_TAX_TITLE.search(compact)
        if dividend_tax_title and DIVIDEND_TAX_SECURITY.search(compact):
            result.append(Detection(0.99, 'comdirect Steuermitteilung inländische Dividende',
                                    'dividende_steuer_inland',
                                    'comdirect, inländische Dividende und Wertpapierkennung erkannt'))
        if ADVANCE_TAX_TITLE.search(text) and ADVANCE_TAX_SECURITY.search(text):
            result.append(Detection(0.99, 'comdirect Steuermitteilung Vorabpauschale', 'vorabpauschale',
                                    'comdirect, Vorabpauschale und Wertpapierkennung erkannt'))
        trade_marker = TRADE_MARKER.search(text)
        compact = re.sub(r'[ \t]+', '', text)
        if trade_marker and TRADE_TOTAL.search(compact) and TRADE_MARKET.search(compact):
            trade_type = trade_marker.group('type').lower()
            result.append(Detection(0.97, 'comdirect Wertpapierabrechnung ' + trade_type.title(),
                                    'wertpapier' + trade_type,
                                    'comdirect, Wertpapier' + trade_type + ' und Provision erkannt'))
        elif trade_marker and re.search(r'GESCH.FTSABRECHNUNG', text, re.I):
            trade_type = trade_marker.group('type').lower()
            result.append(Detection(0.96, 'comdirect Wertpapierabrechnung ' + trade_type.title(),
                                    'wertpapier' + trade_type,
                                    'comdirect Geschäftsabrechnung mit beschädigter eingebetteter Schrift erkannt'))
        if not SETTLEMENT.search(text):
            return result
        result.extend(Detection(0.95, handler['title'], handler_id,
                          'comdirect, Wertpapier-Abrechnung und Dokumenttyp erkannt')
                for handler_id, handler in HANDLERS.items() if handler['marker'].search(text))
        return result

    def _mifid_cost_information(self, document, batch):
        """Parse a MiFID-II cost simulation without creating any economic booking."""
        text = document.text
        title = MIFID_COST_TITLE.search(text)
        security = MIFID_COST_SECURITY.search(text)
        total_row = MIFID_COST_TOTAL.search(text)
        if not title or not security or not total_row:
            raise ValueError('MiFID-II-Kosteninformation unvollständig: Datum, Wertpapier oder Gesamtkosten fehlen.')

        document_date = parse_date(title.group('date'))
        if not document_date:
            raise ValueError('MiFID-II-Kosteninformation: Dokumentdatum ist ungültig.')
        document_time = title.group('time')
        wkn = security.group('wkn').upper()
        security_name = ' '.join(security.group('name').split())
        isin_match = MIFID_COST_ISIN.search(text)
        isin = isin_match.group('isin').upper() if isin_match else ''
        security_ref = isin or 'WKN:' + wkn

        sparplan_number, reference = _mifid_filename_metadata(document.path.stem, document.file_hash)
        account = (f'Kosteninformation Sparplan {sparplan_number}'
                   if sparplan_number else 'Kosteninformation')
        monthly = MIFID_COST_SPARPLAN.search(text)
        annual = MIFID_COST_ANNUAL_SAVINGS.search(text)
        monthly_savings = money(monthly.group('amount')) if monthly else None
        annual_savings = money(annual.group('amount')) if annual else None
        if monthly_savings is not None and annual_savings is not None:
            expected = Decimal(monthly_savings) * 12
            if abs(expected - Decimal(annual_savings)) > Decimal('0.01'):
                raise ValueError(
                    f'MiFID-II-Kosteninformation: Sparbetrag monatlich {monthly_savings} EUR × 12 '
                    f'ergibt nicht den Jahresbetrag {annual_savings} EUR.')
        venue = MIFID_COST_VENUE.search(text)
        currency = MIFID_COST_CURRENCY.search(text)
        customer = MIFID_COST_CUSTOMER.search(text)
        years_match = MIFID_COST_YEARS.search(text)
        assumed_years = int(years_match.group('years')) if years_match else 0
        holding_years = int(years_match.group('holding')) if years_match else 0

        phase_totals, items = _mifid_cost_components(text, security_ref)
        details = {}
        percentages = {}
        for field_name, (label, with_percentage) in MIFID_COST_DETAILS.items():
            value, percentage = _mifid_detail(text, label, with_percentage)
            details[field_name] = value
            percentages[field_name] = percentage
        total_costs = money(total_row.group('amount'))
        total_pct = money(total_row.group('pct'))
        if total_costs is None or total_pct is None:
            raise ValueError('MiFID-II-Kosteninformation: Gesamtkosten oder Renditewirkung ungültig.')

        category_fields = ('service_costs', 'overhead_costs', 'product_costs')
        if all(details[name] is not None for name in category_fields):
            calculated = sum((Decimal(details[name]) for name in category_fields), Decimal('0'))
            if abs(calculated - Decimal(total_costs)) > Decimal('0.01'):
                raise ValueError(
                    f'MiFID-II-Gesamtkosten widersprüchlich: Kategorien {calculated:.2f} EUR, '
                    f'gedruckt {Decimal(total_costs):.2f} EUR.')

        external_id = 'pdf-cost-mifid-' + digest([
            account, document.file_hash, document_date, wkn, isin, reference,
            total_costs, total_pct])
        batch.cost_reports.append(CostReport(
            external_id=external_id,
            account=account,
            period_start=document_date,
            period_end=_mifid_period_end(document_date, assumed_years),
            currency=currency.group('currency') if currency else 'EUR',
            items=items,
            overhead_costs=details['overhead_costs'],
            total_costs=total_costs,
            ongoing_pct=total_pct,
            document_date=document_date,
            document_time=document_time,
            reference=reference,
            sparplan_number=sparplan_number,
            security_name=security_name,
            wkn=wkn,
            isin=isin,
            execution_venue=' '.join(venue.group('venue').split()) if venue else '',
            customer_number=' '.join(customer.group('number').split()) if customer else '',
            monthly_savings=monthly_savings,
            annual_savings=annual_savings,
            purchase_costs=phase_totals.get('kauf'),
            holding_costs=phase_totals.get('haltedauer'),
            sale_costs=phase_totals.get('verkauf'),
            service_costs=details['service_costs'],
            service_pct=percentages['service_costs'],
            product_costs=details['product_costs'],
            product_pct=percentages['product_costs'],
            foreign_pct=percentages['overhead_costs'],
            inducements=details['inducements'],
            assumed_years=str(assumed_years) if assumed_years else '',
            holding_years=str(holding_years) if holding_years else '',
            annual_projection=_mifid_cost_projection(text),
            information_type=_mifid_information_type(text)))

        document_title = (f'{document.path.name} · MiFID-II-Kosteninformation – '
                          'keine ausgeführte Transaktion')
        batch.documents.append(BankDocument(
            account=account,
            external_id=batch.file_hash + ':' + account,
            title=document_title,
            date=document_date,
            content_b64=base64.b64encode(document.content).decode('ascii'),
            document_type='comdirect MiFID-II-Kosteninformation – keine ausgeführte Transaktion',
            bank_name='comdirect',
            document_no=reference,
            page_count=len(document.pages),
            extraction_method='OCR' if any(page.used_ocr for page in document.pages) else 'PDF-Text',
            linked_ids=[external_id]))
        if account not in batch.account_names:
            batch.account_names.append(account)
        batch.securities.append(SecurityInfo(
            key=security_ref,
            identifier_type='isin' if isin else 'wkn',
            isin=isin,
            wkn=wkn,
            name=security_name,
            quote_currency=currency.group('currency') if currency else 'EUR'))
        batch.warnings.append(
            'MiFID-II-Kosteninformation – keine ausgeführte Transaktion: Kostensimulation ohne '
            'Buchung, Cashflow, Salden- oder Depotveränderung; tatsächliche Gebühren nur aus '
            'Wertpapierabrechnungen.')
        if not isin:
            batch.warnings.append(
                f'Im Beleg ist keine ISIN ausgewiesen; Zuordnung über WKN {wkn} (keine ISIN geraten).')
        return batch

    def parse(self, document, detection, context):
        if detection.handler_id == 'kosteninformation_mifid_ii':
            return self._mifid_cost_information(document, context.batch)
        if detection.handler_id == 'investment_ausschuettung':
            return self._investment_distribution_tax(document, context.batch)
        if detection.handler_id == 'dividende_steuer_inland':
            return self._dividend_tax(document, context.batch)
        if detection.handler_id == 'vorabpauschale':
            return self._advance_tax(document, context.batch)
        if detection.handler_id in ('wertpapierkauf', 'wertpapierverkauf'):
            return self._trade(document, context.batch, context.options)
        handler = HANDLERS.get(detection.handler_id)
        if handler is None:
            raise ValueError('Nicht unterstützter Dokumenttyp: ' + detection.handler_id)
        batch = context.batch
        text = document.text

        located = [(page, match) for page in document.pages for match in SETTLEMENT.finditer(page.text)]
        if len(located) != 1:
            raise ValueError('Genau eine Gutschrift pro PDF erwartet, gefunden: %d.' % len(located))
        page, settle = located[0]
        account = 'IBAN ' + re.sub(r'\s+', '', settle.group('iban'))

        holding, per_line = HOLDING.search(text), PER_LINE.search(text)
        isin_match = ISIN.search(holding.group('rest')) if holding else None
        isin = isin_match.group() if isin_match else None
        qty = correction_number(holding.group('qty')) if holding else None
        native_isin, native_qty = isin, qty        # nur diese gehen in die stabile external_id
        from_ocr, ocr_confidence = [], None
        if isin is None or qty is None:
            found, ocr_text, problem = ocr_holding(document, page, context.options)
            if problem:
                batch.warnings.append(problem)
            if isin is None and 'isin' in found:
                isin, ocr_confidence = found['isin'][0], found['isin'][1]
                from_ocr.append('ISIN')
            if qty is None and 'qty' in found:
                if plausible(found['qty'][0], text + '\n' + ocr_text) is False:
                    batch.warnings.append('OCR-Stückzahl %s passt nicht zum Betrag und wurde verworfen.' % found['qty'][0])
                else:
                    qty = found['qty'][0]
                    ocr_confidence = min(ocr_confidence or 1.0, found['qty'][1])
                    from_ocr.append('Stückzahl')
        if per_line:
            name, wkn = split_name_wkn(per_line.group('rest'))
        else:
            names = [m.group(1) for key in ('per', 'stk') for m in [NAME_AFTER_GAP[key].search(text)] if m]
            name, wkn = ' '.join(' '.join(names).split()), ''
        missing = [label for label, value in (('ISIN', isin), ('Stückzahl', qty)) if value is None]
        if missing and handler['kind'] == DIVIDEND_KIND:
            raise ValueError(' und '.join(missing) + ' im PDF nicht lesbar (defekte Schriftkodierung?) und per OCR '
                             'nicht sicher erkannt. Bitte Buchung manuell erfassen.')

        booked = parse_date(settle.group('date'))
        amount = money(settle.group('amount'))
        if not booked or amount is None:
            raise ValueError('Datum oder Betrag ungültig.')
        reference = re.search(
            r'(?:Referenz(?:-Nr\.)?|Vorgangs(?:nummer|-Nr\.)?)\s*:?\s*([A-Z0-9][A-Z0-9 /._-]*)',
            text, re.I)
        reference = ' '.join(reference.group(1).split()) if reference else ''

        purpose = f"{handler['title']}: {name}".rstrip(': ')
        purpose += (f" ({isin}" + (f', WKN {wkn}' if wkn else '') + ')') if isin else ' (Wertpapier-ID nicht lesbar)'
        purpose += f' {qty} Stk.' if qty is not None else ' (Stückzahl nicht lesbar)'
        foreign = FOREIGN.search(text)
        if foreign and foreign.group('currency') != settle.group('currency'):
            purpose += f" · {foreign.group('amount')} {foreign.group('currency')} umgerechnet"

        row = page.text[:settle.start()].count('\n') + 1
        source_line = ' '.join(settle.group().split())
        external_id = 'pdf-income-' + digest(
            [account, detection.handler_id, native_isin or name, booked, amount, native_qty, reference])

        # Zusatzfelder nach dem erweiterten Modell
        gross_basis = handler['kind'] == DIVIDEND_KIND          # comdirect weist den Betrag vor Steuern aus
        per_share = PER_SHARE.search(text)
        pay = PAY_DATE.search(text)
        fx = FX_PAIR.search(text)
        original_amount = original_currency = fx_rate = None
        if foreign and foreign.group('currency') != settle.group('currency') and fx:
            original_amount, original_currency = money(foreign.group('amount')), foreign.group('currency')
            fx_rate = correction_number(fx.group('rate'))
        sources = {}
        if 'ISIN' in from_ocr:
            sources['security'] = f'ocr:{ocr_confidence:.2f}'
        if 'Stückzahl' in from_ocr:
            sources['quantity'] = f'ocr:{ocr_confidence:.2f}'
        if page.used_ocr:
            sources.update({name: 'ocr' for name in ('amount', 'date')})

        batch.transactions.append(BankTransaction(
            account=account, external_id=external_id, date=booked, kind=handler['kind'],
            amount=amount, currency=settle.group('currency'),
            security=isin or '', quantity=qty, row=row,
            value_date=booked, purpose=purpose, bank_reference=reference,
            document_reference=reference,
            booking_text=handler['title'], raw_text=source_line,
            gross_amount=amount, original_amount=original_amount, original_currency=original_currency or '',
            fx_rate=fx_rate, security_ref=isin or '', income_basis='gross' if gross_basis else 'net',
            pay_date=parse_date(pay.group('d')) if pay else (booked if gross_basis else ''),
            per_share_amount=correction_number(per_share.group('r')) if per_share else None,
            per_share_currency=per_share.group('c') if per_share else '',
            fiscal_period_start=short_date(per_share.group('a')) if per_share else '',
            fiscal_period_end=short_date(per_share.group('b')) if per_share else '',
            field_sources=sources))
        if isin:
            domicile = DOMICILE.search(text)
            batch.securities.append(SecurityInfo(
                key=isin, isin=isin, wkn=wkn, name=name,
                domicile=domicile.group('c').title() if domicile else '',
                quote_currency=original_currency or settle.group('currency')))
        review = page.used_ocr or bool(from_ocr) or bool(missing)
        batch.pdf_booking_evidence.append({
            'page': page.number, 'line': row, 'text': source_line,
            'ocr': page.used_ocr or bool(from_ocr), 'review_required': review,
            'confidence': ocr_confidence if from_ocr else page.confidence})

        document_date = re.search(r'(?m)^[ \t]*(\d{2}\.\d{2}\.\d{4})[ \t]*$', text)
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name,
            parse_date(document_date.group(1)) if document_date else booked,
            base64.b64encode(document.content).decode('ascii')))

        batch.warnings.append('Betrag ist die Gutschrift vor Steuern; Steuerabzug steht in der separaten Steuermitteilung.')
        if from_ocr:
            batch.warnings.append(' und '.join(from_ocr) + ' per OCR ergänzt (defekte Schrift im PDF); '
                                  'bitte am Original prüfen.')
        if missing:
            batch.warnings.append(' und '.join(missing) + (' ist' if len(missing) == 1 else ' sind')
                                  + ' in diesem PDF nicht lesbar; übrige Felder wurden übernommen. Bitte am Original prüfen.')
        if page.used_ocr:
            batch.warnings.append('Seite per OCR gelesen; Betrag, Stückzahl und ISIN bitte am Original prüfen.')
        return batch

    def _dividend_tax(self, document, batch):
        compact = re.sub(r'\s+', '', document.text)
        title = DIVIDEND_TAX_TITLE.search(compact)
        security = DIVIDEND_TAX_SECURITY.search(compact)
        gross = INVESTMENT_TAX_GROSS.search(compact)
        # A notice can print the post-offset basis on page one and the
        # economically relevant pre-loss basis in the detailed block later.
        # Prefer the explicitly labelled pre-loss value; never infer it from
        # gross income or a tax rate.
        taxable = (INVESTMENT_TAX_TAXABLE_BEFORE.search(compact)
                   or INVESTMENT_TAX_TAXABLE.search(compact))
        used = DIVIDEND_TAX_USED.search(compact)
        after = DIVIDEND_TAX_AFTER.search(compact)
        paid = INVESTMENT_TAX_PAID.search(compact)
        net = INVESTMENT_TAX_NET.search(compact)
        settlement = INVESTMENT_TAX_SETTLEMENT.search(compact)
        depot = INVESTMENT_TAX_DEPOT.search(compact)
        reference = INVESTMENT_TAX_REFERENCE.search(compact)
        required = (title, security, gross, taxable, used, after, paid, net, settlement, depot, reference)
        if not all(required):
            raise ValueError('Inländische Dividende oder belegte Steuerfelder nicht vollständig erkannt.')
        values = {name: money(match.group('a')) for name, match in (
            ('gross', gross), ('taxable', taxable), ('used', used), ('after', after),
            ('paid', paid), ('net', net))}
        if any(value is None for value in values.values()):
            raise ValueError('Ein Betrag der Dividenden-Steuermitteilung ist ungültig.')
        if abs(Decimal(values['gross']) - Decimal(values['paid']) - Decimal(values['net'])) > Decimal('0.01'):
            raise ValueError('Bruttodividende minus Gesamtsteuer passt nicht zur Nettoauszahlung.')
        if Decimal(values['used']) > Decimal(values['taxable']):
            raise ValueError('Freistellungsauftrag übersteigt die Steuerbemessungsgrundlage.')
        components = {name: money(match.group('a')) for name, pattern in INVESTMENT_TAX_COMPONENTS.items()
                      for match in [pattern.search(compact)] if match}
        if set(components) != {'capital_gains_tax', 'solidarity_surcharge', 'church_tax'}:
            raise ValueError('Steuerkomponenten der Dividende nicht vollständig erkannt.')
        if abs(sum((Decimal(value) for value in components.values()), Decimal())
               - Decimal(values['paid'])) > Decimal('0.01'):
            raise ValueError('Steuerkomponenten passen nicht zur Summe der abgeführten Steuern.')
        treatment_date = parse_date(title.group('date'))
        value_date = parse_date(settlement.group('date'))
        document_date_match = INVESTMENT_TAX_DOCUMENT_DATE.search(compact)
        document_date = parse_date(document_date_match.group('d')) if document_date_match else treatment_date
        if not treatment_date or not value_date:
            raise ValueError('Datum oder Valuta der Dividenden-Steuermitteilung ist ungültig.')
        isin, wkn = security.group('isin').upper(), security.group('wkn').upper()
        qty = correction_number(security.group('qty'))
        name = ' '.join(security.group('name').split())
        depot_account = 'Depot ' + depot.group('n')
        cash_account = 'IBAN ' + settlement.group('iban')
        reference_no = reference.group('r')
        event_id = 'pdf-comdirect-dividend-tax-' + digest(
            [depot_account, isin, treatment_date, values['gross'], values['paid'], reference_no])
        batch.tax_events.append(TaxEvent(
            external_id=event_id, account=depot_account, type='dividende_inland', date=treatment_date,
            tax_year=treatment_date[:4], income_year=treatment_date[:4], document_date=document_date,
            security_ref=isin, quantity=qty, currency='EUR', gross_income=values['gross'],
            taxable_income=values['taxable'],
            used_exemption=values['used'], after_partial_exemption=values['after'],
            capital_gains_tax=components['capital_gains_tax'],
            solidarity_surcharge=components['solidarity_surcharge'],
            church_tax=components['church_tax'], paid_taxes=values['paid'],
            reference_no=reference_no, related_transaction_id='', cash_account=cash_account))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=name, quote_currency='EUR'))
        batch.documents.append(BankDocument(
            depot_account, batch.file_hash + ':' + depot_account, document.path.name, document_date,
            base64.b64encode(document.content).decode('ascii'),
            document_type='Steuermitteilung Dividende', bank_name='comdirect',
            document_no=reference_no, page_count=len(document.pages), extraction_method='PDF-Text',
            linked_ids=[event_id]))
        batch.account_names.extend([depot_account, cash_account])
        batch.warnings.append(
            f'Separate Dividenden-Steuermitteilung: Brutto {values["gross"]} EUR, '
            f'Steuer {values["paid"]} EUR, Netto {values["net"]} EUR. Keine zweite Dividende erzeugt.')
        return batch

    def _investment_distribution_tax(self, document, batch):
        text = document.text
        compact = re.sub(r'\s+', '', text)
        title = INVESTMENT_TAX_TITLE.search(compact)
        security = INVESTMENT_TAX_SECURITY.search(compact)
        gross = INVESTMENT_TAX_GROSS.search(compact)
        partial = INVESTMENT_TAX_PARTIAL.search(compact)
        # Page one may contain the basis after offsets while the detailed
        # block prints the source value before loss offset/FSA.
        taxable = (INVESTMENT_TAX_TAXABLE_BEFORE.search(compact)
                   or INVESTMENT_TAX_TAXABLE.search(compact))
        paid = INVESTMENT_TAX_PAID.search(compact)
        net = INVESTMENT_TAX_NET.search(compact)
        settlement = INVESTMENT_TAX_SETTLEMENT.search(compact)
        depot = INVESTMENT_TAX_DEPOT.search(compact)
        reference = INVESTMENT_TAX_REFERENCE.search(compact)
        if not all((title, security, gross, taxable, paid, net, settlement, reference)):
            raise ValueError('Investment-Ausschüttung, Wertpapier, Steuerbasis, Steuern oder Gutschrift nicht vollständig erkannt.')

        treatment_date = parse_date(title.group('date'))
        value_date = parse_date(settlement.group('date'))
        document_date_match = INVESTMENT_TAX_DOCUMENT_DATE.search(compact)
        document_date = parse_date(document_date_match.group('d')) if document_date_match else treatment_date
        values = {key: money(match.group('a')) for key, match in (
            ('gross', gross), ('taxable', taxable), ('paid', paid), ('net', net))}
        values['partial'] = money(partial.group('a')) if partial else None
        required_values = ('gross', 'taxable', 'paid', 'net')
        if (not treatment_date or not value_date
                or any(values[name] is None for name in required_values)):
            raise ValueError('Datum oder Betrag der Investment-Ausschüttung ist ungültig.')
        if (values['partial'] is not None
                and abs(Decimal(values['gross']) - Decimal(values['partial'])
                        - Decimal(values['taxable'])) > Decimal('0.01')):
            # The notice itself allows differences caused by the tax basis,
            # loss-offset rules and accumulated deemed distributions.  Keep
            # every printed value and flag the discrepancy instead of
            # manufacturing an adjustment amount.
            batch.warnings.append(
                'Bruttoausschüttung minus Teilfreistellung weicht von der ausgewiesenen '
                'Steuerbemessungsgrundlage ab; Originalwerte unverändert übernommen, '
                'keine Ausgleichsbuchung erzeugt.')
        if abs(Decimal(values['gross']) - Decimal(values['paid']) - Decimal(values['net'])) > Decimal('0.01'):
            raise ValueError('Bruttoausschüttung minus Gesamtsteuer passt nicht zur Nettoauszahlung.')

        components = {name: money(match.group('a')) for name, pattern in INVESTMENT_TAX_COMPONENTS.items()
                      for match in [pattern.search(compact)] if match}
        if not components:
            raise ValueError('Keine Steuerkomponenten der Investment-Ausschüttung erkannt.')
        component_total = sum((Decimal(value) for value in components.values()), Decimal())
        if abs(component_total - Decimal(values['paid'])) > Decimal('0.01'):
            raise ValueError('Kapitalertragsteuer, Solidaritätszuschlag und Kirchensteuer passen nicht zur Gesamtsteuer.')

        isin, wkn = security.group('isin').upper(), security.group('wkn').upper()
        qty = correction_number(security.group('qty'))
        name = ' '.join(security.group('name').split())
        depot_account = 'Depot ' + depot.group('n') if depot else 'comdirect Depot'
        cash_account = 'IBAN ' + settlement.group('iban')
        reference_no = reference.group('r')
        origin = 'inland' if title.group('origin').lower().startswith('inl') else 'ausland'
        event_id = 'pdf-comdirect-investment-distribution-tax-' + digest(
            [depot_account, isin, treatment_date, values['gross'], values['paid'], reference_no])
        payment_id = event_id + '-payment' if Decimal(values['paid']) else ''
        used_match = INVESTMENT_TAX_USED.search(compact)
        after_match = INVESTMENT_TAX_AFTER.search(compact)
        used_exemption = money(used_match.group('a')) if used_match else None
        after_offset = money(after_match.group('a')) if after_match else None
        loss_offset = None
        if used_exemption is not None and after_offset is not None:
            calculated = (Decimal(values['taxable']) - Decimal(used_exemption)
                          - Decimal(after_offset))
            if calculated < Decimal('-0.01'):
                raise ValueError('Freistellungsauftrag und Steuerbemessungsgrundlagen widersprechen sich.')
            loss_offset = f'{max(calculated, Decimal()):.2f}'
        batch.tax_events.append(TaxEvent(
            external_id=event_id, account=depot_account,
            type='investment_ausschuettung_' + origin, date=treatment_date,
            tax_year=treatment_date[:4], income_year=treatment_date[:4], document_date=document_date,
            security_ref=isin, quantity=qty, currency='EUR', gross_income=values['gross'],
            taxable_income=values['taxable'],
            partial_exemption_amount=values['partial'], after_partial_exemption=values['taxable'],
            partial_exemption_rate=(correction_number(partial.group('rate')) if partial else None),
            used_exemption=used_exemption, loss_offset=loss_offset,
            capital_gains_tax=components.get('capital_gains_tax'),
            solidarity_surcharge=components.get('solidarity_surcharge'),
            church_tax=components.get('church_tax'), paid_taxes=values['paid'],
            reference_no=reference_no, related_transaction_id=payment_id, cash_account=cash_account))
        if payment_id:
            tax_items = [TaxItem(kind, components[key]) for kind, key in (
                ('kapitalertragsteuer', 'capital_gains_tax'),
                ('solidaritaetszuschlag', 'solidarity_surcharge'),
                ('kirchensteuer', 'church_tax')) if key in components]
            batch.transactions.append(BankTransaction(
                account=cash_account, external_id=payment_id, date=treatment_date, value_date=value_date,
                kind=Kind.TAX, amount='-' + values['paid'], currency='EUR', security=isin,
                taxes=values['paid'], tax_items=tax_items, cash_account=cash_account,
                depot_account=depot_account, performance_depot_key=account_key(depot_account),
                security_ref=isin, affects_cash=False, bank_reference=reference_no,
                document_reference=reference_no, transaction_reference=reference_no,
                booking_text='comdirect Steuerabzug Investment-Ausschüttung',
                purpose=f'Steuerabzug Investment-Ausschüttung · {name}',
                raw_text=f'Brutto {values["gross"]} EUR · Steuern {values["paid"]} EUR · Netto {values["net"]} EUR',
                field_sources={'taxes': 'comdirect Steuermitteilung · abgeführte Steuern',
                               'value_date': 'comdirect Steuermitteilung · Valuta',
                               'security': 'comdirect Steuermitteilung · WKN/ISIN'}))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=name, quote_currency='EUR'))
        batch.documents.append(BankDocument(
            depot_account, batch.file_hash + ':' + depot_account, document.path.name, document_date,
            base64.b64encode(document.content).decode('ascii'),
            document_type='Steuermitteilung Investment-Ausschüttung', bank_name='comdirect',
            document_no=reference_no, page_count=len(document.pages), extraction_method='PDF-Text',
            linked_ids=[event_id, *([payment_id] if payment_id else [])]))
        batch.account_names.extend([depot_account, cash_account])
        batch.warnings.append(
            f'Separate Steuermitteilung: Brutto {values["gross"]} EUR, Steuer {values["paid"]} EUR, '
            f'Netto {values["net"]} EUR. Keine zweite Ausschüttung erzeugt.')
        return batch

    def _advance_tax(self, document, batch):
        text = document.text
        title, security = ADVANCE_TAX_TITLE.search(text), ADVANCE_TAX_SECURITY.search(text)
        base, partial = ADVANCE_TAX_BASE.search(text), ADVANCE_TAX_PARTIAL.search(text)
        taxable, used = ADVANCE_TAX_TAXABLE.search(text), ADVANCE_TAX_USED.search(text)
        after = ADVANCE_TAX_AFTER.search(text)
        if not all((title, security, base, partial, taxable, used)):
            raise ValueError('Vorabpauschale, Teilfreistellung, Steuerbemessungsgrundlage oder Freistellungsnutzung nicht erkannt.')
        treatment_date = parse_date(title.group('date'))
        values = {name: money(match.group('a')) for name, match in
                  (('base', base), ('partial', partial), ('taxable', taxable), ('used', used))}
        if not treatment_date or any(value is None for value in values.values()):
            raise ValueError('Datum oder Steuerbetrag der Vorabpauschale ist ungültig.')
        if abs(Decimal(values['base']) - Decimal(values['partial']) - Decimal(values['taxable'])) > Decimal('0.01'):
            raise ValueError('Vorabpauschale minus Teilfreistellung passt nicht zur Steuerbemessungsgrundlage.')
        if Decimal(values['used']) > Decimal(values['taxable']):
            raise ValueError('Der verbrauchte Freistellungsauftrag übersteigt die Steuerbemessungsgrundlage.')
        after_value = money(after.group('a')) if after else None
        loss_offset = (Decimal(values['taxable']) - Decimal(values['used']) - Decimal(after_value or '0'))
        if loss_offset < Decimal('-0.01'):
            raise ValueError('Freistellungsauftrag, Verlustverrechnung und verbleibende Steuerbasis widersprechen sich.')

        components = {name: money(match.group('a')) for name, pattern in ADVANCE_TAX_COMPONENTS.items()
                      for match in [pattern.search(text)] if match}
        paid_match = ADVANCE_TAX_PAID.search(text)
        paid_taxes = money(paid_match.group('a')) if paid_match else None
        if paid_taxes is not None and components:
            component_total = sum((Decimal(value) for value in components.values()), Decimal())
            if abs(component_total - Decimal(paid_taxes)) > Decimal('0.01'):
                raise ValueError('Kapitalertragsteuer, Solidaritätszuschlag und Kirchensteuer passen nicht '
                                 'zur Summe der abgeführten Steuern.')

        isin, wkn = security.group('isin').upper(), security.group('wkn').upper()
        qty = correction_number(security.group('qty'))
        name = ' '.join(security.group('name').split())
        depot_match = ADVANCE_TAX_DEPOT.search(text)
        depot_number = re.sub(r'\s+', '', depot_match.group('n')) if depot_match else ''
        account = 'Depot ' + depot_number if depot_number else 'comdirect Depot'
        reference_match = ADVANCE_TAX_REFERENCE.search(text)
        reference = re.sub(r'\s+', '', reference_match.group('r')) if reference_match else ''
        document_date_match = ADVANCE_TAX_DOCUMENT_DATE.search(text)
        document_date = parse_date(document_date_match.group('d')) if document_date_match else treatment_date
        income_year = str(int(treatment_date[:4]) - 1)
        settlement = ADVANCE_TAX_SETTLEMENT.search(text)
        cash_account = ('IBAN ' + re.sub(r'\s+', '', settlement.group('iban'))) if settlement else ''
        balances = _advance_tax_balances(document)
        external_id = 'pdf-comdirect-advance-tax-' + digest(
            [account, isin, income_year, treatment_date, values['base'], values['taxable'], reference])
        related_transaction_id = external_id + '-payment' if paid_taxes and Decimal(paid_taxes) else ''
        batch.tax_events.append(TaxEvent(
            external_id=external_id, account=account, type='vorabpauschale_ausland',
            date=treatment_date, tax_year=treatment_date[:4], income_year=income_year,
            document_date=document_date, security_ref=isin, quantity=qty,
            currency='EUR', taxable_income=values['taxable'], advance_tax_base=values['base'],
            partial_exemption_amount=values['partial'], used_exemption=values['used'],
            loss_offset=f'{max(loss_offset, Decimal()):.2f}',
            capital_gains_tax=components.get('capital_gains_tax'),
            solidarity_surcharge=components.get('solidarity_surcharge'),
            church_tax=components.get('church_tax'), paid_taxes=paid_taxes,
            **balances,
            after_partial_exemption=values['taxable'],
            partial_exemption_rate=correction_number(partial.group('rate')),
            reference_no=reference, related_transaction_id=related_transaction_id,
            cash_account=cash_account))
        if related_transaction_id:
            if not cash_account:
                raise ValueError('Steuerbelastung erkannt, aber das belastete Verrechnungskonto ist nicht lesbar.')
            paid_day = parse_date(settlement.group('d'))
            batch.transactions.append(BankTransaction(
                account=cash_account, external_id=related_transaction_id, date=paid_day,
                value_date=paid_day, kind=Kind.TAX, amount='-' + paid_taxes, currency='EUR',
                security=isin, taxes=paid_taxes,
                tax_items=[TaxItem(name, value) for name, value in (
                    ('kapitalertragsteuer', components.get('capital_gains_tax')),
                    ('solidaritaetszuschlag', components.get('solidarity_surcharge')),
                    ('kirchensteuer', components.get('church_tax'))) if value is not None],
                cash_account=cash_account, depot_account=account, performance_depot_key='',
                security_ref=isin, affects_cash=True, bank_reference=reference,
                document_reference=reference, transaction_reference=reference,
                booking_text='comdirect Vorabpauschale Steuerbelastung',
                purpose=f'Vorabpauschale {income_year} · {name}'))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=name))
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name,
            document_date,
            base64.b64encode(document.content).decode('ascii'),
            document_type='Steuermitteilung Vorabpauschale', bank_name='comdirect',
            document_no=reference, page_count=len(document.pages), extraction_method='PDF-Text'))
        batch.account_names.append(account)
        batch.warnings.append(
            f"Vorabpauschale {values['base']} EUR erkannt; nach {partial.group('rate')} % Teilfreistellung "
            f"wurden {values['used']} EUR Freistellungsauftrag verbraucht. Keine Kontobuchung erzeugt.")
        return batch

    def _trade(self, document, batch, options=None):
        options = options or {}
        native_compact = re.sub(r'[ \t]+', '', document.text)
        needs_targeted_ocr = not all((TRADE_LINE.search(document.text) or TRADE_LINE.search(native_compact),
                                      TRADE_DAY.search(native_compact), TRADE_SETTLEMENT.search(native_compact),
                                      TRADE_TOTAL.search(native_compact), TRADE_DEPOT.search(native_compact),
                                      TRADE_MARKET.search(native_compact)))
        if needs_targeted_ocr:
            if not options.get('allow_ocr', True):
                raise ValueError('Beschädigte comdirect-Schrift erkannt; gezielte OCR ist deaktiviert.')
            from portfolio_v5.pdf_ocr import MIN_SAFE_CONFIDENCE, ocr_page
            pages = []
            for page in document.pages:
                recognized, confidence = ocr_page(document.path, page.number - 1)
                if not recognized.strip() or confidence is None or confidence < MIN_SAFE_CONFIDENCE:
                    raise ValueError(f'Gezielte OCR auf Seite {page.number} ist nicht sicher genug; '
                                     'Beleg bitte manuell prüfen.')
                pages.append(PdfPage(page.number, recognized, True, confidence))
            document = PdfDocument(document.path, document.content, document.file_hash, tuple(pages))
            batch.warnings.append('Beschädigte comdirect-Schrift erkannt; gezielte OCR nur für diese '
                                  'Wertpapierabrechnung verwendet. Alle Werte bitte am Original prüfen.')
        text = document.text
        compact = re.sub(r'[ \t]+', '', text)
        fee_matches = [(kind, pattern.search(compact)) for kind, pattern in TRADE_FEES.items()]
        fee_matches = [(kind, match) for kind, match in fee_matches if match]
        security = TRADE_LINE.search(text) or TRADE_LINE.search(compact)
        trade = TRADE_DAY.search(compact)
        settlement = TRADE_SETTLEMENT.search(compact)
        total = TRADE_TOTAL.search(compact)
        depot = TRADE_DEPOT.search(compact)
        if not all((security, trade, settlement, total, depot)):
            raise ValueError('Wertpapier, Geschäftstag, Valuta, IBAN oder Endbetrag nicht erkannt.')
        trade_type = trade.group('type') or TRADE_MARKER.search(text).group('type')
        kind = Kind.BUY if trade_type.lower() == 'kauf' else Kind.SELL
        expected_direction = 'Lasten' if kind == Kind.BUY else 'Gunsten'
        if total.group('direction').lower() != expected_direction.lower():
            raise ValueError(f'Wirtschaftliche Zahlungsrichtung widerspricht {kind}: '
                             f"Zu Ihren {total.group('direction')} statt zu Ihren {expected_direction}.")
        valuta = parse_date(settlement.group('d') or settlement.group('d2'))
        iban = settlement.group('iban') or settlement.group('iban2')
        trade_day = parse_date(trade.group('d'))
        qty, price, execution_market, execution_page, quantity_source = _trade_quantity(document, security)
        amount = money(total.group('a'))
        if not all((valuta, trade_day, qty, amount)):
            raise ValueError('Betrag, Provision, Stückzahl oder Datum ungültig.')
        cash_account = 'IBAN ' + iban
        isin, wkn = security.group('isin').upper(), security.group('wkn').upper()
        name = ' '.join(security.group('name').split())
        reference = (TRADE_REFERENCE.search(compact).group('r')
                     if TRADE_REFERENCE.search(compact) else trade.group('order'))
        account = 'Depot ' + depot.group('n')
        market = TRADE_MARKET.search(compact)
        gross = execution_market or (money(market.group('a')) if market else None)
        tax_total_match = TRADE_TAX_TOTAL.search(compact)
        # A missing tax total is unknown.  Only a printed zero is evidence for
        # 0.00 EUR, and that distinction must survive the import unchanged.
        taxes = money(tax_total_match.group('a')) if tax_total_match else None
        tax_items = [TaxItem(name, money(match.group('a'))) for name, pattern in TRADE_TAX_ITEMS.items()
                     for match in [pattern.search(compact)] if match and Decimal(money(match.group('a'))) != 0]
        documented_tax_total = sum((Decimal(item.amount) for item in tax_items), Decimal())
        if tax_items and taxes is not None and abs(documented_tax_total - Decimal(taxes)) > Decimal('0.01'):
            raise ValueError('Steuerkomponenten passen nicht zur ausgewiesenen Steuersumme.')
        if fee_matches:
            fee_items = [FeeItem(kind, money(match.group('a'))) for kind, match in fee_matches]
            provision = money(sum((Decimal(item.amount) for item in fee_items), Decimal()))
        elif gross is not None:
            tax_value = Decimal(taxes or '0')
            provision_value = ((Decimal(amount) - Decimal(gross) - tax_value) if kind == Kind.BUY
                               else (Decimal(gross) - tax_value - Decimal(amount)))
            if provision_value < Decimal('-0.01'):
                raise ValueError('Kurswert, Steuern und Endbetrag widersprechen der Zahlungsrichtung.')
            provision = money(max(provision_value, Decimal()))
            fee_items = [FeeItem('entgelt', provision)]
        else:
            provision = None
            fee_items = []
        expected_total = (Decimal(gross) + Decimal(provision) if kind == Kind.BUY
                          else Decimal(gross) - Decimal(provision)) if gross is not None and provision is not None else None
        if expected_total is not None:
            tax_value = Decimal(taxes or '0')
            expected_total = (expected_total + tax_value if kind == Kind.BUY
                              else expected_total - tax_value)
        if expected_total is not None and abs(expected_total - Decimal(amount)) > Decimal('0.01'):
            batch.warnings.append('Kurswert, Provision und Endbetrag stimmen nicht überein; Abrechnung bitte prüfen.')
        booking_text = f'{name}\nWPKNR: {wkn} ISIN: {isin}'
        purpose = f'Wertpapiere · {name} · WPKNR: {wkn} ISIN: {isin}'
        if provision and Decimal(provision):
            purpose += f' · Provision {provision} EUR'
        # Keep the historical BUY identity stable across the model correction
        # from cash booking to depot event; otherwise a re-import after upgrade
        # could create a second economic transaction.
        external_id = 'pdf-comdirect-trade-' + digest(
            [cash_account, trade.group('order'), isin, trade_day, valuta, amount])
        batch.transactions.append(BankTransaction(
            account=account, external_id=external_id, date=trade_day, value_date=valuta,
            kind=kind, amount=('-' if kind == Kind.BUY else '') + amount, currency='EUR', security=isin,
            quantity=qty, fees=provision,
            taxes=taxes,
            fee_items=fee_items,
            tax_items=tax_items,
            gross_amount=gross, price=price, trade_date=trade_day, pay_date=valuta,
            cash_account=cash_account, depot_account=account, affects_cash=False,
            security_ref=isin, order_id=trade.group('order'), document_reference=reference,
            transaction_reference=reference, operation='Wertpapiere', booking_text=booking_text,
            purpose=purpose, raw_text=purpose,
            field_sources={'fees': 'comdirect Wertpapierabrechnung · Provision',
                           **({'taxes': 'comdirect Wertpapierabrechnung · abgeführte Steuern'}
                              if tax_total_match else {}),
                           'quantity': quantity_source,
                           **({'price': 'comdirect Geschäftsabrechnung · Zum Kurs von'} if price else {}),
                           'security': 'comdirect Wertpapierabrechnung · WKN/ISIN',
                           'value_date': 'comdirect Wertpapierabrechnung · Valuta'}))
        batch.securities.append(SecurityInfo(key=isin, isin=isin, wkn=wkn, name=name, quote_currency='EUR'))
        page = (next((p for p in document.pages if p.number == execution_page), None) if execution_page else None)
        page = page or next((p for p in document.pages if TRADE_TOTAL.search(re.sub(r'[ \t]+', '', p.text))), document.pages[0])
        batch.pdf_booking_evidence.append({'page': page.number, 'line': 1, 'text': purpose,
            'ocr': page.used_ocr, 'confidence': page.confidence, 'review_required': page.used_ocr})
        batch.documents.append(BankDocument(
            account, batch.file_hash + ':' + account, document.path.name, trade_day,
            base64.b64encode(document.content).decode('ascii'), document_type='Wertpapierabrechnung ' + kind.title(),
            bank_name='comdirect', document_no=reference, page_count=len(document.pages),
            extraction_method='OCR' if page.used_ocr else 'PDF-Text', linked_ids=[external_id]))
        batch.account_names.extend([account, cash_account])
        batch.warnings.append(
            f'Gebühren {provision or "nicht ausgewiesen"} EUR; Zuordnung über Valuta, Betrag und WKN/ISIN.')
        return batch


plugin = ComdirectErtraegePlugin()
