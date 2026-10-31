# Portman PDF Lab – Phase 7 Parsertraining Implementierungsbericht

**Datum:** 31.10.2026  
**Pakete:** `portman-parsers 0.6.0`, `portman-pdf-lab 0.6.0`  
**SQLite-Schema:** 3

## Ergebnis

PDF Lab besitzt einen zehnten Reiter **Parsertraining**. Die bisherigen neun
Reiter und beide unabhängigen comdirect-Parser bleiben erhalten. Training,
Annotation, Golden-Daten, Vorschläge und freigegebene Profile sind lokale
PDF-Lab-Funktionen; kein Parserquellcode und kein Original-PDF wird verändert.

Der Reiter besteht aus vier Bereichen:

1. Dokumentliste mit Bank, Datei, Typ, Parser, Handler, Layout, Review-,
   Trainingsstatus und Fehlerzahl sowie Bank-/Typ-/Statusfiltern;
2. PDF-/Evidence-Textbereich für Seiten- und Textauszugannotation;
3. kopierbare Feldtabelle mit Parser- und Referenzwert, Datentyp, Einheit,
   Seite, Evidence und Prüfstatus;
4. Trainingssteuerung für Bestätigung, Korrektur, Unknown, Textzuordnung,
   Golden, Vorschlag, Test, Freigabe, Verwerfen, Rollback und Qualität.

Mangels belastbarer Bounding Boxes arbeitet Phase 7 bewusst mit Seiten- und
Textauszügen. Es werden keine Koordinaten erfunden. Das Schema kann reale
Koordinaten später optional in `coordinates_json` aufnehmen.

## STANDARD, EXTENDED und COMPARE

Die bestehenden Parser und die normale Registry bleiben unverändert.
`STANDARD` ist der Default und führt ausschließlich Extraktion, bisherigen
Parser und bisherige Validierung aus. Es lädt kein Profil und liefert dasselbe
immutable `ParsedDocument` wie vor Phase 7.

`EXTENDED` führt zuerst denselben Standardpfad aus und lädt danach genau ein
atomar aktiviertes, freigegebenes und zur Parser-Version kompatibles Profil.
Regeln erzeugen `FieldDecision`-Overlays mit Standardwert, Regelwert,
effektivem Wert, Strategie, Konflikt und Provenienz. Das originale DTO wird
nicht überschrieben. `COMPARE` führt STANDARD und EXTENDED unabhängig aus und
gibt die Feldunterschiede aus, ohne produktive Parserdaten zu ändern.

Merge-Strategien:

- `FILL_MISSING` ergänzt nur fehlende Werte und ist Standard;
- `PROPOSE_REPLACEMENT` dokumentiert einen Konflikt, ändert aber nichts;
- `APPROVED_OVERRIDE` liefert einen effektiven Regelwert nur aus einem
  freigegebenen Profil, während Original- und Regelwert erhalten bleiben.

## Trennung der vier Ebenen

- Parserläufe bleiben unveränderliche Einträge in `parser_runs`.
- Menschlich bestätigte Werte liegen in Annotationen, Referenzwerten und
  Golden-Versionen.
- Vorschläge liegen deklarativ in `rule_candidates`.
- Tests und Freigaben erzeugen reproduzierbare `rule_versions`.

Eine Korrektur schreibt niemals in einen Parser. Neue Parserläufe überschreiben
weder Annotationen noch bestätigte Goldens.

## SQLite-Migration

Die nichtdestruktiven Migrationen von Schema 1 über 2 auf 3 ergänzen:

| Tabelle | Zweck |
|---|---|
| `annotations` | PDF-Text, Feldpfad, Referenzwert, Entscheidung, Review, Koordinaten |
| `annotation_history` | vollständige Annotationshistorie |
| `golden_tests` | versionierte Erwartungen und Freigabestatus |
| `golden_history` | Golden-Entscheidungen und Änderungen |
| `rule_candidates` | deklarative Vorschläge im Zustand DRAFT/TESTED/... |
| `rule_tests` | isolierte Kandidatenergebnisse |
| `rule_versions` | reproduzierbare Profile mit Vorgänger |
| `release_decisions` | explizite Freigaben/Ablehnungen |
| `training_history` | abgelehnte Vorschläge, Rollbacks und Trainingseingriffe |
| `profile_activations` | historisierte Aktivierung/Deaktivierung mit Hash |
| `comparison_results` | persistierbare STANDARD-/EXTENDED-Vergleiche |

Indizes unterstützen Dokument-/Feld-, Golden-, Kandidaten- und Testabfragen.
Der Repositoryexport enthält die neuen Tabellen, aber weiterhin keine PDF-Datei.

## Annotationsworkflow

Unterstützt werden Text, Betrag, Datum, Security-ID, Stückzahl, Kurs, Kurswert,
Gebühr, Steuer, Konto, Depot, Referenz, Tabellenzeile, Mehrzeiler, Missing und
Not-applicable. Jede Annotation speichert Dokument-ID/Hashbezug, Parser,
Handler, Seite, unveränderten Originaltext, Feldpfad, Referenzwert,
Benutzerentscheidung, Reviewstatus, Benutzer, Zeit und optionale Koordinaten.

Bestätigen und Korrigieren erzeugen fachlich geprüfte Annotationen. Unknown,
Missing und Not-applicable bleiben ausdrücklich unterscheidbar. Änderungen
erzeugen neue Historieneinträge.

## Golden-Test-Verwaltung

Ein Golden-Fall enthält Dokument, Bank, Handler, Layout, Parserversion,
versionierte Erwartungsdaten und Freigabestatus. Ein neuer Fall startet als
`DRAFT`; die GUI führt eine gesonderte explizite `APPROVED`-Entscheidung aus.
Korrekturen werden als neue Version mit `supersedes_id` gespeichert. Reimports
ändern ältere Goldens nicht.

## Sichere Regelvorschläge

Die lokale Trainingsengine erzeugt ausschließlich `LITERAL_FIELD`-Regeln aus einem
bestätigten Wert, wenn dieser im annotierten Text tatsächlich vorkommt. Ist
kein sicherer Vorschlag möglich, wird dies transparent protokolliert.

Es gibt:

- keine Python-Codegenerierung;
- kein `eval`, `exec` oder dynamisches Importieren;
- keine externen KI-/Netzwerkaufrufe;
- keine ungeprüfte Benutzer-Regex-Ausführung.

Muster sind längenbegrenzt. Verschachtelte Quantifizierer, wiederholte
Wildcards und Look-arounds werden abgelehnt. Nur bekannte deklarative
Regeltypen können ausgeführt werden.

Die anwendungsunabhängige Laufzeitengine liegt in `portman-parsers.rules`.
Sie validiert `LITERAL_FIELD` und `REGEX_FIELD`, bekannte Normalisierer,
Merge-Strategien, Schema-Version und Profilhash. Damit können exportierte
Profile ohne PDF Lab, GUI oder Trainings-SQLite verwendet werden.

## YAML-Profile und Speicherorte

Freigegebene Profile enthalten Schema-Version, Profil-ID, Bank, Parser-ID,
Dokumenttyp, Handler, Layout, Profil- und Parserversion, Status,
Freigabemetadaten, Regeln und SHA-256-Hash. `ProfileStore` speichert sie im
konfigurierbaren Benutzer-Anwendungsdatenverzeichnis, niemals in
`site-packages`. Aktivierungen liegen atomar in `activations.json` und werden
zusätzlich in SQLite historisiert. Export und Import verwenden validiertes
YAML. Unbekannte Felder, Regeltypen, Normalisierer, Schemata oder falsche
Hashes werden kontrolliert abgewiesen.

## Kandidatentest und wirtschaftliche Grenzen

Ein Kandidat läuft isoliert ausschließlich auf seinen bestätigten
Annotationen. Werte werden vor dem Vergleich fachlich normalisiert; `0,63`
und `0,630` gelten als numerisch gleich. Das Ergebnis enthält Treffer,
Regressionen und kritische Cashflowabweichungen.

Eine Freigabe wird verweigert, wenn:

- kein aktueller Test vorliegt;
- eine Regression besteht;
- eine Cashflowannotation abweicht.

Die Regelengine erzeugt selbst keine DTOs und kann daher keine Konten,
Cashflows, Trades, Depot-Snapshots, Steuern oder MiFID-Kosten hinzufügen. Damit
bleiben die wirtschaftlichen Phase-6-Schutzregeln am Parser-/Validatorrand
unverändert wirksam.

## Versionen, Freigabe und Rollback

Zustände sind `DRAFT`, `TESTED`, `APPROVED`, `REJECTED` und `SUPERSEDED`.
Freigabe erzeugt eine neue unveränderliche Profilversion. Der Vorgänger wird
`SUPERSEDED`. Rollback überschreibt nichts, sondern erzeugt eine neue
`APPROVED`-Version mit dem Regelinhalt des Vorgängers und protokolliert die
Aktion.

## Qualitätskennzahlen

Die GUI-Aktion **Qualität** zeigt Dokumente, bestätigte Annotationen,
freigegebene Goldens, Pflichtfeldtreffer, Cashflowfehler, fehlende Evidence und
Regressionen. Nicht belegbare Kennzahlen bleiben `null`; es werden keine
scheinbaren Genauigkeiten aus ungeprüften Parserwerten errechnet.

## Tests

Neue Testgruppen decken ab:

- Annotation, Korrektur, Missing, Mehrzeiler und Historie;
- Golden-Erstellung, explizite Freigabe, Versionierung und Reimport;
- sichere Vorschläge, uneindeutige Fälle und riskante Regex;
- isolierten Vorher-/Referenzvergleich;
- Cashflow-Regression und blockierte Freigabe;
- Profilfreigabe und Rollback;
- numerische Normalisierung;
- GUI-Reiter, vier Bereiche, Feld- und Evidencebindung;
- Architekturregression ohne V09/V10.
- bit-identischen STANDARD-Pfad ohne Profil;
- YAML-Roundtrip, Hashprüfung, falsches Schema und unbekannte Regeln;
- atomare Aktivierung, Deaktivierung und Neustartpersistenz;
- `FILL_MISSING`, konfliktbehaftete Ersetzung und freigegebenen Override;
- Profilexport/-import ohne PDF Lab;
- vollständigen synthetischen STANDARD→EXTENDED→COMPARE→Neustart→Export-Ablauf.

Vollständiger Abschlusslauf:

```text
```text
158 passed in 4.02s
```
```

Alle bisherigen Bank-of-Scotland-, FNZ-, comdirect-, PP-comdirect-, PDF-,
SQLite-, Export-, Vergleichs- und GUI-Tests bestehen weiter.

## Performance

Lokaler synthetischer SQLite-/Regelbenchmark mit 200 Fällen:

| Messung | Ergebnis |
|---|---:|
| 200 Annotationen plus Vorschläge | 3.930,546 ms |
| 200 isolierte Kandidatentests | 2.553,921 ms |
| Gesamt pro Fall | 32,422 ms |

Die bestehende PDF-Analyse und Batchverarbeitung laufen weiterhin im
`QThreadPool`. Kandidatentests sind selektiv auf betroffene Annotationen und
werden persistiert. Für sehr große Golden-Korpora sollte Phase 8 zusätzlich
einen eigenen Hintergrundworker und gruppierte SQLite-Transaktionen einsetzen.

## End-to-End-Abnahme und Isolation

Der synthetische End-to-End-Test erzeugt ein comdirect-PDF mit einem im
STANDARD-Modus fehlenden Layoutwert, aktiviert ein freigegebenes Profil und
prüft, dass EXTENDED den Wert ergänzt. Danach wird STANDARD erneut bitgleich
geprüft, der ProfileStore neu geöffnet, das Profil exportiert, in einen
unabhängigen Store importiert und dasselbe EXTENDED-Ergebnis reproduziert.

Beide Pakete wurden als Wheels gebaut und in eine frische virtuelle Umgebung
installiert. Die Abnahme bestätigte STANDARD, EXTENDED, COMPARE, persistente
YAML-Aktivierung nach erneutem Öffnen des ProfileStore und zehn offscreen
erzeugte GUI-Reiter. Die verbotenen Module `portfolio_v5`, `pdf_plugins` und
`portman.gui` waren nicht geladen. Ergebnis:

```text
ISOLATION_OK tabs=10 profiles=YAML standard=exact extended=active compare=ok forbidden_imports=none
```

PySide6 6.11.3 ließ sich auf dem aktuellen Windows/Python-System installieren,
scheiterte jedoch bereits beim Import von `QtWidgets` mit einem DLL-Ladefehler.
Mit PySide6 6.9.2 lief dieselbe Abnahme erfolgreich. Die Paketabhängigkeit ist
daher auf die getestete Reihe `PySide6>=6.8,<6.10` begrenzt.

GUI-Start: `python -m portman_pdf_lab gui`. Die VS-Code-Konfiguration
`Portman PDF Lab – GUI (F5)` verwendet den aktiv ausgewählten Interpreter.

## Bekannte Einschränkungen

- Keine koordinatengenaue Overlay-Markierung ohne Extraktions-Bounding-Boxes.
- Phase 7 erzeugt konservative Literalregeln, keine allgemeinen automatisch
  abgeleiteten Tabellen- oder Datumsregexe.
- Qualitätsquoten bleiben ohne bestätigte Goldens bewusst unbekannt.
- Produktive comdirect-Layoutfreigaben benötigen weiterhin ausdrücklich
  freigegebene reale Referenzdokumente.
- Große vollständige Regressionen sollten in Phase 8 über einen dedizierten
  GUI-Hintergrundjob mit Fortschritt/Abbruch laufen.

## Empfehlung für Phase 8

1. Bounding-Box-fähigen Extraktor und PDF-Overlay ergänzen.
2. Regeltypen für sichere Label-/Spalten-/Mehrzeilenanker erweitern.
3. Hintergrund-Regression über Golden-Korpora mit Fortschritt und Abbruch.
4. Layout-Clustering ausschließlich auf lokalen bestätigten Referenzen.
5. Signierte Export-/Importpakete für freigegebene Regelprofile.

V09/V10, bestehende Parseralgorithmen und Original-PDFs wurden nicht geändert.
Es wurden keine Commits, Pushes oder Merges ausgeführt.
