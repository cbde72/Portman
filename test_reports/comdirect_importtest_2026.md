# Portman V09 – Rekursiver comdirect-Importtest 2026

- Quelle: `C:\Users\chris\Desktop\history\comdirect\2026`
- Geprüfte PDFs: **102**
- Erfolgreich: **54**
- Fehlerhaft: **3**
- Nicht unterstützt (generischer Fallback): **45**
- Testmodus: `portfolio_v5.pdf_importer.parse_pdf()` mit den tatsächlich registrierten Plugins, ohne Repository/SQLite und ohne dauerhafte Imports.
- Original-PDFs wurden ausschließlich gelesen und nicht verändert.

## Fehler

| Vollständiger Dateipfad | Erkanntes Plugin | Dokumenttyp | Fehlermeldung | Vermutete Ursache |
|---|---|---|---|---|
| C:\Users\chris\Desktop\history\comdirect\2026\Abrechungen\Wertpapierabrechnung_Kauf_0,147_St._A0S9GB_(DT.BOERSE_COM._XETRA-GOLD)_vom_23.09.2026_C80685.pdf | user.comdirect-ertraege (Erkennung; Metadaten wegen Parserfehler nicht finalisiert) | comdirect Wertpapierabrechnung Kauf | PDF konnte nicht gelesen werden: Wertpapier, Geschäftstag, Valuta, IBAN oder Endbetrag nicht erkannt. | Das Layout liefert dem Trade-Parser mindestens eines der Pflichtfelder Wertpapier/Geschäftstag/Valuta/IBAN/Endbetrag nicht in der erwarteten Form. |
| C:\Users\chris\Desktop\history\comdirect\2026\Abrechungen\Wertpapierabrechnung_Kauf_0,221_St._716460_(SAP_SE_O.N.)_vom_23.07.2026_9A3D65.pdf | user.comdirect-ertraege (Erkennung; Metadaten wegen Parserfehler nicht finalisiert) | comdirect Wertpapierabrechnung Kauf | PDF konnte nicht gelesen werden: Steuerliche Stückzahl 0.221 ist vorhanden, kann aber ohne Kurs und Kurswert der Geschäftsabrechnung nicht plausibilisiert werden; Dokument nicht automatisch verbucht. | Nur die steuerliche Stückzahl wird erkannt; Geschäftsabrechnungsblock mit Kurs und Kurswert wird vom regulären Ausdruck nicht gefunden. |
| C:\Users\chris\Desktop\history\comdirect\2026\Abrechungen\Wertpapierabrechnung_Kauf_0,63_St._A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_07.09.2026_0E8E2E.pdf | user.comdirect-ertraege (Erkennung; Metadaten wegen Parserfehler nicht finalisiert) | comdirect Wertpapierabrechnung Kauf | PDF konnte nicht gelesen werden: Steuerliche Stückzahl 0.630 ist vorhanden, kann aber ohne Kurs und Kurswert der Geschäftsabrechnung nicht plausibilisiert werden; Dokument nicht automatisch verbucht. | Nur die steuerliche Stückzahl wird erkannt; Geschäftsabrechnungsblock mit Kurs und Kurswert wird vom regulären Ausdruck nicht gefunden. |

## Zusammenfassung nach Dokumenttyp

| Dokumenttyp | Status | Anzahl |
|---|---:|---:|
| Steuerbescheinigung | nicht unterstützt | 10 |
| Unbekanntes Dokument | nicht unterstützt | 12 |
| Wertpapierabrechnung | nicht unterstützt | 23 |
| comdirect Finanzreport | erfolgreich | 10 |
| comdirect Steuermitteilung Vorabpauschale | erfolgreich | 6 |
| comdirect Wertpapierabrechnung Kauf | erfolgreich | 38 |
| comdirect Wertpapierabrechnung Kauf | fehlerhaft | 3 |

## Zusammenfassung nach Plugin

| Plugin | Status | Anzahl |
|---|---:|---:|
| comdirect.finanzreport | erfolgreich | 10 |
| generic.kontoauszug | nicht unterstützt | 45 |
| user.comdirect-ertraege | erfolgreich | 44 |
| user.comdirect-ertraege (Erkennung; Metadaten wegen Parserfehler nicht finalisiert) | fehlerhaft | 3 |

## Nicht unterstützte Dokumente

- Steuerbescheinigung: **10**
- Unbekanntes Dokument: **12**
- Wertpapierabrechnung: **23**

Diese Dateien wurden von `parse_pdf()` gelesen, aber nur durch `generic.kontoauszug` behandelt; damit liegt kein belastbarer strukturierter Fachimport vor. Die vollständigen Pfade stehen in der CSV. Die 23 generischen Wertpapierabrechnungen liegen sämtlich unter `Kosteninformationen`; sie sind Kosteninformationsblätter, keine ausgeführten Trades.

## Dubletten

Es wurden **9 Gruppen / 18 Dateien** mit identischem SHA-256-Inhalt gefunden:

1. `C:\Users\chris\Desktop\history\comdirect\2026\2026-10-01_Finanzreport_Nr._09_5FCE8E.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Januar\2026-10-01_Finanzreport_Nr._09_5FCE8E.pdf`
2. `C:\Users\chris\Desktop\history\comdirect\2026\Abrechungen\Wertpapierabrechnung_Kauf_0,006_St._LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_07.01.2026_33E4AB.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Januar\Wertpapierabrechnung_Kauf_0,006_St._LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_07.01.2026_33E4AB.pdf`
3. `C:\Users\chris\Desktop\history\comdirect\2026\Abrechungen\Wertpapierabrechnung_Kauf_0,227_St._A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.01.2026_E842CB.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Januar\Wertpapierabrechnung_Kauf_0,227_St._A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.01.2026_E842CB.pdf`
4. `C:\Users\chris\Desktop\history\comdirect\2026\Abrechungen\Wertpapierabrechnung_Kauf_0,667_St._LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.01.2026_C64D27.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Januar\Wertpapierabrechnung_Kauf_0,667_St._LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.01.2026_C64D27.pdf`
5. `C:\Users\chris\Desktop\history\comdirect\2026\Januar\Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2026_17CC5F.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Steuerinformationen\Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2026_17CC5F.pdf`
6. `C:\Users\chris\Desktop\history\comdirect\2026\Januar\Steuermitteilung_A0Q1YX_(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_28.01.2026_FA84F7.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Steuerinformationen\Steuermitteilung_A0Q1YX_(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_28.01.2026_FA84F7.pdf`
7. `C:\Users\chris\Desktop\history\comdirect\2026\Januar\Steuermitteilung_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.01.2026_B52E2F.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Steuerinformationen\Steuermitteilung_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.01.2026_B52E2F.pdf`
8. `C:\Users\chris\Desktop\history\comdirect\2026\Januar\Steuermitteilung_A1JJTF_(SPDR_MSCI_EM.MAR.SM.C.ETF)_vom_02.01.2026_0B8139.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Steuerinformationen\Steuermitteilung_A1JJTF_(SPDR_MSCI_EM.MAR.SM.C.ETF)_vom_02.01.2026_0B8139.pdf`
9. `C:\Users\chris\Desktop\history\comdirect\2026\Januar\Steuermitteilung_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.01.2026_63460F.pdf`  
   `C:\Users\chris\Desktop\history\comdirect\2026\Steuerinformationen\Steuermitteilung_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.01.2026_63460F.pdf`

Zusätzlich zeigen die Finanzreports mehrere unbrauchbare extrahierte `transaction_reference`-Werte (`:`, `belastung`, `ntgelt`, `konto 476492405`). Diese sind keine stabilen Geschäftsreferenzen und dürfen nicht zur fachlichen Dublettenerkennung verwendet werden. Belastbare alphanumerische Referenzen und externe IDs der identischen Kopien stimmen dagegen überein.

## Fachliche Prüfungen

- Erfolgreich strukturierte Käufe/Verkäufe: **38**; alle vorhandenen Stückzahl/Kurs/Kurswert- und Abrechnungsbetrag-Kombinationen lagen innerhalb 0,01 EUR Toleranz.
- Gebührenstatus der 38 Trades: **29** mit nachgewiesenen 0,00 EUR, **9** mit positiven Gebühren, **0** unbekannt.
- Steuern sind bei **38** Trades unbekannt (`null`), nicht nachgewiesene 0,00 EUR. Dadurch ist die Abrechnung nur soweit vollständig prüfbar, wie der Beleg Gebühren/Steuern explizit ausweist.
- WKN, ISIN, Name, Stückzahl, Kurs, Kurswert, Gebühren, Steuern, Gesamtbetrag und Datumsfelder sind je Datei in der CSV-Spalte `parsed_data` vollständig serialisiert.

## Empfehlungen für Parserkorrekturen (noch nicht umgesetzt)

1. Für A111X9 und 716460 die Erkennung des Geschäftsabrechnungsblocks gegen die tatsächliche pypdf/OCR-Zeilenfolge härten: Feldlabels unabhängig von Reihenfolge und variablen Zwischenräumen lesen; Kurs und Kurswert weiterhin gemeinsam verlangen und rechnerisch validieren.
2. Für A0S9GB Pflichtfelder einzeln diagnostizieren, statt einer Sammelfehlermeldung. Reguläre Ausdrücke für Wertpapierzeile, Geschäftstag, Valuta/IBAN und `Zu Ihren Lasten` gegen diesen Layoutjahrgang ergänzen. Keine Werte aus Dateinamen ableiten.
3. Einen spezialisierten comdirect-Kosteninformations-Parser ergänzen. Kosteninformationen strikt als Prognose/Ex-ante-Kosten modellieren und niemals als tatsächliche Transaktionsgebühr oder Trade verbuchen.
4. Die zehn generisch behandelten Steuerbescheinigungen nur dann strukturieren, wenn ein eigener Dokumenttyp mit verlustfreier Quellenabbildung vorhanden ist; bis dahin weiter als nicht unterstützt kennzeichnen.
5. `extract_bank_reference()` und die Finanzreport-Normalisierung müssen Platzhalter und Textfragmente wie `:`, `belastung`, `ntgelt` und reine Kontobezeichnungen verwerfen. Dublettenabgleich nur mit validierter Referenz plus Betrag/Datum/Konto oder identischem Dateihash.
6. Regressionstests mit genau den drei Fehler-PDFs sowie den neun identischen Dateipaaren ergänzen. Erwartung: keine dauerhafte Speicherung, keine Doppelzählung, `null` bleibt unbekannt und wird nicht zu 0,00.

## Methodik und CSV

- Status `fehlerhaft`: Parserfehler oder harte fachliche Inkonsistenz.
- Status `nicht unterstützt`: PDF lesbar, aber nur generischer Fallback ohne spezialisierten Fachparser.
- SHA-256 und dokumentierte Referenzen wurden nur diagnostisch ausgewertet; keine Dateien wurden zusammengeführt.
- Die CSV enthält Warnungen, Fehler, Prüfhinweise und sämtliche Parserobjekte als JSON.
