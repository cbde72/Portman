# SQLite-Integrationstest A0H074 vom 15.09.2026

## Ergebnis

**Abnahme nicht bestanden.** Der Test wurde am 21.10.2026 auf dem Branch
`fix/comdirect-investment-tax-notices` mit Commit `3a45a2d` ausgeführt. Für
jede Importreihenfolge wurde eine neue temporäre SQLite-Datenbank angelegt und
anschließend vollständig gelöscht. Produktive Datenbanken und Original-PDFs
wurden weder geöffnet noch verändert.

Es wurden keine Codeänderungen vorgenommen.

## Verwendete Originalbelege

- Steuermitteilung:
  `C:\Users\chris\Desktop\history\comdirect\2026\Steuerinformationen\Steuermitteilung_A0H074_(IS.DJ_AS.PAC.S.D.50_U.ETF)_vom_15.09.2026_F181E5.pdf`
- Zugehöriger Finanzreport:
  `C:\Users\chris\Desktop\history\comdirect\2026\2026-10-01_Finanzreport_Nr._09_5FCE8E.pdf`
- Identische Kopie des Finanzreports:
  `C:\Users\chris\Desktop\history\comdirect\2026\Januar\2026-10-01_Finanzreport_Nr._09_5FCE8E.pdf`

Unter den 102 PDFs wurde keine separate ursprüngliche Ausschüttungsabrechnung
für A0H074 vom 15.09.2026 gefunden. Der Finanzreport enthält jedoch die
vollständige Kontobuchung einschließlich Brutto- und Steuerinformation.

## Gefundene fachliche Bezüge

### Finanzreport

| Feld | Wert |
|---|---|
| Externe ID | `comdirect-pdf-c26c90418f8b25277672e85284f0bc7b8ce4ee1f799efc6ec5368496d987733e-1` |
| Bankreferenz | `0S5C29F709I0G` |
| Datum / Valuta | 15.09.2026 / 15.09.2026 |
| Konto | `IBAN DE71200411330476492440` |
| Erkannte Art | `DIVIDEND` (Rohimport: `BANK_BOOKING`) |
| Wertpapier | `WKN:A0H074` |
| Stückzahl | 27,051 |
| Brutto | 9,10 EUR |
| Steuerabzug | 1,67 EUR |
| Netto-Kontobuchung | +7,43 EUR |

### Steuermitteilung

| Feld | Wert |
|---|---|
| Steuerereignis-ID | `pdf-comdirect-investment-distribution-tax-dca10eed3f5057a22b63d8dd234fa5a0d7bdb6e41940828bdd7061aeafe66ca9` |
| Zahlungs-ID | Ereignis-ID mit Suffix `-payment` |
| Belegreferenz | `1IINP4025ZX000SB` |
| ISIN / WKN | `DE000A0H0744` / `A0H074` |
| Stückzahl | 27,051 |
| Brutto | 9,10 EUR |
| Teilfreistellung | 30 % / 2,73 EUR |
| Steuerbasis | 6,37 EUR |
| Kapitalertragsteuer | 1,59 EUR |
| Solidaritätszuschlag | 0,08 EUR |
| Kirchensteuer | 0,00 EUR |
| Gesamtsteuer | 1,67 EUR |
| Netto | 7,43 EUR |

## Testaufbau

In jeder Datenbank wurden vor dem Import ausschließlich folgende isolierte
Konten angelegt:

- `Depot 4764924` als comdirect-Depot,
- `IBAN DE71200411330476492440` als verknüpftes Verrechnungskonto,
- die beiden weiteren im Finanzreport vorkommenden comdirect-Konten.

Die Importvorschau schlug für das Steuerdokument korrekt vor:

```text
Depot 476492400 -> Depot 4764924
Grund: comdirect-Depotnummer mit Unterkontokennung stimmt eindeutig überein
```

## Tatsächlich ausgeführte SQL-Prüfungen

Die folgenden Abfragen wurden nach jedem Importschritt ausgeführt:

```sql
SELECT COUNT(*)
FROM imports
WHERE active=1;

SELECT COUNT(*)
FROM transactions t
JOIN imports i ON i.id=t.import_id
WHERE i.active=1;

SELECT
  json_extract(t.payload,'$.kind'),
  json_extract(t.payload,'$.amount'),
  json_extract(t.payload,'$.taxes'),
  json_extract(t.payload,'$.external_id'),
  json_extract(t.payload,'$.bank_reference'),
  json_extract(t.payload,'$.performance_depot_key')
FROM transactions t
JOIN imports i ON i.id=t.import_id
WHERE i.active=1
  AND (
    json_extract(t.payload,'$.security')='DE000A0H0744'
    OR (
      json_extract(t.payload,'$.date')='2026-09-15'
      AND json_extract(t.payload,'$.amount')='7.43'
    )
  )
ORDER BY t.id;

SELECT
  json_extract(m.payload,'$.external_id'),
  json_extract(m.payload,'$.taxable_income'),
  json_extract(m.payload,'$.partial_exemption_amount'),
  json_extract(m.payload,'$.paid_taxes'),
  json_extract(m.payload,'$.related_transaction_id')
FROM import_model_records m
JOIN imports i ON i.id=m.import_id
WHERE i.active=1
  AND m.kind='tax_events'
  AND json_extract(m.payload,'$.security_ref')='DE000A0H0744';

SELECT COUNT(*), COUNT(DISTINCT content_hash)
FROM bank_documents d
JOIN imports i ON i.id=d.import_id
WHERE i.active=1 AND d.date='2026-09-15';
```

Zusätzlich wurden über die bestehenden Repository-APIs geprüft:

- `transactions()` und die automatische Wertpapierzuordnung,
- `tax_events()` und `tax_detail_records()`,
- `automatic_tax_values(..., 2026)`,
- `performance_transactions(...)`,
- `holdings()` und `balances_at('2026-10-01')`.

## Test 1: Steuermitteilung zuerst, danach Finanzreport

### Reguläre Depotzuordnung

Die Steuermitteilung wurde trotz des eindeutigen Zuordnungsvorschlags nicht
gespeichert:

```text
Das zugeordnete Performance-Depot fehlt oder ist inaktiv.
```

SQL unmittelbar danach:

| Wert | Ergebnis |
|---|---:|
| Aktive Imports | 0 |
| Transaktionen | 0 |
| Steuerereignisse A0H074 | 0 |
| Dokumente | 0 |

Ursache: Das Steuerereignis wird auf `Depot 476492400` gemappt, die erzeugte
Steuerbuchung behält jedoch `performance_depot_key='depot 476492400'`. Die
Validierung prüft diesen nicht gemappten Quellschlüssel gegen das vorhandene
Zieldepot `depot 4764924` und lehnt den gesamten Import atomar ab.

Der anschließende Finanzreport wurde korrekt importiert:

| Wert | Ergebnis |
|---|---:|
| Aktive Imports | 1 |
| Transaktionen gesamt | 35 |
| A0H074-Nettozahlung | genau 1 × +7,43 EUR |
| A0H074-Steuer im Dividendendatensatz | 1,67 EUR |
| A0H074-Bestand | 27,051 Stück |
| Kontosaldo am 01.10.2026 | 119,82 EUR |

Ein Wiederholungsimport des Finanzreports wurde als `duplicate` erkannt und
änderte keine Zahl. Jeder Wiederholungsversuch der Steuermitteilung scheiterte
erneut atomar mit demselben Mappingfehler.

## Test 2: Finanzreport zuerst, danach Steuermitteilung

Der Finanzreport erzeugte wiederum genau eine Nettozahlung von 7,43 EUR. Der
anschließende Import der Steuermitteilung scheiterte mit demselben
`performance_depot_key`-Fehler. Ergebnis und Wiederholungsversuche waren damit
identisch zu Test 1. Die Reihenfolge ändert den Fehler nicht, ermöglicht aber
auch keine vollständige Verarbeitung.

## Diagnoselauf mit separat registriertem Quell-Depot

Um die nachgelagerten Berechnungen trotz des Mappingfehlers zu prüfen, wurde in
zwei weiteren temporären Datenbanken zusätzlich `Depot 476492400` als eigenes
Depot registriert. Das ist **kein gültiger Reparaturweg**, sondern isoliert nur
die Logik nach der Speicherprüfung.

Beide Importreihenfolgen führten zum gleichen Endzustand:

| Datensatz | Betrag | Steuerfeld | Performance-Depot |
|---|---:|---:|---|
| Finanzreport-Dividende | +7,43 EUR | 1,67 EUR | `depot 4764924` |
| separate Steuerbuchung | -1,67 EUR | 1,67 EUR | `depot 476492400` |

Damit liegt zwar nur eine Nettoauszahlung vor, die bereits in ihr enthaltene
Steuer wird aber zusätzlich als echter Cash- und Performanceabfluss gebucht.

### Wirtschaftliche Vorher-/Nachherwerte

| Prüfung | Nur Finanzreport | plus Steuermitteilung | Soll |
|---|---:|---:|---:|
| A0H074-Bruttoertrag | 9,10 EUR | 9,10 EUR | 9,10 EUR |
| A0H074-Nettoauszahlung | 7,43 EUR | 7,43 EUR | 7,43 EUR |
| wirtschaftliche Steuer | 1,67 EUR | **3,34 EUR** | 1,67 EUR |
| Cash-/Nachsteuerfluss | 7,43 EUR | **5,76 EUR** | 7,43 EUR |
| Vorsteuer-Performancefluss | 9,10 EUR | 9,10 EUR | 9,10 EUR |

Die gesamte Steuerübersicht des Finanzreports stieg nach Import der
Steuermitteilung von 19,41 EUR auf 21,08 EUR, also nochmals um 1,67 EUR. Der
Kapitalertrag blieb unverändert; die Teilfreistellung aus dem regulären
Ausschüttungsereignis wurde in der Jahresübersicht nicht berücksichtigt.

Der dokumentierte Kontostand von 119,82 EUR blieb unverändert, weil er direkt
aus dem Finanzreport stammt. Das Buchungsjournal enthält jedoch für den
15.09.2026 fälschlich `7,43 - 1,67 = 5,76 EUR` statt des tatsächlichen
Kontozuflusses von 7,43 EUR.

Bestände blieben in allen Wiederholungen unverändert:

| Feld | Wert |
|---|---:|
| Positionen gesamt | 18 |
| A0H074 Stück | 27,051 |
| A0H074 Einstand | 715,96 EUR |
| A0H074 Wert am 01.10.2026 | 869,78 EUR |

## Steuerliche Detailansicht

Die belegten Steuerwerte erscheinen, aber nicht korrekt zusammengeführt:

1. Ein abgeleiteter Dividenden-Datensatz aus dem Finanzreport enthält Brutto
   9,10 EUR, Steuer 1,67 EUR und Netto 7,43 EUR.
2. Ein zusätzlicher Ereignis-Datensatz enthält Steuerbasis 6,37 EUR,
   Teilfreistellung 2,73 EUR sowie KapESt 1,59 EUR, SolZ 0,08 EUR und KiSt
   0,00 EUR.

Der zweite Datensatz wird dabei fälschlich als `Vorgang: Vorabpauschale`
ausgegeben, obwohl der Ereignistyp `investment_ausschuettung_inland` lautet.
Beide Zeilen sind nicht miteinander verknüpft; `linked_transaction_id` bleibt
beim Steuerereignis leer. Außerdem ist dessen berechneter Wert
`Gewinn/Verlust nach Steuern = 4,70 EUR` (6,37 - 1,67) kein belegter
Auszahlungsbetrag.

## Wiederholungsimporte

Im Diagnoselauf blieben Transaktionsanzahl, Steuerereignisanzahl, Bestände und
Performancewerte nach Wiederholungen stabil:

- Finanzreport: korrekt als `duplicate` erkannt.
- Steuermitteilung: Steuerbuchung `unchanged`, Steuerereignis weiterhin genau
  einmal vorhanden.

Die Steuermitteilung erzeugte beim zweiten Import jedoch einen weiteren aktiven
Import und eine zweite `bank_documents`-Zeile mit demselben Content-Hash:

| Wert | Erster Import | Wiederholung |
|---|---:|---:|
| Steuerereignisse | 1 | 1 |
| Steuerbuchungen | 1 | 1 |
| Dokumentzeilen | 1 | 2 |
| unterschiedliche Dokument-Hashes | 1 | 1 |

Die fachlichen Buchungszahlen sind somit idempotent, die Dokumentablage und der
Importdatensatz jedoch nicht vollständig.

## Bewertung der Abnahmekriterien

| Kriterium | Ergebnis |
|---|---|
| Genau ein fachlicher Ausschüttungsvorgang | **Nicht erfüllt**: Dividende und Steuerereignis werden nicht zusammengeführt |
| Keine doppelte Nettoauszahlung | Erfüllt |
| Keine doppelte wirtschaftliche Steuerbelastung | **Nicht erfüllt**: 3,34 statt 1,67 EUR |
| Detailansicht enthält belegte Werte | Teilweise; Werte vorhanden, aber zwei unverbundene Zeilen und falscher Vorgangstyp |
| Reihenfolge beeinflusst Ergebnis nicht | Der Fehler ist in beiden Reihenfolgen gleich; vollständiger Import scheitert |
| Wiederholung ändert Buchungen/Bestände/Performance nicht | Erfüllt im Diagnoselauf; Dokumentablage wird dupliziert |
| Unklare Zuordnung erzeugt keine Doppelbuchung | Regulär atomar abgelehnt, aber ohne gezielten Prüfhinweis zur bereits enthaltenen Steuer |

## Konkrete Fehlerursachen für eine spätere Korrektur

1. `performance_depot_key` der erzeugten Steuerbuchung wird bei der
   Konto-/Depotzuordnung nicht vom Quell- auf das Zieldepot übertragen.
2. Die Finanzreport-Dividende enthält bereits Netto und Gesamtsteuer. Die
   separate Steuermitteilung darf daher nicht zusätzlich als cash-wirksame
   Steuerbuchung gezählt werden, sondern muss die vorhandene Dividende anhand
   von ISIN/WKN, Datum, Brutto/Netto, Konto/Depot und Referenz ergänzen.
3. Die automatische Steuerdetailansicht behandelt jedes `TaxEvent` wie eine
   Vorabpauschale und kennt den neuen Ausschüttungstyp nicht.
4. Ein Wiederimport mit bereits vorhandenem Steuerereignis verändert die
   Importidentität und archiviert dasselbe PDF erneut.

Diese Punkte wurden in diesem Auftrag nur nachgewiesen und dokumentiert; es
wurde bewusst keine Korrektur implementiert.
