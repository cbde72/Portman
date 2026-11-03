# Portman PDF Lab – Code- und Architektur-Audit V1

**Auditdatum:** 2026-11-01  
**Repository:** `cbde72/Portman`  
**Audierter Stand:** `feat/comdirect-document-reference` / `54a1fc3`  
**Basis:** `codex/transfers-corporate-actions-gui` / `9e52e4e`  
**PR 47:** offen, nicht gemergt  
**PR 46:** offen, nicht Bestandteil des auditierten Branches

## 1. Executive Summary

Portman PDF Lab ist als eigenständige Review- und Trainingsumgebung grundsätzlich
eine brauchbare Grundlage für Portman V10. Die Abhängigkeitsrichtung ist im
Wesentlichen richtig: `portman-parsers` kennt weder Qt noch PDF Lab, während PDF
Lab die öffentliche Parser-API konsumiert. Immutable DTOs, Evidence, versionierte
Parserläufe, SQLite-Historie und getrennte Review-/Trainingsartefakte sind gute
Bausteine für eine spätere V10-Integration.

Der aktuelle Stand ist jedoch **noch nicht fachlich produktionsreif für einen
automatisierten dokumentübergreifenden Buchungsabgleich**:

1. PR 47 ist im auditierten Branch enthalten, aber nicht grün: **2 von 103
   Parser-Unit-Tests schlagen fehl**. Die Referenznummern-Regex erwartet einen
   Doppelpunkt, während die Testform `Referenz-Nr. <Wert>` verwendet.
2. Bankreferenzen werden nur im comdirect-Hauptparser und nur in dessen
   Transaktionspfad erfasst. PP-comdirect, Finanzreport und andere Banken sind
   nicht gleichwertig abgedeckt.
3. Eventbezogene Evidence-IDs werden im DTO nicht systematisch gegen die
   Evidence-Tabelle validiert.
4. Wertpapieridentität ist in `FinancialEvent`, `SecurityTrade` und
   Depot-/Positionsstrukturen dupliziert, aber nicht durch einen gemeinsamen
   Status- und Prioritätsvertrag verbunden.
5. Die Registry listet 42 Handler, davon sind 22 tatsächlich implementiert.
   Die übrigen 20 sind bewusst Metadata-only.
6. PDFium ist ein qualitätsabhängiger Fallback, keine allgemeine
   koordinatenbasierte Layoutschicht.
7. Die Unit-Testzahl belegt lokale Verträge, aber keine vollständige Abdeckung
   realer Bank-PDF-Layouts und keine sichere PDF → DTO → SQLite → GUI-Kette.

**Gesamturteil:** Geeignete technische Basis mit klarer modularer Richtung,
aber vor V10-Freigabe müssen Provenienzvalidierung, Referenzdatenmodell,
Layoutvarianten, Parserstatus und dokumentübergreifender Abgleich stabilisiert
werden.

### Zentrale Befunde

| ID | Priorität | Einstufung | Kurzbefund |
|---|---:|---|---|
| A-001 | P1 | Nachgewiesener Fehler | PR 47 erkennt die getestete Referenznummer ohne Doppelpunkt nicht. |
| A-002 | P1 | Nachgewiesenes Risiko | Event-Evidence-IDs werden nicht auf vorhandene Evidence geprüft. |
| A-003 | P1 | Architektur-/Fachrisiko | Bankreferenzen sind nicht parser- und dokumentübergreifend modelliert. |
| A-004 | P1 | Nachgewiesenes Risiko | 20 von 42 Handlern sind nur Metadata-only. |
| A-005 | P1 | Architekturverbesserung | Wertpapieridentität ist in mehreren DTOs dupliziert. |
| A-006 | P1 | Nachgewiesenes Risiko | Layout-/Textfallback kann formal plausible, fachlich falsche Spalten akzeptieren. |
| A-007 | P2 | Nachgewiesenes Risiko | Referenzvergleich und stabile Listenpfade verwenden unterschiedliche Pfadsemantik. |
| A-008 | P2 | Nachgewiesene Lücke | Keine reale/anonymisierte Golden-PDF-Matrix für die zentralen comdirect-Layouts. |
| A-009 | P2 | Nachgewiesenes Risiko | Batchanalyse startet viele Worker; SQLite-Schreibzugriffe werden serialisiert. |
| A-010 | P2 | Wartbarkeitsauffälligkeit | Große Funktionen vermischen Fach-, Persistenz- und Darstellungslogik. |
| A-011 | P2 | Architekturverbesserung | DTO-Erweiterungen ändern JSON, ohne die Resultat-Schema-Version sichtbar anzuheben. |
| A-012 | P3 | Wartbarkeitsauffälligkeit | Wildcard-Imports und stark komprimierter Parsercode erschweren Reviews. |

## 2. Aktueller Architekturstand

Der tatsächliche Hauptpfad ist:

```text
PDF -> pypdf -> preparation/normalization -> optional PDFium fallback
    -> PdfDocument/PdfPage -> PluginRegistry -> ParserPlugin
    -> ParsedDocument -> shared validation -> JSON report
    -> PDF-Lab ReferenceRepository/SQLite -> Qt result, review and training UI
```

Die Trennung aus `docs/architecture/pdf-lab-phase-5.md` ist im Kern umgesetzt.
`portman-parsers` hat keine Abhängigkeit zu Qt, PDF Lab, Portman V09/V10 oder
SQLite. PDF Lab hängt von der öffentlichen Parser-API, PySide6 und SQLite ab.

Die Schichtengrenzen werden allerdings durch Orchestratoren ausgedehnt:

- `application/pdf_analysis.py` verbindet Extraktion, Erkennung, Parsing,
  Validierung, Rules, Parservergleich, Projektionen und Reportaufbau.
- `ui/main_window.py` verbindet GUI-Aufbau, Batchworker, Katalog, Review,
  Training, Navigation und Persistenz.
- `result_view.py`, `field_analysis.py` und `pdf_markings.py` besitzen eigene
  Flattening-, Status-, Katalog- und Evidence-Projektionen.
- `registry.default_registry()` enthält konkrete Plugin-Factories und ist damit
  deterministisch, aber nicht ohne Codeänderung extern erweiterbar.

**V10-Bewertung:** Die Parserabgrenzung ist übernehmbar. Eine formale,
versionierte V10-Schnittstelle für Resultate, Layout und Abgleich fehlt noch.

## 3. Übersicht tatsächlich implementierter Parser

Die Allowlist (`portman-parsers/src/portman_parsers/registry/allowlist.py`)
enthält 42 Handler, davon 22 mit `implemented=True`:

| Plugin | Handler | Status |
|---|---:|---|
| `user.comdirect-ertraege` | 9 | implementiert |
| `comdirect.finanzreport` | 1 | implementiert |
| `portfolio-performance.comdirect` | 9 | implementiert |
| `fnz.finvesto` | 2 | implementiert |
| `user.bank-of-scotland-kontoauszug` | 1 | implementiert |
| `baader.pdf` | 6 | nur registriert/Metadata-only |
| `user.ing-wertpapiere` | 6 | nur registriert/Metadata-only |
| `user.deka-quartalsbericht` | 1 | nur registriert/Metadata-only |
| `renault.kontoauszug` | 6 | nur registriert/Metadata-only |
| `generic.kontoauszug` | 1 | nur registriert/Metadata-only |

`MetadataOnlyPlugin.parse()` wirft absichtlich `HandlerNotImplementedError`.
Das ist technisch sauber, sollte aber in GUI und CLI als „vorbereitet, nicht
implementiert“ erscheinen und nicht wie ein produktiver Parser auswählbar sein.

## 4. Codequalität und Wartbarkeit

### Größere Verantwortungsballungen

| Fundstelle | Beobachtung | Empfehlung |
|---|---|---|
| `ui/main_window.py:113-227` | `_build_ui()` baut fast die gesamte Oberfläche und verdrahtet Zustände. | Panel-/Tab-Factories und dünner UI-Controller. |
| `ui/main_window.py:286-314` | Batch, Worker-Lifecycle, Fortschritt und Dokumentzustand sind gekoppelt. | Batchservice und bounded Jobqueue trennen. |
| `ui/field_analysis.py:196-324` | Katalogdeckung, Status, Training und Rule-Vergleich in einer Funktion. | Reine Match-/Status-/Training-Projektionen. |
| `ui/pdf_markings.py:479-610` | Markings, Evidence, Rules, Conflicts und Fallbacktext gemeinsam. | Gemeinsames EvidenceProjection-Modell. |
| `storage/repository.py:72-200` | Große sequenzielle Migrationseinheit. | Einzelne versionierte Migrationen und Recoverytests. |
| `plugins/bank_of_scotland.py:61-194` | Erkennung, Normalisierung, DTO und Issues in einer Parsefunktion. | Parserhilfen und fachliche Teilparser. |
| `validation/taxes.py:54-178` | Viele unabhängige Steuerregeln in einer Funktion. | Regelgruppen und explizite Invarianten. |

Der comdirect-Parser verwendet `from portman_parsers.api import *` und viele
komprimierte Einzeiler. Das erschwert IDE-/Lint-Unterstützung, API-Migration
und sichere Code-Reviews. Es ist ein P2-Wartbarkeitsrisiko.

### Redundanz und Seiteneffekte

- Mehrere UI-Pfade flatten und klassifizieren Resultate mit leicht anderer
  Statussemantik.
- Haupt- und PP-comdirect implementieren ähnliche Tabellen-/Cash-Regeln separat.
- Name/WKN/ISIN stehen im Event, Trade und Positionsmodell, ohne verbindliche
  Prioritätsregel.
- `MissingValue` ist ein `StrEnum`; damit ist ein fehlender Wert zugleich ein
  `str`, was Typprüfungen und UI-Negativtests fehleranfällig macht.
- `MainWindow.__init__()` importiert den YAML-Feldkatalog und schreibt beim
  Start eine zentrale Beschreibung/Auditdatei unter AppLocalData. Das ist ein
  unerwarteter Dateiseiteneffekt und hängt von einem repositoryrelativen Pfad ab.
- `analyse_pdf()` gibt bei Fehlern ein anderes Dict-Shape als bei Erfolg zurück.

## 5. PDF-Extraktion und Layoutanalyse

`extract_pdf()` liest Seiten mit pypdf. `prepare_pdf()` normalisiert Unicode,
Zeilenumbrüche und bekannte Artefakte. Nur bei `SUSPICIOUS` oder `UNRELIABLE`
wird PDFium versucht. PDFium liefert Character Boxes; `_layout_from_spans()`
gruppiert sie über eine feste y-Toleranz und setzt bei x-Abständen über acht
Einheiten Leerzeichen.

### Nachgewiesene Grenzen

1. PDFium wird nicht genutzt, wenn pypdf formal `OK` ist, aber fachlich falsche
   Spalten liefert.
2. Es gibt Zeichenboxen, aber kein öffentliches Wort-/Zeilen-/Spaltenmodell.
3. Der Fallback ist seitenweit, nicht feld- oder kandidatenbezogen.
4. Leere Textlayer führen nur zu `OCR_REQUIRED`; ein OCR-Workflow fehlt.
5. `Evidence` enthält Seite und Excerpt, aber keine Quads/Bounding Boxes.
6. Rotation, Seitengrößen, mehrseitige Tabellen und wiederholte Header sind
   nicht als expliziter Layoutvertrag modelliert.

Für die vorhandenen Textfälle ist das Verfahren brauchbar. Zuverlässigkeit für
alle Layoutvarianten desselben Bankdokuments ist nicht belegt. Eine gemeinsame
koordinatenbasierte Layoutanalyse ist langfristig sinnvoller als weitere
bankspezifische Regex-Regeln; sie sollte als immutable Layoutartefakt neben
`PdfPage` eingeführt werden.

## 6. Parser- und Datenmodellprüfung

### comdirect-Dividendengutschriften

Die Basis enthält die Identitätserweiterung aus Commit `9e52e4e`. Die
weitergehende Verbesserung aus PR 46 ist offen und **nicht** Bestandteil dieses
Audits. Ein echtes SAP-PDF wurde lokal nicht gefunden; die Aussage beruht auf
synthetischen Texttests und dem beschriebenen Tabellenlayout.

Die fachlich richtige Modellierung ist:

```text
FinancialEvent.security_name = zusammengesetzter Wertpapiername
FinancialEvent.security_wkn  = WKN
FinancialEvent.security_isin = ISIN
CashMovement                 = Zahlbetrag
SecurityMovement             = nicht vorhanden bei Dividendengutschrift
```

Die Eventfelder machen den Sonderfall abbildbar. Die vollständige Kette ist
aber nicht abgesichert, weil Feldkataloge zwischen `events[].security_*` und
`events[].trades[].*` unterscheiden, Event-Evidence nicht global validiert wird
und PR 46 nicht als Basisschnittstelle gelten darf.

### DTO- und Provenienzrisiken

`FinancialEvent`, `SecurityTrade`, `DepotPosition` und `DepotSnapshot` besitzen
jeweils Wertpapierinformationen. Das ist fachlich nur dann sicher, wenn Herkunft,
Status und Priorität explizit sind. Offen sind insbesondere Konflikte zwischen
Event- und Trade-Identität sowie die Serialisierung von `MISSING`, `INVALID`,
`AMBIGUOUS` und `RECOGNIZED`.

`ParsedDocument.__post_init__()` prüft Evidence für Masterdaten-`FieldValue`s.
Für `FinancialEvent.evidence_ids`, `security_identity_evidence_ids` und
`bank_reference_evidence_ids` gibt es keine entsprechende Prüfung. Das ist ein
P1-Risiko für Nachvollziehbarkeit.

Die neuen Eventfelder ändern automatisch `to_json_compatible()` und damit
Persistenz-/Export-JSON, während `ParsedDocument.schema_version` weiter
`1.5.0` lautet. Ein expliziter Schema-Bump oder Adapter fehlt.

## 7. Datenintegrität und Persistenz

### Stärken

- SQLite-Schema versioniert (`SCHEMA_VERSION = 3`).
- Foreign Keys, WAL und `BEGIN IMMEDIATE` aktiv.
- Dokumentdeduplizierung über eindeutigen SHA-256.
- Parserläufe unveränderlich mit Parser-/Resultatversion und Laufzeit.
- Referenzwerte, History, Annotationen, Golden Tests und Rule-Aktivierungen
  getrennt gespeichert.
- PDFbytes bleiben außerhalb der Datenbank.

### Risiken

1. Jeder erneute identische Lauf erzeugt einen neuen `parser_runs`-Eintrag;
   Historie ist korrekt, ein Folgeimport kann ihn aber als Doppelimport lesen.
2. Absolute lokale Pfade werden in Metadaten/Exporten gespeichert und sind weder
   portabel noch datensparsam.
3. `_flatten()` vergleicht ID-stabile Listenpfade, während Katalog/UI numerische
   Indizes verwenden. Referenzvergleiche können dadurch Pfade verfehlen.
4. Migrationen haben keinen dokumentierten Backup-/Downgradepfad.
5. Viele parallele Worker konkurrieren auf derselben SQLite-Datei; das ist bei
   Windows-Dateisperren und `BEGIN IMMEDIATE` ein Reproduzierbarkeitsrisiko.
6. Die Unveränderlichkeit bestätigter Referenzwerte ist überwiegend Service-
   und GUI-Konvention, kein Datenbankconstraint.

## 8. Bankreferenzen und Buchungsabgleich

### PR 47 – aktueller Befund

PR 47 ergänzt `FinancialEvent.bank_reference` und
`bank_reference_evidence_ids` sowie eine comdirect-Regex. Die Änderung ist
offen und nicht gemergt. Die Tests sind im aktuellen Branch nicht grün:

```text
portman-parsers/tests/unit: 101 passed, 2 failed
```

Nachgewiesen:

- `BANK_REFERENCE` verlangt nach `Nr.` zwingend `:`; die Testform
  `Referenz-Nr. <Wert>` enthält keinen Doppelpunkt.
- `MissingValue.UNKNOWN` ist ein `StrEnum` und damit zugleich `str`; der
  Negativtest prüft daher eine falsche Typannahme.

PR 47 erfasst außerdem nur `ComdirectPlugin.transaction()`. PP-comdirect,
Finanzreport und andere Banken erzeugen keinen gleichwertigen Referenzvertrag.

### Fachliches Abgleichskonzept

Diese Identitäten müssen getrennt bleiben:

| Identität | Bedeutung |
|---|---|
| `document_id` | unveränderliches Parserdokument/Hash |
| `event_id` | wirtschaftlicher Vorgang im Parserresultat |
| `bank_reference` | originale Ausstellerreferenz, nur im Bankkontext eindeutig |
| `booking_id` | späteres Kontobuchungsobjekt |
| `evidence_id` | konkrete PDF-Fundstelle |
| `parser_run_id` | technische Ausführung |

Ein späterer Kandidatenschlüssel sollte Bank, normalisierte Referenz,
Dokumenttyp, Konto-/Depotkontext, Datumsfenster, Währung und Betrag kombinieren.
Er darf nie nur aus Betrag, ISIN oder Referenztext bestehen. Kandidaten müssen
Reviewentscheidungen und Evidence besitzen. Automatische Buchung darf erst nach
Idempotenz- und Stornoregeln erfolgen.

`possible_duplicate_events()` berücksichtigt derzeit weder `document_id` noch
`bank_reference`; dadurch sind sowohl falsche Duplikate als auch unzureichende
Unterscheidung gleich hoher Buchungen möglich.

## 9. GUI und Benutzerführung

Positiv sind die getrennten Schnell-/Expertenmodi, Evidence-Excerpt, PDF-
Markierungen, Feldanalyse, JSON-Ansicht, Review/Training und Worker außerhalb
des Qt-Eventloops.

Risiken:

- `MainWindow` umfasst rund 980 Zeilen und orchestriert UI, Analyse, Training,
  Katalog und Persistenz.
- Der Batchdialog startet alle Dateien sofort; der Threadpool begrenzt Threads,
  aber die SQLite-Schreibvorgänge konkurrieren.
- `flatten_result()` und Katalogprojektionen haben unterschiedliche Statusregeln.
- Textbasierte Markierungen ohne Quads können bei gleichen Ausschnitten falsch
  oder mehrdeutig werden.
- `default=str` in der JSON-Ansicht ist Anzeige-, kein stabiler Exportvertrag.
- Metadata-only-Handler sollten in der GUI nicht wie verfügbare Parser wirken.

## 10. Performancebewertung

Gemessen am Audit-Arbeitsplatz mit einem kleinen synthetischen PDF aus
`synthetic_pdf.py`, zehn Wiederholungen, ohne OCR/PDFium/SQLite:

| Vorgang | Median | Minimum | Maximum |
|---|---:|---:|---:|
| `extract_pdf()` | 2,73 ms | 2,35 ms | 7,69 ms |
| `analyse_pdf()` | 5,36 ms | 4,39 ms | 17,89 ms |
| `analyse_directory()` 1 Dokument | 6,00 ms | – | – |
| `analyse_directory()` 10 Dokumente | 15,01 ms | – | – |
| `analyse_directory()` 100 Dokumente | 93,61 ms | – | – |

Die Werte sind gemessen, aber nicht repräsentativ für reale mehrseitige PDFs,
PDFium, OCR, GUI und DB-Locks. `analyse_directory()` liest zum Hashen und
`extract_pdf()` nochmals; das ist ein nachgewiesener doppelter Lesepfad. Der
Parservergleich kopiert/analysiert zusätzliche Ergebnisse.

Eine lineare Abschätzung aus der 100-Dokument-Messung liegt bei ca. 0,9 s für
1.000 und ca. 9 s für 10.000 kleine synthetische PDFs. Das sind ausdrücklich
Abschätzungen; reale Layout-/OCR-/DB-Kosten können deutlich höher liegen.

## 11. Testqualität und Testlücken

Ausgeführt:

```text
python -m pytest portman-parsers/tests/unit -q
101 passed, 2 failed

python -m pytest portman-pdf-lab/tests/unit -q
121 passed
```

Aktueller PR-47-Stand: **222 Tests gesammelt, 220 erfolgreich, 2 fehlgeschlagen**.
Die historische Baseline von 219 erfolgreichen Tests ist wegen zusätzlicher
Tests und offener PR-Änderungen nicht direkt vergleichbar.

Gut abgedeckt sind DTO-Grundverträge, viele Validierungen, Parser-Unitfälle,
SQLite-Transaktionen, Annotation-History, Rules sowie Qt-Offscreen-Zustände.

Wesentliche Lücken:

1. Keine freigegebenen/anonymisierten Golden-PDFs für reale comdirect-
   Dividendengutschriften und Layoutvarianten.
2. Keine vollständige PDF → Parser → `analyse_and_store()` → SQLite →
   Feldanalyse-Assertion für alle vier Identitäts-/Betragswerte.
3. Keine belastbaren Tests für Rotation, Seitengröße, mehrseitige Tabellen,
   wiederholte Header und identische Textausschnitte.
4. Keine Cross-document-Tests für Referenzen, Steuer-/Dividendenpaare,
   Storno und Doppelimporte.
5. Keine globale Evidence-Referenzprüfung.
6. Keine Windows-Lock-, Abbruch- und Recoverytests für Batchworker.
7. Keine JSON-Schema-Contracttests bei DTO-Erweiterungen.
8. Kein echter OCR-End-to-End-Test.

## 12. Priorisierte Befundliste

| ID | Priorität | Bereich | Fundstelle | Problem | Auswirkung | Empfehlung | Aufwand |
|---|---:|---|---|---|---|---|---|
| A-001 | P1 | Referenznummer | `plugins/comdirect.py:13,119-121` | Regex verlangt `:`. | Referenzverlust. | Labelvarianten tolerieren und testen. | S |
| A-002 | P1 | Evidence | `api/events.py:376-406` | Event-Evidence nicht referenziell geprüft. | Nicht belegbare Werte. | Zentrale Evidence-Invariante. | S-M |
| A-003 | P1 | Abgleich | PR 47 / `validation/references.py` | Kein parserübergreifender Referenzvertrag. | Falsche Paarbildung/Doppelbuchung. | Provenienz- und Kandidatenmodell. | M-L |
| A-004 | P1 | Parserumfang | `registry/allowlist.py:25-88` | 20 Handler nur Metadata-only. | Falsche Reifeerwartung. | Readiness in GUI/CLI ausweisen. | S |
| A-005 | P1 | DTO | `api/events.py`, `api/depots.py` | Identität dupliziert. | Widersprüchliche Anzeige. | Gemeinsames Identity-Value-Object. | M |
| A-006 | P1 | Layout | `extraction/preparation.py:230-267` | Fallback nur bei globalem Verdacht. | Plausible Fehlsegmentierung. | Layoutartefakt und Feldkandidaten. | L |
| A-007 | P2 | Vergleich | `storage/repository.py:27-43,265-282` | ID-Pfade vs. UI-Indizes. | Referenzvergleich verfehlt Felder. | Kanonische Pfade trennen. | M |
| A-008 | P2 | Tests | Parser-/Lab-Tests | Keine reale Golden-PDF-Matrix. | Layoutregressionen. | Anonymisierte Fixtures. | M |
| A-009 | P2 | Persistenz | `ui/main_window.py:286-304` | Worker konkurrieren auf SQLite. | Locks/Batchfehler. | Bounded Queue/DB-Writer. | M |
| A-010 | P2 | Wartbarkeit | `main_window.py`, `field_analysis.py`, `pdf_markings.py` | Große Mehrzweckfunktionen. | Hoher Regressionsaufwand. | Reine Services/Projektionen. | M-L |
| A-011 | P2 | API | `api/results.py`, `api/events.py` | JSON erweitert, Schema unverändert. | Unsichere V10-Consumer. | Schema-Version/Adapter. | M |
| A-012 | P3 | Stil | `plugins/comdirect.py:5` | Wildcard-/komprimierter Code. | Schlechtere Reviews. | Explizite Imports, Typisierung. | S-M |
| A-013 | P2 | Datenschutz | `extraction/pdf.py:51-64` | Absolute Pfade in Reports. | Lokale Informationen in Exporten. | Opaque/relative Source-Refs. | S |
| A-014 | P2 | Fehlervertrag | `application/pdf_analysis.py:38-99` | Fehler-Dict unterscheidet sich vom Erfolgsreport. | Sonderfalllogik in Aufrufern. | Einheitlicher `AnalysisOutcome`. | M |

## 13. Empfohlene Zielarchitektur

```text
Portman PDF Lab / V10 adapter
    |
    +-- Analysis orchestration / AnalysisOutcome
    +-- PDF extraction: pypdf, PDFium, optional OCR adapter
    +-- immutable LayoutArtifact: pages, words, lines, columns, quads, quality
    +-- bank parser plugins with capability/readiness metadata
    +-- versioned shared DTOs and JSON contract
    |      +-- SecurityIdentity
    |      +-- Evidence/Provenance invariants
    |      +-- Missing/Invalid/Ambiguous/Recognized status
    +-- domain validation and no-artificial-movement rules
    +-- review-only cross-document reconciliation candidates
    +-- versioned repository and migrations
    +-- thin PDF-Lab GUI projections
```

Übernehmbar sind Parsertrennung, immutable DTO-Grundidee, Evidence-Grundmodell,
deterministische Registry, SQLite-Transaktionskern und Workerprinzip. Vereinfachen
oder neu entwickeln sollte man Layoutvertrag, Identity-/Schemavertrag,
Evidenceprojektionen, GUI-Orchestrierung, Parser-Reifegrad und Reconciliation.

Nicht erforderlich sind ein großer ORM-/Regelframework, eine OCR-Pflicht, eine
V09-Kompatibilitätsschicht im Parserpaket oder automatische Buchung allein aus
PDF-Referenzen.

## 14. Maßnahmenplan

### Phase 0 – Merge-Gate

1. PR 47 korrigieren und grün machen; PR 46 separat bewerten.
2. Einen definierten Baseline-Commit und reproduzierbare Testkommandos festlegen.
3. Resultat-Schema und Evidence-Invarianten verbindlich machen.
4. Nicht implementierte Handler in GUI/CLI klar kennzeichnen.

### Phase 1 – Provenienz und Identität

1. Alle Event-/Child-Evidence-IDs validieren.
2. `SecurityIdentity` und Statuswerte definieren.
3. Bankreferenz als originales, kontextgebundenes Feld mit Evidence für alle
   relevanten Parserpfade modellieren.
4. JSON-Contracttests und rückwärtskompatible Adapter ergänzen.

### Phase 2 – Layout und Dokumente

1. Anonymisierte Golden-PDFs je Bank, Handler und Layoutvariante.
2. Koordinaten-/Wort-/Zeilenartefakt als Parservertrag.
3. pypdf/PDFium feldweise vergleichen.
4. Rotation, Mehrseitigkeit, wiederholte Header und fehlende Textlayer testen.

### Phase 3 – Persistenz und Review

1. Kanonische ID-Pfade und UI-Indexpfade trennen.
2. Bounded Batchqueue und kontrollierten DB-Writer einführen.
3. Windows-Lock-, Backup-, Migration- und Recoverytests ergänzen.
4. Source-Refs datensparsam und transportierbar machen.

### Phase 4 – Buchungsabgleich

1. Kandidatenmodell für Dividendengutschrift, Steuerhinweis, Kontoauszug,
   Abrechnung und Storno.
2. Deterministische Normalisierung und gewichtete Kandidaten ohne Buchung.
3. UI-Review und Auditspur für jede Linkentscheidung.
4. Erst danach idempotenten V10-Exportadapter entwickeln.

## 15. Offene Fragen und Annahmen

- Wird PR 46 vor PR 47 übernommen, oder werden beide gegen denselben Basisstand
  rebaset? Beide ändern comdirect/DTOs.
- Welches öffentliche JSON-Schema konsumiert Portman V10?
- Soll die originale Bankreferenz neben einer normalisierten Form erhalten bleiben?
- Sind anonymisierte/freigegebene reale comdirect-PDFs für Golden Tests verfügbar?
- Soll OCR extern vorverarbeiten oder erhält PDF Lab einen optionalen Adapter?
- Wie eindeutig ist eine Bankreferenz bei mehreren Konten/Depots und Dokumenten?
- Welche lokalen Pfade und Evidence-Excerpts dürfen exportiert werden?
- Wird Layout für einzelne Parser verpflichtend oder bleibt Textfallback zulässig?

## Abschließende Antworten

1. **V10-Eignung:** Ja als technische Basis und Reviewwerkzeug; noch nicht als
   fertige fachlich abgesicherte Importplattform.
2. **Unverändert übernehmen:** Parsertrennung, immutable DTO-Idee, Evidence-/
   Reviewgrundlagen, deterministische Registry und SQLite-Transaktionskern.
3. **Neu/vereinfacht:** Layoutvertrag, Identity-/Schemavertrag, Evidencevalidierung,
   GUI-Projektionen, Parser-Reifegrad und Reconciliation.
4. **Größtes fachliches Risiko:** Werte ohne strikt geprüfte Provenienz oder mit
   widersprüchlicher Identität in einen Buchungsabgleich zu geben.
5. **Größte Komplexitätsreduktion:** `MainWindow`, Feldanalyse/Markierungen und
   doppelte Flattening-/Statuslogik in reine Services/Projektionen aufteilen.
6. **Performance:** Doppeltes Dateilesen vermeiden, Parservergleich cachen,
   Layout/Evidence wiederverwenden und DB-Schreiben zentral serialisieren.
7. **PDF-Zuverlässigkeit:** Für geprüfte Textfälle gut; für unbekannte Layouts,
   Rotation, OCR und koordinatenabhängige Fälle nicht ausreichend belegt.
8. **Abgleichvoraussetzungen:** Referenzvertrag, Kontext, Evidence, kanonische
   IDs, Kandidaten-/Reviewmodell, Storno- und Idempotenzregeln sowie Golden-PDFs.
9. **Fünf Sofortmaßnahmen:** PR 47 grün machen; Evidence global validieren;
   Resultatschema versionieren; reale Golden-PDFs ergänzen; Parser-Reifegrad in
   der GUI sichtbar und nicht implementierte Handler nicht auswählbar machen.

## Auditgrenzen

Es wurden keine produktiven Dateien, Datenbanken oder Referenzdaten verändert.
Der Auditlauf verwendete nur lesende Repository-/GitHub-Abfragen, Tests und eine
isolierte synthetische Performance-Messung in einem freigegebenen Temp-Verzeichnis.
Ein echtes SAP-PDF lag nicht im Repository; Aussagen dazu sind aus Code,
vorhandenen Tests und dem beschriebenen Layout abgeleitet.
