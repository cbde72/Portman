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

## Validierter comdirect-Export 2026

Der Referenzexport wurde lokal und in einer isolierten Datenbank geprüft; die
private CSV und die PDF gehören nicht zum Repository. Das Ergebnis stimmt mit
den erwarteten Werten überein: 38 Einzelvorgänge, 14 Vorabpauschalen, davon 3
steuerpflichtig, 192,24 EUR FSA-Verbrauch aus Vorabpauschalen und 0,00 EUR darauf
gezahlte Steuer. Über alle Vorgänge ergeben sich 508,89 EUR Bemessungsgrundlage
nach Verlustverrechnung, 411,00 EUR FSA-Verbrauch, 97,89 EUR Bemessungsgrundlage
nach FSA, 24,47 EUR Kapitalertragsteuer, 1,32 EUR Solidaritätszuschlag und 25,79
EUR Gesamtsteuer.

Die Belastungsfelder des Originalexports sind negativ vorzeichenbehaftet. Die
genannten Prüfwerte sind deren fachliche Absolutbeträge. Beim gemeinsamen Import
gewinnt die reichere PDF für dasselbe Steuerereignis; die passende CSV-Zeile
bleibt als Originaldatensatz sichtbar, wird in Übersichten aber nicht ein zweites
Mal addiert.
