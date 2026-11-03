# Portman PDF Lab – Phase-3-Architektur

## Abhängigkeitsrichtung

```text
portman-pdf-lab
       │
       ▼ ausschließlich öffentliche API
portman-parsers
       │
       ├─ api          unveränderliche DTOs und JSON-Vertrag
       ├─ registry     Allowlist und deterministische Auswahl
       ├─ validation   bankunabhängige Fachregeln
       ├─ extraction   optionale Text-Extraktionsgrenze
       └─ plugins      Phase 3: keine Bankimplementierungen
```

`portman-parsers` kennt weder PDF Lab noch Portman V09. PDF-/OCR-Engines liegen
hinter `extraction.TextExtractor` und werden nicht beim Import der API geladen.

## Öffentlicher Vertrag

- API-Version `0.3`, Schema-Version `1.2.0`, Paketversion `0.3.0`.
- Positive Cashbeträge sind Zuflüsse, negative Cashbeträge Abflüsse.
- Steuer- und Kostenkomponenten sind positive Beträge. Eine wirtschaftliche
  Zahlung existiert nur über eine explizit referenzierte `CashMovement`.
- Dokument-, Ergebnis-, Ereignis-, Cash-, Wertpapier-, Steuer-, Kosten-,
  Snapshot- und Evidence-IDs sind getrennt.
- `MissingValue` unterscheidet `UNKNOWN`, `NOT_APPLICABLE` und `NOT_FOUND`.
  Ein numerischer Nullwert ist davon verschieden.
- DTOs enthalten keine PDF-Binärdaten und kein Base64.
- `Decimal` wird deterministisch als String serialisiert.

## Depot- und Kontomodell

- `Depot` und `Account` enthalten ausschließlich Stammdatenfelder.
- `DepotSnapshot`/`DepotPosition` bilden stichtagsbezogene Bestände ab;
  `AccountBalance` bildet einen belegten Saldo ab.
- `DepotAccountLink` erlaubt mehrere Konten je Depot und mehrere Depots je Bank.
- `FieldValue` versieht jedes extrahierte Feld mit Quelle, Seite, Evidence und
  Prüfstatus. PDF- und manuelle Stammdaten bleiben unterscheidbar.
- `CashMovement.account_id` und `SecurityMovement.depot_id` ordnen Wirkungen zu.
  Optionale gegenseitige Movement-IDs verbinden Settlement und Wertpapierseite,
  ohne eine zweite wirtschaftliche Wirkung anzulegen.

## Gebühren- und Kostenmodell

- `FeeEvent` ist die einmalig zählbare wirtschaftliche Gebührenposition;
  `FeeAllocation` kann dieselbe Position mehreren fachlichen Zielen zuordnen.
- `FeeEffect` trennt tatsächlich gebucht, im Settlement enthalten,
  informatorisch, geschätzt, Rückerstattung und Storno.
- `CostEvent` bildet Kosteninformationen und MiFID-II Ex ante/Ex post ab.
  Informatorische Kosten dürfen keine Cashbewegung erzeugen.
- Deduplizierung verwendet Referenz, Kategorie, Unterkategorie, Betrag,
  Währung, Datum und fachliche Zuordnungen. Doppelte Dokumentnachweise werden
  gemeldet und nur einmal aggregiert.
- Settlementvalidierung prüft Kurswert, deduplizierte enthaltene Gebühren,
  Steuern und Nettozahlung mit `Decimal`-Toleranz.
- Aggregationen gruppieren nach Bank, Depot, Konto, Wertpapier, Kategorie,
  Transaktion und Zeitraum. Währungen bilden immer getrennte Summen.
- `IssueNature` unterscheidet fehlende Information, ungesicherte Zuordnung,
  mathematische Inkonsistenz und bestätigte Abweichung.

## Registry

Die Registry akzeptiert ausschließlich die neun freigegebenen Einstiegspunkte
der acht Parsergruppen. Die 33 Handler sind in Phase 3 als nicht ausführbare
Metadaten vorhanden. Unbekannte Plugins werden abgewiesen; nicht implementierte
Handler melden `NOT_IMPLEMENTED`. Es gibt keine Dateisystem-Discovery.

## Validierungsstatus

`IssueSeverity` unterscheidet `INFO`, `WARNING`, `ERROR` und `CRITICAL`.
Validierungen liefern Issues und verändern keine Parserergebnisse. Mathematische
Plausibilität ist kein Ground-Truth-Nachweis; Review- und Referenzfallstatus
bleiben deshalb separate Anwendungskonzepte.

