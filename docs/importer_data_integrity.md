# Datenintegrität der Importpipeline

## Verbindliche Invarianten

- Originaldateien und Originalbuchungen bleiben unverändert.
- Wiederholte identische Importe sind idempotent.
- Eine Geldbuchung kann nur innerhalb ihres Restbetrags mehreren
  Depotereignissen zugeordnet werden.
- Depot- und Geldseite dürfen nicht überbucht werden.
- BUY benötigt Belastung; SELL, DIVIDEND und TAX_REFUND Gutschrift; TAX und FEE Belastung.
- Währungen müssen bei direkter Zuordnung identisch sein.
- Gleiche Beträge ohne eindeutige Referenz oder exklusive Kandidatenlage werden
  nicht automatisch verbunden.
- Bestände ohne Vollständigkeitsnachweis sind partiell.

## Teil- und Sammelzahlungen

`allocated_amount` ist der belegte Überschneidungsbetrag zweier Originale. Für
eine Geldbuchung mit Betrag `C` und aktiven Zuordnungen `A_i` gilt:

```text
Restbetrag = Vorzeichen(C) × (abs(C) - Summe(A_i))
0 <= Summe(A_i) <= abs(C)
```

Nur wenn beide Originalreferenzen innerhalb der betrachteten Performancegrenze
liegen, wird `A_i` neutralisiert. Der Restbetrag ist eine temporäre
Auswertungssicht und wird nicht in SQLite gespeichert. Vollständige Zuordnung
unterdrückt die Geldseite; Teilzuordnung erhält den Rest. Steuer-, Gebühren-
und Bruttofelder der Originalbuchung werden nicht fälschlich auf den Rest
dupliziert.

## Wirkung auf Finanzgrößen

- Depotbestände und Einstandskosten werden durch den Link nicht verändert.
- Geldkontosalden verwenden weiterhin den vollständigen Originalbetrag.
- TWR/Modified Dietz/XIRR erhalten den Depot-Cashflow und nur den nicht
  überlappenden Geldrest.
- Dividenden- und Steuerbeleg plus zugehörige Geldbuchung zählen nach voller
  Zuordnung jeweils einmal.
- Teilzuordnungen zeigen `partial` und den Restbetrag; vollständige
  Zuordnungen `complete`. Ungültige Altdaten werden als Konflikt bzw. bei der
  Performance als Überbuchungsfehler sichtbar.

## Bestandsvollständigkeit

Generische CSV-/Excel-Tabellen werden nur durch passenden Depotgesamtwert oder
Positionszahl automatisch vollständig. Summenabweichung, doppelte Position,
fehlende Position oder ungültige Positionszahl verhindert den Snapshot. Eine
explizite manuelle Vollständigkeitsbestätigung bleibt möglich und wird als
Warnung am Snapshot dokumentiert.

Bankspezifische Parser dürfen `complete=True` nur nach eigenen Kontrollen
setzen. Baader, comdirect und ING gleichen bereits Gesamtwerte und/oder
Positionszahlen ab; Deka lässt unbekannte Anteile partiell. Konfigurierbare
PDF-Plugins sind ohne ausdrückliches `complete_snapshot=true` standardmäßig
partiell. Auch historische transponierte Deka-Tabellen bleiben ohne
Gesamtnachweis ausdrücklich partiell.

Phase C verschärft dies für FNZ, Deka und Baader: FNZ-Umsatzabrechnungen gelten
unabhängig von rechnerisch passenden Einzelwerten als partiell; FNZ-
Quartalsauszüge und Baader-Jahresdepotauszüge benötigen eine passende
Gesamtsumme. Deka verlangt weiterhin Gesamtwert, stichtagsgleichen Bestand je
Unterdepot und eindeutige Mengen. Ausschüttung plus Wiederanlage erzeugt einen
positiven DIVIDEND- und einen gleich hohen negativen BUY-Cashflow, sodass kein
zusätzlicher Ertrag und keine zusätzliche externe Einzahlung entsteht.

## comdirect und ING (Phase B)

Wertpapierabrechnungen sind cash-neutrale Depotereignisse mit explizitem
Zahlungskonto. Ein später importierter Kontoumsatz liefert Geldbewegungsbeleg,
ohne den Kauf, Verkauf, Ertrag oder Steuerbetrag ein zweites Mal in der
Performance zu erfassen. Brutto, Gebühren und Netto müssen sich je Richtung
innerhalb eines Cents abstimmen lassen. Bei Vorabpauschalen wird die
Bemessungsgrundlage nicht als Geldbewegung erfunden; nur ein auf dem Dokument
ausgewiesener Steuerabzug wird als `TAX` erfasst.

## Geldkontoauszüge (Phase D)

Renault und Bank of Scotland importieren jede saldowirksame Zeile genau einmal.
Zins, TAX und TAX_REFUND werden nur aus eindeutigen Buchungstexten abgeleitet;
der Betrag behält das tatsächliche Vorzeichen. Steuerzeilen werden nicht noch
einmal als Teil des Zinsertrags gebucht. Überlappende und wiederholte Auszüge
verwenden stabile fachliche IDs, während echte identische Mehrfachbuchungen
durch einen Vorkommenszähler innerhalb desselben Auszugs erhalten bleiben.

Ein vollständiger Auszug wird nur akzeptiert, wenn Anfangssaldo plus alle
Buchungen dem Endsaldo entspricht. Bei Renault ersetzt der geprüfte Zeitraum
vorhandene PDF-/FinTS-Geldbuchungen derselben Periode atomar und rückgängig
machbar. Eigene Überweisungen zählen erst nach expliziter Transferpaarung als
interne Bewegung und verändern dann weder externe Beiträge noch Erträge.
