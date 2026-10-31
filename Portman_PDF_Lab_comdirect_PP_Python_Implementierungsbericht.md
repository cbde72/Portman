# Portman PDF Lab – comdirect PP Python Implementierungsbericht

**Stand:** 31.10.2026  
**Portfolio-Performance-Commit:** `c08d5053f0066f0fad0685a3e35bd7b7037c9b0f`  
**Neue Parser-ID:** `portfolio-performance.comdirect`  
**Parser-Version:** `pp-c08d5053`

## Ergebnis und Architektur

`ComdirectPPPlugin` ist eine zweite, separat registrierte Python-Implementierung.
Sie importiert weder den bestehenden Portman-comdirect-Parser noch Java,
PDFBox, Portfolio-Performance-Modelle oder GUI-Code. Die Variante verwendet
ausschließlich öffentliche `portman-parsers`-DTOs und kann unabhängig über ihre
Plugin-ID gewählt und getestet werden.

Der bestehende Parser blieb fachlich unverändert. Seine Detection-Werte von
0,98/0,99 liegen über 0,90 der PP-Variante; deshalb bleibt er im normalen
Registry-Pfad Standard. Der Vergleichsdienst wählt beide Varianten explizit
und führt sie unabhängig auf demselben `PdfDocument` aus.

## Herkunft und Lizenz

Analysiert wurden im öffentlichen Portfolio-Performance-Repository:

- `ComdirectPDFExtractor.java`;
- `ComdirectPDFExtractorTest.java`;
- die generische `PDFParser`-/`PDFExtractor`-Infrastruktur;
- die in den Tests verwendeten Transaktions-, Geld-, Security- und Unit-Konzepte;
- 141 vorhandene comdirect-Textfixtures als Layoutinventar.

Portfolio Performance steht auf dem untersuchten Commit unter Eclipse Public
License 1.0. EPL‑1.0 erlaubt Nutzung, Bearbeitung und Weitergabe, verlangt bei
Quellweitergabe des Programms aber insbesondere EPL‑Lizenzierung, Lizenzkopie,
Erhalt von Hinweisen und Identifizierbarkeit eigener Beiträge. Daher ist
`comdirect_pp.py` ausdrücklich EPL‑1.0 zugeordnet. Die vollständige Lizenz liegt
in `portman-parsers/LICENSES/EPL-1.0.txt`, die Herkunft in
`portman-parsers/NOTICE_COMDIRECT_PP.md`.

Es wurden keine Java-Dateien oder PP-Fixtures in das Produkt kopiert. Die
Python-Tests sind neu geschriebene synthetische Verhaltensfälle. Die regulären
Ausdrücke und Portman-DTO-Zuordnung wurden für Python neu strukturiert.

## Java-zu-Python-Funktionsmatrix

| PP-Java-Pfad | Beobachtete Funktion | Python-Funktion/Pfad | Status |
|---|---|---|---|
| Konstruktor / DocumentTypes | Parserpfade registrieren | `TITLES`, `detect` | implementiert |
| `addBuySellTransaction` | Kauf, Verkauf, Einlösung, Teilstücke, FX | `_security_transaction` | implementiert für freigegebene Handler |
| negativer Verkaufspfad | negatives/abweichendes Settlement | Vorzeichen aus Seite und Lasten/Gunsten | implementiert |
| `addDividendTransaction` | Dividende, Ertrag, Ausschüttung | `_security_transaction` | implementiert |
| `addTaxesTreatmentTransaction` | Steuerbehandlung zu Handel, Dividende, Einlösung, Vorabpauschale | `_tax_notice`, Tax-Komponenten | implementiert |
| Quellensteuer-/FX-Hilfen | Quellensteuer, Brutto, Wechselkurs | `TAX_PATTERNS`, `gross`, `fx` | implementiert, konservativ |
| Gebühren-Hilfen | Provision, Fremdspesen, Courtage, Börsenentgelt | `FEE_PATTERNS` | implementiert |
| `addFinancialReport` | Ein-/Auszahlungen, Gebühren, Steuern, Zinsen | `_financial_report` | implementierter generischer Buchungspfad |
| `addDepositoryFeeTransaction` | Verwahrentgelt mit Security | kein neuer Handler | Freigabekandidat |
| PP Parser DSL | Block/Section/Match/Assign | direkte Python-Regeln | bewusst nicht übernommen |
| Java `Money`/`Values` | skalierte Long-Werte | Python `Decimal` | implementiert |
| Java Client/Security Lookup | Security-Wiederverwendung | stabile Portman-IDs/DTOs | kein Clientzustand erforderlich |
| Java Transaction Units | Steuer, Gebühr, Brutto/FX | `TaxEvent`, `FeeEvent`, `SecurityTrade` | implementiert |

## Dokumenttypabdeckung

Freigegebene PP-Varianten innerhalb der bestehenden comdirect-Handler:

- `wertpapierkauf`;
- `wertpapierverkauf`;
- `dividendengutschrift`;
- `ertragsgutschrift`;
- `einloesung`;
- `investment_ausschuettung`;
- `dividende_steuer_inland`;
- `vorabpauschale`;
- `finanzreport`.

Portfolio Performance besitzt keinen entsprechenden eigenständigen
MiFID-II-Kosteninformationspfad im untersuchten Extractor. Deshalb behauptet
die PP-Variante keine Unterstützung für `kosteninformation_mifid_ii`.

Der Java-Extractor verarbeitet außerdem `Verwahrentgelt` sowie zahlreiche
spezifische Finanzreport-Buchungsklassen (Versandpauschale, Zinsen,
Steuerverrechnung, Ein-/Auszahlungen). Finanzreport-Buchungen werden im
Python-Pfad als echte, evidence-belegte Buchungen klassifiziert. Ein eigener
Handler `verwahrentgelt` wurde entsprechend dem Auftrag nicht stillschweigend
ergänzt und bleibt Kandidat für eine spätere Allowlist-Freigabe.

## Extraktion und wirtschaftliche Semantik

Unterstützt werden PP-typische Security-Zeilen wie
`Stk. …, WKN / ISIN: … / …`, Teilstücke, Wertpapiername, WKN, ISIN,
Geschäfts-/Valutatag, Kurs, Kurswert, Brutto, Devisenkurs und Settlement.
Gebühren und Steuern sind unsignierte Komponenten; die Richtung liegt am
Cashflow. Kaufsettlements sind negativ, Verkauf/Dividende positiv.

Ein Transaktionsbeleg ohne nachgewiesenes Konto erzeugt ausschließlich
`EXPECTED` Cash. Steuerliche Mitteilungen, Investment-Ausschüttung und
Vorabpauschale erzeugen keinen eigenen Cashflow. Vorabpauschalen verwenden
`TaxEvent` und `AdvanceTaxCalculation`; ohne bestätigten Regelsatz bleibt die
Berechnung `SYNTHETIC_ONLY`. Fehlende Werte werden als `MissingValue`
ausgegeben und nicht erfunden.

## Parservergleich im PDF Lab

`compare_comdirect_parsers` führt Portman und PP-Python separat aus. Verglichen
werden:

- Handlererkennung;
- Name, ISIN, WKN und Stückzahl;
- Kurs, Kurswert und Settlement;
- Cashbetrag und Cashstatus;
- Steuerkomponenten und Vorabpauschale;
- Gebühren;
- Konten und Depot-Konto-Links;
- Evidence-/Event-/Issue-Anzahl;
- Laufzeit.

Die Zeilen stehen im bestehenden Reiter **Referenzvergleich** und sind über die
vorhandene Qt-Tabellenauswahl kopierbar. Jede Zeile trägt
`is_confirmed_reference=false`; `agreement_is_not_reference=true` verhindert
eine fachliche Gleichsetzung mit bestätigten Sollwerten.

## Tests und übertragene Kategorien

Die eigenständigen synthetischen Python-Tests decken ab:

| Kategorie aus PP-Tests | Python-Abdeckung |
|---|---|
| Teilstückkauf | Stückzahl, Kurs, Kurswert, Gebühr, Settlement |
| Verkauf | negativer Security-Abgang, positive Gutschrift |
| Dividende/Ertrag | genau ein Cashflow plus Steuerdetails |
| Investment-Ausschüttung | steuerlich, cash-neutral |
| Vorabpauschale | cash-neutral, TaxEvent/Calculation |
| Gebühren/Steuern | mehrere Kategorien, Decimal, Vorzeichen |
| Finanzreport | Ein-/Ausgang, Gebühr, Dublette |
| Fehlende Felder | explizite Issues und `MissingValue` |
| Parservergleich | unabhängige Detection, Feldzeilen, Laufzeit |
| Herkunft | Commit und EPL-Metadaten |

Gesamter Abschlusslauf:

```text
145 passed in 4.74s
```

Die acht neu hinzugefügten PP-/Vergleichstests bestanden ebenfalls separat.
Es wurden ausschließlich synthetische Portman-Testtexte verwendet.

## Performancevergleich

Je 1.000 Parse-Läufe desselben synthetischen Teilstückkaufs, ohne
PDF-Extraktion:

| Parser | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Portman comdirect | 377,650 µs | 248,500 µs | 12.713,000 µs |
| PP Python | 477,150 µs | 277,000 µs | 14.742,700 µs |

Der Vergleichsbericht misst zusätzlich pro Dokument beide Laufzeiten mit
`perf_counter_ns`. Die Maximalwerte sind nicht als stabiler Benchmark zu
interpretieren; Medianwerte dienen als lokale technische Orientierung.

## Kritische Geldflussabweichungen

Im synthetischen Vergleich stimmen Stückzahl, Richtung und Settlement beider
Parser überein. Strukturelle Unterschiede können auftreten, weil der
PP-Python-Pfad ohne explizite IBAN ein Settlement immer `EXPECTED` lässt und
weil der Portman-Pfad zusätzliche Depot-/Kontomodelle besitzt. Solche
Abweichungen werden angezeigt, nicht automatisch vereinigt.

Steuerbehandlungsdokumente werden in beiden Pfaden ohne zusätzliche
Cashbewegung modelliert. Finanzreport-Buchungen werden nicht mit einem
Settlement zu einem zweiten Cashflow zusammengeführt; dokumentübergreifende
Deduplizierung bleibt Aufgabe der bestehenden Verknüpfungs-/Reviewebene.

## Offene Punkte und Freigabestatus

Technisch ist die zweite Variante installierbar, registriert und getestet.
Eine produktive fachliche Freigabe besteht nicht, weil keine anonymisierten,
ausdrücklich freigegebenen realen comdirect-PDFs verwendet wurden.

Offen sind:

1. vollständige Golden-Abdeckung der 141 öffentlich inventarisierten Layouts
   mit rechtlich und fachlich freigegebenen Referenztexten;
2. eigene Freigabeentscheidung für `verwahrentgelt`;
3. breitere Finanzreport-Tabellen- und Fremdwährungsvarianten;
4. koordinatengenaue Evidence statt reiner Seiten-/Textfundstelle;
5. persistente dokumentübergreifende Verknüpfung von Steuerbehandlung und
   Wertpapierabrechnung;
6. bestätigte Vorabpauschalen-Regelsätze und reale Referenzfälle.

V09 und V10 wurden nicht geändert. Es wurden keine Commits, Pushes oder Merges
ausgeführt.
