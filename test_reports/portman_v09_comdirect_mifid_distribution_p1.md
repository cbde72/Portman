# Portman V09 – comdirect MiFID-II und Investment-Ausschüttungen P1

## 1. Ausgangsbasis

- Ausgangscommit: `3048a097f88a` (`main`, PR #32 enthalten)
- Branch: `fix/comdirect-mifid-distribution-p1`
- Separater Worktree: `.worktrees/comdirect-mifid-distribution-p1`
- Unveränderte Baseline: PDF-Parser-Audit V2 vom 24.10.2026, Fingerprint `c4c46393ea9f4b82`
- Originale: `C:\Users\chris\Desktop\history\comdirect` (nur gelesen)
- Keine produktive Datenbank und kein Original-PDF wurde verändert.

## 2. Fehlergruppen

Alle 167 comdirect-Fehlerpfade der Baseline besitzen unterschiedliche SHA-256-Inhalte; es lagen in diesen Gruppen keine physischen Dubletten vor.

| Gruppe | Physische PDFs | SHA-256 | Ergebnis P1 |
|---|---:|---:|---|
| MiFID-II-Kosteninformationen | 102 | 102 | 102 strukturiert, archiviert, ohne Buchung |
| Investment-Ausschüttungen (priorisierte Fehlermeldung) | 52 | 52 | 52 Steuerereignisse, 52 Archive, 0 Cash-Transaktionen |
| Weitere Investment-Ausschüttung 2021 | 1 | 1 | zusätzlich korrigiert, Originalabweichung als Warnung |
| Stückzahlkonflikte | 6 | 6 | analysiert, unverändert fehlerhaft |
| Inlandsdividenden/Sonderlayout | 5 | 5 | analysiert, unverändert fehlerhaft |
| Sonstiger Steuermitteilungs-/Parserfall | 1 | 1 | analysiert, unverändert fehlerhaft |

## 3. Ursachenanalyse

### MiFID-II

- 90 Belege: Die native PDF-Textextraktion liefert Beträge unmittelbar vor `EUR` (`4,73EUR`). Die bisherigen Muster verlangten ein Leerzeichen.
- 11 Belege: Phasenüberschriften wurden erkannt, Einzelkosten mit kompaktem `EUR` oder Fußnote direkt hinter `[E]` jedoch nicht vollständig summiert.
- 1 Beleg: Kaufkostenüberschrift ohne `, pro Jahr`; der Betrag ist einmalig und darf nicht als jährlich gekennzeichnet werden.
- Die Dokumente sind Ex-ante-Kostensimulationen. Sie belegen keine ausgeführte Transaktion und erzeugen weder Kauf/Verkauf noch Cashflow, Gebühr oder Steuer.

### Investment-Ausschüttungen

- Die 2016/2017-Layouts enthalten fachlich keine Teilfreistellung; fehlend bleibt deshalb `None` und wird nicht zu `0` erfunden.
- Fußnotenketten wie `(1)(22)` standen zwischen Steuerbasis und Betrag.
- Fünf Altbelege enthalten in der extrahierten Quelle keine Depotnummer. Sie werden dem explizit unzugeordneten Konto `comdirect Depot` zugewiesen, nicht einer geratenen Depotnummer.
- Bei einem 2021-Beleg weichen Brutto minus Teilfreistellung und gedruckte Steuerbasis ab. Der Beleg weist selbst auf mögliche Abweichungen hin. Beide Originalwerte bleiben erhalten; es entsteht nur eine Warnung und keine Ausgleichsbuchung.
- Die 52 priorisierten Altbelege weisen jeweils `0,00 EUR` abgeführte Steuer aus. Daher entstehen 52 Steuerereignisse, aber keine Steuer-Cash-Transaktion und keine zweite Ausschüttung.

## 4. Referenztabelle – 30 manuell am extrahierten Originaltext geprüfte Belege

`Sollwerte` wurden aus den jeweiligen Originalbelegen gelesen; `Istwerte` sind die neue Parserausgabe. Personen-, Konto- und Depotnummern werden im Bericht nicht wiedergegeben.

| SHA-256 | PDF-Pfad | Dokumenttyp | Handler | Fehlerursache | Sollwerte / Istwerte | Ergebnis | Maßnahme |
|---|---|---|---|---|---|---|---|
| `95a33d1122e4f58354971bca59f313bd2699d058820f70f730fa555dacddcef3` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_593399_vom_04.03.2022_71E068.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | Kauf 8,86; Halten 4,73; Verkauf 14,79; Gesamt 82,72 EUR / identisch | PASS | Parserkorrektur |
| `1b23dc0af91d4b70107af8244366def64ca0b7405ce7316afb501a214edae72b` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_03.12.2022_39D0BF.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 13,30; 4,43; 18,48; 107,11 EUR / identisch | PASS | Parserkorrektur |
| `2fd280ec2d52d27ce36c9ec98a557e7a0d4ddbcd6105447f93b1f60e4dad08d4` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0D8QZ_vom_04.02.2023_7FDD1F.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 13,30; 4,43; 18,48; 107,11 EUR / identisch | PASS | Parserkorrektur |
| `ee9bf44a9f44f938d71d31972de7dddbea51c021b422813d14a0aecf0f25cbfb` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_03.12.2022_3FD9E7.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 4,43; 4,36; 12,40; 56,34 EUR / identisch | PASS | Parserkorrektur |
| `d36f5460d3a947a6e2782fdb4da902654cbdd052e47a0db3627bbd6b93a5208c` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0LEW8_vom_04.02.2023_DE3CB5.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 4,43; 4,36; 12,40; 56,34 EUR / identisch | PASS | Parserkorrektur |
| `d87fc050b124dd03e198faef177b0664984ed36ee19ce608478456c8a47f2282` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0Q1YX_vom_10.07.2023_B193E0.pdf` | MiFID | `kosteninformation_mifid_ii` | `[E]1`-Fußnote | 8,86; 8,57; 16,39; 103,52 EUR / identisch | PASS | Parserkorrektur |
| `60dd78c2a01200cf2b52ba11cfdc8bffa4f4a53b05d3d58c8d1ada3e1b443de4` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_03.12.2022_0B2265.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 8,86; 1,92; 18,30; 72,18 EUR / identisch | PASS | Parserkorrektur |
| `b9b0f17f9327d2eec1f476a552be5750134db3da6a1e17cc2b10b19e51cb3beb` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A0S9GB_vom_04.02.2023_46B815.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 8,86; 1,92; 18,30; 72,18 EUR / identisch | PASS | Parserkorrektur |
| `533071e34a456283093f958299a0cd64d51b6ac26e74ce8c17ee0376338f6f35` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_03.12.2022_142B5A.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 8,86; 4,14; 14,79; 79,77 EUR / identisch | PASS | Parserkorrektur |
| `ed40f3b9eb2291efcb417239464c8f54c7a7805e6f12d5e52edd93795b8a94a0` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A111X9_vom_04.02.2023_1C4D09.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 44,33; 20,69; 44,35; 369,44 EUR / identisch | PASS | Parserkorrektur |
| `fa58e995611b123882243afe977a07392a822db5ac4baaecba9b28878f0f02bd` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JJTF_vom_04.02.2023_544F25.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 17,72; 18,32; 22,18; 202,40 EUR / identisch | PASS | Parserkorrektur |
| `96d0b99241d600c8953e9be1028a94f8944bbfddb6744afb40da4169c461f173` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A1JSHV_vom_05.01.2023_B4A4B6.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 88,67; 44,33; 62,40; 727,39 EUR / identisch | PASS | Parserkorrektur |
| `ecca223f7ab490e37b24bd502ba0b2c4c8de027f84a8b2d9db522298655b4e4d` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_A2N84X_vom_10.07.2023_34B86B.pdf` | MiFID | `kosteninformation_mifid_ii` | `[E]1`-Fußnote | 17,72; 4,14; 23,78; 133,10 EUR / identisch | PASS | Parserkorrektur |
| `24dc37912063363e25c152c8e4cb676ef0887b47d64c5ceaf11e8e3e667300cb` | `comdirect/KOsteninformationen/Kosteninformation_4_WKN_LYX05A_vom_22.04.2023_D16575.pdf` | MiFID | `kosteninformation_mifid_ii` | kompakter EUR-Abstand | 17,72; 3,85; 22,18; 130,05 EUR / identisch | PASS | Parserkorrektur |
| `cd0a22ba2be9962207dc2150a94a72559ffe2d55595258726928750ef1d29670` | `comdirect/KOsteninformationen/Kosteninformation_Amazon_WKN_906866_vom_02.05.2020_3E1630.pdf` | MiFID | `kosteninformation_mifid_ii` | abweichendes Layout | 8,86; 0,00; 14,79; 59,07 EUR / identisch | PASS | Parserkorrektur |
| `0c2ee307d6a451c7d893c6db8dedff5d7db9b6893e127a59f0c805fc755fe0bd` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399...01.09.2016_9773FE.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung, Fußnoten | Brutto 2,43; Basis 0,00; Steuer 0,00 EUR / identisch | PASS | optionale Felder |
| `2ab9c5164f5d82b91548c5b453a1f98be99d8a31a0a905636545e2f32cb8115c` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_593399...15.03.2017_3E44BE.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 2,40; Basis 2,52; Steuer 0,00 EUR / identisch | PASS | optionale Felder |
| `23cf912d958273daf5517d4194c42b971810a41c31a0f5366c6554e768f50aa0` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4...15.01.2016_BFE1E3.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 4,57; Basis 6,37; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `414544c2a509b1d03f62b1e3b1da99645266954c0fdce92ee35c593b7b1c01a4` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4...16.10.2017_1AD226.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 8,16; Basis 11,49; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `0ef95c6f8d358e5b2a84623ee9afe9ac30e273612f54a499bed218649e65ddb5` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ...01.09.2016_8E04F6.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 3,79; Basis 0,00; Steuer 0,00 EUR / identisch | PASS | optionale Felder |
| `47a07b3be7bddd7be1a1027a8650aa2b6cebc80cefbf86d2648d737baa5d3073` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8QZ...15.03.2017_C3EE7F.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 4,59; Basis 4,50; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `8aabc85ff8e6cb50a0d5101514be9f08acfbaaf86e558728da5fb78c39634550` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074...15.03.2016_392251.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 2,31; Basis 2,43; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `dc6ee531179e6c183c6162cbc8274c7f1ea3f3ccfba018945165ebc1f28b0178` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0H074...15.03.2017_B675DB.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 3,21; Basis 3,38; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `fb65774417dca9f518bd87e9c1934e5ef0cd5dc392fb6395795bc32a4621fe9f` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8...30.08.2016_5615AD.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 5,27; Basis 6,27; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `7f041c8be333ff50baa48cb5e92441cfad1af490ff801b7b60f265679e0ba237` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LEW8...28.02.2017_72E6EC.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 5,62; Basis 7,24; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `b22bf323e775cf05a7c94aa93068caf9d70aa67d2862adbc37b7310d5269562c` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0LGQL...29.02.2016_FB1A06.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 4,63; Basis 5,69; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `456a139be7d245b7f62b1c52c2c5a44fed360b255aa58173dfc3e54dc4779666` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0Q1YX...27.01.2017_610D58.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 3,16; Basis 3,75; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `7f5e556ce493eebb5be5e07399b31ac1c3659ac51fefd80652bf075a7ff9d492` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0Q1YX...29.07.2016_5FC73F.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto 3,76; Basis 7,15; Steuer 0,00 EUR / identisch | PASS | Originalwerte bewahrt |
| `ec8a42fb1b0789fdeee5948ba4fd054bc7f56a15e58d4544d4bcf44de4ce9a2a` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_ETF074...28.12.2017_87DA8A.pdf` | Ausschüttung | `investment_ausschuettung` | keine Teilfreistellung | Brutto/Basis 8,39; Steuer 0,00 EUR / identisch | PASS | optionale Felder |
| `490e9279e173654557fb505f07adabd8aaddef4d0361c603f4b00ed06a7e8663` | `comdirect/Steuermitteilungen/Steuermitteilung_WKN_A0D8Q4...15.01.2021_A48D0D.pdf` | Ausschüttung | `investment_ausschuettung` | gedruckte Basis weicht ab | Brutto 14,86; Teilfrei 4,46; Basis/Steuer 0,00 EUR / identisch | WARNING | Werte bewahrt, keine Ausgleichsbuchung |

## 5. MiFID-II-Klassifizierung und Datenmodell

- `information_type` unterscheidet `ex_ante`, `ex_post` und `unknown` im bestehenden JSON-Modellrecord; keine Schemaänderung.
- Unterstützt sind Dokumentdatum/-zeit, Referenz, Sparplan, WKN/ISIN, Ausführungsplatz, Währung, Laufzeit/Haltedauer, Kauf-/Halte-/Verkaufskosten, Kostenkategorien, Zuwendungen, Gesamtkosten, Renditewirkung und Jahresprojektion.
- Fehlende Kategorien bleiben `None`. Gedruckte Nullwerte bleiben dagegen explizit `0.00`.
- Die 102 Baseline-Belege sind Ex-ante-Simulationen. Ex-post wird erkannt und getrennt gekennzeichnet; im untersuchten Fehlerbestand lag kein Ex-post-Beleg vor.
- Das Datenmodell speichert keine eigenständige relationale MiFID-Phasenhistorie; die Zusatzfelder und Einzelpositionen liegen im JSON-Modellrecord. Das ist die bewusste P1-Grenze ohne DB-Migration.

## 6. Investment-Ausschüttungen

- Brutto, Netto, Steuerbasis, Kapitalertragsteuer, Solidaritätszuschlag, Kirchensteuer, Währung, Stückzahl, ISIN/WKN, Behandlungsdatum, Valuta, Referenz und Konto werden ausschließlich aus dem Beleg übernommen.
- Teilfreistellung, Freistellungsauftrag, Verlustverrechnung und Depotnummer sind optional und werden nie als Null bzw. konkrete Nummer erfunden.
- Brutto minus abgeführte Steuer wird centgenau gegen Netto geprüft.
- Einzelsteuern werden centgenau gegen die ausgewiesene Gesamtsteuer geprüft.
- Steuerereignis und Archivdokument werden angelegt; eine Steuertransaktion nur bei tatsächlich ausgewiesener Steuer ungleich null. Die Ausschüttung selbst wird nicht ein zweites Mal erzeugt.
- Die Logik aus PR #24–#27 (Matching, FSA-Aggregation, atomare Persistenz und Clean-Reimport) bleibt unverändert und wird durch bestehende Regressionstests abgedeckt.

## 7. Geänderte Funktionen

- `pdf_plugins/comdirect_ertraege.py`
  - MiFID-Phasen- und Einzelzeilenmuster
  - `information_type`-Klassifizierung
  - Investment-Steuerbasis-/Fußnoten- und optionale-Felder-Logik
  - Plausibilisierung ohne Ausgleichsbuchung
- `src/portfolio_v5/models.py`
  - additives JSON-Feld `CostReport.information_type`
- Regressionstests in `tests/test_comdirect_mifid_cost.py` und `tests/test_comdirect_investment_distribution_tax.py`

## 8. Vorher-/Nachher-Buchungsvergleich

| Kennzahl | Vorher | Nachher |
|---|---:|---:|
| MiFID-Dokumente archiviert | 0 (Fehler) | 102 |
| MiFID-Kostenreports | 0 | 102 |
| MiFID wirtschaftliche Buchungen | 0 | 0 |
| Priorisierte Ausschüttungs-Steuerereignisse | 0 (Fehler) | 52 |
| Priorisierte Ausschüttungs-Archive | 0 | 52 |
| Priorisierte Ausschüttungs-Cash-Transaktionen | 0 | 0 |
| Zusätzliche Kauf-/Verkaufsbuchungen | 0 | 0 |
| Heuristische Ausgleichsbuchungen | 0 | 0 |

## 9. Steuer-, FSA- und Persistenzintegrität

- Tests prüfen Importreihenfolge, gleiche PDF erneut, unterschiedliche Dokumente derselben wirtschaftlichen Buchung, vorhandenen Kontoumsatz, Steuer-/Transaktionsverknüpfung und atomare Persistenz.
- Temporäre SQLite-Datenbanken bestätigen unveränderte Cashflows, Bestände und Performance für MiFID sowie genau eine wirtschaftliche Ausschüttung bei separater Steuermitteilung.
- `used_exemption` und `loss_offset` werden nur gesetzt, wenn die jeweiligen gedruckten Felder vorhanden sind; die bestehende globale FSA-Logik wurde nicht geändert.

## 10. Audit-Vergleich

Ungecachete, OCR-aktivierte Teil-Audits mit neuem Parser-Fingerprint:

| Kennzahl | Vorher | Nachher |
|---|---:|---:|
| MiFID-II-Parserfehler | 102 | 0 |
| Ausschüttungs-Parserfehler (priorisierte 52) | 52 | 0 |
| Weitere korrigierte Investment-Ausschüttung | 1 Fehler | 0 Fehler / 1 Warning |
| Sonstige comdirect-Parserfehler | 13 | 12 |
| Neue Parserfehler in den geprüften Gruppen | 0 | 0 |
| Generische Fallbacks | 172 | 172 (Parserauswahl außerhalb der Fehlerpfade unverändert) |
| Zusätzliche wirtschaftliche Buchungen | 0 | 0 |
| Neue Steuer- oder Gebührenbuchungen | 0 | 0 |
| Handler-Regressionen in den geprüften Gruppen | 0 | 0 |

Artefakte: `test_reports/pdf_parser_audit/comdirect_p1_mifid_after/`, `comdirect_p1_distribution_after/`, `comdirect_p1_quantity_after/` und `comdirect_p1_parser_after/`. Zusammen decken die ungecacheten Läufe alle 167 comdirect-Baseline-Fehlerpfade ab. Der zusätzliche OCR-Vollkorpuslauf wurde wegen eines reproduzierbar hängenden Alt-PDFs abgebrochen; er wird nicht als Nachweis gewertet.

## 11. Qualitätssicherung

- `python -m compileall -q src/portman src/portfolio_v5 pdf_plugins`: PASS
- `python -m ruff check src/portman src/portfolio_v5 pdf_plugins --select F`: PASS
- gezielte comdirect-Regressionen: PASS
- Gesamtsuite: 1161 PASS, 15 SKIP; ein zunächst fehlgeschlagener reiner Worktree-Umgebungstest (`.venv`-Pfad) bestand nach lokaler Junction isoliert.
- Finaler comdirect-Zielsatz: 29 PASS.

## 12. Verbleibende Sonderfälle

- Sechs Kaufabrechnungen melden widersprüchliche Stückzahlen (z. B. `1.001` gegenüber `1`); keine automatische Buchung, bis das Layout separat fachlich geklärt ist.
- Fünf Inlandsdividenden-Sonderlayouts enthalten nicht alle aktuell verpflichtenden FSA-/Steuerbasisfelder; keine Fehlerunterdrückung.
- Ein weiterer Steuermitteilungs-/Parserfall bleibt separat zu analysieren.
- Diese Fälle sind nicht Teil der beiden P1-Hauptgruppen und wurden nicht durch Fallbacks oder Archiv-only kaschiert.

## 13. Fachliche Risiken

- Alte Steuerbelege können eine Steuerbasis oberhalb oder unterhalb der Barausschüttung ausweisen. Portman bewahrt diese Werte; eine steuerrechtliche Neuberechnung findet bewusst nicht statt.
- Fehlende Depotnummern erfordern beim Import eine Benutzerzuordnung des generischen `comdirect Depot`.
- Ex-post-Klassifizierung ist implementiert und synthetisch getestet, im vorliegenden Fehlerkorpus aber nicht real belegt.

## 14. Gesamtbewertung

**PASS MIT HINWEISEN**: Die beiden priorisierten Fehlergruppen sind fachlich korrigiert, archiviert und cashflow-neutral. Alle 167 bisherigen comdirect-Fehlerpfade wurden ungecached erneut geprüft. Die zwölf verbleibenden Sonderfälle bleiben sichtbar und sind für Folgearbeiten dokumentiert; sie wurden weder unterdrückt noch als Fallback kaschiert.
