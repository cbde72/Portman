# Portman PDF Lab – Phase-6-comdirect-Implementierungsbericht

**Datum:** 31.10.2026  
**Pakete:** `portman-parsers 0.6.0`, `portman-pdf-lab 0.6.0`  
**API:** `0.6`, **Schema:** `1.5.0`

## Ergebnis

Die beiden bestehenden Plugin-Einstiegspunkte `user.comdirect-ertraege` und
`comdirect.finanzreport` sind im unabhängigen Paket aktiv. Alle zehn
inventarisierten Handler werden erkannt und ausgeführt. Der Code importiert
weder `portfolio_v5` noch alte Importer, Stores, Datenbanken, Konfigurationen
oder GUI-Module. V09 und V10 wurden nicht geändert.

Implementiert sind:

| Handler | Wirtschaftliche Wirkung | Wesentliche Ausgabe |
|---|---|---|
| `dividendengutschrift` | tatsächliche oder erwartete Gutschrift | Wertpapier, Steuern, Gebühren, Konto/Depot, Evidence |
| `ertragsgutschrift` | tatsächliche oder erwartete Gutschrift | eigener Detection-/Parse-Golden |
| `einloesung` | Abgang Wertpapier, Settlement | vollständiger wirtschaftlicher Golden |
| `kosteninformation_mifid_ii` | **keine** Cashwirkung | ex ante/ex post, Kostenkomponenten |
| `investment_ausschuettung` | steuerliche Mitteilung | TaxEvent, keine erfundene Zahlung |
| `dividende_steuer_inland` | steuerliche Mitteilung | TaxEvent, keine zweite Dividende |
| `vorabpauschale` | **keine** Cashwirkung ohne Buchung | TaxEvent, Berechnung, Carryforward |
| `wertpapierkauf` | Wertpapierzugang, Settlement | SecurityTrade, Gebühren/Steuern, Evidence |
| `wertpapierverkauf` | Wertpapierabgang, Settlement | SecurityTrade, Gebühren/Steuern, Evidence |
| `finanzreport` | echte Kontobuchungen; Depot nur Snapshot | Konten, Salden, Buchungen, Depotpositionen |

## Algorithmen und Datenmodell

Die Migration verwendet native öffentliche DTOs. `SecurityTrade` bewahrt die
gedruckten Werte für Name, ISIN, WKN, Geschäfts-, Ausführungs- und Valutatag,
Stückzahl, Kurs, Kurswert, Brutto, Devisenkurs und Settlement. Alle Zahlen
werden als `Decimal` verarbeitet; fehlende PDF-Werte bleiben `MissingValue` und
werden nicht rechnerisch überschrieben.

Ein aus IBAN und Depotnummer im konkreten Beleg nachgewiesener Zusammenhang
erzeugt einen nicht als Standard behaupteten `DepotAccountLink`. Ohne Nachweis
bleibt die Zuordnung offen. Es wird kein künstliches Verrechnungskonto erzeugt.
Der Finanzreport kann Giro- und Verrechnungskonten enthalten. Ein dort
aufgeführter Depotbestand wird ausschließlich als `DepotSnapshot` modelliert.

Finanzreport-Buchungen werden über Konto, Buchungsdatum, Valuta, Text und Betrag
identifiziert. Identische Zeilen werden einmal ausgegeben und als
`DUPLICATE_BOOKING` gemeldet. Anfangssaldo plus Buchungen wird gegen Endsaldo,
die Positionssumme gegen den Depotgesamtwert geprüft. Dokumentnummer,
Berichtszeitraum und erkannter Core-/Legacy-Pfad werden gespeichert.

## Steuern, Kosten und Verknüpfung

Die Vorabpauschale trennt Bemessungsgröße, Teilfreistellung,
Freistellungsauftrag, Verlustverrechnung und ausgewiesene Steuerkomponenten.
Sie erzeugt selbst keinen Cashflow. `AdvanceTaxCalculation` ist ohne bestätigte
Referenz als `SYNTHETIC_ONLY` gekennzeichnet; ein Carryforward entsteht nur bei
belegter ISIN, Depot, Steuerjahr und steuerpflichtigem Betrag. Es werden keine
fehlenden gesetzlichen Eingaben erfunden.

MiFID-II-Produkt-, Dienstleistungs-, Einmal-, laufende, Transaktionskosten und
Zuwendungen sind `informational=True` und haben keine Cashbewegung. Gebuchte
Handelsgebühren bleiben davon getrennt. Die konservative
Cross-Dokument-Verknüpfung verlangt mindestens zwei Merkmale (z. B. ISIN plus
Datum oder Depot); Betrag allein genügt nicht. Nicht eindeutige Steuerfälle
werden als Reviewfall ausgegeben.

## PDF Lab und Referenzen

Die vorhandene PySide6-GUI behält ihre neun Reiter. Original-PDF und Ergebnis
stehen nebeneinander; Evidence navigiert zur Seite und zeigt den Fundtext.
Cash-Status unterscheidet `ACTUAL` und `EXPECTED`, Links sind im Resultat
sichtbar. Tabellen unterstützen die Qt-Zell-/Mehrfachauswahl. Im Reiter
Referenzvergleich kann ein feldweiser Sollwert per Doppelklick bearbeitet
werden; jede Änderung läuft über `set_reference` und wird historisiert. Neue
Parserläufe überschreiben bestätigte Sollwerte nicht.

## Test-zu-Handler-Matrix

| Handlergruppe | Detection | Parse | Cashneutralität/Deduplizierung | Golden/Details |
|---|---:|---:|---:|---:|
| Dividende/Ertrag | ja | ja | Steuerdokument getrennt | Ertrags-Golden |
| Einlösung | ja | ja | eindeutiges Settlement | Einlösungs-Golden |
| MiFID II | ja | ja | ja | Komponenten-Test |
| Investment/Dividendensteuer | ja | ja | ja | Handler-Matrix |
| Vorabpauschale | ja | ja | ja | Steuerdetail-/Carryforward-Test |
| Kauf/Verkauf | ja | ja | erwartetes vs. tatsächliches Settlement | zwei Goldens + Detailtest |
| Finanzreport | ja | ja | Buchungsdubletten; Snapshot statt Kauf | Saldo-, Depot-, Dublettentest |

Abschlusslauf mit lokalem beschreibbarem Tempverzeichnis:

```text
137 passed in 4.08s
```

Damit bestehen auch Bank of Scotland, FNZ/finvesto, Architektur, API-Verträge,
PDF-Fehlerfälle, SQLite, Reviewhistorie, Batch, JSON/CSV, Versionsvergleich und
offscreen GUI weiter.

## Performance

Die End-to-End-Anwendung misst Extraktion, Detection, Parsing, Validierung und
Berichtserstellung separat. Ein synthetischer regulärer Finanzreport mit 1.000
unterschiedlichen Buchungen wurde zehnmal ohne Fastpath geparst:

| Messwert | Ergebnis |
|---|---:|
| Ereignisse | 1.000 |
| Median Parsing | 56,546 ms |
| Minimum | 55,399 ms |
| Maximum | 92,987 ms |

Es wurde kein `_comdirect_fast.py` übernommen.

## Wheels und Isolation

Beide Wheels wurden gebaut. In einer frischen venv wurden sie mit leerem
`PYTHONPATH` installiert. Der Check `tools/phase6_isolation_check.py` bestätigte
alle zehn Handler, MiFID-/Vorabpauschalen-Cashneutralität, SQLite-Persistenz,
neun GUI-Reiter und ausschließlich aus `site-packages` geladene Portman-Module:

```text
phase6 isolation: 10 handlers, sqlite, gui, wheel origins OK
```

Auf diesem Rechner war die automatisch gewählte PySide6-6.12-Binärdistribution
beim Laden von `QtWidgets` inkompatibel. Mit PySide6 6.9.2 war der Test grün;
deshalb lautet die Paketgrenze nun `PySide6>=6.8,<6.12`.

## Evidence-Qualität und offene fachliche Punkte

Jeder erkannte Vorgang besitzt Dokument-, Seiten-, Handler- und Parserbezug.
Die aktuelle pypdf-Extraktion liefert Seiten und Textauszüge, aber keine
belastbaren Bounding Boxes. Die GUI springt daher zur Seite, nicht zu einer
erfundenen exakten Koordinate.

Die vorhandenen comdirect-Goldens sind synthetisch. Ohne freigegebene reale,
anonymisierte Dokumente gibt es ausdrücklich keine produktive Layoutfreigabe.
Noch offen für Phase 7 sind insbesondere:

1. bestätigte Goldens mehrerer historischer Core-/Legacy-Jahre;
2. mehrzeilige und tabellarisch verschobene Finanzreportvarianten;
3. Fremdwährungs-, Kirchensteuer- und Stornofälle aus Realbelegen;
4. dokumentübergreifende Persistenz von Links und überlappenden Zeiträumen;
5. Bounding-Box-Evidence/OCR sowie fachlich bestätigte Steuerregelsätze.

Diese Unsicherheiten werden konservativ als fehlend oder reviewpflichtig
behandelt; es entstehen daraus keine künstlichen Konten, Käufe, Steuerabzüge
oder Cashflows.
