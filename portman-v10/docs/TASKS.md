# Portman V10 – Aufgabenliste

Stand: 6. November 2026. Grundlage: Bauplan 3.2. Empfohlener Ablageort: `portman-v10/docs/TASKS.md`.

Status: [x] nachweislich vorbereitet/umgesetzt; [ ] offen. Das V10-Paket liegt auf Branch `codex/portman-v10-foundation` mit Draft-PR #69. Vorbereitung und Prototyp sind keine produktive Anwendung oder Migration. Parser-PR #68 bleibt separat zu entscheiden.

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

## P1 – Vollständiger Importweg und Rücknahme

- [x] V10-11 **Konten und Instrumente verwalten.** Persistente Stammdaten, kontextbezogene Kennungen, Revisionen und manuelle Startbestände; Migration 0003 ergänzt Kennungskontext und Eröffnungsherkunft. Ausführbarer temporärer Terminalablauf; Buchungs-/Eröffnungsänderungen invalidieren den nicht gepflegten Index über die gemeinsame Datenrevision. Keine produktive Indexpflege, Rücknahme oder vollständige Historie behauptet.
- [x] V10-12 **Dokumentablage und ersten Parseradapter bauen.** comdirect Wertpapierkauf über `extract_pdf`, `default_registry`, echten Handler und Parservalidierung aus dem fixierten portman-parsers 0.7.0/Commit; MiFID-Kosteninformation ausdrücklich nur informationsneutral, alle weiteren Handler `unsupported`. Originalbytes hashadressiert und atomar bereitgestellt, identische Bytes teilen eine Datei, opaque Dokumentzugriff ohne Pfad. Keine eigene Extraktion.
- [x] V10-13 **Importvorschau und begrenzte Jobs implementieren.** Dauerhafte Status/Progress, Mehrdatei-Teilfehler, kooperativer Abbruch, Neustartmarkierung und revisionierte Prüfentscheidungen. Exakte Geld-/Mengenwerte, Details, Daten, Quellen/Warnungen und Zuordnungen sichtbar. Kandidaten bleiben `unclassified`; vor V10-14 kein fachlicher Dublettenabgleich, vor V10-15 keine Übernahme. Keine produktiven Buchungen.
- [ ] V10-14 **Dubletten und Ergänzungen behandeln.** Fertig: Dateiwiederholung und mehrere Belege erzeugen keine Doppelzählung; zwei echte identische Käufe bleiben getrennt; Reihenfolge der Belege beeinflusst Ergebnis nicht.
- [ ] V10-15 **Atomare Übernahme umsetzen.** Herkunft und Index gemeinsam committen; Vorschauversion und request_id prüfen. Fertig: Timeout-Wiederholung genau einmal wirksam; gleiche ID mit anderer Eingabe abgelehnt; Abbruch hinterlässt keine Teilbuchung.
- [ ] V10-16 **Vollständige Rücknahme umsetzen.** Einzeln/Auswahl/alle, Vorschau und Abhängigkeitsentscheidungen. Fertig: ausschließlich betroffene Importbeiträge entfernt, gemeinsame Belege und manuelle Änderungen erhalten, Dateibereinigung wiederanlaufbar, erneuter Import möglich.
- [ ] V10-17 **Sonderbedeutungen prüfen.** Finanzreport zeilenweise, MiFID informationsneutral, Steuerbasis/Freistellungsverbrauch ohne zusätzliche Geldwirkung. Fertig: unterstützte reale Referenzfälle belegen korrekte Betragsbedeutung.
- [ ] V10-18 **Import-/Rücknahmeprüfung unabhängig durchführen.** Fertig: Konflikte, gemeinsame Quellen, alte Ergänzungen, manuelle Änderungen, Teiltransfers und konkurrierende Übernahmen geprüft; Befunde behoben.

**Meilenstein B:** Dokument → Vorschau → Übernahme → Wiederimport → Ergänzungsbeleg → Rücknahme liefert exakte erwartete Bestände.

## P1 – Stände und schnelle Navigation

- [ ] V10-19 **Persistenten Bestandsindex implementieren.** Kumulierte Geld-/Mengenstände nur an Änderungstagen, gemeinsame Datenrevision. Fertig: beliebige Stichtage korrekt; keine Vermischung von Währungen/Instrumenten.
- [ ] V10-20 **Inkrementelle Pflege und Speicherindex ergänzen.** Fertig: rückdatierte Änderungen/Rücknahmen aktualisieren betroffene Reihen; konsistenter Speicherstand nach Commit, Neustart und Rekonstruktion geprüft.
- [ ] V10-21 **Zeitnavigation implementieren.** Tag/Woche/Monat/Jahr/freie Schritte, Datumsauswahl und Heute. Fertig: Tagesanker, Monatsenden/Schaltjahre und bewegungslose Tage korrekt; Datum und Daten bleiben konsistent.
- [ ] V10-22 **Geschwindigkeit messen.** Mindestens 100.000 Positionen, dokumentierte Hardware und Kontenzahl. Fertig: warmes lokales Blättern p95 <50 ms; Kaltstart und Indexpflege separat gemessen; langsame Fälle gezielt korrigiert. Kein unbelegtes Versprechen für Netzwerklatenz.

## P1 – Steuerinformationen

- [ ] V10-23 **Freistellungsaufträge verwalten.** Steuerjahr, Gültigkeit, Bank-/Inhaberbezug und Kontenzuordnung. Fertig: gemeinsame Aufträge einmal gezählt, Jahresänderungen historisch erhalten.
- [ ] V10-24 **Verbrauch und Rest anzeigen.** Nur belegte Werte aus unterstützten Parsern, Quellenstichtag und Vollständigkeit. Fertig: kumulierte/Einzelwerte nicht doppelt addiert, Minderungen/Konflikte/Unbekannt korrekt; Rücknahme aktualisiert den Stand, manueller Auftrag bleibt erhalten.

## P1 – Einfache Bedienung und Suche

- [ ] V10-25 **Dünne lokale HTTP-Schnittstelle bauen.** Fertig: dieselben Anwendungsfälle und DTO-Bedeutungen wie lokal; keine zweite Fachlogik; Inhalte statt beliebiger Server-Dateipfade übertragen.
- [ ] V10-26 **Web-Testoberfläche erstellen.** Kontenübersicht, Buchungen, Import, Stammdaten. Fertig: Dateien wählen → prüfen → übernehmen; Beträge/Steuern/Gebühren/Mengen und Quellen lesbar, Details auf Wunsch, Tabellen kopierbar, Rücknahme verständlich.
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

V10-14 Dubletten/Ergänzungen gesondert fachlich umsetzen, danach V10-15 Übernahme samt Atomarität, request_id und Bestandsindex. V10-12/13 bleiben begrenzter Prototyp und nicht produktiver Buchungsweg.


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
| V10-04 | Parser 0.7.0 auf `227eaafb4fb49e4357006546a0855ea7a0668c0a` im offenen PR #68; Remote- und lokaler Pin dokumentiert | 268 Parser-Tests bestanden; frische Remote-Installation und 4 V10-Tests bestanden; Review ohne offene mittlere/blockierende Befunde | ausstehend |
| V10-05 | `domain.rational.RationalAmount`, Decimal-/Rational-SQLite-Collations und `scripts/compare_number_variants.py`; keine Migration | 7 Zahlenrepräsentations-Tests plus 14 V10-06-Golden-Tests und 6 Vertragsprüfungen bestanden; 100.000 Zeilen je Variante gemessen | ausstehend |
| V10-06 | Referenzfälle, proportionale Lotaufteilung und synthetische Daten in `docs/Datenmodell.md` und `tests/reference_cases.py`; Rechenregel unabhängig geprüft, Speicherung auf V10-09/16 vertagt | 14 fachliche Golden-Tests; gesamte V10-Suite 27 bestanden, einschließlich exakter rationaler Kostenerhaltung ohne Float/Rundung | ausstehend |
| V10-07 | `application/contracts.py`, `docs/Schnittstelle.md` Version 0.2 | Transportneutrale Verträge für alle beauftragten Anwendungsfälle, Revisionen, unbekannt und Fehlercodes; 10 gezielte Vertragstests | ausstehend |
| V10-08 | `application/fake_service.py` mit synthetischen Beispielen | Vertragstests decken Eingaben, Erfolg, veraltete Revisionen, Wiederholung, request_id-Kollisionen und Seitenwechsel ab; nur In-Memory-Fake-Garantien | ausstehend |
| V10-11 | Konten/Instrumente in `SQLiteStore`, Migration 0003, manuelle Eröffnungen, `scripts/demo_master_data.py`; DTO-basierter Fake bleibt In-Memory | 13 SQLite-Stammdatentests plus 2 Fake-Vertragstests; Gesamtsuite 63 bestanden; Ruff und `git diff --check` bestanden; Terminalbeispiel vier Sollwerte/Neuöffnung OK | ausstehend |
| V10-09 | `infrastructure/migrations/0001_initial.sql`, `infrastructure/sqlite_store.py`; Ruff als `.[dev]` deklariert | Migration frisch/erneut, DDL-Rollback, 4 Golden-Vorgänge nach Reopen, Präzision/Lotkosten, FK/CHECK und Herkunft geprüft | ausstehend |
| V10-10 | unabhängige lesende Prüfung von Schema, Zahlformat und Modulgrenzen; Befunde in Migration/Prüfgrenzen umgesetzt bzw. dokumentiert | 48 V10-Tests; Ruff und Syntaxprüfung bestanden; unabhängiger Prüfer ohne offene Schema-/Zahlen-/Modulgrenzenbefunde | ausstehend |
| V10-12 | Migration 0004, `document_storage.py`, `parser_adapter.py`; nur comdirect Wertpapierkauf | Sichere Ablage/Hashwiederverwendung/Öffnen nach Neustart; fest gepinnter Parser durch echtes synthetisches PDF mit exakten kanonischen `-126.5 EUR`, `0.125` und separater Gebühr durchlaufen | ausstehend |
| V10-13 | `import_workflow.py`, `preview_codec.py`, Import-/Vorschau DTOs und `scripts/demo_import_preview.py` | 11 gezielte Ablaufprüfungen: Reopen/Versionsangaben, Entscheidung/Revision, widersprechende Kontovorgabe, Teilfehler, verschlüsselt/leere/ungültige Datei, unvollständiger Kauf, informationsneutraler MiFID, unsupported, gezielte Tempdatei-Bereinigung, queued/laufender Abbruch, Neustart ohne Retry; Vorschau ohne Event/Position | ausstehend |

Keine Nutzerprüfung automatisch abhaken. Aktueller Paketstand: SQLite-Stammdaten-/Eröffnungsprototyp plus getestete Dokumentablage, comdirect-Kaufvorschau und persistente Jobs. Noch keine produktive Übernahme, fachliche Dubletten-/Belegzusammenführung, Rücknahme, Indexpflege, GUI oder Nutzerabnahme.
