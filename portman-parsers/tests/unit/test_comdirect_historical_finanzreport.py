"""Historische comdirect-Finanzreports: IBAN-Zuordnung ohne Kontoübersicht mit IBAN.

Alle Daten sind synthetisch (keine echten IBANs, Namen oder Beträge).
"""
from decimal import Decimal

from portman_parsers.api import PdfDocument, PdfPage
from portman_parsers.plugins import ComdirectFinanzreportPlugin

IBAN_GIRO = "DE00 0000 0000 0000 0000 01"
IBAN_TG = "DE00 0000 0000 0000 0000 02"
IBAN_VK = "DE00 0000 0000 0000 0000 03"
IBAN_TGK = "DE00 0000 0000 0000 0000 04"
HINWEIS = """Für Ihre Überweisungen zugunsten Ihrer comdirect-Konten verwenden Sie bitte folgende Kontonummern:
BIC/SWIFT-Code: COBADEHD001
{zeilen}"""


def _parse(text, pages=None):
    source = PdfDocument("hist", "c" * 64, tuple(PdfPage(i + 1, page) for i, page in enumerate(pages or [text])))
    plugin = ComdirectFinanzreportPlugin()
    return plugin.parse(source, plugin.detect(source)[0])


def _hinweis(**ibans):
    return HINWEIS.format(zeilen="\n".join("- %s: Konto 123456789 IBAN %s" % (name.replace("_", " "), iban) for name, iban in ibans.items()))


def _by_name(result):
    return {account.account_name.value: account for account in result.accounts}


def test_historisches_tagesgeld_plus_mit_hinweisblock_wird_zugeordnet_und_abgestimmt():
    text = """comdirect\nFinanzreport Nr. 5 per 01.11.2009
Kontoübersicht
Girokonto +100,00
Tagesgeld PLUS +500,00
Tagesgeld PLUS
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo 01.10.2009 +400,00
Kontoübertrag 05.10.2009 05.10.2009 +150,00
ÜBERTRAG AUF TAGESGELD PLUS
Übertrag/Überweisung 20.10.2009 20.10.2009 -50,00
ÜBERTRAG AUF GIROKONTO
Neuer Saldo 31.10.2009 +500,00
""" + _hinweis(Girokonto=IBAN_GIRO, Tagesgeld_PLUS=IBAN_TG)
    result = _parse(text)
    assert [a.account_name.value for a in result.accounts] == ["Tagesgeld PLUS"]
    assert result.accounts[0].iban.value == IBAN_TG.replace(" ", "")
    assert [e.cash_movements[0].amount for e in result.events] == [Decimal("150.00"), Decimal("-50.00")]
    assert {e.cash_movements[0].account_id for e in result.events} == {result.accounts[0].account_id}
    assert not [i for i in result.issues if i.severity.value in {"ERROR", "WARNING"}]
    assert len(result.account_balances) == 2


def test_historisches_girokonto_verrechnungskonto_und_tagesgeldkonto_je_eigene_iban():
    text = """comdirect\nFinanzreport Nr. 5 per 01.11.2009
Girokonto
Buchungstag Valuta Soll / Haben
Alter Saldo 01.10.2009 +100,00
Lastschrift Einzug 02.10.2009 02.10.2009 -10,00
Neuer Saldo 31.10.2009 +90,00
Verrechnungskonto
Buchungstag Valuta Soll / Haben
Alter Saldo 01.10.2009 +1,00
Neuer Saldo 31.10.2009 +1,00
Tagesgeldkonto
Buchungstag Valuta Soll / Haben
Alter Saldo 01.10.2009 +20,00
Gutschrift 15.10.2009 15.10.2009 +5,00
Neuer Saldo 31.10.2009 +25,00
""" + _hinweis(Girokonto=IBAN_GIRO, Verrechnungskonto=IBAN_VK, Tagesgeldkonto=IBAN_TGK)
    result = _parse(text)
    accounts = _by_name(result)
    assert set(accounts) == {"Girokonto", "Verrechnungskonto", "Tagesgeldkonto"}
    assert accounts["Girokonto"].iban.value == IBAN_GIRO.replace(" ", "")
    assert accounts["Verrechnungskonto"].iban.value == IBAN_VK.replace(" ", "")
    assert accounts["Tagesgeldkonto"].iban.value == IBAN_TGK.replace(" ", "")
    by_account = {}
    for event in result.events:
        by_account.setdefault(event.cash_movements[0].account_id, []).append(event.cash_movements[0].amount)
    assert by_account[accounts["Girokonto"].account_id] == [Decimal("-10.00")]
    assert by_account[accounts["Tagesgeldkonto"].account_id] == [Decimal("5.00")]
    assert accounts["Verrechnungskonto"].account_id not in by_account
    assert not result.issues


def test_iban_mit_abweichender_zeilenstruktur_und_leerzeichen_wird_erkannt():
    text = """comdirect\nFinanzreport Nr. 5 per 01.11.2009
Tagesgeld PLUS
Buchungstag Valuta Soll / Haben
Alter Saldo 01.10.2009 +1,00
Neuer Saldo 31.10.2009 +1,00
- Tagesgeld PLUS:   Konto 123456789   IBAN DE00 0000 0000 0000 0000 02
"""
    result = _parse(text)
    assert result.accounts[0].iban.value == IBAN_TG.replace(" ", "")


def test_fehlende_iban_wird_nicht_erfunden_und_als_issue_gemeldet():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2007
IBAN: DE00 0000 0000 0000 0000 01
Tagesgeld PLUS
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo 01.01.2007 +10,00
Gutschrift 15.01.2007 15.01.2007 +5,00
Neuer Saldo 31.01.2007 +15,00
"""
    result = _parse(text)
    assert not result.accounts and not result.events and not result.account_balances
    issue = [i for i in result.issues if i.code == "ACCOUNT_IBAN_UNRESOLVED"]
    assert len(issue) == 1 and issue[0].severity.value == "ERROR" and "1 Buchung" in issue[0].message


def test_fehlende_iban_ohne_buchungen_ist_nur_warnung():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2007
Tagesgeldkonto
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo 01.01.2007 0,00
Neuer Saldo 31.01.2007 0,00
"""
    result = _parse(text)
    assert not result.accounts
    assert [i.severity.value for i in result.issues] == ["WARNING"]


def test_historisches_girokonto_nach_mehrzeiligen_kartenlimits():
    text = """comdirect
Finanzreport Nr. 1 per 01.02.2010
Girokonto ec Tages-/Wochenlimit
EUR 100,-/EUR 200,-
Visa Tageslimit
EUR 300,-
Dispositionskredit
EUR 400,-
Buchungstag
Valuta
Kto. / IBAN BLZ / BIC
Alter Saldo 01.01.2010 +10,00
15.01.2010
15.01.2010
Gutschrift +5,00
Neuer Saldo 31.01.2010 +15,00
""" + _hinweis(Girokonto=IBAN_GIRO)
    result = _parse(text)
    assert [event.cash_movements[0].amount for event in result.events] == [Decimal("5.00")]
    assert len(result.account_balances) == 2
    assert not result.issues


def test_kompakter_dispositionskredit_beginnt_eigenen_giroabschnitt():
    text = f"""comdirect
Finanzreport Nr. 11 per 01.12.2017
Kontoübersicht
Girokonto {IBAN_GIRO} +15,00
Verrechnungskonto {IBAN_VK} +1,00
Girokonto DispositionskreditEUR 100 girocard Tages-/WochenlimitEUR 200
Buchungstag
Valuta
Alter Saldo 01.11.2017 +10,00
15.11.2017 15.11.2017 Gutschrift +5,00
Neuer Saldo 01.12.2017 +15,00
Verrechnungskonto
Buchungstag
Valuta
Alter Saldo 01.11.2017 +1,00
Neuer Saldo 01.12.2017 +1,00
"""
    result = _parse(text)
    accounts = _by_name(result)
    assert [event.cash_movements[0].account_id for event in result.events] == [accounts["Girokonto"].account_id]
    assert len(result.account_balances) == 4
    assert not result.issues


def test_undatierter_endsaldo_begrenzt_nicht_zuordenbaren_kontobereich():
    text = """comdirect
Finanzreport Nr. 12 per 31.12.2007
IBAN: DE00 0000 0000 0000 0000 01
Girokonto ec Tages-/WochenlimitEUR 100,-
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo +10,00
Lastschrift Einzug 02.12.2007 02.12.2007 -5,00
Neuer Saldo +5,00
Tagesgeld PLUS
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo +10,00
Gutschrift 15.12.2007 15.12.2007 +1,00
Gutschrift 17.12.2007 17.12.2007 +2,00
Neuer Saldo +13,00
"""
    result = _parse(text)
    assert not result.accounts and not result.events and not result.account_balances
    assert [issue.code for issue in result.issues] == ["ACCOUNT_IBAN_UNRESOLVED"] * 2
    assert "1 Buchung(en)" in result.issues[0].message
    assert "2 Buchung(en)" in result.issues[1].message


def test_mehrdeutige_iban_zuordnung_wird_nicht_geraten():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2007
Tagesgeld PLUS
Buchungstag Valuta Soll / Haben
Alter Saldo 01.01.2007 +10,00
Gutschrift 15.01.2007 15.01.2007 +5,00
Neuer Saldo 31.01.2007 +15,00
""" + _hinweis(Girokonto=IBAN_GIRO) + "\n- Tagesgeld PLUS: Konto 1 IBAN %s\n- Tagesgeld PLUS: Konto 2 IBAN %s\n" % (IBAN_TG, IBAN_TGK)
    result = _parse(text)
    assert not result.accounts and not result.events
    assert "mehrdeutig" in [i for i in result.issues if i.code == "ACCOUNT_IBAN_UNRESOLVED"][0].message


def test_saldenabgleich_meldet_abweichung_weiterhin():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2007
Tagesgeld PLUS
Buchungstag Valuta Soll / Haben
Alter Saldo 01.01.2007 +10,00
Gutschrift 15.01.2007 15.01.2007 +5,00
Neuer Saldo 31.01.2007 +99,00
""" + _hinweis(Tagesgeld_PLUS=IBAN_TG)
    result = _parse(text)
    assert [i.code for i in result.issues] == ["BALANCE_MISMATCH"]


def test_verwahrentgelt_im_historischen_layout_ohne_doppelbuchung():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2007
Verrechnungskonto
Buchungstag Valuta Soll / Haben
Alter Saldo 01.01.2007 +10,00
Entgelte Verwahrentgelt Xetra Gold WKN A0S9GB 06.01.2007 05.01.2007 -0,67
Neuer Saldo 31.01.2007 +9,33
""" + _hinweis(Verrechnungskonto=IBAN_VK)
    result = _parse(text)
    assert len(result.events) == 1 and len(result.events[0].cash_movements) == 1
    assert len(result.events[0].fee_events) == 1
    assert result.events[0].fee_events[0].cash_movement_id == result.events[0].cash_movements[0].movement_id
    assert not result.issues


def test_historische_tabellenspalten_uebernehmen_eindeutige_buchung_und_stimmen_saldo_ab():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2013
Girokonto
Buchungstag
Kto. / IBAN BLZ / BIC
Alter Saldo 01.01.2013 +100,00
-10,00Lastschrift Beispiel
01.01.2013
01.01.2013
Neuer Saldo 31.01.2013 +90,00
""" + _hinweis(Girokonto=IBAN_GIRO)
    result = _parse(text)
    assert len(result.accounts) == 1 and len(result.account_balances) == 2
    assert [event.cash_movements[0].amount for event in result.events] == [Decimal("-10.00")]
    assert not result.issues


def test_historische_tabellenspalten_text_vor_betrag_und_wiederholter_kopf():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2013
Girokonto
Buchungstag
Kto. / IBAN BLZ / BIC
Alter Saldo 01.01.2013 +100,00
Lastschrift Beispiel -10,00
Referenzzeile
01.01.2013
01.01.2013
Kto. / IBAN BLZ / BIC
Gutschrift Beispiel +5,00
02.01.2013
03.01.2013
Neuer Saldo 31.01.2013 +95,00
""" + _hinweis(Girokonto=IBAN_GIRO)
    result = _parse(text)
    assert [event.cash_movements[0].amount for event in result.events] == [Decimal("-10.00"), Decimal("5.00")]
    assert not result.issues


def test_historischer_seitenkopf_verwirft_nur_unverankerte_seitenrandzeilen():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2013
Girokonto
Buchungstag
Kto. / IBAN BLZ / BIC
Alter Saldo 01.01.2013 +100,00
Seitenfuß
Kontaktzeile
Kto. / IBAN BLZ / BIC
01.01.2013
02.01.2013
Lastschrift -10,00 Beispiel
Neuer Saldo 31.01.2013 +90,00
""" + _hinweis(Girokonto=IBAN_GIRO)
    result = _parse(text)
    assert [event.cash_movements[0].amount for event in result.events] == [Decimal("-10.00")]
    assert not result.issues


def test_historische_tabellenspalten_mehrdeutige_daten_bleiben_offen():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2013
Girokonto
Buchungstag
Kto. / IBAN BLZ / BIC
Alter Saldo 01.01.2013 +100,00
Lastschrift Beispiel -10,00
01.01.2013
02.01.2013
03.01.2013
Neuer Saldo 31.01.2013 +90,00
""" + _hinweis(Girokonto=IBAN_GIRO)
    result = _parse(text)
    assert not result.events
    assert [(issue.code, issue.severity.value) for issue in result.issues] == [("HISTORICAL_BOOKING_LAYOUT_UNSUPPORTED", "ERROR")]


def test_historische_buchungskandidaten_ohne_saldenabgleich_werden_nicht_ausgegeben():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2013
Girokonto
Buchungstag
Kto. / IBAN BLZ / BIC
Alter Saldo 01.01.2013 +100,00
01.01.2013
02.01.2013
Lastschrift -10,00 Beispiel
Neuer Saldo 31.01.2013 +95,00
""" + _hinweis(Girokonto=IBAN_GIRO)
    result = _parse(text)
    assert not result.events
    issue = next(issue for issue in result.issues if issue.code == "HISTORICAL_BOOKING_LAYOUT_UNSUPPORTED")
    assert issue.severity.value == "ERROR"
    assert "1 erkannte Buchungskandidaten" in issue.message
    assert "nicht als Kontobewegungen ausgegeben" in issue.message


def test_historische_tabellenspalten_daten_vor_buchung_und_betrag_im_text():
    text = """comdirect\nFinanzreport Nr. 1 per 01.02.2013
Girokonto
Buchungstag
Kto. / IBAN BLZ / BIC
Alter Saldo 01.01.2013 +100,00
01.01.2013
02.01.2013
Empfänger Beispiel
Referenz Beispiel
Lastschrift -10,00 Beispiel
Referenzzeile
Neuer Saldo 31.01.2013 +90,00
""" + _hinweis(Girokonto=IBAN_GIRO)
    result = _parse(text)
    assert [event.cash_movements[0].amount for event in result.events] == [Decimal("-10.00")]
    assert not result.issues


def test_finanzreport_2007_getrennte_spalten_ohne_iban_erhaelt_buchungen_und_salden():
    text = """comdirect
Ihre Kontonummer:
1234567
Finanzreport Nr. 12 per 31.12.2007
Girokonto
Umsätze
EUR
Buchungstag
Valuta
Soll / Haben
Alter Saldo
+4.277,72
Lastschrift Einzug
04.12.2007
04.12.2007
-24,42
PLUS KLEINE PREISE
Übertrag/Überweisung
05.12.2007
05.12.2007
+1.019,45
Gutschrift Beispiel
Kontoabschluss
31.12.2007
31.12.2007
+3,19
Abschluss Zinsen Kto 123456700EUR
Habenzinsen
Abschlussrechnung 3,19 EUR
Neuer Saldo
+5.275,94
Tagesgeld PLUS
Umsätze
EUR
Buchungstag
Valuta
Soll / Haben
Alter Saldo
+5.001,00
Kontoabschluss
31.12.2007
31.12.2007
+136,88
Abschluss Zinsen Kto 123456705EUR
Habenzinsen
Abschlussrechnung 136,88 EUR
Neuer Saldo
+5.137,88
Tagesgeldkonto
Umsätze
EUR
Buchungstag
Valuta
Soll / Haben
Alter Saldo
0,00
Neuer Saldo
0,00
"""
    result = _parse(text)
    assert result.attributes["layout_path"] == "legacy"
    assert [account.account_name.value for account in result.accounts] == ["Girokonto", "Tagesgeld PLUS", "Tagesgeldkonto"]
    assert [account.account_number.value for account in result.accounts] == ["1234567"] * 3
    assert all(account.iban.value.value == "UNKNOWN" for account in result.accounts)
    assert [event.cash_movements[0].amount for event in result.events] == [Decimal("-24.42"), Decimal("1019.45"), Decimal("3.19"), Decimal("136.88")]
    assert len(result.account_balances) == 6
    assert not result.issues


def test_finanzreport_2007_kontozuordnung_aus_blz_kontonummer_und_kopf_iban():
    text = """comdirect
Ihre Kontonummer: 4764924
Bankleitzahl: 200 411 33
IBAN: DE84 2004 1133 0476 4924 00
Finanzreport Nr. 12 per 31.12.2007
Kontonummer 4764924 / BLZ 20041133
Girokonto
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo +100,00
Neuer Saldo +100,00
Tagesgeld PLUS
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo +50,00
Kontoabschluss 31.12.2007 31.12.2007 +1,00
Abschluss Zinsen Kto 476492405EUR
von 30.09.2007 bis 31.12.2007
Habenzinsen
Neuer Saldo +51,00
Tagesgeldkonto
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo 0,00
Neuer Saldo 0,00
"""
    result = _parse(text)
    accounts = _by_name(result)
    assert accounts["Girokonto"].iban.value == "DE84200411330476492400"
    assert accounts["Girokonto"].account_number.value == "4764924"
    assert accounts["Tagesgeld PLUS"].iban.value == "DE46200411330476492405"
    assert accounts["Tagesgeld PLUS"].account_number.value == "476492405"
    assert accounts["Tagesgeldkonto"].iban.value.value == "UNKNOWN"


def test_finanzreport_2007_widerspruechliche_kopf_iban_wird_nicht_zugeordnet():
    text = """comdirect
Ihre Kontonummer: 4764924
Bankleitzahl: 20041133
IBAN: DE00 2004 1133 0476 4924 00
Finanzreport Nr. 12 per 31.12.2007
Kontonummer 4764924 / BLZ 20041133
Girokonto
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo +100,00
Neuer Saldo +100,00
"""
    result = _parse(text)
    assert _by_name(result)["Girokonto"].iban.value.value == "UNKNOWN"
    assert [issue.code for issue in result.issues] == ["ACCOUNT_IBAN_MISMATCH"]


def test_finanzreport_mit_iban_verwendet_unveraendert_core_parser():
    text = """comdirect
Finanzreport Nr. 7 per 01.02.2026
Girokonto DE00 0000 0000 0000 0000 01
Alter Saldo 01.01.2026 +100,00
02.01.2026 02.01.2026 Gutschrift +10,00
Neuer Saldo 31.01.2026 +110,00
"""
    result = _parse(text)
    assert result.accounts[0].iban.value == IBAN_GIRO.replace(" ", "")
    assert [event.cash_movements[0].amount for event in result.events] == [Decimal("10.00")]
    assert not result.issues


def test_historischer_parser_unterstuetzt_pypdf_kompaktierte_tabellenzeilen():
    text = """comdirect
Ihre Kontonummer: 1234567
Finanzreport Nr. 12 per 31.12.2007
Girokonto ec Tages-/Wochenlimit
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo +100,00
Gutschrift 02.12.2007 02.12.2007 +10,00
Neuer Saldo +110,00
Tagesgeldkonto
Umsätze EUR
Buchungstag Valuta Soll / Haben
Alter Saldo 0,00
Neuer Saldo 0,00
"""
    result = _parse(text)
    assert result.attributes["layout_path"] == "legacy"
    assert [account.account_name.value for account in result.accounts] == ["Girokonto", "Tagesgeldkonto"]
    assert [event.cash_movements[0].amount for event in result.events] == [Decimal("10.00")]
    assert len(result.account_balances) == 4
    assert not result.issues
