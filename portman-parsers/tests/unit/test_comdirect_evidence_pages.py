"""Regressionstests für die Evidence-Seitenzuordnung der comdirect-Handler.

Deckt die Ursachen des Fehlers ``field value page differs from Evidence`` ab:
hartkodierte Seiten in FieldValue, Substring-Suche mit stiller Seite-1-Annahme
und identische Fundstellen auf verschiedenen Seiten.
"""

import re
from datetime import date
from decimal import Decimal

import pytest

from portman_parsers.api import (Account, Evidence, FieldValue, MissingValue, ParsedDocument,
                                 PdfDocument, PdfPage)
from portman_parsers.plugins.comdirect import (ComdirectFinanzreportPlugin, ComdirectPlugin,
                                               evidence_page, evidence_recorder, _page_for_offset)


def _document(pages):
    return PdfDocument("doc-ev", "a" * 64,
                       tuple(PdfPage(number, text) for number, text in pages.items()))


def _evidence_pages(result):
    return {item.evidence_id: item.page_number for item in result.evidence}


def _field_pages(values):
    """{(Pfad, Wert): (Seite, Evidence-Liste)} über ein FieldValue-Objekt."""
    return values


# --- Seitenzuordnung an der Entstehungsstelle -------------------------------

def test_offset_mapping_is_one_based_and_boundary_correct():
    document = _document({1: "AA\nBB", 2: "CC\nDD", 3: "EE"})
    assert _page_for_offset(document, 0) == 1
    assert _page_for_offset(document, 4) == 1          # letzter Offset von Seite 1
    assert _page_for_offset(document, 5) == 2          # Join-Newline gehört zum Seitenstart
    assert _page_for_offset(document, 6) == 2          # erstes Zeichen von Seite 2
    assert _page_for_offset(document, 10) == 2         # letztes Zeichen von Seite 2
    assert _page_for_offset(document, 12) == 3
    assert _page_for_offset(document, 13) == 3
    assert [page.number for page in document.pages] == [1, 2, 3]


def test_excerpt_spanning_page_break_maps_to_starting_page():
    document = _document({1: "Vorhalle ABC", 2: "DEF Nachhalle"})
    joined = document.text
    assert joined == "Vorhalle ABC\nDEF Nachhalle"
    match = re.search(r"ABC\nDEF", joined)
    page = evidence_page(document, match.group(0), offset=match.start())
    assert page == 1


def test_identical_excerpts_on_different_pages_use_the_match_offset():
    document = _document({1: "Saldo 10,00", 2: "Saldo 10,00"})
    ev, fv, evidence = evidence_recorder(document, "p", "h", "1")
    matches = list(re.finditer(r"Saldo 10,00", document.text))
    first_id, second_id = ev("saldo", matches[0]), ev("saldo", matches[1])
    assert first_id != second_id
    pages = {item.evidence_id: item.page_number for item in evidence}
    assert pages[first_id] == 1
    assert pages[second_id] == 2


def test_unlocatable_excerpt_raises_instead_of_silently_claiming_page_one():
    document = _document({1: "nur diese Seite"})
    ev, fv, evidence = evidence_recorder(document, "p", "h", "1")
    with pytest.raises(ValueError, match="does not occur in any PDF page"):
        ev("security_name", "L A N G    G ESCHWARZ")


def test_locates_value_with_repaired_glyph_spacing():
    document = _document({1: "Kopf", 2: "Bezeichnung L A N G  S C H W A R Z"})
    ev, fv, evidence = evidence_recorder(document, "p", "h", "1")
    eid = ev("security_name", "LANG SCHWARZ")
    assert _evidence_pages(type("R", (), {"evidence": evidence}))[eid] == 2


def test_field_value_always_shares_the_evidence_page():
    document = _document({1: "Depotnummer: 12345", 2: "Mehr Text"})
    ev, fv, evidence = evidence_recorder(document, "p", "h", "1")
    match = re.search(r"Depotnummer: 12345", document.text)
    eid = ev("depot_number", match)
    value = fv("12345", eid)
    assert value.page_number == 1 and value.evidence_ids == (eid,)


# --- Validierung bleibt scharf ----------------------------------------------

def test_parsed_document_still_rejects_page_mismatch():
    document = _document({1: "x", 2: "y"})
    eid = "evidence-x1"
    evidence = (Evidence(eid, document.document_id, 2, "iban", "DE11"),)
    account = Account("account-1", iban=FieldValue.from_pdf("DE11", 1, eid))
    with pytest.raises(ValueError, match="field value page differs from Evidence"):
        ParsedDocument("result-1", document.document_id, "plugin", "1", "handler",
                       evidence=evidence, accounts=(account,))


def test_parsed_document_rejects_unknown_evidence_reference():
    account = Account("account-1", iban=FieldValue.from_pdf("DE11", 1, "evidence-fehlt"))
    with pytest.raises(ValueError, match="unknown Evidence"):
        ParsedDocument("result-1", "d1", "plugin", "1", "handler", accounts=(account,))


# --- Mehrseitiger Finanzreport ----------------------------------------------

FINANZREPORT_SEITE1 = """comdirect
Finanzreport Nr. 5 per 31.03.2026
Kundennummer: 102 4764924
Kontoübersicht
Girokonto DE00 0000 0000 0000 0000 01 +105,00
Tagesgeld PLUS-Konto DE11 0000 0000 0000 0000 11 +51,00
Girokonto Dispositionskredit 1.500 EUR
Buchungstag
Alter Saldo 01.01.2026 100,00"""

FINANZREPORT_SEITE2 = """02.01.2026 02.01.2026 Gutschrift +10,00
03.01.2026 03.01.2026 Lastschrift -5,00
Neuer Saldo 31.01.2026 105,00
Tagesgeld
PLUS-Konto
Buchungstag
Alter Saldo 01.01.2026 +50,00
05.01.2026 05.01.2026 Zinsgutschrift +1,00
Neuer Saldo 31.03.2026 +51,00"""

FINANZREPORT_SEITE3 = """Depot
A0D8QZ / Girosammelverwahrung
ISH.S.EUR.SMALL 200 U.ETF
101,307 34,966 EUR 3.542,31
+0,00
2.735,85
+806,46
Gesamtkurswert
Stückzinsen gesamt
Gesamtwert
3.542,31
+0,00
3.542,31
2.735,85
+806,46"""


def _finanzreport_multiseite():
    document = _document({1: FINANZREPORT_SEITE1, 2: FINANZREPORT_SEITE2, 3: FINANZREPORT_SEITE3})
    plugin = ComdirectFinanzreportPlugin()
    return plugin.parse(document, plugin.detect(document)[0])


def test_finanzreport_multiseite_ohne_validierungsabbruch_und_mit_korrekten_seiten():
    result = _finanzreport_multiseite()
    assert not [issue for issue in result.issues if issue.code == "BALANCE_MISMATCH"]
    # Konto-IBAN steht auf Seite 1, Feldwert und Evidence teilen diese Seite.
    account = next(item for item in result.accounts if item.iban.value.endswith("01"))
    iban_evidence = next(item for item in result.evidence if item.evidence_id == account.iban.evidence_ids[0])
    assert iban_evidence.page_number == 1
    assert account.iban.page_number == iban_evidence.page_number == 1
    # Buchungen auf Seite 2: Event-Evidence zeigt auf Seite 2.
    booking = next(item for item in result.events if item.cash_movements[0].amount == Decimal("10.00"))
    booking_evidence = next(item for item in result.evidence
                            if item.evidence_id == booking.evidence_ids[0])
    assert booking_evidence.page_number == 2
    # Depotposition auf Seite 3.
    position = result.depot_snapshots[0].positions[0]
    position_evidence = next(item for item in result.evidence
                             if item.evidence_id == position.market_value.evidence_ids[0])
    assert position_evidence.page_number == 3
    assert position.market_value.page_number == 3


@pytest.mark.parametrize(("price", "expected"), [
    ("0,000", Decimal("0.000")),
    ("0,001", MissingValue.UNKNOWN),
])
def test_finanzreport_depotposition_ohne_kurswaehrung(price, expected):
    row = f"0,999 {price} 0,00"
    depot_page = FINANZREPORT_SEITE3.replace(
        "Gesamtkurswert\n",
        f"X0TEST / Girosammelverwahrung\nTestwert\n{row}\n+0,00\n0,00 +0,00\nGesamtkurswert\n",
    )
    document = _document({1: FINANZREPORT_SEITE1, 2: FINANZREPORT_SEITE2, 3: depot_page})
    plugin = ComdirectFinanzreportPlugin()
    result = plugin.parse(document, plugin.detect(document)[0])
    position = next(item for item in result.depot_snapshots[0].positions if item.security_id.value == "X0TEST")
    assert position.quantity.value == Decimal("0.999")
    assert position.price.value == expected
    assert position.market_value.value == Decimal("0.00")
    assert position.currency.value == "EUR"
    evidence = next(item for item in result.evidence if item.evidence_id in position.market_value.evidence_ids)
    assert evidence.page_number == 3
    assert row in evidence.excerpt
    if expected is not MissingValue.UNKNOWN:
            price_evidence = next(item for item in result.evidence if item.evidence_id in position.price.evidence_ids)
            assert price_evidence.excerpt == row
            assert position.price.evidence_ids != position.market_value.evidence_ids
    assert not result.issues


def test_finanzreport_split_heading_tagesgeld_plus_konto():
    result = _finanzreport_multiseite()
    accounts = {item.account_name.value for item in result.accounts}
    assert accounts == {"Girokonto", "Tagesgeld PLUS-Konto"}
    # Salden beider Konten werden erkannt und abgestimmt.
    assert len(result.account_balances) == 4
    assert not [issue for issue in result.issues
                if issue.code in {"BALANCE_MISMATCH", "OVERVIEW_BALANCE_MISMATCH", "SALDO_MISSING"}]


def test_finanzreport_identische_zeilen_auf_verschiedenen_seiten_ohne_falsche_fundstelle():
    seite2 = FINANZREPORT_SEITE2.replace("03.01.2026 03.01.2026 Lastschrift -5,00\n", "")
    dokument = _document({1: FINANZREPORT_SEITE1 + "\n03.01.2026 03.01.2026 Lastschrift -5,00",
                          2: seite2, 3: FINANZREPORT_SEITE3})
    plugin = ComdirectFinanzreportPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    duplicates = [issue for issue in result.issues if issue.code == "DUPLICATE_BOOKING"]
    assert not duplicates  # unterschiedliche Seiten, aber identischer Inhalt ist hier nicht gegeben
    # dieselbe Buchung noch einmal auf Seite 2 ergänzt -> Dublette mit Warnung
    dokument2 = _document({1: FINANZREPORT_SEITE1 + "\n02.01.2026 02.01.2026 Gutschrift +10,00",
                           2: FINANZREPORT_SEITE2, 3: FINANZREPORT_SEITE3})
    result2 = plugin.parse(dokument2, plugin.detect(dokument2)[0])
    assert any(issue.code == "DUPLICATE_BOOKING" for issue in result2.issues)
    gutschriften = [event for event in result2.events
                    if event.cash_movements[0].amount == Decimal("10.00")]
    assert len(gutschriften) == 1
    evidence = next(item for item in result2.evidence
                    if item.evidence_id == gutschriften[0].evidence_ids[0])
    assert evidence.page_number == 1


def test_finanzreport_balance_mismatch_is_reported_not_swallowed():
    text = FINANZREPORT_SEITE1 + "\n02.01.2026 02.01.2026 Gutschrift +10,00\nNeuer Saldo 31.01.2026 200,00"
    dokument = _document({1: text})
    plugin = ComdirectFinanzreportPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    assert any(issue.code == "BALANCE_MISMATCH" for issue in result.issues)


def test_finanzreport_depot_position_mismatch_is_reported():
    text = (FINANZREPORT_SEITE1 + "\nNeuer Saldo 31.01.2026 105,00\nDepot\n"
            "A0D8QZ / Girosammelverwahrung\nISH.S.EUR.SMALL 200 U.ETF\n101,307 34,966 EUR 3.542,31\n"
            "+0,00\n2.000,00\n+500,00\nGesamtkurswert\nStückzinsen gesamt\nGesamtwert\n"
            "3.542,31\n+0,00\n3.542,31\n2.735,85\n+806,46")
    dokument = _document({1: text})
    plugin = ComdirectFinanzreportPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    assert any(issue.code == "DEPOT_POSITION_MISMATCH" for issue in result.issues)


def test_finanzreport_zinsabschluss_mit_steuern_als_tax_event():
    text = (FINANZREPORT_SEITE1 + "\n02.01.2026 02.01.2026 Gutschrift +5,00\nNeuer Saldo 31.01.2026 105,00\n"
            "Tagesgeld\nPLUS-Konto\nBuchungstag\nAlter Saldo 01.01.2026 +50,00\n"
            "31.03.2026\n31.03.2026\nKontoabschluss\nAbschluss Zinsen Kto 476492405EUR\n"
            "von 01.01.2026 bis 31.03.2026\nHabenzinsen\n1,000% ab 01.01. 2,00 EUR\n"
            "Kapitalertragsteuer 0,30 EUR\nSolidaritätszuschlag 0,02 EUR\n"
            "Abschlussrechnung 1,68 EUR\nSaldo nach Abschluss\n51,68 EUR\n+1,68\n"
            "Neuer Saldo 31.03.2026 +51,68")
    dokument = _document({1: text.replace("Tagesgeld PLUS-Konto DE11 0000 0000 0000 0000 11 +51,00",
                                          "Tagesgeld PLUS-Konto DE11 0000 0000 0000 0000 11 +51,68")})
    plugin = ComdirectFinanzreportPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    interest = next(event for event in result.events if event.cash_movements[0].amount == Decimal("1.68"))
    assert interest.cash_movements[0].movement_type.value == "INTEREST_CREDIT"
    components = {component.kind: component.amount for component in interest.tax_events[0].components}
    assert components == {"CAPITAL_GAINS_TAX": Decimal("0.30"), "SOLIDARITY_SURCHARGE": Decimal("0.02")}
    assert not [issue for issue in result.issues if issue.code in
                {"INTEREST_RECONCILIATION", "BALANCE_MISMATCH", "OVERVIEW_BALANCE_MISMATCH"}]


# --- Mehrseitige Kaufabrechnung ----------------------------------------------

KAUF_SEITE1 = """comdirect
Wertpapierkauf
Wertpapier-Bezeichnung WPKNR/ISIN
Beispiel Fonds ABC123
Geschäftstag 01.02.2026"""

KAUF_SEITE2 = """Depotnummer: 12345
IBAN DE00 0000 0000 0000 0000 01
Stk. 0,125 Beispiel Fonds , WKN / ISIN: ABC123 / DE0008474511
Kurs EUR 1.000,00
Kurswert EUR 125,00
Provision EUR 1,50
Kapitalertragsteuer EUR 2,00
Solidaritätszuschlag EUR 0,11
Kirchensteuer EUR 1,00
Zu Ihren Lasten EUR 126,50
Valuta 04.02.2026
Referenz-Nummer:
14IKXK3WUKY00GUQ"""


def test_kaufabrechnung_mehrseitig_account_und_link_auf_evidence_seite():
    dokument = _document({1: KAUF_SEITE1, 2: KAUF_SEITE2, 3: "Anhang\ncomdirect"})
    plugin = ComdirectPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    event = result.events[0]
    assert event.kind == "BUY"
    account = result.accounts[0]
    iban_evidence = next(item for item in result.evidence if item.evidence_id == account.iban.evidence_ids[0])
    assert iban_evidence.page_number == 2
    assert account.iban.page_number == 2
    link = result.depot_account_links[0]
    link_evidence = next(item for item in result.evidence if item.evidence_id == link.role.evidence_ids[0])
    assert link_evidence.page_number == 2
    assert link.role.page_number == 2
    settlement_evidence = next(item for item in result.evidence if item.evidence_id == event.evidence_ids[0])
    assert settlement_evidence.page_number == 2


def test_kaufabrechnung_gebuehren_und_steuern_volstaendig():
    dokument = _document({1: KAUF_SEITE1 + "\n" + KAUF_SEITE2})
    plugin = ComdirectPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    event = result.events[0]
    assert [(fee.subcategory, fee.amount) for fee in event.fee_events] == [("provision", Decimal("1.50"))]
    components = {component.kind: component.amount for component in event.tax_events[0].components}
    assert components == {"CAPITAL_GAINS_TAX": Decimal("2.00"),
                          "SOLIDARITY_SURCHARGE": Decimal("0.11"),
                          "CHURCH_TAX": Decimal("1.00")}
    assert event.cash_movements[0].amount == Decimal("-126.50")
    assert event.cash_movements[0].currency == "EUR"


def test_kaufabrechnung_fremdwaehrung_und_getrennte_referenz():
    text = ("comdirect\nAbrechnung Dividendengutschrift\nDepotnummer: 12345\n"
            "IBAN DE00 0000 0000 0000 0000 01\n"
            "Stk. 2,000 US-Stock , WKN / ISIN: US1234 / US0378331005\n"
            "Bruttobetrag USD 12,34\nQuellensteuer USD 1,23\n"
            "Devisenkurs 1,1000\nZu Ihren Gunsten USD 11,11\n"
            "Referenz-Nummer:\n14IKXK3WUKY00GUQ")
    dokument = _document({1: text})
    plugin = ComdirectPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    event = result.events[0]
    assert event.kind == "DIVIDEND"
    assert event.cash_movements[0].currency == "USD"
    assert event.cash_movements[0].amount == Decimal("11.11")
    assert event.trades == ()
    components = {component.kind: component.amount for component in event.tax_events[0].components}
    assert components == {"WITHHOLDING_TAX": Decimal("1.23")}
    assert event.bank_reference == "14IKXK3WUKY00GUQ"
    assert event.bank_reference_status == "RECOGNIZED"


def test_kaufabrechnung_geteilte_referenz_und_defekte_stueckzahl_bleiben_ehrlich():
    text = (KAUF_SEITE1 + "\nDepotnummer: 12345\nIBAN DE00 0000 0000 0000 0000 01\n"
            "Stk. 0 LANG+SCHWARZ O.E. INDEX , WKN / ISIN: LS9AVX / DE000LS9AVX3\n"
            "Zu Ihren Lasten vor Steuern: EUR -24,92\n"
            "Valuta 09.01.2026\nReferenz-Nummer:\n0\nSIN8K01DPG003GV")
    dokument = _document({1: text})
    plugin = ComdirectPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    event = result.events[0]
    # Der über zwei Zeilen zerrissene Referenzwert wird zusammengefügt.
    assert event.bank_reference == "0SIN8K01DPG003GV"
    assert event.bank_reference_status == "RECOGNIZED"
    # Die defekte Stückzahl ("Stk. 0") wird nicht geraten, sondern gemeldet.
    assert any(issue.code == "COMDIRECT_QUANTITY_MISSING" for issue in result.issues)
    assert event.security_movements == ()
    # Name und Kennungen kommen aus der Steuerzeile, nicht aus dem Tabellenkopf.
    assert event.security_name == "LANG+SCHWARZ O.E. INDEX"
    assert event.security_wkn == "LS9AVX"
    assert event.security_isin == "DE000LS9AVX3"
    assert event.trades[0].security_name == "LANG+SCHWARZ O.E. INDEX"


def test_kaufabrechnung_nennwert_kurs_und_mengen_fallback():
    text = ("comdirect\nWertpapierkauf\nDepotnummer: 12345\nIBAN DE00 0000 0000 0000 0000 01\n"
            "Stk. 0 LANG+SCHWARZ O.E. INDEX , WKN / ISIN: LS9AVX / DE000LS9AVX3\n"
            "Nennwert Zum Kurs von\nSt. 0,006 EUR 3.662,71\nKurswert : EUR 21,98\n"
            "Zu Ihren Lasten vor Steuern: EUR -21,98\nValuta 03.06.2026\n"
            "Steuerliche Behandlung: Wertpapierkauf Nr. 91229890 vom 01.06.2026")
    dokument = _document({1: text})
    plugin = ComdirectPlugin()
    result = plugin.parse(dokument, plugin.detect(dokument)[0])
    trade = result.events[0].trades[0]
    assert trade.quantity == Decimal("0.006")
    assert trade.price == Decimal("3662.71")
    assert trade.market_value == Decimal("21.98")
    assert trade.trade_date == date(2026, 6, 1)
