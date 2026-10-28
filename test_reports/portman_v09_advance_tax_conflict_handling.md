# Portman V09 – Vorabpauschalen-Konflikte

Datum: 28.10.2026
Branch: `main`
Ausgangscommit: `1016e13125a983628ee825c47aa798b41302f539`

## Technische Ursache

Die bestehende Buchungskonfliktprüfung in `ImportSession.conflicts()` betrachtete ausschließlich Transaktionen. Die fachliche Eindeutigkeitsprüfung für Vorabpauschalen wurde erst in `Store._deduplicate_tax_events()` ausgeführt. Deshalb erschien der Konflikt erst während `ImportSession.simulate()` innerhalb von `repo.commit_batches()`. Der Wizard hatte zu diesem Zeitpunkt bereits mit der Berechnung der Importwirkung begonnen.

Die Schutzregel in `storage.py` wurde weder entfernt noch abgeschwächt. Sie bleibt die letzte Integritätsbarriere für direkte und nicht interaktive Importe.

## Neuer Ablauf

`ImportSession.advance_tax_conflicts()` ermittelt vor der Simulation alle vorhandenen Vorabpauschalen anhand von:

- effektivem Zieldepot nach Kontozuordnung,
- ISIN beziehungsweise Wertpapieridentität,
- Ertragsjahr,
- Steuerereignistyp `vorabpauschale` oder `vorabpauschale_ausland`.

Vorhandene und neue Steuerwerte werden vollständig verglichen. Änderliche Beleg- und Verknüpfungsidentitäten werden getrennt von den wirtschaftlichen Steuerwerten behandelt. Der Dialog zeigt vorhandenen und neuen Beleg sowie alle wesentlichen Steuerfelder und hebt Abweichungen hervor.

Zusätzlich wurde die Kontozuordnungsaktion eindeutig benannt: **„Vorhandenes Zielkonto nicht zuordnen · gesamte Datei überspringen“**. Sie verwendet weiterhin den ausdrücklich reservierten Wert `__skip__`. Der Dateiindex wird vor dem Erzeugen der Importkopie ausgeschlossen; damit gelangen weder Buchungen noch Dokumente, Steuerereignisse oder sonstige Datensätze dieser PDF in die Importsitzung. Eine lediglich offene Pflichtzuordnung bleibt davon getrennt und weiterhin blockierend.

## Entscheidungen

### Ignorieren

Die vorhandene Vorabpauschale bleibt bestehen. Nur das neue kollidierende Steuerereignis wird aus der vorbereiteten Importkopie entfernt. Unmittelbar daran gebundene neue Steuerdetails werden ebenfalls entfernt, damit keine verwaisten Verknüpfungen entstehen. Andere Buchungen, Dokumente und Dateien des Imports bleiben erhalten.

Die Entscheidung wird unter dem stabilen Konfliktschlüssel in der laufenden Importsitzung gehalten und bei einer intern erneut erforderlichen Simulation wiederverwendet. Im Importbericht bleibt ein Hinweis auf das bewusst ignorierte Steuerereignis erhalten.

### Abbrechen

Der Abbruch erfolgt, bevor `simulate()` oder eine Datenbanktransaktion gestartet wird. Daher sind keine Datenbankänderungen und kein Rollback von Teilergebnissen erforderlich. Kontozuordnungen und bereits gespeicherte Entscheidungen bleiben im geöffneten Wizard erhalten. Ein erneuter Klick beginnt keine bereits ausgeführte Importwirkung von vorne.

## Alt-/Neu-Vergleich

| Verhalten | Vorher | Nachher |
| --- | --- | --- |
| Konflikterkennung | während `commit_batches()` | vor `simulate()` |
| Benutzerentscheidung | generische Fehlermeldung | fachlicher Vergleichsdialog |
| Ignorieren | nicht möglich | nur betroffenes Steuerereignis überspringen |
| Übrige Importdaten | Import vollständig blockiert | werden weiterverarbeitet |
| Abbruch | nach Beginn der Wirkungsberechnung | vor jeder Datenbankwirkung |
| Integritätsschutz | Storage-Prüfung | Vorprüfung plus unveränderte Storage-Prüfung |

## Transaktionssicherheit

- Produktive SQLite-Datenbanken wurden nicht geöffnet oder verändert.
- Tests verwenden ausschließlich temporäre synthetische Datenbanken.
- Normale Datenbank-, Validierungs- und Integritätsfehler werden nicht abgefangen oder übersprungen.
- Der eigentliche Commit bleibt atomar in der bestehenden Transaktion.
- Mehrfachimporte werden weiterhin durch Dokument- und Ereignisidentitäten verhindert.

## Tests

Gezielte Regression:

```text
python -m pytest -q tests/test_import_conflict_ui.py tests/test_comdirect_historical_tax_mapping.py --basetemp tmp/pytest_advance_tax_targeted
36 passed
```

Geprüft wurden insbesondere identische und abweichende Vorabpauschalen, Ignorieren, Abbrechen, Entscheidungserhalt, weitere Buchungen derselben Datei, abhängige Steuerdetails und unverändert blockierende normale Fehler.

Erste vollständige Regression nach der Vorabpauschalen-Korrektur:

```text
python -m pytest -q --basetemp tmp/pytest_advance_tax_conflicts
1258 passed, 16 skipped, 2 warnings, 5 subtests passed in 396.44s
```

Gezielte Regression nach Präzisierung der Datei-Überspringen-Aktion:

```text
python -m pytest -q tests/test_pdf_import.py tests/test_import_overview.py tests/test_import_conflict_ui.py tests/test_comdirect_historical_tax_mapping.py --basetemp tmp/pytest_import_skip_and_advance
58 passed, 1 skipped
```

Abschließende vollständige Regression nach beiden Korrekturen:

```text
python -m pytest -q --basetemp tmp/pytest_advance_tax_conflicts_final
1258 passed, 16 skipped, 2 warnings, 5 subtests passed in 356.80s
```

`python -m compileall -q src` und `python -m ruff check src --select F`
waren ebenfalls erfolgreich. Die zwei Warnungen sind die bereits bekannte
Qt-Deprecation-Warnung für `QSortFilterProxyModel.invalidateFilter()` in
`tax_detail_view.py`; sie steht nicht mit diesen Änderungen in Zusammenhang.

## Sicherungsstand

Vor den Änderungen wurden die betroffenen Dateien nach
`C:\Users\chris\Desktop\Portman_AdvanceTax_Backup_20261028`
kopiert. Die Quelldateien wurden vor der Bearbeitung per SHA-256 erfasst.

## Verbleibende Risiken

Historische, unvollständig gespeicherte Steuerereignisse können beim Feldvergleich als abweichend erscheinen. Sie werden nicht automatisch ignoriert, sondern müssen ausdrücklich im Dialog geprüft werden. Direkte Importe außerhalb des V09-Wizards erhalten weiterhin die bestehende harte Storage-Ablehnung.
