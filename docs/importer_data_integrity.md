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

## comdirect und ING (Phase B)

Wertpapierabrechnungen sind cash-neutrale Depotereignisse mit explizitem
Zahlungskonto. Ein später importierter Kontoumsatz liefert Geldbewegungsbeleg,
ohne den Kauf, Verkauf, Ertrag oder Steuerbetrag ein zweites Mal in der
Performance zu erfassen. Brutto, Gebühren und Netto müssen sich je Richtung
innerhalb eines Cents abstimmen lassen. Bei Vorabpauschalen wird die
Bemessungsgrundlage nicht als Geldbewegung erfunden; nur ein auf dem Dokument
ausgewiesener Steuerabzug wird als `TAX` erfasst.
