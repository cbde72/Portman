# Portman V09 – Wertpapierüberträge und Kapitalmaßnahmen in der GUI

## Implementierte Funktionen

### Wertpapierüberträge

- Zentrale Registerkarte **Wertpapierüberträge** im bestehenden Dialog „Umbuchungen, Kapitalmaßnahmen und Währungskurse“.
- Automatische Kandidatenbildung aus noch nicht zugeordneten `TRANSFER_OUT`-/`TRANSFER_IN`-Buchungen anhand von Wertpapierkennung, Stückzahl, unterschiedlichen Depots und höchstens sieben Tagen Abstand.
- Kennzeichnung eindeutiger und prüfbedürftiger Vorschläge; Anzeige von Datum, Quell-/Zieldepot, Kennung, Stückzahl und den bis dahin belegten Kauflosen.
- Manuelle Auswahl jeder Aus- und Einlieferungsseite für unvollständige oder mehrdeutige Fälle.
- Bestätigung nur mit Belegquelle/Begründung. Sie erzeugt ausschließlich eine lot-erhaltende Transfermaßnahme, keinen Kauf, Verkauf oder Cashflow.
- Bestätigte Zuordnungen erscheinen in der zentralen Verwaltung und können mit protokollierter Begründung widerrufen und anschließend neu zugeordnet werden.
- Originalbelege lassen sich in Kandidaten- und Verwaltungsansicht per Doppelklick öffnen, sofern der gespeicherte Pfad vorhanden ist.

### Kapitalmaßnahmen

- Zentrale Erfassung und Bearbeitung für `SPLIT`, `MERGER`, `TRANSFER`, `SPINOFF`, `RIGHTS` und `CAPITAL_REPAYMENT`.
- Die Verwaltung zeigt Datum, Depot, Wertpapier, Art, Verhältnis, betroffene Stückzahl, Kostenanteil/Kostenminderung und Belegquelle.
- Spin-offs und Bezugsrechte verlangen einen ausdrücklich eingegebenen belegten Ziel-Kostenanteil zwischen 0 und 1. Auch ein Anteil von 0 ist nur als bewusste Belegeingabe möglich.
- Kapitalrückzahlungen verlangen positiven belegten Kostenminderungsbetrag und ISO-Währung.
- Spin-off/Bezugsrecht erzeugen neue Stücke und teilen die vorhandenen FIFO-Lose proportional nach der bestätigten Kostenquote; Kaufdatum und Gesamtkosten bleiben erhalten.
- Kapitalrückzahlungen mindern die vorhandenen Loskosten. Übersteigt die Rückzahlung die belegte Basis oder ist die Basis unbekannt, bleibt der Einstand unbekannt statt negativ oder geschätzt zu werden.
- Korrekturen erzeugen eine neue aktive Maßnahme und nehmen die alte transaktional zurück. Widerrufe bleiben über `change_log` beziehungsweise die vorhandenen Audit-Trigger nachvollziehbar.

## Wirtschaftliche Regressionen

| Kette | Ergebnis |
|---|---|
| Kauf 2 Stück für 200 EUR → bestätigter Depotübertrag → Verkauf für 260 EUR | Einstand 200 EUR, realisiert 60 EUR, Transfer-Cashflow 0 EUR |
| Kauf OLD 10 Stück für 100 EUR → Spin-off NEW 1:0,5 mit belegten 20 % Kosten → Verkauf NEW | NEW-Einstand 20 EUR, realisiert 10 EUR |
| Danach Kapitalrückzahlung OLD 20 EUR → Verkauf OLD für 100 EUR | OLD-Einstand 60 EUR, realisiert 40 EUR |
| Teilübertrag über mehrere FIFO-Lose | Bestehende P1-Regression bleibt unverändert grün; ursprüngliche Losdaten und anteilige Einstände werden fortgeführt. |

## Tests und Sicherheit

- Neue GUI-/Fachtests: Erkennen, Bestätigen und Widerrufen von Wertpapierüberträgen; Erstellen und Korrigieren eines Spin-offs; belegte Kostenaufteilung; Kapitalrückzahlung.
- Relevante kombinierte Suite: **135 bestanden**.
- Vollständige Pytest-Suite: **1277 bestanden, 19 übersprungen, 5 Subtests bestanden**; zwei bereits vorhandene Qt-Deprecation-Warnungen, Laufzeit 460,28 s.
- Tests verwenden ausschließlich temporäre SQLite-Datenbanken. Produktive Datenbank und Original-PDFs wurden nicht verändert.
- Produktive SQLite abschließend ausschließlich per URI `mode=ro` geprüft: `PRAGMA integrity_check = ok`, keine Foreign-Key-Verstöße.

## Offene Einschränkungen

- Die Kandidatensuche paart nicht automatisch unterschiedliche Kennungen bei einem Wertpapierumtausch; dieser Vorgang wird bewusst als `MERGER` mit Zielkennung erfasst.
- Eine Kapitalrückzahlung oberhalb der vorhandenen Kostenbasis kann einen gesondert steuerpflichtigen Ertrag darstellen. Ohne entsprechenden Beleg wird dieser nicht automatisch erzeugt; die Kostenbasis bleibt unbekannt.
- Belegdateien können nur geöffnet werden, wenn der importierte lokale Pfad noch existiert.
