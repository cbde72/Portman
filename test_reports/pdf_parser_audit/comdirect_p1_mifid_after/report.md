# Portman – PDF-Parser-Audit V2

- Datum (UTC): `2026-10-25T09:25:08.581563+00:00`
- Quellverzeichnis: `C:\Users\chris\Desktop\history`
- Modus: `targeted`; OCR: `True`; Parser-Fingerprint: `708ab7eb14583628`
- PDFs im Scope: **102**; eindeutige SHA-256: **102**; Cache-Treffer: **0**
- Plugin-Ladefehler: **0**; Scanfehler: **0**

## Schweregrade

| Grad | PDFs |
|---|---:|
| ERROR | 0 |
| WARNING | 102 |
| INFO | 0 |
| PASS | 0 |

## Befunde (pro Dokument, Kategorien können mehrfach vorkommen)

| Kategorie | Dokumente |
|---|---:|
| `MIFID_COST` | 102 |
| `UNCLASSIFIED_WARNING` | 102 |

## Parser/Handler

| Plugin | Handler | Dateien | Fehler | Warnungen |
|---|---|---:|---:|---:|
| `user.comdirect-ertraege` | `kosteninformation_mifid_ii` | 102 | 0 | 102 |

## Vergleich mit Baseline

Verglichen: **102**, Verbesserungen: **102**, Regressionen: **102**, veränderte Befunde: **102**, neu: **0**.
**Teillauf:** Nicht im Scope enthaltene PDFs gelten nicht als entfernt.

### Regressionen (max. 100, vollständige Liste in delta.csv)

- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_593399_vom_04.03.2022_71E068.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_03.12.2022_39D0BF.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.02.2023_7FDD1F.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.03.2022_E7EFE2.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.03.2023_5CAD29.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_05.01.2023_3B88FB.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_06.01.2023_88BDC0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_10.07.2023_F3FB72.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_22.04.2023_39F0D7.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_03.12.2022_3FD9E7.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.02.2023_DE3CB5.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.03.2022_226712.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.03.2023_EEF006.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_05.01.2023_A6CDBA.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_06.01.2023_AE77C8.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_22.04.2023_F20853.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0Q1YX_vom_10.07.2023_B193E0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_03.12.2022_0B2265.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.02.2023_46B815.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.03.2022_E8CD81.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.03.2023_A330C8.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_05.01.2023_52DC66.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_06.01.2023_B82F79.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_10.07.2023_280378.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_15.05.2023_7CAAF0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_22.04.2023_66A388.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_03.12.2022_142B5A.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_04.02.2023_1C4D09.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_04.03.2023_853EBA.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_05.01.2023_83F648.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_06.01.2023_70F9AD.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_22.04.2023_F741D4.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_04.02.2023_544F25.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_15.05.2023_9C7C6A.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_22.04.2023_E9BB9B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_05.01.2023_B4A4B6.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_06.01.2023_DFABB9.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_15.05.2023_954971.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_22.04.2023_3F67A0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A2N84X_vom_10.07.2023_34B86B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_LYX05A_vom_22.04.2023_D16575.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amazon_WKN_906866_vom_02.05.2020_3E1630.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_15.08.2023_382A7F.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_27.05.2024_DA532B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_01.06.2023_4D864C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_10.01.2019_24E64C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_18.03.2020_CAFF9B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_20.11.2019_CFA5EE.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_29.10.2019_6B4ED8.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_20.11.2019_79FB21.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_29.09.2019_910ACD.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_30.05.2020_1AD653.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_31.08.2020_A7E824.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_20.11.2019_8D8D5B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_29.09.2019_C5E0F5.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_30.05.2020_A82849.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_03.06.2021_92CBA5.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_25.02.2022_8E2273.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_30.01.2022_EC4E6F.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_13.04.2019_565727.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_26.02.2019_8CA417.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_26.03.2019_DD36A1.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_13.04.2019_45C6C3.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_26.02.2019_7A4BB0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_26.03.2019_A09233.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_30.01.2019_7CB5C0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Fresenius_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_02.04.2024_740090.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Fresenius_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_27.05.2024_EDCFF7.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Immo_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_30.01.2024_1C4A1E.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Immo_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_30.06.2024_C24D39.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Kauf_12_St._WKN_A0JK68_vom_29.09.2019_D0C6CD.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Kauf_20_St._WKN_A1JSHV_vom_06.01.2023_788BE8.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_MSCI_JAPAN_UCITS_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_01.02.2025_050F8D.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_SAP_716460_(SAP_SE_O.N.)_vom_02.04.2024_0D0929.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_SAP_716460_(SAP_SE_O.N.)_vom_27.05.2024_31A045.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_Nr._37_LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_31.12.2025_94866C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_593399_vom_02.09.2021_B77CCF.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A0JK68_vom_02.09.2021_4C698A.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A0S9GB_vom_02.09.2021_9DF9E7.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A2H57N_vom_10.01.2019_E6DA2C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_US_div_WKN_A0D8Q4_vom_05.07.2020_A1FDEA.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_03.10.2021_D53682.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_25.02.2022_BD56EE.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_30.01.2022_CFFC61.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_10.12.2020_05C62D.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_26.01.2021_8EB601.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_29.11.2020_10219C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_02.09.2021_482D29.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_10.12.2020_1C6125.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_26.01.2021_B685D9.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_29.11.2020_A59498.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_03.10.2021_857318.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_10.12.2020_B07E9A.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_25.02.2022_CD4C85.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_26.01.2021_B11CAC.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_29.11.2020_F69C1C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_30.01.2022_63F2DB.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_02.09.2021_88C891.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_03.10.2021_FDF5CC.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_25.02.2022_DF7AD4.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)

### Verbesserungen (max. 100, vollständige Liste in delta.csv)

- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_593399_vom_04.03.2022_71E068.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_03.12.2022_39D0BF.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.02.2023_7FDD1F.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.03.2022_E7EFE2.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.03.2023_5CAD29.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_05.01.2023_3B88FB.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_06.01.2023_88BDC0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_10.07.2023_F3FB72.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_22.04.2023_39F0D7.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_03.12.2022_3FD9E7.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.02.2023_DE3CB5.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.03.2022_226712.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.03.2023_EEF006.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_05.01.2023_A6CDBA.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_06.01.2023_AE77C8.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_22.04.2023_F20853.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0Q1YX_vom_10.07.2023_B193E0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_03.12.2022_0B2265.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.02.2023_46B815.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.03.2022_E8CD81.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.03.2023_A330C8.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_05.01.2023_52DC66.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_06.01.2023_B82F79.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_10.07.2023_280378.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_15.05.2023_7CAAF0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_22.04.2023_66A388.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_03.12.2022_142B5A.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_04.02.2023_1C4D09.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_04.03.2023_853EBA.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_05.01.2023_83F648.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_06.01.2023_70F9AD.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_22.04.2023_F741D4.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_04.02.2023_544F25.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_15.05.2023_9C7C6A.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_22.04.2023_E9BB9B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_05.01.2023_B4A4B6.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_06.01.2023_DFABB9.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_15.05.2023_954971.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_22.04.2023_3F67A0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A2N84X_vom_10.07.2023_34B86B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_4_WKN_LYX05A_vom_22.04.2023_D16575.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amazon_WKN_906866_vom_02.05.2020_3E1630.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_15.08.2023_382A7F.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_27.05.2024_DA532B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_01.06.2023_4D864C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_10.01.2019_24E64C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_18.03.2020_CAFF9B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_20.11.2019_CFA5EE.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_29.10.2019_6B4ED8.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_20.11.2019_79FB21.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_29.09.2019_910ACD.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_30.05.2020_1AD653.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_31.08.2020_A7E824.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_20.11.2019_8D8D5B.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_29.09.2019_C5E0F5.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_30.05.2020_A82849.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_03.06.2021_92CBA5.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_25.02.2022_8E2273.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_30.01.2022_EC4E6F.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_13.04.2019_565727.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_26.02.2019_8CA417.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_26.03.2019_DD36A1.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_13.04.2019_45C6C3.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_26.02.2019_7A4BB0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_26.03.2019_A09233.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_30.01.2019_7CB5C0.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Fresenius_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_02.04.2024_740090.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Fresenius_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_27.05.2024_EDCFF7.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Immo_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_30.01.2024_1C4A1E.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Immo_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_30.06.2024_C24D39.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Kauf_12_St._WKN_A0JK68_vom_29.09.2019_D0C6CD.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Kauf_20_St._WKN_A1JSHV_vom_06.01.2023_788BE8.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_MSCI_JAPAN_UCITS_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_01.02.2025_050F8D.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_SAP_716460_(SAP_SE_O.N.)_vom_02.04.2024_0D0929.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_SAP_716460_(SAP_SE_O.N.)_vom_27.05.2024_31A045.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_Nr._37_LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_31.12.2025_94866C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_593399_vom_02.09.2021_B77CCF.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A0JK68_vom_02.09.2021_4C698A.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A0S9GB_vom_02.09.2021_9DF9E7.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A2H57N_vom_10.01.2019_E6DA2C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_US_div_WKN_A0D8Q4_vom_05.07.2020_A1FDEA.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_03.10.2021_D53682.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_25.02.2022_BD56EE.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_30.01.2022_CFFC61.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_10.12.2020_05C62D.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_26.01.2021_8EB601.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_29.11.2020_10219C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_02.09.2021_482D29.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_10.12.2020_1C6125.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_26.01.2021_B685D9.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_29.11.2020_A59498.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_03.10.2021_857318.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_10.12.2020_B07E9A.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_25.02.2022_CD4C85.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_26.01.2021_B11CAC.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_29.11.2020_F69C1C.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_30.01.2022_63F2DB.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_02.09.2021_88C891.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_03.10.2021_FDF5CC.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)
- `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_25.02.2022_DF7AD4.pdf`: ERROR → WARNING (MIFID_COST → MIFID_COST,UNCLASSIFIED_WARNING)

## Einzelbefunde

Vollständig in `findings.csv` (jede Meldung einzeln), `files.csv` und `audit.json`. Der Markdownbericht enthält nur die ersten 150 ERROR/ WARNING-Dateien.

- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_593399_vom_04.03.2022_71E068.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_03.12.2022_39D0BF.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.02.2023_7FDD1F.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.03.2022_E7EFE2.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.03.2023_5CAD29.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_05.01.2023_3B88FB.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_06.01.2023_88BDC0.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_10.07.2023_F3FB72.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_22.04.2023_39F0D7.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_03.12.2022_3FD9E7.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.02.2023_DE3CB5.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.03.2022_226712.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.03.2023_EEF006.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_05.01.2023_A6CDBA.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_06.01.2023_AE77C8.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_22.04.2023_F20853.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0Q1YX_vom_10.07.2023_B193E0.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_03.12.2022_0B2265.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.02.2023_46B815.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.03.2022_E8CD81.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.03.2023_A330C8.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_05.01.2023_52DC66.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_06.01.2023_B82F79.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_10.07.2023_280378.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_15.05.2023_7CAAF0.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_22.04.2023_66A388.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_03.12.2022_142B5A.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_04.02.2023_1C4D09.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_04.03.2023_853EBA.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_05.01.2023_83F648.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_06.01.2023_70F9AD.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_22.04.2023_F741D4.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_04.02.2023_544F25.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_15.05.2023_9C7C6A.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_22.04.2023_E9BB9B.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_05.01.2023_B4A4B6.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_06.01.2023_DFABB9.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_15.05.2023_954971.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_22.04.2023_3F67A0.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A2N84X_vom_10.07.2023_34B86B.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_4_WKN_LYX05A_vom_22.04.2023_D16575.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Amazon_WKN_906866_vom_02.05.2020_3E1630.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_15.08.2023_382A7F.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_27.05.2024_DA532B.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_01.06.2023_4D864C.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_10.01.2019_24E64C.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_18.03.2020_CAFF9B.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_20.11.2019_CFA5EE.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Amundi_Europe_WKN_A2H57N_vom_29.10.2019_6B4ED8.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_03.10.2021_D53682.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_25.02.2022_BD56EE.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_593399_vom_30.01.2022_CFFC61.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_10.12.2020_05C62D.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_26.01.2021_8EB601.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0H074_vom_29.11.2020_10219C.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_02.09.2021_482D29.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_10.12.2020_1C6125.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_26.01.2021_B685D9.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0JK68_vom_29.11.2020_A59498.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_03.10.2021_857318.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_10.12.2020_B07E9A.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_25.02.2022_CD4C85.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_26.01.2021_B11CAC.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_29.11.2020_F69C1C.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0LEW8_vom_30.01.2022_63F2DB.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_02.09.2021_88C891.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_03.10.2021_FDF5CC.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_25.02.2022_DF7AD4.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A0S9GB_vom_30.01.2022_CE4D7C.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_drei_WKN_A111X9_vom_02.09.2021_B71267.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_20.11.2019_79FB21.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_29.09.2019_910ACD.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_30.05.2020_1AD653.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A111X9_vom_31.08.2020_A7E824.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_20.11.2019_8D8D5B.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_29.09.2019_C5E0F5.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emergency_WKN_A1JJTF_vom_30.05.2020_A82849.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_03.06.2021_92CBA5.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_25.02.2022_8E2273.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Emerging_WKN_A111X9_vom_30.01.2022_EC4E6F.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_13.04.2019_565727.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_26.02.2019_8CA417.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_593399_vom_26.03.2019_DD36A1.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_13.04.2019_45C6C3.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_26.02.2019_7A4BB0.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_26.03.2019_A09233.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Europe_Small_WKN_A0D8QZ_vom_30.01.2019_7CB5C0.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Fresenius_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_02.04.2024_740090.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Fresenius_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_27.05.2024_EDCFF7.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Immo_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_30.01.2024_1C4A1E.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Immo_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_30.06.2024_C24D39.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Kauf_12_St._WKN_A0JK68_vom_29.09.2019_D0C6CD.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Kauf_20_St._WKN_A1JSHV_vom_06.01.2023_788BE8.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_MSCI_JAPAN_UCITS_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_01.02.2025_050F8D.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_SAP_716460_(SAP_SE_O.N.)_vom_02.04.2024_0D0929.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_SAP_716460_(SAP_SE_O.N.)_vom_27.05.2024_31A045.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Sparplan_Nr._37_LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_31.12.2025_94866C.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_593399_vom_02.09.2021_B77CCF.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A0JK68_vom_02.09.2021_4C698A.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A0S9GB_vom_02.09.2021_9DF9E7.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_Sparplan_WKN_A2H57N_vom_10.01.2019_E6DA2C.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING
- **WARNING** `comdirect/KOsteninformationen/Kosteninformation_US_div_WKN_A0D8Q4_vom_05.07.2020_A1FDEA.pdf` · `user.comdirect-ertraege/kosteninformation_mifid_ii` · MIFID_COST, UNCLASSIFIED_WARNING

## Grenzen

- Klassifikationen sind regelbasierte Priorisierung, **kein** Beweis, dass Beträge fachlich korrekt oder fehlerhaft sind.
- `INFO` umfasst z. B. normale Plugin-Erkennungsnachrichten; `WARNING` enthält auffällige Vorzeichen und Brutto-Netto-Werte.
- Die Suite führt `parse_pdf()` aus und schreibt keinerlei Portman-Datenbankeinträge.
- Optionaler Cache nutzt Dateigröße, mtime_ns, SHA-256, OCR-Modus und Parser-Fingerprint; SHA wird auch bei Cache-Treffern neu berechnet.
- Für schnelle gezielte Läufe `--only-errors`, `--plugin` und `--issue-code` verwenden; mit `--compare` zu V1/V2 vergleichen.
- Historische Baselines unter `test_reports` unverändert aufbewahren. Berichte nicht öffentlich teilen (Dateinamen/Belegdetails).
