# Steuerliche Detailansicht (V09)

## Datenmodell und Quellenpriorität

Der comdirect-Export wird als eigenständige Quelle `tax_details` in der bestehenden
Import-Historie gespeichert. Jede Zeile enthält alle 32 benannten Spalten als
unveränderte Zeichenketten (`original_values`). Dadurch bleiben insbesondere
deutsche Dezimaldarstellung, Vorzeichen und die gerundete CSV-Stückzahl als
Beleginhalt erhalten. Diese Stückzahl aktualisiert niemals einen Depotbestand.

Die stabile Identität verwendet vorrangig Institut/Konto und Referenznummer. Fehlt
die Referenz, wird sie aus Steuerjahr, Buchungs- und Steuerdatum, Vorgang, WKN und
den maßgeblichen Beträgen gebildet. Überlappende oder erneut exportierte Dateien
erzeugen daher keinen zweiten steuerlichen Vorgang.

PDF-Steuermitteilungen bleiben für Details maßgeblich, die im CSV fehlen oder dort
nur gerundet vorkommen (beispielsweise Vorabpauschale, Teilfreistellung und exakte
Stückzahl). Eine Zuordnung erfolgt konservativ über Depot, Referenz, WKN/ISIN und
Datum. Bei mehreren Treffern wird `ambiguous` ausgewiesen und nichts automatisch
zusammengeführt. In der Steuerübersicht wird ein verknüpfter CSV-Vorgang nicht
nochmals berücksichtigt. Eine unverknüpfte CSV-Vorabpauschale dient als Fallback
für steuerpflichtigen Betrag, FSA-Verbrauch und tatsächlich ausgewiesene Steuern;
sie erzeugt weder eine Geld- noch eine Bestandsbuchung.

## Bedienung

`Importieren → comdirect-Steuerdetails importieren` durchläuft die reguläre
Vorschau und Konto-/Depotzuordnung. `Werkzeuge → Steuerliche Detailansicht` bietet
Institut-, Konto-/Depot-, Steuerjahr- und Vorgangsfilter, Volltextsuche,
Sortierung, gruppierte Spaltenauswahl sowie CSV- und Excel-Export. Ein Doppelklick
zeigt alle Originalwerte, Quelle, Referenz, PDF-Verknüpfung, Geldbuchung und
Zuordnungsstatus.

## Bewusst offene Fälle

- Der comdirect-Export enthält kein separates Belegdatum und kein Ertragsjahr.
  Diese Werte werden ausschließlich aus einem verknüpften PDF übernommen und
  nicht aus Buchungs- oder Steuerdatum geraten.
- Fortlaufende Verlusttopf- und Steuersalden werden als Originalwerte angezeigt.
  Portman berechnet sie nicht neu, solange kein nachweislich vollständiger
  Anfangsbestand und lückenloser Buchungsbestand vorliegt.
- Mehrdeutige PDF- oder Geldbuchungszuordnungen bleiben zur manuellen Prüfung
  markiert; eine automatische Auswahl unter gleichwertigen Kandidaten findet
  nicht statt.
