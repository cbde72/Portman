# Portman – PDF-Parser-Audit V2

- Datum (UTC): `2026-10-25T09:28:51.763030+00:00`
- Quellverzeichnis: `C:\Users\chris\Desktop\history`
- Modus: `targeted`; OCR: `True`; Parser-Fingerprint: `ad82dfb95b4bc879`
- PDFs im Scope: **58**; eindeutige SHA-256: **58**; Cache-Treffer: **0**
- Plugin-Ladefehler: **0**; Scanfehler: **0**

## Schweregrade

| Grad | PDFs |
|---|---:|
| ERROR | 5 |
| WARNING | 53 |
| INFO | 0 |
| PASS | 0 |

## Befunde (pro Dokument, Kategorien können mehrfach vorkommen)

| Kategorie | Dokumente |
|---|---:|
| `DIVIDEND_TAX` | 58 |
| `OCR_LAYOUT` | 52 |

## Parser/Handler

| Plugin | Handler | Dateien | Fehler | Warnungen |
|---|---|---:|---:|---:|
| `(kein Plugin)` | `-` | 5 | 5 | 0 |
| `user.comdirect-ertraege` | `investment_ausschuettung` | 53 | 0 | 53 |

## Vergleich mit Baseline

Verglichen: **58**, Verbesserungen: **53**, Regressionen: **0**, veränderte Befunde: **53**, neu: **0**.
**Teillauf:** Nicht im Scope enthaltene PDFs gelten nicht als entfernt.

### Regressionen (max. 100, vollständige Liste in delta.csv)


### Verbesserungen (max. 100, vollständige Liste in delta.csv)

- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_01.09.2016_9773FE.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.03.2016_47CFE1.pdf`: ERROR → WARNING (DIVIDEND_TAX → DIVIDEND_TAX)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.03.2017_3E44BE.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.06.2016_31FDE8.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.06.2017_1FD193.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.09.2016_651926.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.09.2017_5BF375.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.12.2016_62961F.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.12.2017_AB6366.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_27.04.2017_B8A274.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2016_BFE1E3.pdf`: ERROR → WARNING (DIVIDEND_TAX → DIVIDEND_TAX)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2021_A48D0D.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.04.2016_B630EC.pdf`: ERROR → WARNING (DIVIDEND_TAX → DIVIDEND_TAX)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.07.2016_BF5810.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_16.10.2017_1AD226.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_17.01.2017_E6ADCF.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_17.07.2017_7FE89F.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_17.10.2016_F83501.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_18.04.2017_E45FC8.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_23.09.2016_7897D3.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_27.04.2017_595FEB.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_01.09.2016_8E04F6.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.03.2016_F8D129.pdf`: ERROR → WARNING (DIVIDEND_TAX → DIVIDEND_TAX)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.03.2017_C3EE7F.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.06.2016_ED9C53.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.06.2017_03AB13.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.09.2016_6C0B9B.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.09.2017_ED837C.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.12.2016_0C1249.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.12.2017_BA1943.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_27.04.2017_89EA7C.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.03.2016_392251.pdf`: ERROR → WARNING (DIVIDEND_TAX → DIVIDEND_TAX)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.03.2017_B675DB.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.06.2016_13795B.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.06.2017_4E7760.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.09.2016_4E0CE8.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.09.2017_76CE80.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.12.2016_1D8305.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.12.2017_14489E.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_27.04.2017_A7214E.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISH.II.DEV.M.PR.Y.U.ETF)_vom_30.08.2016_5615AD.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_28.02.2017_72E6EC.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_28.11.2016_F1FA97.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_30.11.2017_F15BF9.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_31.05.2017_3E9EC0.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_31.08.2017_E1DFA3.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LGQL(ISII-DEV.M.PR.YLD.U.ETFDZ)_vom_29.02.2016_FB1A06.pdf`: ERROR → WARNING (DIVIDEND_TAX → DIVIDEND_TAX)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LGQL(ISII-DEV.M.PR.YLD.U.ETFDZ)_vom_31.05.2016_E46226.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0Q1YX(ISHSIII-MSCIJP.SC_UC.ETFD)_vom_29.07.2016_5FC73F.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0Q1YX(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_27.01.2017_610D58.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0Q1YX(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_31.07.2017_625F1B.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_ETF074(COMST.-S.E.600R.ES.UETF_I)_vom_28.12.2017_87DA8A.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)
- `comdirect/Steuermitteilungen/Steuermitteilung_WKN_ETF074(COMST.-S.E.600R.ES.UETF_I)_vom_30.08.2017_36D720.pdf`: ERROR → WARNING (DIVIDEND_TAX,OCR_LAYOUT → DIVIDEND_TAX,OCR_LAYOUT)

## Einzelbefunde

Vollständig in `findings.csv` (jede Meldung einzeln), `files.csv` und `audit.json`. Der Markdownbericht enthält nur die ersten 150 ERROR/ WARNING-Dateien.

- **ERROR** `comdirect/Steuermitteilungen/Steuermitteilung_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_23.05.2023_64A5A5.pdf` · `/` · DIVIDEND_TAX, OCR_LAYOUT
- **ERROR** `comdirect/Steuermitteilungen/Steuermitteilung_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_28.05.2025_8E6638.pdf` · `/` · DIVIDEND_TAX, OCR_LAYOUT
- **ERROR** `comdirect/Steuermitteilungen/Steuermitteilung_716460_(SAP_SE_O.N.)_vom_16.05.2023_53BEC6.pdf` · `/` · DIVIDEND_TAX, OCR_LAYOUT
- **ERROR** `comdirect/Steuermitteilungen/Steuermitteilung_716460_(SAP_SE_O.N.)_vom_16.05.2025_685BB6.pdf` · `/` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_01.09.2016_9773FE.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.03.2016_47CFE1.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.03.2017_3E44BE.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.06.2016_31FDE8.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.06.2017_1FD193.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.09.2016_651926.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.09.2017_5BF375.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.12.2016_62961F.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_15.12.2017_AB6366.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399(ISH.S.EUROP.MID_200_U.ETF)_vom_27.04.2017_B8A274.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2016_BFE1E3.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2021_A48D0D.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.04.2016_B630EC.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.07.2016_BF5810.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_16.10.2017_1AD226.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_17.01.2017_E6ADCF.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_17.07.2017_7FE89F.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_17.10.2016_F83501.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_18.04.2017_E45FC8.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_23.09.2016_7897D3.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_27.04.2017_595FEB.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_01.09.2016_8E04F6.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.03.2016_F8D129.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.03.2017_C3EE7F.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.06.2016_ED9C53.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.06.2017_03AB13.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.09.2016_6C0B9B.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.09.2017_ED837C.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.12.2016_0C1249.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.12.2017_BA1943.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ(ISH.S.EUR.SMALL_200_U.ETF)_vom_27.04.2017_89EA7C.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.03.2016_392251.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.03.2017_B675DB.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.06.2016_13795B.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.06.2017_4E7760.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.09.2016_4E0CE8.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.09.2017_76CE80.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.12.2016_1D8305.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_15.12.2017_14489E.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074(IS.DJ_AS.PAC.S.D.30_U.ETF)_vom_27.04.2017_A7214E.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISH.II.DEV.M.PR.Y.U.ETF)_vom_30.08.2016_5615AD.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_28.02.2017_72E6EC.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_28.11.2016_F1FA97.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_30.11.2017_F15BF9.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_31.05.2017_3E9EC0.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_31.08.2017_E1DFA3.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LGQL(ISII-DEV.M.PR.YLD.U.ETFDZ)_vom_29.02.2016_FB1A06.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LGQL(ISII-DEV.M.PR.YLD.U.ETFDZ)_vom_31.05.2016_E46226.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0Q1YX(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_27.01.2017_610D58.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0Q1YX(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_31.07.2017_625F1B.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0Q1YX(ISHSIII-MSCIJP.SC_UC.ETFD)_vom_29.07.2016_5FC73F.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **ERROR** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A3MQQ1(FRESENIUS_SE+CO._DIV.CASH)_vom_13.06.2022_86D3A3.pdf` · `/` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_ETF074(COMST.-S.E.600R.ES.UETF_I)_vom_28.12.2017_87DA8A.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT
- **WARNING** `comdirect/Steuermitteilungen/Steuermitteilung_WKN_ETF074(COMST.-S.E.600R.ES.UETF_I)_vom_30.08.2017_36D720.pdf` · `user.comdirect-ertraege/investment_ausschuettung` · DIVIDEND_TAX, OCR_LAYOUT

## Grenzen

- Klassifikationen sind regelbasierte Priorisierung, **kein** Beweis, dass Beträge fachlich korrekt oder fehlerhaft sind.
- `INFO` umfasst z. B. normale Plugin-Erkennungsnachrichten; `WARNING` enthält auffällige Vorzeichen und Brutto-Netto-Werte.
- Die Suite führt `parse_pdf()` aus und schreibt keinerlei Portman-Datenbankeinträge.
- Optionaler Cache nutzt Dateigröße, mtime_ns, SHA-256, OCR-Modus und Parser-Fingerprint; SHA wird auch bei Cache-Treffern neu berechnet.
- Für schnelle gezielte Läufe `--only-errors`, `--plugin` und `--issue-code` verwenden; mit `--compare` zu V1/V2 vergleichen.
- Historische Baselines unter `test_reports` unverändert aufbewahren. Berichte nicht öffentlich teilen (Dateinamen/Belegdetails).
