# Portman V10 – Aufgabenliste

Stand: 7. November 2026. Grundlage: Bauplan 3.2. Empfohlener Ablageort: `portman-v10/docs/TASKS.md`.

Status: [x] nachweislich vorbereitet/umgesetzt; [ ] offen. Das V10-Paket liegt auf Branch `codex/portman-v10-foundation` mit Draft-PR #69. Vorbereitung und Prototyp sind keine produktive Anwendung oder Migration. Parser-PR #68 und der darauf gestapelte Parserfix PR #70 sind gemergt.

## Arbeitsweise

Ein Auftrag umfasst eine Aufgabe oder einen eng zusammengehörigen Block. IDs bleiben stabil. Erst nach erfülltem Fertigkriterium abhaken; bei Bedarf Commit/PR und Prüfbefehl kurz daneben ergänzen. Kein zusätzliches Statusberichtssystem. Umsetzungsagent entwickelt und testet; unabhängiger Prüfer bei kritischen Änderungen ausdrücklich beauftragen und zunächst lesend einsetzen. Niemals zwei Agenten im selben Worktree schreiben lassen.

## Bereits vorbereitet

- [x] VOR-01 Architektur und Bauplan 3.1 dokumentiert.
- [x] VOR-02 Eigenständiges Vorbereitungspaket für Schritte 1–3 erstellt.
- [x] VOR-03 Erste Lese-DTOs, ReadApplication-Protocol und vier grundlegende Tests vorbereitet; damaliger Lauf bestanden.
- [x] VOR-04 AGENTS.md und CLAUDE.md mit gemeinsamen Regeln erstellt.
- [x] VOR-05 Öffentliche Parserverträge initial geprüft; widersprüchliche Reifegradangaben festgehalten. Vollständige API-Prüfung bleibt offen.

## P0 – Fundament: zuerst umsetzen

- [x] V10-01 **Branch und Arbeitsverzeichnis einrichten.** `codex/portman-v10-foundation` und eigenen Worktree aus geprüftem Ausgangsstand anlegen; bestehende Änderungen erhalten. Fertig: V10-Änderungen isoliert nachvollziehbar, V09 unverändert.
- [x] V10-02 **Vorbereitungspaket integrieren.** Eigenes Paket `portman-v10/`, Regeln, Bauplan und diese Aufgabenliste aufnehmen. Fertig: unabhängige Installation/Tests; keine V09-Abhängigkeit und keine Regelduplikate.
- [x] V10-03 **Zugriffsgrenzen festlegen.** Agent im V10-Verzeichnis starten; für echte Sperre Sandbox/Dateirechte konfigurieren. Fertig: tatsächlicher erlaubter Bereich geprüft; Branch/AGENTS.md nicht als technische Sperre ausgegeben. Geprüft: Dateisystemzugriff ist uneingeschränkt; es besteht keine technische Sandbox.
- [x] V10-04 **Parservertrag vollständig prüfen.** Installierbare Version, Lizenz, Entry-Points, DTO-Felder, ausführbare Handler und Referenztests prüfen. Fertig: konkrete unterstützte Anbindung dokumentiert, keine erfundene API. Nachweis: `docs/Parserpruefung.md`, Version 0.7.0 auf vollständigem lokalem Commit; 268 Parser-Tests bestanden.
- [x] V10-05 **Exakte Zahlendarstellung entscheiden.** Hybrid gewählt: belegte Werte als kanonische Dezimalstrings, berechnete Anteile als normalisierte rationale Werte; Summe exakt, `ROUND_HALF_UP` nur an der Anzeigegrenze. Variantenmessung und Tests dokumentiert; keine produktive Migration.
- [x] V10-06 **Vier Referenzvorgänge fachlich modellieren.** Bestandswirksame Positionen, nicht saldierende Betragsdetails, Datumsbedeutung, optionale/unbekannte Werte, Belege, Rücknahme und proportionale Teilüberträge belegter Lots dokumentiert; synthetische Golden-Daten und Tests ergänzt. Rationale Referenz bleibt unabhängig von V10-05-Rechenformat; Schema-Roundtrip in V10-09 geprüft, vollständige Rücknahmelogik bleibt V10-16.
- [x] V10-07 **Anwendungsschnittstelle vervollständigen.** Typisierte DTOs für Konten/Instrumente, Importjobs/Vorschau/Konflikte, Übernahme/Rücknahme, Suche/Details, Dokumente, gemeinsame Stichtagsübersicht und Steuerdaten; Revisionen, unbekannte Werte, Fehlercodes, request_id und stabile Cursor festgelegt. Keine Parser-/Qt-/SQL-Objekte.
- [x] V10-08 **FakeService und Vertragstests ergänzen.** Synthetischer zustandsbehafteter Fake; Erfolgs-, Validierungs-, Revisions-, Idempotenz- und Seitentests bestehen. Persistente Transaktions-/Wiederholungsgarantien ausdrücklich nicht nachgewiesen.
- [x] V10-09 **Erstes Schema und Migration erstellen.** Versionierte SQLite-Initialmigration mit Konten/Kennungen, Instrumenten, Vorgängen/Positionen, Lots, Komponenten, Dokumenten/Belegen, Importbeiträgen, Operationsschlüsseln, Bestandsindex, Steuer- und Festgeldstrukturen. CHECK/FK-Regeln, Migration-Checksumme, Atomarität und Referenz-Roundtrip geprüft; vollständiger Importservice nicht enthalten.
- [x] V10-10 **Architekturprüfung durchführen.** Domain/Application bleiben ohne GUI-/SQL-/Parser-/V09-Imports; unabhängige lesende Schema-/Zahlen-/Modulgrenzenprüfung durchgeführt und Befunde behoben bzw. Grenzen explizit dokumentiert. Persistente Replay-, Rücknahme- und gemeinsame Buchungs-/Indexgarantien bleiben offen.

**Meilenstein A:** Schnittstellen und exaktes Modell tragen die vier Referenzfälle. Danach können Oberfläche und Kern getrennt entwickelt werden.

**Status Meilenstein A:** V10-01 bis V10-10 sind nach ihren jeweiligen Implementierungs- und Automatikprüfkriterien abgeschlossen. Eine separate Nutzerabnahme ist nicht für jedes Fundamentpaket vorgesehen und bleibt als übergreifende Produktabnahme offen.

## P1 – Vollständiger Importweg und Rücknahme

- [x] V10-11 **Konten und Instrumente verwalten.** Persistente Stammdaten, kontextbezogene Kennungen, Revisionen und manuelle Startbestände; Migration 0003 ergänzt Kennungskontext und Eröffnungsherkunft. Die Indexpflege wurde mit V10-19/20 ergänzt; V10-11 allein enthielt sie noch nicht.
- [~] V10-12 **Dokumentablage und Parseradapter bauen – comdirect-Vorschau erweitert.** Alle 19 ausführbaren Registryeinträge in drei comdirect-Plugins werden erfasst und Parserausgaben über öffentliche DTOs/Validierung in Vorschauen übersetzt. Zusätzlich ist ein enger SQLite-Kernpfad für einzelne Finanzreport-`CASH_BOOKING`-Zeilen vorhanden: explizite `accept_unmatched`-Entscheidung ohne Bankreferenz, Prüfung der tatsächlichen Geldbewegung und zielgenauer Wiederimport über Zeilenherkunft. Gleichartige Positionen werden bei gleicher Vorgangsart als Ergänzung verknüpft; andere oder mehrdeutige Treffer blockieren die Neuanlage. Weboberfläche noch nicht angebunden; sieben Kontozuordnungen im konkreten Referenzreport, Layoutabdeckung und Nutzerabnahme offen. Steuer-/MiFID-/Snapshotinformationen bleiben nicht buchbar. Originalbytes bleiben hashadressiert; keine eigene Extraktion.
- [x] V10-13 **Importvorschau und begrenzte Jobs implementieren.** Dauerhafte Status/Progress, Mehrdatei-Teilfehler, kooperativer Abbruch, Neustartmarkierung und revisionierte Prüfentscheidungen. Exakte Geld-/Mengenwerte, Parser-Wertpapiername mit ISIN/WKN einmal je Vorgang und getrennte offene Stammdatenzuordnung sind sichtbar. ISIN-Zuordnung nutzt die Eventkennung, WKN ist eindeutiger Fallback; Mehrdeutigkeit/Widerspruch bleibt offen. Fehlende Angaben, Zuordnungen, Dubletten, Konflikte und handlungsrelevante Warnungen erscheinen als rote, fette Prüfpunkte. Übernahme bleibt V10-15.
- [~] V10-14 **Dubletten und Ergänzungen behandeln (teilweise).** Dateiidentität und sichere Bankreferenzhinweise werden angezeigt; Datum/Betrag allein führen nicht zusammen. Identische Käufe ohne sichere Referenz bleiben getrennt. Bei bestätigter Ergänzung werden exakt belegte Positionen mit der vorhandenen Position verknüpft; neue, dimensionsmäßig fehlende Positionen werden mit eigener Herkunft ergänzt und separat rücknehmbar. Abweichende Beträge und doppeldeutige Positionen brechen den Commit atomar mit `SOURCE_CONFLICT` ab. Offen: Konfliktvorschau vor der Nutzerbestätigung; Feldergänzungen über Originaltext, Bankreferenz, Gebühren/Steuern hinaus.
- [~] V10-15 **Atomare Übernahme (Kern vorhanden, Freigabe offen).** Additive Migration 0005; Preview-/Datenrevisionen, `request_id`, Commit, Importquellen und betroffene Indexreihen sind transaktional verdrahtet und mit synthetischen SQLite-Tests geprüft. Offen: echte unveränderte Parser-PDF→UI→Commit-Integration; Index-Unbekanntheits-/Vollständigkeitssemantik nochmals fachlich absichern; Nutzerabnahme. Rücknahme folgt V10-16.
- [x] V10-16 **Vollständige Import-Rücknahme (SQLite-Kern).** Persistente, revisionsgebundene Rücknahmepläne; einzeln/Auswahl/ausdrücklich alle; Vorschau von Beiträgen, Beleglinks, Instrumentherkunft, Bestandswirkung und Abhängigkeiten; atomare Rücknahme, Indexneubau und `request_id`-Replay. Gemeinsame Vorgänge/Belege und manuelle Eröffnungen bleiben erhalten. Auto-Instrumente werden nur anhand Importherkunft, Revision und verbleibender Nutzungen entfernt. Interne Belegkopien bleiben erhalten, solange Import-/Jobhistorie referenziert; externe PDFs werden nie gelöscht. Web-GUI bleibt ausgenommen.
- [~] V10-17 **Sonderbedeutungen prüfen – Parserfakten in Vorschau.** Synthetische Tests belegen getrennte Finanzreportzeilen samt Quellen sowie Steuerbasis/Freistellungsverbrauch ohne Geldbewegung; MiFID und Snapshots bleiben nicht buchbar. Der gemergte Parser liefert bei Investment-Ausschüttungen nun Wertpapiername, WKN und ISIN samt Belegquellen; V10 zeigt sie als saldenneutrale Details ohne Stückbewegung. Offen bleiben reale Referenzlayouts, fehlende Originalbelege und Nutzerprüfung.
- [~] V10-18 **Import-/Rücknahmeprüfung unabhängig durchführen.** Import-/Rollbackworkflow und SQLite-Speicher wurden unabhängig anhand der Anforderungen und Tests geprüft. Bestätigt: gemeinsame Vorgänge/Belegquellen, feldweise Rücknahme bei späterer manueller Änderung, initiale Gebühren-/Steuerkomponenten mit eigener Herkunft, Auswahl/Alle-Importe, veralteter Plan, Replay, Fehlerrollback, Auto-Instrument-Herkunft und parallele Übernahmen sind abgedeckt. Noch offen: Teiltransfers/Anschaffungstranchen haben keinen nachgewiesenen Herkunftspfad vom Erwerbsimport zum späteren Lot; die vorhandene Rücknahmeprüfung kann deshalb eine Abhängigkeit des Erwerbs nicht zuverlässig erkennen. V10-18 bleibt bis zur Provenienzkorrektur und einem Regressionstest offen.

**Meilenstein B:** Dokument → Vorschau → Übernahme → Wiederimport → Ergänzungsbeleg → Rücknahme liefert exakte erwartete Bestände.

## P1 – Stände und schnelle Navigation

- [x] V10-19 **Persistenten Bestandsindex implementieren.** SQLiteStore liefert `get_overview(as_of, account_ids)` aus der letzten Indexzeile je Konto und Währung/Instrument. Neue Stichtagswerte sind exakt, getrennt und revisionsgeprüft; automatische/uneröffnete Historie vor erster Eröffnung bleibt unbekannt. Backendtests bestanden; Nutzerprüfung der Webansicht ausstehend.
- [x] V10-20 **Inkrementelle Pflege und Speicherindex ergänzen.** Eröffnungen und allgemeine Ereignisschreibungen aktualisieren nur betroffene Reihen; rückdatierte Ereignisse bauen spätere Indexpunkte derselben Reihe neu auf. Import aktualisiert betroffene Reihen, Rücknahme rekonstruiert den Index atomar. Datenrevisionen, Wiederöffnen und Stichtagswerte sind getestet; Performanceprüfung ist V10-22, Nutzerprüfung bleibt offen.
- [ ] V10-21 **Zeitnavigation implementieren.** Tag/Woche/Monat/Jahr/freie Schritte, Datumsauswahl und Heute. Fertig: Tagesanker, Monatsenden/Schaltjahre und bewegungslose Tage korrekt; Datum und Daten bleiben konsistent.
- [ ] V10-22 **Geschwindigkeit messen.** Mindestens 100.000 Positionen, dokumentierte Hardware und Kontenzahl. Fertig: warmes lokales Blättern p95 <50 ms; Kaltstart und Indexpflege separat gemessen; langsame Fälle gezielt korrigiert. Kein unbelegtes Versprechen für Netzwerklatenz.

## P1 – Steuerinformationen

- [ ] V10-23 **Freistellungsaufträge verwalten.** Steuerjahr, Gültigkeit, Bank-/Inhaberbezug und Kontenzuordnung. Fertig: gemeinsame Aufträge einmal gezählt, Jahresänderungen historisch erhalten.
- [ ] V10-24 **Verbrauch und Rest anzeigen.** Nur belegte Werte aus unterstützten Parsern, Quellenstichtag und Vollständigkeit. Fertig: kumulierte/Einzelwerte nicht doppelt addiert, Minderungen/Konflikte/Unbekannt korrekt; Rücknahme aktualisiert den Stand, manueller Auftrag bleibt erhalten.

## P1 – Einfache Bedienung und Suche

- [~] V10-25 **Dünne lokale HTTP-Schnittstelle bauen – teilweise umgesetzt.** Nur Importupload, Jobstatus, Vorschau und Dokumentbytes sind über `ImportWorkflow` verfügbar; ausschließlich Loopback und opaque Dokument-ID. Konten-/Buchungsfälle der vollständigen `ApplicationService`-Abdeckung bleiben offen.
- [~] V10-26 **Web-Testoberfläche erstellen – teilweise umgesetzt.** Lokaler Browserablauf für PDF → Job → Vorschau → Original; exakte Werte, Details und offene Zuordnungen sichtbar. Vollständige Kontenübersicht, Buchungssuche, Übernahme, Tabellenkopie und Rücknahme bleiben offen.
- [ ] V10-27 **Buchungssuche implementieren.** Originaltext, Referenz, Dokument, Instrument und Konten; Datum/Betrag/Währung/Art/Status filtern. Fertig: deaktivierte Konten enthalten, exakte Betragsfilter, stabile Seiten; erste Seite bei 100.000 Positionen p95 <300 ms.
- [ ] V10-28 **Veraltete Antworten verhindern.** Fertig: schnelles Blättern zeigt letzte Auswahl, Revisionswechsel invalidiert Caches; optional kleine Nachbarabfrage ohne unbeschränkte Vorladung.

## P1 – Betrieb und Gesamtprüfung

- [ ] V10-29 **Sicherung und Wiederherstellung umsetzen.** Fertig: SQLite und Dokumente konsistent gesichert und wiederhergestellt; Migrationen abgesichert, Laufzeitdaten nicht im Git.
- [ ] V10-30 **Grundversion abnehmen.** Referenzablauf mit Geld, Wertpapieren, exakten Kryptomengen, Transfers, Steuerinfos, Dubletten, Rücknahme und Zeitnavigation prüfen. Fertig: relevante Tests bestanden; unabhängige kritische Prüfung erfolgt oder ausdrücklich ausstehend; Einschränkungen dokumentiert.

**Meilenstein C:** Überprüfbarer Importkern mit einfacher Bedienung, Suche, historischen Ständen, Freistellungsanzeige und Sicherung. Keine Charts oder Performanceanalyse nötig.

## P2 – Nach der Grundversion

- [ ] V10-31 Weitere ausgewählte Parser/Dokumenttypen nach einzeln belegter Qualität anbinden.
- [ ] V10-32 Endgültige Desktopoberfläche mit bestehendem Vertrag entwickeln, sofern weiterhin gewünscht.
- [ ] V10-33 Zentralen Betrieb und responsive Handyansicht ergänzen; Anmeldung und verschlüsselte Verbindung prüfen. SQLite bleibt beim zentralen Prozess.
- [ ] V10-34 Kurs-/FX-Versorgung und Bewertung mit Quellen-/Vollständigkeitsstatus ergänzen.
- [ ] V10-35 Performance und Charts erst nach geprüften Geldflüssen über kleine Adapter ergänzen.

## Nicht Teil des aktuellen Auftrags

V09-Komplettmigration, eigene Parser, automatische Übernahme unsicherer Kandidaten, Offline-Synchronisation mehrerer Datenbestände, Microservices, generische Pluginplattform und umfassende Steuerberechnung.

## Nächster Auftrag

V10-14/15/17 verbleiben teilweise offen: Konfliktvorschau und weitere Feldergänzungen, echte PDF→Vorschau→Übernahme-Integration mit geprüftem Indexverhalten sowie die reproduzierbare Investment-Ausschüttungs-Identitätslücke. V10-16 hat den SQLite-Kern und automatisierte Rücknahmeabdeckung; Nutzerprüfung und unabhängige Abschlussprüfung stehen noch aus. Fehlende Positionen können bei bestätigter Ergänzung mit eigener Feldherkunft angefügt und gezielt zurückgenommen werden. Positionskonflikte werden derzeit beim Commit erkannt und atomar abgebrochen; sie werden noch nicht vollständig vor der Bestätigung ausgewiesen.


## Ergänzende Aufgaben – Nutzerprüfung

- [ ] V10-36 Buchungsansicht durchgängig scrollbar machen; automatische Nachladung mit stabiler Sortierung und Revision. Fertig: komplette Girohistorie erreichbar, Filter/Suche unabhängig vom geladenen Ausschnitt; Kopieren aller Treffer berücksichtigt weitere Seiten.
- [ ] V10-37 Reproduzierbare Testumgebung erstellen. Fertig: separate Testdatenbank, vorhandenes Referenzbeispiel ohne GUI; später lokaler Webstarter mit Browseröffnung, sichtbarem Branch/Commit und Profil.
- [ ] V10-38 Übergabeprozess einführen. Fertig: je abgeschlossenem Schritt kurze Prüfanleitung mit Soll-Ergebnis; Nutzer kann denselben Stand starten und rückmelden.

Diese Aufgaben gehören zur Grundversion: V10-36 zusammen mit Suche/Oberfläche, V10-37 spätestens vor erster interaktiver Übergabe, V10-38 ab dem ersten abgeschlossenen Schritt.

### Prüfnachweis je abgeschlossener Aufgabe

| ID | Implementierung / Commit | Automatische Prüfung | Nutzerprüfung |
|---|---|---|---|
| Beispiel-ID | offen | offen | ausstehend |
| V10-01 | lokaler Branch `codex/portman-v10-foundation`, Basis `816034a`, separater Worktree | `git status`, `git worktree list` | ausstehend |
| V10-02 | Vorbereitungspaket im isolierten Worktree als lokaler Foundation-Commit integriert | eigene `.venv`, Editable-Installation und 4 Unittests bestanden | ausstehend |
| V10-03 | tatsächliche Grenze in README dokumentiert | uneingeschränkten Dateisystemzugriff festgestellt; keine Sandbox behauptet | ausstehend |
| V10-04 | Parser 0.7.0 auf gemergtem Main-Commit `074c3404d08e082c5f9b2a987ed302cfcf929f13`; PR #68 und #70 gemergt | 271 Parser-Tests; Remote-Wheel in V10 installiert und `direct_url.json` geprüft; V10-Importworkflow 52 Tests bestanden | ausstehend |
| V10-05 | `domain.rational.RationalAmount`, Decimal-/Rational-SQLite-Collations und `scripts/compare_number_variants.py`; keine Migration | 7 Zahlenrepräsentations-Tests plus 14 V10-06-Golden-Tests und 6 Vertragsprüfungen bestanden; 100.000 Zeilen je Variante gemessen | ausstehend |
| V10-06 | Referenzfälle, proportionale Lotaufteilung und synthetische Daten in `docs/Datenmodell.md` und `tests/reference_cases.py`; Rechenregel unabhängig geprüft, Speicherung auf V10-09/16 vertagt | 14 fachliche Golden-Tests; gesamte V10-Suite 27 bestanden, einschließlich exakter rationaler Kostenerhaltung ohne Float/Rundung | ausstehend |
| V10-07 | `application/contracts.py`, `docs/Schnittstelle.md` Version 0.2 | Transportneutrale Verträge für alle beauftragten Anwendungsfälle, Revisionen, unbekannt und Fehlercodes; 10 gezielte Vertragstests | ausstehend |
| V10-08 | `application/fake_service.py` mit synthetischen Beispielen | Vertragstests decken Eingaben, Erfolg, veraltete Revisionen, Wiederholung, request_id-Kollisionen und Seitenwechsel ab; nur In-Memory-Fake-Garantien | ausstehend |
| V10-11 | Konten/Instrumente in `SQLiteStore`, Migration 0003, manuelle Eröffnungen, `scripts/demo_master_data.py`; DTO-basierter Fake bleibt In-Memory | 13 SQLite-Stammdatentests plus 2 Fake-Vertragstests; Gesamtsuite 63 bestanden; Ruff und `git diff --check` bestanden; Terminalbeispiel vier Sollwerte/Neuöffnung OK | ausstehend |
| V10-09 | `infrastructure/migrations/0001_initial.sql`, `infrastructure/sqlite_store.py`; Ruff als `.[dev]` deklariert | Migration frisch/erneut, DDL-Rollback, 4 Golden-Vorgänge nach Reopen, Präzision/Lotkosten, FK/CHECK und Herkunft geprüft | ausstehend |
| V10-10 | unabhängige lesende Prüfung von Schema, Zahlformat und Modulgrenzen; Befunde in Migration/Prüfgrenzen umgesetzt bzw. dokumentiert | 48 V10-Tests; Ruff und Syntaxprüfung bestanden; unabhängiger Prüfer ohne offene Schema-/Zahlen-/Modulgrenzenbefunde | ausstehend |
| V10-12 | Migration 0004, `document_storage.py`, `parser_adapter.py`; nur comdirect Wertpapierkauf | Sichere Ablage/Hashwiederverwendung/Öffnen nach Neustart; fest gepinnter Parser durch echtes synthetisches PDF mit exakten kanonischen `-126.5 EUR`, `0.125` und separater Gebühr durchlaufen | ausstehend |
| V10-13 | `import_workflow.py`, `preview_codec.py`, Import-/Vorschau DTOs und `scripts/demo_import_preview.py` | 11 gezielte Ablaufprüfungen: Reopen/Versionsangaben, Entscheidung/Revision, widersprechende Kontovorgabe, Teilfehler, verschlüsselt/leere/ungültige Datei, unvollständiger Kauf, informationsneutraler MiFID, unsupported, gezielte Tempdatei-Bereinigung, queued/laufender Abbruch, Neustart ohne Retry; Vorschau ohne Event/Position | ausstehend |
| V10-14 (Teil) | Gleicher Dateiinhalt nach erfolgter Kaufübernahme: Parserneulauf, Konfliktziel, explizite Verknüpfungsentscheidung | synthetische Parser-PDF; ein Vorgang/zwei Positionen bleiben bestehen, zwei Importbeiträge belegen den Wiederimport | ausstehend |
| Vorschau Wertpapieridentität | Serverdarstellung nutzt bestehende `security_name`, `security_isin` und `security_wkn`; Stammdatenmatch bleibt separat; Konto-/Depot-Belegkennung steht nur in Details | gerenderte Vorschau mit gemapptem Kauf sowie echtem Parserdurchlauf ohne V10-Instrument; V-Präfix-Passthrough in gespeicherter Vorschau geprüft | ausstehend |
| V10-13 Instrumentzuordnung/Prüfpunkte | `parser_adapter.py` sucht Event-ISIN und nur ohne ISIN eindeutige WKN; Konflikte/Mehrfachtreffer bleiben offen. Vorschau markiert Zuordnungen und sonstige Prüfgründe rot/fett | echter Parserkauf: ungemappt → konkrete Meldung, neues Preview mit passender ISIN → zugeordnet/Meldung weg; WKN-Fallback, Kennungskonflikt und Mehrfachtreffer gezielt getestet | ausstehend |
| V10-25/26 (Teil) | `src/portman_v10/web/server.py`, serverseitige Templates, `start_v10_web.ps1`; Flask als optionale Web-Abhängigkeit | HTTP-Tests für Upload, Jobstatus, Vorschau, Originalzugriff, ungültige/zu große Uploads und unsupported; kein Buchungs-/Positionsschreibpfad | Browserprüfung und Nutzerabnahme nach tatsächlicher Rückmeldung ausstehend |

Keine Nutzerprüfung automatisch abhaken. Aktueller Paketstand: SQLite-Stammdaten-/Eröffnungsprototyp, getestete Dokumentablage, comdirect-Importvorschau und ausgewählte Übernahmepfade, persistente Jobs, fachliche Dubletten-/Belegverknüpfung mit selektiver Rücknahme, sowie lokale Web-Testoberfläche für Import, Konten und Instrumente. Der Bestandsindex wird bei Eröffnung, manueller Ereignisschreibung, Übernahme und Rücknahme aktualisiert; SQLiteStore bietet einen persistenten Stichtagslesepfad. Webansicht und unabhängige Nutzerabnahme sind noch zu prüfen. Vollständige Konten-/Buchungssuche steht aus.

### Comdirect-Vorgangstypen – gezielte Erweiterung am 7. November 2026

- [~] **Ausgewählte user.comdirect-Erträge-Bewegungen angebunden:** Kauf, Verkauf und Einlösung mit Parservorzeichen; Dividendengutschrift/Ertragsgutschrift als tatsächliche Geldgutschrift ohne synthetischen Depotzugang. Übernahme verlangt passende Zuordnungen und sichere Bankreferenz. Steuer-/Vorabpauschalen-/MiFID-Fälle bleiben Information ohne Buchung.
- [x] **Steuer-Parserlücke abgesichert:** Steuerereignis mit alleiniger Parser-Mengenbewegung und ohne tatsächliche Geldbewegung erzeugt keine V10-Position und bleibt mit konkretem Parsergrund offen.
- [x] **Registryabdeckung erfasst:** 19 ausführbare Registryeinträge mit Parserstatus, V10-Wirkung, Einschränkung und Testnachweis in `docs/Parserpruefung.md` dokumentiert.
- [x] **Automatikprüfung:** vollständige V10-Unittests 121 bestanden; Ruff über `src tests` bestanden; `git diff --check` bestanden; Parserpaket weiter 0.7.0 mit unverändertem Pin.
- [ ] **Noch offen, nicht als implementiert gezählt:** PP-Aliasbewegungen, sichere Übernahme einzelner Finanzreportzeilen/Wiederimport als Zweitbeleg, weitere Kontobewegungs-/Steuerbewegungstypen und vollständiger Durchlauf des autorisierten A2H57N-Belegs nach Eintrag des passenden V10-Instruments/Kontos.
- Nutzerprüfung bleibt ausstehend. Persönliche Referenz-PDFs wurden nicht versioniert.

### V10-16 Rücknahme – 7. November 2026

- **Implementierung:** `SQLiteStore.preview_rollback`/`execute_rollback`, `ImportWorkflow`-Anwendungsmethoden und Migration 0006 persistieren Plan-ID, gemeinsame Datenrevision, Importauswahl und Replaybericht. Vorschau listet betroffene Vorgänge, typisierte Feld-/Positionsbeiträge, Beleglinks, Instrumente, signierte Bestandswirkungen und konkrete Referenz-/Eröffnungs-/Lotkonflikte. Ausführung prüft Plan und Abhängigkeiten erneut unter `BEGIN IMMEDIATE`, entfernt nur ausgewählte Beiträge, bewahrt Event-Erzeugungs- und Instrumentherkunftsmarken bei verbleibenden Quellen, rekonstruiert den Bestandsindex und löscht ungenutzte, unveränderte, importseitig angelegte Instrumente. Manuelle Felder erhalten den Vorgang, ohne unbelegte Importpositionen zu erhalten. Fehler rollen auch Revision und Index zurück; der Bericht führt entfernte Positionen einzeln auf.
- **Dateien:** Externe Originale bleiben außerhalb der Rücknahme. Interne Kopien verbleiben, solange `import_documents`/`import_job_documents` sie als Historienquelle referenzieren; aktuelle Löschfälle sind dadurch nicht unreferenziert. Ein eigener Cleanup-Outboxpfad wurde nicht eingeführt.
- **Automatische Prüfung:** Importworkflowtests prüfen einzelne Rücknahme, ausdrücklich alle, Importquellen in beiden Belegreihenfolgen, Komponentenherkunft, Instrumentanlage/-wiederverwendung/-Erhalt, spätere Referenzabhängigkeit, veralteten Plan, dauerhaften Replay nach Reopen sowie Fehler nach Indexmutation. Aktueller Vollsuite-Lauf: 162 Tests, 161 bestanden; `test_investment_distribution_tax_notice_preserves_identity_without_position` schlägt wegen fehlendem `security_isin` fehl. Dieser Parser-/Ertragsfehler ist unabhängig von V10-16. Ruff `src tests` und `git diff --check` bestanden.
- **Nutzerprüfung:** Ausstehend. Anwendungsschnittstellenablauf: `preview = workflow.preview_rollback(RollbackSelection(import_ids=(import_id,)))`; Ergebnis und `unresolved_dependencies` prüfen; nur bei leerer Konfliktliste `workflow.execute_rollback(ExecuteRollback(preview.plan_id, preview.revision, request_id))`; Ergebnis anhand `removed_event_ids`, `retained_event_ids`, `removed_position_ids`, `removed_instrument_ids` und Datenrevision prüfen. Für alle aktiven Importe explizit `RollbackSelection(all_imports=True)` verwenden. Migration mit temporärer SQLite-Datenbank, nicht mit Echtdaten, prüfen.
- **Unabhängiges Review:** Lesendes Review fand fehlende Feldrücknahme bei erhaltenen gemeinsamen Vorgängen und fehlende Herkunft der initialen Gebühren/Steuern. Beide Punkte wurden feldweise umgesetzt; initiale Komponenten schreiben jetzt eigene Beiträge. Das Review belegte keine weitergehenden späteren Lotabhängigkeiten; direkte Event-/Positionsreferenzen werden blockiert. Teilallokationen ohne direkte Referenz sind weiterhin eine bekannte Grenze. Interne Dokumente bleiben wegen dauerhafter Importhistorie erhalten; ein Cleanup-Outboxpfad ist nicht vorhanden.

### Ertragsabgleich PDF Lab / V10 – 7. November 2026

- **Implementierung:** V10 behandelt eine `user.comdirect-ertraege/investment_ausschuettung` ohne tatsächliche Geldbewegung als saldenneutrale Information. Die erkannte Stückzahl wird nicht als Bestand gebucht; erwartete Kauf-/Settlementfelder blockieren sie nicht. Der Parserquellstand ergänzt Identität und Identitätsquellen auf Steuerereignissen. V10-Pin `227eaafb4fb49e4357006546a0855ea7a0668c0a` bleibt unverändert; Parserquelländerung und installiertes Wheel sind verschiedene Stände.
- **Automatische Prüfung:** Mit dem installierten V10-Pin scheitert `test_investment_distribution_tax_notice_preserves_identity_without_position`, weil der Parser keine ISIN liefert. Mit `portman-parsers/src` zuerst im `PYTHONPATH` besteht derselbe Vorschautest; zusätzlich bestehen die drei gezielten Parsermodule `test_comdirect.py`, `test_comdirect_evidence_pages.py` und `test_comdirect_security_identity.py` (74 Tests) sowie die vollständige V10-Suite (166 Tests). Der Parserpin bleibt unverändert; der Quelltest ist daher kein Nachweis für das installierte Wheel. Ruff `src tests` und `git diff --check` bestanden. Ruff auf dem Parsermodul meldet 144 vorhandene Pyflakes-Befunde aus dem breiten Altbestand der Datei; sie wurden nicht pauschal refaktoriert.
- **Nutzerprüfung:** offen. SAP-Original vom 21.05.2024 und der rote Investment-Ausschüttungsbeleg fehlen im lokalen V10-Testprofil. Daher sind PDF-Lab-Auditvergleich derselben PDFs, SAP-Referenzprüfung, beidseitiger Wiederimport-/Steuerbeleg-Reihenfolgetest und Browserabnahme nicht bestanden oder behauptet.

### Parser-Update nach Merge – 7. November 2026

- PR #68 (Parser 0.7.0) und PR #70 (Steuerbeleg-Identität) wurden gemergt. V10 pinnt jetzt den Main-Commit `074c3404d08e082c5f9b2a987ed302cfcf929f13` in `requirements-parser.txt`; Paketversion, API und Schema bleiben 0.7.0/0.6/1.6.0.
- Das V10-`.venv`-Wheel wurde aus diesem Commit neu gebaut und installiert. `direct_url.json` bestätigt den Commit. `test_investment_distribution_tax_notice_preserves_identity_without_position` besteht mit dem installierten Wheel; Importworkflow-Suite: 52 bestanden.
- Vollständige V10-Suite nach der Installation: 185 Tests bestanden. Ruff `src tests` und `git diff --check` bestanden.
- Weiterhin offen: identischer PDF-Lab-Abgleich der fehlenden Originale und Nutzerabnahme. Der neue Parserstand ändert keine Buchungsfreigabe für Steuerinformationen.

### Automatische Instrumentanlage im Import – 7. November 2026

- **Implementierung:** Die Anwendungs-DTOs melden in der Vorschau `instrument_resolution` und `instrument_message`; Commit-Ergebnisse liefern `created_instrument_ids`. Neue Stammsätze erfordern eine gültige ISIN und einen belegten Wertpapiernamen. Der neutrale Typ `security` verhindert eine unbelegte Einordnung als Aktie/Fonds. ISIN/WKN werden im atomaren SQLite-Commit erneut abgeglichen; Instrument, Kennungen, Quellenbeitrag und Vorgang teilen dieselbe Transaktion. Keine Webserver-/Templateänderung in diesem Arbeitsschritt.
- **Automatische Prüfung:** 137 V10-Unittests, Ruff `src tests` und `git diff --check` bestanden. Die gezielten Tests in `tests/test_import_workflow.py` sind `test_a2h57n_confirmed_import_creates_instrument_once_and_reuses_it`, `test_parallel_imports_for_same_new_isin_do_not_create_duplicate_instruments` und `test_failed_a2h57n_commit_rolls_back_new_instrument_with_event`. Übergabe-Befehl aus dem Paketordner: `$env:PYTHONPATH='src;tests'; .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_import_workflow.py -v`.
- **Temporärer Originalbeleglauf:** Die lokal vorhandenen Originale mit `A2H57N` aus `data/web-test` wurden in einer separaten temporären SQLite-Datenbank geprüft: Vorschau ohne Stammdatenänderung; bestätigter Erstimport mit genau einem Instrument und Kauf; identischer Wiederimport ohne zweite Buchung; zweiter Originalbeleg mit derselben ISIN verwendet dasselbe Instrument. Der Lauf gab keine persönlichen Kennungen aus.
- **Nutzerprüfung/Übergabe an Web-GUI:** noch ausstehend. Erwartete API-Anzeige vor Bestätigung: `instrument_resolution == "will_create"` und `instrument_message` beginnt mit „Neues Instrument wird angelegt“; nach Bestätigung enthält `CommitReport.created_instrument_ids` genau die neu angelegten Instrumente. In der Browservorschau bestätigen, dass noch nichts persistiert wird; erst nach ausdrücklicher Annahme erscheinen Instrument und Kauf. Die Web-GUI ist in diesem Arbeitsschritt nicht geändert.

### V10-19/20 Bestandsindex – 7. November 2026

- **Implementierung:** `SQLiteStore.get_overview` liest je Konto und Währung/Instrument die letzte Indexzeile bis zum angefragten Tag. `ImportWorkflow.get_overview` stellt den Anwendungsaufruf bereit. Indexpunkte werden nur für Änderungstage gespeichert; alle Reihen tragen nach einer veröffentlichten Änderung dieselbe Datenrevision. Eröffnung setzt den bekannten Bestand fest; Historie davor bleibt `unknown` und wird nicht zur Eröffnung addiert. Eröffnungen und allgemeine Ereignisse aktualisieren ihre Reihen transaktional; rückdatierte Änderungen berechnen spätere Punkte derselben Reihe neu. Commit aktualisiert betroffene Reihen, Rücknahme rekonstruiert die verbleibenden Reihen atomar.
- **Automatische Prüfung:** `test_master_data.py` (14 Tests) und `test_import_workflow.py` (52 Tests) bestanden; Stichtagsgrenzen, Währungs-/Instrumenttrennung, Rückdatierung, unbekannter Vor-Eröffnungszeitraum, unveränderte Reihen, Wiederöffnen sowie Commit-/Rollbackindex sind enthalten.
- **Nutzerprüfung:** ausstehend. In der Test-Weboberfläche `/overview` ein Datum vor und nach einer Eröffnung aufrufen, danach eine Buchung erfassen und einen rückdatierten Änderungstag prüfen. Erwartet werden die Werte aus `workflow.get_overview(as_of)`, „Unbekannt“ vor der Eröffnung und eine aktualisierte gemeinsame Datenrevision. Keine Echtdaten verwenden.
- **Grenze:** Performanceziel und 100.000-Positionsmessung gehören zu V10-22 und wurden hier nicht geprüft.

### Offene Importvorschau verwerfen – 7. November 2026

- **Implementierung:** `ImportWorkflow.discard_import(import_id, expected_revision)` und derselbe Vertrag in `ApplicationService` verwerfen ausschließlich eine offene Vorschau. Der SQLite-Kern prüft Import-/Jobstatus und Vorschauversion unter einer Schreibtransaktion, setzt Import und Job auf `cancelled` und entfernt Vorschau sowie gespeicherte Entscheidungen. Importhistorie, Dokumentzuordnungen und Originaldateien bleiben erhalten; Buchungen und Bestände werden nicht verändert. Die bereits vorbereitete Schaltfläche auf Jobseite und Importliste ist damit an den Kern angebunden.
- **Automatische Prüfung:** `tests/test_import_workflow.py` prüft Verwerfen, veraltete Revision, Schutz eines übernommenen Imports, erhaltenes Original und erneute Einreichung. `tests/test_web_imports_list.py` prüft Formular/CSRF-Route und Statusanzeige. Vollständige V10-Suite: 220 Tests bestanden, 2 übersprungen; Ruff `src tests` und `git diff --check` bestanden.
- **Nutzerprüfung:** ausstehend. Im isolierten Testprofil eine offene Vorschau öffnen, „Vorschau verwerfen“ betätigen und bestätigen, dass der Job als abgebrochen erscheint, keine Buchung entsteht und derselbe Beleg erneut eingereicht werden kann.
