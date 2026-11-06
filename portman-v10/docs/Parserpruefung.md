# Parserprüfung – 6. November 2026

## Geprüfter Stand

Die lokal installierte Distribution `portman-parsers` ist eine editable
Installation der Version `0.6.0` aus
`C:\Users\chris\Desktop\programming\PortmanNL\portman-parsers`. Geprüft wurde
dieser Quellstand auf Commit `bdc8eb8`. Der V10-Worktree selbst basiert dagegen
bewusst auf `origin/main` bei `816034a`; dort ist der Parserstand älter. Eine
V10-Anbindung darf deshalb nicht allein aus dem Inhalt des V10-Worktrees auf die
aktuell lokal installierten Handler schließen.

Das Paket verlangt Python >=3.11 und deklariert `pypdf>=6,<7` sowie
`PyYAML>=6,<7`. Die Projektlizenz ist MIT. Für
`plugins/comdirect_pp.py` gilt gemäß `NOTICE_COMDIRECT_PP.md` die mitgelieferte
EPL-1.0. Es gibt keine Python-Paket-Entry-Points oder Konsolenskripte. Der
öffentliche Einstieg ist programmatisch:

```python
from portman_parsers.registry import default_registry

registry = default_registry()
detection = registry.select(document)
result = registry.parse(document, detection) if detection is not None else None
```

`default_registry()` registriert deterministisch eine feste Allowlist; es gibt
keine Dateisystem- oder Entry-Point-Discovery. `select()` verwendet standardmäßig
eine Mindestkonfidenz von `Decimal("0.70")` und meldet gleich starke Treffer
verschiedener Handler als Mehrdeutigkeit. `parse()` lehnt unbekannte und nur als
Metadaten vorhandene Handler ausdrücklich ab.

## Ausführbare Handler

Die geprüfte Allowlist enthält 42 Handler in zehn Plugin-IDs. Davon sind 35 als
`IMPLEMENTED` registriert und über konkrete Plugin-Klassen ausführbar:

- `user.comdirect-ertraege` 2.0: neun Handler für Erträge, Einlösung,
  MiFID-Kosteninformation, Investmentausschüttung, inländische
  Dividendensteuer, Vorabpauschale, Kauf und Verkauf.
- `comdirect.finanzreport` 3.0: `finanzreport`.
- `portfolio-performance.comdirect` `pp-c08d5053`: neun comdirect-Handler.
- `baader.pdf` 2.0: sechs Handler.
- `user.ing-wertpapiere` 2.0: sechs Handler.
- `user.deka-quartalsbericht` 1.0: `quartalsbericht`.
- `fnz.finvesto` 2.0: `umsatzabrechnung` und `depotauszug`.
- `user.bank-of-scotland-kontoauszug` 1.0: `kontoauszug`.

Nur Metadaten, nicht ausführbar, sind die sechs Renault-Handler und
`generic.kontoauszug/generic`. `pbb_direkt` und `baader_krypto` sind ausdrücklich
blockiert. Die Readiness-Angabe ist eine technische Registrierung, keine
fachliche Freigabe jedes realen Belegs; V10 muss Parser-Issues und Evidence
weiterhin auswerten und darf unsichere Ergebnisse nicht automatisch übernehmen.

## Öffentlicher Vertrag

`API_VERSION` ist `0.6`. Eingabe ist ein `PdfDocument` mit Dokument-ID,
Quellhash, Seiten, Dateiname und Metadaten. Eine `Detection` trägt Plugin- und
Handler-ID samt Version, Dokumenttyp, `Decimal`-Konfidenz und Begründung. Das
Ergebnis ist ein `ParsedDocument` mit stabilen Identitäten sowie Events,
Snapshots, Evidence, Issues, Konten, Depots, Salden, Depotständen,
Kontoverknüpfungen und Vorabpauschalen-Daten.

Für die V10-Anbindung besonders relevant sind `FinancialEvent`,
`CashMovement`, `SecurityMovement`, `SecurityTrade`, `TaxEvent`, `TaxComponent`,
`FeeEvent`, `CostEvent`, `AccountBalance` und `DepotSnapshot`. Beträge und Mengen
sind `Decimal`. Fehlende fachliche Werte werden über `MissingValue` beziehungsweise
bei belegbezogenen Stammdaten über `FieldValue` dargestellt, nicht als Nullbetrag.
Steuer- und Kostenkomponenten erzeugen nicht von selbst eine Geldbewegung;
Bestandsnachweise sind keine synthetischen Käufe. Evidence-IDs und
Dokument-/Parseridentitäten müssen beim Mapping erhalten bleiben.

Eine konkrete V10-Infrastrukturkomponente darf daher nur
`portman_parsers.api` und `portman_parsers.registry` konsumieren. Parser-DTOs
dürfen nicht in Domain oder Anwendungsschnittstelle durchsickern. Ein Adapter
ist in V10-01 bis V10-04 noch nicht implementiert; dessen erster Dokumenttyp ist
ein eigener späterer Auftrag.

## Ausgeführte Prüfung

Im Parserpaket wurde ausgeführt:

```powershell
python -m pytest tests -p no:cacheprovider --basetemp="C:\Users\chris\AppData\Local\Temp\opencode\pt-v10-parser"
```

Ergebnis: 268 Tests bestanden in 5,76 Sekunden unter Python 3.14.3. Darin sind
Architektur-, API-/Registry-Vertrags- und Referenztests der registrierten
Plugin-Klassen enthalten. Es wurden keine Parserdateien geändert.
