# Depot, Verrechnungskonto und Dividenden

Unter **Kontodetails → Allgemein** den Kontotyp **Depot** einstellen und das
**Verrechnungskonto** auswählen. Als Ziel sind aktive Giro- und Verrechnungskonten
zulässig. Mehrere Depots können dasselbe Konto verwenden. Die Zuordnung nutzt den
dauerhaften Kontoschlüssel und bleibt beim Umbenennen erhalten.

Beim PDF-Import bleibt das **Zielkonto** die Stelle der Geldgutschrift. Im Reiter
**PDF-Buchungen** lässt sich zusätzlich das **Depot für Dividenden-Performance**
auswählen. Die automatische Auswahl verwendet die Kontoverknüpfung; bei gemeinsamem
Verrechnungskonto kann ein belegter Wertpapierbestand die Auswahl eingrenzen.
Mehrdeutige Zuordnungen verlangen eine Auswahl. Die bestätigte Depotzuordnung wird
mit der Buchung gespeichert. Bestehende Dividenden ohne gespeicherte Zuordnung
verwenden die aktuelle Kontoverknüpfung.

Die bestehende Performance-Ansicht bewertet **Wertpapiere ohne Kontoguthaben**.
Nettodividenden fließen als Ertrag ein, unabhängig davon, ob die Abrechnung selbst
den Kontostand beeinflusst. Bereits im Nettobetrag enthaltene Steuern und Gebühren
werden nicht erneut abgezogen. Bruttodividenden werden als Summe nur angezeigt,
wenn sie vollständig in EUR belegt sind; fehlende Beträge gelten nicht als null.
Die Buchungsübersicht zeigt zusätzlich Bruttoertrag in Originalwährung, belegte
Gesamtsteuern und separat belegte Quellensteuer.
comdirect-Gutschriften vor separat abgerechneten Steuern werden ausdrücklich als
solche gekennzeichnet; sie werden nicht als vollständig belegter Nettoertrag bezeichnet.

Dividendenabrechnung und Kontoauszug werden bei eindeutig übereinstimmendem Konto,
Betrag, Währung, Zahlungsdatum und Referenz bzw. ISIN mit Ertragsbezeichnung als
derselbe Vorgang gelesen. Die Originale bleiben erhalten und die Verknüpfung wird
bei Import-Rücknahme neu ermittelt. Betrag und Datum allein reichen nicht.
Mehrdeutige Beleggruppen müssen geprüft werden; eine automatische Zusammenführung
findet dann nicht statt. Manuell klassifizierte Gegenbuchungen werden geschützt.

Die ING-Dividendengutschrift verwendet `DIVIDEND`; ältere `dividende`-Buchungen
werden beim Lesen ebenfalls erkannt. Nicht vollständig erkannte Steuern auf
weiteren Belegseiten werden nicht als vollständige Steuerbeträge ausgegeben.

Regressionstests (PowerShell):

```powershell
$env:PYTHONPATH='src'
.venv/Scripts/python.exe -m unittest discover -s tests -v
```
