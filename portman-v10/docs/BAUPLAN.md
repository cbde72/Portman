# Portman V10 – Bauplan 3.2: Schritt für Schritt

Stand: 5. November 2026. Konsolidierter Architektur- und Umsetzungsentwurf; ersetzt die vorherigen Fassungen einschließlich abweichender Cache-Empfehlungen. Noch keine implementierte Anwendung.

## Ziel

Eine eigenständige, schlanke Portfolioverwaltung, unabhängig von V09. Zuerst korrekte Importe und überprüfbare Beträge, danach weitere Funktionen. Kleine Web-Testoberfläche, vollständig getrennte Applikationslogik, vorbereitet für Desktop und späteren Fernzugriff. Schnelles zeitliches Blättern ist ein Kernmerkmal.

## Verbindliche Entscheidungen

- V09 bleibt unverändert; keine automatische Komplettmigration.
- Parser ausschließlich aus portman-parsers; PDF Lab bleibt das separate Entwicklungs- und Prüfwerkzeug und ist keine Laufzeitabhängigkeit.
- Zwei Kontogrundtypen: Geldkonto und Bestandskonto. Darstellung als Giro, Tagesgeld, Festgeld, Verrechnungskonto, Depot oder Kryptokonto/Wallet.
- Eine wirtschaftliche Bewegung wird einmal erfasst; mehrere Dokumente können sie belegen oder ergänzen.
- Alle übernommenen Buchungen bleiben durchsuchbar, auch bei deaktivierten Konten.
- Vollständige Rücknahme einzelner, ausgewählter oder aller Importe gehört zum ersten Lieferumfang.
- Exakte Geld- und Mengenrechnung; fehlende Werte sind unbekannt und nicht null.
- Clean, lean, modern, professionell: wenige Ansichten, klare Aktionen, Details auf Anforderung.
- Zunächst keine Charts, Kurse, Renditen, Fundamentaldaten oder Analysebibliotheken.
- Vorberechneter Bestandsindex: dauerhaft gespeichert und im Speicher verfügbar. Er ist abgeleitet, keine zweite Buchungswahrheit.

## Schritt 1 – Eigenständiges Projekt und klare Modulgrenzen

Empfohlene Basis: Python und SQLite; konkrete Versionen nach Prüfung der Parserkompatibilität. Ein Projekt mit domain, application, infrastructure und Oberflächenadaptern. Keine Microservices, kein allgemeines Plugin-Framework, kein Event-Sourcing.

| Baustein | Aufgabe | Darf nicht enthalten |
|---|---|---|
| Fachkern | Buchungsregeln, exakte Arithmetik, Geld- und Mengenlogik | Qt, HTTP, SQL oder PDF-Extraktion |
| Applikationsschicht | Anwendungsfälle, Transaktionsgrenzen, Freigabe, Suche und Rücknahme koordinieren | Oberflächencode |
| Infrastruktur | SQLite, Dateien, Parseradapter, Bestandsindex-Persistenz | Bankspezifische Extraktionsregeln |
| Web-/Desktopoberfläche | Eingaben und Darstellung | Eigene Finanzregeln oder direkter SQL-Zugriff |

Fertig, wenn Kern und Applikationsschicht ohne Oberfläche importiert und getestet werden können.

## Schritt 2 – Schnittstellenvertrag zuerst festlegen

Eine kleine ApplicationService-Schnittstelle bedient lokale Aufrufe. Ein dünner HTTP-Adapter macht dieselben Anwendungsfälle für die Web-Testoberfläche erreichbar. Kein zweiter Finanzkern. Fachliche Aufrufe statt allgemeinem Tabellen-CRUD.

| Anwendungsfall | Eingabe | Ergebnis |
|---|---|---|
| Konten lesen/anlegen/ändern | Filter, Kontodaten, erwartete Revision bei Änderung | Kontodaten und neue Revision |
| Import starten / Job lesen / abbrechen | Dateien bzw. Inhaltsstreams, optionale Kontovorgabe / Job-ID | Job-ID, Fortschritt, Ergebnis |
| Importvorschau / Kandidat entscheiden | Import-ID / Kandidat, Entscheidung, Revision | Neu, vorhanden, Ergänzung, Konflikt oder Fehler |
| Import übernehmen | Import-ID, Vorschauversion, request_id | Übernahmebericht |
| Buchungen suchen / Details | Filter, Cursor / Vorgang-ID | Ergebnisseite / Positionen, Betragsdetails und Quellen |
| Dokument öffnen | Dokument-ID | Metadaten und Dateiinhalt, kein interner Serverpfad |
| Importhistorie | Filter, Cursor | Übernahmen und Status |
| Rücknahme vorschauen / ausführen | Importauswahl / Plan-ID, Version, Entscheidungen, request_id | Auswirkungen / Rücknahmebericht |
| Freistellungsauftrag pflegen / Steuerübersicht lesen | Steuerbezug, Steuerjahr, Betrag/Gültigkeit und erwartete Revision / Stichtag | Auftrag und Revision / genutzt, verfügbar, Quellenstand und Vollständigkeit |
| Kontenübersicht zum Stichtag | Datum, Kontoauswahl | Geldsalden und Mengenbestände mit gemeinsamer Datenrevision |

Die kombinierte Stichtagsabfrage vermeidet einen Netzwerkaufruf je Konto. Optionale Bereichsabfrage liefert benachbarte Stichtage für einen kleinen Oberflächen-Cache.

### Austauschregeln

- IDs als stabile opaque Strings. Namen, Ticker und Zeilennummern sind keine Identitäten.
- Geld als Dezimalstring plus Währung, Mengen als Dezimalstring plus Instrument-ID; keine JSON-Floats.
- Datum als ISO-Datum; Zeitpunkt mit Zeitzone. Buchungsdatum, Handelsdatum und Valuta werden nicht vermischt.
- Unbekannte Werte ausdrücklich kennzeichnen. Anzeigeprojektionen sind keine vollständigen Buchungsobjekte.
- Feste typisierte DTOs, verständliche Status- und Fehlercodes. Keine Qt-Objekte, SQL-Rows oder Parserobjekte im Vertrag.
- Stabile Sortierung mit ID als zweitem Schlüssel; seitenweise Ergebnisse und Cursor. Bei Datenänderung Cursorrevision prüfen bzw. Suche neu starten.
- Optimistische Revisionen schützen Vorschauen und manuelle Änderungen. Schnittstellenversion und Datenrevision sind unterschiedliche Begriffe.
- Übernahme und Rücknahme erhalten eine gespeicherte request_id. Wiederholung nach Timeout liefert denselben Abschluss, keine zweite Änderung.

Erste Fehlercodes: VALIDATION_ERROR, UNRESOLVED_ACCOUNT, POSSIBLE_DUPLICATE, SOURCE_CONFLICT, STALE_REVISION, DEPENDENCY_CONFLICT, NOT_FOUND, CANCELLED. Meldungen nennen Problem und mögliche nächste Aktion. Technische Details sind separat abrufbar.

Fertig, wenn eine Fake-Implementierung die geplanten Ansichten bedienen kann und Vertragstests Eingaben, Fehler, Dezimalwerte und Wiederholungen prüfen. Danach können Oberfläche und Kern unabhängig entwickelt werden.

## Schritt 3 – Datenmodell und exakte Zahlen festlegen

| Datenbereich | Inhalt |
|---|---|
| accounts | ID, Name, Geld-/Bestandskonto, Unterart, Kontowährung bei Geldkonten, Institut, aktiv, optional Referenzkonto |
| account_identifiers | Benötigte IBAN-/Konto-/Depotkennungen und ihr Kontext |
| instruments / instrument_identifiers | Name, Anlageart, ISIN/WKN, kontextbezogene Ticker-/Anbieter-/Netzwerkkennungen |
| events | Vorgangsart, Datumswerte, Originaltext, Status, Revision, Korrektur-/Stornobezug |
| postings | Geld- oder Mengenposition, Konto, Wert, Währung oder Instrument und Wirksamkeitsdatum |
| event_components | Gebühren, Steuern und Bruttowerte mit eindeutiger Bedeutung und Positionsbezug |
| documents / event_documents | Dateihash, Originalname, Ablagebezug; n:m-Zuordnung zu Vorgängen samt Quellenbezug |
| event_references | Bankreferenzen mit geprüftem Gültigkeitsbereich |
| import_batches / import_documents | Übernahmeeinheit, Status, Zeitpunkte, Parser-Version und verarbeitete Dokumente |
| import_changes | Typisierte Herkunft von Erstellungen, Ergänzungen und Verknüpfungen; nötige Vorher-Werte und unterstützende Quellen |
| operation_requests | Wiederholungsschutz und kompakter Abschlussbericht |
| fixed_term_details | Bei Bedarf Beginn, Fälligkeit und vereinbarter Zinssatz |
| balance_points / balance_index_state | Abgeleitete kumulierte Bestände an Änderungstagen und gemeinsame Datenrevision |
| tax_scopes / tax_scope_accounts | Gemeinsamer steuerlicher Bank-/Inhaberbezug mit zugeordneten Konten/Depots |
| exemption_orders | Steuerbezug, Steuerjahr, erteilter Betrag, Gültigkeit und Revision; frühere Änderungen erhalten |
| allowance_evidence | Verbrauch/Rest/Auftrag laut Beleg, Art Einzeländerung oder kumulierter Stand, Steuerjahr, fachlicher Stichtag, Quellen-/Importbezug |
| schema_migrations | Kontrollierte Schema-Versionen |

Geldposition: genau ein Betrag in einer Währung. Mengenposition: genau eine Menge eines Instruments. CHECK-Regeln verhindern unzulässige Mischformen. Fremdschlüssel sichern Bezüge; keine Löschkaskade vom Dokument auf gemeinsam belegte Vorgänge.

Beispiel Kauf: +2 Stück, −201 EUR Geldposition, 200 EUR Handelswert und 1 EUR Gebühr als Erklärung. Die Gebühr wird nicht nochmals abgezogen. Ausschüttung: +8 EUR Geldposition, 10 EUR brutto und 2 EUR Steuer als Erklärung. Spätere tatsächliche Steuerzahlung/-erstattung ist ein eigener verknüpfter Geldfluss.

Zahlenentscheidung vor der ersten Migration: Decimal im Kern, persistentes Format nach kurzem Genauigkeits-/Abfragetest. Integer plus Skalierung mit Überlaufprüfung oder kanonische Decimal-Speicherung mit exakter Such-/Summenlogik. Kein SQLite REAL. Referenztest umfasst Kryptomengen mit mindestens 18 Nachkommastellen und große Bestände. API-Dezimalstrings bleiben unabhängig vom internen Format stabil.

Depots benötigen kein künstliches Verrechnungskonto; Giro kann Referenzkonto sein. Mehrwährungsgeldbestände werden als Geldkonten je Währung geführt. Ein Instrument kann in mehreren Bestandskonten vorkommen. Eröffnungen sind explizite Buchungen; fehlende Anschaffungskosten sind unbekannt. Ursprüngliche Anschaffungstranchen müssen bei Übertrag erhalten bleiben; zusätzliche Lot-Tabelle nur soweit für das gewählte Kostenverfahren erforderlich.

Keine PDF-Blobs, Volltexte, Textkoordinaten oder vollständigen Parserdumps im Buchungskern. Originaldateien separat; Originalbuchungstext und Referenzen bleiben gespeichert. Keine frei anlegbaren Benutzerfelder.

Fertig, wenn Kauf, Ausschüttung, Geldtransfer und Depotübertrag eindeutig mit exakten Werten gespeichert und wieder gelesen werden können.

## Schritt 4 – Einen Parser anbinden und Vorschau erzeugen

Tatsächlich verfügbare portman-parsers-API und Paketversion prüfen. Mit einem freigegebenen comdirect-Dokumenttyp beginnen. Der Adapter übersetzt Strukturen und ergänzt keine Bankextraktion. Unvollständige Konto-/Instrumentzuordnung wird sichtbar zurückgehalten.

Geprüfter Paketstand für die weitere Adapterarbeit ist `portman-parsers` 0.7.0
auf Commit `227eaafb4fb49e4357006546a0855ea7a0668c0a` im offenen PR gegen
`main`. API 0.6 und Ergebnisschema 1.6.0 bleiben unverändert.

Vorgesehene Auswahl bleibt comdirect, Baader/finanzen.zero, ING, Deka, FNZ/Finvesto, Renault, Bank of Scotland und generischer Dokument-Fallback. Freigabe je Dokumenttyp anhand echter Referenzen; keine Reifegradbehauptung aus der Auswahlliste. pbb direkt und Baader-Kryptowährungen bleiben ausgeschlossen. Generischer Fallback erzeugt ohne ausreichende Fakten keine Buchung.

Fertig, wenn Vorschauwerte unmittelbar mit dem Original vergleichbar sind und noch keine produktiven Buchungen entstanden sind.

## Schritt 5 – Übernahme und Dublettenabgleich

Drei Ebenen: identische Datei per SHA-256; sichere Bankreferenzen im richtigen Kontext; fachliche Vergleichskandidaten aus Konto, Art, Datum, Betrag/Währung, Instrument und Menge. Datum und Betrag allein genügen nie zum automatischen Zusammenführen.

Finanzreports zeilenweise behandeln: bekannte Vorgänge belegen, fehlende Angaben ergänzen, neue Bewegungen übernehmen. Steuerbemessungsgrundlage, Freistellungsverbrauch und Jahreskontrollsumme sind keine zusätzlichen Geldabgänge. MiFID-Kosteninformationen erzeugen keine Kostenbuchung.

Ergebnisse: neu, bereits vorhanden, Ergänzung, Prüfung nötig oder Fehler. Bestätigte Werte bei Konflikten nicht still überschreiben. Dateiablagе, Herkunft, Buchungen und Bestandsindex konsistent übernehmen. Dokumentdatei vor Commit sicher bereitstellen; verwaiste Dateien ausfallsicher bereinigen. Dubletten unmittelbar vor Commit nochmals prüfen.

Fertig, wenn erneuter Import keine zusätzliche Bewegung erzeugt, zwei echte gleichartige Käufe getrennt bleiben und ein zweiter Beleg denselben Vorgang ergänzen kann. Umgekehrte Importreihenfolge muss fachlich dasselbe Ergebnis liefern.

## Schritt 6 – Vollständige Import-Rücknahme

Einzeln, als Auswahl oder alle Importe. Vorschau zeigt Auswirkungen und notwendige Entscheidungen; danach eine klare Bestätigung. Rücknahme entfernt aktive Importwirkungen und ist kein Bankstorno mit künstlichen Gegenbuchungen.

- Beiträge des gewählten Imports entfernen; weiterhin anderweitig belegte Vorgänge erhalten.
- Ergänzungen mit Herkunft zurücknehmen, ohne spätere manuelle Werte zu überschreiben.
- Abhängige Transfers und Anschaffungsbezüge auflösen oder explizit als unvollständig kennzeichnen; Konflikte vor Commit lösbar machen.
- Nur ungenutzte, ausschließlich importierte Stammdaten entfernen. Manuelle und anderweitig verwendete Daten erhalten.
- Externe Originaldateien unverändert lassen. Unreferenzierte eigene Dokumentkopien nach Commit wiederanlaufbar bereinigen.
- „Alle Importe“ lässt manuelle Daten bestehen und ist kein Datenbank-Reset.
- Buchungen, Herkunft und persistenter Bestandsindex in einer Transaktion ändern; Such-/Speichercaches danach auf die neue Revision bringen.
- Erneuter Import zurückgenommener Dokumente ist möglich. Kleines Rücknahmeprotokoll darf erhalten bleiben.

Fertig, wenn auch Ergänzungsbelege, spätere manuelle Änderungen, gemeinsame Quellen und Abbrüche geprüft sind. Im isolierten Fall stellt Rücknahme exakt die ursprünglichen Geld- und Mengenbestände wieder her.

## Schritt 7 – Bestandsindex für sofortiges Blättern

Der Index wird von Anfang an als gezielte Beschleunigung eingeplant. Er enthält kumulierte Salden nur an Änderungstagen je Konto/Währung bzw. Konto/Instrument. Stichtagsabfrage sucht den letzten Punkt kleiner/gleich Datum. Tage ohne Bewegung erzeugen keinen eigenen Datensatz. Keine Tageskopien der vollständigen Datenbank.

Persistenter Index und Buchungen teilen eine Datenrevision und werden atomar aktualisiert. Rückdatierter Import, Korrektur oder Rücknahme berechnet pro betroffener Reihe nur den Abschnitt ab dem frühesten geänderten Wirksamkeitsdatum neu. Lang laufende Aufbereitung findet vor dem kurzen Commit statt; Revision beim Commit erneut prüfen.

Im laufenden Anwendungskern liegen kompakte sortierte Indexreihen im Speicher. Nach Commit wird ein konsistenter neuer Speicherstand veröffentlicht. Leseantworten enthalten eine Revision; keine Mischung alter Geldsalden mit neuen Mengen. Ein alter Oberflächen-Cache wird bei Revisionswechsel verworfen. Nach Neustart wird der persistente Index geladen; keine vollständige Neuberechnung aller Buchungen erforderlich.

Der Index lässt sich vollständig aus Buchungen rekonstruieren. Ein Reparatur-/Prüflauf vergleicht Summen und Revision; unvollständigen Index niemals als aktuellen Bestand ausgeben. Die Speichergröße wächst mit Änderungstagen, nicht mit jeder Kalendersekunde.

Fernzugriff verwendet eine gebündelte Stichtagsabfrage und kleinen Cache für benachbarte Stände. Ein ungesehener Stichtag kann Netzwerklatenz benötigen; „keine Wartezeit“ wird nicht als physikalische Garantie versprochen. Keine unbeschränkte Vorabübertragung aller Stände.

Fertig, wenn lokal bei geladener Übersicht Datumsklick bis konsistenter Anzeige im 95. Perzentil unter 50 ms liegt. Referenzlauf mindestens 100.000 Positionen, dokumentierte Hardware/Kontenzahl, Monats-/Jahressprünge und weit zurückdatierte Änderung prüfen. Kaltstart und Indexpflege separat messen. Keine blockierende GUI während der Aufbereitung. Weitere Optimierung nur nach Messung.

## Schritt 8 – Kleine Web-Testoberfläche

Zunächst serverseitig erzeugte Seiten, Standardkomponenten und dünner HTTP-Adapter. Kein großes Frontend-Framework, keine Chartbibliothek. Lokal betreiben; Fernzugriff erst mit Anmeldung und geeigneter Absicherung. Automatische Tests bleiben erforderlich.

Vier Bereiche: Kontenübersicht, Alle Buchungen, Import und Stammdaten. Import in drei Schritten: Dateien wählen → Ergebnis prüfen → Übernehmen. Eine primäre Aktion je Schritt, sichere Ergebnisse zusammenfassen, nur Probleme einzeln entscheiden. Details, Steuerbestandteile und technische Diagnose auf Anforderung. Tabellen und Texte kopierbar; klare Tastaturbedienung und Statusmeldungen.

Anzeigen: Datum, Konto/Depot, Art, Betrag/Währung, gegebenenfalls Instrument und Menge; Brutto/Netto/Gebühren/Steuern in Details; Originaltext und Dokumentzugriff; Importverlauf und Rücknahme. Währungen nie zusammenzählen. Fehlende Daten als unbekannt kennzeichnen.

Fertig, wenn ein Nutzer ohne technische Parserkenntnisse importieren, Beträge vergleichen, suchen und zurücknehmen kann. Gleiche Aufrufe laufen mit FakeService und echtem Service.

## Schritt 9 – Einfache Zeitnavigation in der Kontenübersicht

Eine Leiste: Zurück · Datum mit Kalender · Vor · Schrittweite · Heute. Schrittweiten Tag, Woche, Monat, Jahr und benutzerdefiniert, beispielsweise 10 Tage oder 3 Monate. Alle Konten verwenden denselben Stichtag; keine Dialoge beim Blättern.

Woche = sieben Kalendertage. Monat/Jahr = Kalenderschritt mit erhaltenem Tagesanker: 31. Januar → letzter Februartag → 31. März. Manuelle Datumswahl setzt den Anker neu. Entsprechend Schaltjahre behandeln.

Anzeige zum Tagesende. Geld verwendet Buchungsdatum; Mengen verwenden ausdrücklich festgelegtes Wirksamkeitsdatum, bei Handel grundsätzlich Handelsdatum soweit bekannt. Valuta wird nicht stillschweigend eingesetzt. Bei fehlender Anfangshistorie: „Bestand aus erfassten Buchungen“. Zukünftiges Datum ist keine Prognose und wird gekennzeichnet.

Schnelle Klicks zusammenfassen; letzte Auswahl zählt. Verspätete Antwort darf kein neueres Ergebnis überschreiben. Datum und Daten stets gemeinsam aktualisieren. Nachbarstände bei Fernzugriff vorladen; keine Finanzberechnungen in der View.

Fertig, wenn Monatsenden, Schaltjahre, bewegungslose Tage, Rücknahme alter Importe und schnelle Navigation korrekt und flüssig funktionieren.

## Schritt 10 – Suche, Betrieb und gemeinsame Abnahme

Suche über Originaltext, Verwendungszweck, Referenz, Dokumentname, Instrument, ISIN/WKN und Kontoname. Filter nach Konto, Zeitraum, Betrag/Bereich, Währung, Art und Status. Indexierte SQL-Abfragen und seitenweises Laden; FTS5 erst bei tatsächlichem Bedarf. Keine PDF-Volltextsuche im ersten Umfang. Ziel für erste Suchseite bei 100.000 Positionen: 95. Perzentil unter 300 ms auf dokumentierter Referenzhardware.

Migrationen versionieren, Fremdschlüssel aktivieren, einen koordinierten Schreibpfad verwenden. Konsistente Sicherung von SQLite und Dokumenten; bei offener Datenbank SQLite-Backupverfahren verwenden. Wiederherstellung tatsächlich testen. Jobs abbrechbar, Commit atomar; Netzwerkabbruch bedeutet nicht automatisch fehlgeschlagenen Commit.

| Prüffall | Erwartung |
|---|---|
| Kauf mit Gebühr | Geld und Menge korrekt, Gebühr einmal |
| Ausschüttung mit Steuer | Netto korrekt, Steuer einmal |
| Kaufabrechnung plus Finanzreport | Ein Vorgang, mehrere Belege |
| Steuerinformation ohne Geldbewegung | Kein zusätzlicher Geldabgang |
| Zwei echte identische Käufe | Zwei Vorgänge |
| Eigener Geld-/Depot-/Kryptotransfer | Interne Bewegung, Gebühren gesondert |
| Kleine Kryptomenge, Fremdwährung | Exakt und getrennt |
| Rücknahme einzeln/gesamt | Importwirkungen vollständig entfernt; unabhängige Daten erhalten |
| Timeout und wiederholte Anfrage | Genau eine Übernahme/Rücknahme |
| Alte Änderung und neuer Stichtag | Persistenter und Speicherindex korrekt und revisionsgleich |
| Deaktiviertes Konto | Historie bleibt suchbar |
| Backup/Wiederherstellung | Daten und Dokumente zusammen nutzbar |

Grundversion fertig: Referenzdokument → Vorschau → Übernahme → Betrags-/Bestandskontrolle → erneuter Import ohne Doppelzählung → Ergänzungsbeleg → Rücknahme → korrekter Ausgangsstand. Dazu schnelle Stichtagsnavigation, Suche und geprüfte Sicherung. Noch keine Kurse oder Performanceanalyse erforderlich.

## Ergänzung zu Schritten 2–10 – Freistellungsaufträge und Restbetrag

Diese Funktion gehört zur Grundversion, soweit die benötigten Steuerbelege durch portman-parsers unterstützt werden. Fehlen belegte Angaben, bleibt der Restbetrag ausdrücklich unbekannt. Keine eigene steuerliche Schätzlogik und kein V10-Parser.

### Zuordnung und Speicherung

Ein Freistellungsauftrag wird manuell im Bereich Stammdaten → Steuern gepflegt. Er gehört zu einem gemeinsamen steuerlichen Bank-/Inhaberbezug und einem Steuerjahr, nicht zu einem Wertpapier. Konten und Depots werden diesem Bezug zugeordnet. Gleicher Institutsname allein rechtfertigt keine Zusammenfassung; unterschiedliche Inhaber-/Gemeinschaftsbezüge müssen getrennt bleiben. Im ersten Schritt genügt eine einfache Bezeichnung mit Kontenauswahl, kein umfangreiches Personenverwaltungssystem.

Gespeichert werden erteilter Betrag, Steuerjahr und fachliche Gültigkeit. Änderungen innerhalb eines Jahres überschreiben nicht die historische Gültigkeit. Eine dauerhafte Vorgabe kann Folgejahre vorbelegen, wird aber nicht stillschweigend als bestätigter Auftrag übernommen.

Verbrauchsinformationen stammen aus Imports. Dokumentiert werden Betrag, Bedeutung (Verbrauch, Rest oder Auftrag laut Bank), Einzeländerung oder kumulierter Stand, Steuerjahr, fachlicher Stichtag und Quelle. Dokumentdatum und Verbrauchsstichtag sind getrennt. Werte ohne eindeutige Bedeutung bleiben zur Prüfung offen. Geldbeträge verwenden dasselbe exakte Format wie die Buchungen.

### Verbrauch ohne Doppelzählung

- Freistellungsverbrauch ist Steuerinformation und verändert keinen Geldsaldo.
- Ein kumulierter Bankstand ist bereits eine Summe; er wird nicht zu den enthaltenen Einzelwerten addiert.
- Die Übersicht nutzt einen eindeutigen belegten kumulierten Stand als Anker. Spätere Einzeländerungen werden nur ergänzt, wenn deren Abgrenzung und Vollständigkeit sicher sind. Andernfalls bleibt die Anzeige beim belegten Stand mit dessen Datum.
- Mehrere Dokumente über denselben Verbrauch unterstützen denselben Sachverhalt; keine Mehrfachzählung.
- Korrekturen und Verbrauchsminderungen sind möglich. Nicht pauschal das Maximum früherer Verbrauchswerte verwenden.
- Widersprüchliche Bankangaben werden als Konflikt angezeigt. Keine stille Auswahl allein nach Importreihenfolge.
- „Verfügbar“ wird aus dem für den angegebenen Quellenstand gültigen Auftrag minus bestätigtem Verbrauch berechnet oder als expliziter Bank-Restwert mit Quelle angezeigt. Widersprüche zwischen beiden Darstellungen bleiben sichtbar; keine doppelte Berechnung aus verschiedenen Grundlagen.
- Negative Differenzen werden als Inkonsistenz angezeigt, nicht still auf null begrenzt.

### Anzeige und Stichtag

In der Kontenübersicht erscheint auf Anforderung eine kompakte Steuerzeile: „Freistellungsauftrag [Jahr]: erteilt … · genutzt … · verfügbar … · Bankstand vom …“. Beispielwerte sind keine persönlichen Ist-Daten. Gemeinsam genutzte Aufträge heißen „gemeinsam für diese Konten/Depots“ und werden in Summen genau einmal pro Steuerbezug gezählt.

Die Zeitnavigation wählt das passende Steuerjahr und den zum Stichtag gültigen Auftrag. Es werden nur Verbrauchsbelege mit fachlichem Stichtag bis zum gewählten Datum verwendet. Ein später importierter Beleg für einen früheren fachlichen Stichtag darf die historische Sicht verbessern; dies ist keine Rekonstruktion dessen, was dem Programm damals bereits bekannt war. Falls kein exakter Tagesstand belegt ist, zeigt die Oberfläche den letzten belegten Stand und dessen Datum, nicht einen vermeintlich aktuellen Tageswert.

Ein historischer Vorjahresrest wird nicht ins neue Jahr addiert. Fehlt ein bestätigter Anfangs-/Verbrauchsstand, bedeutet das „Verbrauch/Rest unbekannt“ und nicht „alles frei“. Keine automatische Gleichsetzung von Ausschüttungsbrutto, steuerpflichtiger Bemessungsgrundlage und tatsächlichem Verbrauch. Eine Vorabpauschaleninformation kann Verbrauch belegen, ohne eine zusätzliche Geldbuchung auszulösen.

### Schnittstelle, Rücknahme und Geschwindigkeit

Die Anwendungsfälle save_exemption_order und get_tax_summary liefern Steuerbezug, Jahr, Auftrag, Verbrauch, Rest, fachlichen Quellenstand, Herkunft, Vollständigkeit und Konfliktstatus. Die Oberfläche berechnet den Rest nicht eigenständig. Kontenübersicht und Steuerdaten verwenden eine konsistente Datenrevision.

Importierte Steuerangaben erhalten dieselbe Herkunftsverwaltung wie andere Ergänzungen. Rücknahme entfernt nur die entsprechenden Beiträge und ermittelt den verbleibenden belegten Stand neu. Ein manuell gepflegter Auftrag bleibt bestehen. Gemeinsam belegte Informationen bleiben erhalten. Ein bankseitig gemeldeter Auftragsbetrag überschreibt die manuelle Vorgabe nicht ungeprüft.

Für schnelles Blättern reicht eine kompakte sortierte Reihe steuerlicher Änderungspunkte pro Bezug/Jahr im Anwendungskern. Sie wird bei relevanten Änderungen aktualisiert, bei Bedarf rekonstruiert und gemeinsam mit der Kontenübersicht abgefragt. Kein separates Steuerberechnungssystem und keine täglichen Steuerkopien.

### Abnahme

Gemeinsamer Auftrag für Giro und Depot; getrennte Inhaberbezüge derselben Bank; Auftragsänderung innerhalb des Jahres; Einzelverbrauch plus überlappender kumulierter Report; Korrektur mit sinkendem Verbrauch; fehlender Bankstand; widersprüchliche Angaben; Jahreswechsel; historisches Datum; Vorabpauschale ohne Geldbewegung; Rücknahme bei verbleibenden Quellen. Jede Änderung muss in Übersicht und Historie ohne Doppelzählung erscheinen.

## Späterer Ausbau – ausdrücklich nicht im ersten Lieferumfang

Weitere freigegebene Dokumenttypen/Parser nach Bedarf; endgültige Desktopoberfläche mit demselben Vertrag; zentrale Instanz auf PC/Heimserver; responsive Handyansicht. Die zentrale Instanz besitzt SQLite, Geräte greifen per API zu. Keine gemeinsam geöffnete SQLite-Datei im Netzwerkordner und keine Mehrgeräte-Offline-Synchronisation zum Start.

Danach Kurse, Wechselkurse, Marktwerte und erst nach geprüften Geldflüssen TWR/IRR. Chartbibliotheken erhalten Anzeigezeitreihen aus der Schnittstelle; Analysebibliotheken werden über kleine Adapter angebunden. Instrumentstammdaten und kontextbezogene Symbole bleiben getrennt von zeitabhängigem KGV mit Quelle und Berechnungsbasis. Kryptospezialvorgänge und Fundamentaldaten sind optionale Erweiterungen.

Frühere 206 unsichere Buchungskandidaten bleiben zurückgehaltener Prüfbestand; die zurückgestellten 10/33 Altfälle blockieren V10 nicht. Zahlen sind historische Hinweise und wurden für diesen Entwurf nicht erneut auditiert.

## Nächster konkreter Arbeitsschritt

Schritt 1–3 vorbereiten: tatsächliche Parser-API prüfen, DTOs/ApplicationService festlegen, vier Referenzvorgänge durchmodellieren und Zahlenformat einschließlich indexierter Bestandsrechnung messen. Erst dann die erste Migration und den ersten vollständigen Importweg implementieren. Oberfläche kann nach Freigabe des Vertrags mit Testdaten unabhängig entstehen.


## Ergänzung 6. November 2026 – jederzeit prüfbare Änderungen

Alle Kontobuchungen, insbesondere Girohistorien, erhalten kontinuierliches Scrollen mit automatischem Nachladen, Suche und kombinierbare Filter. Sortierung und Filter liegen im Datenzugriff, nicht im View. Gegenparteien sind nur bei erfassten Angaben durchsuchbar. Einzelzellen, Zeilen und alle gefilterten Treffer sind kopierbar, bei großen Treffermengen über eine eigene seitenübergreifende Kopieraktion statt nur der geladenen Zeilen.

Jeder abgeschlossene Arbeitsschritt bekommt einen reproduzierbaren Testweg: zunächst ein ausführbares Kernbeispiel, später einen einzigen lokalen Startbefehl für die Web-Testoberfläche mit Browseröffnung. Branch, Commit und Testdatenprofil sind sichtbar. Ein separater Testbestand schützt echte Daten. Pro Übergabe: neue Funktion, Ort, Schritte, Soll-Ergebnis, Stand und Einschränkungen.

Implementiert, automatisch geprüft und durch den Nutzer geprüft sind getrennte Zustände. Keine Nutzerfreigabe erfinden. Zwischenstände während der Entwicklung müssen nicht fertig sein; übergebene Prüfstände müssen startbar sein. Die Launcher für eine echte Webanwendung werden erst mit dieser Anwendung geliefert. Das beigefügte Vorbereitungspaket besitzt noch keinen Webserver und keine Importoberfläche.
