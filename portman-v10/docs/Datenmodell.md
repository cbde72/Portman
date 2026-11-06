# Logisches Datenmodell 0.1

Die versionierten SQLite-Migrationen 0001–0003 bilden einen Persistenzprototyp, aber keinen produktiv freigegebenen Gesamtservice. Migration 0003 ergänzt den Kontext von Instrumentkennungen und kennzeichnet Eröffnungen ausdrücklich als manuelle Startbestände; bereits versionierte Migrationen werden nicht nachträglich geändert.

| Entität | Schlüssel/Beziehungen und Inhalt |
|---|---|
| Konto | stabile ID; Geld-/Bestandskonto, Unterart, Institut, Währung bei Geldkonto, Referenzkonto optional, aktiv, Revision |
| Kontokennung | Konto-ID, Typ, Kontext, Kennung; kein globales UNIQUE auf Nummern |
| Instrument | stabile ID, Name, Anlageart; ISIN/WKN soweit vorhanden |
| Instrumentkennung | Instrument-ID, Anbieter/Börse/Netzwerk und Kennung |
| Eröffnungsbestand | eigener Vorgang und bestandswirksame Position am Stichtag; Herkunft `manual`, Umfang `starting_balance`; bei Mengen optional ein Anschaffungslot mit bekanntem oder unbekanntem Kostenstatus |
| Vorgang | ID, Typ, Datum, Originaltext, Revision, Vollständigkeit, Korrektur-/Stornobezug |
| Position | Vorgang-ID und Konto-ID; entweder Geld/Währung oder Menge/Instrument; Wirksamkeitsdatum |
| Betragskomponente | Positions-/Vorgangsbezug, Art, Betrag/Währung; erklärt Geldfluss, keine zweite Saldenwirkung |
| Dokument | ID, eindeutiger SHA-256, Originalname, relative Ablage |
| Vorgangsbeleg | n:m Vorgang–Dokument; Seite/Eintrag, Quellenrolle |
| Import | ID, Zeitpunkt, Status; n:m Dokumentverarbeitung mit Parser-/Schemaversion |
| Importbeitrag | Import-ID, Ziel/Feld, typisierte Erstellung/Ergänzung/Verknüpfung, Quellenunterstützung, nötiger Vorher-Wert |
| Operation | request_id, Eingabehash, Abschlussbericht; transaktionaler Wiederholungsschutz |
| Bestandsindex | Konto/Währung oder Konto/Instrument, Änderungstag, kumulierter Wert, gemeinsame Revision |
| Steuerbezug | Bank-/Inhaberbezug; n:m Konten, keine Gruppierung allein anhand Bankname |
| Freistellungsauftrag | Steuerbezug, Steuerjahr, Gültigkeit, Betrag, Revision; historische Änderungen erhalten |
| Verbrauchsbeleg | Einzeländerung oder kumulierter Stand, Stichtag, Steuerjahr, Betrag/Bedeutung, Importherkunft |
| Festgeld | Konto-ID, Beginn, Fälligkeit, vereinbarter Zinssatz |

CHECK: Geld-/Mengenfelder schließen sich gegenseitig aus. Fremdschlüssel aktiv. Keine Dokument-Löschkaskade auf gemeinsam belegte Vorgänge. Konten mit Historie deaktivieren. Keine JSON-Parserdumps oder Volltextarchive im Kern.

### V10-11: Stammdaten und Eröffnungsbestände

Konten werden über die bestehenden `AccountInput`-/`Account`-Verträge angelegt und mit erwarteter Revision geändert. Die Eingabe ist ein vollständiger Datensatzstand, kein PATCH: gewünschte Kennungen müssen bei einer Änderung vollständig übermittelt werden; eine leere Liste entfernt Kennungen. Erlaubt sind Geldkonten (`checking`, `savings`, `fixed_term`, `settlement`) mit Kontowährung und Bestandskonten (`depot`, `crypto`) ohne Kontowährung. Ein Referenzkonto muss ein Geldkonto sein; ein bereits referenziertes Geldkonto kann nicht in ein Bestandskonto umgewandelt werden. Historische Konten bleiben per Soft-Deaktivierung samt Bezügen auffindbar.

Instrumente erhalten stabile IDs; weder Name noch Ticker identifizieren ein Instrument allein. ISIN/WKN sind optionale Standardkennungen. Weitere Kennungen werden mit Anbieter, Typ, Kontext und Wert gespeichert. Migration 0003 führt das Kontextfeld ein; historische Kennungen erhalten die dokumentierten Platzhalterkontexte `standard` oder `unspecified`, bis sie gezielt belegt werden.

Eine manuelle Eröffnung speichert genau eine Geld- oder Mengenposition. Sie erzeugt keinen Kauf, keine frühere Erwerbshistorie und keine erfundene Gegenbuchung. Ein bekannter Anschaffungszeitpunkt und bekannte Kosten bleiben als Lot-Metadaten erhalten; unbekannte Kosten werden als SQL-NULL/`None` mit Status `unknown` gespeichert. Stichtag und `source_kind="manual"` sowie `history_scope="starting_balance"` kennzeichnen Herkunft und Bedeutung.

Stammdaten- und Buchungsschreibvorgänge erhöhen `app_state.data_revision` transaktional. Der SQLiteStore pflegt den Bestandsindex noch nicht inkrementell. Bei Buchungs- und Eröffnungsänderungen bleiben Indexzeilen auf ihrer vorherigen Revision; sie sind damit ungültig und dürfen nicht als aktueller Bestand ausgegeben werden. Es existiert hier kein produktiver Stichtagslesepfad, der solche Zeilen ausliefert. Vollständige Indexpflege und Rücknahme bleiben offen.

## Vier Referenzfälle

`Positionen` sind die einzigen bestandswirksamen Werte. `Betragskomponenten` (Brutto, Steuer, Handelswert, Gebühr) erklären diese Positionen, erzeugen aber keine zweite Bewegung. Beträge und Mengen sind vorzeichenbehaftete Dezimalwerte; fehlende Angaben sind `unknown`/`None`, nie ein stilles `0`.

| Fall | Pflichtangaben und Positionen | Betragsdetails, Zuordnung und Sollbestand |
|---|---|---|
| Kauf | Instrument, Depot, Stückzahl, Geldkonto, tatsächlicher Geldabgang und Währung. Depotposition `+2 Stück`; Geldposition `−201 EUR`. | Handelswert `200 EUR`, Gebühr `1 EUR` erklären zusammen denselben Geldabgang. Konto und Instrument sind explizit zugeordnet; Gebühr ist keine zusätzliche Position. Bei Start Depot `5`, Geld `1.000 EUR`: danach Depot `7`, Geld `799 EUR`. |
| Ausschüttung | Empfängerkonto, Währung und tatsächlich gutgeschriebener Nettobetrag `+8 EUR`. | Brutto `10 EUR`, Steuer `2 EUR` sind Details, nicht weitere Bewegungen; `10 − 2 = 8`. Bei Start `100 EUR`: danach `108 EUR`. Wertstellungs-/Buchungstag steuert den Geldbestand. |
| Eigener Geldtransfer | Zwei eigene, zugeordnete Geldkonten gleicher Währung und bestätigte Beträge `−100 EUR`/`+100 EUR`. | Ein Transfer mit zwei Positionen. Giro `1.000 EUR` und Tagesgeld `250 EUR` werden zu `900 EUR` und `350 EUR`; die Summe bleibt `1.250 EUR`, externer Zufluss `0 EUR`. |
| Depotübertrag | Eigenes Quell-/Zieldepot, Instrument, übertragene Menge `2 Stück` und bestätigte Seite(n). | Quellposition `−2`, Zielposition `+2`; die Anschaffungstranchen wechseln unverändert mit. Start Depot A `8`, Depot B `1`: danach `6` und `3`. Einstandskosten und ursprüngliche Erwerbsdaten sind Lot-Metadaten, keine neue Geldbewegung. |

### Pflicht, optionale und unbekannte Angaben

- Kauf: Instrument, Depot, Menge und belegte Geldposition mit Währung sind für einen vollständigen Fall Pflicht. Handelsdatum steuert die Mengenposition; Bank-Wertstellung/gebuchter Tag steuert die Geldposition. Handelswert und Gebühr sind optionale, jeweils separat belegte Details, hier beide bekannt. Fehlt ein Detail, bleibt es unbekannt; aus einem Geldabgang wird keine Gebühr erraten.
- Ausschüttung: Empfängerkonto, Währung, tatsächlich belegter Nettogeldfluss und dessen Wertstellung sind Pflicht. Das ausschüttende Instrument wird zugeordnet, wenn der Beleg es identifiziert; sonst bleibt es unbekannt. Brutto, Abzüge/Steuern, Ex-Tag und Zahltag sind optionale Fakten; bekannte Brutto-/Steuerwerte dürfen den Nettoposten erklären, aber nie zusätzlich saldiert werden. Ein unbekannter Steuerwert ist nicht `0`. Eine Jahres-/Steuerbescheinigung ergänzt Evidenz, erzeugt keine weitere Ausschüttung.
- Eigener Transfer: beide eigenen Konten, Währung und jeder tatsächlich bestätigte Beinbetrag sind Pflicht für einen vollständigen Transfer. Wertstellung je Bein bleibt erhalten; abweichende Tage ändern die Zusammengehörigkeit nicht. Referenz, Verwendungszweck und Gebühren sind optionale Details. Eine nur bestätigte Seite ist ein unvollständiger Transfer: fehlende Gegenbuchung bleibt unbekannt und wird nicht als null oder angenommene Gegenseite gespeichert.
- Depotübertrag: Instrument, Quell-/Zieldepot, bestätigte Stückzahl und Buchungstag je bestätigter Seite sind Pflicht für den jeweils bekannten Beinposten. Anschaffungsdatum, Menge und historische Gesamtkosten je Lot werden unverändert mitgeführt, soweit belegt. Fehlende Gegenseite erzeugt keinen Gegenposten; unbekannte Anschaffungskosten bleiben `None`, nicht `0 EUR`. Kostenwährung und Referenzen sind optional, sofern belegt.

### Belege, Importreihenfolge und Rücknahme

Jeder Importbeitrag stützt gezielt Fakten/Positionen und bleibt mit Import-ID, Dokument und Herkunft verknüpft. Belege werden als Evidenz an denselben wirtschaftlichen Vorgang angehängt, nie als Anlass für eine zweite identische Position. Die Testdaten enthalten für jeden Fall einen primären Beleg plus Bestätigungsbeleg. Ein zweiter Beleg, der nur einen bestehenden Vorgang bestätigt, fügt ausschließlich Evidenz hinzu. Zusammenführen muss kommutativ sein: dieselben Belege in anderer Importreihenfolge ergeben dieselben Positionen, Komponenten und Lots.

Rücknahme entfernt nur die Beiträge der ausgewählten Import-ID. Eine Position/Fakt bleibt erhalten, wenn ein verbleibender Beleg denselben Fakt stützt; andernfalls wird er unbekannt bzw. der zugehörige Importbeitrag entfernt. Ein Vorgang mit verbleibender Evidenz bleibt bestehen. Manuelle Änderungen haben eigene Herkunft und bleiben bei Rücknahme älterer Importe erhalten. Das gilt auch für Ergänzungen an Kosten, Kontenzuordnung und Text; ein alter Vorher-Wert darf sie nicht zurücksetzen.

Zusatzfälle, ebenfalls synthetisch getestet:

- Eine tatsächlich belastete Transfergebühr von `1 EUR` ist eine zusätzliche Geldposition `−1 EUR` auf dem belasteten Konto, mit optionalem Gebühren-Detail als Erklärung. Bei Start Giro `1.000 EUR`/Tagesgeld `250 EUR` und später gebuchter Gebühr beträgt der Endstand Giro `899 EUR`/Tagesgeld `350 EUR` (Gesamt `1.249 EUR`). Die kombinierte Wirkung ist Giro `−101 EUR`, Tagesgeld `+100 EUR`; die Gebühr wird als eigener verknüpfter Geldvorgang mit eigenem Wertstellungstag geführt.
- Zwei übertragene Lots bleiben getrennt: je `1 Stück`, Anschaffungsdaten `2023-02-03` und `2024-06-17`, historische Gesamtkosten `40 EUR` und `60 EUR`. Menge, Datum, Kosten und Kostenwährung werden nicht neu datiert oder neu bewertet.
- Ein Übertragsbeleg mit nur Depot-A-Abgang `−2 Stück` bucht nur diese bestätigte Seite und kennzeichnet den Vorgang unvollständig. Bei bekanntem Depot-A-Bestand `8` wird daraus `6`; ein bekannter Depot-B-Bestand `1` bleibt `1`. Der Gegenposten für Depot B bleibt unbekannt (nicht `0`); ein Depotbestand wird nicht durch das Fehlen dieses Belegs überschrieben. Fehlende Anschaffungskosten bleiben unbekannt.
- Ein zweiter Beleg zur Bestätigung eines vorhandenen Kaufs erzeugt null zusätzliche Geld-/Mengenpositionen. Entfernt man den Import, der den Vorgang angelegt hat, bleibt er erhalten, wenn der verbleibende Beleg dieselben Felder stützt.
- Eine tatsächliche spätere Steuererstattung (Testbetrag `+0,40 EUR`) ist ein neuer Geldvorgang am späteren Wertstellungstag, verknüpft mit der Ausschüttung. Bei Start `100 EUR` ergeben Nettozahlung `+8 EUR` und Erstattung `+0,40 EUR` den Endstand `108,40 EUR`; die Erstattung ändert die ursprüngliche Nettozahlung nicht rückwirkend.

### Teilüberträge und Anschaffungskosten

Die belegten Anschaffungstranchen bestimmen die Zuordnung eines Teilübertrags. Eine Tranche wird nur dann geteilt, wenn der Beleg sie eindeutig identifiziert; es gibt keine stillschweigende FIFO- oder Durchschnittskostenannahme. Innerhalb der bekannten Tranche werden die Anschaffungskosten proportional zur übertragenen Menge aufgeteilt. Das ursprüngliche Anschaffungsdatum und die Kostenwährung bleiben für übertragene und verbleibende Anteile erhalten. Für jede Tranche gilt exakt: übertragene Menge plus Restmenge = ursprüngliche Menge und übertragene Kosten plus Restkosten = ursprüngliche Kosten.

Beispiel: Von einer Tranche mit `10 Stück` und `103 EUR` historischen Gesamtkosten werden `3 Stück` übertragen. Der Anteil beträgt `103 × 3 / 10 = 30,90 EUR`; im Quelldepot bleiben `7 Stück` und `72,10 EUR`. Bei mehreren Tranchen wird diese Berechnung je ausdrücklich zugeordneter Tranche durchgeführt, nicht über deren Gesamtdurchschnitt.

Alle Zwischenwerte werden ohne Float berechnet. Jeder Teil wird exakt proportional von der aktuellen Resttranche abgezogen; Restkosten sind ursprüngliche Kosten minus Summe aller exakten Teilanteile. Vollständige Auslieferung ergibt exakt die ursprünglichen Gesamtkosten, Rücknahme entfernt die zugehörigen Beiträge und rekonstruiert die vorherige Tranche. Es gibt keine Cent-Restzuweisung auf die letzte Tranche.

Ist die Tranche nicht eindeutig belegt, bleiben übertragene und verbleibende Kostenbasis unbekannt, auch wenn die Depotmenge bekannt ist. Vollständige Rücknahme eines Teilübertrags stellt die ursprünglichen Mengen und Kosten je Tranche wieder her; unabhängige spätere manuelle Änderungen bleiben davon unberührt.

## Bestandsindex

Nur Änderungstage speichern, kumulierte exakte Werte. Rückdatierte Änderung aktualisiert betroffene Reihen ab frühestem geändertem Datum. Persistenz im selben Commit wie Buchungen; Speicherstand mit identischer Revision veröffentlichen. Stichtag per binärer Suche. Rekonstruierbar, kein eigener fachlicher Bestand. Kaltstart lädt Index; keine Summierung aller Buchungen pro Klick. Ziel: p95 unter 50 ms lokal warm; Messung mit 100.000 Positionen. Fernzugriff benötigt kleinen Nachbarcache und gebündelte Aufrufe.

Die V10-09-Migration enthält `balance_index` mit eindeutiger (Konto, Währung/Instrument, Stichtag)-Identität, exakter Dezimal- bzw. rationaler Wertspalte, Vollständigkeit und `data_revision`. `put_balance_index()` akzeptiert nur die in `app_state` aktuell veröffentlichte Revision. Das ist kein Nachweis, dass Buchungen und Index bereits atomar gemeinsam gepflegt oder alle Indexzeilen revisionsgleich gehalten werden; dafür fehlt der vollständige Anwendungs-/Indexservice. Die bestehende Testinfrastruktur initialisiert für jede Prüfdatenbank eine isolierte gemeinsame Revision.

## Freistellung

Auftrag manuell; Verbrauch importiert. Kumulierte Stände und enthaltene Einzelverbräuche nicht addieren. Korrekturen können Verbrauch senken. Fehlend ist unbekannt. Rücknahme entfernt nur Importbeiträge. Quellenstichtag sichtbar. Keine Steuerrechtsberechnung und keine zusätzliche Geldbuchung für reinen Freistellungsverbrauch.

## Exakte Zahlenrepräsentation (V10-05)

Die Rechenregel ist entschieden; die erste SQLite-Migration setzt sie als Prototyp um, noch ohne produktive Freigabe:

- **Belegte Originalbeträge und -mengen:** kanonische endliche Dezimalstrings ohne Exponent und ohne feste Stellenbegrenzung, z. B. `0.000000000000000001` oder `1000000000000000000000000000000`. Kanonisierung entfernt nur numerisch redundante Nullen; Beleg und Originaltext bleiben als Herkunft erhalten. SQLite `REAL` und Float sind ausgeschlossen.
- **Intern berechnete Kostenanteile:** normalisierte rationale Werte `Zähler/Nenner` mit beliebig großen Ganzzahlen und positivem, gekürztem Nenner, z. B. `100/3`. Persistenzkandidat ist ein kanonischer TEXT-Wert `num/den`, nicht SQLite-INTEGER. `RationalAmount` implementiert eine unabhängige Integer-Rechenvariante. Die vorhandenen Golden-Referenzen verwenden Python `Fraction` als unabhängigen Vergleichsmaßstab und bestimmen nicht selbst das Speicherformat.
- **Summen und Teilüberträge:** Original-Dezimalwerte werden verlustfrei in rationale Rechenwerte überführt. Der Anteil je Tranche ist `Kosten × übertragene_Menge / aktuelle_Menge`; Restkosten ergeben sich exakt als Originalkosten minus alle übertragenen Anteile. Wiederholte Teilungen, vollständige Auslieferung und Rücknahme erhalten Menge und Gesamtkosten exakt. Es wird keine Rest-Cent-Zuweisung vorgenommen.
- **Suche und Bereichsfilter:** Originalwerte nutzen die indizierte `PORTMAN_DECIMAL`-Collation; berechnete rationale Werte die `PORTMAN_RATIONAL`-Collation mit exaktem Kreuzproduktvergleich. Jede Datenbankverbindung muss die jeweilige Collation registrieren. Tests belegen die Indexnutzung für Gleichheit und Bereich.
- **Gerundete Anzeige:** erst am Darstellungsrand, nach sämtlichen Berechnungen. Fiatbeträge werden auf die Minor-Unit der Währung mit `ROUND_HALF_UP` gerundet (`EUR`: zwei Stellen); Mengen werden exakt angezeigt. Gerundete rationale Teilkosten sind als Näherung zu kennzeichnen. Summen werden aus exakten Grundwerten addiert und einmal gerundet, nicht aus angezeigten Einzelwerten. So können drei Anzeigen `≈0,33 EUR` zusammen `0,99 EUR` ergeben, während der exakte Gesamtwert `1/1 EUR` als `1,00 EUR` erscheint.

### Variantenvergleich mit 100.000 Positionen

Ausführbar in PowerShell mit `$env:PYTHONPATH='src'; .venv\Scripts\python.exe scripts\compare_number_variants.py`. Das Skript baut temporäre SQLite-Dateien samt Index, prüft verlustfreie Abfragen und identische exakte Summen. Datensatz: 100.000 nichtnegative kanonische Beträge mit sechs Nachkommastellen; Bereich ab Position 50.000, Gleichheitssuche nach Position 54.321. Abfragezeit ist Median aus neun Läufen. SQLite-Dateigröße umfasst Tabelle und Index. Aufbauzeit enthält Tabellenerstellung, Index und Inserts; Summenzeit ist eine einzelne exakte Summenberechnung. Keine RAM-Peak-Messung.

Umgebung: Python 3.14.3, SQLite 3.50.4, Intel Core i5-9300H @ 2.40 GHz, 8.45 GB RAM. Laufzeiten in Millisekunden, Speicher in Byte:

| Variante | Präzisionsgrenze/Randfall | Aufbau + Index | Gleichheit | Bereich | Summe 100k | SQLite-Datei |
|---|---|---:|---:|---:|---:|---:|
| Dezimal-TEXT + Collation | verlustfrei für kleine Kryptomengen/große Bestände; `100/3` nicht endlich dezimal | 6.175,35 | 0,1413 | 0,6723 | 157,99 | 4.333.568 |
| SQLite-INTEGER, Skala `10^6` | klein/schnell im Bereich; lehnt 18 Stellen ab, `10^30` überläuft | 205,54 | 0,0735 | 0,6255 | 61,11 | 3.076.096 |
| Rationale `num/den`-TEXT + Collation | exakt auch für `100/3`; größeres Indexformat, langsamere Summen | 4.014,65 | 0,1062 | 0,7259 | 537,12 | 5.619.712 |

Die Messung enthält keinen RAM-Peak und ist kein allgemeiner Performance-Freigabenachweis. Sie modelliert eine lokale synthetische Verteilung; Kaltstart, Kontenfilter und Bestandsindex sind nicht enthalten. Feste INTEGER-Skalierung ist im homogenen Test rund 29 % kleiner und bei Suche/Summe schneller, erfüllt aber nicht gleichzeitig Kryptopräzision und große Bestände. Rationale Speicherung ist gegenüber Dezimal-TEXT rund 30 % größer, bleibt im Bereichsfilter unter 1 ms und hält nicht terminierende Kostenanteile exakt. Daher gilt der **Hybrid**: belegte Werte als kanonischer Dezimal-TEXT, berechnete Kostenanteile als normalisiertes rationales `num/den`-TEXT. Rationale Werte sind weniger häufig als gebuchte Positionen.

Das ursprüngliche Variantenbenchmark ist kein p95-Freigabenachweis für Stichtagsblättern. V10-09 ergänzt ein versioniertes Schema, aber noch keinen produktiven Speicher-/Stichtagsservice.

## Weitere offene Freigabepunkte

V10-09 speichert ursprüngliche Anschaffungslots und rationale Zuordnungsanteile in `acquisition_lots`/`lot_allocations`. Die Datenbank prüft positive Mengen, Quellkonto, Instrument und Belegreferenzen; sie prüft noch keine kumulierte Restmengen-/Kostenerhaltung über mehrere Allokationen. Rücknahme einzelner Beiträge und manuelle Folgeänderungen sind strukturell nachvollziehbar, aber nicht ausführbar implementiert. `operations` trägt eindeutige request_id und Eingabehash; dauerhafte Replaylogik ist nicht implementiert. Indexzeilen müssen die aktuelle gemeinsame Revisionsnummer tragen; deren atomare Aktualisierung gemeinsam mit Buchungen wird noch nicht garantiert. Widersprüchliche Belege zu Kosten bleiben prüfpflichtig. Vollständiger Parservertrag und echte Dokumenttypen vor produktiver Implementierung verifizieren.

## SQLite-Schema (V10-09, V10-12/13)

`src/portman_v10/infrastructure/migrations/0001_initial.sql` definiert die versionierte Initialstruktur (SQLite mindestens 3.37 für STRICT-Tabellen); V10-11 ergänzt 0003 und die Importablage/-jobs 0004, ohne bereits versionierte Migrationen zu verändern. `SQLiteStore.migrate()` wendet DDL und Prüfsumme in einer Transaktion an, verweigert nachträglich geänderte Migrationen und ist beim erneuten Aufruf wirkungslos. Die Tabellen enthalten Konten/Kennungen, Instrumente, Vorgänge, gegenseitig ausschließende Geld-/Mengenpositionen, Lots/Allokationen, nicht bestandswirksame Komponenten, gemeinsam verknüpfte Dokumente, Importe, Feldbeiträge und Operationsschlüssel, Bestandsindex, Festgeld, Steuerbezug, Auftragshistorie und Verbrauchsquellen. 0004 ergänzt dauerhafte Job-/Dokumentstatus, normalisierte Vorschau-DTOs und revisionierte manuelle Prüfentscheidungen; sie speichert keinen beliebigen Parserdump.

Finanzwerte bleiben kanonisches Dezimal-TEXT; intern berechnete Lotkosten bleiben normalisiertes rationales `num/den`-TEXT. Jede `SQLiteStore`-Verbindung registriert die V10-05-Collations und deterministische CHECK-Funktionen. Es gibt keinen REAL-/Float-Pfad. `save_event()` zeigt atomare Speicherung synthetischer Vorgänge/Positionen/Quellen; das ist kein vollständiger Importservice. Der Importworkflow speichert Bytes unter intern generierten SHA-256-Pfaden in `documents/`, nach atomarer Bereitstellung und vor Metadatenregistrierung; Browser-/Transport-DTOs erhalten nie Dateipfade. Vorschauen speichern nur V10-normalisierte Fakten, Quellexzerpte, Warnungen und Versionsangaben. Der SHA-256-Abgleich verhindert nur eine zweite physische Kopie identischen Inhalts, nicht fachliche Duplikate oder doppelte Importläufe.

`ImportWorkflow` verwendet einen begrenzten Threadpool und öffnet für jeden SQLite-Zugriff eine eigene Verbindung. Fortschritt zählt abgeschlossene Dokumente. Parseraufrufe selbst können nicht sicher unterbrochen werden; ein währenddessen angeforderter Abbruch verwirft deren Ergebnis nach Rückkehr. Jobs im Zustand `queued`/`running` werden beim Neustart als `JOB_INTERRUPTED` fehlgeschlagen markiert; es gibt keinen automatischen Wiederanlauf. Prüfentscheidungen speichern erwartete Vorschau- und Kandidatenrevision sowie Entscheidung getrennt vom Parserfakt.

Der erste vollständige Buchungsvorschauweg verarbeitet nur comdirect `wertpapierkauf` (Handler `user.comdirect-ertraege`, Plugin-Version 2.0, Paket 0.7.0, API 0.6, Ergebnisschema 1.6.0) mit dem im Ergebnis gespeicherten Textaufbereitungsstand. Genau ein explizit beschränkter zweiter Handler, comdirect MiFID-II-Kosteninformation, wird nur als Information ohne Buchungskandidat ausgegeben. Alle weiteren Handler einschließlich comdirect Verkauf bleiben auf V10-Seite `unsupported`, auch wenn die Parserbibliothek sie ausführen könnte. Tatsächliche Geld-/Mengenbewegungen stammen nur aus `CashMovement`/`SecurityMovement`; Gebühren, Steuern und Trade-Kennzahlen sind getrennte Details ohne zusätzliche Wirkung. Zuordnungen erfolgen nur bei eindeutiger exakter Kennung; gleichnamige Symbole werden nicht verwendet. `disposition="unclassified"` lässt eine Kandidaten-Dublette ausdrücklich offen. Keine Preview erzeugt Ereignisse/Positionen. Reine Steuerinformations- und Snapshotdokumente ohne tatsächliche Geld-/Mengenbewegung werden als Information, nicht als Buchungskandidat, angezeigt.

Parserintegration, Ablage und Jobstatus sind mit synthetischen temporären Dateien/-datenbanken getestet. Keine autorisierten realen comdirect PDFs lagen für diese Prüfung vor. Der bekannte PDFium-Test mit beschädigten Baader-PDFs ist nicht Bestandteil dieser Integration; ein synthetischer comdirect-PDF-Test ist kein Nachweis für Baader-/PDFium- oder historische Layoutqualität. Persistenter Replay, Importcommit, Dublettenabgleich und Beitragsrücknahme bleiben späteren Aufgaben vorbehalten.
