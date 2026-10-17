# Depotbuchungen und Zahlungsquellen – Audit und Konzept

## Bestand vor der Änderung

`Transaction` und `BankTransaction` besitzen bereits stabile Importfelder für
Depot, Geldkonto, Gruppe, Referenzen, Steuern, Gebühren, FX und Storno. Das Feld
`performance_depot_key` ordnet einen Geldvorgang wirtschaftlich einem Depot zu,
ohne das gesamte Geldkonto in das Depotvermögen aufzunehmen. `settlement.py`
führt doppelte Dividendenbelege nur bei einem eindeutigen Match zusammen und
`performance_transactions()` verschiebt Käufe, Verkäufe und Erträge an die
richtige Performancegrenze. Datei- und Buchungsdubletten bleiben mit ihren
Originalquellen gespeichert.

Die wesentlichen Lücken waren:

1. Ein Depot konnte nur ein `cash_account_key` besitzen.
2. Es gab keinen allgemeinen, persistenten n:m-Abgleich zwischen Depotbeleg und
   Geldbuchung. Die spezialisierten Tabellen `fee_links` und `transfer_pairs`
   deckten diesen Fall nicht ab.
3. Die Buchungsliste eines Depots las nur Buchungen mit dem Depotnamen und
   verlor dadurch wirtschaftlich zugehörige Vorgänge auf Giro- oder
   Verrechnungskonten aus der Ansicht.
4. Für zwei verknüpfte Belege desselben Kaufs fehlte eine allgemeine Sperre
   gegen doppelte Performance-Cashflows.

## Neues Zuordnungskonzept

Das bestehende `cash_account_key` bleibt unverändert das Standardkonto.
Zusätzliche zulässige Zahlungskonten stehen rückwärtskompatibel als
`cash_account_keys` in den vorhandenen Kontodetails. Es gibt keine Änderung an
historischen Transaktionspayloads.

Die additive Tabelle `transaction_reconciliations` verbindet stabile
Buchungsreferenzen. Mehrere Zeilen je Depotbeleg erlauben Teilausführungen und
mehrere Geldbuchungen. Gespeichert werden zugeordneter Betrag, Währung, Status
(`matched` oder `manual`) und Begründung. Originalbuchungen werden nicht
verändert und fiktive Geldbuchungen werden nicht erzeugt.

Automatisch wird nur bei genau einem Kandidaten abgeglichen. Kriterien sind:

- zugelassenes Zahlungskonto des Depots;
- identischer absoluter Betrag und identische Währung;
- Buchungs-/Valuta- beziehungsweise Zahltermin höchstens drei Tage auseinander;
- vorhandene gemeinsame Order-, Ausführungs-, Transaktions- oder Bankreferenz
  hat Vorrang.
- die wirtschaftliche Richtung muss stimmen: Kauf, Steuer und Gebühr sind
  Belastungen; Verkauf und Dividende sind Gutschriften;
- ein Geldbeleg darf innerhalb eines Laufs und über bereits gespeicherte
  Zuordnungen hinweg nur bis zu seinem verfügbaren Betrag verwendet werden.

Kein Kandidat ergibt **Offen**, mehrere Kandidaten ergeben **Konflikt**. Eine
Auswahl in der GUI wird als **Manuell bestätigt** gespeichert. Bereits direkte,
geldwirksame Depotbuchungen auf einem erlaubten Konto gelten als
**Abgeglichen**.

Manuelle Zuordnungen dürfen begründete Teilbeträge enthalten. Die Summe aller
aktiven Zuordnungen wird dabei sowohl gegen den Depotbeleg als auch gegen den
Geldbeleg geprüft; eine Überzuordnung wird abgewiesen. Auch bei einer manuellen
Bestätigung muss die wirtschaftliche Zahlungsrichtung übereinstimmen.

## Datenintegrität und Performance

Für TWR/XIRR bleibt die Depotgrenze unverändert: Ein externes Girokonto wird
nicht Teil des Depotvermögens. Bei einem bestätigten Belegpaar verwendet die
Performanceberechnung genau den Depotbeleg und unterdrückt lediglich den
verknüpften Geld-Gegenbeleg. Rohdaten, Kontosaldo und Importhistorie bleiben
erhalten. Ohne bestätigten/eindeutigen Link ändert sich keine Berechnung.

Die bestehende reine Wertpapierrendite bleibt damit kompatibel. Eine direkte
Zahlung vom Girokonto wird als Kauf-Cashflow des Depots modelliert, nicht als
Aufnahme des gesamten Giroguthabens. Gesamtportfolio-interne Überträge werden
weiter über `transfer_pairs` neutralisiert.

## GUI

Der Konteneditor bietet neben dem Standard-Verrechnungskonto mehrere zusätzliche
Zahlungskonten. Ein Doppelklick auf ein Depot öffnet nun eine depotzentrierte
Buchungshistorie auf Basis von `performance_depot_key`, unabhängig vom
tatsächlichen Geldkonto. Suche, Sortierung, Detailbearbeitung, Quellenhinweise,
Abgleichstatus und eine manuelle Auswahl bei Konflikten verwenden die vorhandene
performante Tabellenansicht.

## Grenzen

- Die automatische Summensuche für beliebige Kombinationen mehrerer
  Teilzahlungen ist bewusst noch nicht aktiv; solche Fälle bleiben offen und
  werden manuell bestätigt. Dadurch entstehen keine falsch positiven Matches.
- Der bestehende CSV-Export ist für diese Ansicht noch nicht als eigener Button
  verdrahtet; Tabellenzeilen können weiterhin per Strg+C exportiert werden.
- Depotliquidität wird nur dann in einer Depotrendite eingeschlossen, wenn das
  Konto fachlich als abgegrenztes Verrechnungskonto behandelt wird. Ein bloß als
  Zahlungsquelle zugelassenes Girokonto bleibt außerhalb.

## Tests

Neue Regressionen prüfen mehrere Zahlungskonten, direkten Girokauf, eindeutigen
und mehrdeutigen Abgleich, Persistenz manueller Zuordnung bei Wiederholungsimport
und die einmalige Performancewirkung. Die vorhandene Settlement-Suite deckt
Dividenden, Steuern, Gebühren, Transfers, Stornos, Cashflow-Neutralität und
Renditegrenzen ab.

Abschlussprüfung am 17. Oktober 2026:

- gezielte Abgleichsregressionen: **23 bestanden**;
- vollständige Testsuite: **950 bestanden, 9 übersprungen**;
- Ruff-Prüfung für `src` und `tests`: **ohne Befund**;
- Depotbestände und Kontosalden blieben vor/nach dem Abgleich identisch;
  TWR und XIRR blieben ebenfalls identisch, und der verknüpfte Geldgegenbeleg
  erschien nicht als zweiter Performance-Zahlungsstrom.
