# Importer-Audit Portman V09 / Portfolio Performance

Stand: 17. Oktober 2026

## 1. Gegenstand und Reproduzierbarkeit

Untersucht wurden der aktuelle `main`-Branch von Portman sowie der aktuelle
`master`-Branch von Portfolio Performance (PP):

| Projekt | Commit | Zeitpunkt / Hinweis |
|---|---|---|
| Portman | `b121549790776ce99fe52f932b8a0be6a914edda` | 17.10.2026; enthält „Depotbuchungen sicher mit Zahlungen abgleichen (#3)“ |
| Portfolio Performance | `805c20dff5d999e987675181b4f1d82f81df10c0` | 15.10.2026 |

Reproduzierbare Upstream-Referenz: [Portfolio-Performance-Commit
805c20d](https://github.com/portfolio-performance/portfolio/commit/805c20dff5d999e987675181b4f1d82f81df10c0).

Zum Prüfzeitpunkt gab es in `cbde72/Portman` keinen offenen Pull Request. Die
früher in PR #3 entwickelte Depot-/Kontenzuordnung ist damit keine
„nicht gemergte“ Funktion mehr, sondern Bestandteil des geprüften `main`.

Die Aussagen beruhen auf Quellcode, Tests und vorhandener Projektdokumentation.
Ein Dateiname allein wurde nicht als Implementierungsnachweis gewertet. Die
Statuswerte bedeuten:

- **Vollständig nachgewiesen:** Parser, fachliche Verarbeitung und einschlägige
  Tests sind vorhanden.
- **Teilweise unterstützt:** Nur Formate, Layouts, Vorgänge oder Datenfelder
  einer Quelle sind nachgewiesen.
- **Nicht unterstützt:** Im geprüften Stand fehlt eine entsprechende
  Implementierung.
- **Nicht verifiziert:** Es gibt Hinweise, aber keinen ausreichenden Nachweis.

PP steht unter der Eclipse Public License 1.0. Für dieses Audit wurde kein
fremder Quellcode übernommen. Eine spätere Umsetzung sollte Anforderungen und
Testfälle aus öffentlich beobachtbarem Verhalten ableiten, nicht PP-Code
kopieren.

## 2. Kurzfazit

Portman besitzt eine solide, sicherheitsorientierte Importbasis: unveränderte
Quelldokumente, SHA-256-Identität, Vorschau, Validierung, Importhistorie,
revisionsfähige Korrekturen, konservative Dublettenerkennung, PDF-Plugins und
lokale OCR. Die tiefste Abdeckung besteht für comdirect, ING und Baader; sie ist
aber jeweils deutlich schmaler als bei PP. PP bringt 140 konkrete
PDF-Extraktorklassen und eine sehr große, belegbasierte Regressionstestbasis
mit. Portman hat zehn produktive bankspezifische PDF-Plugins; zusätzlich wird
derzeit das Beispiel-Plugin technisch mitgeladen.

Die dringendsten Befunde sind:

1. **P0 – Teilzuordnung und Performance:** Schon eine Teilzuordnung unterdrückt
   die gesamte Geldkontobuchung in `performance_transactions()`. Der
   `allocated_amount` wird für die Performance nicht verwendet. Bei einer
   Sammelzahlung oder nur teilweise belegter Zahlung kann dies TWR, Modified
   Dietz und XIRR zu hoch oder zu niedrig ausweisen.
2. **P0 – Vollständigkeit von Bestandsimporten:** Der Deka-Spezialimport markiert
   Bestände korrekt als unvollständig. Der generische Tabellenimport kann ohne
   ausgewiesene Kontrollsumme oder Positionszahl jedoch nicht erkennen, ob
   Zeilen fehlen; ein vom Benutzer als vollständig bestätigter Teilbestand kann
   einen guten Bestand logisch ablösen.
3. **P1 – Ereignisabdeckung:** ING-Verkäufe, Baader/finanzen.net-zero-Dividenden,
   Steuerdokumente, Vorabpauschalen, Depotüberträge, Kapitalmaßnahmen und
   Stornos sind nicht in der Breite von PP nachgewiesen.
4. **P1 – CSV-Konfiguration:** Portman kann Spaltenprofile verarbeiten, besitzt
   aber nicht die nachgewiesene PP-Breite bei Formaterkennung, dauerhaft
   verwalteten Profilen und unterschiedlichen Zieltypen.
5. **P1 – XML/Plattformimporte:** Der PP-XML-Import ist nützlich, aber schmal
   getestet; IB Flex, XTB und native Trade-Republic-Formate fehlen.

## 3. Portman-Bestandsaufnahme

### 3.1 PDF-Plugins

| Quelle / Plugin | Format und nachgewiesene Dokumente | Fachliche Verarbeitung | Integrität, OCR, Tests und Grenzen | Status |
|---|---|---|---|---|
| Baader Bank (`baader.pdf`) | PDF; Quartalsaufstellung, Kauf-/Verkaufsabrechnung | Bestände, BUY, SELL; ISIN, Stück, Kurs, Betrag | Strenge ISIN-, Mengen-/Kurs- und Summenprüfung; OCR wird abgelehnt; 37 Baader-bezogene Tests im Projekt. Keine vollständige Dividenden-/Steuer-/Kapitalmaßnahmenstrecke nachgewiesen | Teilweise unterstützt |
| comdirect Finanzreport | PDF; aktuelle und ältere Finanzreport-Layouts | Geldbuchungen, Salden, Depotbestände | Salden-/Bestandskontrollen, schnelle PyMuPDF-Strecke; OCR wird abgelehnt; 69 comdirect-bezogene Tests insgesamt. Finanzreport ist kein vollständiger Wertpapierbelegimport | Vollständig nachgewiesen für die genannten Reports |
| comdirect Erträge | PDF; Ertrags-, Tilgungs-, Kauf- und Vorabpauschalbelege | DIVIDEND/Ertrag, BUY, Provision, Steuerereignis, Vorabpauschale | Brutto-/Netto-, Steuer- und Referenzfelder; OCR alter Schriftarten mit Review-Markierung. SELL und breite Kapitalmaßnahmen fehlen | Teilweise unterstützt |
| ING Wertpapiere | PDF; Dividende, Kauf, Jahresdepotauszug | DIVIDEND, BUY einschließlich Sparplan-Untertyp, Bestände, Steuern | OCR für Dividenden/Käufe; Bestände benötigen eingebetteten Text; 159 ING-bezogene Tests. Kein ING-SELL-Parser nachgewiesen | Teilweise unterstützt |
| Baader Krypto | PDF; Kryptoabrechnung | BUY für Krypto | Begrenzter Vorgangsumfang; kein vollständiger Wallet-/Verkaufs-/Steuerzyklus | Teilweise unterstützt |
| Deka Quartalsbericht | PDF; Quartalsbericht | Bestände, Ausschüttungen | Warnung bei nicht unterstützten Umsätzen; verhindert damit stilles Vollständigkeitsversprechen | Teilweise unterstützt |
| pbb direkt | PDF; leere Kontoauszüge, Steueroptimierung zum Jahresende | Spezialfälle, keine allgemeine Umsatzstrecke | Sehr enger Dokumentumfang | Teilweise unterstützt |
| Bank of Scotland | PDF; Kontoauszug | Geldbuchungen und Saldo | Saldenabgleich; keine Wertpapierfunktionen | Vollständig nachgewiesen für den Kontoauszug |
| Renault Bank direkt | PDF; Kontoauszug | Geldbuchungen | Saldenabgleich; 15 Renault-bezogene Tests; keine Wertpapierfunktionen | Vollständig nachgewiesen für den Kontoauszug |
| Generischer Kontoauszug | PDF-Fallback | Konservative Geldbuchungen | Mindestkonfidenz 0,70, Review-Hinweise; keine verlässlichen Salden/Bestände. Falsche Pluginwahl bleibt bei ähnlichen Layouts ein Risiko | Teilweise unterstützt |

Die Plugin-Erkennung lädt Dateien aus `src/portfolio_v5/pdf_plugins/` und aus
dem top-level-Verzeichnis `pdf_plugins/`. Sie bewertet Kandidaten ab 0,70 und
meldet Mehrdeutigkeit, wenn die zwei besten Ergebnisse höchstens 0,10
auseinanderliegen. Das mitgelieferte `example_plugin.py` wird ebenfalls
entdeckt; es sollte aus produktiver Discovery ausgeschlossen werden.

### 3.2 Weitere Importwege

| Importweg | Nachgewiesene Funktion | Grenzen / Risiko | Status |
|---|---|---|---|
| Konfigurierbares CSV-Profil | Spaltenzuordnung, Trennzeichen, Datum-, Dezimal- und Tausenderformat, Steuer-/Quellensteuer-/Referenzfelder, zeilenweise Fehler | Keine gleichwertige automatische Formaterkennung und Profilverwaltung wie PP nachgewiesen; ein Format je Lauf | Teilweise unterstützt |
| Generischer Tabellenimport | CSV, XLSX, XLS, ODS; Headererkennung, ISIN/WKN/Name, Werte, Dubletten, optionale Depotwert-Kontrolle | Ohne Kontrollsumme/Positionszahl ist ein abgeschnittener Bestand nicht sicher erkennbar | Teilweise unterstützt |
| Deka Excel | Blatt „Bestände“ sowie Käufe und Wiederanlagen/Ausschüttungen | Bestände werden sicher als `complete=False` importiert; übrige Vorgänge begrenzt | Teilweise unterstützt |
| Krypto-Wallet CSV | Exaktes Schema, Footer-Summen, IDs, FIFO-Bestand bei Verkäufen, Snapshots | Quellenspezifisch; kein allgemeiner Exchange-Importer | Vollständig nachgewiesen für das definierte Schema |
| Portfolio-Performance-Import | XML und gezipptes XML; Securities, Konten, Portfoliotransaktionen, Vorschau und Mapping | Kein verschlüsseltes/protobuf-Format; DTD/Entities werden sicher abgelehnt; nur vier spezifische Tests | Teilweise unterstützt |
| comdirect REST | Salden, paginierte gebuchte Geldumsätze, Depotbestände | Kein vollständiger Brokerage-Ereignisfeed; Geldumsätze bleiben `BANK_BOOKING` | Teilweise unterstützt |
| ING/Baader/Renault FinTS | Salden, Umsätze, je nach Bank MT535-Bestände/Dokumente | Fähigkeiten bankabhängig; EUR-zentrierte Bewertung; keine breite Wertpapierklassifikation | Teilweise unterstützt |
| Automatischer Bankimport | Wiederverwendung eindeutiger Kontozuordnungen, Überspringen neuer/mehrdeutiger Quellen | Sicherheit vor Automatisierung; kein Ersatz für fachliche Ereigniszuordnung | Vollständig nachgewiesen für diesen Umfang |

### 3.3 Gemeinsame Importpipeline

- `ImportWorker` verarbeitet Dateien mit höchstens vier Threads; PDF-Plugins
  werden pro Sammelauftrag einmal entdeckt.
- PDFs erhalten einen SHA-256-Hash. Text wird zunächst mit `pypdf` bzw. in der
  schnellen Strecke mit PyMuPDF extrahiert. Fehlender, kurzer, beschädigt
  wirkender oder layoutkritischer Text löst lokale RapidOCR-Verarbeitung aus.
- OCR-Modell und Engine werden wiederverwendet; ein Lock serialisiert OCR.
  Seiten werden begrenzt gerendert. OCR-Belege können gezielte Review-Hinweise
  erhalten.
- Die Speicherung erkennt denselben Importbatch über Quellhash, Parser,
  Parserdaten und Kontenzuordnung. Transaktionen mit gleicher externer ID und
  gleichem Fingerprint bleiben unverändert. Originaldateien und Importhistorie
  bleiben erhalten.
- Fachwarnungen werden von harten Validierungsfehlern unterschieden. Das ist
  für Vorschauen sinnvoll, verlangt aber je Plugin explizite Regeln, welche
  Abweichungen einen Import zwingend blockieren.

## 4. Portfolio Performance

### 4.1 Architektur

PP trennt Extraktion und Importaktionen. PDF-Extraktoren erkennen Banken über
Kennungen, danach konkrete Dokumenttypen und Textblöcke/-abschnitte. Die
erzeugten Items durchlaufen unter anderem Typ-, Datums-, Währungs-,
Forex-Bruttowert-, wertpapierbezogene und Dublettenprüfungen, bevor sie
eingefügt werden. Die Dublettenprüfung vergleicht unter anderem Datum, Währung,
Betrag, Stückzahl, Wertpapier und Typ und kennt Toleranzen für Sparpläne.

Die CSV-Strecke bietet unterschiedliche Ziele für Kontoumsätze,
Depottransaktionen, Wertpapiere, Kurse und Portfolios, freie Spaltenzuordnung,
Encoding, Trennzeichen, übersprungene Zeilen/Header, Formatvorschläge sowie
gespeicherte JSON-Konfigurationen. Hinzu kommen eigene Importpfade für IB Flex,
Trade Republic und XTB.

Im geprüften Commit wurden gezählt:

| Merkmal | Anzahl |
|---|---:|
| Konkrete PDF-Extraktorklassen | 140 |
| PDF-Testklassen | 146 |
| PDF-`@Test`-Methoden | 3.490 |
| Tests in CSV/IB-Flex/Trade-Republic/XTB-Verzeichnissen | 117 |

Diese Zahlen messen Umfang, nicht automatisch Fehlerfreiheit.

### 4.2 Verzeichnis der nachgewiesenen PDF-Anbieter

Die 140 Extraktoren decken unter anderem folgende Anbieter ab (mehrere
Extraktoren pro Anbieter sind möglich):

ABN AMRO, Advanzia, AJ Bell, akf, Alpaca, Alpian, apoBank, Arkéa, Audi Bank,
Austrian Anadi, Aviva, Ayvens, Baader Bank, BBVA, Bank11, bank99, Bank SLM,
Barclays, Basellandschaftliche Kantonalbank/radicant, BAWAG, Bigbank, Bison,
Bondora, Bourse Direct, BoursoBank, BSDEX, Bundesschatz, C24, Cetes Directo,
Chase, comdirect, Commerzbank, CommSec, Computershare, Consorsbank, Crédit
Mutuel, Credit Suisse, Crowdestor, DAB, DADAT, Debitum, DEGIRO, Deka, Deutsche
Bank, Directa SIM, 1822direkt, DKB, Drei Banken, DZ/VR, easybank, ebase/FNZ,
Erste Bank, EstateGuru, E*TRADE, Fidelity, FIL Fondsbank, Findependent,
FinTechGroup/flatex, Firstrade, Fondsdepot Bank, Ford Money, Freiburger
Kantonalbank, GenoBroker, Ginmon, Gladbacher Bank, Hello Bank,
Hypothekarbank Lenzburg, ING, J&T, KBC, Keytrade, KFintech, LGT, Liberty, LLB,
Lime, MeDirect, Merkur, MLP, Modena, Morgan Stanley, N26, Neon, NIBC,
Nordax/Bank Norwegian, NordLB, OLB, Onvista, OpenBank, Orange Bank, Pictet,
Postbank, PostFinance, Questrade, Quirin, Raiffeisen, Raisin, Relai, Renault
Bank, Revolut, Robinhood, Santander, Saxo, Sberbank, S Broker, Scalable,
Charles Schwab, Score Priority, SelfWealth, Simpel, Solaris, Stake, St. Galler
Kantonalbank, Sunrise, Suresse, Sutor/justTRADE, Swisscard, Swissquote, Sydbank,
Targobank, Thurgauer Kantonalbank, Tiger Brokers, Tradegate, Trade Republic,
Trading 212, UBS, UmweltBank, UniCredit, Upvest, Vanguard, V-Bank, VDK,
Volksbank Wien, Volkswagen Bank, VZ, Wealthsimple, Weberbank, WIR/VIAC,
Whitebox und Zürcher Kantonalbank.

Wesentliche Dokumenttypen sind Kauf/Verkauf, Dividende/Ausschüttung, Konto- und
Depotauszug, Zinsen, Gebühren, Steuern/Steuererstattung/Vorabpauschale,
Ein-/Auslieferung, Splits und weitere Kapitalmaßnahmen. Die Abdeckung ist je
Anbieter unterschiedlich; die Liste bedeutet nicht, dass jeder Anbieter alle
Typen unterstützt.

Für die priorisierten Anbieter zeigt der tatsächliche Code:

- **comdirect:** Kauf, Verkauf, Dividenden/Erträge, Verkaufsgebühren,
  Steuerbehandlung/-erstattung, Depotgebühren, Finanzreport mit Geldbewegungen,
  Zinsen und Fremdwährungs-/Bruttowertinformationen. 244 Testmethoden und 141
  zugehörige Fixture-Dateien.
- **ING Deutschland:** Kauf, Verkauf, Dividende, Vorabpauschale, Kontoauszug,
  steuerrelevanter Tausch und Verlustverrechnung. 108 Testmethoden und 91
  Fixtures.
- **Baader Bank:** Trades, Krypto, Ausschüttungen, Vorabpauschale,
  Steuerverrechnung und periodische Kontoauszüge. 174 Testmethoden und 137
  Fixtures.
- **Deka:** Kauf/Verkauf, Fonds-/Tauschvorgänge, Dividende/Wiederanlage,
  Ein-/Auslieferung, Quartals-/Jahresumsätze, Gebühren und Steuererstattung. 54
  Testmethoden und 53 Fixtures.
- **Renault Bank:** Ein-/Auszahlungen, Zinsen und Kontoauszüge. 13 Testmethoden
  und 13 Fixtures.
- **Trade Republic:** umfangreiche Trades, Dividenden, Vorabpauschalen,
  Kontoübersichten, Zinsen, Steuerkorrekturen/-erstattungen sowie
  Splits/Ein-/Auslieferungen. 284 Testmethoden und 248 Fixtures.

## 5. Vergleichsmatrix

Aufwand: S = wenige Tage, M = etwa 1–3 Wochen, L = mehrere Wochen, XL =
fortlaufendes Programm. Schätzungen umfassen Parser, anonymisierte Belege,
Validierungen und Tests, nicht nur Regex-Anpassungen.

| Bank / Broker | Dokumenttyp | Format | Portfolio Performance | Portman | Fehlende Funktionen | Datenintegritätsrisiko | Testabdeckung | Aufwand | Priorität |
|---|---|---|---|---|---|---|---|---|---|
| comdirect | Finanzreport/Konto/Depot | PDF | Vollständig nachgewiesen | Vollständig nachgewiesen für unterstützte Layouts | Langfristig weitere Layoutvarianten | Mittel | Stark in beiden Projekten | M laufend | P1 |
| comdirect | Kauf | PDF | Vollständig nachgewiesen | Teilweise unterstützt | Layoutbreite, vollständige FX-Fälle | Hoch | Portman-Tests vorhanden | M | P1 |
| comdirect | Verkauf | PDF | Vollständig nachgewiesen | Nicht unterstützt als eigener Wertpapierbeleg | Verkauf, realisierte Werte, Gebühren-/Steuerdetails | Kritisch | Keine entsprechende Portman-Strecke | M | P0 |
| comdirect | Dividende/Ausschüttung | PDF | Vollständig nachgewiesen | Teilweise unterstützt | Layout-/FX-/Sonderfallbreite | Hoch | Portman-Tests vorhanden | M | P1 |
| comdirect | Vorabpauschale/Steuer | PDF | Vollständig nachgewiesen | Teilweise unterstützt | Korrektur-/Erstattungsvarianten | Hoch | Einzelne Portman-Fälle | M | P1 |
| finanzen.net zero / Baader | Wertpapiertrade | PDF | Teilweise unterstützt über Baader-Layouts | Teilweise unterstützt über Baader-Plugin | Frontend-/Depotbankidentität, Layoutvarianten, Referenzen | Hoch | Baader-Tests, keine klare zero-Matrix | M | P1 |
| finanzen.net zero / Baader | Ausschüttung/Steuer/Vorabpauschale | PDF | Teilweise bis vollständig je Baader-Beleg | Nicht unterstützt bzw. nicht verifiziert | Fachtypen und zero-spezifische Fixtures | Kritisch | Nicht ausreichend | L | P0 |
| finanzen.net zero / Tangany | Krypto | PDF/Export | Teilweise unterstützt | Teilweise unterstützt | Depotbank und Kryptoverwahrer getrennt modellieren; Verkauf/Steuer | Hoch | Enger Portman-Umfang | L | P1 |
| ING Deutschland | Kauf/Sparplan | PDF | Vollständig nachgewiesen | Vollständig nachgewiesen für bekannte Layouts | Layoutpflege/FX | Hoch | 159 ING-bezogene Portman-Tests | M laufend | P1 |
| ING Deutschland | Verkauf | PDF | Vollständig nachgewiesen | Nicht unterstützt | Vollständiger Verkauf inkl. Steuer/Gebühr | Kritisch | Fehlt | M | P0 |
| ING Deutschland | Dividende | PDF | Vollständig nachgewiesen | Vollständig nachgewiesen für bekannte Layouts | Sonder-/FX-Fälle | Hoch | Stark | M laufend | P1 |
| ING Deutschland | Vorabpauschale/Steuerausgleich | PDF | Vollständig nachgewiesen | Nicht unterstützt bzw. nicht verifiziert | Eigene Dokumenttypen | Hoch | Fehlt | M | P1 |
| ING Deutschland | Jahresdepotbestand | PDF | Vollständig nachgewiesen | Vollständig nachgewiesen bei eingebettetem Text | Scan/OCR-Bestand und Vollständigkeitsbeweis | Hoch | Vorhanden | M | P1 |
| Deka | Quartalsbestand/Ausschüttung | PDF/XLSX | Vollständig nachgewiesen | Teilweise unterstützt | Breitere Umsatz- und Kontrollsummenstrecke | Hoch | Begrenzte Excel-Tests | M | P1 |
| Renault Bank | Kontoauszug/Zins | PDF/FinTS | Vollständig nachgewiesen | Vollständig nachgewiesen für bekannte Auszüge | Layoutpflege | Mittel | Vorhanden | S laufend | P2 |
| Bank of Scotland | Kontoauszug | PDF | Nicht verifiziert | Vollständig nachgewiesen | Nur Layoutpflege | Mittel | Vorhanden | S laufend | P2 |
| pbb direkt | Kontoauszug/Steuer | PDF | Nicht verifiziert | Teilweise unterstützt | Allgemeine Umsätze und weitere Dokumenttypen | Mittel | Eng | M | P2 |
| Generische Bank | Kontoauszug | PDF | Nicht verifiziert | Teilweise unterstützt | Sicherere Identifikation und Saldenkontrolle | Hoch | Fallback-Tests | M | P1 |
| Trade Republic | Trade/Dividende/Steuer/Kapitalmaßnahme | PDF/eigene Importe | Vollständig nachgewiesen in großer Breite | Nicht unterstützt | Gesamte Quelle | Hoch | 284 PP-Tests, keine Portman-Abdeckung | L/XL | P1 |
| DEGIRO | Wertpapier-/Kontovorgänge | PDF/CSV | Vollständig nachgewiesen | Nicht unterstützt | Gesamte Quelle | Hoch | PP-Fixtures, keine Portman-Abdeckung | L | P2 |
| Interactive Brokers | Flex Query | XML | Vollständig nachgewiesen | Nicht unterstützt | Gesamte Quelle und FX-Komplexität | Hoch | PP-Teststrecke | XL | P2 |
| XTB | Brokerexport | CSV | Vollständig nachgewiesen | Nicht unterstützt | Gesamte Quelle | Hoch | PP-Teststrecke | L | P2 |
| Generisch | konfigurierbarer Tabellenimport | CSV | Vollständig nachgewiesen | Teilweise unterstützt | Profilverwaltung, Autoerkennung, Zieltypen, UI-Korrektur | Hoch | Portman: 4 Excel-, CSV-/Importtests; PP deutlich breiter | L | P1 |
| Portfolio Performance | Gesamtbestand/-historie | XML/ZIP | Eigenformat | Teilweise unterstützt | protobuf/verschlüsselte Varianten, mehr Transaktionsfelder | Hoch | Nur 4 spezifische Portman-Tests | L | P1 |

Bei finanzen.net zero darf die Marke nicht pauschal mit Baader gleichgesetzt
werden: Baader führt das Wertpapierdepot und Verrechnungskonto; Krypto wird laut
Anbieter durch Tangany verwahrt. Außerdem können verschiedene Frontends
ähnliche Baader-Dokumente erzeugen. Erkennung und Kontozuordnung müssen deshalb
Bank, Frontend, Depotnummer und Dokumentreferenzen getrennt behandeln.

## 6. Buchungsarten und Datenvollständigkeit

| Vorgang | Portman | Portfolio Performance | Wichtigste Portman-Lücke |
|---|---|---|---|
| Kauf / Sparplan | Teilweise unterstützt | Breite Unterstützung | Banken-/Layoutbreite, FX |
| Verkauf | Teilweise (Baader) | Breite Unterstützung | comdirect/ING und realisierte Werte |
| Dividende / ETF-Ausschüttung | Teilweise | Breite Unterstützung | Bankenbreite, FX/Sonderfälle |
| Zinsen | Über Kontoauszüge/Bankfeed teilweise | Breite Unterstützung | Dokument- und Steuerdetails |
| Gebühren | Teilweise | Breite Unterstützung | eigenständige und Verkaufsgebühren |
| Kapitalertragsteuer / Soli / Quellensteuer | Teilweise und feldweise | Breite Unterstützung | vollständige Komponenten-/Erstattungslogik |
| Kirchensteuer | Nicht durchgängig nachgewiesen | Je Extraktor unterstützt | eigenes Feld und Validierung |
| Steuererstattung | Teilweise/nicht durchgängig | Mehrere Extraktoren | Dokumenttypen, Vorzeichen, Referenzen |
| Vorabpauschale | comdirect teilweise | Mehrere Banken | ING/Baader und Korrekturen |
| Depotübertrag / Ein-/Auslieferung | Nicht verifiziert | Mehrere Extraktoren | Bestand, Einstandskosten, steuerliche Daten |
| Split / Fusion / Kapitalmaßnahme | Nicht unterstützt | Teilweise/bankabhängig | vollständiges Modell und Bestandsinvarianten |
| Storno / Korrektur | Revisionsänderungen vorhanden, Belegsemantik begrenzt | Bankabhängig | explizite Gegenbuchungsbeziehungen |
| Währungsumrechnung | Teilweise | Breite Unterstützung | Wechselkurs-/Brutto-/Nettoinvarianten |
| Ein-/Auszahlung | Unterstützt | Unterstützt | Klassifikation generischer Bankbuchungen |
| Interne Umbuchung | Teilweise | Unterstützt | Paarbildung ohne Performancewirkung |

Die Kernfelder Datum, Betrag, Währung, Konto, Wertpapier, ISIN/WKN und Menge
sind im Modell vorhanden. Handelsdatum, Buchungsdatum und Valuta werden nicht in
jedem Importer gleich vollständig belegt. Gleiches gilt für Kurs, Brutto,
Netto, einzelne Steuerarten, Gebühren, Wechselkurs und Belegreferenzen. Pro
Dokumenttyp sollte deshalb ein verbindlicher Feldvertrag definieren, welche
Felder Pflicht, optional oder rechnerisch ableitbar sind.

## 7. Datenintegrität und Dubletten

### 7.1 Positiv nachgewiesen

Der in `main` enthaltene Depot-/Bankbuchungsabgleich behebt zentrale Risiken:

- Eine automatische Geldbuchung wird nur bei eindeutiger Zuordnung verwendet;
  zwei gleich hohe Käufe dürfen nicht dieselbe Kandidatenbuchung konsumieren.
- Bereits gespeicherte Verknüpfungen reservieren den verfügbaren Betrag.
- Manuelle Zuordnungen prüfen Depot, erlaubte Zahlungskonten, Währung,
  wirtschaftliche Richtung und verfügbare Beträge auf beiden Seiten.
- BUY akzeptiert nur Belastungen; SELL und DIVIDEND nur Gutschriften; TAX und
  FEE nur Belastungen.
- Belege und Geldbuchungen bleiben getrennt gespeichert; für die Performance
  soll nur der wirtschaftliche Vorgang zählen.
- Regressionstests decken doppelte Kandidaten, Gegenrichtung, gleich hohe
  Käufe, Teilbeträge und bestehende Links ab.

Auch die allgemeine Dublettenlogik ist bewusst konservativ: starke
Order-/Dokument-/Ausführungsreferenzen haben Vorrang; gleiche Beträge allein
reichen bei mehreren Kandidaten nicht aus. Wiederholte identische Dateien und
identische externe IDs werden zusätzlich auf Speicherebene erkannt.

### 7.2 Offene Risiken

| Szenario | Beobachtung | Wirkung | Einstufung |
|---|---|---|---|
| Teilzuordnung einer Sammelzahlung | Jede aktive Verknüpfung unterdrückt die vollständige Cash-Buchung; `allocated_amount` wird nicht anteilig in Performance-Flows verwendet | Falsche TWR/Modified-Dietz/XIRR; Unter- oder Überzählung des externen Cashflows | **Kritisch (P0)** |
| Teilweise abgeglichene Depotbuchung | UI-Status wird bei einem vorhandenen Link bereits „Manuell bestätigt“, auch wenn ein Restbetrag offen ist | Nutzer übersieht offenen Rest; Folgezuordnung oder Prüfung unterbleibt | Hoch (P0) |
| Kaufbeleg plus Giroabbuchung | Mit explizitem Link korrekt; ohne eindeutige Referenz bleibt Konflikt/offen | Bei manueller Fehlentscheidung falscher Performanceflow, Rohsaldo bleibt korrekt | Hoch |
| Dividendenbeleg plus Gutschrift | Spezielle Konsolidierung verlangt Eindeutigkeit | Mehrfachimporte können sonst Ertrag/Steuer/Performance doppeln | Kritisch |
| Verkauf plus Gutschrift | Nur bei unterstütztem Beleg und Link sicher | Erlös, realisierter Gewinn und XIRR können doppelt zählen | Kritisch |
| Steuerbeleg plus Bankabzug | Keine universelle fachliche Ereignis-ID über alle Importer | Steuer und Performanceflow können doppelt zählen | Kritisch |
| Storno und Neuausführung | Fingerprints schützen nicht vor fachlich verschieden referenzierten Gegen-/Neubuchungen | Bestand, Einstandskosten und realisierter Gewinn falsch | Kritisch |
| Teilausführungen | Gleiche ISIN/Beträge dürfen nicht pauschal zusammengelegt werden | Verlust echter Trades oder Doppelzählung | Hoch |
| Gleich hoher Kauf verschiedener Wertpapiere | Neue Exklusivitätslogik verhindert automatische Mehrfachverwendung | Konflikt erfordert Nutzerentscheidung | Beherrscht |
| Handels- vs. Valutadatum | Drei-Tage-Fenster nutzt Zahlungs-/Valutadaten, soweit vorhanden | Feiertage, FX und längere Settlementzyklen können echte Treffer verpassen | Mittel |
| Teilbestand aus Tabelle | Vollständigkeit ohne Kontrollsumme nicht beweisbar | Depotbestand und Gesamtvermögen können sinken, obwohl nur Importzeilen fehlen | Kritisch |

### 7.3 Auswirkungen auf Kennzahlen

- **Depotbestände:** werden primär von Beständen und Wertpapierereignissen
  bestimmt. Fehlende Verkäufe, Überträge oder ein fälschlich vollständiger
  Snapshot sind direkt bestandswirksam.
- **Geldkontosalden:** basieren auf den tatsächlichen Geldbuchungen; ein
  Settlement-Link löscht keine Rohbuchung. Das schützt den Saldo, löst aber
  keine falsche Klassifikation.
- **Einstandskosten/realisierte Gewinne:** hängen an korrekten Mengen, Trades,
  Gebühren und Stornos. Das aktuelle Linkmodell validiert Zahlungen, ergänzt
  aber keine fehlenden steuerlichen Anschaffungsdaten.
- **Dividenden/Steuern:** parallele PDF- und Kontobelege brauchen eine
  gemeinsame wirtschaftliche Ereignis-ID oder eine eindeutige Verknüpfung.
- **TWR/Modified Dietz/XIRR:** `performance_transactions()` unterdrückt bei
  Verknüpfung die Geldseite. Das verhindert die normale Doppelwirkung, ist bei
  Teilzuordnungen aber nicht proportional und daher P0.
- **Gesamtportfoliovermögen:** ein Link verändert weder Bestand noch Rohsaldo.
  Falsche oder unvollständige Importdaten tun dies dagegen unmittelbar.

Empfohlene Invariante: Für jede Zuordnungsgruppe müssen Summe der Anteile,
Restbeträge und Performancewirkung getrennt berechnet werden. Nur ein vollständig
zugeordneter Anteil darf von der Cash-Seite unterdrückt werden. UI und API
müssen `offen`, `teilweise`, `vollständig` und `überbucht` unterscheiden.

## 8. CSV und Excel

PP ist funktional überlegen bei wiederverwendbaren Profilen und Zieltypen.
Portman bietet die fachlich wichtigen Grundparameter, aber keine gleichwertig
nachgewiesene Verwaltung mehrerer benannter Profile, automatische Vorschläge
für Encoding/Delimiter/Datums- und Zahlenformate oder separate Zielschemata für
Kurse und Stammdaten.

Empfehlungen:

1. Profile versioniert mit Quellkennung, Header-Signatur und Beispieldaten
   speichern; Änderungshistorie und explizite Benutzerbestätigung vorsehen.
2. Encoding, Trennzeichen, Dezimal-/Tausenderformat und Datum aus einer Probe
   vorschlagen, aber niemals still festlegen.
3. Vorschau mit Zeilenstatus, Rohwert, normalisiertem Wert und konkretem Fehler;
   fehlerhafte Zeilen dürfen nicht unbemerkt übersprungen werden.
4. Für Bestände Pflichtkontrollen anbieten: erwartete Positionszahl,
   Depotgesamtwert, Seiten-/Zeilenanzahl und expliziter
   `vollständig/unvollständig`-Status. Fehlt der Nachweis, muss der sichere
   Standard `complete=False` sein.
5. Große Dateien streamen/chunken und die Speicherung batchen; siehe Benchmark.

## 9. PDF und OCR

Portmans lokale OCR, Größenbegrenzung, Review-Markierung und konservative
Pluginwahl sind gute Sicherheitsmechanismen. Risiken bleiben bei gescannten,
mehrseitigen oder gemischten Dokumenten: OCR kann Dezimaltrennzeichen, Minus,
Datum, ISIN/WKN oder Währung falsch erkennen. Eine hohe allgemeine
OCR-Konfidenz beweist nicht die Korrektheit eines Finanzfeldes.

Jeder Parser sollte deshalb mindestens folgende Invarianten prüfen:

- ISIN-Prüfziffer bzw. WKN-Format und eindeutige Stammdatenzuordnung,
- Stück × Kurs plus/minus Gebühren/Steuern gegen Brutto/Netto,
- Vorzeichen passend zu BUY/SELL/DIVIDEND/TAX/FEE,
- Währung und Wechselkurs auf beiden Seiten der Rechnung,
- Summen, Anfangs-/Endsaldo und Seitenvollständigkeit,
- Dokumenthash plus bankseitige Referenz als getrennte Identitäten,
- keine automatische Buchung bei fehlenden Pflichtfeldern oder mehreren
  ähnlich guten Plugins.

OCR sollte pro kritischem Feld Konfidenz und Bounding Box speichern. Ein
kritisches Feld unter Schwellwert führt zu manueller Bestätigung, nicht nur zu
einem allgemeinen Warnbanner. Für Layoutänderungen werden anonymisierte
Original-/Text-/Erwartungs-Fixtures benötigt.

## 10. Importperformance

### 10.1 Reproduzierbarer Benchmark

`benchmarks/benchmark_import_pipeline.py` erzeugt deterministische,
personenfreie CSV-Daten und misst Parser und Speicherung getrennt. Umgebung:
lokale Windows-/Python-/SQLite-Installation dieses Arbeitsbaums; drei Läufe je
Größe, Median. Die Werte sind Messungen, keine Vorher-/Nachher-Behauptung.

| Zeilen | CSV-Größe | Parser Median | Parserrate | SQLite-Commit Median | Commitrate |
|---:|---:|---:|---:|---:|---:|
| 1.000 | 112.847 B | 59,8 ms | 16.719/s | 406,6 ms | 2.460/s |
| 10.000 | 1.147.847 B | 712,4 ms | 14.037/s | 3.076,7 ms | 3.250/s |
| 50.000 | 5.827.847 B | 3.159,4 ms | 15.826/s | 17.239,7 ms | 2.900/s |

Plugin-Discovery fand in fünf Läufen jeweils elf Plugins. Der erste Lauf
benötigte 604,7 ms, die vier warmen Läufe 289,5–315,0 ms (Median 307,2 ms).
Da der Worker nur einmal pro PDF-Sammelauftrag entdeckt, ist das relevant für
Einzelimporte, aber nicht der größte Bulk-Engpass.

### 10.2 Engpassanalyse

| Bereich | Typ | Befund / Maßnahme |
|---|---|---|
| PDF-Textextraktion | CPU/I/O | PyMuPDF-Schnellpfad beibehalten; Seiten nur einmal extrahieren und Ergebnis je Hash cachen |
| OCR | CPU | Durch Lock serialisiert; Modellcache hilft. Sichere Parallelität erst mit Prozess-/Speicherbenchmark prüfen |
| Plugin-Erkennung | CPU/I/O | Rund 0,3 s warm; Registry pro Prozess und Dateisignatur cachen, Beispiel-Plugin ausschließen |
| CSV/Excel | CPU/RAM | CSV skaliert linear; Streaming/Chunks für sehr große Dateien, XLSX `read_only` ist bereits sinnvoll |
| Dublettenprüfung | CPU/DB | Referenz-/Fingerprintindizes und vorberechnete normalisierte Schlüssel verwenden |
| Datenbankvalidierung/Speicherung | DB | Gemessener Hauptengpass: etwa 2,5–3,25 Tsd. Zeilen/s; Batch-`executemany`, weniger per-row Queries, Transaktionsgrenzen profilieren |
| Vorschau | GUI/RAM | Virtuelle/paginierte Tabelle statt aller Zeilenwidgets; Fehler aggregieren und Details lazy laden |
| Portfolioansichten | CPU/DB/GUI | Nach Import nur betroffene Konten/Zeiträume invalidieren; teure Kennzahlen asynchron berechnen |

PDF/OCR-Benchmarks wurden nicht angegeben, weil im Repository kein hinreichend
großer, lizenz- und datenschutzrechtlich geeigneter Belegkorpus für belastbare
Vergleiche vorlag.

## 11. Teststrategie und Lücken

Portman enthält 782 statisch gezählte Testmethoden (Parametrisierung erhöht die
tatsächliche pytest-Fallzahl). Davon betreffen Dateinamen grob 81 PDF-, 106
Import-, 30 Settlement-, 17 Dubletten-, 11 Depotbuchungs-, 12 Krypto-Wallet-,
4 Excel- und 4 PP-Importtests. Die Bankzählungen überlappen mit diesen Gruppen.

Die vollständige Suite wurde auf dem oben genannten Portman-Commit mit Python
3.13.9, pytest 8.4.2 und PySide6 6.9.2 ausgeführt: **950 bestanden, 9
übersprungen, 0 fehlgeschlagen** in 244,56 Sekunden. Ein erster Lauf war wegen
eines nicht zugreifbaren globalen Windows-pytest-Tempverzeichnisses nicht
auswertbar; die unveränderte Suite lief danach mit einem isolierten
Projekt-Tempverzeichnis vollständig grün.

Die größten Lücken sind vollständige Lebenszyklen statt einzelner Parserfälle:

1. Kauf → Teil-/Sammelzahlung → Verkauf → Steuer/Gebühr → Performance für zwei
   Wertpapiere mit gleichen Beträgen.
2. PDF-Beleg plus Bankfeed plus Wiederholungsimport, jeweils mit und ohne starke
   Referenz sowie mit abweichendem Handels-/Valutadatum.
3. Storno/Neuausführung, Teilausführung und Depotübertrag mit Erhaltung von
   Menge, Einstandskosten und realisiertem Gewinn.
4. Alle Steuerkomponenten, Erstattung, Quellenwährung und Wechselkursrechnung.
5. Abgeschnittene XLSX/PDF-Dateien, fehlende Seiten/Zeilen und falsche
   Vollständigkeitskennzeichnung.
6. OCR-Mutationen für Minuszeichen, Komma/Punkt, Datum, ISIN und Währung.
7. Große Imports mit Zeit-, Speicher- und Query-Budgets.

Empfohlene Fixture-Struktur:

```text
tests/fixtures/importers/<anbieter>/<dokumenttyp>/<layout-version>/
  source.txt           # anonymisierter Extraktionstext oder synthetisches PDF
  expected.json        # normalisierte Items und Pflichtwarnungen
  provenance.json      # Layoutdatum, Anonymisierung, erlaubte Verwendung
  mutations/           # OCR-/Seiten-/Zahlenfehler
```

Jeder Fall sollte Invarianten für Rohbuchungen, wirtschaftliche Ereignisse,
Bestände, Salden, Einstandskosten, realisierte Gewinne, Steuern, TWR, Modified
Dietz, XIRR und Gesamtvermögen vor und nach Wiederholungsimport prüfen. Fixtures
dürfen keine echten Namen, Konto-/Depotnummern, Adressen, Barcodes oder
Dokumentreferenzen enthalten. Reale Belege sind vor Aufnahme automatisiert und
manuell auf Metadaten sowie eingebettete Bilder zu prüfen.

## 12. Priorisierte Umsetzung

### P0 – vor Ausbau weiterer Banken

1. Performance-Settlement anteilig machen: Restbeträge erhalten, nur
   zugeordnete Anteile unterdrücken und vollständige/teilweise Status getrennt
   anzeigen. Invarianten für TWR, Modified Dietz und XIRR ergänzen.
2. Generische Bestandsimporte standardmäßig als unvollständig behandeln, sofern
   Positionszahl oder Depotwert nicht erfolgreich abgeglichen wurden.
3. ING- und comdirect-Verkäufe sowie Baader/zero-Ertrags- und Steuerdokumente
   schließen, damit Kernanbieter keinen einseitigen Lebenszyklus erzeugen.

### P1 – hoher praktischer Nutzen

1. Benannte, versionierte CSV-Profile mit Vorschlägen, Vorschaukorrektur und
   unterschiedlichen Zielschemaarten.
2. Trade Republic als neue Quelle; anschließend Nachfrage und anonymisierte
   Fixture-Verfügbarkeit für weitere Anbieter messen.
3. Einheitlicher Importervertrag für Pflichtfelder, Recheninvarianten,
   wirtschaftliche Ereignis-ID und harte/weiche Fehler.
4. PP-XML-Testmatrix verbreitern und unterstützte Formatversionen klar melden.

### P2/P3 – Ausbau

- P2: DEGIRO, XTB und Deka-Lebenszyklus; IB Flex wegen FX-/Derivatekomplexität
  separat planen.
- P3: Long-Tail-Banken nur mit Nachfrage, legal nutzbaren Fixtures und
  dauerhaftem Wartungsbudget. Numerische PP-Parität allein ist kein sinnvolles
  Ziel.

## 13. Quellennachweis im Arbeitsbaum

Besonders relevant waren:

- `src/portfolio_v5/importers.py`, `pdf_importer.py`, `pdf_ocr.py`,
  `booking_duplicates.py`, `settlement.py` und `pdf_plugins/`
- `pdf_plugins/` und `docs/pdf-import.md`
- `src/portman/import_v09.py`, `import_worker.py`,
  `automatic_bank_import.py`, `portfolio_performance_import.py`,
  `repository_v09.py`, `storage_v09.py`, `excel_import.py`
- Tests zu comdirect, ING, Baader, PDF, Dubletten, Settlement,
  Depotbuchungsabgleich, Tabellen-, Wallet- und PP-Import
- PP: `name.abuchen.portfolio/.../datatransfer/{pdf,csv,ibflex,traderepublic,xtb}`
  sowie die zugehörigen Testverzeichnisse und Importaktionen

Externe Anbieterhinweise wurden nur zur organisatorischen Einordnung von
finanzen.net zero verwendet: Preis-/Leistungsverzeichnis und Feature-Seite
weisen Baader Bank als konto-/depotführende Bank und Tangany als
Kryptoverwahrer aus. Maßgeblich für Parseraussagen blieb der untersuchte Code.
Quellen: [zero Preis-/Leistungsverzeichnis](https://www.finanzen.net/zero/wp-content/uploads/2025/Preis-Leistungsverzeichnis-Wertpapiere.pdf),
[zero Features](https://www.finanzen.net/zero/features/) und [PP-Issue zur
Baader-Frontend-Erkennung](https://github.com/portfolio-performance/portfolio/issues/5234).
