# Portman V09 – Produktive Abnahme, Kopierfunktion und Steuerjahresübersicht

Stand: 23.10.2026

Branch: `feature/production-acceptance-copy-tax-summary`

Basis: `main` / `334ed8f` (PR #24 enthalten)

## Gesamtbewertung

**PASS MIT HINWEISEN für die neuen Funktionen; produktive Datenabnahme P1 offen.**

Die globale Kopierfunktion und die neue kontenbezogene Steuerjahresübersicht
sind implementiert und auf temporären Datenbanken getestet. Die produktive
Datenbank ist technisch integer und enthält inzwischen 37 `booking_details`.
Die comdirect-Steuerdetail-CSV ist jedoch produktiv **nicht importiert**,
`fee_links` ist weiterhin leer und 37 zur Laufzeit abgeleitete Käufe besitzen
keine persistierte Performance-Depotzuordnung. Es wurde keine produktive
Reparatur ausgeführt.

## Sicherheitsnachweis

`data/v09/portfolio.sqlite` wurde ausschließlich per SQLite-URI `mode=ro` mit
`PRAGMA query_only=ON` geöffnet. Für Prüfungen der Repository-Logik wurde über
die SQLite-Backup-API ein temporärer Snapshot erstellt. Original-PDFs und die
produktive Datenbank blieben unverändert.

```sql
PRAGMA integrity_check;  -- ok
PRAGMA foreign_key_check; -- 0 Zeilen
```

## Produktive Steuerabnahme 2026

| Kennzahl | comdirect Soll | Produktiv/Portman | Bewertung |
|---|---:|---:|---|
| Steuerpflichtige Erträge | 523,07 € | 523,07 € | PASS |
| Verbrauchter Freibetrag | 411,00 € | 200,80 € | CSV-Abdeckung fehlt |
| BMG nach FSA | 112,07 € | n. v. | CSV-Abdeckung fehlt |
| Kapitalertragsteuer | 28,02 € | 28,02 € | PASS |
| Solidaritätszuschlag | 1,51 € | 1,51 € | PASS |
| Kirchensteuer | 0,00 € | 0,00 € | PASS, belegte Null |
| Steuerpflichtige Vorabpauschalen | 192,24 € | 192,24 € / 3 | PASS |
| Fachliche Detailzeilen | 39 | 27 automatisch | 12 CSV-Zeilen fehlen |

SQL-Nachweis des fehlenden CSV-Imports:

```sql
SELECT COUNT(*)
FROM import_model_records r
JOIN imports i ON i.id=r.import_id AND i.active=1
WHERE r.kind='tax_details';
-- 0
```

Die 27 PDF-/Buchungszeilen enthalten die wirtschaftlichen Vorgänge korrekt.
Die fehlenden 12 Zeilen sind überwiegend belegte Nullereignisse und die nur im
CSV vollständig nachgewiesenen FSA-/BMG-Werte. Ein temporärer Import der realen
CSV ergibt 39/39 Zeilen, 411,00 € FSA und 112,07 € BMG nach FSA, ohne eine
Transaktion oder ein Steuerereignis anzulegen.

## Gebühren, Links und Performance

| Prüfung | Soll | Ist | Bewertung |
|---|---:|---:|---|
| `booking_evidence` | 38 | 38 | PASS |
| `booking_details` | 37 | 37 | PASS |
| `fee_links` | 4 | 0 | HINWEIS/P1 |
| Fokus-Dividenden fachlich erkennbar | 6 | 6 read-only Treffer | PASS zur Laufzeit |
| Finanzreport-Saldointervalle | 27 | 27 centgenau | PASS |

Gebührennachweise:

- A111X9, Transaktion 330: 0,46 €
- A0S9GB, Transaktion 348: 0,27 €
- SAP 716460, Transaktion 272: 0,43 €

Die vier besteuerten Ausschüttungen sind fachlich eindeutig erkennbar:
A0H074 1,67 €, A0D8QZ 10,36 €, 593399 6,48 € und A0LEW8 6,38 €.
SAP und Fresenius werden ebenfalls eindeutig mit ihren Dividendenbuchungen
zusammengeführt. Der seit PR #24 vorhandene konservative read-only Matcher
verhindert dabei doppelte Detailzeilen und Steuerzählungen, auch ohne
persistierte `fee_links`.

Persistenzseitig bleiben zwei Abweichungen:

1. `fee_links` enthält 0 statt 4 Zeilen. Die vier TAX-Hilfsbuchungen bleiben
   `affects_cash=false`; dadurch entsteht keine doppelte Cash- oder Steuerwirkung.
2. `booking_details` werden zur Laufzeit zu 37 Käufen abgeleitet. Diese 37
   Käufe haben jedoch weiterhin keinen `performance_depot_key`; nur 35 andere
   Ertrags-/Gebührenbuchungen sind `Depot 4764924` zugeordnet. Damit ist die
   gebühreninklusive Depotperformance produktiv noch nicht abschließend
   abnehmbar.

Kontosaldennachweis:

```text
Schlusssaldo - Anfangssaldo - Summe Cashbuchungen = 0,00 EUR
27 von 27 Finanzreport-/Kontointervallen; maximale Centabweichung 0,00 EUR.
```

Empfohlene Reparatur bleibt ein separater, kontrollierter Vorschauprozess auf
einer Datenbankkopie: ausschließlich eindeutige `booking_details` auf das
gemappte `Depot 4764924` nachziehen und vier besteuerte Ereignisse verlinken.
Keine automatische produktive Ausführung.

## Kauf vom 07.10.2026

Der Beleg ist als `booking_evidence` vorhanden:

- Import-ID 57
- ISIN LU2090063673 / LYX05A
- Datum 07.10.2026
- Gesamtbetrag 1,33 €
- Gebühr 0,00 €

Im Zeitraum 03.10.–11.10.2026 existiert keine Finanzreportbuchung über 1,33 €.
Der Vorgang ist daher fachlich als **„Beleg vorhanden – Gegenbuchung fehlt“**
zu behandeln. Es wurde weder eine Kauftransaktion erfunden noch eine unsichere
Zuordnung vorgenommen.

## Globale Kopierfunktion

Die Funktion wird einmal beim Programmstart installiert und gilt auch für
später erzeugte Dialoge:

- `Ctrl+A` selektiert alle sichtbaren Zellen der aktiven Tabelle;
- `Ctrl+C` kopiert sichtbare, formatierte Displaywerte;
- Zell-, Bereichs-, Zeilen- und Spaltenselektion wird unterstützt;
- Sortierung, Proxy-Filter, visuelle Spaltenreihenfolge und ausgeblendete
  Spalten werden berücksichtigt;
- Standard-Kontextmenü enthält „Kopieren“ und „Alles auswählen“;
- vorhandene anwendungsspezifische Kontextmenüs bleiben unverändert;
- Labels sind per Maus und Tastatur auswählbar;
- Eingabefelder behalten ihre nativen Bearbeitungs- und Kopierfunktionen.

Die Lösung wirkt auf `QTableView`, `QTableWidget`, `QTreeView`, `QTreeWidget`
und `QLabel` in sämtlichen GUI-Modulen, ohne Modelle oder Daten zu verändern.

## Neue Ansicht „Steuerliche Jahresübersicht“

Die Ansicht ist im Menü „Werkzeuge“ erreichbar und bietet:

- Steuerjahr-, Institut- und Kontoauswahl;
- optionale Institutssumme über mehrere Konten;
- elf geforderte Steuerkennzahlen;
- Bankwert, Portman-Wert und Differenz;
- `n. v.` für unbekannte und `0,00` für belegte Nullwerte;
- Quellenname, Referenzzeilenzahl und aus dem Beleg abgeleiteten Datenstand;
- kopierbare Tabellenzellen durch die globale Kopierfunktion.

Verlustverrechnungstöpfe werden ausschließlich aus dokumentierten Banksalden
gezeigt. Sie werden nicht aus historischen Gewinnen oder Verlusten geschätzt.
Die realen Referenzdaten liefern in der temporären Abnahme exakt 523,07 €,
411,00 €, 112,07 €, 28,02 €, 1,51 € und 0,00 € Kirchensteuer.

## Regressionstests

- Zieltests für Steuerjahresübersicht, reale CSV und globale Kopierfunktion:
  20 bestanden
- vollständige Pytest-Suite: 1.115 bestanden, 12 erwartete Skips,
  5 Subtests bestanden
- zwei bestehende Qt-Deprecation-Warnungen in `tax_detail_view.py`
- rekursiver PDF-Lauf: 126 strukturiert, 0 Parserfehler

## Dokumentbestand

Der aktuelle Verzeichnisstand umfasst 126 physische PDFs, nicht mehr die ältere
102-PDF-Referenz. Der rekursive Parserlauf erkennt 126/126 strukturiert und
meldet 0 Parserfehler. Die produktive Datenbank enthält 94 aktive Imports und
121 Dokumentdatensätze; die Zähler sind deshalb nicht unmittelbar mit einem
vollständigen Neuimport des inzwischen erweiterten Ordners gleichzusetzen.
