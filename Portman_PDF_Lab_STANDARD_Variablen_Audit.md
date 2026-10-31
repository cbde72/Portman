# Audit der STANDARD-Parservariablen

Die Laufzeitfunktion `audit_standard_descriptions(report, catalog)` in
`ui/standard_values.py` erzeugt für jeden tatsächlich ausgegebenen
STANDARD-Wert einen Auditdatensatz:

```text
variable | description | source
```

`source` ist einer von:

- `field_catalog`: exakter versionierter Katalogpfad,
- `field_catalog_normalized`: Katalogtreffer nach Entfernung von
  Listenindizes und des bekannten `.value`-Wrappers,
- `unknown`: keine sichere fachliche Beschreibung hinterlegt.

Die Variablenpfade bleiben im Audit und in der GUI vollständig erhalten. Die
Beschreibungssuche verwendet zentral `normalize_field_path()` aus
`field_catalog.py`; dadurch verwenden Feldanalyse, F1-Hilfe, Training und die
STANDARD-Werteansicht dieselbe Katalogquelle.

Beispiel:

```text
accounts[0].bank_name.value | Name der Bank, bei der das Konto geführt wird | field_catalog_normalized
accounts[1].bank_name.value | Name der Bank, bei der das Konto geführt wird | field_catalog_normalized
events[0].trades[0].isin    | Internationale Wertpapierkennung | field_catalog
events[0].trades[0].wkn     | Deutsche Wertpapierkennnummer | field_catalog
attributes.user_fields.trade.venue | Optionaler Ausführungs- oder Handelsplatz | field_catalog
```

Unbekannte oder mehrdeutige Felder werden nicht semantisch geraten, sondern
als `Beschreibung noch nicht hinterlegt` ausgewiesen.
