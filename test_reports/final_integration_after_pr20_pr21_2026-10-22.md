# Portman V09 – Abschließende Gesamtintegration nach PR #20 und #21

Prüfdatum: 22.10.2026  
Codebasis: `main` / `1c91ae9`

## Gesamturteil

**PASS mit zwei nicht blockierenden Betriebshinweisen.** Alle 102 physischen
comdirect-PDFs werden strukturiert erkannt. Der Import der 93 eindeutigen
Dateiinhalte in eine neue temporäre SQLite-Datenbank ist vollständig,
idempotent und wirtschaftlich konsistent. MiFID-II-Kosteninformationen bleiben
cash-, bestands- und performanceneutral.

Die produktive Datei `data/v09/portfolio.sqlite` wurde ausschließlich mit
SQLite `mode=ro&immutable=1` geöffnet und nicht verändert.

## 1. Codebasis und Umgebung

Die Historie von `main` enthält:

| PR | Commit | Ergebnis |
|---|---|---|
| #19 | `55b2eda` | Steuer-/Dividenden- und Kaufgebührenabgleich enthalten |
| #21 | `ac42c92` | comdirect MiFID-II-Kostenimport enthalten |
| #20 | `1c91ae9` | Windows-OCR-Härtung und Diagnostik enthalten; aktueller HEAD |

`main` entspricht `origin/main`. Bereits vorhandene unversionierte Testordner
und Berichte wurden nicht verändert oder entfernt.

`pip check` meldet zwei bereits vorhandene Metadatenkonflikte:

```text
docstring-to-markdown 0.17 benötigt importlib-metadata>=3.6,
installiert ist importlib-metadata 0.5.
spyder 6.1.3 benötigt importlib-metadata>=4.6.0,
installiert ist importlib-metadata 0.5.
```

Diese Pakete liegen außerhalb des Portman-Importpfads. PDF-, OCR-, SQLite- und
GUI-Regressionstests liefen trotzdem vollständig erfolgreich. Die Umgebung
sollte separat bereinigt werden, um künftige Werkzeugprobleme zu vermeiden.

## 2. PDF-Gesamttest

Rekursiv geprüft wurde:

`C:\Users\chris\Desktop\history\comdirect\2026`

| Ergebnis | Anzahl |
|---|---:|
| Physische PDF-Dateien | 102 |
| Eindeutige SHA-256-Inhalte | 93 |
| Identische Dateikopien | 9 |
| Strukturiert erkannt | 102 |
| Generisch erkannt | 0 |
| Parserfehler | 0 |
| MiFID-II-Kosteninformationen | 23 |

Verteilung der 93 eindeutigen Inhalte:

| Handler | Anzahl |
|---|---:|
| Finanzreport | 9 |
| Wertpapierkauf | 38 |
| Investment-Ausschüttung | 18 |
| Vorabpauschale | 3 |
| Inländische Dividenden-Steuermitteilung | 2 |
| MiFID-II-Kosteninformation | 23 |

Die neun Kopien wurden anhand identischer vollständiger SHA-256-Hashes erkannt
und nicht ein zweites Mal wirtschaftlich importiert. Dazu gehören ein
Finanzreport, LS9AVX, A2H57N, LYX05A sowie fünf Steuermitteilungen.

## 3. Isolierter SQLite-Gesamtimport

Die GUI-Route wurde nachgebildet:

1. `portfolio_v5.pdf_importer.parse_pdf()` mit OCR und registrierten Plugins;
2. Kontozuordnung der Vorschau auf `Depot 4764924`;
3. `RepositoryV09.commit_batches()`;
4. erneuter Import derselben Quellen.

Die MiFID-II-Quelle `Kosteninformation Sparplan 38` wurde – wie in der GUI
erforderlich – explizit dem aktiven Zieldepot zugeordnet.

Finale Datenbankzähler:

| Tabelle/Fachobjekt | Anzahl |
|---|---:|
| Aktive eindeutige Imports | 93 |
| Transaktionen | 366 |
| Archivierte Dokumentdatensätze | 120 |
| Importe ohne Dokumentablage | 0 |
| MiFID-II-`cost_reports` | 23 |
| Steuerereignisse | 23 |
| `booking_details` | 37 |
| Kaufbelege als `booking_evidence` | 38 |
| `fee_links` | 4 |

Mehrere Dokumentdatensätze pro PDF sind bei Finanzreports fachlich korrekt,
weil die einzelnen Konto-/Depotbereiche getrennt archiviert werden.

### Idempotenz und Dubletten

- Die 70 wirtschaftlichen Dokumente wurden beim Wiederholungslauf nicht erneut
  aktiv gespeichert.
- Alle 23 MiFID-II-Dokumente erhielten beim Wiederholungslauf den Status
  `duplicate`.
- Sämtliche obigen Zähler waren vor und nach dem Wiederholungsimport identisch.
- Keine doppelten Kombinationen aus Konto und `external_id` wurden gefunden.
- `PRAGMA integrity_check` ergab `ok`.
- `PRAGMA foreign_key_check` ergab keine Zeile.

### MiFID-II-Neutralität

Vor und nach dem Import der 23 Kosteninformationen wurden vollständig
verglichen:

- Transaktionsanzahl und Cashsumme;
- Bestände einschließlich Stückzahl und Wert;
- Performance-Transaktionen einschließlich Betrag, Gebühren und Steuern.

Alle drei Vergleichsmengen waren identisch. Die Kosteninformationen erzeugen
weder Buchungen noch Gebühren-Cashflows und verändern keine Bestände oder
Performance.

### Steuer- und Dividendenverknüpfung

Vier tatsächlich besteuerte Ausschüttungen besitzen eine fachliche
`related_transaction_id` und genau einen `fee_link`:

| Wertpapier | Wirtschaftliche Steuer |
|---|---:|
| A0H074 | 1,67 EUR |
| A0D8QZ | 10,36 EUR |
| 593399 | 6,48 EUR |
| ausländische Investment-Ausschüttung IE00B1FZS350 | 6,38 EUR |

Fresenius 578560 und SAP 716460 sind als reguläre Dividenden mit Nullsteuer
verbunden, ohne künstlichen `fee_link` und ohne zweite Steuerbelastung.
A0LEW8 und die übrigen belegten Nullsteuer-Ereignisse bleiben korrekt von
unbekannten Beträgen getrennt.

### Kaufgebühren

Die Finanzreportbuchungen wurden mit den Kaufbelegen angereichert, ohne eine
zweite Kauftransaktion zu erzeugen. Unter anderem wurden nachgewiesen:

| Referenzfall | Strukturierte Gebühr |
|---|---:|
| A111X9 vom 07.09.2026 | 0,46 EUR |
| A0S9GB vom 23.09.2026 | 0,27 EUR |
| SAP 716460 vom 23.07.2026 | 0,43 EUR |

LS9AVX, A2H57N und LYX05A besitzen ebenfalls strukturierte
`booking_details`; nachgewiesene Nullgebühren bleiben `0.00` und werden nicht
als unbekannt behandelt.

### Stammdaten-Referenzfälle

Die WKN A0H074, A0LEW8, 593399, A0D8QZ, 578560, 716460, LS9AVX, A2H57N,
LYX05A, A111X9 und A0S9GB sind jeweils genau einmal in `security_master`
vorhanden. Ihre kanonischen Namen sind echte Wertpapierbezeichnungen; weder
Buchungstexte noch bloße ISIN/WKN wurden als Anzeigename übernommen.

## 4. Finanzreport-Salden

Die neun eindeutigen Finanzreports enthalten jeweils drei Konten. Alle
eingebauten Prüfungen

```text
Anfangssaldo + Summe der Buchungen = Endsaldo
```

waren centgenau: **27/27 ohne Differenz**.

## 5. Produktive Datenbank – nur lesend

Prüfmodus: `file:.../portfolio.sqlite?mode=ro&immutable=1`.

| Prüfung | Ergebnis |
|---|---|
| `PRAGMA integrity_check` | `ok` |
| Fremdschlüsselverletzungen | 0 |
| Doppelte aktive Quellhashes | 0 |
| Doppelte aktive Transaktions-IDs je Konto | 0 |
| Aktive Imports | 9 |
| Transaktionen | 362 |
| Dokumentdatensätze | 36 |
| `booking_details` | 0 |
| `fee_links` | 0 |

Die produktive Datenbank ist technisch konsistent, enthält aber noch keinen
Neuimport nach PR #19–#21. Deshalb sind die neuen `booking_details`,
`cost_reports`, Steuerlinks und MiFID-II-Datensätze dort noch nicht
materialisiert. Das ist kein Fehler des isolierten Integrationstests. Ein
produktiver Neuimport darf nur bewusst über die GUI mit Vorschau erfolgen.

Dateigröße und letzter Änderungszeitpunkt blieben während der Prüfung
unverändert: `176492544` Bytes, `22.10.2026 18:26:32 UTC`.

## 6. Vollständige Regression

```text
1098 passed, 12 skipped in 338.42s (0:05:38)
```

Es gab keine Testfehler. Damit sind insbesondere OCR-Sicherheitsprüfungen,
reale Windows-PDFs, MiFID-II-Import, Steuer-/Dividendenabgleich,
Gebührenpersistenz, Importvorschau und SQLite-Atomarität gemeinsam abgedeckt.

## Empfehlung

Der Stand ist für einen kontrollierten GUI-Neuimport freigabefähig. Vorher
sollte eine Sicherung der produktiven Datenbank erstellt werden. Der Import
sollte mit Vorschau erfolgen; insbesondere ist die Zuordnung
`Kosteninformation Sparplan 38 → Depot 4764924` bewusst zu bestätigen. Eine
automatische Änderung der produktiven Datenbank ist nicht erforderlich und
wurde nicht durchgeführt.
