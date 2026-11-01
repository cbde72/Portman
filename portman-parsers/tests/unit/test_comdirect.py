from decimal import Decimal
from pathlib import Path
from portman_parsers.api import PdfDocument, PdfPage
from portman_parsers.plugins import ComdirectFinanzreportPlugin, ComdirectPlugin

CASES={"dividendengutschrift":"Abrechnung Dividendengutschrift","ertragsgutschrift":"Abrechnung Ertragsgutschrift","einloesung":"Abrechnung Einlösung","kosteninformation_mifid_ii":"Kosteninformation zum Wertpapiergeschäft 10,00 EUR","investment_ausschuettung":"Steuerliche Behandlung: Ausländische Investment-Ausschüttung","dividende_steuer_inland":"Steuerliche Behandlung: Inländische Dividende","vorabpauschale":"Steuerliche Behandlung: Vorabpauschale Vorabpauschale EUR 10,00","wertpapierkauf":"Wertpapierkauf","wertpapierverkauf":"Wertpapierverkauf"}
def doc(text): return PdfDocument("doc","a"*64,(PdfPage(1,"comdirect\n"+text+"\nStk. 1,000 DE0008474511\nZu Ihren Gunsten EUR 10,00"),))
FIXTURES=Path(__file__).parents[1]/"fixtures"/"comdirect"
def golden(name): return PdfDocument("doc-"+name,"d"*64,(PdfPage(1,(FIXTURES/name).read_text(encoding="utf-8")),))
def test_all_nine_security_handlers_detect_and_parse():
 for handler,text in CASES.items():
  plugin=ComdirectPlugin(); source=doc(text); detection=plugin.detect(source)[0]; result=plugin.parse(source,detection)
  assert detection.handler_id==handler; assert result.evidence
  if handler=="kosteninformation_mifid_ii": assert not result.events[0].cash_movements
  if handler=="vorabpauschale": assert not result.events[0].cash_movements
def test_trade_without_iban_is_expected_not_actual():
 plugin=ComdirectPlugin(); source=doc("Wertpapierkauf"); result=plugin.parse(source,plugin.detect(source)[0])
 assert result.events[0].cash_movements[0].status.value=="EXPECTED"; assert not result.accounts
def test_finanzreport_handler_is_executable():
 source=doc("Finanzreport Nr. 1"); plugin=ComdirectFinanzreportPlugin(); result=plugin.parse(source,plugin.detect(source)[0])
 assert result.handler_id=="finanzreport"; assert result.evidence

def test_finanzreport_parses_account_bookings_and_balances():
 text="""comdirect\nFinanzreport Nr. 7\nGirokonto DE00 0000 0000 0000 0000 01
Alter Saldo 01.01.2026 100,00
02.01.2026 02.01.2026 Gutschrift +10,00
03.01.2026 03.01.2026 Lastschrift -5,00
Neuer Saldo 31.01.2026 105,00"""
 source=PdfDocument("report","b"*64,(PdfPage(1,text),)); plugin=ComdirectFinanzreportPlugin(); result=plugin.parse(source,plugin.detect(source)[0])
 assert len(result.accounts)==1; assert len(result.events)==2; assert not result.issues
 assert result.account_balances[-1].amount.value==105

def test_finanzreport_depot_is_snapshot_not_trade():
 text="""comdirect\nFinanzreport Nr. 8\nDepotnummer: 12345
DE0008474511 2,000 50,00 EUR 100,00 EUR 31.01.2026
Depotgesamtwert 100,00 EUR"""
 source=PdfDocument("depot-report","c"*64,(PdfPage(1,text),)); plugin=ComdirectFinanzreportPlugin(); result=plugin.parse(source,plugin.detect(source)[0])
 assert len(result.depot_snapshots)==1; assert not result.events

def test_ertragsgutschrift_golden_has_actual_net_and_taxes():
 source=golden("ertragsgutschrift.txt"); plugin=ComdirectPlugin(); result=plugin.parse(source,plugin.detect(source)[0]); event=result.events[0]
 assert result.handler_id=="ertragsgutschrift"; assert event.kind=="DIVIDEND"
 assert event.cash_movements[0].amount==Decimal("97.36"); assert event.cash_movements[0].status.value=="ACTUAL"
 assert [x.kind for x in event.tax_events[0].components]==["CAPITAL_GAINS_TAX","SOLIDARITY_SURCHARGE"]

def test_einloesung_golden_has_redemption_and_security_outflow():
 source=golden("einloesung.txt"); plugin=ComdirectPlugin(); result=plugin.parse(source,plugin.detect(source)[0]); event=result.events[0]
 assert event.kind=="REDEMPTION"; assert event.security_movements[0].quantity==Decimal("-1.000")
 assert event.cash_movements[0].amount==Decimal("100.00"); assert not result.issues

def test_buy_and_sell_goldens_preserve_direction_fees_and_tax():
 plugin=ComdirectPlugin()
 buy=plugin.parse(golden("kauf.txt"),plugin.detect(golden("kauf.txt"))[0]).events[0]
 sell=plugin.parse(golden("verkauf.txt"),plugin.detect(golden("verkauf.txt"))[0]).events[0]
 assert buy.cash_movements[0].amount==Decimal("-126.50"); assert buy.security_movements[0].quantity==Decimal("0.125")
 assert buy.fee_events[0].amount==Decimal("1.50")
 assert sell.cash_movements[0].amount==Decimal("121.00"); assert sell.security_movements[0].quantity==Decimal("-0.125")
 assert sell.tax_events[0].components[0].amount==Decimal("2.50")

def test_incomplete_trade_is_explicit_review_case():
 source=PdfDocument("broken","e"*64,(PdfPage(1,"comdirect\nWertpapierkauf"),)); plugin=ComdirectPlugin(); result=plugin.parse(source,plugin.detect(source)[0])
 assert {i.code for i in result.issues}=={"COMDIRECT_SECURITY_MISSING","COMDIRECT_QUANTITY_MISSING","COMDIRECT_SETTLEMENT_MISSING"}

def test_trade_details_and_evidenced_depot_account_link():
 text="""comdirect
Wertpapierkauf
Depotnummer: 12345
IBAN DE00 0000 0000 0000 0000 01
Wertpapierbezeichnung: Beispiel Fonds
WKN ABC123
ISIN DE0008474511
Stk. 0,125
Geschäftstag 01.02.2026
Ausführungstag 02.02.2026
Valuta 04.02.2026
Kurs EUR 1.000,00
Kurswert EUR 125,00
Provision EUR 1,50
Zu Ihren Lasten EUR 126,50"""
 source=PdfDocument("trade-details","f"*64,(PdfPage(1,text),)); plugin=ComdirectPlugin(); result=plugin.parse(source,plugin.detect(source)[0])
 trade=result.events[0].trades[0]
 assert trade.wkn=="ABC123" and trade.price==Decimal("1000.00") and trade.market_value==Decimal("125.00")
 assert trade.settlement_amount==Decimal("126.50")
 assert len(result.depot_account_links)==1 and result.depot_account_links[0].is_default.value is False

def test_mifid_components_are_informational_and_cash_neutral():
 source=doc("Kosteninformation zum Wertpapiergeschäft ex-post\nProduktkosten 10,00 EUR\nDienstleistungskosten 2,00 EUR\nTransaktionskosten 1,00 EUR")
 plugin=ComdirectPlugin(); result=plugin.parse(source,plugin.detect(source)[0]); event=result.events[0]
 assert [x.kind for x in event.cost_events]==["PRODUCT_COST","SERVICE_COST","TRANSACTION_COST"]
 assert all(x.informational and x.cash_movement_id is None for x in event.cost_events)
 assert not event.cash_movements

def test_advance_tax_has_calculation_and_never_cash_without_booking():
 text="""comdirect
Steuerliche Behandlung: Vorabpauschale
Depotnummer: 12345
ISIN DE0008474511
Vorabpauschale EUR 100,00
Steuerbemessungsgrundlage EUR 70,00
Teilfreistellung 30,00 %
Freistellungsauftrag EUR 20,00
Verlustverrechnung EUR 10,00
steuerlicher Zufluss 02.01.2026
Kapitalertragsteuer EUR 10,00
Solidaritätszuschlag EUR 0,55"""
 source=PdfDocument("advance","1"*64,(PdfPage(1,text),)); plugin=ComdirectPlugin(); result=plugin.parse(source,plugin.detect(source)[0])
 tax=result.events[0].tax_events[0]
 assert not result.events[0].cash_movements and tax.tax_year==2026
 assert tax.partial_exemption_rate==Decimal("0.30") and tax.actually_withheld_tax==Decimal("10.55")
 assert len(result.tax_calculations)==1 and len(result.tax_carryforwards)==1

def test_finanzreport_duplicate_booking_is_not_double_counted():
 text="""comdirect
Finanzreport Nr. 9
Zeitraum 01.01.2026 bis 31.01.2026
Girokonto DE00 0000 0000 0000 0000 01
Alter Saldo 01.01.2026 100,00
02.01.2026 02.01.2026 Gutschrift +10,00
02.01.2026 02.01.2026 Gutschrift +10,00
Neuer Saldo 31.01.2026 110,00"""
 source=PdfDocument("duplicate-report","2"*64,(PdfPage(1,text),)); plugin=ComdirectFinanzreportPlugin(); result=plugin.parse(source,plugin.detect(source)[0])
 assert len(result.events)==1 and any(x.code=="DUPLICATE_BOOKING" for x in result.issues)
 assert result.attributes["document_number"]=="9" and result.attributes["period_start"]=="01.01.2026"

def test_dividend_security_column_recognizes_wkn_isin_and_name():
 text = """comdirect
Gutschrift fälliger Wertpapier-Erträge
Dividendengutschrift
Depotbestand                          Wertpapier-Bezeichnung                WKN/ISIN
per 15.05.2024                        SAP SE                                  716460
STK               0,733               Inhaber-Aktien o.N.               DE0007164600
zahlbar ab 21.05.2024
Abrechnung Dividendengutschrift
Zu Ihren Gunsten EUR 1,61"""
 plugin=ComdirectPlugin(); source=PdfDocument("sap-dividend","b"*64,(PdfPage(1,text),))
 result=plugin.parse(source,plugin.detect(source)[0]); event=result.events[0]
 assert event.kind=="DIVIDEND" and not event.trades
 assert (event.security_name,event.security_wkn,event.security_isin)==("SAP SE Inhaber-Aktien o.N.","716460","DE0007164600")
 assert len(event.security_identity_evidence_ids)==3
 assert event.cash_movements[0].amount==Decimal("1.61")


def test_dividend_security_column_generalizes_to_alphanumeric_wkn():
 from portman_parsers.plugins.comdirect import extract_comdirect_security_identity
 text="""Wertpapier-Bezeichnung            WKN/ISIN
Beispiel MSCI ETF                  A0S9GB
Inhaber-Anteile                    DE000A0S9GB0"""
 assert extract_comdirect_security_identity(text)==("Beispiel MSCI ETF Inhaber-Anteile","A0S9GB","DE000A0S9GB0")


def test_dividend_security_column_does_not_pick_unrelated_six_digit_number():
 from portman_parsers.plugins.comdirect import extract_comdirect_security_identity
 text="""Konto 123456
Wertpapier-Bezeichnung            WKN/ISIN
Aktienfonds                       unbekannt
Inhaber-Anteile                    keine ISIN
Referenz 716460"""
 assert extract_comdirect_security_identity(text)==(None,None,None)


def test_dividend_identity_accepts_spaced_glyphs_and_variable_columns():
 from portman_parsers.plugins.comdirect import extract_comdirect_security_identity
 text="""Wertpapier-Bezeichnung   WKN/ISIN
per 01.02.2025  Example-ETF  A1B2C3
STK 1,000  I n h a b e r - A n t e i l e o . N .  DE000A1B2C35"""
 assert extract_comdirect_security_identity(text)==("Example-ETF Inhaber-Anteile o.N.","A1B2C3","DE000A1B2C35")


def test_dividend_identity_rejects_invalid_isin_checksum_and_reports_no_value():
 from portman_parsers.plugins.comdirect import _extract_comdirect_security_identity
 identity=_extract_comdirect_security_identity("""Wertpapier-Bezeichnung WKN/ISIN
per 01.02.2025 Generic Fund 123456
STK 1,000 Accumulating Shares DE000A1B2C34""")
 assert identity.status=="INVALID" and identity.isin is None


def test_dividend_identity_marks_multiple_identifiers_ambiguous():
 from portman_parsers.plugins.comdirect import _extract_comdirect_security_identity
 identity=_extract_comdirect_security_identity("""Wertpapier-Bezeichnung WKN/ISIN
per 01.02.2025 First Fund 123456
STK 1,000 First Shares DE000A1B2C35""")
 assert identity.status=="RECOGNIZED"
 identity=_extract_comdirect_security_identity("""Wertpapier-Bezeichnung WKN/ISIN
per 01.02.2025 First Fund 123456 654321
STK 1,000 First Shares DE000A1B2C30""")
 assert identity.status=="AMBIGUOUS"


def test_dividend_does_not_create_security_movement_for_identity_quantity():
 text="""comdirect
Dividendengutschrift
Wertpapier-Bezeichnung WKN/ISIN
per 01.02.2025 Example Fund 123456
STK 1,000 Shares DE000A1B2C30
Zu Ihren Gunsten EUR 1,00
Abrechnung Dividendengutschrift"""
 plugin=ComdirectPlugin(); source=PdfDocument("no-security-movement","c"*64,(PdfPage(1,text),))
 event=plugin.parse(source,plugin.detect(source)[0]).events[0]
 assert event.kind=="DIVIDEND" and not event.security_movements and not event.trades
