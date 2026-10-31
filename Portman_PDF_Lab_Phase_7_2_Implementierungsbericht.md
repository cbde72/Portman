# Portman PDF Lab – Phase 7.2 Implementierungsbericht

## Ergebnis

Phase 7.2 und die ergänzende Schnell-/Expertenmodus-Anforderung sind umgesetzt.
Die bestehenden Parser, wirtschaftlichen DTOs, Rule Engine, Goldens und
Referenzwerte wurden nicht ersetzt. V09/V10 werden nicht importiert.

## PDF-Bibliothek und Lizenz

Die direkte Selektion verwendet die bereits vorhandene Qt-PDF-Engine aus
PySide6. Die installierten Paketmetadaten weisen PySide6 als
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` aus. PDF Lab fügt keine
statische Qt-Verknüpfung oder veränderte Qt-Bibliothek hinzu.

PyMuPDF wurde geprüft, aber nicht übernommen. Die lokal verfügbaren
Paketmetadaten nennen eine Dual-Lizenz aus AGPL 3.0 oder kommerzieller
Artifex-Lizenz. Damit wäre eine direkte Aufnahme ohne zusätzliche
Lizenzentscheidung nicht angemessen. `pypdfium2` wäre mit BSD-3-Clause/
Apache-2.0 grundsätzlich eine Alternative, ist aber nicht erforderlich, weil
Qt PDF Text und echte Koordinaten bereits zuverlässig liefert.

Die Paketabhängigkeit ist auf den getesteten Bereich
`PySide6>=6.9.2,<6.11.2` begrenzt. Die isolierte Python-3.14-Abnahme verwendet
PySide6 6.11.1. Version 6.11.3 bleibt wegen des zuvor beobachteten
Windows-DLL-Ladefehlers ausgeschlossen.

## Direkte PDF-Selektion

`DirectPdfView` rendert die echte PDF-Seite über `QPdfDocument.render` und
transformiert Mauspositionen in das PDF-Punktkoordinatensystem. Die Auswahl
entsteht mit `QPdfDocument.getSelection`; Text, Zeichenindizes und
`QPdfSelection.bounds()` werden übernommen. Es werden keine Rechtecke geraten.

Persistierte Koordinaten enthalten:

- `coordinate_system: PDF_POINTS`
- PDF-Quads pro Textfragment
- Seitenbreite und Seitenhöhe
- Rotation
- Zeichenanfang und -ende
- Dokument-ID und SHA-256
- Feldpfad

Die Anzeige transformiert diese PDF-Punkte bei jedem Paint-Vorgang neu. Damit
bleiben Markierungen bei Zoom, DPI-Änderung, Scrollen, Resizing und
unterschiedlichen Seitengrößen stabil. Die Seitendrehung wird aus `/Rotate`
gelesen. Mausrad-Zoom, Buttons, Pan, Seitennavigation und Scrollposition bleiben
funktionsfähig. Original-PDFs werden ausschließlich gelesen.

Das Kontextmenü auf der gerenderten Seite bietet Kopieren, Zuordnen,
Referenzübernahme, neue Felddefinition, Bearbeiten, Entfernen und Hervorheben.
Annotationen werden versioniert beziehungsweise deaktiviert, nicht
überschrieben. Mehrere fachliche Zuordnungen derselben Fundstelle bleiben
möglich.

PDF → Tabelle, Tabelle → PDF und Parsertraining → PDF verwenden dieselben
Feldpfade und PDF-Quads. Persistierte Annotationen werden nach Neustart erneut
geladen. Für schwierige oder textlose PDFs bleibt der synchronisierte Textlayer
sichtbar; ohne Textlayer wird OCR ausdrücklich als erforderlich angezeigt, aber
nicht automatisch gestartet.

## Dokumenttypspezifische Feldkataloge

Versionierte YAML-Kataloge werden nach Bank, Parser, Dokumenttyp und Layout
aufgelöst. Alle tatsächlich als `implemented=True` registrierten Handler sind
abgedeckt:

- comdirect Kauf, Verkauf, Einlösung, Dividenden-/Ertragsgutschrift,
  Investment-Ausschüttung, Dividendensteuer, Vorabpauschale, MiFID II und
  Finanzreport
- die entsprechenden Portfolio-Performance-comdirect-Varianten
- FNZ/Finvesto Umsatzabrechnung und Depotauszug
- Bank-of-Scotland-Kontoauszug

Nicht implementierte Allowlist-Einträge werden nicht als unterstützt
ausgegeben. Generische und Kontodokumente erhalten keine
Wertpapierhandelspflichten.

Katalogbedingungen verwenden ausschließlich deklarative Operationen:
`REQUIRED_UNLESS_VALID`, `PRESENT`, `EQUALS`, `ALL` und `ANY`. Es wird kein
Python-Ausdruck aus YAML ausgeführt. ISIN und WKN bleiben getrennt. Eine valide
ISIN kompensiert die WKN; fehlen alle belegten Identifikationen, wird die
Abhängigkeit rot. `trade.venue` ist optional und fehlt grau. Kontoauszüge,
Depotaufstellungen, MiFID-Kosten und Steuerdokumente haben eigene Sollfelder.
Informatorische MiFID-Kosten erzeugen durch diese Anzeige keine Cashflows.

Die vollständige Soll-Feldansicht unterscheidet erkannte, fehlende,
prüfpflichtige und nicht anwendbare Werte. Fehlende Katalogfelder bleiben
sichtbar. Zeilenfarben werden zusätzlich immer als Textstatus ausgegeben.

## Schnellmodus und Expertenmodus

Die Toolbar enthält `Schnell | Experte`. Eine neue Installation startet im
Schnellmodus; die Wahl wird sofort in `QSettings` gespeichert.

Im Schnellmodus ist nur die kompakte Feldanalyse neben Dokumentliste und PDF
sichtbar. Technische Pfade, Evidence-Details und Parserregeln sind ausgeblendet.
Fehlende optionale Felder bleiben standardmäßig verborgen und erscheinen über
`Alle Felder anzeigen`. Pflichtfehler, relevante erkannte optionale Werte und
Prüffälle bleiben sichtbar.

`Feld trainieren` übernimmt Dokument, Bank, Parser, Dokumenttyp und Zielfeld.
Der Benutzer markiert nur noch direkt im PDF und bestätigt den Wert im
typgerechten Editor. Danach werden Annotation und ein deklarativer Kandidat in
derselben Datenbasis angelegt. `Regel prüfen`, `Regel freigeben` und
`Profil aktivieren` bleiben drei getrennte Aktionen. Eine einzelne erfolgreiche
Probe meldet verständlich, dass weitere Beispiele empfohlen sind.

Der Expertenmodus stellt alle elf aktuellen Reiter, STANDARD/EXTENDED/COMPARE,
Parservergleich, vollständige Evidence, Golden-Tests, Kandidaten,
Profilversionen, Import/Export, Rollback und Qualitätsdaten wieder her. Ein
Moduswechsel führt keinen Parserlauf aus und bewahrt Dokument, Seite, Zoom,
Pan, Auswahl und ungespeicherte Eingaben.

### Geführtes Schnelltraining ohne Reiterwechsel

Der Schnellmodus besitzt nun einen ein- und ausblendbaren vierten
Splitterbereich direkt neben PDF und Feldanalyse. Er zeigt ausschließlich:

- ausgewähltes Feld und bisherigen Parserwert,
- markierten PDF-Text,
- typgerechten Referenzwerteditor,
- aktuellen Schritt und nächste Aktion,
- verständliche Kurzresultate der Regelprüfung.

Der Fortschritt lautet:
`Feld auswählen → PDF markieren → Bestätigen → Regel prüfen → Freigeben → Aktivieren`.
Bank, Parser, Handler, Dokumenttyp, Feldpfad und Regelparameter werden intern
aus demselben `TrainingContext` übernommen, den auch der Expertenmodus nutzt.
Ein Reiterwechsel und ein modaler Zuordnungsdialog sind im Schnellworkflow
nicht mehr erforderlich.

Bei der PDF-Auswahl werden Text, Seite, SHA-256 und echte PDF-Quads direkt in
den Seitenbereich übertragen. Der Referenzwert kann im kataloggesteuerten
Editor korrigiert, bestätigt oder ausdrücklich als nicht im PDF vorhanden
markiert werden. Bestätigung speichert Annotation und Referenz, ändert aber
nicht den Parserwert und färbt die Zeile daher nicht vorzeitig grün.

Der Regelvorschlag verwendet als Quelltext die vollständige PDF-Zeile um die
Auswahl. Dadurch wird aus der Auswahl `XETRA` in `Handelsplatz: XETRA` ein
Label-/Wert-Kandidat, der auch `Tradegate` erkennt. Test, Freigabe und
Aktivierung bleiben getrennte, explizite Aktionen. `Erneut prüfen` startet
ausschließlich EXTENDED und stellt ursprünglichen Wert, EXTENDED-Wert,
Referenz und Status im Seitenbereich gegenüber.

Der Panelzustand bleibt beim Wechsel in den Expertenmodus erhalten. Dort ist
der Bereich verborgen, während das vollständige bisherige Parsertraining
unverändert verfügbar bleibt. Beim Rückwechsel wird das begonnene
Schnelltraining fortgesetzt.

Offscreen-Sichtprüfung:

- [Schnellmodus](Portman_PDF_Lab_Schnellmodus.png)
- [Expertenmodus](Portman_PDF_Lab_Expertenmodus.png)

## Tests

Die automatisierte Abnahme umfasst direkte Mausauswahl, Wort-/Mehrzeilentext,
Quads, Rotation, Zoom, Pan, Resize, Kontextmenü, Markierungspersistenz,
bidirektionale Navigation, Textlayer-Fallback, Katalogbedingungen,
Dokumenttypwechsel, Statusfarben, Schnellmodus, Expertenmodus,
Zustandserhaltung und gemeinsame Persistenz.

Gesamtergebnis:

```text
227 passed in 19.11s
```

Der generalisierte Handelsplatzkandidat erkennt sowohl `XETRA` als auch
`Tradegate` und enthält den konkreten Beispielwert nicht im Regex.

## Wheel-Isolation

Beide Pakete wurden als Wheels gebaut und in eine frische Python-3.14-Umgebung
installiert. Ergebnis:

```text
ISOLATION_OK mode=quick expert_tabs=11 selection=XETRA quads=1 forbidden=none
```

Damit wurden Schnellmodus-Standard, Expertenansicht, echte Qt-PDF-Auswahl,
PDF-Quads und die Abwesenheit von `portfolio_v5`, `pdf_plugins` und
`portman.gui` bestätigt.

## Bekannte Grenzen und Phase 8

- PDFs mit defekter Zeichenreihenfolge können auch bei korrekten Quads einen
  ungewöhnlich sortierten Auswahltext liefern; Textlayer und manuelle
  Bestätigung bleiben verfügbar.
- OCR ist bewusst nicht Bestandteil dieser Phase.
- Komplexe bedingte Pflichten sollten in Phase 8 um weitere geprüfte
  deklarative Operatoren und fachlich freigegebene Katalogfixtures erweitert
  werden.
- Automatisches Layout-Clustering oder selbsttätige Regelfreigabe bleiben
  ausgeschlossen.

## Start

```powershell
python -m portman_pdf_lab gui
```

Es wurden keine Commits, Pushes oder Merges ausgeführt.
