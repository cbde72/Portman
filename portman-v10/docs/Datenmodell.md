# Logisches Datenmodell 0.1

Noch keine freigegebene produktive Migration. Zuerst Referenzfälle und Zahlenprototyp abnehmen.

| Entität | Schlüssel/Beziehungen und Inhalt |
|---|---|
| Konto | stabile ID; Geld-/Bestandskonto, Unterart, Institut, Währung bei Geldkonto, Referenzkonto optional, aktiv, Revision |
| Kontokennung | Konto-ID, Typ, Kontext, Kennung; kein globales UNIQUE auf Nummern |
| Instrument | stabile ID, Name, Anlageart; ISIN/WKN soweit vorhanden |
| Instrumentkennung | Instrument-ID, Anbieter/Börse/Netzwerk und Kennung |
| Vorgang | ID, Typ, Datum, Originaltext, Revision, Vollständigkeit, Korrektur-/Stornobezug |
| Position | Vorgang-ID und Konto-ID; entweder Geld/Währung oder Menge/Instrument; Wirksamkeitsdatum |
| Betragskomponente | Positions-/Vorgangsbezug, Art, Betrag/Währung; erklärt Geldfluss, keine zweite Saldenwirkung |
| Dokument | ID, eindeutiger SHA-256, Originalname, relative Ablage |
| Vorgangsbeleg | n:m Vorgang–Dokument; Seite/Eintrag, Quellenrolle |
| Import | ID, Zeitpunkt, Status; n:m Dokumentverarbeitung mit Parser-/Schemaversion |
| Importbeitrag | Import-ID, Ziel/Feld, typisierte Erstellung/Ergänzung/Verknüpfung, Quellenunterstützung, nötiger Vorher-Wert |
| Operation | request_id, Eingabehash, Abschlussbericht; transaktionaler Wiederholungsschutz |
| Bestandsindex | Konto/Währung oder Konto/Instrument, Änderungstag, kumulierter Wert, gemeinsame Revision |
| Steuerbezug | Bank-/Inhaberbezug; n:m Konten, keine Gruppierung allein anhand Bankname |
| Freistellungsauftrag | Steuerbezug, Steuerjahr, Gültigkeit, Betrag, Revision; historische Änderungen erhalten |
| Verbrauchsbeleg | Einzeländerung oder kumulierter Stand, Stichtag, Steuerjahr, Betrag/Bedeutung, Importherkunft |
| Festgeld | Konto-ID, Beginn, Fälligkeit, vereinbarter Zinssatz |

CHECK: Geld-/Mengenfelder schließen sich gegenseitig aus. Fremdschlüssel aktiv. Keine Dokument-Löschkaskade auf gemeinsam belegte Vorgänge. Konten mit Historie deaktivieren. Keine JSON-Parserdumps oder Volltextarchive im Kern.

## Vier Referenzfälle

1. Kauf: Depot +2 Stück, Geldkonto −201 EUR; 200 EUR Handelswert und 1 EUR Gebühr erklären denselben Abgang.
2. Ausschüttung: Geld +8 EUR, brutto 10 und Steuer 2 als Bestandteile. Jahresbescheinigung bucht nicht erneut.
3. Geldtransfer: Quelle −100 EUR, Ziel +100 EUR, ein Vorgang; bei gesonderter Gebühr Quelle zusätzlich −1 EUR. Keine externe Performanceeinzahlung.
4. Depotübertrag: Quelle −2 Stück, Ziel +2 Stück; Anschaffungstranchen/-daten bleiben erhalten. Fehlende Kosten bleiben unbekannt. Ein Transferbeleg mit nur einer Seite bleibt unvollständig.

Jeder Fall bekommt mehrere Quellen und vollständige Rücknahme. Bleibt ein unterstützender Beleg, darf sein gemeinsamer Vorgang nicht verschwinden. Manuelle spätere Änderungen erhalten eigene Herkunft und werden nicht von alten Vorher-Werten überschrieben.

## Bestandsindex

Nur Änderungstage speichern, kumulierte exakte Werte. Rückdatierte Änderung aktualisiert betroffene Reihen ab frühestem geändertem Datum. Persistenz im selben Commit wie Buchungen; Speicherstand mit identischer Revision veröffentlichen. Stichtag per binärer Suche. Rekonstruierbar, kein eigener fachlicher Bestand. Kaltstart lädt Index; keine Summierung aller Buchungen pro Klick. Ziel: p95 unter 50 ms lokal warm; Messung mit 100.000 Positionen. Fernzugriff benötigt kleinen Nachbarcache und gebündelte Aufrufe.

## Freistellung

Auftrag manuell; Verbrauch importiert. Kumulierte Stände und enthaltene Einzelverbräuche nicht addieren. Korrekturen können Verbrauch senken. Fehlend ist unbekannt. Rücknahme entfernt nur Importbeiträge. Quellenstichtag sichtbar. Keine Steuerrechtsberechnung und keine zusätzliche Geldbuchung für reinen Freistellungsverbrauch.

## Offene Freigabepunkte

Zahlenentscheidung für V10-05: Geld und Mengen werden als kanonische endliche Dezimalstrings ohne Exponent gespeichert; keine Float-/REAL-Spalten und keine auf eine feste Skala begrenzten SQLite-INTEGER. Schreibpfade müssen überflüssige Nachkommastellen normalisieren. Bereichssuche und Sortierung verwenden die registrierte SQLite-Collation `PORTMAN_DECIMAL` auf einer indizierten TEXT-Spalte. Jede Verbindung muss die Collation vor Abfragen registrieren; ihre Vergleichsregeln sind damit Teil des Speichervertrags. Summen werden über ganzzahlige Koeffizienten und gemeinsame Skala gebildet, nicht mit dem kontextbegrenzten Standard-Decimal-Addieren. Fehlende Werte bleiben separat von `0`.

Prototypnachweis (Python 3.14.3, SQLite 3.50.4, In-Memory-Datenbank, 100.000 Integerbeträge): indexierte Bereichsabfrage `>=` Median aus 7 Läufen 0,563 ms; der Index wurde laut `EXPLAIN QUERY PLAN` verwendet. Ein SQLite-INTEGER-Wert von `10**30` löst `OverflowError` aus. Vertragstests prüfen außerdem Werte jenseits 64 Bit, 18 Nachkommastellen, exakte Summen ohne Decimal-Kontext und numerische SQLite-Sortierung/Suche. Das ist ein Formatprototyp, keine produktive Migration; keine Rundung wird vorgenommen. Benchmarkwerte sind kein p95-Zielnachweis für Stichtagsblättern.

Anschaffungstranchen: Kostenverfahren festlegen; bei nicht aus Buchungen rekonstruierbaren Ursprungsdaten zusätzliche Lot-Tabelle. Vollständiger Parservertrag und echte Dokumenttypen vor Implementierung verifizieren.
