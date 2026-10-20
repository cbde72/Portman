# Automatische Gebührenanalyse

Portman übernimmt ausschließlich Gebühren, die aus einem Importbeleg hervorgehen oder sich bei
vollständig bekannten Abrechnungswerten centgenau ergeben. Es werden keine Gebühren geschätzt.

## Nachweiszustände

- **nachgewiesen**: Betrag und Gebührenart stammen aus dem Beleg oder aus der abgestimmten Differenz.
- **nachgewiesen 0,00 €**: Kurswert und Abrechnungsbetrag belegen ausdrücklich, dass keine Gebühr anfiel.
- **unbekannt**: Der Beleg enthält nicht genug Angaben. Unbekannt wird niemals als null summiert.
- **widersprüchlich**: Kurswert, Gebühren, Steuern und Abrechnungsbetrag sind nicht centgenau vereinbar.

Für Käufe gilt `Kurswert + Gebühren + Steuern = Abrechnungsbetrag`, für Verkäufe
`Kurswert - Gebühren - Steuern = Abrechnungsbetrag`. Der Kontoabgleich verwendet die bestehende
Zuordnung anhand von Referenz, Betrag, Datum, Zahlungsrichtung und den zum Depot gehörenden Konten.

PDF-/CSV-Überschneidungen werden über die konsolidierte Buchungssicht und stabile Auftrags- oder
Dokumentreferenzen dedupliziert. Eine separat gebuchte Gebühr, die mit dem Gebührennebenfeld einer
Transaktion verknüpft ist, wird nicht als zweiter Transaktionskostenbetrag ausgewertet.

## Oberfläche und Export

Unter **Historie → Gebührenauswertung** stehen Bank, Depot, Wertpapiername, ISIN, WKN,
Gebührenart, Jahr, Nachweis-, Plausibilitäts- und Kontoabgleichstatus zur Verfügung. CSV wird als
UTF-8 mit Semikolon-Trennung exportiert; Excel als `.xlsx` mit Filterzeile.

Unter **Wertpapierdaten → Kauftranchen / Buchungen** werden Kurswert, Gebühren, Steuern und
Abrechnungsbetrag separat angezeigt. Die importierten Originalbelege und Rohbuchungen bleiben
unverändert.

Gebühren sind bereits Bestandteil der Nettozahlung einer Transaktion. Anschaffungskosten,
realisierte Ergebnisse und Performance verwenden daher weiterhin die Nettozahlung; das
Gebührennebenfeld dient der Erklärung und Auswertung und wird nicht nochmals addiert.
