# Automatische steuerliche Detailansicht

Die Ansicht unter **Werkzeuge → Steuerliche Detailansicht** ist eine
schreibgeschützte Projektion der aktiven Imports. Sie speichert und verändert
keine abgeleiteten Steuerzeilen. Nach Import, Rücknahme oder Neuzuordnung wird
sie aus CSV-Originalzeilen, `TaxEvent`-Belegen und steuerrelevanten Transaktionen
neu aufgebaut. Das einheitliche Schema ist exakt `COLUMNS` aus
`comdirect_tax_detail.py` und gilt damit für alle Institute.

## Quellenpriorität und Zusammenführung

1. Eine importierte Steuerdetail-CSV bleibt mit allen 32 Originaltexten
   unverändert maßgeblich.
2. Ein eindeutig zugeordnetes PDF ergänzt nur den Herkunftsnachweis und Werte,
   die außerhalb der 32 Originalfelder angezeigt werden. Abweichungen werden
   als `conflict` markiert; der CSV-Wert wird nicht überschrieben.
3. Fehlt eine CSV-Zeile, erzeugt ein strukturiertes `TaxEvent` eine dynamische
   32-Spalten-Zeile.
4. Fehlen CSV und Steuerereignis, werden belegte Dividenden, Ausschüttungen,
   Zinsen, Verkäufe, Steuerzahlungen und -erstattungen aus aktiven Transaktionen
   projiziert. Eine Steuerzahlung erscheint nur bei `affects_cash=True`.
5. Ein über Referenz oder über Depot, WKN/ISIN, Datum und Betrag verknüpfter
   Vorgang wird nur einmal angezeigt. Mehrere Kandidaten bleiben getrennt und
   werden als mehrdeutig gekennzeichnet.

Jede belegte Zelle besitzt `column_provenance` mit Status und Quelle. Leere
Zellen stehen ausdrücklich für „nicht zuverlässig bestimmbar“. Die Oberfläche
markiert sie gelb, widersprüchliche Zeilen rot und zeigt den Herkunftsnachweis
im Doppelklick-Dialog. Verlusttopf- oder FSA-Salden werden niemals ohne belegten
Ausgangssaldo und vollständige Historie fortgeschrieben.

## Abdeckung der 32 Spalten

| Spalte | Automatische Regel | Sichere Quelle / Grenze |
|---|---|---|
| Steuerjahr | Jahr des Steuerdatums | CSV, Steuerereignis oder Buchungsdatum |
| Buchungstag | dokumentiertes Buchungs-/Belegdatum | Kein geratenes Valutadatum |
| Steuerliches Datum | steuerlicher Zufluss, sonst Buchungstag | PDF-Steuerereignis oder Transaktion |
| Referenznummer | dokumentierte Referenz | Externe ID nur als technische Ersatzreferenz |
| Vorgang | normalisierter Fachtyp | Vorabpauschale, Dividende, Ausschüttung, Zins, Verkauf, Steuer/Erstattung |
| Stück/Nominale | dokumentierte Stückzahl | Leer bei reiner Geldbuchung |
| Bezeichnung | Wertpapierstamm oder Gegenpartei | Kein erfundener Wertpapiername |
| WKN | Wertpapierstamm | Leer, wenn nur eine nicht auflösbare ISIN vorliegt |
| Betrag Brutto | dokumentierter Bruttoertrag; bei Vorabpauschale deren Bruttobasis | Keine Netto-Hochrechnung ohne Komponenten |
| Gewinn/Verlust | dokumentierter Ertrag oder vollständig belegter steuerlicher Verkaufsgewinn | Verkauf nur bei sicherem FIFO und Abdeckung |
| Gewinn Aktien | nur Originalwert | Keine Klassifikation ohne Steuerbeleg |
| Verlust Aktien | nur Originalwert | Keine Klassifikation ohne Steuerbeleg |
| Gewinn Sonstige | belegter Fonds-/Zins-/Dividendenertrag | CSV bleibt maßgeblich |
| Verlust Sonstige | PDF-Teilfreistellung als negativer Minderungsbetrag | Sonstige Verluste sonst nur aus CSV |
| verrechneter Gewinn Aktien | nur Originalwert | Unbekannt ohne Bankberechnung |
| verrechneter Verlust Aktien | nur Originalwert | Unbekannt ohne Bankberechnung |
| verrechneter Gewinn Sonstige | nur Originalwert | Unbekannt ohne Bankberechnung |
| verrechneter Verlust Sonstige | nur Originalwert | Unbekannt ohne Bankberechnung |
| BMG nach VV | steuerpflichtiger Betrag minus belegte Verlustverrechnung | Sonst leer |
| Veränderung FSA | negativer belegter Verbrauch | Keine Ableitung aus Steuersatz |
| BMG nach FSA | BMG nach VV minus belegter FSA-Verbrauch | Nur mit beiden Komponenten |
| Umsatz anrechenbarer Quellensteuer | dokumentierter anrechenbarer Betrag | PDF/Transaktionskomponente |
| Veränderung Anrechenbare Quellensteuer | nur Originalwert | Unbekannt ohne Banksaldo |
| Veränderung Angerechnete Quellensteuer | nur Originalwert | Unbekannt ohne Banksaldo |
| Kapitalertragssteuer | dokumentierte Steuerkomponente | Keine Aufteilung einer bloßen Gesamtsumme |
| Solidaritätszuschlag | dokumentierte Steuerkomponente | Keine Schätzung |
| Kirchensteuer | dokumentierte Steuerkomponente | Keine Schätzung |
| Summe Steuern | dokumentierte Komponenten/Gesamtsumme | Tatsächliche Zahlung nur bei Kontobelastung |
| Gewinn/Verlust nach Steuern | dokumentierter Nettobetrag | Keine Ergänzung unbekannter Gebühren |
| Steuerbemessungsgrundlage | dokumentierte steuerpflichtige Basis | Nicht mit Bruttoertrag gleichgesetzt |
| Gewinn/Verlust Aktien (Saldo) | dokumentierter Banksaldo nach Vorgang | Keine Fortschreibung ohne Anfangssaldo |
| Gewinn/Verlust Sonstige (Saldo) | dokumentierter Banksaldo nach Vorgang | Keine Fortschreibung ohne Anfangssaldo |

## Referenzabgleich 2026

Der private comdirect-Export wurde lokal, nicht im Repository, geprüft: 38
Vorgänge, 14 Vorabpauschalen, davon 3 steuerpflichtig, 192,24 EUR FSA-Verbrauch
aus Vorabpauschalen, 411,00 EUR insgesamt, 508,89 EUR BMG nach
Verlustverrechnung, 97,89 EUR BMG nach FSA und 25,79 EUR Gesamtsteuer. Für
A111X9 zeigt bereits die PDF allein 137,65 EUR Bruttobasis, −41,30 EUR
Teilfreistellung, 96,35 EUR steuerpflichtigen Betrag, −96,35 EUR FSA-Verbrauch
und 0,00 EUR gezahlte Steuer. Mit zusätzlicher CSV bleibt genau eine
wirtschaftliche Zeile erhalten.

Nicht automatisch bestimmbar bleiben insbesondere die steuerliche Aufteilung
von Verkäufen ohne vollständige Anschaffungshistorie, Verlusttopfbewegungen ohne
Banknachweis, FSA-Verbrauch ohne Beleg sowie Korrektur-/Stornofolgen mit
mehrdeutigen Referenzen.
