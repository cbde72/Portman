# Portman V09 – P1: FIFO und Einstandskosten

Stand: 29.10.2026, Branch `codex/p1-fifo-cost-basis`, Ausgangspunkt `main` (`08f29cc`).

## Gap-Tabelle vor Änderungen

| Bereich | Status | Nachweis / Codefundstelle |
|---|---|---|
| Mehrere Käufe, Teilverkauf über mehrere Lose, Bruchstücke | abgeschlossen | `src/portman/baader_holdings.py:purchase_value`, `apply_costs`; `tests/test_baader_portfolio_history.py` |
| Kaufnebenkosten in der Kostenbasis | abgeschlossen | Der Settlement-Betrag wird als Gesamteinstand verwendet; Parsergleichung und FIFO-Tests in `tests/test_baader_trade_semantics.py` und `tests/test_baader_portfolio_history.py` |
| Verkaufsprovisionen im realisierten Ergebnis | abgeschlossen | Nettoerlös aus dem Settlement-Betrag in `src/portman/analysis_v09.py:realized_profit`; Aggregationstest in `tests/test_depot_overview.py` |
| Getrennte Lose je Depot, Wertpapier und Währung | abgeschlossen | Schlüssel `(depot, security, currency)` in `apply_costs` und `realized_profit` |
| Vollverkauf, Wiederkauf, offene/geschlossene Positionen | teilweise | FIFO-Verbrauch funktioniert; eine vollständige, depotübergreifende Kettentest-Abdeckung fehlt |
| Reihenfolge mehrerer Buchungen am selben Tag | teilweise | Ohne belegte Reihenfolge bewusst unbekannt; Transaktionen besitzen derzeit keine persistierte Ausführungssequenz |
| Unbekannter Anfangseinstand | abgeschlossen | Bleibt `None`; unbekannte Lose werden nicht zu 0 EUR umgedeutet (`apply_costs`, `realized_profit`) |
| Aktiensplit / Reverse Split | abgeschlossen | Stückzahl und Lospreis werden reziprok fortgeführt; Gesamtkosten bleiben erhalten (`baader_holdings.py`, `tests/test_cost_split.py`) |
| Eigener Depotübertrag mit Loserhalt | **fehlerhaft** | `corporate_actions.TRANSFER` wird nur in `change_analysis`, nicht in `holdings`/`apply_costs`/`realized_profit` fortgeführt |
| Fusion / Kennungswechsel mit Loserhalt | **fehlerhaft** | `MERGER` markiert spätere Verkäufe pauschal unbekannt; Bestands- und Losfortführung fehlt |
| Ein-/Auslieferung aus Transaktionsimporten | teilweise | Mengenbewegung ist analysierbar, Kostenbasis mangels belegter Paarung bewusst unbekannt; kein fiktiver Verkauf |
| Spin-off, Bezugsrecht, Kapitalrückzahlung | fehlend | Datenmodell enthält keine belegfähige Kostenaufteilung; eine automatische Aufteilung wäre fachlich unzulässig |
| Storno/Korrektur von Kapitalmaßnahmen | abgeschlossen | Soft-Revoke mit Auditquelle in `RepositoryV09.revoke_action`; Split-Rücknahme getestet |
| Historische Fremdwährung | teilweise | Lose sind nach Währung getrennt; historische FX-Werte werden nicht als erfundene EUR-Kostenbasis verwendet |
| Import-Idempotenz und SQLite-Integrität | abgeschlossen | Duplikat-/Reimporttests vorhanden; produktive DB wird in diesem Audit ausschließlich per `mode=ro` geprüft |

## Änderungen

### Nachgewiesene Fehler und Korrekturen

1. **Depotüberträge wurden nicht in Bestand und Kostenbasis fortgeführt.**
   `PortfolioRepository.holdings` stellte bisher ausschließlich Splits als Replay-Ereignis bereit. `TRANSFER` war nur in der Mengenvergleichsanalyse sichtbar. Jetzt wird vor einem Kontofilter der vollständige Depotgraph wiedergegeben (`src/portman/repository.py:75-116`). Ein Teilübertrag entnimmt die ältesten Quelllose und fügt sie mit ursprünglichem Anschaffungsdatum, Einstand und Währung in das Zieldepot ein (`src/portman/baader_holdings.py:39-82`, `156-179`).

2. **Fusionen/Kennungswechsel zerstörten die auswertbare FIFO-Kette.**
   Ein dokumentierter `MERGER` führte bislang dazu, dass jeder spätere Verkauf pauschal unbekannt blieb. Jetzt werden Stückzahl und Stückkosten mit dem belegten Umtauschverhältnis transformiert, während der Gesamteinstand erhalten bleibt (`src/portman/analysis_v09.py:263-294`). Es findet keine unbelegte Kostenaufteilung statt.

3. **Übertragene Lose wurden am Ziel nach Übertragungszeitpunkt statt ursprünglichem Kaufdatum angeordnet.**
   Bei bereits vorhandenem Zielbestand konnte dies das falsche Los zuerst verbrauchen. Die Losbücher tragen jetzt das ursprüngliche Anschaffungsdatum und werden nach dem Zusammenführen danach sortiert (`src/portman/analysis_v09.py:285-289`, `src/portman/baader_holdings.py:165-174`).

4. **Vollständig unbekannte Kostenlose waren im Zielbestand nicht quantitativ ausgewiesen.**
   Der Einstand blieb zwar `None`, `unknown_cost_quantity` wurde aber nur bei teilweise bekannten Kosten gesetzt. Die unbekannte Menge wird nun auch bei vollständig unbekanntem Einstand ausgewiesen (`src/portman/baader_holdings.py:192-203`). Es wird ausdrücklich weder 0 EUR noch ein Schätzwert erzeugt.

5. **Kontospezifische Depotansicht konnte den Quellbestand eines eingehenden Übertrags ausblenden.**
   Die Berechnung erfolgt jetzt vollständig depotübergreifend; erst das fertige Ergebnis wird auf das ausgewählte Konto eingeschränkt (`src/portman/repository.py:75-116`). Spätere vollständige Depotstände verhindern weiterhin eine doppelte Wiedergabe bereits enthaltener Maßnahmen.

### Unverändert gelassene korrekte Funktionen

- Settlement-Gesamtbetrag als Kaufkosten einschließlich enthaltener Kaufnebenkosten.
- Nettoverkaufserlös einschließlich der im Settlement enthaltenen Verkaufsgebühren.
- Normale FIFO-Verarbeitung für mehrere Käufe, Teil- und Vollverkäufe, Bruchstücke, Wiederkäufe sowie getrennte Bücher je Depot/Wertpapier/Währung.
- Splits und Reverse Splits: Stückzahl und Stückkosten ändern sich reziprok, Gesamteinstand bleibt gleich.
- Gebühren-, Steuer- und Dividendenbuchungen; daran wurde kein Produktivcode geändert.
- Vorabpauschalenanrechnung auf später realisierte Ergebnisse.

### Regressionstests

Neu in `tests/test_fifo_cost_basis_p1.py`:

- vollständige Kette Kauf → Kauf → Teilverkauf → Teilübertrag → Split → Verkauf;
- Übertrag eines vollständig unbekannten Alt-Einstands;
- Zusammenführung vorhandener Ziellose nach ursprünglichem Kaufdatum;
- Fusion/Kennungswechsel mit Umtauschverhältnis und anschließendem Verkauf.

Der bestehende Split-Test in `tests/test_v09.py` wurde an die nun belegbar fortgeführte FIFO-Kostenbasis angepasst. Ein dokumentierter Split macht einen späteren Verkauf nicht mehr künstlich unbekannt.

## Testergebnisse und wirtschaftliche Werte

### Unabhängiger Referenzfall

| Vorgang | Erwarteter FIFO-Effekt | Ergebnis vorher | Ergebnis nachher |
|---|---:|---:|---:|
| Kauf 10 Stück für 100 EUR | Los 10 × 10 EUR | 10 × 10 EUR | 10 × 10 EUR |
| Kauf 5 Stück für 100 EUR | Los 5 × 20 EUR | 5 × 20 EUR | 5 × 20 EUR |
| Verkauf 12 Stück für 180 EUR | Kosten 140 EUR, Gewinn 40 EUR | 140 / 40 EUR | 140 / 40 EUR |
| Übertrag 2 der verbleibenden Stücke A → B | ursprüngliches Los 2 × 20 EUR | spätere Ergebnisse unbekannt | 2 × 20 EUR erhalten |
| Split 1:2 im Depot B | 4 × 10 EUR, Gesamt 40 EUR | spätere Ergebnisse unbekannt | 4 × 10 EUR |
| Verkauf 3 Stück für 45 EUR | Kosten 30 EUR, Gewinn 15 EUR | unbekannt | 30 / 15 EUR |
| Rest Depot A bei Wert 25 EUR | 1 Stück, Kosten 20 EUR, unrealisiert +5 EUR | Transfer nicht fortgeführt | korrekt |
| Rest Depot B bei Wert 12 EUR | 1 Stück, Kosten 10 EUR, unrealisiert +2 EUR | Transfer/Split nicht fortgeführt | korrekt |

Zusätzlicher Fusionsfall: 3 Altaktien mit Gesamteinstand 120 EUR werden im Verhältnis 0,5 in 1,5 neue Aktien getauscht. Verkauf einer neuen Aktie für 100 EUR ergibt belegte Kosten 80 EUR und Gewinn 20 EUR; das Restlos beträgt 0,5 Stück / 40 EUR.

### Datenbank- und Importprüfung

- Produktive Datenbank `data/v09/portfolio.sqlite` ausschließlich mit SQLite-URI `mode=ro` geöffnet.
- `PRAGMA integrity_check`: `ok`.
- Bestand: 8.170 Transaktionen, 218 Snapshots; keine produktiv erfassten Kapitalmaßnahmen oder Wertpapier-Transferbuchungen. Die Transfer-/Fusionskorrektur ist daher durch deterministische Referenzketten belegt, nicht durch erfundene Interpretation produktiver Daten.
- Import-Idempotenz ist durch die vollständige Suite einschließlich der vorhandenen Reimporttests abgedeckt.
- Originaldateien unter `C:\Users\chris\Desktop\history` wurden nur gelesen und nicht verändert.

### Testläufe

- Gezielte FIFO-/Bestands-/V09-Suite: **87 bestanden**.
- Vollständige Pytest-Suite: **1.265 bestanden, 19 übersprungen**, 394,56 s.
- Reale PDF-Validierung: 23/23 MiFID-Kosten-PDFs strukturiert und cash-neutral erkannt; der 126-PDF-Clean-Reimport erreichte in beiden Importreihenfolgen fehlerfreie Parser-, Zuordnungs-, Duplikat- und SQLite-Prüfungen.
- Der zunächst beobachtete Realtest-Unterschied 940,77/523,07 EUR wurde anschließend als Doppelzählung eigenständiger Ertragsgutschrift-PDFs aufgeklärt und auf demselben Branch korrigiert. Details stehen in `test_reports/portman_v09_tax_difference_41770.md`.

## Verbleibende fachliche Einschränkungen

- Mehrere Wertpapierbuchungen am selben Tag bleiben ohne persistierte, belegte Ausführungssequenz bewusst unbekannt; externe IDs werden nicht als Reihenfolge missbraucht.
- Ungepaarte `TRANSFER_IN`/`TRANSFER_OUT`-Importbuchungen erhalten keine erfundene Kostenbasis. Die sichere Losfortführung setzt eine explizit belegte Kapitalmaßnahme voraus.
- Spin-offs, Bezugsrechte und Kapitalrückzahlungen besitzen noch kein Modell für eine belegte Kostenaufteilung. Ohne entsprechende Belegdaten erfolgt keine automatische Verteilung.
- Historische Fremdwährungskosten bleiben in ihrer Belegwährung getrennt. Ohne belegten historischen FX-Kurs wird kein EUR-Einstand geschätzt.
- Ein pauschaler Depotstand mit Gesamteinstand, aber ohne einzelne Anschaffungshistorie, kann die exakte historische FIFO-Reihenfolge nicht beweisen. Vollständig dokumentierte Käufe und manuell belegte Maßnahmen sind davon nicht betroffen.
