# Portman V09 – P0 Steuerdifferenz 417,70 EUR

Stand: 29.10.2026 · Branch `codex/p1-fifo-cost-basis`

## Ergebnis

Der Referenzwert **523,07 EUR ist korrekt und nicht veraltet**. Die 940,77 EUR entstanden durch eine wirtschaftliche Doppelzählung:

| Bestandteil | Vorher | Nachher | Bewertung |
|---|---:|---:|---|
| Steuerpflichtige PDF-Ereignisse nach Teilfreistellung | 515,13 | 515,13 | korrekt |
| Tagesgeldzinsen | 7,94 | 7,94 | korrekt |
| Eigenständige Ertragsgutschrift-PDFs zusätzlich zu denselben Steuerereignissen/Finanzreportbuchungen | 417,70 | 0,00 | Doppelzählung |
| **`other_result`** | **940,77** | **523,07** | **korrigiert** |

Die Differenz ist vollständig: **940,77 − 523,07 = 417,70 EUR**.

## Ursache

Für jede Ausschüttung existieren bis zu drei Belegdarstellungen:

1. Steuerereignis aus der Steuermitteilung – maßgeblich für die steuerpflichtige Bemessungsgrundlage nach Teilfreistellung.
2. Buchung im Finanzreport – maßgeblich für den Geldfluss und bereits mit Depotzuordnung.
3. Eigenständige Ertragsgutschrift – derselbe Geldfluss, aber in der aktuellen Importkonstellation ohne `performance_depot_key`.

Das konservative Matching verlangte bislang auch für die eigenständige Ertragsgutschrift einen identischen Depotschlüssel. Deshalb wurde nur die Finanzreportbuchung mit dem Steuerereignis abgeglichen. Die zusätzliche Ertragsgutschrift blieb steuerlich ungematcht und ihr Bruttobetrag wurde nochmals addiert. Ihre 21 Bruttobeträge ergeben exakt 417,70 EUR.

Die Korrektur akzeptiert eine reine Verrechnungskonto-Darstellung nur dann als weitere Darstellung desselben Steuerereignisses, wenn zugleich folgende Belege übereinstimmen:

- exakte Bankreferenz aus der Steuermitteilung,
- zugeordnetes Verrechnungskonto,
- ISIN/WKN-Alias,
- Brutto- oder Nettobetrag,
- Steuerbetrag und Datumsabstand von höchstens vier Tagen.

Alle so belegten Darstellungen werden aus der steuerlichen Bemessungsgrundlagensumme ausgeschlossen. Für den kanonischen Link bleibt weiterhin genau ein eindeutiger bester Treffer erforderlich. Es wurden weder Cashflows noch Steuerbuchungen erzeugt oder gelöscht.

## Einzelpositionen der korrekten 523,07 EUR

| Datum | Steuerjahr | ISIN | Ertragsart | Steuerpflichtig EUR | PDF-Quelle | Transaktions-/Ereignis-ID |
|---|---:|---|---|---:|---|---|
| 2026-01-02 | 2026 | IE00B48X4842 | Vorabpauschale Ausland | 26,42 | `Steuermitteilung_A1JJTF_(SPDR_MSCI_EM.MAR.SM.C.ETF)_vom_02.01.2026_0B8139.pdf` | `pdf-comdirect-advance-tax-66ac5fcde49da4f87ced9d450b3d4c023147ed96ea621c7665d5a80973677a43` |
| 2026-01-02 | 2026 | IE00BKM4GZ66 | Vorabpauschale Ausland | 96,35 | `Steuermitteilung_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.01.2026_B52E2F.pdf` | `pdf-comdirect-advance-tax-6861f601c6fd979ee310421d1514cdbf9eea0e0f61e29d271fa9a1c0da1d5865` |
| 2026-01-02 | 2026 | LU1681041973 | Vorabpauschale Ausland | 69,47 | `Steuermitteilung_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.01.2026_63460F.pdf` | `pdf-comdirect-advance-tax-a0c0701d3888883a931beee6e4ff2bc122c1bdcb42074c2477464c44398e37dd` |
| 2026-01-15 | 2026 | DE000A0D8Q49 | Ausschüttung Inland | 14,64 | `Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2026_17CC5F.pdf` | `pdf-comdirect-investment-distribution-tax-92c4a85c64618ef9db53609ccdeb8e4ecbff2d01766fa2072ccfb165e557914c` |
| 2026-01-28 | 2026 | IE00B2QWDY88 | Ausschüttung Ausland | 6,72 | `Steuermitteilung_A0Q1YX_(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_28.01.2026_FA84F7.pdf` | `pdf-comdirect-investment-distribution-tax-62f3abc5e41bf7a0b3406e6ddca3233db475229ce23d2f1c4ce702c762574bf5` |
| 2026-02-18 | 2026 | IE000XLJ2JQ9 | Ausschüttung Ausland | 19,98 | `Steuermitteilung_ETF039_(AM.-S+P_SM.C.600_SCR.DLD)_vom_18.02.2026_209479.pdf` | `pdf-comdirect-investment-distribution-tax-c179e4c68ac3d0bad9c382e5c59547608166c7c7e143ed7ce13404e45546d8da` |
| 2026-02-27 | 2026 | IE00B1FZS350 | Ausschüttung Ausland | 22,09 | `Steuermitteilung_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_27.02.2026_8561D1.pdf` | `pdf-comdirect-investment-distribution-tax-1b82c7cc44640fead377e30d55247bc2e3f3fa7b6a9dc1ee42fd780596533553` |
| 2026-03-16 | 2026 | DE000A0D8QZ7 | Ausschüttung Inland | 7,48 | `Steuermitteilung_A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_16.03.2026_269FD6.pdf` | `pdf-comdirect-investment-distribution-tax-0dddb0bdd7e30b5c85a9f78eb061a458b775f27f7be573e709cb43f80cc191fa` |
| 2026-03-16 | 2026 | DE000A0H0744 | Ausschüttung Inland | 1,62 | `Steuermitteilung_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_16.03.2026_C85F10.pdf` | `pdf-comdirect-investment-distribution-tax-953f688cdfe2884ced5cc1fee689405f8420fbaec3cd2787081d0853cb71f1a9` |
| 2026-03-16 | 2026 | DE0005933998 | Ausschüttung Inland | 4,00 | `Steuermitteilung_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_16.03.2026_94F45C.pdf` | `pdf-comdirect-investment-distribution-tax-fd42d9f4084b9bdc1af68a9243424080836888d67ebec84f1a29e98f727f409a` |
| 2026-04-15 | 2026 | DE000A0D8Q49 | Ausschüttung Inland | 15,72 | `Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.04.2026_329554.pdf` | `pdf-comdirect-investment-distribution-tax-5a4c1dd5ddef5eb199c071f4da327b13c884aa29c519c9ffd62b9acbaa1b9b37` |
| 2026-05-08 | 2026 | DE0007164600 | Dividende Inland | 4,49 | `Steuermitteilung_716460_(SAP_SE_O.N.)_vom_08.05.2026_19EC9B.pdf` | `pdf-comdirect-dividend-tax-eba668da7a285861432aa89dd547e108b9240d6ab3ecb3e6dac8da52a664e2c1` |
| 2026-05-27 | 2026 | DE0005785604 | Dividende Inland | 4,07 | `Steuermitteilung_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_27.05.2026_2832C7.pdf` | `pdf-comdirect-dividend-tax-1af3389e126d5694f8376ac1aec95dcb400267aca5140194768671a6cd0e4745` |
| 2026-05-29 | 2026 | IE00B1FZS350 | Ausschüttung Ausland | 27,05 | `Steuermitteilung_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_29.05.2026_F2986C.pdf` | `pdf-comdirect-investment-distribution-tax-68b5ec47ffad5d7a30a5cb45a72f1de276ece06f3de0d4b95ebb8e6f1fb6f456` |
| 2026-06-15 | 2026 | DE000A0D8QZ7 | Ausschüttung Inland | 32,14 | `Steuermitteilung_A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.06.2026_54E44D.pdf` | `pdf-comdirect-investment-distribution-tax-0873a492549ec3fa3fc1883db1bbc1a5ae0bbc46be1b8b8f31975f01dc026890` |
| 2026-06-15 | 2026 | DE000A0H0744 | Ausschüttung Inland | 8,72 | `Steuermitteilung_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_15.06.2026_37FEF0.pdf` | `pdf-comdirect-investment-distribution-tax-0f028982cf5618df4e0c513df4e55af4db09cf50bca133cce3a3d8eec9d4c6a8` |
| 2026-06-15 | 2026 | DE0005933998 | Ausschüttung Inland | 14,40 | `Steuermitteilung_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_15.06.2026_F4C359.pdf` | `pdf-comdirect-investment-distribution-tax-9395be0d5e1da53ffe93098b1182ab2ea3d2110772155d5f3411d4e599c76c01` |
| 2026-07-15 | 2026 | DE000A0D8Q49 | Ausschüttung Inland | 18,05 | `Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.07.2026_EFE375.pdf` | `pdf-comdirect-investment-distribution-tax-dc931a7d648b9cab641c8dd290e292fcab9906822e3412e1811c158dc73a2a4d` |
| 2026-07-29 | 2026 | IE00B2QWDY88 | Ausschüttung Ausland | 8,66 | `Steuermitteilung_A0Q1YX_(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_29.07.2026_9EC77B.pdf` | `pdf-comdirect-investment-distribution-tax-b72b0bba4d9353e3fc276d00f2a8f509b47fd1db28231349cd4cd2f563ee9e53` |
| 2026-08-31 | 2026 | IE00B1FZS350 | Ausschüttung Ausland | 28,62 | `Steuermitteilung_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_31.08.2026_76B982.pdf` | `pdf-comdirect-investment-distribution-tax-1aa58a8b087a879c5f2c044aff779568317b725ae1492d57cd0059620c17251b` |
| 2026-09-15 | 2026 | DE000A0D8QZ7 | Ausschüttung Inland | 39,29 | `Steuermitteilung_A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.09.2026_C3BF64.pdf` | `pdf-comdirect-investment-distribution-tax-0bc7746654cc10342d44d7575a58370c8a164d0870c1562ef73d2bf7a817a72e` |
| 2026-09-15 | 2026 | DE0005933998 | Ausschüttung Inland | 24,60 | `Steuermitteilung_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_15.09.2026_2E8722.pdf` | `pdf-comdirect-investment-distribution-tax-a8fc417256ebfa39c6dd14db365d70499597a2115047c3ed84e8a9d0b5814566` |
| 2026-09-15 | 2026 | DE000A0H0744 | Ausschüttung Inland | 6,37 | `Steuermitteilung_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_15.09.2026_F181E5.pdf` | `pdf-comdirect-investment-distribution-tax-dca10eed3f5057a22b63d8dd234fa5a0d7bdb6e41940828bdd7061aeafe66ca9` |
| 2026-10-15 | 2026 | DE000A0D8Q49 | Ausschüttung Inland | 14,18 | `Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.10.2026_FFCE02 (1).pdf` | `pdf-comdirect-investment-distribution-tax-87576b19faffd7a81629b19d11f15f6b1076115808f3d1f6c2908985630f3e9c` |
| 2026-03-31 | 2026 | – | Tagesgeldzins | 1,97 | `2026-04-01_Finanzreport_Nr._03_6C6287.pdf` | `comdirect-pdf-3f26570372c5e84c277234f34fa7c751be331c0da1bb7c82bba0270e212763c2-1` |
| 2026-06-30 | 2026 | – | Tagesgeldzins | 2,55 | `2026-07-01_Finanzreport_Nr._06_5EA5B6.pdf` | `comdirect-pdf-96887fe8d1e8c0c7ba353156e0ad43e7969950a278c0c67ed3cc7ff701849e6a-1` |
| 2026-09-30 | 2026 | – | Tagesgeldzins | 3,42 | `2026-10-01_Finanzreport_Nr._09_5FCE8E.pdf` | `comdirect-pdf-bdd7a95c01eb93b10c131e6bfad2eadeb382dbad66c9039b6745ad568edd7f31-1` |
| **Summe** | | | | **523,07** | | |

Die drei Vorabpauschalen betreffen das Ertragsjahr 2025, sind laut Beleg aber am 02.01.2026 steuerlich zugeflossen und korrekt dem Steuerjahr 2026 zugeordnet. Bei Fonds-Ausschüttungen ist bereits die Bemessungsgrundlage nach Teilfreistellung enthalten; die Teilfreistellung wird nicht nochmals abgezogen.

## Vollständige Differenz 417,70 EUR

Diese Zeilen wurden vor der Korrektur zusätzlich als steuerpflichtiges Brutto berücksichtigt. Nach der Korrektur bleiben sie als Cash-/Belegnachweis erhalten, tragen zu `other_result` aber jeweils 0 EUR bei.

| Datum | Steuerjahr | ISIN | Falsch zusätzlich EUR | PDF-Quelle | Transaktions-ID |
|---|---:|---|---:|---|---|
| 2026-01-19 | 2026 | DE000A0D8Q49 | 20,92 | `Ertragsgutschrift_38,526_St._A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2026_D86D99.pdf` | `pdf-income-36f78ec35348683ad3bf99495f8db0381aa1ca41b9b0f56c8b93e188f92494fa` |
| 2026-01-30 | 2026 | IE00B2QWDY88 | 6,73 | `Ertragsgutschrift_17_St._A0Q1YX_(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_28.01.2026_022DD7.pdf` | `pdf-income-4eb2ee8fc643cff47eaf7a943efb60b01f68d706554d572303b8ede9861d7f9c` |
| 2026-02-20 | 2026 | IE000XLJ2JQ9 | 28,55 | `Ertragsgutschrift_42,759_St._ETF039_(AM.-S+P_SM.C.600_SCR.DLD)_vom_18.02.2026_144D34.pdf` | `pdf-income-e773a17fd889fea74406729c00458dfd6aee018af1a64b4d47e8c31c703d56b9` |
| 2026-03-03 | 2026 | IE00B1FZS350 | 22,09 | `Ertragsgutschrift_151,326_St._A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_27.02.2026_9A3FCB.pdf` | `pdf-income-641dac85ad6f51bc624b9267b333290aeba2f05115ca607881f3a395a19d7e97` |
| 2026-03-16 | 2026 | DE0005933998 | 5,72 | `Ertragsgutschrift_38,382_St._593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_16.03.2026_6AED75.pdf` | `pdf-income-1c94451a2a09427ec438ab51f63a3471bd1d8abf2aaef84e938ae1f4bfd4342d` |
| 2026-03-16 | 2026 | DE000A0D8QZ7 | 10,69 | `Ertragsgutschrift_101,307_St._A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_16.03.2026_E0C028.pdf` | `pdf-income-2e78688f66aac50cfff87473630cd0a7044da41e885834ada27fdb82b03d4b7f` |
| 2026-03-16 | 2026 | DE000A0H0744 | 2,31 | `Ertragsgutschrift_26,122_St._A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_16.03.2026_9461C8.pdf` | `pdf-income-2f812ad408288c4e7a321e7ff0db8a899cf0116f1350e3cdeb82b868ce38c641` |
| 2026-04-17 | 2026 | DE000A0D8Q49 | 22,46 | `Ertragsgutschrift_38,526_St._A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.04.2026_E2E2F8.pdf` | `pdf-income-304ac5dedd554642cfe34bb0c479537d7ddb875774f913459c0d33751072702f` |
| 2026-05-08 | 2026 | DE0007164600 | 4,49 | `Dividendengutschrift_1,794_St._716460_(SAP_SE_O.N.)_vom_08.05.2026_1D5759.pdf` | `pdf-income-b198ea16911a77534b9edd32fb1c2e6a3fc424081370d7ce06b744a28a8d79ea` |
| 2026-05-27 | 2026 | DE0005785604 | 4,07 | `Dividendengutschrift_3,878_St._578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_27.05.2026_2D385D.pdf` | `pdf-income-0976e97d208bb3853acaa90435fea63a9030403559315da84fb65988ddabe13c` |
| 2026-06-02 | 2026 | IE00B1FZS350 | 27,05 | `Ertragsgutschrift_151,326_St._A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_29.05.2026_55EA7A.pdf` | `pdf-income-c752bd33db80d4ad9a28158647fb9e0ab5b37bca6a3684b937cb564c546261cc` |
| 2026-06-15 | 2026 | DE000A0H0744 | 12,46 | `Ertragsgutschrift_26,122_St._A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_15.06.2026_AE976E.pdf` | `pdf-income-4d98a7c8ecb57058acd0c212cf42194661a2eaf69906f965ca1c214944e642bf` |
| 2026-06-15 | 2026 | DE000A0D8QZ7 | 45,91 | `Ertragsgutschrift_101,307_St._A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.06.2026_6FE2F0.pdf` | `pdf-income-78e1b93c926011adb57112e3d6ff0d9ff944927a20198837678e8a15718ebaf2` |
| 2026-06-15 | 2026 | DE0005933998 | 20,57 | `Ertragsgutschrift_38,382_St._593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_15.06.2026_BAD922.pdf` | `pdf-income-b2c09f4c3d77faa8e287ab387ae0d3cecd80adf8e6a37e02d9ceb07ce1aa3404` |
| 2026-07-17 | 2026 | DE000A0D8Q49 | 25,78 | `Ertragsgutschrift_38,526_St._A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.07.2026_255137.pdf` | `pdf-income-9f3ab515094e61222799b99cf1ef0bbf67c5ddd57569d9638274db464556a009` |
| 2026-07-31 | 2026 | IE00B2QWDY88 | 8,66 | `Ertragsgutschrift_17_St._A0Q1YX_(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_29.07.2026_AB9F7A.pdf` | `pdf-income-9ec95e3e55267a578c8d992ac46c53489dcd8da2ca124e44059f0178e5a01719` |
| 2026-09-02 | 2026 | IE00B1FZS350 | 28,62 | `Ertragsgutschrift_152,090_St._A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_31.08.2026_DF4027.pdf` | `pdf-income-b2e6332963f1f63de60fd9332eb735baf2b1f33a8785cedcefd1d8aafac34774` |
| 2026-09-15 | 2026 | DE0005933998 | 35,15 | `Ertragsgutschrift_39,002_St._593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_15.09.2026_C104EA.pdf` | `pdf-income-4f6604a1cf888eacbc0872286060ee6173385bff0d63d5af502ad3d981d5c3e4` |
| 2026-09-15 | 2026 | DE000A0D8QZ7 | 56,12 | `Ertragsgutschrift_102,038_St._A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.09.2026_AD1E3B.pdf` | `pdf-income-eb0a2fd532b58f0b691ab4d95d757dfe3aaae348f3b98db57ddd894ebdb88b5a` |
| 2026-09-15 | 2026 | DE000A0H0744 | 9,10 | `Ertragsgutschrift_27,051_St._A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_15.09.2026_1D2E10.pdf` | `pdf-income-fa38faadcd18e2d91f91ba0616d65056c87ff7a7aa9d2c3546a074e55ac50b40` |
| 2026-10-19 | 2026 | DE000A0D8Q49 | 20,25 | `Ertragsgutschrift_39,011_St._A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.10.2026_111007.pdf` | `pdf-income-14a2829d465abcacd697cb1e860e4509aa3b838eb624d1ddb767a3f8ac84da3c` |
| **Summe** | | | **417,70** | | |

## Weitere Prüfungen

- **Doppelte Ausschüttungen:** exakt die oben aufgeführten 21 Ertragsgutschriften; jede ist über Referenz, Wertpapier, Betrag, Datum und Verrechnungskonto einer bereits erfassten Ausschüttung zugeordnet.
- **Finanzreport-/Steuerbeleg-Verknüpfung:** 20 Ausschüttungen besitzen einen passenden Finanzreporttreffer; die Oktober-Ausschüttung besitzt eine direkte Zahlungs-/Steuerbelegverknüpfung. Zusätzliche Ertragsgutschriften sind keine weiteren Erträge.
- **Jahreszuordnung:** alle 48 zuvor beitragenden Zeilen gehören steuerlich zu 2026. Die Vorabpauschalen weisen korrekt `income_year=2025`, aber `tax_year=2026` aus.
- **Teilfreistellung:** 417,70 EUR ist die Summe der Ausschüttungs-Bruttobeträge. Die korrekte steuerpflichtige Summe der Ausschüttungen beträgt nach belegter Teilfreistellung 322,89 EUR; zusammen mit 192,24 EUR Vorabpauschalen ergeben sich 515,13 EUR Wertpapiererträge.
- **Neu hinzugekommene PDFs:** Der aktuelle 126-PDF-Korpus enthält eigenständige Ertragsgutschriften zusätzlich zu Finanzreports und Steuermitteilungen. Sie liefern zusätzliche Belege, aber keine zusätzlichen wirtschaftlichen Vorgänge. Der unabhängige Steuerdetail-CSV-Export mit 39 Zeilen bestätigt weiterhin 523,07 EUR.

## Codeänderung

- `src/portman/tax_matching.py`: alle streng belegten Cash-Darstellungen eines Steuerereignisses werden ermittelt; reine Verrechnungskonto-Belege sind nur mit exakter Bankreferenz zulässig.
- `src/portman/tax_overview.py`: sämtliche belegten Darstellungen werden aus der zusätzlichen Bruttoaggregation ausgeschlossen; der kanonische Link bleibt eindeutig und konservativ.
- `tests/test_comdirect_p1_integrity.py`: Regressionstest für Finanzreport + eigenständige Ertragsgutschrift + Steuermitteilung.

Der Testreferenzwert 523,07 EUR wurde nicht verändert.

## Testergebnisse

- Gezielte Steuer-/Matching-Suite: **23 bestanden**.
- Realimport `finance-first` und `notices-first`, jeweils einschließlich identischem Zweitimport nach Integration von PR #42: **2 bestanden**, 422,65 s.
- Vollständige Pytest-Suite nach Integration von PR #42: **1.269 bestanden, 19 übersprungen**, 427,68 s.

Produktive Datenbank und Original-PDFs wurden nicht verändert. Sämtliche Schreibvorgänge erfolgten auf temporären SQLite-Datenbanken.
