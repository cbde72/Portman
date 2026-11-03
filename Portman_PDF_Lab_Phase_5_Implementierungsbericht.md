# Portman PDF Lab – Phase-5-Implementierungsbericht

**Datum:** 30.10.2026  
**Pakete:** `portman-parsers 0.6.0`, `portman-pdf-lab 0.6.0`  
**API:** `0.6`  
**Schema:** `1.5.0`

## 1. Neue Projektstruktur

`portman-parsers` bleibt der autonome Parserkern. Neu sind der unabhängige
FNZ/finvesto-Parser und dessen native Tests. `portman-pdf-lab` enthält neu das
SQLite-Referenzrepository, Qualitätsauswertung, Referenz-/Versionsvergleich,
erweiterte Batchanalyse und die PySide6-Oberfläche. Es bestehen keine Imports
aus `portfolio_v5`, `pdf_plugins` oder V09/V10.

## 2. Implementierte Parser und Dokumenttypen

Aktiv sind Bank of Scotland `kontoauszug` sowie FNZ/finvesto
`umsatzabrechnung` und `depotauszug`. FNZ erkennt Käufe, Verkäufe,
Ausschüttungen, Wiederanlagen, Gebühren, Steuern, Fremdwährung, ISIN,
Stückzahl, Kurs, Kurswert, Settlement und Buchungsdatum. Mengen, Preise,
Währungen sowie Brutto-/Gebühren-/Steuer-/Settlement-Beziehungen werden
geprüft.

Die FNZ-Umsatzabrechnung erzeugt Wirtschafts- und Wertpapierereignisse. Ein nur
im Beleg genannter Settlementbetrag bleibt `EXPECTED`, solange kein Konto
belegt ist. Ausschüttung und Wiederanlage werden getrennt modelliert, ohne
zusätzlichen tatsächlichen Geldzufluss. Der Depotauszug erzeugt ausschließlich
einen `DepotSnapshot`; Positionssumme und Gesamtwert werden verglichen.

## 3. Konto-, Depot- und Geldflussmodell

Das Phase-4-Modell bleibt verbindlich. FNZ erfindet weder Verrechnungskonto noch
Depot-Konto-Link. Ein tatsächliches Konto kann später über Evidence und
`DepotAccountLink` zugeordnet werden. Funktionen bleiben unabhängig vom
Kontotyp. Erwartete Settlements werden nicht als bestätigte Kontobuchungen
ausgegeben.

## 4. Steuern und Gebühren

Die Phase-4-Verträge für `TaxEvent`, Vorabpauschale und Gebühren bleiben
erhalten. FNZ-Steuerabzüge und Transaktionsentgelte sind eigenständige,
belegbezogene Komponenten. Informatorische Kosten bleiben cash-neutral. Die
Vorabpauschalen-Handler für comdirect, Baader und ING bleiben deaktiviert.

## 5. GUI-Funktionen

Das maximierte PySide6-Hauptfenster besitzt verschiebbare Bereiche für
Dokumente, Original-PDF und Analyse. Vorhanden sind Suche, PDF-Seitenwechsel,
Zoom, Hintergrundanalyse, Fortschritt, Abbruch sowie die Reiter Übersicht,
Konto, Depot, Buchungen, Geldflüsse, Gebühren & Kosten, Steuern,
Referenzvergleich und Issues. Evidence springt zur belegten Seite und zeigt
den Textauszug. Nicht vorhandene Textkoordinaten werden nicht erfunden.

Parserläufe werden beim GUI-Import gespeichert. Manuelle Freigabe oder
Korrekturmarkierung wird in der Reviewhistorie protokolliert. Listen werden nur
bei Ergebnissen aktualisiert; PDF-Seiten lädt Qt bedarfsgesteuert.

## 6. SQLite-Schema und Reviewworkflow

Schema-Version 1 enthält `documents`, `parser_runs`, `reference_values`,
`reference_history` und `reviews`. WAL, Foreign Keys und `BEGIN IMMEDIATE`
sichern atomare Schreibvorgänge. Dokumente werden über SHA-256 wiedererkannt.
Parserläufe sind versionsbezogen und überschreiben weder frühere Ergebnisse
noch Sollwerte. Sollwertänderungen erfordern Benutzer, Grund und Historie.

Reviewzustände: `NOT_REVIEWED`, `IN_REVIEW`, `APPROVED`, `REJECTED` und
`NEEDS_CORRECTION`. Kategorien umfassen Erkennung, Felder, Geldfluss,
Depotbestand, Steuern, Gebühren, Referenzen und Evidence. Ein erfolgreicher
Lauf wird nicht automatisch freigegeben.

## 7. Soll-/Ist- und Parservergleich

Referenzwerte werden feldweise gegen einen gespeicherten Lauf verglichen.
Versionen zeigen hinzugekommene, verschwundene und geänderte Pfade sowie die
Laufzeitdifferenz. Geldbetrags-, Währungs- und Cashflowänderungen werden als
kritisch hervorgehoben. Listen mit stabilen wirtschaftlichen IDs werden nach
diesen IDs statt nur nach ihrer Position verglichen.

## 8. Batchanalyse und Export

Die rekursive Batchanalyse behandelt Einzelfehler isoliert, meldet Fortschritt,
ist abbrechbar und erkennt identische PDFs per SHA-256. JSON bleibt der
vollständige Bericht; CSV liefert Dokument, Hash, Parser, Handler, Status und
Laufzeit. Die GUI führt Parserarbeit außerhalb des Hauptthreads aus.

## 9. Qualitätsmetriken

Eine Quote wird ausschließlich berechnet, wenn bestätigte Referenzfelder
existieren. Ohne Referenzbasis bleibt der Score `None`. Technischer Erfolg ist
keine fachliche Freigabe.

## 10. Tests

Die Suite umfasst FNZ-Umsatz und -Depotauszug, Ausschüttung/Wiederanlage,
Gebühren, Snapshot, unbekannte Kontozuordnung, Evidence, SQLite-Integrität,
Reimport, Review- und Sollwerthistorie, Versionsvergleich, PDF-Navigation,
GUI-Smoke, Batchfehler, Hash-Deduplizierung, Abbruch und CSV-Export.

Abschließendes Ergebnis: **124 Tests bestanden** (`portman-parsers`: 94,
`portman-pdf-lab`: 30). Darin enthalten sind die bestehenden Bank-of-Scotland-,
Gebühren-, Steuer- und Architekturregressionen.

## 11. Reproduzierbarer Benchmark

Synthetische Bank-of-Scotland-PDFs, Python 3.14 auf dem Entwicklungsrechner:

| Messung | Ergebnis |
|---|---:|
| Einzeldatei, Median aus 10 Läufen | 5,910 ms |
| Batch, 20 unterschiedliche PDFs | 356,723 ms |
| Batch pro Dokument | 17,836 ms |

Die Werte sind synthetische Orientierungswerte und keine produktive
Layoutfreigabe.

## 12. Isolationstest

Beide Pakete wurden als Wheels gebaut und unter
`C:\Users\chris\Desktop\PortmanPDFLabPhase5Isolation` in eine frische venv
installiert. Installierte direkte Laufzeitgrenzen sind `pypdf>=6,<7`,
`portman-parsers>=0.6,<0.7` und `PySide6>=6.8,<7`.

Mit leerem `PYTHONPATH` wurden erfolgreich geprüft:

- Bank-of-Scotland-Import;
- FNZ-Umsatzabrechnung und FNZ-Depotauszug;
- SQLite-Persistenz und Wiederladen zweier Läufe;
- manueller Revieweintrag;
- Parservergleich;
- Batchanalyse einschließlich defekter PDF;
- JSON-, CSV- und Referenzexport;
- offscreen GUI-Start mit neun Reitern;
- Laden und Navigieren einer PDF-Seite.

Der effektive `sys.path` enthielt ausschließlich die externe Umgebung und deren
`site-packages`, keinen Portman-Repositorypfad. Geladene verbotene Module:
**keine** (`portfolio_v5`, `pdf_plugins`, `portman.gui`).

## 13. Validierungsstatus und offene Probleme

Bank of Scotland und FNZ sind in Phase 5 ausschließlich mit synthetischen,
öffentlichen Charakterisierungsdaten getestet. Es lagen keine anonymisierten,
ausdrücklich freigegebenen realen Kunden-PDFs für eine produktive Layoutfreigabe
vor. Präzise PDF-Textkoordinaten, OCR, breitere historische FNZ-Layouts und
komplexe Fremdwährungssteuerblöcke benötigen bestätigte Referenzdokumente.

## 14. Empfehlungen

1. Freigegebene, anonymisierte FNZ-Goldens annotieren und Layoutvarianten härten.
2. Reviewkategorien und Sollwerteditor in der GUI weiter ausbauen.
3. Koordinatenfähigen Evidence-Adapter ergänzen, sobald reale PDF-Extraktion
   belastbare Bounding Boxes liefert.
4. Erst danach den nächsten Bankparser aktivieren.

## 15. V09/V10-Unverändertheit

Bestehende V09-/V10-Parser, GUI, Datenbanken, Stores, Konfigurationen und Tests
wurden nicht verändert. `pdf_plugins/fnz_finvesto.py` wurde nur als
schreibgeschützte Referenz gelesen. Es wurden keine Commits, Pushes oder Merges
ausgeführt.
