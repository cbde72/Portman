# Portman V09 - Renault Bank PDF-Parser P2

## 1. Ausgangsbasis

- Ausgangscommit: `509b100500e1` (`origin/main`, einschließlich PR #31 bis #34)
- Branch: `fix/renault-pdf-parser-p2`
- Unveränderte Baseline: PDF-Parser-Audit V2 vom 24.10.2026
- Originalbestand: `C:\Users\chris\Desktop\history\renault`
- Produktive Datenbank und Original-PDFs wurden nicht verändert.

## 2. Vollständiges Dokumentinventar

Die Baseline-Zahlen 170 + 24 sind keine 194 eindeutigen Renault-Dokumente. Das Verzeichnis enthält
200 physische PDFs mit 199 unterschiedlichen SHA-256-Inhalten. Die vollständige Datei-, SHA-,
Handler-, Zeitraum-, Salden- und Buchungsübersicht steht in
`test_reports/pdf_parser_audit/renault_p2_after/files.csv`.

| Klassifikation nach P2 | Physische Dateien | Buchungswirkung |
|---|---:|---|
| Formale Renault-Kontoauszüge | 163 | 529 physische / 465 eindeutige Renault-Buchungszeilen |
| Renault-Jahressteuerbescheinigungen | 18 | Archiv-only |
| Renault-Zinsmitteilungen | 7 | Archiv-only, da Kontoauszug dieselben Werte bucht |
| Renault-Freistellungsauftrag | 1 | Archiv-only; keine FSA-Nutzung abgeleitet |
| Sonstige Renault-Archivdokumente | 5 | Archiv-only |
| Bereits vorhandener generischer Handler | 4 | drei Vertragsunterlagen ohne Buchung; ein fremder Kontoauszug |
| Baader-Handler im Renault-Verzeichnis | 2 | bewusst nicht Renault zugeordnet |

Die einzige identische physische Kopie ist der Kontoauszug
`130765700_2016_Nr.001_Kontoauszug` mit SHA-256 `93fb50399d6c…` an zwei Pfaden. Daneben existieren
wirtschaftlich gleiche Kontoauszüge mit unterschiedlicher PDF-Metadatenstruktur; ihre stabilen
Buchungs-IDs verhindern doppelte wirtschaftliche Zeilen.

## 3. Inventar und Ursache der ursprünglichen 24 Fehler

| Gruppe | Anzahl | Ursache in der Baseline | P2-Behandlung |
|---|---:|---|---|
| Jahressteuerbescheinigungen 2016-2025 | 13 | Renault erkannt, aber keine Buchungstabelle | explizit klassifiziert und archiviert |
| Festgeld-Zinsmitteilungen | 7 | Renault erkannt, aber kein formaler Kontoauszug | explizit klassifiziert und archiviert |
| Freistellungsauftrag | 1 | Renault erkannt, aber keine Buchungstabelle | archiviert, keine FSA-Nutzung erzeugt |
| Informationsschreiben | 2 | Markenkennung ohne Buchungstabelle | Archivdokument |
| Online-Umsatzübersicht | 1 | neues, umgekehrt extrahiertes Kartenlayout ohne Tabellenkopf | Archiv-only wegen Überlappung und fehlendem Ersatzzeitraum |

Alle 24 Belege besitzen unterschiedliche SHA-256-Inhalte. Sämtliche ersten Seiten wurden visuell
gegen das gerenderte Original geprüft. Poppler war lokal nicht vorhanden; für die Sichtprüfung kam
PDFium zum Einsatz. Die produktive Textextraktion und der Parserpfad blieben unverändert.

## 4. Fachliche Bewertung der Dokumentgruppen

### Kontoauszüge

Nur eine echte Kontoauszug-Titelzeile aktiviert den Buchungsparser. Hinweise im Kleingedruckten,
die lediglich das Wort „Kontoauszug“ erwähnen, reichen nicht mehr aus. Alle bisherigen formalen
Auszüge bleiben im bewährten Tabellenparser und behalten Anzahl, Betrag, Vorzeichen und externe ID.

### Zinsmitteilungen und Steuern

Die sieben Zinsmitteilungen wiederholen nachweislich Bruttozins, Kapitalertragsteuer,
Solidaritätszuschlag und Endsaldo der zugehörigen Festgeld-Kontoauszüge. Eine erneute Buchung würde
Zins und Steuer doppelt zählen. Deshalb werden diese Belege strukturiert erkannt und nur archiviert.

Jahressteuerbescheinigungen sind Jahresaggregate. Sie erzeugen weder Cashflows noch zusätzliche
Steuerereignisse. Dokumentierte FSA-Werte werden nicht als einzelne FSA-Nutzung interpretiert.
Das Datenmodell besitzt in diesem P2-Scope keinen separaten, cash-neutralen Speicher für sämtliche
Jahresbescheinigungsfelder; eine Schemaänderung erfolgte nicht.

### Online-Umsatzübersicht

Der Beleg vom 05.10.2026 enthält 90 Tage rückwärts sortierte Umsätze und überlappt die formalen
Monatsauszüge Juli bis September. Er weist Start- und Endsaldo, aber keinen eindeutig belegten
vollständigen Ersatzzeitraum für den Renault-Ersetzungsimport aus. Eine automatische Übernahme
würde bestehende Zins-, Steuer- und Überweisungsbuchungen duplizieren. Der Beleg wird daher bewusst
als `Renault Umsatzübersicht` archiviert und nicht als vollständig geparster Kontoauszug gewertet.

## 5. Buchungsarten und Vorzeichen

Nach Deduplizierung über Konto und externe Buchungs-ID enthalten die Renault-Kontoauszüge:

| Buchungsart | Eindeutige Zeilen | Semantik |
|---|---:|---|
| Sonstige Bankbuchung | 152 | belegtes Vorzeichen |
| Zinsgutschrift/-korrektur | 144 | Haben positiv, Storno entsprechend umgekehrt |
| Steuerabzug | 105 | Soll negativ |
| Einzahlung | 51 | positiv |
| Auszahlung | 11 | negativ |
| Steuererstattung | 2 | positiv |
| **Gesamt** | **465** | fünf getrennte Renault-Konten |

Der Ordner enthält zusätzlich einen fremden generischen Kontoauszug mit sieben Zeilen und einen
Baader-Dividendenbeleg. Diese acht Buchungen sind nicht Renault zugeordnet und werden in den
Renault-Summen nicht mitgerechnet.

## 6. Salden- und Kontinuitätsprüfung

- 159 physische Auszüge enthalten vollständige `AccountStatement`-Salden.
- Nach Gruppierung wirtschaftlich gleicher Auszüge bleiben 144 eindeutige Auszugszeiträume.
- Fünf Renault-IBANs werden getrennt geführt.
- Jeder einzelne Auszug erfüllt `Anfangssaldo + Buchungen = Endsaldo` centgenau; andernfalls hätte
  der Renault-Parser den Beleg abgewiesen.
- 139 zeitlich anschließende Saldenpaare wurden verglichen.
- Ergebnis: **0 Saldenabweichungen**.
- Vier Kontoeröffnungs-/Erstauszüge besitzen keinen vollständigen Anfangs- und Endsaldo und wurden
  deshalb nicht künstlich in die Kontinuitätsrechnung aufgenommen.

## 7. Parseränderungen

Geändert wurde ausschließlich `pdf_plugins/renault_kontoauszug.py`:

- handler-spezifische Erkennung für Zinsmitteilung, Jahressteuerbescheinigung,
  Freistellungsauftrag und Umsatzübersicht;
- strengere Erkennung einer formalen Kontoauszug-Titelzeile;
- Renault-spezifische Archiv-only-Persistenz mit Dokumenttyp, Bank, Datum und Referenz;
- explizite Warnung, warum keine wirtschaftliche Buchung erzeugt wurde.

Globale Buchungs-, Steuer-, FSA- und Parserregeln wurden nicht geändert.

## 8. Vorher-/Nachher-Audit

| Kennzahl | Baseline V2 | P2 nachher |
|---|---:|---:|
| Physische Dateien im Ordner | 200 | 200 |
| Eindeutige SHA-256 | 199 | 199 |
| Renault zugeordnete Pfade | 170 | 194, davon 31 Archiv-only |
| Formale Renault-Kontoauszüge | in 170 nicht sauber abgegrenzt | 163 |
| Parserfehler | 24 | 0 |
| Timeouts | nicht isoliert | 0 |
| Generische Fallbacks | 4 | 4 |
| Neue generische Fallbacks | 0 | 0 |
| Handler-Regressionen | 0 | 0 |
| Physische Transaktionszeilen | 537 | 537 |
| Pfade mit geänderter Transaktionsanzahl | - | 0 |
| Eindeutige Renault-Buchungszeilen | nicht ausgewiesen | 465 |

Der Audit wurde ohne Cache in separaten Prozessen mit 30 Sekunden Timeout je Datei ausgeführt.
Keine Datei benötigte OCR oder überschritt das Limit. Artefakte: `audit.json`, `files.csv`,
`findings.csv`, `transactions.csv` und `report.md` unter
`test_reports/pdf_parser_audit/renault_p2_after/`.

## 9. Normalisierte Buchungsdifferenzen

Die Baseline enthält keine vollständigen Buchungsdatensätze, sondern nur Zählwerte. Ein
feldweiser historischer Vorher-Dump kann daher nicht nachträglich erzeugt werden. Belastbar
vergleichbar sind die Transaktionsanzahlen je Pfad: **0 von 200 Pfaden änderten ihre Anzahl**;
Gesamtsumme vorher und nachher jeweils 537. Für den Nachher-Stand enthält `transactions.csv`
sämtliche normalisierten Datensätze. 473 Konto-/ID-Kombinationen sind über den gesamten Ordner
eindeutig, davon 465 Renault; keine ID trägt widersprüchliche Inhalte.

## 10. SQLite- und Dublettenprüfung

Auf `tmp/renault_p2.sqlite` wurden alle 200 PDFs in eine leere temporäre Datenbank importiert:

| Prüfung | Erster Import | Zweiter Import |
|---|---:|---:|
| Importstatus `imported` | 200 | 0 |
| Importstatus `duplicate` | 0 | 200 |
| gespeicherte Transaktionen | 473 | 473 |
| Steuerereignisse | 0 | 0 |

Damit bleiben Wiederholungsimport, gleiche SHA-Kopie und wirtschaftlich überlappende formale
Auszüge idempotent. Kontenübergreifende Isolation ist durch getrennte IBAN-Konten und die
Saldenketten belegt. Der Test nutzte keine produktive Datenbank.

## 11. Regressionstests

Neu hinzugefügt wurden synthetisch und ausdrücklich als solche erkennbare Tests für:

- Zinsmitteilung ohne Buchung;
- Jahressteuerbescheinigung ohne Buchung;
- Freistellungsauftrag ohne Änderung der FSA-Aggregation;
- überlappende Umsatzübersicht ohne Doppelbuchung;
- allgemeines Renault-Archivdokument;
- unveränderten formalen Kontoauszug mit Saldenabgleich.

Zusammen mit den bestehenden Renault-Tests sind reguläre und alte/neue Layouts, mehrzeilige
Buchungen, positive/negative Beträge, Zins, Steuer, Storno, Steuererstattung, Überlappung,
Mehrkontenfähigkeit, Wiederholungsimport, Saldenfortschreibung, Pflichtfelder und Persistenz
abgedeckt.

## 12. Qualitätssicherung

- `python -m compileall -q src/portman src/portfolio_v5 pdf_plugins`: PASS
- `python -m ruff check src/portman src/portfolio_v5 pdf_plugins --select F`: PASS
- Renault-/PDF-Zieltests: **43 passed**
- vollständige Testsuite: **1175 passed, 15 skipped, 5 subtests passed**
- zwei bestehende Qt-Deprecation-Warnungen in `tax_detail_view.py`; keine Renault-Regression
- vollständiger Renault-Audit: **200/200, 0 Fehler, 0 Timeouts, 0 Regressionen**

## 13. Verbleibende Hinweise und Risiken

- Archiv-only ist bewusst kein vollständig strukturierter Steuerimport.
- Die Online-Umsatzübersicht bleibt wegen des nicht belegten Ersatzzeitraums ohne Buchung. Ihre
  Werte sind lesbar, aber ein automatischer Mischimport mit Monatsauszügen wäre nicht sicher.
- Drei Vertragsunterlagen bleiben beim bestehenden generischen Archivhandler; ein im Renault-
  Ordner abgelegter fremder Kontoauszug und zwei Baader-Dokumente bleiben korrekt außerhalb des
  Renault-Handlers.
- Originalnamen enthalten personenbezogene Angaben; die Auditdateien verbleiben im privaten
  Projektkontext und enthalten keine PDF-Inhalte.

## 14. Gesamtbewertung

**PASS MIT HINWEISEN.** Alle fachlich eindeutig lösbaren Renault-Dokumente werden klassifiziert,
alle formalen Kontoauszüge bleiben wirtschaftlich unverändert und saldenkonsistent. Die 24
ursprünglichen Fehler sind ohne zusätzliche oder doppelte Buchung behoben. Die einzige nicht
buchungswirksam übernommene Umsatzübersicht ist ausdrücklich als sicherheitsbedingter Archiv-only-
Fall dokumentiert.
