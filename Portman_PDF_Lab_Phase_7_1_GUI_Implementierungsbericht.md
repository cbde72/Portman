# Portman PDF Lab – Phase 7.1 GUI-Implementierungsbericht

## Ergebnis

Phase 7.1 ist als reine GUI- und Anzeigeänderung umgesetzt. Parser,
Rule Engine, SQLite-Schema, YAML-Regelprofile und fachliche Berechnungen wurden
nicht verändert. Das Hauptfenster startet weiterhin maximiert über
`python -m portman_pdf_lab gui`.

Zusätzlich zur strukturierten Ergebnisansicht und zum Parsertraining werden
erkannte Werte evidencebasiert im PDF markiert. Die Markierungen sind
transparente Überlagerungen aus der PDF-Textschicht, verändern das Dokument
nicht und lösen keinen zusätzlichen Parserlauf aus. Der zuvor beim Auswählen
fehlender Felder auftretende `NoneType`-Absturz ist behoben.

## Resizing und persistentes Layout

- Der horizontale Hauptsplitter teilt Dokumentliste, PDF und Ergebnisreiter.
- PDF und Evidence-Auszug liegen in einem zusätzlichen vertikalen Splitter.
- Parsertraining besitzt persistente obere, untere und Hauptsplitter.
- `QSettings("Portman", "PDFLab")` speichert Fenstergeometrie,
  Splitterzustände und Tabellenkopfbreiten.
- Eine außerhalb der aktuellen Bildschirme liegende Geometrie wird verworfen.
- Zentrale Bereiche verwenden expandierende Größenrichtlinien und nur kleine,
  sicherheitsrelevante Mindestbreiten. Es gibt keine feste zentrale Höhe.
- PDF-Zoom bleibt beim Splitter-Resizing unverändert. Splitterbewegungen lösen
  weder Extraktion noch Parserlauf aus.
- Die Trainingsaktionen sind in einem dreispaltigen Raster angeordnet, sodass
  sie nicht mehr in einer einzelnen überbreiten Zeile liegen.

## Strukturierte Ergebnisansicht

`ui/result_view.py` enthält den generischen, read-only Anzeigeadapter:

- Verlustfreies Flattening mit eindeutigen Pfaden wie `fees[0].amount`.
- Keine Mutation der Eingabedaten und keine Konvertierung in `float`.
- Umschaltung zwischen `Tabelle` und vollständig formatiertem `JSON`.
- Spalten `Feldpfad`, `Feldname`, `Wert`, `Einheit`, `Status`, `Quelle` und
  `PDF-Seite`.
- Evidence-Verknüpfung, Seitenwechsel und vollständige Tooltips.
- Währungen/Einheiten werden für untergeordnete Betragsfelder übernommen.
- Arrays, Objekte, `null`, `MissingValue`, `0`, `0.00`, `False`, Evidence,
  Issues, Konten, Depots, Transaktionen, Gebühren, Steuern, Cashflows,
  Regelprofile und FieldDecisions verwenden denselben Adapter.

Die bisherigen neun Ergebnisreiter verwenden nun jeweils diese Ansicht. Die
Rohdaten bleiben im JSON-Modus erreichbar.

## Statusmodell

| Status | Darstellung | Regel |
|---|---|---|
| ERKANNT | grün plus Text | Wert vorhanden, PDF-Evidence vorhanden, kein Konflikt |
| NICHT ERKANNT | rot plus Text | `null`, `MissingValue` oder expliziter Missing-Status |
| PRÜFEN | gelb plus Text | keine Evidence, Konflikt, Mehrdeutigkeit oder EXPECTED/PROPOSED |
| NICHT ANWENDBAR | grau plus Text | explizites `NOT_APPLICABLE`/`N/A` |

Die Erkennung ist von Referenzbestätigung und Reviewstatus getrennt. Nullwerte
sind fehlend; numerische Null, `False` und leere Strings werden nicht als
fehlend behandelt. EXPECTED-Cashflows werden nicht als nachgewiesene
ACTUAL-Buchungen grün dargestellt. Ein fehlender Pflichtwert wird nur dann rot
markiert, wenn dafür eine echte Textstelle existiert; ein fehlender optionaler
Wert erscheint grau und erzeugt keine PDF-Markierung.

Der Statusfilter bietet `Alle Felder`, `Nur erkannte`, `Nur fehlende` und
`Nur zu prüfende`. Die Statistik zählt alle vier Statusklassen aus dem
Statusmodell und nicht aus formatierten Zelltexten.

## Tabellenbedienung

- Zellen-, Mehrfach- und Bereichsauswahl
- `Strg+A` und `Strg+C` als tabulatorgetrennter Export
- Kontextmenü `Kopieren` beziehungsweise `Alles kopieren`
- sortierbare und manuell skalierbare Spalten
- persistente Spaltenbreiten
- horizontale und vertikale Scrollbars bei Bedarf
- vollständige lange Werte per Tooltip oder JSON-Ansicht

Die Tabellen sind reine Ansichten. Sortieren, Filtern und Kopieren verändern
weder Parserwerte noch Referenzen.

## Parsertraining

Der zehnte Reiter behält Annotation, Korrektur, Referenzbestätigung,
Golden-Tests, Regelvorschläge, Tests, Freigabe, Aktivierung, Export/Import und
Rollback. STANDARD, EXTENDED, Referenzwert, Quelle, Fundstelle, Status und
Regel-ID bleiben gemeinsam sichtbar. Fehlende und unsichere Felder sind farbig
und textuell markiert und können unmittelbar zur Korrektur ausgewählt werden.

### Absturzursache `'NoneType' object has no attribute 'text'`

Die Auswahl eines Feldes las Zellen ungeprüft über `QTableWidget.item(row,
column)` und rief anschließend `.text()` auf. Bei fehlenden Parserwerten, nach
dem Sortieren, beim Filtern oder bei unvollständig aufgebauten Zeilen lieferte
Qt für nicht vorhandene Zellen `None`. Der Fehler trat damit genau in der
Situation auf, die eigentlich eine Korrektur ermöglichen sollte.

Behoben durch drei Maßnahmen:

- Jede Zeile wird beim Aufbau vollständig mit allen neun Zellen angelegt; die
  Tabelle sortiert erst nach abgeschlossenem Aufbau.
- Ein zentraler, seiteneffektfreier Helfer liest Zellen mit `None`-Prüfung und
  liefert einen leeren String. Alle Status-, Filter-, Auswahl- und
  Navigationszugriffe verwenden ihn.
- `_select_field` arbeitet zusätzlich über das gebundene `DisplayRow`-Objekt
  und fällt nur dann auf Zelltexte zurück, wenn keine Anzeigezeile existiert.
  Fehlende Werte bleiben als editierbare Felder erhalten und werden nicht mehr
  aus der Tabelle entfernt.

Sortierung und Filterung verändern weder die zugrunde liegenden Parserwerte
noch die Zeilenfarben; die Referenzspalte bleibt editierbar. Die
Feldauswahl ist damit unabhängig von der aktuellen Zeilenreihenfolge.


## Erweiterung: PDF-Textauswahl und Feldzuordnung

Die Qt-PDF-Ansicht der eingesetzten PySide6-Version bietet keine belastbare
öffentliche Maus-Textauswahl mit Koordinaten. Deshalb zeigt PDF Lab direkt beim
Original-PDF einen synchronisierten, read-only Textlayer aus der bestehenden
lokalen PDF-Extraktion. Er unterstützt Wort-, Abschnitts- und
Mehrzeilenauswahl, Kopieren, Seitenbindung und persistente Hervorhebungen beim
Seitenwechsel. Die Original-PDF wird nicht verändert und ein Splitter-Resize
startet keine Extraktion. Fehlt der Textlayer, wird ausdrücklich auf die nicht
aktivierte OCR hingewiesen.

Das Kontextmenü bietet:

- Text kopieren
- Feld zuordnen
- Neues Feld definieren
- Als Referenzwert übernehmen
- Fundstelle anzeigen

Der Zuordnungsdialog zeigt Bank, Parser, Dokumenttyp, Seite, Original- und
Auswahltext, Zielfeld, Wert, Datentyp, Pflichtstatus, Normalisierung, Evidence
und Regelmodus. Original- und normalisierter Wert bleiben getrennt. Eine
Zuordnung erzeugt eine Annotation im bestehenden Phase-7-Workflow und niemals
automatisch eine aktive Regel oder wirtschaftliche Buchung. Bereits vorhandene
Koordinaten können in `annotations.coordinates_json` gespeichert werden; der
aktuelle Textlayer behauptet keine Bounding-Boxes, wenn keine vorliegen.

Sichere Regelvorschläge bevorzugen nun Label-/Wert-Muster. Aus
`Handelsplatz: XETRA` entsteht ein begrenzter deklarativer `REGEX_FIELD`, der
auch `Handelsplatz: Tradegate` erkennt und nicht den konkreten Belegwert
festschreibt. Vorschläge bleiben vorläufig, inaktiv und müssen weiterhin über
Golden-/Regressionstest und explizite Freigabe laufen. Beliebiger Python-Code
wird nicht erzeugt oder ausgeführt.

## PDF-Markierungen erkannter Werte

### Datenquelle und Evidence-Autorität

`ui/pdf_markings.py` bildet Parserergebnis, Regelentscheidungen und
Benutzerannotationen auf markierbare Fundstellen ab. Die Feldliste stammt aus
den tatsächlichen DTO-Pfaden und dem versionierten Feldkatalog; es gibt keine
hart codierte Feld-Whitelist. Anzeigename, Pflichtstatus und Bedingung kommen
aus dem Katalog, der Wert ausschließlich aus dem Parser- beziehungsweise
Regelmodus-Ergebnis.

Als Koordinatenquelle dient die Textschicht von `QPdfDocument`:

- `getAllText(page)` liefert den Text samt Zeichenindizes.
- `getSelectionAtIndex(page, start, length)` liefert die zugehörigen
  Vierecke in PDF-Punkten.
- Diese Punkte sind unabhängig von Fenstergröße, Splitterposition, Zoom, DPI
  und Scrollzustand. Die Überlagerung rechnet sie erst beim Zeichnen in
  Widget-Koordinaten um.
- Es werden keine Bounding-Boxes geschätzt. Fehlt eine eindeutige Textstelle,
  bleibt die Markierung aus.

Der Evidence-Auszug ist die maßgebliche Verankerung. Verglichen wird
normalisiert (Whitespace, Groß-/Kleinschreibung) und zusätzlich über gedruckte
Äquivalente, etwa `126.50` → `126,50` oder ISO-Datum → `DD.MM.YYYY`. Dadurch
werden Parserwert und sichtbarer Beleg zusammengeführt, ohne den Wert zu
verändern.

### Markierungsregeln und Farben

| Status | Farbe | Markierungsregel |
|---|---|---|
| Erkannt | grün `#2e7d32` | Wert und Evidence vorhanden, Textstelle eindeutig zuordenbar |
| Prüfen | gelb/orange `#b26a00` | mehrdeutige oder wiederholte Textstelle, Konflikt, EXPECTED/PROPOSED |
| Fehlend / ungültig | rot `#c62828` | erforderlicher Wert fehlt oder ist ungültig, echte Textstelle vorhanden |
| Nicht anwendbar | grau `#707070` | optionaler/nicht anwendbarer fehlender Wert; keine PDF-Markierung |

Weitere Regeln:

- Ein eindeutiger, normalisierter Treffer gilt als zuverlässig und wird grün
  markiert.
- Mehrfache Treffer ohne eindeutigen Kontext werden gelb mit Fundstellenangabe
  (`n von m`) markiert, nicht grün.
- Ein nicht auffindbarer Wert erzeugt keine Markierung; die Tabelle zeigt den
  Status weiterhin textuell und farbig.
- Fehlende Pflichtwerte werden nur dann rot am Beleg verankert, wenn eine
  reale Textstelle existiert.
- Optionale fehlende Werte sind `NOT_APPLICABLE`, grau und ohne PDF-Zeichen.
- `NOT_FOUND`, `UNKNOWN` und leere Strings gelten als fehlend.
- Mehrere Befunde pro Feld und mehrere Felder an derselben Textstelle bleiben
  erhalten und werden gruppiert dargestellt.
- Liegen gespeicherte Annotationskoordinaten vor, werden diese Vierecke direkt
  verwendet.

### Regelmodi und Herkunft

- **STANDARD** markiert ausschließlich Ergebnisse des bestehenden
  Python-Parsers.
- **EXTENDED** ergänzt Werte aus dem freigegebenen Regelprofil. Die Herkunft
  wird als `Optionale Regelkonfiguration` mit Regel-ID angezeigt; Konflikte
  werden gelb statt grün dargestellt.
- **COMPARE** zeigt Unterschiede und beide Herkunftswege. Bei Konflikten
  erhalten auch die Parser-Markierungen Gelb, damit kein falsches Grün
  entsteht. Nur durch das Regelprofil erkannte Werte werden als solche
  gekennzeichnet.
- Benutzerbestätigte Annotationen tragen die Herkunft
  `Benutzerbestätigte Annotation`. Parser, Regelprofil und Annotation bleiben
  im Tooltip getrennt sichtbar.

### Bedienung

Die PDF-Werkzeugleiste enthält:

- Kontrollkästchen `Erkannte Werte markieren` (Standard: aktiv)
- Auswahl `Alle erkannten Felder` (Standard), `Nur ausgewähltes Feld` oder
  `Markierungen ausblenden`

Die Einstellungen werden über `QSettings("Portman", "PDFLab")` unter
`pdf/markings-enabled` und `pdf/markings-scope` gespeichert.

Interaktion:

- Hover über eine Markierung zeigt Feld, Pfad, Wert, Status, Herkunft, Parser,
  Regel-ID und Seite; bei Mehrfachtreffern zusätzlich die Fundstelle.
- Klick auf eine Markierung selektiert die zugehörige Tabellenzeile.
- Klick auf eine Tabellenzeile navigiert zur PDF-Seite und hebt das Feld hervor.
- Ein Wechsel des ausgewählten Feldes aktualisiert die eingeschränkte Ansicht
  ohne erneuten Parserlauf.
- Das Kontextmenü der Textschicht bietet weiterhin Feldzuordnung, neues Feld,
  Referenzübernahme und Fundstellenanzeige; bestätigte Annotationen erscheinen
  anschließend als Markierung.
- Markierungen sind transparente Überlagerungen. Das Original-PDF wird weder
  verändert noch neu geschrieben.

### Bugfix: `'tuple' object has no attribute 'x'`

**Ursache:** `_screen_polygon()` erwartete für jeden Eckpunkt ein Objekt mit
`x()`/`y()`-Methoden. Tatsächlich erreichten die Funktion drei Formate:

- `QPdfSelection.bounds()` liefert `QPointF`-Polygone,
- aufgelöste Markierungen speichern Quads als Tupel von `(x, y)`-Tupeln,
- persistierte Annotationen liefern verschachtelte `[[x, y], ...]`-Listen.

Beim Zeichnen gespeicherter Annotationskoordinaten und beim Aufruf über
`markings_at()` aus `mouseMoveEvent()` wurden die Listenpunkte unverändert an
`point.x()` übergeben. Daraus entstand
`AttributeError: 'tuple' object has no attribute 'x'`. Eine einzige fehlerhafte
Annotation konnte damit die PDF-Anzeige beziehungsweise jede Mausbewegung
abbrechen.

**Korrektur:**

- Zentrale Funktion `_as_point()` normalisiert `QPointF`, `QPoint`, Tupel,
  zweielementige Listen und `{"x": ..., "y": ...}`-Mappings zu `QPointF`.
- Nur endliche Zahlen werden akzeptiert; `None`, boolesche Werte, falsche
  Längen, nicht numerische Strings sowie `NaN`/`Inf` werden kontrolliert
  zurückgewiesen.
- `_screen_polygon()` validiert das gesamte Polygon. Ungültige oder
  unvollständige Quads liefern ein leeres `QPolygonF`, werden mit Seite,
  Feldpfad und Quad-Index protokolliert und weder gezeichnet noch für die
  Treffererkennung verwendet.
- `_pdf_point()` verwendet dieselbe Normalisierung für Mauspositionen.
- Gespeicherte Annotationen werden beim Hinzufügen über `_coordinate_quads()`
  normalisiert. Unbekannte Koordinatensysteme und strukturell ungültige
  Annotationen werden protokolliert und übersprungen; Legacy-Rechtecke
  `[x, y, width, height]` werden weiterhin in ein Polygon umgewandelt.
- Zeichnen und Treffererkennung verwenden gemeinsam `_marking_polygons()`.
  Damit ist die Transformation für Maus und Darstellung identisch.
- Bildschirmpolygone werden je Markierung zwischengespeichert. Der Cache wird
  bei Dokument-, Seiten-, Zoom- und Markierungswechsel sowie bei Resize
  invalidiert. Scrollen verändert keine Canvas-Koordinaten und benötigt keine
  Neuberechnung.
- `focusMarking()` berechnet den Scroll-Zielpunkt aus demselben validierten
  Polygon statt aus ungeprüften Rohpunkten.

**Zoom, Rotation und DPI:** `QPdfDocument.pagePointSize()` liefert bereits die
gedrehte Anzeigegröße; `QPdfSelection.bounds()` und gespeicherte Quads liegen im
selben Anzeigekoordinatensystem. Zoom, Seitenrotation, Seitengröße und
DPI-Skalierung reduzieren sich daher auf die Skalierung vom PDF-Punktraum auf
die aktuelle Pixmap. Ein Rotationstest mit `/Rotate 90` bestätigt, dass
Auswahlrechtecke innerhalb der gedrehten Seite liegen und per Maus getroffen
werden.

### Performance und Robustheit

- Seitentexte werden je Dokument zwischengespeichert; Markierungsänderungen und
  Sichtbarkeitsschalter verwenden diesen Cache und starten weder Extraktion
  noch Parserlauf.
- Es wird nur die aktuell sichtbare Seite gerendert. Nicht sichtbare Seiten
  werden nicht gezeichnet; ein Resize oder Scrollen löst keine neue
  Seitenextraktion aus.
- Das Umschalten von Sichtbarkeit, Umfang oder Regelmodus ändert nur die
  Darstellung und verwendet die vorhandenen Daten.
- Die Überlagerung folgt Zoom, Scrollen, Seitenwechsel, Rotation,
  Seitengröße, DPI und Fenstergröße, weil die Koordinaten in PDF-Punkten
  gespeichert und erst beim Zeichnen transformiert werden.
- Steht keine PDF-Textschicht zur Verfügung (etwa bei gescannten Dokumenten),
  nutzt der separate Textlayer die pypdf-Extraktion und kennzeichnet die
  Markierung gestrichelt als Fallback ohne PDF-Bounding-Box. Es werden keine
  Koordinaten erfunden.

## Versionierte Feldkataloge und Editoren

`field_catalog.py` verwaltet schema- und versionsgeprüfte YAML-Kataloge im
lokalen PDF-Lab-Datenverzeichnis. Der Katalog ist nach Bank, Parser,
Dokumenttyp und Layout eingrenzbar und enthält Feld-ID, echten DTO-Pfad,
Anzeigename, Beschreibung, Typ, Format, Einheit, Pflichtstatus, Validierung,
Editor, Reihenfolge, Sichtbarkeit, Muster, Normalisierer und
Evidence-Anforderung.

ISIN und WKN sind getrennte DTO-Pfade. `trade.venue` ist optional und liegt im
ausdrücklichen Erweiterungsbereich `attributes.user_fields`; neue
Benutzerfelder werden dort als neue unveränderliche Katalogversion gespeichert
und erzeugen keine DTO-Eigenschaft oder Geldwirkung. Die Editor-Factory bietet
validierte ISIN-, WKN-, IBAN-, Decimal-, Betrags- und Datumsfelder sowie
Handelsplatz-, Status- und Mehrzeileneditoren. Decimal-Normalisierung verwendet
`Decimal` und rundet nicht.

F1, Toolbar-Hilfe und der Zuordnungsdialog erzeugen ihre Feldhilfe vollständig
aus dem Katalog. Die vier Gruppen sind unbedingt erforderlich, bedingt
erforderlich, optional sowie technisch/Qualität. Katalogfelder ergänzen die
Übersicht; fehlende erforderliche Werte werden rot, optionale oder nicht
anwendbare Werte grau dargestellt. Die komplette Tabellenzeile erhält die
Statusfarbe und behält zusätzlich den Statustext.

## Parser-Feldanalyse und direkter Trainingsübergang

### Ziel und Einordnung

Der neue Tab `Feldanalyse` steht unmittelbar vor `Parsertraining` und bildet
den vollständigen Katalog eines Parserlaufs ab. Er beantwortet drei getrennte
Fragen:

1. Welche Felder verlangt der Katalog (Pflicht, bedingt, optional, technisch)?
2. Was hat der Parser tatsächlich extrahiert und womit ist es belegt?
3. Welcher Trainingsstand existiert bereits für dieses Feld?

Die Feldanalyse erzeugt keine Werte und keine wirtschaftlichen Buchungen. Sie
liest ausschließlich den vorhandenen Parserlauf, den Katalog sowie die
bestehenden Annotation-, Kandidaten- und Aktivierungstabellen.

### Spalten und Zeilenquelle

Die Tabelle zeigt `Feldgruppe`, `Feldname`, `Feldpfad`, `Pflichtstatus`,
`Gefundener Wert`, `Erkennungsstatus`, `PDF-Seite`, `Evidence`, `Parserregel`,
`Trainingsstatus` und `Aktion`.

Primäre Zeilenquelle sind die sichtbaren Felder des versionierten Katalogs.
Dadurch erscheinen auch reine Katalogfelder, die im Parserergebnis gar nicht
vorkommen. Fehlt ein Katalog, wird auf die flach dargestellten Ergebnisfelder
zurückgefallen. Dadurch bleibt ein ungewöhnlicher oder alter Lauf inspizierbar,
ohne dass Zeilen erfunden werden.

Die Zuordnung verwendet ausschließlich den stabilen Feldpfad. Sortierung,
Filterung, Tabwechsel und erneutes Binden ändern keine Zeilenidentität; die
Aktion wird nie über einen Tabellenzeilenindex gespeichert.

### Status- und Farbmodell

| Erkennungsstatus | Bedeutung | Farbe |
| --- | --- | --- |
| `ERKANNT` | Parserwert vorhanden und durch Evidence belegt | grün |
| `NICHT ERKANNT` | Pflicht- oder bedingtes Pflichtfeld ohne gültigen Wert | rot |
| `PRÜFEN` | Konflikt, ungültiger Wert oder mehrdeutige Evidence | gelb |
| `NICHT ANWENDBAR` | optionales Feld ohne Wert oder fachlich nicht anwendbar | grau |

Zusätzliche Statustexte unterscheiden ausdrücklich:

- `Fehlt / nicht extrahiert` – der Parser hat keinen Wert geliefert; es gibt
  keinen Nachweis, dass die Angabe im PDF fehlt.
- `Nicht extrahiert (optional)` – optionales Feld ohne Parserwert; kein Fehler.
- `Nachweislich nicht im PDF vorhanden` – nur wenn eine aktive Annotation die
  Abwesenheit ausdrücklich bestätigt.
- `Prüfen (STANDARD/EXTENDED-Konflikt)` – die Regelmodi liefern verschiedene
  Werte.

Eine bestätigte Referenz, ein Regelkandidat oder ein freigegebenes, aber noch
nicht aktives Profil färbt eine Zeile niemals grün. Der Trainingsstatus ist
eine separate Spalte:

- `Untrainiert`
- `Annotation`
- `Abwesenheit bestätigt`
- `Kandidat`, `Kandidat getestet`, `Kandidat verworfen`, `Kandidat ersetzt`
- `Freigegeben`
- `Freigegeben · Profil aktiv`

Nur ein erneuter Parserlauf mit tatsächlich extrahiertem Wert und Evidence darf
`ERKANNT` erzeugen. Bei aktiviertem EXTENDED-Profil gilt dasselbe: erst der
Lauf, nicht die Aktivierung, verändert den Erkennungsstatus.

### Trainingskontext

Die Übergabe erfolgt über das unveränderliche `TrainingContext`-Objekt in
`training/context.py`. Es enthält unter anderem:

- Dokument-ID und Dokument-Hash,
- Bank, Parser-ID, Handler-ID, Dokumenttyp und Regelmodus,
- Feld-ID, Feldpfad, Feldname, Datentyp und Pflichtstatus,
- aktuellen Parserwert, Referenz- oder Annotationswert,
- Evidence, PDF-Seite und Originaltext,
- Katalogversion und aktive Regelprofilversion,
- Annotations-ID, Kandidaten-ID und Kandidatenstatus,
- Trainingsstatus.

`FieldAnalysisWidget.training_context()` erzeugt dieses Objekt direkt aus der
stabilen Zeile. `TrainingWidget.apply_training_context()` bindet damit den
vorhandenen Trainingsbildschirm: Dokument ist ausgewählt, Parser und Modus sind
vorbelegt, das Zielfeld ist markiert, der aktuelle Wert und die Evidence sind
sichtbar, und eine bestehende Annotation bleibt ausgewählt. Es existiert keine
zweite Trainingslogik und keine zweite Datenbank.

### Direkte PDF-Auswahl

Die PDF-Ansicht unterstützt unverändert:

- linke Maustaste: Text auswählen,
- Mausrad: Zoomen am Mauszeiger,
- mittlere Maustaste: Verschieben,
- `Leertaste` + linke Maustaste: Verschieben,
- rechte Maustaste: Kontextmenü.

Eine Auswahl liefert Text, Seite, Start-/Endindex und zuverlässige PDF-Quads.
`TrainingWidget.apply_pdf_selection()` übernimmt sie in den vorbelegten
Trainingskontext. Aus `Handelsplatz: XETRA` wird der normalisierte
Referenzwert `XETRA`; der vollständige Originaltext bleibt getrennt erhalten.
Der Nutzer bestätigt anschließend mit `Auswahl übernehmen`. Ist das Feld
`attributes.user_fields.trade.venue`, wird genau dieses optionale Feld
trainiert; eine automatische Aktivierung oder Buchung findet nicht statt.

Der Zuordnungsdialog `FieldMappingDialog` akzeptiert nun eine Vorauswahl über
Feld-ID oder Feldpfad. Damit öffnet das PDF-Kontextmenü direkt das Feld, das
zuvor in der Feldanalyse oder im Training ausgewählt wurde.

### Referenz- und Annotationsaktionen

Das vorhandene Parsertraining wurde um folgende Aktionen erweitert:

- Feld bestätigen,
- Feld korrigieren,
- als unbekannt markieren,
- PDF-Text zuordnen,
- PDF-Auswahl übernehmen,
- Fehlen bestätigen,
- nicht anwendbar markieren,
- Annotation bearbeiten,
- Annotation löschen,
- zurück zur Feldanalyse.

Beim Speichern werden Originaltext und normalisierter Referenzwert getrennt
gespeichert. Seitenzahl, Dokument-ID, Dokument-Hash, Parser, Handler,
Feldpfad, Entscheidung und Koordinaten werden mitgeführt. Eine vorhandene
Annotation wird aktualisiert statt dupliziert. Löschen deaktiviert die
Annotation, sodass die Historie erhalten bleibt.

### Regelkandidaten und Aktivierung

Der Weg bleibt unverändert:

```text
Annotation → Regelkandidat → Golden Test → Regression → Freigabe → Aktivierung
```

Freigabe und Aktivierung sind weiterhin getrennte Schritte. Kandidaten werden
mit eindeutiger ID, Parser-/Dokumenttypbindung und Verweis auf die
ursprünglichen Annotationen gespeichert. Sie bleiben inaktiv, bis sie
ausdrücklich freigegeben und das Profil ausdrücklich aktiviert wird.

Der Vorschlag für `Handelsplatz: XETRA` ist eine begrenzte Label-/Wert-Regel
und enthält den Literalwert `XETRA` nicht. Derselbe Kandidat erkennt daher auch
`Handelsplatz: Tradegate` und `Handelsplatz: Frankfurt`. STANDARD bleibt
unverändert; EXTENDED verwendet nur freigegebene und aktivierte Profile;
COMPARE zeigt Unterschiede und Konflikte transparent.

### Aktualisierung und Navigation

Die Feldanalyse wird nach Annotation, Referenzzuordnung, Kandidatenerstellung,
Test, Freigabe, Ablehnung, Rollback, Aktivierung, Deaktivierung sowie nach
Moduswechsel erneut aus den vorhandenen Tabellen aufgebaut. Es wird kein
Parserergebnis künstlich verändert.

Die Navigation ist bidirektional und identitätsstabil:

- Feldanalyse → `Feld trainieren` → Parsertraining mit Kontext,
- Parsertraining → `Zur Feldanalyse` → dieselbe Zeile,
- grüne PDF-Markierung → dieselbe Feldanalyse-Zeile,
- Trainingszeile → zugehörige Feldanalyse-Zeile.

Sortierung, Filter und Tabwechsel unterbrechen diesen Weg nicht, weil alle
Übergaben über Feldpfad und Kontextobjekt statt über sichtbare Zeilennummern
laufen.

### Robustheit

Die neuen Tabellen und Kontextpfade behandeln `None`, `MissingValue`, leere
Zellen, fehlende `QTableWidgetItem`, unbekannte Evidence-Strukturen,
nicht-numerische Seitenangaben und ungewöhnliche Ergebnisformen ohne Absturz.
Ungültige oder fehlende Koordinaten werden ignoriert statt geschätzt.

## Tests und Sichtprüfung

Ergänzte Tests prüfen:

- verschachtelte Objekte und indizierte Listen ohne Datenverlust,
- Präzisionsstrings, `null`, `0`, `False` und leere zulässige Werte,
- Evidence-, Konflikt-, EXPECTED- und N/A-Klassifizierung,
- Tabellen-/JSON-Umschaltung, Statusfilter und Komplettkopie,
- Maximieren, Verkleinern, Geometrie-, Splitter- und Headerpersistenz,
- fortbestehende Parsertraining- und Worker-Funktionalität,
- fehlende Zellen und Sortierung/Filterung ohne `NoneType`-Absturz,
- Markierungssammlung aus DTOs, Katalog und Evidence,
- eindeutige, wiederholte und nicht auffindbare Textstellen,
- gedruckte Zahlen-/Datumsäquivalente und normalisierte Leerzeichen,
- Pflicht-/Optionalregeln, Annotationskoordinaten und Herkunftsnachweis,
- STANDARD/EXTENDED/COMPARE inklusive Konflikt-Gelb statt Grün,
- Sichtbarkeitsschalter, Feldbereich, Persistenz und Klicknavigation,
- `QPointF`, `QPoint`, Tupel und zweielementige Listen als Koordinaten,
- vierpunktige Quads, leere, falsch typisierte und nicht endliche Quads,
- fehlerhafte gespeicherte Annotationen ohne Absturz der Anzeige,
- Mausbewegung und Tooltip über grünen Markierungen,
- Klick auf eine grüne Fundstelle inklusive Feldaktivierung,
- Textauswahl nach Zoom und Resize,
- Treffererkennung und Darstellung auf `/Rotate 90`-Seiten,
- seitengebundene Markierungen auf mehreren PDF-Seiten,
- unveränderte STANDARD-/EXTENDED-/COMPARE-Status- und Herkunftslogik,
- Katalogabdeckung, Katalog-ohne-Parserwert und leere/ungültige Berichte,
- Trennung von Erkennungsstatus und Trainingsstatus bei Annotationen,
  Kandidaten und aktiven Profilen,
- vollständigen `TrainingContext` inklusive Dokument-Hash, Parser, Handler,
  Evidence, Seite, Katalog- und Profilversion,
- labelbasierte Handelsplatz-Regel ohne hart codiertes `XETRA`,
- Tabellenfilter, Sortierung und Übergabe an das Parsertraining,
- direkte PDF-Auswahl inklusive Normalisierung, Seite und Koordinaten,
- Vorauswahl des Zielfelds im `FieldMappingDialog`,
- Feldanalyse-Tabposition, Tabwechsel, Rücknavigation und grüne
  PDF-Markierung als Gegenrichtung,
- Mausrad-Zoom am Zeiger sowie Mittelbutton- und Leertaste-Pan ohne
  versehentliche Textauswahl,
- Aktualisierung der Feldanalyse nach Annotation und Regelaktion.

Vollständige Regression der betroffenen Pakete:

```text
portman-pdf-lab: 100 passed in 8.62s
portman-parsers: 119 passed in 1.58s
```

Offscreen-Sichtprüfung:

```text
SCREENSHOT_OK=True size=796x796 textlayer=True
```

Screenshot: [Portman_PDF_Lab_Phase_7_1_GUI.png](Portman_PDF_Lab_Phase_7_1_GUI.png)

Der offscreen Qt-Treiber stellt auf diesem Rechner Umlaute ohne Systemfont als
Platzhalter dar; dies betrifft nur den headless Screenshot, nicht die native
Windows-GUI.

## Verbleibende Einschränkungen

- Für Dokumenttypen ohne spezifisch freigegebenen Katalog wird der allgemeine
  Startkatalog verwendet. Bedingte Pflichten bleiben dabei grau, bis ihre
  wirtschaftliche Bedingung katalogseitig präzisiert ist.
- PDF-Markierungen benötigen eine Textschicht mit Zeichenindizes. Bei reinen
  Scans ohne Textschicht bleibt die PDF-Überlagerung leer; der separate
  Textlayer zeigt dann einen gestrichelt gekennzeichneten Fallback aus der
  pypdf-Extraktion. OCR ist weiterhin nicht aktiviert.
- Mehrdeutige oder wiederholte Werte werden bewusst gelb statt grün markiert.
  Eine eindeutige Zuordnung über Kontext ist nur möglich, wenn der Beleg
  ausreichend unterscheidenden Text enthält.
- Ohne gespeicherte Annotationskoordinaten entstehen Markierungen ausschließlich
  aus der Textschicht. Es werden weiterhin keine Bounding-Boxes geschätzt oder
  gespeichert, wenn keine zuverlässige Textstelle vorliegt.
- Die Darstellung folgt den von `QPdfDocument` gelieferten Seitenkoordinaten.
  Sehr ungewöhnliche PDF-Transformationen oder beschädigte Textschichten können
  dazu führen, dass eine Markierung ausbleibt; es wird dann kein Ersatzrechteck
  erfunden.
- Persistierte Annotationen mit unbekanntem Koordinatensystem oder ungültigen
  Punkten werden protokolliert und ignoriert. Sie werden weder geschätzt noch
  stillschweigend in ein anderes Koordinatensystem umgerechnet.
- Die Feldanalyse beschreibt den zuletzt gespeicherten Parserlauf. Sie startet
  keinen Lauf und verändert kein Ergebnis. Ein grüner Status nach Regel- oder
  Profiländerung setzt daher immer einen erneuten Lauf voraus.
- Die Evidence stammt aus dem Parserergebnis. Liefert der Parser für ein Feld
  keinen feldspezifischen Auszug, zeigt die Feldanalyse den vorhandenen
  Evidence-Auszug; sie erfindet keinen passenderen Text und keine Bounding-Box.
- Die direkte PDF-Auswahl benötigt eine Textschicht. Bei reinen Scans bleibt
  die Auswahl leer; es wird weiterhin kein OCR und keine geschätzte
  Koordinate ergänzt.
- Eine Abwesenheit gilt nur nach ausdrücklicher Bestätigung als nachgewiesen.
  Ohne Annotation bleibt ein fehlender Wert `nicht extrahiert`, auch wenn er
  wahrscheinlich im PDF nicht vorkommt.

## Start

```powershell
python -m portman_pdf_lab gui
```

V09/V10 wurden nicht geändert. Es wurden keine Commits, Pushes oder Merges
ausgeführt.
