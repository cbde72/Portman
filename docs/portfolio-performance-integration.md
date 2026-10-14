# Portfolio-Performance-Konzepte für PortmanNL

Stand: 11.10.2026

## Entscheidung

Portfolio Performance (PP) wird nicht als Java-Komponente eingebettet. PortmanNL übernimmt ausgewählte
fachliche Konzepte in eigener Python-Implementierung und ergänzt später einen dateibasierten Austausch.
Das hält die bestehende SQLite-Datenhaltung, die Importbelege und die nachvollziehbaren Korrekturen
von PortmanNL zusammen.

PP steht unter EPL-1.0. Übernommener Quellcode müsste als abgeleitete EPL-Komponente sauber getrennt
und mit Lizenzhinweisen ausgeliefert werden. Eine unabhängige Implementierung öffentlich beschriebener
Finanzmethoden und des dokumentierten XML-Austauschs vermeidet diese Kopplung.

Quellen:

- https://github.com/portfolio-performance/portfolio
- https://help.portfolio-performance.info/en/getting-started/measure-performance/
- https://help.portfolio-performance.info/en/reference/file/save/
- https://help.portfolio-performance.info/en/reference/file/export/
- https://help.portfolio-performance.info/en/reference/view/taxonomies/

## Abgleich

| Bereich | Portfolio Performance | PortmanNL heute | Empfehlung |
|---|---|---|---|
| Geldgewichtete Rendite | IRR | XIRR vorhanden | Behalten und mit Zahlungsstrom-Nachweis anzeigen |
| Zeitgewichtete Rendite | tägliche TTWROR | verketteter Modified-Dietz aus Depotbewertungen | Täglicher Bewertungsindex umgesetzt; Modified-Dietz als Näherung gekennzeichnet. Echte TTWROR mit taggenauer Neutralisierung externer Flüsse bleibt Aufgabe |
| Ergebnisüberleitung | Anfang, Zuflüsse, Erträge, Kursgewinne, Gebühren, Steuern, Ende | Gewinn, Nettozuflüsse, Dividenden, Gebühren, Steuern | Vollständig abstimmbare Überleitung je Depot und Position ergänzen |
| Risiko | Volatilität, Semivolatilität, maximaler und längster Drawdown | Volatilität und Drawdown nur je Kursreihe | Volatilität und maximaler Drawdown aus täglichem Index ergänzt; Semivolatilität, aktueller Drawdown und längste Drawdown-Dauer offen |
| Gewinne | realisiert/unrealisiert, FIFO oder gleitender Durchschnitt | Einstand und Wertänderung, teilweise FIFO | Lots als eigene, neu berechenbare Projektion einführen |
| Vergleich | Benchmarks und Datenreihen | kein persistenter Benchmark | Benchmark-Definitionen und Vergleichsindex ergänzen |
| Klassifikation | frei definierbare, gewichtete Taxonomien | Anlageklasse, Region, Cap als feste Felder | Hierarchische Taxonomien mit prozentualer Mehrfachzuordnung ergänzen |
| Kurse | mehrere Feeds, historische Kurse, FX | mehrere Provider, Kursarchiv, FX und Herkunft bereits vorhanden | Providervertrag vereinheitlichen; Lücken- und Qualitätsstatus ausbauen |
| Datenhaltung | eine XML-/Binärdatei; intern skalierte Ganzzahlen | SQLite, Dezimalwerte als Text, Originalimporte, Audit und Backups | SQLite beibehalten; berechnete Reihen als löschbaren Cache behandeln |
| Austausch | PP-XML und CSV | Portman-Pakete und Kontoexport | PP-XML zunächst lesend, später kontrolliert schreibend unterstützen |

## Ziel-Datenmodell

Die kanonischen Daten bleiben Konten, Wertpapiere, Buchungen, Bestände, Kurse und FX-Belege. Kennzahlen
werden daraus berechnet und dürfen jederzeit neu aufgebaut werden.

Neue Tabellen in einer späteren Migration:

```sql
CREATE TABLE benchmarks(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  security_key TEXT,
  provider TEXT NOT NULL,
  symbol TEXT NOT NULL,
  currency TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE taxonomies(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE taxonomy_nodes(
  id INTEGER PRIMARY KEY,
  taxonomy_id INTEGER NOT NULL REFERENCES taxonomies(id) ON DELETE CASCADE,
  parent_id INTEGER REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  target_weight TEXT
);

CREATE TABLE taxonomy_assignments(
  node_id INTEGER NOT NULL REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
  asset_uuid TEXT NOT NULL REFERENCES asset_identity(uuid),
  weight TEXT NOT NULL,
  PRIMARY KEY(node_id, asset_uuid)
);

CREATE TABLE analytics_cache(
  cache_key TEXT PRIMARY KEY,
  source_revision INTEGER NOT NULL,
  methodology_version INTEGER NOT NULL,
  payload TEXT NOT NULL,
  calculated_at TEXT NOT NULL
);
```

Geldwerte, Kurse, Stückzahlen und Gewichte bleiben kanonische Dezimaltexte. Binäre Fließkommazahlen
werden nur für Diagrammdarstellung und statistische Zwischenrechnungen verwendet. Jeder Cache-Schlüssel
enthält Portfolio, Kontenauswahl, Zeitraum, Berichtswährung und Methodenversion. Eine Änderung an
Buchungen, Kursen, FX oder Zuordnungen macht den Cache ungültig.

## Kennzahlen

### Priorität 1

1. (umgesetzt) Täglicher Portfolioindex für jeden Kalendertag. Zwischen Bewertungstagen wird die
   Teilperiodenrendite geometrisch verteilt; bewertet wird weiterhin an den vorhandenen Ständen.
2. Echte TTWROR durch Neutralisierung externer Zu- und Abflüsse am jeweiligen Tag.
3. XIRR mit derselben, sichtbaren Zahlungsstromliste.
4. Abstimmung: Anfangswert + externe Flüsse + Erträge + realisierte/unrealisierte Kurs- und
   Währungseffekte - Gebühren - Steuern = Endwert.
5. Datenqualitätsstatus je Ergebnis: vollständig, geschätzt, veraltet oder nicht berechenbar.

### Priorität 2

- (umgesetzt) annualisierte Volatilität aus dem täglichen Index; Semivolatilität offen
- (umgesetzt) maximaler Drawdown aus dem täglichen Index; aktueller Drawdown und längste
  Drawdown-Dauer offen
- beste/schlechteste Periode, Monats- und Jahresrenditen
- Benchmark-Rendite, aktive Rendite und Tracking Error
- Ausschüttungsrendite auf Einstand und auf Marktwert

Sharpe- und Sortino-Ratio werden erst ergänzt, wenn eine belegte risikofreie Vergleichsreihe
konfigurierbar ist. Ohne diese Reihe würde PortmanNL eine scheinpräzise Kennzahl anzeigen.

## Finanzdaten

Das vorhandene Provider-System bleibt die Grundlage. Jeder Provider liefert künftig denselben Vertrag:

- Wertpapieridentität und Listing (ISIN, Symbol, MIC, Währung)
- Tageskurse mit Angabe `close` oder `adjusted_close`
- Dividenden und Splits als getrennte Ereignisse
- Abrufzeit, Quell-URL, Status und Fehlermeldung
- Abdeckungszeitraum und erkannte Lücken

Kursreihen werden pro Provider und Listing getrennt gespeichert. Ein Providerwechsel überschreibt keine
alten Daten. Für Berechnungen wird eine explizite Prioritätsregel verwendet. Adjustierte und unadjustierte
Kurse dürfen nicht unbemerkt in derselben Renditereihe gemischt werden.

Sinnvolle Ergänzungen aus dem PP-Umfeld sind Eurostat-HVPI als Inflationsbenchmark und EZB-FX-Reihen.
Kursanbieter mit Zugangsschlüsseln bleiben optional; Schlüssel gehören weiterhin in den geschützten
Credential Store und nie in Exportdateien oder Protokolle.

## PP-Datenhaltung und Import

### Tatsächliche Dateiformate

Eine PP-Datei ist kein stabiles, veröffentlichtes XML-Schema. Der aktuelle Quellstand kennt XML mit
relativen XStream-Verweisen, XML mit ID-Verweisen, ein binäres Protobuf-Format sowie ZIP-Komprimierung
und Verschlüsselung. Das XML trägt eine Modellversion; der untersuchte Quellstand verwendet Version 70.
Ältere Dateien können UUIDs noch nicht enthalten. Ein Importer darf deshalb weder eine feste XML-Struktur
noch immer vorhandene IDs voraussetzen.

PortmanNL unterstützt in der ersten Stufe unverschlüsseltes XML und ZIP-komprimiertes XML. Binäre
`.portfolio`-Dateien und verschlüsselte Dateien werden eindeutig erkannt und mit dem Hinweis abgewiesen,
die Datei in PP als XML zu speichern. Das vermeidet eine unvollständige Nachbildung des proprietären
Serialisierungs- und Verschlüsselungspfads.

Der aktuelle PP-Quellcode skaliert Geldwerte mit 100, Kurse mit 100.000.000 und Stückzahlen mit
100.000.000. Diese Faktoren gelten nicht ungeprüft für jede alte Modellversion; die Normalisierung
entscheidet anhand der Dateiversion und wandelt ausschließlich in `Decimal` um.

### Kanonische Abbildung

| Portfolio Performance | PortmanNL | Regel |
|---|---|---|
| `account` | Giro-/Verrechnungskonto | UUID als externe Identität behalten; Währung und Kontoname nicht als alleinigen Schlüssel verwenden |
| `portfolio` | Depot | zugehöriges Verrechnungskonto explizit zuordnen oder neu anlegen |
| `security` | `asset_identity` | UUID, ISIN, WKN, Ticker, Börsenplatz und Währung getrennt übernehmen |
| `account-transaction` | Kontobuchung | Betrag, Währung, Typ, Datum, Steuer-/Gebührenanteile und Quelle erhalten |
| `portfolio-transaction` | Depotbewegung | Stückzahl, Wertpapier, Typ, Datum und Kostenanteile erhalten |
| `buysell` | wirtschaftlicher Vorgang mit Konto- und Depotbein | beide Buchungen über eine externe Vorgangs-ID verbinden |
| Konto-/Depotübertrag | zwei verbundene Buchungen | Quelle und Ziel zusammen importieren; keine unabhängigen Einzelbuchungen erzeugen |
| `unit` | Betragskomponente | Bruttowert, Steuer und Gebühr getrennt; Forexbetrag und Wechselkurs erhalten |
| `price` / `latest` | `price_history` | eigener Importfeed, Skalierung und Konfliktstatus; vorhandene Providerdaten nicht überschreiben |

PP unterscheidet Kontoarten wie Einzahlung, Entnahme, Zins, Dividende, Gebühr, Steuer, Kauf, Verkauf
und Übertrag von den Depotarten Kauf, Verkauf, Ein-/Auslieferung und Übertrag. Besonders Kauf und
Verkauf bestehen aus einem synchronisierten Konto- und Depotbein. PortmanNL speichert diese Beine in
seinen vorhandenen Fachobjekten, ergänzt aber eine gemeinsame Vorgangskennung. Dadurch bleiben Saldo,
Bestand und Performance abstimmbar und eine Korrektur zerreißt nicht unbemerkt den Vorgang.

Bei Fremdwährungen gelten harte Prüfungen: Die Kontobuchung muss zur Kontowährung passen. Weichen
Wertpapier- und Transaktionswährung ab, muss eine Bruttowert-Komponente mit Gegenwährung und Wechselkurs
vorliegen. Bei gleicher Währung ist eine fremde Bruttowert-Komponente ein Fehler. Fehlende Wechselkurse
werden nicht aus dem Betrag geraten.

### Importprovenienz und Identitäten

Die vorhandenen Originaldateien, Importläufe und Auditdaten bleiben Grundlage. Für fremde Objektgraphen
sind folgende Ergänzungen sinnvoll:

```sql
CREATE TABLE external_identity_map(
  source_system TEXT NOT NULL,
  external_uuid TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  local_key TEXT NOT NULL,
  first_import_id INTEGER NOT NULL REFERENCES imports(id),
  PRIMARY KEY(source_system, external_uuid, entity_type)
);

CREATE TABLE external_transaction_links(
  import_id INTEGER NOT NULL REFERENCES imports(id),
  external_group_id TEXT NOT NULL,
  local_transaction_id INTEGER NOT NULL,
  leg_type TEXT NOT NULL,
  PRIMARY KEY(import_id, external_group_id, local_transaction_id)
);

CREATE TABLE external_import_entities(
  import_id INTEGER NOT NULL REFERENCES imports(id),
  entity_type TEXT NOT NULL,
  external_id TEXT,
  fingerprint TEXT NOT NULL,
  raw_payload TEXT NOT NULL,
  status TEXT NOT NULL,
  warning TEXT,
  PRIMARY KEY(import_id, entity_type, fingerprint)
);
```

`raw_payload` ist die normalisierte Darstellung eines einzelnen Elements und kein zweites Kontenmodell.
Sie erlaubt spätere Parserverbesserungen und erklärt Warnungen. Die vollständige Originaldatei bleibt
über den bestehenden Importbeleg mit SHA-256-Hash nachvollziehbar.

Die Zuordnung erfolgt in dieser Reihenfolge:

1. bereits bestätigte Kombination aus Quellsystem und PP-UUID,
2. eindeutige ISIN,
3. eindeutige Kombination aus WKN und Währung,
4. eindeutige Kombination aus Ticker, Börsenplatz und Währung,
5. manuelle Auswahl oder Neuanlage.

Namen allein verbinden keine Konten, Depots oder Wertpapiere. Fehlt in einer alten Datei eine UUID,
erzeugt PortmanNL eine stabile externe Kennung aus Entitätstyp, normalisierten Identifikatoren und
Quelldatei. Die einmal bestätigte Zuordnung wird gespeichert und bei Folgeimporten wiederverwendet.

### Importpipeline

Die erste Ausbaustufe ist ein Vorschau-Importer:

1. Container anhand seiner Signatur erkennen, nicht anhand der Dateiendung.
2. ZIP-Pfade, Dateianzahl, entpackte Größe und Kompressionsverhältnis prüfen; DTD und Entitäten sperren.
3. Modellversion lesen und XML in neutrale Staging-Objekte überführen. Referenzen werden erst nach dem
   vollständigen Einlesen aufgelöst.
4. Konten, Depots und Wertpapiere über gespeicherte Identitäten abgleichen. Unklare Treffer kommen in
   die Zuordnungsvorschau; fehlende Ziele können dort angelegt werden.
5. Transaktionspaare, Einzelbuchungen, Kurse und Einheiten validieren. Fehler einer Zeile stoppen nicht
   die Analyse der restlichen Datei.
6. Dubletten über externe UUID, bereits importierten Dateihash und fachlichen Fingerprint markieren.
   Der bestehende Herkunftsnachweis von PortmanNL bleibt maßgeblich.
7. Die Vorschau zeigt pro Objekt Quelle, Ziel, Datum im Format `TT.MM.JJJJ`, Betrag/Stückzahl, Währung,
   Status und konkrete Warnung. Der Benutzer kann Zuordnungen korrigieren und Objekte abwählen.
8. Nach Bestätigung werden Neuanlagen, Buchungen, Verknüpfungen und Kurse in einer SQLite-Transaktion
   geschrieben. Jeder Fehler rollt den gesamten Lauf zurück.
9. Abschließend werden Kontosaldo, Depotbestand, verbundene Buchungsbeine und Kursanzahl gegen die
   Vorschau abgestimmt. Erst danach erhält der Import den Status `abgeschlossen`.

Historische Kurse landen in einem Feed wie `portfolio-performance-xml:<Quelldatei-Hash>`. Ein Konflikt
mit einem bereits vorhandenen Kurs wird in der Vorschau angezeigt; Providerreihen werden niemals still
überschrieben. Unbekannte XML-Elemente und Attribute bleiben im Staging-Payload erhalten und erzeugen
eine Warnung, damit neue PP-Versionen nicht unbemerkt Daten verlieren.

Die vorhandene Dublettenerkennung wird nicht auf die gröbere PP-Regel reduziert. PP vergleicht im Kern
Tag, Währung, Betrag, Stückzahl, Wertpapier und einen äquivalenten Typ. PortmanNL berücksichtigt zusätzlich
Importquelle, externe IDs und bestätigte Konfliktentscheidungen.

### Prüfmatrix

Vor Freigabe des vollständigen Imports werden Testdateien für alte und aktuelle Modellversionen, XML mit
relativen und ID-Verweisen, ZIP-XML, fehlende UUIDs, alle Buchungsarten, Fremdwährungen, Transaktionspaare,
Kurskonflikte und Wiederholungsimporte benötigt. Verschlüsselte und Protobuf-Dateien müssen kontrolliert
abgewiesen werden. Für jede unterstützte Datei gelten anschließend diese Invarianten:

- Summe der Kontoauswirkungen entspricht der PP-Datei je Konto und Währung.
- Stückzahl je Depot und Wertpapier stimmt am letzten Importtag überein.
- jedes gekoppelte Geschäft besitzt alle erwarteten Beine.
- ein erneuter Import derselben Datei legt keine weiteren Fachdaten an.
- ein Fehler während des Schreibens hinterlässt weder Konten noch Teilbuchungen.

Ein Export wird erst freigegeben, wenn Roundtrip-Tests mit repräsentativen Dateien Konten, Buchungen,
Kurse, Identitäten, Transaktionsverknüpfungen und Währungen verlustfrei bestätigen.

## Umsetzungsreihenfolge

1. (umgesetzt) Tägliche Bewertungsreihe: Tagesindex mit echter TTWROR aus der taggenauen
   Neutralisierung externer Flüsse.
2. (umgesetzt) Portfolio-Risiko auf derselben Reihe: Volatilität, Semivolatilität, maximaler und
   aktueller Drawdown sowie längste Drawdown-Dauer.
3. (teilweise umgesetzt) Benchmark-Rendite, aktive Rendite und Tracking Error; Inflation/FX-Vergleich offen.
4. Hierarchische Taxonomien und Soll-/Ist-Allokation.
5. (umgesetzt) PP-XML-Vorschauimport (lesend) mit Kontenzuordnung und Dublettenprüfung; Schreiben
   erst nach Bestätigung über `save_pp_preview`.
6. PP-XML-Export nach Roundtrip-Validierung.

Die vorhandene SQLite-Datenbank bleibt damit die zentrale Wahrheit. PP-XML dient als Austauschformat,
nicht als zweite parallele Datenhaltung.
