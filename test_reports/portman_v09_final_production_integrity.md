# Portman V09 – Finale produktive SQLite-Datenintegritätsprüfung

Prüfdatum: 22.10.2026  
Git-Stand: `main` / `1c91ae9` (`Harden Windows OCR validation and add diagnostics (#20)`)  
Referenz: `test_reports/final_integration_after_pr20_pr21_2026-10-22.md`

## Gesamtbewertung

**FAIL.** Der Neuimport ist hinsichtlich PDF-Vollständigkeit, Dokumentablage,
Kontosalden, Depotbeständen und technischer SQLite-Integrität vollständig. Die
nachgelagerte wirtschaftliche Verknüpfung wurde in der produktiven Datenbank
jedoch nicht persistiert:

- `booking_details`: **0 statt 37**;
- `fee_links`: **0 statt 4**;
- die 23 Steuerereignisse besitzen keine fachliche Verbindung zur jeweiligen
  Finanzreport-Dividende;
- die Performance-Sicht für `Depot 4764924` enthält deshalb keine zugeordneten
  Wertpapier-Cashflows.

Es gibt keine doppelte Cashbelastung. Die Cashkonten und Depot-Snapshots sind
korrekt. Gebühren, Einstandskosten, Steuerdetails und Performance sind aber
nicht vollständig fachlich angereichert und erfüllen daher die Abnahme nicht.

## 1. Sicherheits- und Snapshotnachweis

Portman war während der Prüfung geschlossen. Der einzige laufende
`python.exe`-Prozess gehörte zur VS-Code-Erweiterungsumgebung und besaß kein
Portman-Fenster. Vor dem Snapshot lagen weder `portfolio.sqlite-wal` noch
`portfolio.sqlite-shm` vor.

Die Quelle wurde ausschließlich so geöffnet:

```text
file:///.../data/v09/portfolio.sqlite?mode=ro
PRAGMA query_only=ON
```

Anschließend wurde mit der SQLite-Backup-API ein konsistenter temporärer
Snapshot erzeugt. Sämtliche fachlichen Abfragen liefen auf diesem Snapshot.
Der read-only SQLite-Zugriff legte dabei eine leere WAL-Datei (0 Byte) und eine
SHM-Verwaltungsdatei (32 KiB) neben der Datenbank an. Sie enthalten keine
fachlichen Änderungen; ihre automatische Entfernung wurde von der
Ausführungsrichtlinie blockiert und deshalb nicht umgangen. Die produktive
Hauptdatenbank und die 102 Original-PDFs wurden nicht verändert.

Produktive Datei zum Prüfzeitpunkt:

```text
Größe: 176492544 Bytes
LastWriteTimeUtc: 22.10.2026 21:05:40
```

## 2. Soll-Ist-Vergleich

| Kennzahl | Soll | Ist | Bewertung |
|---|---:|---:|---|
| Physische PDFs | 102 | 102 | PASS |
| Eindeutige PDF-Inhalte | 93 | 93 | PASS |
| Aktive Imports | 93 | 93 | PASS |
| Transaktionen | 366 | 366 | PASS |
| Dokumentdatensätze | 120 | 120 | PASS |
| MiFID-II-CostReports | 23 | 23 | PASS |
| Steuerereignisse | 23 | 23 | PASS |
| `booking_evidence` | 38 | 38 | PASS |
| `booking_details` | 37 | **0** | FAIL |
| `fee_links` | 4 | **0** | FAIL |
| Finanzreport-Saldoabgleiche | 27/27 | 27/27 | PASS |

Alle 93 aktiven Importhashes entsprechen exakt den 93 eindeutigen SHA-256-
Hashes im Originalverzeichnis. Es gibt weder fehlende noch zusätzliche
Importhashes. Die neun physischen PDF-Kopien wurden damit korrekt dedupliziert.

## 3. Technische Integrität und Dubletten

```sql
PRAGMA integrity_check;
-- ok

PRAGMA foreign_key_check;
-- keine Zeile
```

Weitere Ergebnisse:

| Prüfung | Ergebnis |
|---|---:|
| Doppelte aktive Quellhashes | 0 |
| Doppelte Buchungen je Konto/`external_id` | 0 |
| Doppelte Steuerereignis-IDs | 0 |
| Doppelte Dokumente je Konto/`external_id` | 0 |
| Aktive Imports ohne Dokumentablage | 0 |
| Verwaiste Transaktionen | 0 |
| Verwaiste Dokumente | 0 |
| Verwaiste Modelldatensätze | 0 |
| Verwaiste Snapshots/Salden | 0 |

Verwendete Kernabfragen:

```sql
SELECT COALESCE(json_extract(report,'$.source_sha256'), file_hash), COUNT(*)
FROM imports
WHERE active=1
GROUP BY 1
HAVING COUNT(*)>1;

SELECT t.account, t.external_id, COUNT(*)
FROM transactions t
JOIN imports i ON i.id=t.import_id AND i.active=1
GROUP BY t.account, t.external_id
HAVING COUNT(*)>1;

SELECT json_extract(r.payload,'$.external_id'), COUNT(*)
FROM import_model_records r
JOIN imports i ON i.id=r.import_id AND i.active=1
WHERE r.kind='tax_events'
GROUP BY 1
HAVING COUNT(*)>1;
```

## 4. Fehlende Kaufgebührenpersistenz

Alle 38 Kaufabrechnungen sind als `booking_evidence` erhalten. Ein read-only
Abgleich über Cashkonto, Währung, Gesamtbetrag, Datum/Valuta innerhalb von drei
Tagen und ISIN/WKN ergibt:

| Kandidatenzahl | Belege |
|---:|---:|
| genau ein Finanzreporttreffer | 37 |
| kein Treffer | 1 |
| mehrere Treffer | 0 |

Trotz 37 eindeutiger Treffer ist `booking_details` vollständig leer.

### Referenzfälle

| Wertpapier | Evidence-Import-ID | Finanzreport-Transaktions-ID | Belegte Gebühr | Persistiert |
|---|---:|---:|---:|---|
| A111X9, 07.09.2026 | 66 | 330 | 0,46 EUR | nein |
| A0S9GB, 23.09.2026 | 67 | 348 | 0,27 EUR | nein |
| SAP 716460, 23.07.2026 | 73 | 272 | 0,43 EUR | nein |

Der einzige Beleg ohne Finanzreporttreffer ist Import-ID 63,
`LU2090063673`, 07.10.2026, Gesamtbetrag 1,33 EUR, Gebühr 0,00 EUR. Der letzte
vorhandene Finanzreport endet am 01.10.2026; dieser offene Fall darf nicht
automatisch zugeordnet werden.

Relevante SQL-Abfrage:

```sql
SELECT transaction_id,
       json_extract(payload,'$.security') AS security,
       json_extract(payload,'$.fees') AS fees,
       source_hash
FROM booking_details;
-- 0 Zeilen
```

### Wirtschaftliche Auswirkung

Die Finanzreport-Gesamtbelastungen sind bereits in den Cashbuchungen enthalten;
es existiert deshalb keine zweite Cashbelastung. Ohne `booking_details` bleiben
die Buchungen aber rohe `BANK_BOOKING`-Zeilen. Stückzahl, Kurswert und Gebühr
werden nicht strukturiert der Kaufbuchung zugeordnet. Dadurch sind
Anschaffungskosten und gebührenbereinigte Performance unvollständig.

## 5. Fehlende Steuer-/Dividendenverknüpfungen

Die vier Steuer-TX-Zeilen sind korrekt `affects_cash=false` und erzeugen damit
keine zweite Kontobelastung. Ihre Steuerereignisse zeigen jedoch weiterhin auf
die TAX-Evidenzzeile statt auf die fachliche Finanzreport-Dividende. `fee_links`
enthält keine Zeile.

| Fall | Tax-Import-ID | TAX-TX-ID | Finanzreport-Dividenden-TX-ID | Steuer | Fachlich verknüpft |
|---|---:|---:|---:|---:|---|
| A0LEW8 / IE00B1FZS350 | 29 | 363 | 327 | 6,38 EUR | nein |
| 593399 / DE0005933998 | 30 | 364 | 362 | 6,48 EUR | nein |
| A0D8QZ / DE000A0D8QZ7 | 31 | 365 | 360 | 10,36 EUR | nein |
| A0H074 / DE000A0H0744 | 32 | 366 | 361 | 1,67 EUR | nein |

Die Netto-Cashflows sind jeweils genau einmal als Finanzreportbuchung vorhanden.
Die zusätzlichen TAX-Zeilen sind cash-neutral. Es liegt daher keine doppelte
wirtschaftliche Kontobelastung vor, wohl aber eine fehlende fachliche
Zusammenführung und eine unvollständige Steuer-/Performanceansicht.

### A0H074

| Feld | Wert |
|---|---:|
| Brutto | 9,10 EUR |
| Teilfreistellung | 2,73 EUR |
| Steuerbasis | 6,37 EUR |
| Kapitalertragsteuer | 1,59 EUR |
| Solidaritätszuschlag | 0,08 EUR |
| Gesamtsteuer | 1,67 EUR |
| Netto-Cashflow, TX 361 | 7,43 EUR |

Die Fachwerte sind vollständig und korrekt gespeichert. Fehlerhaft ist nur die
Verknüpfung: `related_transaction_id` referenziert die TAX-Evidenz TX 366 statt
der Dividende TX 361; ein `fee_link` fehlt.

### SAP und Fresenius

| Fall | Steuerereignis-Import-ID | Finanzreport-TX-ID | Netto | Steuer | `related_transaction_id` |
|---|---:|---:|---:|---:|---|
| SAP 716460 | 21 | 214 | 4,49 EUR | 0,00 EUR | leer |
| Fresenius 578560 | 22 | 215 | 4,07 EUR | 0,00 EUR | leer |

Beide Cashflows sind genau einmal vorhanden und fachlich eindeutig. Die
Nullsteuer darf keinen `fee_link` erzeugen, aber das Steuerereignis muss auf die
jeweilige Dividende zeigen. Diese Verbindung fehlt.

## 6. Kontosalden und Depotbestände

Die neun eindeutigen Finanzreports enthalten jeweils drei Konten. Für jede der
27 Kombinationen wurde geprüft:

```text
Endsaldo − Anfangssaldo − Summe der Cashbuchungen
```

Auf Cent gerundet beträgt jede Differenz `0,00 EUR`. Damit sind **27/27
Saldoabgleiche korrekt**. Die in SQLite bei `CAST(... AS REAL)` sichtbaren
Restwerte liegen nur im Bereich von etwa `10^-13 EUR` und sind binäre
Fließkommaarithmetik, keine Centdifferenzen.

Der letzte vollständige Depot-Snapshot:

| Feld | Wert |
|---|---:|
| Snapshot-ID | 9 |
| Import-ID | 9 |
| Stichtag | 01.10.2026 |
| Positionen | 18 |
| Doppelte Positionsschlüssel | 0 |
| Gesamtwert | 54.802,91 EUR |

Die Bestände sind damit vollständig und intern eindeutig. Da die Käufe nicht
mit `booking_details` angereichert sind, lässt sich die korrekte
gebühreninklusive Einstandskostenfortschreibung jedoch nicht bestätigen.

## 7. Performanceprüfung

Die produktive Performance-Sicht für `Depot 4764924` liefert aus den
gespeicherten Transaktionen **0 zugeordnete Depot-Cashflows**. Es existieren 58
relevante Finanzreportbuchungen mit Wertpapier- oder Ertragsbezug, deren
`performance_depot_key` leer ist. Ohne `booking_details` bleiben auch die
Käufe rohe `BANK_BOOKING`-Zeilen.

Die Bestandsbewertung aus Snapshots ist vorhanden, aber Kaufzahlungen,
Dividenden, Gebühren und Steuern sind für die Depotperformance nicht vollständig
zugeordnet. Eine belastbare Performance- oder Einstandskostenabnahme ist daher
nicht möglich.

## 8. MiFID-II-Kostenreports

Die 23 `cost_reports` sind vollständig vorhanden. Ihre 23 Import-IDs besitzen:

| Wirtschaftliche Tabelle | Zeilen |
|---|---:|
| Transaktionen | 0 |
| Salden | 0 |
| Depot-Snapshots | 0 |

Damit sind die Kosteninformationen ausschließlich informativ. Sie erzeugen
keinen Cashflow, keine Bestandsänderung und keine Performancewirkung.

## 9. Priorisierte Auffälligkeiten

### P0 – Performance und Einstandskosten nicht fachlich vollständig

Die Depotperformance besitzt keine zugeordneten Wertpapier-Cashflows. Ursache
ist die vollständig ausgebliebene Persistenz von 37 eindeutigen
`booking_details` sowie fehlende Depotzuordnungen der Finanzreportzeilen.

**Empfehlung:** Importpfad und Laufzeitstand prüfen. Auf einer Kopie der
Produktionsdatenbank eine explizite, idempotente Nachverknüpfung mit Vorschau
testen. Nur eindeutige 1:1-Treffer übernehmen; Import-ID 63 offen lassen.
Anschließend Einstandskosten und Performance gegen den isolierten
Referenzimport vergleichen.

### P1 – Steuer- und Dividendenlinks fehlen

Vier besteuerte Ausschüttungen sowie SAP und Fresenius sind fachlich nicht mit
den vorhandenen Finanzreport-Dividenden verbunden. `fee_links=0`.

**Empfehlung:** Zuerst klären, warum der nach `commit_batches()` vorgesehene
Postprozessor beim produktiven Neuimport keine Persistenz erzeugte. Danach eine
separate Reparatur mit Vorschau entwickeln: `related_transaction_id` auf die
oben dokumentierten Finanzreport-TX-IDs setzen und ausschließlich für die vier
bezahlten Steuern je einen validierten `fee_link` erzeugen.

### P2 – Ein Kaufbeleg ohne Finanzreportgegenbuchung

Import-ID 63 vom 07.10.2026 besitzt keinen passenden Finanzreport im
Prüfbestand. Dies ist kein Beweis für einen Fehler.

**Empfehlung:** Den nächsten Finanzreport beziehungsweise die Kontobuchung
nachreichen; bis dahin Prüfhinweis beibehalten und nicht automatisch buchen.

### P3 – Keine weiteren Auffälligkeiten

PDF-Vollständigkeit, Dokumentablage, Hash-Deduplizierung, SQLite-Struktur,
Fremdschlüssel, Kontosalden, Depot-Snapshot und MiFID-II-Neutralität sind ohne
Befund.

## Schlussfolgerung

Die Originaldaten sind vollständig importiert und die Konten/Bestände stimmen.
Die Abnahme scheitert ausschließlich, aber wesentlich, an der fehlenden
wirtschaftlichen Nachverknüpfung. Es wurden keine produktiven Daten geändert,
keine Migration ausgeführt und keine Reparatur vorgenommen.
