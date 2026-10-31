# Portman PDF Lab – Phase 7.3
## Robuste PDF-Textaufbereitung

## Ergebnis

Die PDF-Extraktion verwendet jetzt eine gemeinsame, qualitätsbewusste
Textaufbereitung vor Dokumenterkennung und Bankparsern. Die Parseralgorithmen
selbst wurden nicht verändert. Der Parser erhält weiterhin das bestehende
`PdfDocument`-DTO, dessen Seitentext nun aus der dokumentierten Aufbereitung
stammt.

Die Aufbereitung ist bankunabhängig. Sie kennt weder SAP noch comdirect und
enthält keine fachlichen Feld- oder Buchungsregeln.

## Bestandsanalyse und Fehlerursache

Vor Phase 7.3 wurde der Parsertext direkt mit
`pypdf.PdfReader(...).pages[i].extract_text()` erzeugt. Die Qt-PDF-Ansicht
verwendete dagegen `QPdfDocument.getAllText()`. Parser, PDF-Direktauswahl und
Textlayer konnten deshalb unterschiedliche Zeichenfolgen und Zeichenoffsets
sehen.

Die Ursache beschädigter Werte liegt in der PDF-Schrift-/Glyph-Zuordnung des
Textlayers, nicht in einem Bankparser. Das neue Verfahren bewahrt den
unveränderten pypdf-Text, bewertet ihn seitenweise und verwendet PDFium nur
bei auffälliger Qualität. Eine pauschale Ersetzung einzelner Buchstaben findet
nicht statt.

## Architektur und Datenfluss

```text
PDF-Datei
  └─ pypdf Rohtext je Seite
       └─ pdf_text_preparation
            ├─ Originaltext unverändert
            ├─ kontrolliert normalisierter Text
            ├─ Qualitätsdiagnosen je Seite/Block
            ├─ Textblöcke und Spannen
            └─ optional PDFium-Fallback mit Quads
                 └─ PdfDocument / Registry / Bankparser
                      └─ Analysebericht + Parsertraining + GUI
```

Die zentrale Implementierung liegt in
`portman-parsers/src/portman_parsers/extraction/preparation.py`.
`extract_pdf()` verwendet sie automatisch; dadurch erhalten STANDARD,
EXTENDED und COMPARE denselben vorbereiteten Dokumenttext. Der Qt-Renderer
bleibt für Darstellung und direkte Mausauswahl zuständig.

## Datenmodell

`PreparedPdf` enthält:

- Dokumenthash und Aufbereitungsversion `7.3.0`.
- `PagePreparation` pro Seite.
- Originaltext und normalisierten Text.
- Extraktor-ID und Version.
- Qualitätsstatus und Diagnosen.
- Textblöcke, Textspannen und Mappingstatus.
- Fallback-Informationen.

Die Metadaten werden im `PdfDocument` und im Analysebericht unter
`text_preparation` dokumentiert. Neue Parserläufe speichern damit Version,
Extraktor, Seitenqualität und Diagnosen; historische Läufe werden nicht
überschrieben.

## Qualitätsbewertung

Bewertet werden unter anderem:

- Unicode-Ersatzzeichen.
- Wiederholte verdächtige alphanumerische Glyph-Tokens.
- `SP010000` als Beispiel eines wiederholten Fontartefakts.
- Undruckbare Zeichen und geringe Zeichenvielfalt.
- Fehlende numerische Tokens.
- Leere beziehungsweise textlose Seiten.

Die Bewertung erfolgt auf Seiten- und Blockebene. Ein einzelnes unbekanntes
Zeichen löst keine globale Korrektur aus.

Die Qualitätsstufen sind `OK`, `SUSPICIOUS`, `UNRELIABLE` und `NO_TEXT`.
Im Schnellmodus zeigt die GUI nur einen kompakten Hinweis. Der Bericht enthält
zusätzlich Seiten, Diagnosen, Extraktoren und Mappingdetails für den
Expertenmodus.

## Sichere Normalisierung

Durchgeführt werden nur fachlich neutrale Transformationen:

- Unicode-NFKC-Normalisierung.
- Vereinheitlichung von Zeilenenden.
- Umwandlung belegter Leerzeichenglyphen in normale Leerzeichen.
- Begrenzte Leerzeichen-/Zeilenumbruchnormalisierung.

Zahlen, Vorzeichen, Währungen, ISINs und WKNs bleiben unverändert. Ein
wiederholtes Token wird nur dann entfernt, wenn es die Form eines kurzen
Präfixes mit langem Nullanteil besitzt. Die konkrete Folge `SP010000` wird
nicht als fachlicher Wert interpretiert; andere `U`, `@` oder ungewöhnliche
Zeichen werden nicht pauschal ersetzt.

Originaltext und normalisierter Text bleiben getrennt nachvollziehbar.

## Fallback-Extraktor

PDFium über `pypdfium2` ist eine optionale Abhängigkeit:

```text
portman-parsers[pdfium]
```

Sie wird nicht beim Import der DTOs geladen und ist keine Pflichtabhängigkeit
für Parser oder PDF-Lab. Windows-Binaries werden durch das pypdfium2-Paket
bereitgestellt. Die Lizenzprüfung bleibt beim Paket- und Deploymentprozess;
PyMuPDF wurde bewusst nicht als Laufzeitabhängigkeit aufgenommen.

PDFium wird nur für verdächtige Seiten aufgerufen. Der Fallback wird nur
übernommen, wenn er nicht leer ist, keine unzuverlässige Qualität meldet und
qualitativ besser beziehungsweise bei gleicher Qualität nicht wesentlich
kürzer ist. Ein schlechterer Fallback wird verworfen und dokumentiert.

PDFium-Spannen können Zeichenquads enthalten. Fehlt eine zuverlässige
Zuordnung, bleibt das Mapping `UNMAPPED`; es werden keine Rechtecke erfunden.

## Evidence, Marker und Training

Die bestehende Qt-Ansicht bleibt für Rendering, Zoom, Pan, direkte Auswahl und
Kontextmenü aktiv. Wenn PDFium einen abweichenden Text verwendet, werden keine
Qt-Marker aus unsicheren Cross-Extractor-Offsets erzeugt. Der normalisierte
Text bleibt im PDF-Layer sichtbar; automatisch grün werden nur belastbar
zuordenbare Fundstellen.

Parsertraining erhält weiterhin Originaltext, Referenzwert, Seite und
Koordinaten getrennt. Die Feldanalyse und der typisierte Trainingskontext aus
Phase 7.2 bleiben unverändert kompatibel.

## STANDARD, EXTENDED und COMPARE

Alle drei Modi verwenden exakt dieselbe dokumentierte Aufbereitungsversion.
STANDARD führt weiterhin keine trainierten Zusatzprofile aus. EXTENDED und
COMPARE erhalten denselben vorbereiteten Eingangstext; nur die Regelprofile
unterscheiden sich.

Damit sind zwei Regressionsebenen sichtbar:

1. Die Parserimplementierung bleibt unverändert.
2. Ein neuer, besserer Eingangstext kann absichtlich ein anderes Ergebnis
   liefern.

Wirtschaftliche Cashflows, Steuern und Gebühren werden durch die Aufbereitung
nicht erzeugt. Golden-Referenzen und historische Parserläufe bleiben erhalten.

## Tests

Ergänzt wurden Tests für:

- Zahlenpräzision mit `0,733`, `2,20` und `1,61`.
- Unicode- und Zeilenumbruchnormalisierung.
- wiederholte Glyph-Tokens ohne Beschädigung von ISIN/WKN.
- Original-/Normaltext-Trennung.
- Seitenblöcke, Diagnosen und Aufbereitungsversion.
- Extraktionsmetadaten im `PdfDocument`.
- normale PDFs und textlose PDFs.
- vorhandene PDF-Lab-Feldanalyse, Training, Marker, Zoom und Navigation.

Aktuelle Suite-Ergebnisse:

```text
portman-parsers: 123 passed
portman-pdf-lab: 108 passed
```

Das angegebene Originaldokument
`Dividendengutschrift_0,733_St._716460_(SAP_SE_O.N.)_vom_21.05.2024_23BC54.pdf`
war im Arbeitsbereich nicht vorhanden und wurde daher nicht in Tests oder
Berichte kopiert. Für CI bleibt ein anonymisiertes/synthetisches Fixture die
bevorzugte Variante.

## Performance und Einschränkungen

- Normale Seiten werden mit einem zusätzlichen linearen Normalisierungsschritt
  verarbeitet.
- PDFium wird nur bei auffälligen Seiten gestartet.
- Die optionale PDFium-Auswertung ist bei vielen verdächtigen Seiten teurer
  als pypdf, liefert dafür Text- und Positionsinformationen.
- Reine Bild-PDFs bleiben `NO_TEXT`; OCR ist weiterhin nicht automatisch aktiv.
- Bei mehrdeutigen Textabgleichen wird keine grüne Koordinate erzeugt.
- Die Aufbereitung verbessert Eingangstext und Evidence-Metadaten, ersetzt aber
  keine fachliche Parserregel und keine Golden-/Regressionfreigabe.

Keine Änderungen an Portman V09/V10 wurden vorgenommen. Es wurden keine
Commits, Pushes oder Merges ausgeführt.
