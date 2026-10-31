# STANDARD-Werteansicht

## Umsetzung

Die neue Schaltfläche **„Alle gefundenen Werte“** befindet sich in der
Parser-Feldanalyse und bleibt im Schnellmodus sowie im Expertenmodus sichtbar.
Sie öffnet eine separate, nicht verändernde Tabelle mit dem Titel
`Alle gefundenen Werte – STANDARD`.

Die Datenquelle ist ausschließlich `report["result"]`. Das ist der
unveränderte Basis-/STANDARD-Parseroutput. Es werden nicht verwendet:

- `rule_decisions` oder EXTENDED-Overlays,
- COMPARE-Werte,
- Feldkatalog-Zeilen ohne Parserwert,
- Annotationen, Referenzwerte oder Golden-Daten,
- Regelkandidaten und Trainingszustände.

Ein EXTENDED- oder COMPARE-Bericht kann deshalb sicher geöffnet werden: Die
Ansicht verwendet weiterhin nur den darin enthaltenen Basiswert
`report["result"]`.

## Tabellenmodell

Die kompakte Hauptansicht zeigt ausschließlich:

1. `Variable` – den tatsächlichen technischen Feldpfad,
2. `Wert` – den tatsächlich ausgegebenen Parserwert,
3. `Beschreibung` – die fachliche Bedeutung der Variable.

Über `Details anzeigen` werden zusätzlich Feldname, Einheit/Währung, Datentyp,
Parser-ID, Regel-ID, PDF-Seite, Evidence und Status eingeblendet.

Verschachtelte Dictionaries, Listen und wiederholte Vorgänge werden mit den
vorhandenen DTO-Pfaden vollständig flach dargestellt, etwa
`events[0].cash_movements[0].amount`. Der vorhandene `flatten_result`-Adapter
wird wiederverwendet; es entstehen keine parallelen Parserfelder.

Als tatsächlicher Wert gelten befüllte STANDARD-Blätter. `None`,
`MissingValue`, `NOT_APPLICABLE`, leere Strings und leere Container werden
ausgelassen. `0`, `0.00` und `False` bleiben gültige Werte. Ein befüllter Wert
ohne Evidence bleibt sichtbar und erhält den Status `Evidence fehlt / Prüfen`.

Beschreibungen kommen aus dem versionierten Feldkatalog. Ohne Katalogeintrag
werden der technische Feldname und `Beschreibung noch nicht hinterlegt`
angezeigt; es werden keine fachlichen Beschreibungen erfunden.

Für die Beschreibungssuche werden Listenindizes und ausschließlich der bekannte
`FieldValue`-Wrapper `.value` normalisiert. Beispielsweise werden
`accounts[0].bank_name.value` und `accounts[1].bank_name.value` beide über
`accounts[].bank_name` auf die Katalogbeschreibung „Name der Bank, bei der das
Konto geführt wird“ aufgelöst. Der tatsächlich angezeigte Variablenpfad bleibt
vollständig und unverändert. Gleichnamige Felder aus unterschiedlichen
DTO-Kontexten werden nicht über den bloßen Endnamen zusammengeführt.

## Bedienung

- Suche nach Feld, Wert und Beschreibung.
- Sortierbare Spalten.
- Kompakt-/Detailumschaltung.
- Strg+A und Strg+C sowie Kontextmenü zum Kopieren.
- Anzahl der sichtbaren und gesamten Werte.
- JSON- und CSV-Export.
- Klick auf einen Wert navigiert zur vorhandenen PDF-Evidence und zur
  korrespondierenden Feldanalysezeile. Ohne belastbare Evidence wird keine
  Position erzeugt.

Die direkte PDF-Auswahl, Zoom- und Pan-Bedienung bleiben unverändert.

Wenn kein Bericht mit STANDARD-Ergebnis ausgewählt ist, fragt die GUI, ob ein
STANDARD-Lauf gestartet werden soll. Die Aktion startet weder Training noch
Profilaktivierung.

## Betroffene Dateien

- `ui/standard_values.py`: Datenadapter, Tabelle, Dialog, Suche und Export.
- `ui/field_analysis.py`: sichtbarer STANDARD-Werte-Button und Signal.
- `ui/main_window.py`: Dialogöffnung und Navigation zur PDF/Feldanalyse.
- `tests/unit/test_standard_values.py`: Wertefilter, Null/False, Evidence,
  Suche und Detailmodus.

## Tests

```text
portman-pdf-lab: 111 passed
portman-parsers: 123 passed
```

Die bestehende Parserlogik und wirtschaftliche Berechnung wurden nicht
verändert. Portman V09/V10 wurden nicht geändert. Es wurden keine Commits,
Pushes oder Merges ausgeführt.
