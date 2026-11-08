# Portman V10 – Arbeitsregeln

## Ziel und Umfang
- Eigenständiges, schlankes Paket `portman-v10/`. V09 unverändert lassen.
- Zuerst Importkontrolle: Beträge, Mengen, Gebühren, Steuern, Suche und Rücknahme.
- Keine Charts, Kurse, Renditebibliotheken oder Fundamentaldaten ohne Auftrag.
- Bauplan und Schnittstellen im Paket unter `docs/` pflegen; keine doppelten Spezifikationen.
- Diese Datei gilt für das V10-Paket. Übergeordnete widersprechende Altregeln konkret benennen, statt V09-Struktur zu übernehmen.

## Arbeitsbereich und Isolation
- Änderungen ausschließlich im V10-Paket; vorhandene fremde Änderungen erhalten.
- V09 weder importieren noch ändern. Lesen außerhalb V10 nur für konkret beauftragte Schnittstellenprüfung.
- portman-parsers als Paket verwenden; Änderungen dort sind ein eigener Auftrag.
- Diese Regeln sind keine technische Sandbox. Eine Zugriffssperre muss die Ausführungsumgebung erzwingen; niemals eine ungeprüfte Isolation behaupten.
- Bei paralleler Schreibarbeit separate Branches und Worktrees; nie zwei Agenten gleichzeitig an denselben Dateien.

## Architektur
- `domain`: exakte Werte und Finanzregeln; ohne Qt, HTTP, SQL oder Parserimports.
- `application`: typisierte Anwendungsfälle/DTOs, Transaktionen, Revisionen.
- `infrastructure`: SQLite, Dokumentablage und Adapter zu portman-parsers.
- Oberflächen verwenden nur die Anwendungsschnittstelle, niemals SQL oder eigene Finanzregeln.
- Lokal und später per HTTP derselbe Fachkern. Kleine Web-Testoberfläche zuerst.
- Keine eigenen Parser oder bankspezifischen Fallbacks. API und Handler tatsächlich prüfen.
- PDF Lab bleibt separat; keine Laufzeitabhängigkeit zu PDF Lab oder V09.

## Datenregeln
- Geldkonto oder Bestandskonto; Unterarten Giro/Tagesgeld/Festgeld/Verrechnung/Depot/Krypto.
- Eine wirtschaftliche Bewegung einmal erfassen; mehrere Belege dürfen sie ergänzen.
- Geld-/Mengenpositionen bestimmen Bestände. Gebühren-/Steuerdetails nicht doppelt zählen.
- Exakte Dezimalwerte; keine Floats für Buchhaltung. Fehlend ist unbekannt, nicht null.
- Originaltext, Referenzen und Belegherkunft erhalten; alle Buchungen durchsuchbar.
- Jeder Import einzeln, als Auswahl oder insgesamt rücknehmbar; unabhängige manuelle Änderungen erhalten.
- Vorschauversion, request_id und atomare Änderung schützen vor Doppelübernahme.
- Bestandsindex nur an Änderungstagen, dauerhaft und im Speicher; revisionsgleich mit Buchungen.
- Stichtagsblättern per Index, nicht durch erneutes Summieren aller Buchungen.
- Freistellungsauftrag je Steuerjahr und Bank-/Inhaberbezug. Kumulierte Verbrauchsstände nicht zu enthaltenen Einzelwerten addieren. Quellenstand anzeigen.
- Keine echten Portfolio-/Kontodaten, PDFs, Datenbanken oder Zugangsdaten committen.

## Effizient arbeiten
- Pro Auftrag einen kleinen, vollständig prüfbaren Schritt liefern. Keine Nebenrefactorings.
- Zuerst git status, relevante AGENTS.md und vorhandene Implementierung prüfen.
- Mit rg Dateipfade/Symbole eingrenzen; gezielte Ausschnitte statt ganzer Repositories lesen.
- Unabhängige Lesezugriffe bündeln. Keine unveränderten Dateien wiederholt lesen.
- Bauplan nicht pro Aufgabe vollständig wiederholen. Nur relevante Abschnitte laden.
- Erst vorhandene Komponenten nutzen; neue Abhängigkeiten nur mit konkretem Nutzen.
- Keine vorsorglichen Frameworks, generischen Abstraktionen oder Pluginplattformen.
- Routinen innerhalb des Auftrags selbstständig erledigen. Bei echten fachlichen Unklarheiten gezielt fragen.
- Keine parallelen Agenten ohne ausdrücklichen Auftrag. Ein verantwortlicher Agent pro Änderung.
- Keine automatisch erzeugten Zwischenberichte, Diagramme oder Dokumentkopien ohne Nutzen.
- Nach bestandenen relevanten Checks nicht ohne neuen Grund erneut testen oder analysieren.

## Umsetzung und unabhängige Prüfung
- Der Umsetzungsagent implementiert, schreibt passende Tests und führt sie aus.
- Ein Prüfagent wird nur ausdrücklich beauftragt und arbeitet zunächst lesend.
- Für Buchungslogik, Dubletten, Rücknahme, Schema und Bestandsindex ist vor Merge eine unabhängige Prüfung vorgesehen; falls nicht erfolgt, offen benennen.
- Review anhand Anforderungen, Diff und relevanter Tests: Fehler, fehlende Fälle und Risiken mit Dateibelegen. Keine bloße Wiederholung des Entwicklerberichts.
- Korrekturen anschließend durch den verantwortlichen Umsetzungsagenten.

## Kontext und Tokenverbrauch
- Dauerhafte Regeln hier; detaillierter Bauplan und Verträge in docs/. Keine doppelte Pflege in CLAUDE.md.
- Pro Aufgabe nur relevante Spezifikationsabschnitte und Quelldateien laden.
- Zusammenhängende Aufgabe in derselben Sitzung bearbeiten; unnötige Modell-/Werkzeugwechsel vermeiden.
- Kein künstlicher Zusatztext oder übergroßer Kontext zur vermeintlichen Cacheoptimierung.
- Regeln während einer Aufgabe nur bei inhaltlichem Bedarf ändern, nicht für wechselnde Statusmeldungen.
- Nach Meilensteinen kurze Übergabe: Stand, Tests, offene Entscheidungen, nächster Schritt. Kein vollständiges Gespräch abschreiben.

## Prüfen und Abschluss
- Tests auf fachliches Verhalten: Beträge, Dubletten, Rücknahme, Revisionen und Bestandsindex.
- Zuerst betroffene Tests; breitere Suite bei gemeinsamem Kern, Schemaänderung oder vor PR.
- Keine Tests, die nur die Implementierung nachschreiben.
- Grundgerüst: aus dem Paket `python -m unittest discover -s tests -v`, zuvor `src` auf PYTHONPATH setzen.
- Unter PowerShell: `$env:PYTHONPATH = 'src'`. Unter Linux: `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
- Neue Prüfkommandos erst dokumentieren, wenn sie wirklich existieren und ausgeführt wurden.
- Geschwindigkeit messen: Ziel p95 <50 ms für warmes lokales Stichtagsblättern; Hardware und Datenumfang nennen.
- Kurz auf Deutsch abschließen: Änderung, Prüfung, verbleibende Einschränkung.
- Keine ungetesteten Aussagen wie „fertig“, „freigegeben“ oder „performant“.

## Nutzerprüfung und Buchungsansicht
- Alle Giro- und sonstigen Buchungen dauerhaft scrollbar, durchsuchbar und kombinierbar filterbar halten; auch deaktivierte Konten.
- Datenbankseitig filtern/sortieren und seitenweise automatisch nachladen; stabile Reihenfolge, keine vollständige Historie in die View laden.
- Gegenpartei nur durchsuchen/anzeigen, soweit tatsächlich erfasst; unbekannte Daten nicht ergänzen oder erraten.
- Nach jedem abgeschlossenen Schritt einen reproduzierbar prüfbaren Stand liefern. Ohne GUI zunächst ausführbarer Referenzablauf.
- Sobald die Weboberfläche existiert: ein lokaler Startbefehl öffnet sie im Browser. Testdatenbank von echten Daten trennen.
- Branch/Commit und Datenbankprofil in der Testoberfläche sichtbar machen.
- Pro Änderung eine knappe Prüfanleitung: Was, wo, erwartetes Ergebnis, geprüfter Commit, bekannte Grenzen.
- In docs/TASKS.md Implementierung, automatische Prüfung und Nutzerprüfung getrennt dokumentieren; Nutzerprüfung nur nach tatsächlicher Rückmeldung als bestanden markieren.
