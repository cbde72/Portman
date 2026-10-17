# Importer-Roadmap

## Phase A – Datenintegrität

Branch `codex/importer-p0-data-integrity`:

- anteilige Neutralisierung von Teil-/Sammelzahlungen,
- Status offen/teilweise/vollständig/Konflikt,
- Richtungs-, Währungs- und Restbetragsinvarianten,
- generische Bestände ohne Nachweis standardmäßig partiell,
- Regressionen für Cashflows, Renditen, Bestände und beschädigte Quellen.

Phase A endet mit einem ungemergten PR gegen `main`. Phase B beginnt erst nach
Freigabe und Integration.

### Performance-Nachweis

Der identische synthetische Benchmark aus
`benchmarks/benchmark_import_pipeline.py` ergab vor/nach Phase A folgende
Mediane (drei Läufe):

| Zeilen | Parser vorher / nachher | SQLite vorher / nachher |
|---:|---:|---:|
| 1.000 | 59,8 / 53,7 ms | 406,6 / 314,3 ms |
| 10.000 | 712,4 / 539,1 ms | 3.076,7 / 3.241,6 ms |
| 50.000 | 3.159,4 / 3.309,8 ms | 17.239,7 / 17.047,4 ms |

Die Streuung umfasst einen 42,96-s-Ausreißer beim 50.000er-Commit; deshalb
werden Mediane berichtet. Die Phase-A-Logik liegt nicht im gemessenen
CSV-Schreibpfad. Es ist keine belastbare Performanceverbesserung und keine
systematische Regression erkennbar. Speicherverbrauch und Queryanzahl wurden
in diesem Benchmark nicht instrumentiert und werden daher nicht behauptet.

## Phase B – comdirect und ING

Umgesetzt auf `codex/importers-comdirect-ing`: comdirect-Verkauf im bestehenden
kompakten Layout, ING-Verkauf, ING-Vorabpauschale mit tatsächlicher
Steuerbelastung sowie positive nachträgliche Steuererstattung. Kauf und Verkauf
werden als Depotereignisse normalisiert; die separate Geldbuchung bleibt über
den Phase-A-Vertrag zuordenbar und zählt nicht doppelt.

Nicht verifiziert bleiben insbesondere comdirect-Fremdwährungsverkäufe,
separate comdirect-Steuerkorrekturen, historische Layouts mit beschädigter
Schriftextraktion sowie ING-Kapitalmaßnahmen, Belastungen aus nachträglicher
Verlustverrechnung und weitere FX-/Kirchensteuervarianten. Dafür fehlen
freigegebene anonymisierte Originalbelege; es wurden bewusst keine
spekulativen Regeln ergänzt.

Nachprüfung mit lokal bereitgestellten Dokumenten: Zwei ING-Verkäufe bestätigen
das implementierte Layout sowohl mit als auch ohne ausgewiesene Gebühr. Die
comdirect-Sammlung bestätigt ein weiteres kompaktes Kauf-/Steuerlayout, dessen
eingebettete Schrift Stückzahlen teilweise als null extrahiert. Solche Belege
werden nun ausdrücklich abgewiesen statt mit falschem Bestand importiert.
Mangels verfügbarer lokaler OCR-Laufzeit und sicher lesbarer Stückzahl bleibt
dieses Layout teilweise unterstützt.

## Phase C – Baader, FNZ/ebase und Deka

Umgesetzt auf `codex/importers-baader-fnz-deka`: Baader-Dividende,
Vorabpauschale, Depotübertrag und vollständiger Jahresdepotauszug; eigener
FNZ-/finvesto-Importer für belegte Umsatz- und Depotabrechnungen; Deka-
Ausschüttung plus Wiederanlage sowie historische Jahresdepotauszug-Erkennung.

Bewusst offen bleiben Vorgänge ohne belastbaren Beleg: FNZ-Verkauf,
Vorabpauschale, Übertrag und historische ebase-Kontoumsätze; Baader-
Steuerkorrektur, Managergebühr, Zins, Storno und weitere Kapitalmaßnahmen;
Deka-Verkauf, Fondswechsel, Steuererstattung und Übertrag. Diese Varianten
werden nicht spekulativ interpretiert.

## Phase D – Renault Bank und Bank of Scotland

Geplant: mehrseitige und überlappende Kontoauszüge, Valuta/Buchung,
Zins-/Steuer-/Stornofälle und weitere Layoutversionen. Beide Quellen bleiben
Geldkonten, solange Belege keine Wertpapierfunktion nachweisen.

## Fehlende Nachweise

Prioritär benötigt werden anonymisierte Verkaufs-/Steuer-/FX-Belege von
comdirect und ING, Baader-Ertrags-/Steuerbelege, alte ebase- und neue FNZ-
Dokumente, Deka-Wechsel-/Steuerbelege sowie mehrseitige Renault-/BoS-Auszüge.
Ohne diese Nachweise bleibt der jeweilige Status „nicht verifiziert“ oder
„teilweise“.
