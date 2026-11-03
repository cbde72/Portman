# Portman PDF Lab – Phase-3-Implementierungsbericht

**Datum:** 30.10.2026  
**Ausgangscommit:** `8eb0091bdd95cce40ee4ea35469e14ec139e2c8e`  
**Pakete:** `portman-parsers 0.3.0`, `portman-pdf-lab 0.3.0`  
**API-Version:** `0.3`  
**Schema-Version:** `1.2.0`

## 1. Ergebnis

Phase 3 ist technisch umgesetzt. Es bestehen zwei getrennt paketierbare
Python-Projekte. Der Parserkern besitzt keine V09-, PDF-, OCR-, GUI- oder
Persistenzabhängigkeit. PDF Lab hängt ausschließlich vom veröffentlichten
Paketvertrag `portman-parsers>=0.3,<0.4` ab.

Die 33 freigegebenen Handler sind als Metadaten vorhanden, aber noch nicht als
Bankparser implementiert. Jeder Aufruf eines Platzhalters endet explizit mit
`NOT_IMPLEMENTED`. Damit wurde keine verborgene Teilmigration vorgenommen.

## 2. Neue Dateistruktur

```text
portman-parsers/
  pyproject.toml
  README.md
  src/portman_parsers/
    api/          documents, detection, events, evidence, issues, results
    registry/     allowlist, registry
    validation/   money, cashflows, references, consistency
    extraction/   interfaces, text_adapter
    utilities/    dates, numbers, identifiers
    plugins/      reservierter Phase-4-Namespace
  tests/
    unit/ contract/ architecture/ fixtures/

portman-pdf-lab/
  pyproject.toml
  README.md
  src/portman_pdf_lab/
    application/  AnalysisService und AnalysisReport
    analysis/     Qualitätszusammenfassung
    reviews/      ReviewDecision und ReviewStatus
    storage/      reservierte Persistenzgrenze
    ui/           reservierte UI-Grenze, keine GUI
    cli.py, demo.py, __main__.py
  tests/
    unit/ integration/ fixtures/

docs/
  architecture/pdf-lab-phase-3.md
  audits/README.md
```

## 3. Datenmodell und API-Vertrag

Implementiert sind:

- `PdfDocument` und `PdfPage` ohne PDF-Binärdaten/Base64.
- `Detection` mit Plugin, Version, Handler, Dokumenttyp und `Decimal`-Konfidenz.
- `ParsedDocument` als deterministisch serialisierbares Aggregat.
- `FinancialEvent` mit getrennten `CashMovement`, `SecurityMovement`,
  `TaxEvent` und `CostEvent`.
- `PositionSnapshot` und `Position` ohne künstliche Trades.
- `Evidence` mit Dokument-, Seiten-, Feld- und Quellreferenz.
- `Issue` mit stabiler Kennung, Code, Schweregrad und optionalen
  Evidence-/Eventreferenzen.
- `MissingValue.UNKNOWN`, `NOT_APPLICABLE` und `NOT_FOUND` getrennt von `0`.
- `Depot` und `Account` als eigenständige Stammdatenaggregate.
- `DepotSnapshot`/`DepotPosition`, `AccountBalance` und `DepotAccountLink` als
  von Stammdaten, Transaktionen und Wirtschaftsereignissen getrennte Verträge.
- `FieldValue` mit Wert, Herkunft (`PDF`, `MANUAL`, `DERIVED` oder
  `NOT_PROVIDED`), PDF-Seite, Evidence-IDs und Reviewstatus.

Vorzeichenkonvention: Cashzufluss positiv, Cashabfluss negativ. Steuer- und
Kostenkomponenten werden als nichtnegative Beträge modelliert. Sie werden nur
zahlungswirksam, wenn sie eine konkrete Cashbewegung referenzieren.

Die JSON-Konvertierung serialisiert `Decimal` verlustfrei als Dezimalstring,
Datumswerte als ISO-8601 und Enums über ihre stabilen Werte. Mappings werden
sortiert, DTOs sind eingefrorene Dataclasses mit Slots.

PDF-extrahierte Feldwerte müssen technisch mindestens eine PDF-Seite und eine
existierende Evidence referenzieren. Die Seitenangabe muss mit der Evidence
übereinstimmen. Manuell gepflegte Stammdaten bleiben durch `ValueSource.MANUAL`
von PDF-Werten unterscheidbar. Nicht belegte Eigenschaften werden mit
`MissingValue.UNKNOWN` geführt und nicht geschätzt.

Mehrere Depots je Bank und mehrere Verrechnungskonten je Depot sind durch
stabile Identitäten und mehrere `DepotAccountLink`-Datensätze möglich.
`CashMovement.account_id` und `SecurityMovement.depot_id` ordnen beide Seiten
eines Trades zu. Gegenseitige Movement-Referenzen verbinden Settlement und
Wertpapierbewegung, ohne einen zweiten Cashflow oder Trade zu erzeugen.

## 4. Registry und Negativauswahl

Die Allowlist umfasst acht Gruppen, neun Plugin-Einstiegspunkte und exakt 33
Handler. comdirect besitzt wie gefordert zwei Einstiegspunkte:
`user.comdirect-ertraege` und `comdirect.finanzreport`.

Die Registry bietet Registrierung, Metadaten, Erkennung, Mindestkonfidenz,
deterministische Sortierung, Ambiguitätsfehler, gezielte Auswahl und Parseaufruf.
Beliebige Dateisystem-Discovery existiert nicht.

`pbb_direkt` und `baader_krypto` sind ausschließlich als Blocklistenwerte für
Negativtests bekannt. Es gibt keine entsprechenden Module, Imports,
Entry-Points oder Handler. Architekturtests prüfen Modul- und Importausschluss.

## 5. Bankunabhängige Validierung

Implementiert wurden:

- `Decimal`-Toleranzprüfung für Geldbeträge.
- Kauf-/Verkaufs-/Dividendenvorzeichen.
- Brutto-Netto-Abgleich mit Steuern und Gebühren.
- Prüfung von Steuer-/Kostenreferenzen auf Cashbewegungen.
- kritischer Befund für informative MiFID-Kosten mit Cashwirkung.
- Vorabpauschale ohne automatisch erfundene Geldbewegung.
- Snapshotmodell ohne implizite Transaktion.
- Stornoverknüpfung und Neutralitätsprüfung.
- einfache wirtschaftliche Duplikatsignatur.
- Evidence-Referenzprüfung und aggregierte Dokumentvalidierung.

Ein mathematisch konsistentes Ergebnis erhält dadurch keine automatische
Ground-Truth-Freigabe. Der Reviewstatus ist separat im PDF-Lab-Modell angelegt.

## 6. PDF-Lab-Anwendung

`AnalysisService` nimmt ein öffentliches `ParsedDocument` entgegen, führt die
bankunabhängigen Prüfungen aus und liefert `AnalysisReport` mit Issues und
Laufzeit. `quality_summary` fasst Ereignisse, Snapshots, Schweregrade und
Reviewbedarf zusammen.

Der CLI-Aufruf `python -m portman_pdf_lab demo` erzeugt und analysiert einen
vollständig synthetischen Kauf mit Settlement, Wertpapierzugang, Steuer und
Gebühr. Die Demo enthält außerdem ein Depot, zwei Verrechnungskonten, zwei
Depot-Konto-Verknüpfungen, einen Kontosaldo und einen Depot-Snapshot.

Als einfache Demonstrationsansichten ohne GUI-Framework stehen `depot_view`,
`account_view` und `depot_account_link_view` bereit. Sie projizieren Stammdaten,
Bestände, Salden und Verknüpfungen getrennt und erhalten die Feldprovenienz.
Es wurde keine vollständige GUI implementiert.

### Gebühren & Kosten

Die Phase-3-Erweiterung stellt ein bankübergreifendes Gebührenmodell bereit:

- `FeeEvent` erfasst Kategorie, Unterkategorie, Betrag, Währung, Datum, Bank,
  Depot, Konto, Wertpapier, Transaktion, Cashbewegung, Dokument und Evidence.
- `FeeEffect` unterscheidet `ACTUAL_BOOKED`, `INCLUDED_IN_SETTLEMENT`,
  `INFORMATIONAL`, `ESTIMATED`, `REFUND` und `REVERSAL`.
- `FeeAllocation` ordnet eine Gebührenposition mehreren Objekten zu, ohne den
  Betrag zu vervielfachen.
- `CostInformationType` unterscheidet MiFID-II `MIFID_EX_ANTE` und
  `MIFID_EX_POST`; beide bleiben informatorisch und cash-neutral.
- Deduplizierung verhindert die doppelte Zählung derselben Kostenposition aus
  Handelsabrechnung und Kontoauszug und erzeugt einen Reviewhinweis.
- Settlementvalidierung prüft Käufe und Verkäufe aus Kurswert, deduplizierten
  enthaltenen Gebühren, Steuern und Netto-Settlement.
- Rückerstattung und Storno werden über positive Quellbeträge mit negativer
  wirtschaftlicher Wirkung modelliert; Storno referenziert die Ursprungsgebühr.
- Aggregationen unterstützen Bank, Depot, Konto, Wertpapier, Kategorie,
  Unterkategorie, Transaktion, Wirkungsart und Zeitraum. Fremdwährungen werden
  ohne dokumentierte Umrechnung niemals addiert.
- `IssueNature` trennt fehlende Information, ungesicherte Zuordnung,
  mathematische Inkonsistenz und bestätigte Abweichung.

`fee_cost_view` bereitet den späteren Reiter „Gebühren & Kosten“ vor. Die
Projektion enthält Filter, gebuchte und informatorische Positionen,
Transaktionssummen, Dokumentnachweise, Dubletten-/Abweichungswarnungen und
einen währungsgetrennten Bankenvergleich. Es wurde keine GUI implementiert.

## 7. Abhängigkeiten

### Laufzeit

- `portman-parsers`: keine externen Laufzeitabhängigkeiten.
- `portman-pdf-lab`: ausschließlich `portman-parsers>=0.3,<0.4`.

### Build und Test

- `setuptools>=77`: standardkonformes Wheel-/Sdist-Buildbackend.
- `pytest>=8`: ausschließlich optionales Testextra.

Es wurden bewusst keine DTO-, Validierungs-, CLI-, PDF- oder GUI-Frameworks
aufgenommen. PDF-/OCR-Pakete werden weder deklariert noch importiert.

## 8. Tests und Messergebnisse

Neu erstellte Tests: **60**, alle erfolgreich.

```text
60 passed in 0.70s
```

Abgedeckt sind DTO-/JSON-Vertrag, Decimal/Währung, Missing-Value-Semantik,
Identitäten, Evidence, Allowlist, 33 Handler, deterministische Registry,
Ambiguität, `NOT_IMPLEMENTED`, alle geforderten synthetischen Finanzregeln,
Konto-/Depotidentitäten, mehrere Verrechnungskonten, Salden, Snapshots,
Verknüpfungen, Feldprovenienz, Architekturgrenzen, Paketimport und CLI-Smoke-Test.
Zusätzlich geprüft werden mehrteilige Kauf-/Verkaufsgebühren, MiFID Ex ante und
Ex post, dokumentübergreifende Dubletten, Rückerstattung/Storno,
Fremdwährungsgebühren, widersprüchliche Settlements, Qualitätsarten,
Mehrfachzuordnungen und dimensions-/zeitraumbezogene Kostenaggregation.

Frischinstallation unter Python 3.14.3:

- `portman-parsers-0.3.0` wurde als Wheel gebaut, installiert und importiert.
- `portman-pdf-lab-0.3.0` wurde als separates Wheel gebaut, nach Installation
  seiner Parserabhängigkeit installiert und mit der Gebühren-Demo erfolgreich
  ausgeführt.
- Die von Python 3.14 erzeugten Test-venvs enthielten zunächst kein
  `setuptools`; nach Installation des im `build-system` deklarierten
  `setuptools 84.2.1` waren beide Builds erfolgreich.

Einzelmessungen in der frischen Lab-Umgebung, inklusive Python-Prozessstart:

- Import `portman_parsers.api`: **246,08 ms**.
- synthetischer CLI-Demolauf: **279,25 ms**.
- reine Validierung im bereits gestarteten Demo-Prozess lag im gemessenen Lauf
  bei rund **0,03 ms**; dieser Einzelwert ist kein belastbarer Benchmark.

## 9. Architekturtests und V09-Unverändertheit

AST-basierte Tests verbieten im Parserkern Imports von `portfolio_v5`,
`portman_pdf_lab` und Portman-GUI. PDF Lab darf weder `portfolio_v5`,
`pdf_plugins` noch V09-GUI importieren. Ein Importtest stellt sicher, dass DTOs
keine PDF-/OCR-Pakete laden.

**Bestätigung:** Keine vor Phase 3 vorhandene V09-Datei wurde verändert,
verschoben oder gelöscht. Es gab keine Datenbank-, Benutzerdatei-, V10-,
Parser-, Test- oder GUI-Änderung im bestehenden Portman-Code. Alle
Implementierungen liegen in den zwei neuen Projekten und den neuen
Dokumentationsdateien.

## 10. Abweichungen und offene Entscheidungen

- Die angeforderte Struktur wurde beibehalten. Zusätzlich liegen CLI und Demo
  direkt im Lab-Paket, um eine unnötige Abstraktionsebene zu vermeiden.
- Die Phase-2-Baseline bleibt bei 33 Handlern und 140 bestandenen
  Charakterisierungstests. Diese Alt-Tests wurden in Phase 3 nicht kopiert oder
  umgedeutet.
- Phase 1 lag außerhalb des Repositorys auf dem Desktop; die Datei wurde nur
  gelesen. Phase 2 lag im aktiven Arbeitsbaum vor.
- `storage` und `ui` sind bewusste Grenzen ohne Implementierung. Persistenz- und
  GUI-Entscheidungen wären in Phase 3 verfrüht.
- JSON-Schema-Dateien werden erst ergänzt, wenn der DTO-Vertrag nach der ersten
  Parsermigration praktisch validiert wurde; Schema- und API-Version sind
  bereits im Vertrag vorhanden.
- Die einfache Duplikatsignatur ist ein Reviewhinweis, keine automatische
  Deduplizierung.
- Ground-Truth-Repository, Batch-Audit und Versionsdiff bleiben Aufgaben nach
  der ersten Parsermigration.

## 11. Empfehlung für Phase 4

Empfohlene Reihenfolge:

1. **Bank of Scotland** – ein Handler, klare Salden-/Summenregeln; kleinster
   End-to-End-Nachweis für Statement, Evidence und Cashklassifikation.
2. **FNZ / Finvesto** – zwei Handler; Trade/Ertrag/Snapshot erweitern den
   Vertrag kontrolliert.
3. **Deka** – ein Handler mit Snapshot plus Umsatzblöcken.
4. **ING** – sechs Handler; vorher die drei Phase-2-Golden-Lücken schließen.
5. **Baader** – strenge Snapshot-, Trade-, Transfer- und Stornoregeln.
6. **comdirect Finanzreport** – Legacy-/Core-Layout und Depotpfad.
7. **comdirect Erträge** – größte fachliche Breite; fehlende Einlösungs- und
   Ertragsgutschrift-Goldens zuerst ergänzen.
8. **Renault und generischer Fallback** – gemeinsamer Statementkern zuletzt,
   weil konservativer Review-/Archivworkflow vor produktiver Nutzung stehen
   muss.

Jede Migration sollte genau einen Handler oder einen eng gekoppelten
Handlerverbund umfassen, bestehende Charakterisierung zunächst unverändert
ausführen und erst danach native DTO-/Evidence-Vertragstests ergänzen.

## 12. Abnahme

Die Phase-3-Kriterien sind erfüllt:

- zwei getrennte, installierbare Projekte;
- Parserkern ohne V09-Abhängigkeit;
- versionierte öffentliche API und Schemaangabe;
- Registry mit allen freigegebenen Plugin-IDs und 33 Handlern;
- technisch blockierte ausgeschlossene Plugins;
- synthetisch getestete Wirtschafts- und Validierungsmodelle;
- lauffähige PDF-Lab-Anwendungsschicht und CLI-Demo;
- 60/60 neue Tests erfolgreich;
- bestehende V09-Dateien unverändert.
