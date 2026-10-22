# Portman V09 – SQLite-Datenintegritätsprüfung nach PR #18

Prüfdatum: 22.10.2026
Projekt: `C:\Users\chris\Desktop\programming\PortmanNL`
Datenbank: `data/v09/portfolio.sqlite`
Originale: `C:\Users\chris\Desktop\history\comdirect\2026`

## 1. Executive Summary und Gesamtbewertung

**Freigabeentscheidung: FAIL.**

PR #18 ist im geprüften `main` enthalten: `49ff9c8 Improve comdirect PDF
import quality (#18)`. Die physische SQLite-Struktur ist intakt und alle 27
Saldointervalle der neun Finanzreports gehen centgenau auf. Es gibt keine
Fremdschlüsselverletzung, keine doppelten aktiven Importhashes und keine
doppelten Transaktions-IDs beziehungsweise Content-Hashes.

Die Freigabe scheitert an zwei nachgewiesenen P1-Problemen:

1. **P1 – Steuerverknüpfungen fehlen im Neuimport.** `fee_links` enthält null
   Zeilen. Keines der 20 Dividenden-/Ausschüttungs-Steuerereignisse ist mit der
   vorhandenen Finanzreport-Dividende verbunden. Bei den vier steuerpflichtigen
   September-Fällen verweist `related_transaction_id` stattdessen auf die
   jeweils eigene synthetische TAX-Transaktion. A0H074 ist beispielsweise als
   Finanzreportbuchung 361 und Steuertransaktion 366 doppelt dargestellt, ohne
   fachlichen Link. Die zusätzliche Steuertransaktion ist zwar cash-neutral,
   sodass kein zweiter Geldabfluss entsteht; Detailansicht und fachliche
   Zusammenführung bleiben dennoch falsch beziehungsweise unvollständig.
2. **P1 – Gebührennachweise der Wertpapierabrechnungen sind nicht strukturiert
   im Bestand nachvollziehbar.** Die Kauf-PDFs werden korrekt geparst und ihre
   Gebühren stimmen mit den Cashbuchungen überein. In der Datenbank bleiben
   jedoch nur Dokument, SecurityInfo und ein Text im Importbericht. Es gibt
   keine `booking_details` und keine `fee_links`; die Finanzreportbuchungen
   selbst haben `fees=NULL` und leere `fee_items`. Eine belastbare Prüfung der
   einmaligen Gebührenwirkung in Anschaffungskosten und Performance ist aus
   dem persistierten Neuimport deshalb nicht möglich.

Zusätzliche Einschränkung: Die produktive Datenbank wurde während der Prüfung
von einem anderen Prozess verändert. Die Hauptdatei wechselte von
`2026-10-22 13:46:38 UTC` auf `13:54:19 UTC`; die WAL-Datei wurde zuletzt um
`13:58:35 UTC` geändert. Alle eigenen Verbindungen verwendeten nachweislich
`mode=ro`, `PRAGMA query_only=ON` und eine Lesetransaktion. Einzelne
Abfrageblöcke sind konsistente SQLite-Snapshots, der Bericht bildet wegen der
externen Änderungen aber keinen einzigen globalen Zeitpunkt ab. Die beiden
P1-Befunde wurden auch im abschließenden Snapshot bestätigt.

Es wurden keine Datenbankmigrationen, Imports, Reparaturen oder Löschungen
ausgeführt. Die direkten PDF-Prüfungen verwendeten ausschließlich
`portfolio_v5.pdf_importer.parse_pdf()` ohne Repository und ohne Speicherung.

## 2. Code- und Datenbankstand

| Prüfung | Ergebnis |
|---|---|
| Git-Branch | `main`, synchron zu `origin/main` |
| HEAD / PR #18 | `49ff9c8`, enthalten |
| Vorgänger | `8d2b72f` PR #17 |
| SQLite `user_version` | 9 |
| SQLite `schema_version` | 439 |
| Migrationen | 7, 8, 9 |
| Letzter Import | `2026-10-22T13:49:19.569928+00:00` |
| Abschluss-Snapshot | 70 Imports, 366 Transaktionen, 97 Dokumentzeilen |
| Zugriff | URI `mode=ro`, `query_only=1` |

Der Arbeitsbaum enthielt bereits vor der Prüfung zahlreiche unversionierte
Testverzeichnisse und ältere Berichte. Sie wurden weder verändert noch
bereinigt. Dieser Bericht ist die einzige erzeugte Projektdatei.

## 3. Datenbankintegrität und Kennzahlen

| Invariante/Kennzahl | Soll | Ist | Bewertung |
|---|---:|---:|---|
| `PRAGMA integrity_check` | `ok` | `ok` | PASS |
| `PRAGMA foreign_key_check` | 0 Treffer | 0 | PASS |
| Aktive Imports | nur aktive Neuimporte | 70 | PASS |
| Inaktive Imports | 0 | 0 | PASS |
| Transaktionen | plausibel / ohne Dubletten | 366 | PASS |
| Finanzreport-Snapshots | 9 | 9 | PASS |
| Saldozeilen | 9 × 3 Konten × 2 Stände | 54 | PASS |
| Steuerereignisse | 23 eindeutige Belege | 23 | PASS |
| Synthetische TAX-Transaktionen | nur vier mit gezahlter Steuer | 4 | PASS |
| TAX mit `affects_cash=true` | 0 | 0 | PASS |
| Dokumentzuordnungen | 36 + 38 + 23 | 97 | PASS |
| `fee_links` | Links zu vorhandenen Dividenden | 0 | **FAIL P1** |
| `booking_details` | Gebühren nachvollziehbar | 0 | **FAIL P1** |
| `security_master` | – | 32 | Hinweis |
| `security_metadata` | – | 19 | Hinweis |
| `original_files` gesamt | projektweiter Bestand | 1067 | Hinweis |

Transaktionen je Konto:

| Konto | Transaktionen |
|---|---:|
| `IBAN DE84200411330476492400` | 320 |
| `IBAN DE71200411330476492440` | 37 |
| `IBAN DE46200411330476492405` | 9 |

Arten: 359 `BANK_BOOKING`, vier `TAX`, drei `INTEREST`. Die Tabellen
`transactions`, `bank_documents` und `import_model_records` enthalten keine
verwaisten `import_id`-Referenzen. Datumsprüfung (`date(date)`) und die Prüfung
der belegten Währungen ergaben keine ungültigen Werte.

## 4. Import- und Dokumentabdeckung

| Begriff | Anzahl | Erklärung |
|---|---:|---|
| Physische PDF-Dateien | 102 | alle Dateien einschließlich Unterordner |
| Eindeutige SHA-256-Inhalte | 93 | neun zusätzliche identische Kopien |
| Strukturierte physische PDFs | 79 | Referenzstand PR #18 bestätigt |
| Strukturierte eindeutige Inhalte / Imports | 70 | je Inhalt genau ein aktiver Import |
| Generische physische/eindeutige PDFs | 23 | ausschließlich `Kosteninformationen` |
| Parserfehler im Referenzlauf | 0 | Bericht PR #18 |
| Dokumentzeilen in SQLite | 97 | 36 Finanzreport-Zuordnungen + 38 Käufe + 23 Steuerbelege |

Die 79 strukturierten Dateien bestehen physisch aus neun Finanzreports, 41
Kaufabrechnungen und 29 Steuerdateien; neun davon sind identische Kopien. Nach
Hash-Deduplizierung bleiben 9 + 38 + 23 = 70 Imports. Die neun Finanzreports
werden jeweils vier fachlichen Konten/Depots als Dokument zugeordnet, also 36
Dokumentzeilen. Das ist erlaubte Mehrfachzuordnung, keine Dokumentdubletten.

Alle 23 nicht importierten eindeutigen Inhalte liegen im Ordner
`Kosteninformationen`. Damit ist die erwartete Klassifikation aus PR #18
bestätigt. Keine Kosteninformation wurde als ausgeführter Trade oder Cashflow
gespeichert.

Die neun identischen Paare umfassen einen Finanzreport, drei Kaufabrechnungen
(LS9AVX, A2H57N, LYX05A) und fünf Januar-Steuermitteilungen. Für keinen dieser
Hashes existiert ein zweiter aktiver Import.

## 5. Dubletten

| Prüfung | Treffer | Bewertung |
|---|---:|---|
| Identische aktive `imports.file_hash` | 0 | PASS |
| Gleiches Konto + `external_id` | 0 | PASS |
| Gleiches Konto + `content_hash` | 0 | PASS |
| Doppelte Steuer-Signatur aus Wertpapier, Datum, Basis, Steuer, Referenz | 0 | PASS |
| Identische PDF-Inhalte als mehrere aktive Imports | 0 | PASS |
| Physische Hash-Kopierpaare im Quellbaum | 9 | korrekt dedupliziert |

Die Finanzreport-Dokumente besitzen pro Report vier Zeilen mit gleichem
`content_hash`, aber unterschiedlichen Konten. Dies ist die ausdrücklich
zulässige Dokumentzuordnung und keine doppelte wirtschaftliche Buchung.

Zwei Buchungen (IDs 270 und 271) besitzen dieselbe Bankreferenz
`1C5C299W0AV`, sind aber keine Dublette: beide sind am 23.07.2026 gebucht,
jedoch über unterschiedliche Beträge, Wertpapiere und Geschäftskennungen:

- ID 270: Fresenius 578560, −47,47 EUR, Kennung `U1FDA/2`.
- ID 271: 593399, −41,95 EUR, Kennung `ZJERR/2`.

Die 16 Treffer mit dem Text `Übertrag / Überweisung` sind keine stabile externe
Bankreferenz, sondern ein generisches extrahiertes Textfragment. Die
Transaktionen besitzen unterschiedliche Beträge, Gegenkonten, Tage und
Rohtexte. Sie wurden daher nicht als Dubletten gewertet.

## 6. Steuerereignisse und Verknüpfungen

### Investment-Ausschüttungen September

| WKN | Finanzreport-ID | Steuer-TX-ID | Brutto | Teilfrei | Basis | Steuer | Netto | Link |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A0LEW8 | 327 | 363 | 28,62 | 0,00 | 28,62 | 6,38 | 22,24 | fehlt |
| 593399 | 362 | 364 | 35,15 | 10,55 | 24,60 | 6,48 | 28,67 | fehlt |
| A0D8QZ | 360 | 365 | 56,12 | 16,83 | 39,29 | 10,36 | 45,76 | fehlt |
| A0H074 | 361 | 366 | 9,10 | 2,73 | 6,37 | 1,67 | 7,43 | fehlt |

Bei A0LEW8 ist die fachlich zulässige Datumsabweichung vorhanden:
Ertragsdatum 31.08., Buchung 01.09., Valuta 02.09.2026. Der Cashbetrag 22,24
EUR und die Steuer 6,38 EUR sind eindeutig.

Alle vier TAX-Transaktionen besitzen:

- `affects_cash=false`;
- `performance_depot_key='depot 4764924'`;
- Cashkonto `IBAN DE71200411330476492440`;
- ein korrektes Mapping des Quellschlüssels `depot 476492400` auf
  `depot 4764924`.

Damit entsteht kein zweiter Cash- oder Performanceabfluss. Der Fehler liegt in
der fachlichen Verbindung: `fee_links=0`, und `related_transaction_id` zeigt
auf die eigene TAX-`…-payment`-ID (zum Beispiel A0H074 auf Transaktion 366)
statt auf die Finanzreport-Dividende (A0H074 ID 361).

### A0H074 verbindlicher Referenzfall

| Parameter | Soll | Ist |
|---|---:|---:|
| Stückzahl | 27,051 | 27,051 |
| Brutto | 9,10 EUR | 9,10 EUR |
| Teilfreistellung | 2,73 EUR | 2,73 EUR |
| Steuerbasis | 6,37 EUR | 6,37 EUR |
| Kapitalertragsteuer | 1,59 EUR | 1,59 EUR |
| Solidaritätszuschlag | 0,08 EUR | 0,08 EUR |
| Kirchensteuer | 0,00 EUR | 0,00 EUR, explizit belegt |
| Gesamtsteuer | 1,67 EUR | 1,67 EUR |
| Netto-Cashflow | 7,43 EUR | 7,43 EUR |
| Doppelte Cash-Steuer | 0,00 EUR | 0,00 EUR |
| Fachlicher Link | genau einer | **keiner** |

### Alle Steuerereignisse und Aktien-Dividenden

Die 23 Ereignisse verteilen sich auf zwölf
`investment_ausschuettung_inland`, sechs
`investment_ausschuettung_ausland`, drei `vorabpauschale_ausland` und zwei
`dividende_inland`. Keine fachliche Steuersignatur ist doppelt.

SAP 716460 (Import 59) und Fresenius 578560 (Import 60) sind korrekt als
`dividende_inland` klassifiziert. Die Finanzreport-Dividenden sind vorhanden:

| WKN | Finanzreport-TX | Datum | Netto/Basis | Steuer | Ereignistyp | Link |
|---|---:|---|---:|---:|---|---|
| 716460 | 214 | 08.05.2026 | 4,49 EUR | 0,00 EUR | `dividende_inland` | fehlt |
| 578560 | 215 | 27.05.2026 | 4,07 EUR | 0,00 EUR | `dividende_inland` | fehlt |

Kapitalertragsteuer, Solidaritätszuschlag und Kirchensteuer sind in diesen
Belegen als explizite Nullbeträge gespeichert; sie sind nicht mit unbekannten
Werten verwechselt. Es wurde keine zusätzliche Cashtransaktion erzeugt. Der
fachliche Link zur vorhandenen Dividende fehlt jedoch ebenso wie bei allen
weiteren steuerfreien Ausschüttungen (`related_transaction_id=''`).

## 7. Transaktionen und Depotbestände

Die Schwerpunkt-PDFs wurden erneut direkt und schreibgeschützt mit
`portfolio_v5.pdf_importer.parse_pdf()` und den registrierten Plugins geprüft.
Alle liefen über `user.comdirect-ertraege`, Handler `wertpapierkauf`, mit 97 %
Erkennung und ohne Fehler.

| WKN | Handel | Stück | Kurs | Kurswert | Gebühren | Gesamt | Cash-TX |
|---|---|---:|---:|---:|---:|---:|---:|
| LS9AVX | 01.06. | 0,006 | 3.662,71 | 21,98 | 0,00 | −21,98 | ID 211, −21,98 |
| A2H57N | 01.07. | 0,211 | 236,15 | 49,83 | 0,00 | −49,83 | ID 249, −49,83 |
| LYX05A | 07.10. | 0,014 | 95,02 | 1,33 | 0,00 | −1,33 | nach letztem Report |
| A111X9 | 07.09. | 0,630 | 48,401 | 30,49 | 0,46 | −30,95 | ID 330, −30,95 |
| A0S9GB | 23.09. | 0,147 | 121,20 | 17,82 | 0,27 | −18,09 | ID 348, −18,09 |
| 716460 | 23.07. | 0,221 | 129,52 | 28,62 | 0,43 | −29,05 | ID 272, −29,05 |

Die reparierten OCR-Werte A111X9, A0S9GB und 716460 sind rechnerisch
konsistent und stimmen exakt mit den Finanzreport-Cashbuchungen überein. Die
langjährig beschädigten Schriftfamilien LS9AVX, A2H57N und LYX05A wurden
ebenfalls strukturiert erkannt. Nullgebühren sind als belegte `0.00` samt
`fee_items` im Parserresultat vorhanden und nicht als unbekannt behandelt.

Bestandskontrolle anhand der vollständigen Snapshots:

- LS9AVX: 0,006 am 02.02. auf 0,043 am 01.08.; die monatlichen Käufe erklären
  die Deltas.
- A2H57N: 32,055 am 02.02. auf 33,126 am 01.07.; die importierten Käufe
  erklären die Deltas. Ein Anfangsbestand vor dem ersten Report ist vorhanden
  und wurde ausdrücklich **nicht** als null angenommen.
- LYX05A: 19,248 am 02.02. auf 23,985 am 01.10.; alle bis 01.10. bekannten
  Käufe sind enthalten. Der Kauf vom 07.10. kann ohne späteren Snapshot nicht
  bestandsseitig bestätigt werden.
- A111X9: 234,356 am 01.09. auf 236,009 am 01.10.; Differenz 1,653 entspricht
  den Käufen 0,630 + 1,023.
- A0S9GB: 18,851 am 01.09. auf 18,998 am 01.10.; Differenz 0,147.
- SAP 716460: 1,794 am 01.07. auf 2,015 am 03.08.; Differenz 0,221.

Die Snapshot-Einstandskosten verändern sich in denselben Perioden plausibel.
Eine vollständige lotbasierte Anfangsbestands- und realisierte
Ergebnisrechnung ist mit den 2026-Dokumenten allein nicht möglich, weil die
Bestände bereits vor dem ersten geprüften Report existierten.

## 8. Kontosalden und Cashflow

Für jeden Finanzreport wurde je Konto gerechnet:

`Endsaldo − Anfangssaldo − SUM(importierte Beträge)`

Alle 27 Ergebnisse sind exakt 0,00 EUR. Zusammenfassung der jeweils letzten
Intervalle:

| Konto | Stichtag | dokumentiert vorher | dokumentiert neu | Buchungssumme | Differenz |
|---|---|---:|---:|---:|---:|
| Giro `…2400` | 01.10.2026 | 1.781,43 | 4.325,17 | 2.543,74 | 0,00 |
| Tagesgeld `…2405` | 01.10.2026 | 2.000,00 | 2.002,52 | 2,52 | 0,00 |
| Verrechnung `…2440` | 01.10.2026 | 38,65 | 119,82 | 81,17 | 0,00 |

Auch die übrigen acht Intervalle pro Konto stimmen centgenau. Interne
Umbuchungen tragen auf den jeweiligen Konten die korrekten Vorzeichen.
Wertpapierkäufe, Ausschüttungen und Verwahrentgelte sind in den
Finanzreport-Cashbuchungen enthalten. Die vier TAX-Informationsbuchungen sind
`affects_cash=false` und wurden nicht in die dokumentierten Salden addiert.

## 9. Gebühren und Performance

Positiv:

- Die direkt geparsten Kaufbelege erfüllen jeweils
  `Kurswert + Gebühren + Steuern = Gesamtbelastung`.
- Die Gesamtbelastungen stimmen mit den vorhandenen Finanzreportbuchungen
  überein.
- Steuertransaktionen mit bereits netto gebuchter Ausschüttung sind
  cash-neutral und dem richtigen Performance-Depot zugeordnet.
- Steuer- und Kosteninformationen erzeugen keine Bestandsveränderung.

Nicht freigabefähig:

- Die Kauftransaktion aus dem PDF wird beim Speichern nicht als zweite
  Transaktion angelegt (das verhindert einen doppelten Cashflow), aber ihre
  strukturierten Gebührenkomponenten werden auch nicht in `booking_details`
  oder `fee_links` mit der Finanzreportbuchung verbunden.
- Beispiel SAP: PDF-Parser liefert Provision 0,43 EUR; Cash-TX 272 enthält
  `fees=NULL` und `fee_items=[]`. Im persistenten Import bleibt der Betrag nur
  als Warntext `Gebühren 0.43 EUR` erhalten.
- Entsprechendes gilt für A111X9 0,46 EUR und A0S9GB 0,27 EUR sowie die übrigen
  Kaufabrechnungen.

Damit ist zwar keine doppelte Gebühren-Cashbuchung nachgewiesen, aber die
Gebührenwirkung auf Einstandskosten und Performance kann nicht aus einer
stabilen strukturierten Verknüpfung hergeleitet werden. Die Snapshot-Kaufwerte
sind plausibel; sie ersetzen keinen transaktionsbezogenen Gebührennachweis.

## 10. Priorisierte Auffälligkeiten

### P1-01 – Ausschüttungs-/Dividendenlinks fehlen

- Betroffen: alle 20 Dividenden- und Investment-Ausschüttungsereignisse;
  besonders Imports 67–70 / TX 363–366 und Finanzreport-TX 327, 360–362.
- Nachweis: `SELECT COUNT(*) FROM fee_links` ergibt 0.
- Ursache im Datenbestand: `related_transaction_id` bleibt leer oder zeigt auf
  die eigene TAX-Payment-ID; kein Eintrag verbindet Ereignis und
  Finanzreportbuchung.
- Wirkung: keine doppelte Cashsteuer, aber unverbundene Detaildarstellung und
  fehlende fachliche Eindeutigkeit.
- Empfehlung: Neuimport in einer temporären Datenbank mit aktivem PR-#18-Code
  reproduzieren und untersuchen, weshalb `_link_investment_distribution_taxes`
  trotz eindeutiger Kandidaten keine Links persistiert. Keine produktive
  Nachreparatur ohne Vorschau.

### P1-02 – Gebührenkomponenten werden nicht strukturiert persistiert

- Betroffen: alle Kaufabrechnungsimporte 10–47; konkrete Beispiele TX 330,
  348 und 272.
- Nachweis: `booking_details=0`, `fee_links=0`, Cashbuchungen haben
  `fees=NULL`, während `parse_pdf()` belegte Gebühren liefert.
- Wirkung: Gebühren sind im Bericht lesbar, aber für eine belastbare
  transaktionsbezogene Kosten-/Performanceprüfung nicht verfügbar.
- Empfehlung: bestehende Abgleichlogik prüfen und Gebühren aus dem
  cash-neutralen PDF-Trade eindeutig an die Finanzreportbuchung binden; keine
  zweite Transaktion und keine zweite Belastung erzeugen.

### P2-01 – Uneinheitlicher Quell-Depotname

- Kauf- und Steuerbelege verwenden `Depot 476492400`, Finanzreports und
  Stammdaten `Depot 4764924`.
- Steuerimporte 48–70 mappen den Quellschlüssel korrekt auf `depot 4764924`.
- Kaufimporte 10–47 mappen den Quell-Depotschlüssel dagegen auf das Girokonto
  `iban de84200411330476492400`; das erklärt den Dokument-/Cashabgleich, ist
  semantisch aber missverständlich und sollte in einer Vorschau geprüft
  werden. Es wurde keine automatische Korrektur vorgenommen.

### P2-02 – Historische Namensaliase

Die kanonischen Namen der Schwerpunkt-Wertpapiere sind gültig, einschließlich
A2H57N (`Amundi Index Solutions - Amundi MSCI Europe High Dividend Factor
UCITS ETF-C`). In einzelnen `original_names` stehen weiterhin lange historische
Tabellenzeilen. Diese Provenienzwerte dürfen nicht automatisch gelöscht werden;
eine Reparaturvorschau sollte sie lediglich als verdächtig markieren.

### P3-01 – Produktive DB während Prüfung geöffnet

Die externe WAL-Aktivität verhindert einen global unveränderlichen Prüfstand.
Für eine formale Abschlussfreigabe Anwendung schließen und denselben Audit auf
einer unveränderten, read-only Kopie oder bei stillstehender Datenbank
wiederholen.

## 11. SQL- und API-Prüfnachweise

Jede SQLite-Verbindung wurde so geöffnet:

```python
sqlite3.connect('file:C:/.../data/v09/portfolio.sqlite?mode=ro', uri=True)
connection.execute('PRAGMA query_only=ON')
connection.execute('BEGIN')
```

Zentrale SQL-Abfragen:

```sql
PRAGMA integrity_check;
PRAGMA foreign_key_check;
PRAGMA user_version;
PRAGMA schema_version;

SELECT active, COUNT(*) FROM imports GROUP BY active;
SELECT account, COUNT(*) FROM transactions GROUP BY account;
SELECT json_extract(payload, '$.kind'), COUNT(*)
FROM transactions GROUP BY 1;
SELECT kind, COUNT(*) FROM import_model_records GROUP BY kind;
SELECT COUNT(*) FROM fee_links;
SELECT COUNT(*) FROM booking_details;

SELECT file_hash, COUNT(*), group_concat(id)
FROM imports WHERE active=1
GROUP BY file_hash HAVING COUNT(*) > 1;

SELECT account, external_id, COUNT(*), group_concat(id)
FROM transactions
GROUP BY account, external_id HAVING COUNT(*) > 1;

SELECT account, content_hash, COUNT(*), group_concat(id)
FROM transactions
GROUP BY account, content_hash HAVING COUNT(*) > 1;

SELECT content_hash, COUNT(*), group_concat(id), group_concat(import_id)
FROM bank_documents
GROUP BY content_hash HAVING COUNT(*) > 1;

SELECT COUNT(*)
FROM transactions t LEFT JOIN imports i ON i.id=t.import_id
WHERE i.id IS NULL;

SELECT COUNT(*)
FROM bank_documents d LEFT JOIN imports i ON i.id=d.import_id
WHERE i.id IS NULL;

SELECT id, import_id, date,
       json_extract(payload,'$.amount'),
       json_extract(payload,'$.affects_cash'),
       json_extract(payload,'$.performance_depot_key')
FROM transactions
WHERE json_extract(payload,'$.kind')='TAX';

SELECT import_id, source_key, account_key
FROM import_account_links
WHERE source_key LIKE '%4764924%';
```

Saldoabgleich wurde je Import und Konto mit den beiden `balances.value` und
der Summe aller `transactions.payload.amount` desselben Imports durchgeführt.
Alle 27 Differenzen waren `0.00`.

Dateiabdeckung wurde mit SHA-256 über alle rekursiv gefundenen `*.pdf`
ermittelt und gegen `imports.report.source_sha256` verglichen. Ergebnis:
102 Dateien, 93 eindeutige Inhalte, 70 importierte Inhalte, 23 ausschließlich
im Kosteninformationsordner fehlende Inhalte.

Direkte Parserprüfung:

```python
from portfolio_v5.pdf_importer import parse_pdf
batch = parse_pdf(original_pdf_path)
```

Sie wurde ohne Repository für die Schwerpunktfamilien LS9AVX, A2H57N,
LYX05A, A111X9, A0S9GB und 716460 ausgeführt. Es wurden keine Imports
gespeichert.

## 12. Freigabeempfehlung

**FAIL.** Die physische Datenbankintegrität, der Dublettenschutz, die
Dokumentabdeckung, die Cashsalden und die reparierte PDF-Erkennung sind gut.
Vor einer Freigabe müssen jedoch mindestens die fehlenden Steuer-/Dividenden-
Verknüpfungen und die nicht strukturiert nachvollziehbaren Gebührenverbindungen
in einer temporären Datenbank reproduziert und behoben werden. Anschließend ist
die Prüfung bei stillstehender produktiver Datenbank zu wiederholen.

Es wurden keine produktiven Daten und keine Originaldokumente verändert.
