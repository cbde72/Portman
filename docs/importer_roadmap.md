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

Geplant: verifizierte Verkaufs-, Gebühren-, Steuer-/Erstattungs-, FX-,
Vorabpauschal- und Korrekturbelege. Voraussetzung sind anonymisierte Fixtures
je Layout. Finanzreport-Geldbuchungen und Wertpapierbelege werden über den
Phase-A-Vertrag als ein wirtschaftlicher Vorgang behandelt.

## Phase C – Baader, FNZ/ebase und Deka

Geplant: Baader-Ertrag/Steuer/Kapitalmaßnahme, eigener FNZ-/ebase-Importer mit
getrennten historischen Layoutfamilien und erweiterter Deka-Lebenszyklus.
Ausschüttung plus Wiederanlage sind Ertrag plus Kauf; Fondswechsel werden ohne
eindeutigen Beleg nicht steuerlich interpretiert. Bei ausreichendem Umfang wird
die Phase in bankweise PRs geteilt.

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
