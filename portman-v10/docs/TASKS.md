# Portman V10 – Aufgabenliste

Stand: 6. November 2026. Grundlage: Bauplan 3.2. Empfohlener Ablageort: `portman-v10/docs/TASKS.md`.

Status: [x] nachweislich vorbereitet; [ ] offen. Vorbereitung ist keine fertige Implementierung. Branch, Repositoryintegration und produktive Migration sind noch nicht erfolgt. Aktuellen lokalen/GitHub-Stand vor Beginn prüfen.

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
- [x] V10-04 **Parservertrag vollständig prüfen.** Installierbare Version, Lizenz, Entry-Points, DTO-Felder, ausführbare Handler und Referenztests prüfen. Fertig: konkrete unterstützte Anbindung dokumentiert, keine erfundene API. Nachweis: `docs/Parserpruefung.md`, fixierter Commit mit 196 bestandenen und einem optional übersprungenen Parser-Test.
- [ ] V10-05 **Exakte Zahlendarstellung entscheiden.** Präzision, SQLite-Roundtrip, Betragssuche, Summen, Kryptomengen mit mindestens 18 Nachkommastellen und große Werte vergleichen. Fertig: gemessene Entscheidung ohne Float-/Überlauf-/Decimal-Kontextverlust.
- [ ] V10-06 **Vier Referenzvorgänge modellieren.** Kauf, Ausschüttung, Geldtransfer und Depotübertrag samt Gebühren/Steuern und unbekannten Kosten. Fertig: erwartete Geld-/Mengenwirkungen, Datumsbasis und Quellen eindeutig festgelegt.
- [ ] V10-07 **Anwendungsschnittstelle vervollständigen.** DTOs für Konten, Jobs, Vorschau, Commit, Suche, Dokumente, Rücknahme, Stichtag und Freistellung. Fertig: typisiert, revisionsfähig, unbekannte Werte ausdrücklich, keine Parser-/Qt-/SQL-Objekte im Vertrag.
- [ ] V10-08 **FakeService und Vertragstests ergänzen.** Fertig: wichtige Ansichten ohne Datenbank entwickelbar; Fehler, Dezimalserialisierung und Seitenlogik geprüft.
- [ ] V10-09 **Erstes Schema und Migration erstellen.** Konten, Instrumente, Vorgänge/Positionen, Komponenten, Dokumente, Importbeiträge, Wiederholungsschutz und Bestandsindex; Steuer-/Festgeldstrukturen passend zum nächsten Ablauf. Fertig: CHECK/FK-Regeln, versionierte Migration und Referenz-Roundtrip geprüft.
- [ ] V10-10 **Architekturprüfung durchführen.** Fertig: domain/application ohne GUI importierbar; keine V09-Imports und kein SQL oder Bankparsercode in Views. Unabhängige Prüfung von Schnittstelle/Schema dokumentiert.

**Meilenstein A:** Schnittstellen und exaktes Modell tragen die vier Referenzfälle. Danach können Oberfläche und Kern getrennt entwickelt werden.

## P1 – Vollständiger Importweg und Rücknahme

- [ ] V10-11 **Konten und Instrumente verwalten.** Zwei Grundtypen mit allen vereinbarten Unterarten, Kennungen, Eröffnungen und deaktivierbaren Konten. Fertig: Giro als Referenzkonto möglich; historische Daten bleiben erhalten.
- [ ] V10-12 **Dokumentablage und Parseradapter bauen.** Erst einen tatsächlich freigegebenen Dokumenttyp anbinden, vorzugsweise comdirect. Fertig: sichere Originalablage, Hash und Parser-/Schemaversion vorhanden; keine eigene Extraktion.
- [ ] V10-13 **Importvorschau und Jobs implementieren.** Fertig: neu/vorhanden/Ergänzung/Prüfung/Fehler, Quellen und Kontozuordnung sichtbar; vor Übernahme keine produktiven Buchungen; Parsing abbrechbar.
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

V10-01 bis V10-04: Arbeitsbereich isolieren, Vorbereitung integrieren, tatsächliche Parseranbindung verifizieren. Anschließend V10-05 bis V10-10 als Fundament abschließen. Kein offener Punkt gilt durch diese Liste als bereits umgesetzt.


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
| V10-04 | Parsercommit `816034a` in `requirements-parser.txt` fixiert; Vertrag in `docs/Parserpruefung.md` dokumentiert | 196 Parser-Tests bestanden, 1 optionaler PDFium-Test übersprungen | ausstehend |

Nur bei tatsächlichem Abschluss eine Zeile ergänzen. Keine Nutzerprüfung automatisch abhaken. Aktueller Paketstand: Grundgerüst und Dokumente; keine produktive Anwendung, keine Nutzerabnahme.
