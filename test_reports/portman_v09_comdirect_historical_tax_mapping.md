# Portman V09 – comdirect-Steuermitteilungen ohne Depotnummer

Datum: 28.10.2026
Branch: `main`
Ausgangscommit: `1016e13125a983628ee825c47aa798b41302f539`

## Ergebnis

Historische comdirect-Steuermitteilungen ohne Depotnummer werden jetzt über die im Beleg dokumentierte IBAN des Verrechnungskontos einem Depot vorgeschlagen. Die automatische Auswahl erfolgt ausschließlich, wenn sowohl das Verrechnungskonto als auch genau ein damit über `cash_account_key` verknüpftes Depot eindeutig sind.

Bei mehreren passenden Depots oder fehlender Verknüpfung bleibt die Depotauswahl bewusst offen. Reine Steuerereignisse ohne eigenständige Geldbuchung erzeugen keine zusätzliche Pflichtzeile für das Verrechnungskonto. Die IBAN bleibt unverändert als belegte Information in `TaxEvent.cash_account` erhalten.

## Tatsächliche Ursache

`pdf_plugins/comdirect_ertraege.py::_investment_distribution_tax()` verwendete bei fehlender Depotnummer den fachlich notwendigen Platzhalter `comdirect Depot`. Gleichzeitig wurden jedoch sowohl dieser Platzhalter als auch die erkannte IBAN in `batch.account_names` eingetragen.

`import_sources()` bildet aus `batch.account_names`, Dokumenten und Steuerereignissen eigenständige Quellkonten. Dadurch entstanden in der Vorschau zwei Zeilen:

1. `comdirect Depot` mit Depotpflicht wegen des Steuerereignisses;
2. die IBAN als zusätzliche Quelle vom Typ Kontoname.

Die bestehende `suggest_accounts()`-Logik konnte zwar IBAN und explizite Depotnummern erkennen, leitete aus einem eindeutig erkannten Verrechnungskonto aber noch kein über `cash_account_key` verknüpftes Depot ab.

## Neue Kontoauswahl

Die neue Hilfslogik `tax_depot_from_cash_account()` ist absichtlich eng begrenzt:

- nur für den Platzhalter `comdirect Depot`;
- nur für Quellen mit Steuerereignissen oder Steuerdetails;
- IBAN ausschließlich aus `TaxEvent.cash_account`;
- eindeutige Identifikation des aktiven Verrechnungskontos über die bestehende `pdf_account_match()`-Logik;
- Auswahl nur bei genau einem aktiven Depot mit passendem `cash_account_key`;
- keine automatische Auswahl bei mehreren Depots;
- keine automatische Auswahl bei fehlendem Verrechnungskonto oder fehlender Depotverknüpfung.

Gespeicherte Importregeln haben weiterhin Vorrang. Explizite Depotnummern durchlaufen unverändert die bestehende Depotnummern- und comdirect-Unterkontokennungserkennung.

## Quellenbildung im Parser

Bei Investment-Ausschüttungs-Steuermitteilungen wird nur noch das Depot in `batch.account_names` eingetragen. Die IBAN wird nicht entfernt oder geraten:

- `TaxEvent.cash_account` bleibt befüllt;
- bei tatsächlich ausgewiesenen Steuern bleibt sie auch in der vorhandenen nicht zahlungswirksamen Abstimmungsbuchung erhalten;
- Steuerereignis-ID, Referenznummer, Dokumentidentität und wirtschaftliche Felder bleiben unverändert.

Steuerfreie Ausschüttungen mit `paid_taxes = 0.00` erzeugen weiterhin weder Steuerbuchung noch Geldbuchung.

## Vorher-/Nachher-Vergleich

| Fall | Bisher | Jetzt |
| --- | --- | --- |
| Keine Depotnummer, eindeutiges Verrechnungskonto und ein Depot | Zwei Zuordnungszeilen; Depot manuell | Eine Depotzeile; Depot vorausgewählt |
| Mehrere Depots am selben Verrechnungskonto | Keine Ableitung | Keine automatische Auswahl; Begründung weist auf Mehrdeutigkeit hin |
| Verrechnungskonto fehlt | Keine Ableitung | Manuelle Depotauswahl erforderlich |
| Depotverknüpfung fehlt | Keine Ableitung | Manuelle Depotauswahl erforderlich |
| Explizite Depotnummer | Bestehende Nummernlogik | Unverändert |
| Gespeicherte Importregel | Verwendet | Hat weiterhin Vorrang |
| Steuer 0,00 EUR | Keine Transaktion | Unverändert keine Transaktion |

## Prüfung der drei Originalbelege

Die Original-PDFs wurden ausschließlich lesend mit `parse_pdf(..., allow_ocr=False)` geprüft. Keine Originaldatei wurde verändert oder kopiert.

| WKN | Datum | Parserfehler | Steuerereignisse | Transaktionen | Quellen | IBAN-Beleg | Steuer |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: |
| 593399 | 27.04.2017 | 0 | 1 | 0 | `comdirect Depot` | vorhanden | 0,00 EUR |
| A0D8QZ | 27.04.2017 | 0 | 1 | 0 | `comdirect Depot` | vorhanden | 0,00 EUR |
| A0D8Q4 | 27.04.2017 | 0 | 1 | 0 | `comdirect Depot` | vorhanden | 0,00 EUR |

Für jeden Beleg wurde anschließend mit einer temporären synthetischen SQLite-Datenbank geprüft:

- eindeutiges Depot wird über das Verrechnungskonto vorgeschlagen;
- die Vorschau enthält genau eine Zuordnungszeile;
- Import erzeugt keine Transaktion;
- Reimport wird als `duplicate` erkannt;
- Steuerereigniszahl bleibt eins;
- keine zusätzliche Geldbuchung entsteht.

## Diagnose `ImportSession.apply()` / `repo.commit_batches()`

Der gemeldete Fehler wurde unabhängig von der Kontozuordnung auf einer temporären synthetischen Datenbank reproduziert. `repo.commit_batches()` lieferte tatsächlich:

```text
status: error
errors: Für IE00BKM4GZ66 im Depot <synthetisches Testdepot> ist für das Ertragsjahr 2020 bereits eine Vorabpauschale gespeichert.
```

`ImportSession.apply()` übernimmt dieses `result['errors']` und wirft daraus erwartungsgemäß einen `ValueError`. Ursache ist die fachliche Periodenkollision in `_deduplicate_tax_events()`: Für dasselbe Depot, Wertpapier, Ertragsjahr und denselben Vorabpauschalentyp lagen abweichende Steuerdaten vor.

Die Reproduktion zeigt damit keinen Zusammenhang zur hier korrigierten IBAN-/Depotvorschlagslogik. Die äußere Importtransaktion wurde vollständig zurückgerollt; es blieb genau das ursprüngliche Steuerereignis gespeichert.

## Geänderte Dateien dieser Aufgabe

- `pdf_plugins/comdirect_ertraege.py`
- `src/portfolio_v5/import_accounts.py`
- `tests/test_comdirect_historical_tax_mapping.py`
- `test_reports/portman_v09_comdirect_historical_tax_mapping.md`

Die bestehenden uncommitteten Änderungen an GUI-Redesign und Konfliktbehandlung wurden erhalten und nicht überschrieben.

## Sicherung

Vor den Änderungen wurden die betroffenen vorhandenen Dateien gesichert unter:

`C:\Users\chris\Desktop\Portman_Comdirect_Tax_Mapping_Backup_20261028`

Das SHA-256-Manifest wurde nach Abschluss geprüft: **3/3 Dateien stimmen in Größe und Prüfsumme überein**.

## Tests

Gezielte Regression:

```text
45 passed, 3 subtests passed
```

Abgedeckt sind:

- WKN 593399, A0D8QZ und A0D8Q4 als Realbelege;
- eindeutige Depot-Verrechnungskonto-Verknüpfung;
- mehrere Depots am selben Verrechnungskonto;
- fehlendes Verrechnungskonto;
- fehlende Depotverknüpfung;
- explizite Depotnummer;
- gespeicherte Importregel;
- Vorschau mit genau einer Zuordnungszeile;
- Import und Reimport ohne zusätzliche Geldbuchung;
- kein falsches automatisches Depot;
- reproduzierte Repository-Fehlermeldung und atomarer Rollback.

Statische Prüfungen:

```powershell
python -m compileall -q src pdf_plugins
python -m ruff check src pdf_plugins tests/test_comdirect_historical_tax_mapping.py --select F
```

Ergebnis: erfolgreich; Ruff meldet `All checks passed!`.

Vollständige Regression:

```powershell
python -m pytest -q --basetemp tmp/pytest_comdirect_historical_tax_mapping
```

Ergebnis:

```text
1245 passed, 16 skipped, 2 warnings, 5 subtests passed in 595.41s
```

Die zwei Warnungen betreffen unverändert die veraltete Qt-Methode `QSortFilterProxyModel.invalidateFilter()` in `src/portman/tax_detail_view.py`; diese Datei wurde nicht geändert.

## Risiken und Empfehlung

Die Zuordnung ist absichtlich konservativ. Bei Mehrdeutigkeit wird niemals automatisch gewählt. Da Dokument- und Steueridentitäten nicht geändert wurden und die vollständige Regression grün ist, ist die Änderung für einen getrennten lokalen Commit freigabefähig.

Es wurde kein Commit und kein Push ausgeführt.
