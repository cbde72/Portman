# Portman V09 – P0 Vorabpauschalen-Fehlklassifizierung

Prüfdatum: 23.10.2026

Branch: `fix/vorabpauschale-booking-classification`

## Gesamtbewertung

**PASS nach Korrektur.** Der comdirect-Parser und die SQLite-Persistenz speichern
die Steuerereignistypen korrekt. Der Fehler entstand ausschließlich beim Aufbau
der virtuellen Zeilen für „Depot → Buchungen“:
`RepositoryV09.tax_event_bookings()` setzte bisher für jedes Steuerereignis
unbedingt `kind='VORABPAUSCHALE'` und erzeugte immer einen mit
„Vorabpauschale“ beginnenden Verwendungszweck.

Die produktive Datenbank wurde über `mode=ro` und `PRAGMA query_only=ON`
geöffnet und mit der SQLite-Backup-API in eine temporäre Prüfdatenbank kopiert.
Alle Repository- und GUI-Prüfungen liefen ausschließlich auf dieser Kopie.

## Herkunft der angezeigten Zeilen

Für `Depot 4764924` liefert die aktuelle produktive Kopie:

| Quelle der GUI-Zeile | Anzahl | Persistenz |
|---|---:|---|
| `reconcile_depot_bookings()` | 34 | vorhandene Transaktionen bzw. abgeleitete Transaktionssicht |
| `tax_event_bookings()` | 23 | virtuelle, cash-neutrale Projektion aus `import_model_records(kind='tax_events')` |
| GUI-Gesamtzeilen | 57 | keine eigene GUI-Tabelle |

Damit sind im aktuellen Datenstand nicht 56 persistierte Vorabpauschalen
vorhanden. Es gibt 57 sichtbare Zeilen, von denen vor dem Fix 23 virtuelle
Steuerzeilen falsch „Vorabpauschale“ hießen. Die beobachtete Zahl 56 lässt sich
durch einen früheren Datenstand oder einen GUI-Filter erklären; sie ist keine
SQL-Entität und keine Mehrfachpersistenz.

Die 23 gespeicherten Steuerereignisse sind korrekt verteilt:

```sql
SELECT json_extract(payload,'$.type') AS event_type, COUNT(*)
FROM import_model_records
WHERE kind='tax_events'
GROUP BY event_type;
```

| tatsächlicher Typ | Anzahl |
|---|---:|
| `vorabpauschale_ausland` | **3** |
| `investment_ausschuettung_inland` | 12 |
| `investment_ausschuettung_ausland` | 6 |
| `dividende_inland` | 2 |

## Vollständige Ist-Liste der 23 falsch projizierten Zeilen

`Betrag=0,00` und `affects_cash=false` zeigen, dass es virtuelle
Depotinformationen und keine zusätzlichen Cashbuchungen sind. `kind` und
`purpose` in dieser Tabelle sind die fehlerhafte Darstellung vor dem Fix.

| Datum | Depot | WKN / ISIN | Betrag | kind | purpose | external_id | import_id | Quell-PDF | tatsächlicher Steuerereignistyp |
|---|---|---|---:|---|---|---|---:|---|---|
| 02.01.2026 | Depot 4764924 | A1JJTF / IE00B48X4842 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2025 | `pdf-comdirect-advance-tax-66ac5f…` | 12 | `Steuermitteilung_A1JJTF_(SPDR_MSCI_EM.MAR.SM.C.ETF)_vom_02.01.2026_0B8139.pdf` | `vorabpauschale_ausland` |
| 02.01.2026 | Depot 4764924 | A111X9 / IE00BKM4GZ66 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2025 | `pdf-comdirect-advance-tax-6861f6…` | 11 | `Steuermitteilung_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.01.2026_B52E2F.pdf` | `vorabpauschale_ausland` |
| 02.01.2026 | Depot 4764924 | A2H57N / LU1681041973 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2025 | `pdf-comdirect-advance-tax-a0c070…` | 13 | `Steuermitteilung_A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.01.2026_63460F.pdf` | `vorabpauschale_ausland` |
| 15.01.2026 | Depot 4764924 | A0D8Q4 / DE000A0D8Q49 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-92c4a8…` | 10 | `Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.01.2026_17CC5F.pdf` | `investment_ausschuettung_inland` |
| 28.01.2026 | Depot 4764924 | A0Q1YX / IE00B2QWDY88 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-62f3ab…` | 14 | `Steuermitteilung_A0Q1YX_(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_28.01.2026_FA84F7.pdf` | `investment_ausschuettung_ausland` |
| 18.02.2026 | Depot 4764924 | ETF039 / IE000XLJ2JQ9 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-c179e4…` | 15 | `Steuermitteilung_ETF039_(AM.-S+P_SM.C.600_SCR.DLD)_vom_18.02.2026_209479.pdf` | `investment_ausschuettung_ausland` |
| 27.02.2026 | Depot 4764924 | A0LEW8 / IE00B1FZS350 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-1b82c7…` | 16 | `Steuermitteilung_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_27.02.2026_8561D1.pdf` | `investment_ausschuettung_ausland` |
| 16.03.2026 | Depot 4764924 | A0D8QZ / DE000A0D8QZ7 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-0dddb0…` | 18 | `Steuermitteilung_A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_16.03.2026_269FD6.pdf` | `investment_ausschuettung_inland` |
| 16.03.2026 | Depot 4764924 | A0H074 / DE000A0H0744 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-953f68…` | 19 | `Steuermitteilung_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_16.03.2026_C85F10.pdf` | `investment_ausschuettung_inland` |
| 16.03.2026 | Depot 4764924 | 593399 / DE0005933998 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-fd42d9…` | 17 | `Steuermitteilung_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_16.03.2026_94F45C.pdf` | `investment_ausschuettung_inland` |
| 15.04.2026 | Depot 4764924 | A0D8Q4 / DE000A0D8Q49 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-5a4c1d…` | 20 | `Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.04.2026_329554.pdf` | `investment_ausschuettung_inland` |
| 08.05.2026 | Depot 4764924 | 716460 / DE0007164600 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-dividend-tax-eba668…` | 21 | `Steuermitteilung_716460_(SAP_SE_O.N.)_vom_08.05.2026_19EC9B.pdf` | `dividende_inland` |
| 27.05.2026 | Depot 4764924 | 578560 / DE0005785604 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-dividend-tax-1af338…` | 22 | `Steuermitteilung_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_27.05.2026_2832C7.pdf` | `dividende_inland` |
| 29.05.2026 | Depot 4764924 | A0LEW8 / IE00B1FZS350 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-68b5ec…` | 23 | `Steuermitteilung_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_29.05.2026_F2986C.pdf` | `investment_ausschuettung_ausland` |
| 15.06.2026 | Depot 4764924 | A0D8QZ / DE000A0D8QZ7 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-0873a4…` | 25 | `Steuermitteilung_A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.06.2026_54E44D.pdf` | `investment_ausschuettung_inland` |
| 15.06.2026 | Depot 4764924 | A0H074 / DE000A0H0744 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-0f0289…` | 26 | `Steuermitteilung_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_15.06.2026_37FEF0.pdf` | `investment_ausschuettung_inland` |
| 15.06.2026 | Depot 4764924 | 593399 / DE0005933998 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-9395be…` | 24 | `Steuermitteilung_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_15.06.2026_F4C359.pdf` | `investment_ausschuettung_inland` |
| 15.07.2026 | Depot 4764924 | A0D8Q4 / DE000A0D8Q49 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-dc931a…` | 27 | `Steuermitteilung_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_15.07.2026_EFE375.pdf` | `investment_ausschuettung_inland` |
| 29.07.2026 | Depot 4764924 | A0Q1YX / IE00B2QWDY88 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-b72b0b…` | 28 | `Steuermitteilung_A0Q1YX_(ISHSIII-MSCI_J.SM.CAP_DLD)_vom_29.07.2026_9EC77B.pdf` | `investment_ausschuettung_ausland` |
| 31.08.2026 | Depot 4764924 | A0LEW8 / IE00B1FZS350 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-1aa58a…` | 29 | `Steuermitteilung_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_31.08.2026_76B982.pdf` | `investment_ausschuettung_ausland` |
| 15.09.2026 | Depot 4764924 | A0D8QZ / DE000A0D8QZ7 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-0bc774…` | 31 | `Steuermitteilung_A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_15.09.2026_C3BF64.pdf` | `investment_ausschuettung_inland` |
| 15.09.2026 | Depot 4764924 | 593399 / DE0005933998 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-a8fc41…` | 30 | `Steuermitteilung_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_15.09.2026_2E8722.pdf` | `investment_ausschuettung_inland` |
| 15.09.2026 | Depot 4764924 | A0H074 / DE000A0H0744 | 0,00 | VORABPAUSCHALE | Vorabpauschale Ertragsjahr 2026 | `pdf-comdirect-investment-distribution-tax-dca10e…` | 32 | `Steuermitteilung_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_15.09.2026_F181E5.pdf` | `investment_ausschuettung_inland` |

Vollständige `external_id`-Werte (Zuordnung über `import_id` in obiger Tabelle):

```text
12 pdf-comdirect-advance-tax-66ac5fcde49da4f87ced9d450b3d4c023147ed96ea621c7665d5a80973677a43
11 pdf-comdirect-advance-tax-6861f601c6fd979ee310421d1514cdbf9eea0e0f61e29d271fa9a1c0da1d5865
13 pdf-comdirect-advance-tax-a0c0701d3888883a931beee6e4ff2bc122c1bdcb42074c2477464c44398e37dd
10 pdf-comdirect-investment-distribution-tax-92c4a85c64618ef9db53609ccdeb8e4ecbff2d01766fa2072ccfb165e557914c
14 pdf-comdirect-investment-distribution-tax-62f3abc5e41bf7a0b3406e6ddca3233db475229ce23d2f1c4ce702c762574bf5
15 pdf-comdirect-investment-distribution-tax-c179e4c68ac3d0bad9c382e5c59547608166c7c7e143ed7ce13404e45546d8da
16 pdf-comdirect-investment-distribution-tax-1b82c7cc44640fead377e30d55247bc2e3f3fa7b6a9dc1ee42fd780596533553
18 pdf-comdirect-investment-distribution-tax-0dddb0bdd7e30b5c85a9f78eb061a458b775f27f7be573e709cb43f80cc191fa
19 pdf-comdirect-investment-distribution-tax-953f688cdfe2884ced5cc1fee689405f8420fbaec3cd2787081d0853cb71f1a9
17 pdf-comdirect-investment-distribution-tax-fd42d9f4084b9bdc1af68a9243424080836888d67ebec84f1a29e98f727f409a
20 pdf-comdirect-investment-distribution-tax-5a4c1dd5ddef5eb199c071f4da327b13c884aa29c519c9ffd62b9acbaa1b9b37
21 pdf-comdirect-dividend-tax-eba668da7a285861432aa89dd547e108b9240d6ab3ecb3e6dac8da52a664e2c1
22 pdf-comdirect-dividend-tax-1af3389e126d5694f8376ac1aec95dcb400267aca5140194768671a6cd0e4745
23 pdf-comdirect-investment-distribution-tax-68b5ec47ffad5d7a30a5cb45a72f1de276ece06f3de0d4b95ebb8e6f1fb6f456
25 pdf-comdirect-investment-distribution-tax-0873a492549ec3fa3fc1883db1bbc1a5ae0bbc46be1b8b8f31975f01dc026890
26 pdf-comdirect-investment-distribution-tax-0f028982cf5618df4e0c513df4e55af4db09cf50bca133cce3a3d8eec9d4c6a8
24 pdf-comdirect-investment-distribution-tax-9395be0d5e1da53ffe93098b1182ab2ea3d2110772155d5f3411d4e599c76c01
27 pdf-comdirect-investment-distribution-tax-dc931a7d648b9cab641c8dd290e292fcab9906822e3412e1811c158dc73a2a4d
28 pdf-comdirect-investment-distribution-tax-b72b0bba4d9353e3fc276d00f2a8f509b47fd1db28231349cd4cd2f563ee9e53
29 pdf-comdirect-investment-distribution-tax-1aa58a8b087a879c5f2c044aff779568317b725ae1492d57cd0059620c17251b
31 pdf-comdirect-investment-distribution-tax-0bc7746654cc10342d44d7575a58370c8a164d0870c1562ef73d2bf7a817a72e
30 pdf-comdirect-investment-distribution-tax-a8fc417256ebfa39c6dd14db365d70499597a2115047c3ed84e8a9d0b5814566
32 pdf-comdirect-investment-distribution-tax-dca10eed3f5057a22b63d8dd234fa5a0d7bdb6e41940828bdd7061aeafe66ca9
```

## Korrektur

`tax_event_bookings()` bildet jetzt explizit ab:

| gespeicherter Ereignistyp | GUI-`kind` | Verwendungszweck |
|---|---|---|
| `vorabpauschale`, `vorabpauschale_ausland` | `VORABPAUSCHALE` | Vorabpauschale, Basis und Ertragsjahr |
| `investment_ausschuettung_inland` | `DISTRIBUTION` | Investment-Ausschüttung Inland, Brutto, Teilfreistellung und Steuer |
| `investment_ausschuettung_ausland` | `DISTRIBUTION` | Investment-Ausschüttung Ausland, Brutto, Teilfreistellung und Steuer |
| `dividende_inland` | `DIVIDEND` | Dividende Inland, Brutto und Steuer |
| unbekannter zukünftiger Typ | `TAX_EVENT` | Originaltyp beziehungsweise Steuerereignis; niemals Vorabpauschale als Default |

Die steuerliche Detailansicht verwendete bereits eine korrekte typabhängige
Abbildung und bleibt damit konsistent. Der comdirect-Parser musste nicht
geändert werden.

## Nachweis auf der produktiven Kopie

Nach dem Fix zeigt derselbe reale Datenbestand:

```text
57 GUI-Zeilen insgesamt
20 DIVIDEND-Cashflows
18 DISTRIBUTION · nur Depot
 9 FEE
 4 TAX · nur Depot
 3 VORABPAUSCHALE · nur Depot
 2 DIVIDEND · nur Depot
 1 BUY
```

Nur die drei Originalbelege vom 02.01.2026 enthalten nach dem Fix noch
„Vorabpauschale“ in Art oder Verwendungszweck. SAP und Fresenius erscheinen als
`DIVIDEND · nur Depot`; die 18 ETF-Ereignisse als
`DISTRIBUTION · nur Depot`.

## Wirtschaftliche Integrität

Die Korrektur verändert ausschließlich die zur Laufzeit erzeugten Dictionaries.
Es gibt keine SQL-Schreiboperation und keine Änderung an Transaktionen,
Steuerereignissen, `fee_links`, Cashflows, Beständen oder Performance. Alle
virtuellen Steuerzeilen behalten `amount='0.00'` und `affects_cash=false`.

Regressionstests prüfen:

- genau drei Vorabpauschalen;
- SAP und Fresenius als Dividenden;
- in- und ausländische ETF-Ausschüttungen als Ausschüttungen;
- dieselben Arten in der realen Depotbuchungstabelle und steuerlichen
  Detailansicht;
- unveränderte leere Transaktions-, Cashflow- und Bestandsmengen im isolierten
  Klassifikationstest.

```text
Gezielte GUI-/Steuer-/Importtests: 34 passed
Gesamte Pytest-Suite: 1103 passed, 12 skipped
```
