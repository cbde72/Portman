# Importer-Architektur Portman V09

Stand: Phase B, 17.10.2026. Portman-Basiscommit:
`7412d28e6e4bc56eb1ef31fa039c6599dd4feae5`. Fachliche Referenz: Portfolio
Performance `805c20dff5d999e987675181b4f1d82f81df10c0`. Es wurde kein fremder
Quellcode übernommen.

## Pipeline

1. `ImportWorker` liest Dateien außerhalb des GUI-Threads. PDF-Plugins werden
   einmal je Auftrag entdeckt.
2. Quellparser erzeugen `ImportBatch` mit unveränderten Dokumenten,
   Transaktionen, Beständen, Salden und strukturierten Warnungen/Fehlern.
3. Die Vorschau löst Kontenzuordnung, Dubletten und fachliche Konflikte, ohne
   die produktive Datenbank zu verändern.
4. `RepositoryV09.commit_batches()` schreibt einen bestätigten Import atomar.
   Datei- und Datensatzidentitäten sichern Wiederholbarkeit und Idempotenz.
5. Depot-/Geldbuchungen bleiben als Originaldatensätze erhalten.
   `transaction_reconciliations` beschreibt ausschließlich ihre wirtschaftliche
   Überlappung.
6. Auswertungen erzeugen eine abgeleitete Sicht. Zugeordnete Anteile werden nur
   dort neutralisiert; Originalbetrag und Kontosaldo bleiben unverändert.

## Fachlicher Importvertrag

Importer sollen die folgenden Felder liefern oder ausdrücklich leer lassen:

- Bank, Quellformat, Dokumenttyp und Layoutversion
- Depot- und Zahlungskonto
- Handels-, Buchungs- und Valutadatum
- Name, ISIN/WKN, Stückzahl und Kurs
- Brutto, Gebühren, einzelne Steuern und Netto
- Währung, Wechselkurs und Umrechnungsrichtung
- Order-, Ausführungs- und Dokumentreferenz
- Quelle, Dokumenthash, Qualitäts-/Vollständigkeitsstatus und Abgleichstatus

Nicht anwendbare Felder werden nicht erfunden. Automatische endgültige
Verbuchung ist nur bei vorhandenen Pflichtfeldern und erfüllten Invarianten
zulässig. Abweichungen sind als harter Fehler, prüfpflichtige Warnung oder
Hinweis zu klassifizieren.

## Bestandsvertrag

Ein Snapshot ist `complete=True` nur, wenn eine bankspezifische Vollständigkeits-
prüfung erfolgreich war oder die Vollständigkeit im Import ausdrücklich
bestätigt wurde. Geeignete Nachweise sind insbesondere abgestimmter Depotwert,
ausgewiesene Positionszahl, Seiten-/Zwischensummen und eindeutiger Stichtag.
Generische Tabellen sind ohne Nachweis standardmäßig Teilbestände. Teilbestände
dürfen den letzten vollständigen Bestand nicht ersetzen.

## Settlementvertrag

Eine Verknüpfung speichert positiven `allocated_amount`, gleiche Währung,
fachlich passende Zahlungsrichtung und zwei aktive Originalreferenzen. Die
Summen aller Verknüpfungen dürfen weder Depot- noch Geldbetrag überschreiten.
Maschinenlesbare Zustände sind `open`, `partial`, `complete` und `conflict`;
die Oberfläche zeigt Offen, Teilweise zugeordnet, Vollständig abgeglichen oder
Konflikt.

Für Renditen wird nur die belegte Überlappung neutralisiert. Bei einer
Teilzuordnung bleibt der Restbetrag als abgeleitete Sicht der ursprünglichen
Geldbuchung wirksam. Es wird keine zusätzliche gespeicherte Buchung angelegt.
Ein Link über eine Auswertungsgrenze neutralisiert nichts, solange nicht beide
Originale im betrachteten Zeitraum enthalten sind.

## Phase-B-Normalisierung

Verifizierte comdirect- und ING-Wertpapierabrechnungen werden als Depotereignis
`BUY` oder `SELL` gespeichert; das ausgewiesene IBAN-Konto bleibt als
`cash_account` erhalten. Der PDF-Beleg erzeugt keine zweite Geldbewegung.
Eine separat importierte Kontobuchung kann über den Settlementvertrag als
Beleg desselben wirtschaftlichen Vorgangs zugeordnet werden.

Vorabpauschalen trennen die steuerliche Bemessungsgrundlage (`TaxEvent`) von
einer tatsächlich ausgewiesenen Kontobelastung (`TAX`). Steuererstattungen sind
positive `TAX_REFUND`-Cashflows. Auch für diese Typen gelten Komponentenabgleich,
Richtung, Währung und eindeutige Depotzuordnung.
