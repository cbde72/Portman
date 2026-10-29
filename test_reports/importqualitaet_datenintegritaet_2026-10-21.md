# Portman V09 – Importqualität und Datenintegrität

Prüfdatum: 21.10.2026  
Codebasis: `main` nach PR #17 (`8d2b72f`)  
Produktivdaten: `data/v09/portfolio.sqlite`, Stand 21.10.2026 18:54:25,
ausschließlich mit SQLite `mode=ro` und `PRAGMA query_only=ON` geöffnet. Der
Bericht wurde nach dem vom Benutzer gemeldeten Neuimport vollständig erneut
erhoben.

## Kurzfazit

- SQLite meldet `integrity_check=ok`, Schema-Version 9.
- 70 aktive Imports, 366 Buchungen, 97 Dokumentzuordnungen und 21
  Steuerereignisse wurden geprüft. Es gibt keine inaktiven Imports.
- Es wurden keine doppelten aktiven Import-Dateihashes, Buchungs-IDs,
  Buchungs-Content-Hashes oder Steuerereignis-IDs gefunden.
- Zwei nur nach Datum/Betrag/Konto gleich aussehende Buchungspaare sind keine
  Dubletten; Gegenpartei, Kartendatum und Geschäftskennung unterscheiden sich.
- Die zuvor festgestellten vier doppelten generischen Dokumentablagen sind im
  neu importierten Bestand nicht mehr vorhanden.
- Die Investment-Ausschüttungs-Steuerbuchungen sind nun cash-neutral und dem
  richtigen Zieldepot zugeordnet. Die fachliche `fee_links`-Verknüpfung zur
  jeweiligen Finanzreport-Dividende fehlt allerdings weiterhin.
- Die 40 aktuell generischen PDFs bestehen aus 23 Kosteninformationen,
  15 Dateien zu Kaufabrechnungen und 2 Dividenden-Steuermitteilungen.

Es wurden weder Datenbank noch Originaldateien verändert.

## Phase 1 – Produktive Datenintegrität

### Dublettenprüfung

| Prüfung | Ergebnis | Bewertung |
|---|---:|---|
| Aktive Imports mit identischem `file_hash` | 0 | unauffällig |
| Buchungen mit identischem Konto und `external_id` | 0 | unauffällig |
| Buchungen mit identischem `content_hash` | 0 | unauffällig |
| Steuerereignisse mit identischer ID | 0 | unauffällig |
| Steuerereignisse mit identischer fachlicher Signatur | 0 | unauffällig |
| Dokumente mit gleichem Inhalt und gleichem Konto | 0 | unauffällig |

Die zwei groben Signaturtreffer bei Buchungen sind echte getrennte Umsätze:

- 05.01.2026, zweimal −15,00 EUR bei EDEKA: unterschiedliche Kartendaten
  (02.01. und 03.01.) sowie Kennungen `F6RQ/10185` und `F6RQ/31025`.
- 04.05.2026, zweimal −15,60 EUR: einmal ARAL, einmal EDEKA, mit
  unterschiedlichen Kartendaten und Kennungen.

Mehrfachzuordnungen desselben Finanzreport-PDFs zu vier Konten beziehungsweise
Depot und ältere Steuerbelege mit je einer Depot- und Kontozuordnung sind keine
Dokumentdubletten: Es handelt sich jeweils um einen Import und unterschiedliche
fachliche Zielkonten.

Die Neuimporte enthalten weder parallele generische Ablagen noch mehrfache
aktive Imports desselben Dateihashes. Mehrfachzuordnungen eines Finanzreports zu
seinen verschiedenen Konten bleiben erwartungsgemäß erhalten und sind keine
Dubletten.

### A0H074 und Investment-Ausschüttungen

A0H074 ist fachlich vollständig extrahiert:

| Feld | Bestand |
|---|---:|
| Brutto | 9,10 EUR |
| Steuerbasis | 6,37 EUR |
| Teilfreistellung | 2,73 EUR |
| Steuer | 1,67 EUR |
| Netto-Finanzreportbuchung | 7,43 EUR |
| Zieldepot der Steuerbuchung | `depot 4764924` |

Die wirtschaftliche Cash-Neutralisierung funktioniert, die fachliche
Verknüpfung ist jedoch noch nicht vollständig hergestellt:

- `fee_links` enthält 0 Zeilen.
- Die Steuerbuchung aus Import 70 hat korrekt `affects_cash=false`.
- Ihr `performance_depot_key` ist korrekt auf `depot 4764924` gemappt.
- Die Finanzreportbuchung mit Bankreferenz `0S5C29F709I0G` enthält bereits den
  Nettozufluss 7,43 EUR und im Buchungstext Brutto 9,10 EUR / Steuer 1,67 EUR.
- Die Steuerbuchung erzeugt damit keinen zweiten Cash- oder Performanceabfluss;
  der wirtschaftliche Netto-Cashflow bleibt 7,43 EUR.
- Es gibt nur eine Dokumentzeile für den A0H074-Beleg.
- Wegen des fehlenden Links können Steuerereignis und Dividende in der
  steuerlichen Detailansicht weiterhin als unverbundene Vorgänge erscheinen.

Dasselbe Restproblem betrifft die strukturierten Steuerimporte A0LEW8, 593399
und A0D8QZ: Die Steuerbuchungen sind korrekt cash-neutral, aber keine besitzt
einen `fee_links`-Eintrag. Für alle vier ist eine passende Netto-Ertragsbuchung
im Finanzreport vorhanden;
bei A0LEW8 liegt deren Buchungstag am 01.09.2026 zum Ertragsdatum 31.08.2026.

Priorität **P1**: Die Linkbildung muss auch dann funktionieren, wenn die
Finanzreportbuchung roh als `BANK_BOOKING` gespeichert ist und Wertpapier,
Brutto sowie Steuer erst aus ihrem Buchungstext abgeleitet werden. Die
Cashwirkung ist bereits korrekt. Mehrdeutige Fälle müssen ungeändert mit
Prüfhinweis bleiben.

### Drei reparierte Kaufabrechnungen

| WKN / Datum | Parsergebnis im Bestand | Finanzreportbetrag | Gebührennachweis |
|---|---|---:|---:|
| A111X9, 07.09.2026 | comdirect Kauf, 97 %, Dokumentimport 20 | −30,95 EUR | 0,46 EUR |
| A0S9GB, 23.09.2026 | comdirect Kauf, 97 %, Dokumentimport 21 | −18,09 EUR | 0,27 EUR |
| 716460, 23.07.2026 | comdirect Kauf, 97 %, Dokumentimport 27 | −29,05 EUR | 0,43 EUR |

Die Kauf-PDFs erzeugten bewusst keine zweite Transaktion; sie wurden über
Valuta, Betrag und WKN/ISIN den bereits vorhandenen Finanzreportbuchungen
zugeordnet. Es bestehen keine Buchungsdubletten. Die Belege und Gebührenwerte
sind im Importbericht vorhanden. A111X9 vom 15.09.2026 wurde ebenfalls erkannt
und derselben sicheren Zuordnungslogik unterworfen.

### Weitere Stammdatenauffälligkeit

Der kanonische Name von A0H074 ist gültig. In `original_names` befindet sich
aber noch ein historischer, aus einer fehlerhaften PDF-Zeile stammender langer
Alias mit Tabellenüberschriften. Priorität **P2**: In einer allgemeinen
Stammdaten-Reparaturvorschau als verdächtigen Alias markieren, aber nicht
automatisch löschen; der Originalwert muss als Provenienz erhalten bleiben.

## Phase 2 – Klassifikation der 40 generischen PDFs

| Klasse | Dateien | unterschiedliche Inhalte | Priorität |
|---|---:|---:|---|
| Kaufabrechnungen mit defekter eingebetteter Schrift | 15 | 12 | P1 |
| MiFID-II-Kosteninformationen | 23 | 23 | P2 |
| Dividenden-Steuermitteilungen | 2 | 2 | P1 |
| Sonstige Dokumente | 0 | 0 | – |

### Ursache der 15 Kaufabrechnungsdateien

Alle Belege enthalten lesbare Überschriften wie `GESCHÄFTSABRECHNUNG` und
`Wertpapierkauf`. Die eingebetteten Fonts besitzen jedoch fehlerhafte oder
unbrauchbare Zeichenabbildungen. Drei stabile Schadensbilder wurden beobachtet:

- LS9AVX: lange `z`-Folgen und aus `g/h/i/...` zusammengesetzte Nummern;
- A2H57N: lange `R`-Folgen und aus `v/w/...` zusammengesetzte Zahlen;
- LYX05A: zahlreiche Ersatzzeichen (`U+FFFD`) und verstümmelte Ziffern.

Die native Extraktion ist mit etwa 7.600–7.900 Zeichen lang genug und enthält
lesbare Kopftexte. Die aktuelle globale OCR-Heuristik erkennt deshalb bei den
LS9AVX- und A2H57N-Varianten keine hinreichende Qualitätsstörung. Beim LYX05A-
Muster reicht der relative Ersatzzeichenanteil nicht in jedem Fall zuverlässig
aus. Anschließend fehlen dem comdirect-Handler belastbare Zahlen-, ISIN- und
Betragsmuster; der generische Handler gewinnt mit 70 % und bezeichnet die
Belege teilweise irreführend als Steuerbescheinigung.

Technische Empfehlung innerhalb der bestehenden Pluginstruktur:

1. Im bestehenden `comdirect_ertraege.py` eine enge Erkennung für
   `GESCHÄFTSABRECHNUNG` + `Wertpapierkauf` + comdirect-Kopf ergänzen, selbst
   wenn Detailfelder beschädigt sind.
2. Nur für diese erkannte comdirect-Dokumentfamilie OCR der relevanten Seiten
   beziehungsweise Feldregionen erzwingen; keine globale OCR-Ausweitung.
3. Die bereits vorhandenen Feldvalidatoren für ISIN-Prüfziffer, WKN, Datum,
   Stück, Kurswert, Gebühren und Gesamtbelastung unverändert als harte Schranke
   verwenden. Nicht sicher erkannte Werte bleiben unbekannt.
4. Identische Dateihashes vor fachlicher Verarbeitung zusammenfassen. Die drei
   Kopien im Ordner `Januar` dürfen keine zweiten Buchungen erzeugen.
5. Regressionstests je Font-Schadensbild sowie für OCR-Ausfall und uneindeutige
   OCR-Ergebnisse ergänzen.

### Vollständige Dateiliste

#### P1 – Kaufabrechnungen mit defekter Schrift

| Datei relativ zu `comdirect\2026` | Ursache |
|---|---|
| `Abrechungen\Wertpapierabrechnung_Kauf_0,006_St._LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_07.01.2026_33E4AB.pdf` | defekte z/g/h-Zeichenzuordnung |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,006_St._LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_07.04.2026_BF9BF9.pdf` | defekte z/g/h-Zeichenzuordnung |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,006_St._LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_09.02.2026_8152BF.pdf` | defekte z/g/h-Zeichenzuordnung |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,006_St._LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_09.03.2026_8FD854.pdf` | defekte z/g/h-Zeichenzuordnung |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,212_St._A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.03.2026_DB29F5.pdf` | defekte R/v/w-Zeichenzuordnung |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,215_St._A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_01.04.2026_52140A.pdf` | defekte R/v/w-Zeichenzuordnung |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,223_St._A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.02.2026_37725D.pdf` | defekte R/v/w-Zeichenzuordnung |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,227_St._A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.01.2026_E842CB.pdf` | defekte R/v/w-Zeichenzuordnung |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,604_St._LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.03.2026_2AA5CC.pdf` | Ersatzzeichen / defekte ToUnicode-Tabelle |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,619_St._LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_01.04.2026_6D0613.pdf` | Ersatzzeichen / defekte ToUnicode-Tabelle |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,642_St._LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.02.2026_877A53.pdf` | Ersatzzeichen / defekte ToUnicode-Tabelle |
| `Abrechungen\Wertpapierabrechnung_Kauf_0,667_St._LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.01.2026_C64D27.pdf` | Ersatzzeichen / defekte ToUnicode-Tabelle |
| `Januar\Wertpapierabrechnung_Kauf_0,006_St._LS9AVX_(LANG+SCHWARZ_O.E._INDEX)_vom_07.01.2026_33E4AB.pdf` | identische Kopie des ersten LS9AVX-Belegs |
| `Januar\Wertpapierabrechnung_Kauf_0,227_St._A2H57N_(AIS-AM.E.H.D.F.EOC)_vom_02.01.2026_E842CB.pdf` | identische Kopie des A2H57N-Januarbelegs |
| `Januar\Wertpapierabrechnung_Kauf_0,667_St._LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.01.2026_C64D27.pdf` | identische Kopie des LYX05A-Januarbelegs |

#### P1 – Dividenden-Steuermitteilungen

| Datei relativ zu `comdirect\2026` | Ursache und Empfehlung |
|---|---|
| `Steuerinformationen\Steuermitteilung_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_27.05.2026_2832C7.pdf` | normale inländische Dividende, nicht Investment-Ausschüttung; bestehenden comdirect-Ertragsparser um diesen belegten Typ erweitern |
| `Steuerinformationen\Steuermitteilung_716460_(SAP_SE_O.N.)_vom_08.05.2026_19EC9B.pdf` | normale inländische Dividende, nicht Investment-Ausschüttung; bestehenden comdirect-Ertragsparser um diesen belegten Typ erweitern |

Die Erweiterung sollte das vorhandene Steuermodell und dieselben strengen
Abgleichregeln nutzen. Sie darf weder eine zweite Dividende noch eine zweite
Steuerbelastung erzeugen. Freistellungsauftrag und nachgewiesene Nullsteuer sind
von unbekannten Beträgen zu unterscheiden.

#### P2 – MiFID-II-Kosteninformationen

Diese Dokumente sind keine Ausführungsabrechnungen und dürfen keine Käufe oder
Gebühren-Cashflows erzeugen. Empfohlen wird lediglich eine explizite Erkennung
im bestehenden comdirect-Plugin als `Kosteninformation`, strukturierte Ablage im
vorhandenen Kostenmodell soweit die Felder belegt sind und ein klarer Hinweis
`keine ausgeführte Transaktion`.

| Datei relativ zu `comdirect\2026` |
|---|
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_06.08.2026_6CC595.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_16.07.2026_51DDA6.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_578560_(FRESENIUS_SE+CO.KGAA_O.N.)_vom_20.07.2026_189A2E.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_16.07.2026_A2B37A.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_593399_(ISH.S.EUROP.MID_200_U.ETF)_vom_20.07.2026_6BC967.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_716460_(SAP_SE_O.N.)_vom_20.07.2026_FD3076.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A0D8Q4_(IS.DJ_U.S.SELEC.DIV.U.ETF)_vom_06.08.2026_633EA0.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A0D8QZ_(ISH.S.EUR.SMALL_200_U.ETF)_vom_25.08.2026_9AE5E4.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_25.08.2026_7F7CFF.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A0JK68_(M.A.-R.INT.COM.IN.UETF)_vom_25.08.2026_49F27D.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A0LEW8_(ISHSII-DEV.MKT.PR.Y.DLDIS)_vom_06.08.2026_05A1ED.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A0S9GB_(DT.BOERSE_COM._XETRA-GOLD)_vom_16.09.2026_36146D.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.09.2026_7B522C.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_02.09.2026_BB3EBE.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A111X9_(IS_C.MSCI_EMIMI_U.ETF_DLA)_vom_10.09.2026_8591B8.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A1JJTF_(SPDR_MSCI_EM.MAR.SM.C.ETF)_vom_18.08.2026_AFAC71.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_A1JSHV_(SPDR_S+P_400_US_MID_CAP)_vom_18.08.2026_7092E0.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_ETF039_(AM.-S+P_SM.C.600_SCR.DLD)_vom_10.09.2026_5BB8A6.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_ETF039_(AM.-S+P_SM.C.600_SCR.DLD)_vom_16.09.2026_586A97.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.09.2026_2A6556.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.09.2026_D1C6E1.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_02.10.2026_2C6645.pdf` |
| `Kosteninformationen\Kosteninformation_Sparplan_Nr._38_LYX05A_(MUL-AM.MSCI_JPN_ETF_YND)_vom_24.09.2026_2A9BEA.pdf` |

## Priorisierte nächste Schritte

1. **P1 – Investment-Ausschüttungen verknüpfen:** die vier cash-neutralen
   Steuerereignisse auch mit roh als `BANK_BOOKING` gespeicherten
   Finanzreport-Dividenden sicher verbinden; keine Bestands- oder Cashänderung.
2. **P1 – Defekte comdirect-Kaufschrift:** dokumenttypspezifischen OCR-Fallback
   im bestehenden `comdirect_ertraege.py` ergänzen und die 12 eindeutigen
   Belege plus 3 Hash-Dubletten testen.
3. **P1 – Dividenden-Steuermitteilungen:** Fresenius und SAP als eigenen
   belegten Dokumenttyp im bestehenden Ertragsplugin abbilden und sicher mit
   Finanzreport-Dividenden zusammenführen.
4. **P2 – Kosteninformationen:** explizit klassifizieren und optional im
   vorhandenen Kostenmodell ablegen; niemals als ausgeführte Trades behandeln.
5. **P2 – Stammdatenhygiene:** verdächtige historische Namensaliase in einer
   read-only Vorschau markieren und nur nach Bestätigung bereinigen.
