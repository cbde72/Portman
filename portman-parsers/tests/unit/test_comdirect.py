from decimal import Decimal
from pathlib import Path
from portman_parsers.api import MissingValue, PdfDocument, PdfPage
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

def test_buy_tax_treatment_section_creates_no_withholding():
 text="""comdirect
Wertpapierkauf
Zu Ihren Lasten vor Steuern
EUR 24,92
Steuerliche Behandlung: Wertpapierkauf Nr. 1 vom 07.01.2026
Stk. 0,006 TEST INDEX , WKN / ISIN: LS9AVX / DE000LS9AVX3
Steuerbemessungsgrundlage EUR 0,00
Kapitalertragsteuer EUR 0,00
Solidaritätszuschlag EUR 0,00
Kirchensteuer EUR 0,00
abgeführte Steuern EUR 0,00
Zu Ihren Lasten nach Steuern: EUR -24,92"""
 source=PdfDocument("buy-tax","f"*64,(PdfPage(1,text),)); plugin=ComdirectPlugin(); event=plugin.parse(source,plugin.detect(source)[0]).events[0]
 assert event.kind=="BUY"; assert not event.tax_events
 assert event.cash_movements[0].amount==Decimal("-24.92")

def test_tax_section_does_not_override_quantity_and_market_value():
 text="""comdirect
Wertpapierkauf
Nennwert Zum Kurs von St. 0,006 EUR 3.662,70 Kurswert : EUR 21,98
Zu Ihren Lasten vor Steuern EUR 21,98
Steuerliche Behandlung: Wertpapierkauf Nr. 1 vom 07.01.2026
Stk. 0,010 TEST INDEX , WKN / ISIN: LS9AVX / DE000LS9AVX3
Kurswert : EUR 99,99
Zu Ihren Lasten nach Steuern: EUR -21,98"""
 source=PdfDocument("buy-qty","1"*64,(PdfPage(1,text),)); plugin=ComdirectPlugin(); event=plugin.parse(source,plugin.detect(source)[0]).events[0]
 assert event.trades[0].quantity==Decimal("0.006"); assert event.security_movements[0].quantity==Decimal("0.006")
 assert event.trades[0].market_value==Decimal("21.98"); assert event.trades[0].price==Decimal("3662.70")

def test_tax_section_quantity_is_fallback_when_trade_part_is_unreadable():
 text="""comdirect
Wertpapierkauf
Nennwert Zum Kurs von
��� EUR ���
Steuerliche Behandlung: Wertpapierkauf Nr. 1 vom 07.01.2026
Stk. 0,212 TEST FONDS , WKN / ISIN: A2H57N / DE0008474511
Zu Ihren Lasten vor Steuern: EUR -49,89"""
 source=PdfDocument("buy-fallback","2"*64,(PdfPage(1,text),)); plugin=ComdirectPlugin(); event=plugin.parse(source,plugin.detect(source)[0]).events[0]
 assert event.trades[0].quantity==Decimal("0.212"); assert event.trades[0].market_value is MissingValue.NOT_FOUND

# Seite 1 mit Schrift ohne Unicode-Zuordnung (Zeichenfolgen aus echten Abrechnungen, ohne Personendaten)
CIPHER_GLYPHS={"z":("r","d"),"ü":("v","g")}
def cipher_buy(sp,day,number,qty,price,market,plain_day,plain_number,plain_qty,plain_market):
 colon,dot=CIPHER_GLYPHS[sp]
 return f"""comdirect
Wertpapierkauf
Geschäftsnummer{sp*3}{colon}{sp}{number[:2]}{sp}{number[2:]}
Geschäftstag{sp*6}{colon}{sp}{day}{sp*8}
Nennwert Zum Kurs von
St{dot}{sp}{qty}{sp*17}EUR{sp*2}{price}{sp*12}
{sp*26}Kurswert{sp*20}{colon}{sp}EUR{sp*15}{market}{sp*8}
Steuerliche Behandlung: Wertpapierkauf Nr. {plain_number} vom {plain_day}
Stk. {plain_qty} TEST WERTPAPIER , WKN / ISIN: LYX05A / LU2090063673
Zu Ihren Lasten vor Steuern: EUR -{plain_market}"""

def parse_text(text):
 source=PdfDocument("cipher-"+str(abs(hash(text))),"3"*64,(PdfPage(1,text),)); plugin=ComdirectPlugin(); return plugin.parse(source,plugin.detect(source)[0])

def test_cipher_page_z_variant_with_truncated_tax_quantity():
 result=parse_text(cipher_buy("z","fndfgdhfhm","pggohhoi","fbffm","kdglhbpg","hkbph","07.01.2026","91182283","0","24,92"))
 trade=result.events[0].trades[0]
 assert (trade.quantity,trade.price,trade.market_value)==(Decimal("0.006"),Decimal("4152.91"),Decimal("24.92"))
 assert "COMDIRECT_QUANTITY_MISSING" not in {i.code for i in result.issues}

def test_cipher_page_resolves_two_missing_digits_only_when_unique():
 trade=parse_text(cipher_buy("z","fpdfhdhfhm","pghfighh","fbffm","idpohblg","hibpf","09.02.2026","91203122","0","23,90")).events[0].trades[0]
 assert (trade.quantity,trade.price,trade.market_value)==(Decimal("0.006"),Decimal("3982.51"),Decimal("23.90"))

def test_cipher_page_u_variant():
 trade=parse_text(cipher_buy("ü","imgimgmimr","ulmrrsru","ierom","ssetr","oueuu","02.02.2026","91266769","0,642","49,99")).events[0].trades[0]
 assert (trade.quantity,trade.price,trade.market_value)==(Decimal("0.642"),Decimal("77.86"),Decimal("49.99"))

def test_cipher_page_is_rejected_when_quantity_times_price_mismatches():
 result=parse_text(cipher_buy("ü","imgimgmimr","ulmrrsru","ierom","sseur","oueuu","02.02.2026","91266769","0,642","49,99")); trade=result.events[0].trades[0]
 assert trade.price is MissingValue.NOT_FOUND and trade.market_value is MissingValue.NOT_FOUND
 assert trade.quantity==Decimal("0.642")
 assert "COMDIRECT_TRADE_VALUES_UNRESOLVED" in {i.code for i in result.issues}

def test_resolved_cipher_page_has_no_unresolved_issue():
 result=parse_text(cipher_buy("ü","imgimgmimr","ulmrrsru","ierom","ssetr","oueuu","02.02.2026","91266769","0,642","49,99"))
 assert "COMDIRECT_TRADE_VALUES_UNRESOLVED" not in {i.code for i in result.issues}

def test_cipher_page_does_not_guess_unknown_thousands_separator():
 # Ohne Datums-Anker ist der Punkt-Code unbekannt und passt rechnerisch als Ziffer 0 (10111,11 x 2 = 20222,22).
 # Das ist kein gültiges Zahlenformat; belegt ist nur 1.111,11 (über die Belastung ohne Entgelte).
 trade=parse_text(cipher_buy("z","fndfgdhfhm","pggohhoi","h","gdgggbgg","hdhhhbhh","kein Datum","91182283","2","2.222,22")).events[0].trades[0]
 assert (trade.quantity,trade.price,trade.market_value)==(Decimal("2"),Decimal("1111.11"),Decimal("2222.22"))

def raw_cipher_buy(sp,colon,dot,eur,day,number,qty,price,market,plain_day,plain_number,plain_qty,plain_market,kurs="Kurs",head="",tail=""):
 return f"""comdirect
Wertpapierkauf
Geschäftsnummer{sp*3}{colon}{sp}{number[:2]}{sp}{number[2:]}
Geschäftstag{sp*6}{colon}{sp}{day}{sp*8}
Nennwert Zum {kurs} von
St{dot}{sp*2}{qty}{sp*17}{eur}UR{sp*2}{price}{sp*12}
{sp*26}Kurswert{sp*20}{colon}{sp}{eur}UR{sp*15}{market}{sp*8}
{head}Steuerliche Behandlung: Wertpapierkauf Nr. {plain_number} vom {plain_day}
Stk. {plain_qty} TEST WERTPAPIER , WKN / ISIN: A0LEW8 / IE00B1FZS350
Zu Ihren Lasten vor Steuern: EUR -{plain_market}
{tail}"""

def cipher_values(text):
 trade=parse_text(text).events[0].trades[0]; return trade.quantity,trade.price,trade.market_value

def test_cipher_page_with_fees_ignores_settlement_as_key():
 text=raw_cipher_buy("�","u","f","E","hlfhoflhlm","tihssnil","idnns","psdhi","tsdns","02.05.2023","91088412","1,448","99,96")
 assert cipher_values(text)==(Decimal("1.448"),Decimal("68.01"),Decimal("98.48"))

def test_cipher_page_quantity_beats_whole_number_tax_quantity():
 text=raw_cipher_buy("�","u","g","E","ikgipglill","tkilosrl","keiim","lneomo","lnepk","01.06.2022","91025872","1","24,98")
 assert cipher_values(text)==(Decimal("1.003"),Decimal("24.535"),Decimal("24.61"))

def test_cipher_page_uses_valuta_to_resolve_ambiguous_digit():
 args=("�","u","g","E","ikgkkgliln","tkilnrsk","lelm","llenko","ntett","01.11.2024","91024781","2,230","49,99")
 sp="�"; iban=sp.join(("DEii","iiii","iiii","iiii","iiii","ii"))
 head=f"IBAN Valuta Zu Ihren Lasten vor Steuern\n{iban}{sp*3}EUR{sp*5}iogkkgliln{sp*8}EUR{sp*15}ntett\n"
 tail="Die Belastung erfolgt mit Valuta 05.11.2024 auf Konto EUR mit der IBAN DE00 0000 0000 0000 0000 00"
 # Ohne Valuta passen 22,415 und 22,416 gleichermaßen.
 assert cipher_values(raw_cipher_buy(*args))[1] is MissingValue.NOT_FOUND
 assert cipher_values(raw_cipher_buy(*args,head=head,tail=tail))==(Decimal("2.23"),Decimal("22.415"),Decimal("49.99"))

def test_cipher_page_with_coded_currency_and_mischkurs():
 sap=raw_cipher_buy("T","�","l","E","noloolpnps","zoppnvsw","nioor","pouisn","psist","01.11.2024","91220748","0,113","24,82",kurs="Mischkurs")
 assert cipher_values(sap)==(Decimal("0.113"),Decimal("216.40"),Decimal("24.45"))
 spdr=raw_cipher_buy("w","p","c","�","elcefcgegh","ofeeekfk","ge","loanf","fcholage","06.01.2023","91000515","20","1.411,50")
 assert cipher_values(spdr)==(Decimal("20"),Decimal("69.81"),Decimal("1396.20"))

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


def test_dividend_reference_number_is_preserved_with_evidence():
 text="""comdirect
Abrechnung Dividendengutschrift
Wertpapier-Bezeichnung                  WKN/ISIN
SAP SE                                  716460
Inhaber-Aktien o.N.                     DE0007164600
STK 0,733
Zu Ihren Gunsten EUR 1,61
(Referenz-Nr. 14IKXK3WUKY00GUQ)."""
 plugin=ComdirectPlugin()
 source=PdfDocument("dividend-reference","f"*64,(PdfPage(1,text),))
 result=plugin.parse(source,plugin.detect(source)[0])
 event=result.events[0]
 assert event.bank_reference=="14IKXK3WUKY00GUQ"
 assert len(event.bank_reference_evidence_ids)==1
 evidence=next(item for item in result.evidence if item.evidence_id==event.bank_reference_evidence_ids[0])
 assert evidence.page_number==1 and "14IKXK3WUKY00GUQ" in evidence.excerpt
 assert not event.trades


def test_dividend_reference_label_variants_are_supported_without_rewriting_value():
 from portman_parsers.plugins.comdirect import BANK_REFERENCE
 for label in ("Referenz-Nr. ", "Referenz-Nr.: ", "Referenz Nr ", "Referenznummer: "):
  match=BANK_REFERENCE.search(f"({label}14IkXK3WUKY00GUQ)")
  assert match and match.group(1)=="14IkXK3WUKY00GUQ"


def test_dividend_without_reference_does_not_invent_link_identifier():
 plugin=ComdirectPlugin()
 source=doc("Abrechnung Dividendengutschrift")
 event=plugin.parse(source,plugin.detect(source)[0]).events[0]
 assert not event.bank_reference_evidence_ids
 assert event.bank_reference_status=="MISSING"
 assert str(event.bank_reference)=="UNKNOWN"


def test_dividend_reference_invalid_and_multiple_values_are_not_selected():
 plugin=ComdirectPlugin()
 for text, status in (("(Referenz-Nr. ABC123)", "INVALID"),
                      ("Referenz-Nr. 14IKXK3WUKY00GUQ Referenznummer 24ABC987ZYX00001", "AMBIGUOUS")):
  event=plugin.parse(PdfDocument("reference-status","g"*64,(PdfPage(1,"comdirect\nAbrechnung Dividendengutschrift\n"+text),)), plugin.detect(PdfDocument("reference-status","g"*64,(PdfPage(1,"comdirect\nAbrechnung Dividendengutschrift\n"+text),)))[0]).events[0]
  assert event.bank_reference_status==status and str(event.bank_reference)=="NOT_FOUND"


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


PURCHASE_CASES=(
 ("07.01.2026","0,006","4.152,91","24,92","spaced"),
 ("09.02.2026","0,006","3.982,51","23,90","spaced"),
 ("09.03.2026","0,006","3.843,17","23,06","spaced"),
 ("07.04.2026","0,006","3.996,05","23,98","spaced"),
 ("07.05.2026","0,006","3.648,63","21,89","joined"),
 ("01.06.2026","0,006","3.662,71","21,98","joined"),
 ("01.07.2026","0,007","3.471,31","24,30","joined"),
)


def purchase_document(date_value,quantity,price,market,layout="spaced",tax_quantity="0"):
 settlement=(f"Nennwert Zum Kurs von\nSt. {quantity} EUR {price}\nKurswert : EUR {market}"
             if layout=="spaced" else
             f"Nennwert ZumKursvonSt.{quantity} EUR{price}Kurswert :EUR {market}")
 text=f"""comdirect
Wertpapierkauf
Depotnummer: 123456
WKN: LS9AVX
ISIN: DE000LS9AVX3
{settlement}
Valuta {date_value}
Zu Ihren Lasten EUR {market}
Steuerliche Behandlung: Wertpapierkauf Nr. 91182283 vom {date_value}
Stk. {tax_quantity} LANG+SCHWARZ O.E. INDEX , WKN / ISIN: LS9AVX / DE000LS9AVX3"""
 return PdfDocument("doc-"+date_value,"a"*64,(PdfPage(1,text),))


def test_all_seven_comdirect_purchase_quantities_are_exact():
 plugin=ComdirectPlugin()
 for date_value,quantity,price,market,layout in PURCHASE_CASES:
  source=purchase_document(date_value,quantity,price,market,layout); result=plugin.parse(source,plugin.detect(source)[0])
  event=result.events[0]; trade=event.trades[0]; expected=Decimal(quantity.replace(",",".")); amount=Decimal(market.replace(",","."))
  assert event.kind=="BUY"
  assert trade.quantity==expected and event.security_movements[0].quantity==expected
  assert trade.market_value==amount==trade.settlement_amount and event.cash_movements[0].amount==-amount
  assert (trade.isin,event.security_isin)==("DE000LS9AVX3","DE000LS9AVX3")
  assert (trade.wkn,event.security_wkn)==("LS9AVX","LS9AVX")
  assert "COMDIRECT_QUANTITY_MISSING" not in {issue.code for issue in result.issues}


def test_decimal_zero_tax_quantity_does_not_override_purchase_quantity():
 source=purchase_document("07.01.2026","0,006","4.152,91","24,92","spaced","0,000")
 event=ComdirectPlugin().parse(source,ComdirectPlugin().detect(source)[0]).events[0]
 assert event.trades[0].quantity==Decimal("0.006") and event.security_movements[0].quantity==Decimal("0.006")


def test_quantity_without_nennwert_still_uses_stk_line():
 text="""comdirect
Wertpapierkauf
Stk. 0,125
WKN: ABC123
ISIN: DE0008474511
Valuta 01.07.2026
Zu Ihren Lasten EUR 126,50"""
 source=PdfDocument("fallback-quantity","b"*64,(PdfPage(1,text),)); plugin=ComdirectPlugin()
 event=plugin.parse(source,plugin.detect(source)[0]).events[0]
 assert event.trades[0].quantity==Decimal("0.125") and event.security_movements[0].quantity==Decimal("0.125")


def test_tax_line_zero_alone_is_not_a_purchase_quantity():
 for tax_line in ("Stk. 0 LANG+SCHWARZ O.E. INDEX","Stk. 0,000 LANG+SCHWARZ O.E. INDEX"):
  text=f"""comdirect
Wertpapierkauf
WKN: LS9AVX
ISIN: DE000LS9AVX3
{tax_line}
Valuta 07.01.2026
Zu Ihren Lasten EUR 24,92"""
  source=PdfDocument("zero-tax-quantity","c"*64,(PdfPage(1,text),)); plugin=ComdirectPlugin()
  result=plugin.parse(source,plugin.detect(source)[0]); event=result.events[0]
  assert event.trades[0].quantity is MissingValue.NOT_FOUND and not event.security_movements
  assert "COMDIRECT_QUANTITY_MISSING" in {issue.code for issue in result.issues}

# Gebühren in defekter Schrift (codierte Zeichenfolgen aus echten Abrechnungen, ohne Personendaten)
def cipher_fees(text):
 return [(fee.subcategory,fee.amount) for fee in parse_text(text).events[0].fee_events]

SAP_ARGS=("T","�","l","E","noloolpnps","zoppnvsw","nioor","pouisn","psist","01.11.2024","91220748","0,113","24,82")
def sap_fee_head(coded,sp="T"):
 return f"Eigene{sp}Entgelte{sp*20}\n{sp*26}Provision{sp*19}§{sp}EUR{sp*16}{coded}{sp*11}\n"

def test_cipher_provision_is_decoded_with_trade_key():
 text=raw_cipher_buy(*SAP_ARGS,kurs="Mischkurs",head=sap_fee_head("nirv"))
 assert cipher_values(text)==(Decimal("0.113"),Decimal("216.40"),Decimal("24.45"))
 assert cipher_fees(text)==[("provision",Decimal("0.37"))]

def test_cipher_provision_is_not_invented_when_settlement_does_not_match():
 # "nirt" ergäbe 0,35; Kurswert + Gebühr erklärt die Belastung von 24,82 dann nicht.
 text=raw_cipher_buy(*SAP_ARGS,kurs="Mischkurs",head=sap_fee_head("nirt"))
 assert cipher_values(text)==(Decimal("0.113"),Decimal("216.40"),Decimal("24.45"))
 assert cipher_fees(text)==[]

def test_cipher_provision_resolves_missing_digit_by_glyph_order_and_settlement():
 # "s" kommt sonst nirgends vor; zwischen r=4 und t=6 bleibt nur 5, und 39,41 + 0,59 = 40,00.
 sp="R"; head=f"Eigene{sp}Entgelte{sp*20}\n{sp*26}Provision{sp*19}z{sp}EUR{sp*17}mgsw{sp*53}\n"
 text=raw_cipher_buy(sp,"z","i","E","mnimpiomon","wnmopomo","ngtm","orgtp","pwgrn","01.03.2021","91023202","1,600","40,00",head=head)
 assert cipher_values(text)==(Decimal("1.60"),Decimal("24.63"),Decimal("39.41"))
 assert cipher_fees(text)==[("provision",Decimal("0.59"))]

def test_cipher_clearing_provision_and_exchange_fee_are_all_required():
 sp="w"; eur="�"
 clearing=f"{sp*26}zbwicklcentgelt{sp}ßlearstream{sp}p{sp}{eur}UR{sp*16}gaoe{sp*11}\n"
 provision=f"{sp*26}Provision{sp*19}p{sp}{eur}UR{sp*16}oaoe{sp*11}\n"
 exchange=f"{sp*26}§örsenplatzabhängc{sp}öntgelt{sp*2}p{sp}{eur}UR{sp*16}gake{sp*11}\n"
 args=(sp,"p","c",eur,"elcefcgegh","ofeeekfk","ge","loanf","fcholage","06.01.2023","91000515","20","1.411,50")
 assert sorted(cipher_fees(raw_cipher_buy(*args,head=clearing+provision+exchange)))==[
  ("clearing_fee",Decimal("2.90")),("exchange_fee",Decimal("2.50")),("provision",Decimal("9.90"))]
 # Fehlt eine ausgewiesene Gebühr, erklärt die Summe die Belastung nicht: keine Teilübernahme.
 assert cipher_fees(raw_cipher_buy(*args,head=clearing+provision))==[]

def test_plain_clearstream_settlement_fee_is_extracted():
 text="""comdirect
Wertpapierkauf
Nennwert Zum Kurs von
St. 16 EUR 25,00
Kurswert : EUR 400,00
Provision : EUR 9,90
Abwickl.entgelt Clearstream : EUR 2,90
Börsenplatzabhäng. Entgelt : EUR 1,50
Summe Entgelte : EUR 14,30
Zu Ihren Lasten vor Steuern EUR 414,30"""
 assert sorted(cipher_fees(text))==[("clearing_fee",Decimal("2.90")),("exchange_fee",Decimal("1.50")),("provision",Decimal("9.90"))]
