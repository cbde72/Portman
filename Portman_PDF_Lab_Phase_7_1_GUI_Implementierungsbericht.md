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
- Sichtbarkeitsschalter, Feldbereich, Persistenz und Klicknavigation.

Vollständige Regression der betroffenen Pakete:

```text
portman-pdf-lab: 72 passed in 7.28s
portman-parsers: 119 passed in 1.51s
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

## Start

```powershell
python -m portman_pdf_lab gui
```

V09/V10 wurden nicht geändert. Es wurden keine Commits, Pushes oder Merges
ausgeführt.
