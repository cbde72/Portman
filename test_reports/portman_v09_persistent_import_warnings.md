# Portman V09 – Dauerhaft ignorierte Importwarnungen

Datum: 28.10.2026
Branch: `main`
Ausgangscommit des Arbeitsbaums: `1016e13125a983628ee825c47aa798b41302f539`

## Ergebnis

Der bestehende Importhinweisdialog bietet jetzt vier explizite, per Tastatur erreichbare Entscheidungen:

1. **Übernehmen**
2. **Nachfragen**
3. **Ignorieren · aktueller Import**
4. **Alle zukünftigen ignorieren**

Die vierte Auswahl wird dauerhaft in den bestehenden GUI-Einstellungen gespeichert. Beim nächsten Import und nach einem Programmneustart wird nur derselbe stabil identifizierte Warnungstyp unterdrückt. Die Warnung bleibt vollständig im Import- und Auditprotokoll erhalten und beeinflusst weder Buchungen noch Belege.

## Persistenz

Die Regeln werden unter dem Schlüssel `ignored_import_warnings` in der bestehenden Datei `portfolio_settings.json` gespeichert. Es erfolgen keine Schreibzugriffe auf die Portfolio-SQLite-Datenbank.

Schema:

```json
{
  "ignored_import_warnings": {
    "comdirect:CACHE_FRESHNESS": {
      "plugin": "comdirect",
      "code": "CACHE_FRESHNESS",
      "category": "Cache Freshness"
    }
  }
}
```

Der vollständige Meldungstext wird nicht als Schlüssel verwendet. Der technische Schlüssel besteht aus:

- Plugin beziehungsweise Bank;
- stabilem technischen Warnungscode;
- einer rein beschreibenden Kategorie für die Einstellungsanzeige.

## Warnungsidentität

Vorhandene `ValidationIssue.code`-Werte werden übernommen, sofern sie nicht sicherheitsrelevant sind. Da die produktiven Parserwarnungen überwiegend normale Strings sind, wurde für bereits vorhandene eindeutig nichtkritische Meldungsarten eine kleine explizite Registry ergänzt:

| Meldungsart | Technischer Code |
| --- | --- |
| comdirect-Zwischenspeicher | `CACHE_FRESHNESS` |
| separate Steuermitteilung als reiner Importhinweis | `SEPARATE_TAX_NOTICE` |
| gelieferter/angeforderter Historienzeitraum | `HISTORY_RANGE_INFO` |
| Lieferumfang einer Historie | `HISTORY_DELIVERY_INFO` |
| keine neuen Bankumsätze | `NO_NEW_BOOKINGS` |

Unbekannte ungecodete Hinweise können weiterhin übernommen oder nur im aktuellen Import ignoriert werden. Die dauerhafte Schaltfläche ist für sie deaktiviert.

## Sicherheitsmechanismen

Dauerhafte Unterdrückung wird verweigert, wenn:

- kein stabiler Code vorhanden ist;
- die Meldung den Schweregrad `error` trägt;
- der Code auf Datenbank-, Integritäts-, Identitäts-, Konflikt-, Pflichtfeld-, Validierungs- oder Nichtendlichkeitsfehler hinweist.

Insbesondere bleiben unverändert blockierend:

- Datenbankfehler;
- ungültige beziehungsweise nicht-endliche Beträge;
- Steueridentitätskonflikte;
- echte wirtschaftliche Buchungskonflikte;
- fehlende zwingende Kontozuordnungen;
- Integritäts- und Validierungsfehler.

Die Entscheidungspolitik verändert keine `ImportBatch.warnings`. Bei dauerhafter oder sitzungsbezogener Unterdrückung wird nur der GUI-Dialog ausgelassen. Die Warnung wird weiterhin im gespeicherten Importreport protokolliert.

## Verhalten im Import

- **Übernehmen** akzeptiert die aktuelle Meldungsart für den laufenden Import.
- **Nachfragen** legt keine Regel an; der nächste entsprechende Hinweis wird wieder angezeigt.
- **Ignorieren · aktueller Import** unterdrückt weitere Anzeigen desselben Typs nur in diesem Wizard.
- **Alle zukünftigen ignorieren** speichert Plugin und Code sofort über `window.save_settings()`.

Der Importabschluss zeigt die Anzahl unterdrückter Hinweise an. Der Zähler wird ausschließlich als UI-Ergebnisinformation an das erste Ergebnisobjekt angefügt und nicht statt der eigentlichen Warnungen gespeichert.

## Verwaltung

Unter **Einstellungen → Import → Ignorierte Meldungen** steht eine Übersicht mit folgenden Spalten bereit:

- Meldungstyp;
- Plugin / Bank;
- technischer Code.

Verfügbar sind:

- ausgewählte Regel löschen;
- alle Regeln zurücksetzen.

Jede Änderung wird sofort in den GUI-Einstellungen gespeichert. Nach dem Löschen wird der entsprechende Hinweis beim nächsten Auftreten wieder angezeigt.

## Geänderte Dateien dieser Aufgabe

- `src/portman/import_conflict_actions.py`
- `src/portman/import_ui_v09.py`
- `src/portman/import_v09.py`
- `src/portman/gui/appearance.py`
- `src/portman/gui/import_result.py`
- `tests/test_import_conflict_ui.py`
- `tests/test_gui_components.py`
- `test_reports/portman_v09_persistent_import_warnings.md`

`import_conflict_actions.py`, `import_ui_v09.py`, `appearance.py`, `test_import_conflict_ui.py` und `test_gui_components.py` enthielten bereits uncommittete Änderungen aus den unmittelbar vorherigen GUI- und Konfliktaufgaben. Diese wurden erhalten. Der Vergleich gegen den vor dieser Aufgabe gesicherten Stand weist für die sechs gesicherten Dateien 322 Ergänzungen und 18 Entfernungen aus; hinzu kommen die kleine Menüprüfung und dieser Bericht.

## Technischer Sicherungsstand

Die vor dieser Aufgabe betroffenen Arbeitskopien wurden gesichert unter:

`C:\Users\chris\Desktop\Portman_Persistent_Warnings_Backup_20261028`

Das SHA-256-Manifest wurde nach Abschluss verifiziert: **6/6 Dateien stimmen in Größe und Prüfsumme überein**.

## Tests

Gezielte Regression:

```text
36 passed, 3 subtests passed
```

Abgedeckt sind:

- vier Schaltflächen und Tastaturkürzel;
- dauerhafte Speicherung;
- Laden nach Neustart über eine neue `StorageV07`-Instanz;
- Unterdrückung nur bei identischem Plugin und Code;
- weiterhin sichtbare unterschiedliche Warnungen;
- unveränderte Warnungen im gespeicherten Importreport;
- Anzeige der Anzahl unterdrückter Hinweise im Ergebnis;
- Entfernen einer Regel;
- Zurücksetzen aller Regeln;
- deaktivierte und serverseitig abgewiesene Dauerregel für kritische Codes;
- unveränderte Buchungskonflikt-, Undo-, Rollback- und GUI-Thread-Tests;
- Erreichbarkeit des Einstellungsuntermenüs in einer realen `MainWindow`-Instanz.

Statische Prüfungen:

```powershell
python -m compileall -q src
python -m ruff check src --select F
```

Ergebnis: erfolgreich; Ruff meldet `All checks passed!`.

Vollständige Regression:

```powershell
python -m pytest -q --basetemp tmp/pytest_import_warning_persistence
```

Ergebnis:

```text
1252 passed, 16 skipped, 2 warnings, 5 subtests passed in 495.82s
```

Die zwei Warnungen betreffen unverändert `QSortFilterProxyModel.invalidateFilter()` in `src/portman/tax_detail_view.py`. Diese Datei wurde nicht geändert.

## Git-Abgrenzung

Die Änderung ist technisch geprüft. Ein isolierter Commit nur dieser Aufgabe ist auf Dateiebene derzeit nicht möglich, weil mehrere Dateien bereits die noch uncommittete Vorgängerimplementierung der Konfliktbehandlung und des GUI-Redesigns enthalten. Ein automatischer gemischter Commit wurde daher nicht erzeugt.

Es wurde nichts gestaged, committed oder gepusht. Produktive Datenbanken und Original-PDFs wurden nicht geöffnet oder verändert.
