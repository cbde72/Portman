# Portman V09 – P1/P2 Restarbeiten

## Gap-Tabelle vor der Umsetzung

| Bereich | Status auf `main` (`b66ba59`) | Codefundstelle | Befund |
|---|---|---|---|
| EUR-Einstand bei Fremdwährung | teilweise | `src/portman/baader_holdings.py:purchase_value`, `src/portman/analysis_v09.py:realized_profit` | Der dokumentierte Abrechnungsbetrag einschließlich Gebühren wird genutzt; bei einer Buchung in USD/GBP werden jedoch vorhandene explizite FX-Paare nicht in EUR fortgeführt. |
| Historische Wechselkurse | teilweise | `src/portman/repository_v09.py:save_fx`, `historical_rate` | Belegkurse können gespeichert werden. Die bisherige Sieben-Tage-Rückschau ist für Bewertung geeignet, aber kein belastbarer Ersatz für einen fehlenden Transaktionskurs der Kostenbasis. |
| Fremdwährungsdividenden/-gebühren | abgeschlossen | `src/portfolio_v5/models.py`, Income-/Tax-Auswertungen und Parser-Regressionstests | Originalwährung, Buchungswährung, Steuern und Gebühren bleiben erhalten; keine Änderung ohne Gegenbeleg. |
| Handels- und Berichtswährung | teilweise | `src/portman/analysis_v09.py`, `src/portfolio_v5/performance.py` | Handelswährung wird ausgewiesen; EUR-Performance lehnt unbelegte Fremdwährungen korrekt ab. Ein belegter EUR-FIFO-Ausweis fehlt. |
| Fehlender Wechselkurs | teilweise | Modellvalidierung und Performance | Widersprüchliche/fehlende Kurse werden erkannt; Kostenübersichten kennzeichnen die unbekannte EUR-Basis noch nicht durchgängig. |
| Manuelle Kapitalmaßnahme `TRANSFER` | abgeschlossen | `RepositoryV09.add_action`, `baader_holdings`, `realized_profit` | Ursprüngliche FIFO-Lose, Kaufdaten und Teilüberträge werden fortgeführt; unbekannte Kosten bleiben unbekannt. |
| Belegtes `TRANSFER_IN`/`TRANSFER_OUT`-Paar | fehlend | `realized_profit` | Importierte Wertpapierüberträge werden pauschal als unbekannt behandelt; es gibt keine bestätigbare Paarung analog zu Geldumbuchungen. |
| Splits/Reverse Splits | abgeschlossen | `baader_holdings`, `realized_profit`, `tests/test_fifo_cost_basis_p1.py` | Stückzahl und Stückkosten werden mit positivem Verhältnis fortgeführt. |
| Fusion/Wertpapierumtausch | abgeschlossen | dieselben Fundstellen | Kennung, Verhältnis und ursprüngliche Lose werden fortgeführt. |
| Spin-off/Bezugsrechte/Kapitalrückzahlung | fehlend | `corporate_actions`/`add_action` | Das Datenmodell kennt diese Typen nicht. Ohne belegte Kostenaufteilung darf keine automatische Verteilung erfolgen. |
| Storno/Korrektur Kapitalmaßnahme | abgeschlossen | `RepositoryV09.revoke_action` | Rücknahme ist auditierbar und getestet. |
| FIFO am selben Tag ohne Zeit | abgeschlossen | `tests/test_v09.py:test_same_day_trade_order_is_not_inferred_from_external_ids` | Ergebnis bleibt bewusst unbekannt; Import-ID wird nicht als fachliche Reihenfolge akzeptiert. |
| FIFO am selben Tag mit Ausführungszeit | fehlerhaft | `Transaction.executed_at`, `analysis_v09.realized_profit`, `baader_holdings` | Die belegte Zeit wird persistiert, aber nicht verwendet; teilweise wird danach noch nach externer ID sortiert. |

## Nachgewiesene Fehler und Korrekturen

- **FIFO-Zeitpunkt wurde ignoriert:** `executed_at` war bereits Bestandteil des persistierten Transaktions-Payloads, die Berechnungen sortierten jedoch nicht danach. `realized_profit` und die Bestands-/Kostenfortschreibung verwenden jetzt ausschließlich eine gültige Zeitzonen-Ausführungszeit. Fehlende, ungültige oder gleiche Zeiten bleiben mehrdeutig; externe IDs bestimmen die Reihenfolge nicht mehr.
- **Belegter Fremdwährungseinstand ohne EUR-Ausweis:** Realisierte Ergebnisse enthalten jetzt zusätzlich `report_currency`, `proceeds_eur`, `cost_eur`, `realized_eur` und `fx_status`. Verwendet werden nur EUR-Buchungen, ein explizites passendes FX-Paar oder ein exakt tagesgleicher Kurs mit Belegquelle. Die vorhandene Sieben-Tage-Bewertungsrückschau wird nicht als Anschaffungskurs missbraucht.
- **Importierter Wertpapierübertrag verlor die Loskette:** Zwei aktive, in Kennung und Stückzahl übereinstimmende `TRANSFER_OUT`-/`TRANSFER_IN`-Buchungen können nun mit Belegquelle bestätigt werden. Erst diese Bestätigung erzeugt beim Replay eine cash-neutrale `TRANSFER`-Maßnahme. Das Quelllos einschließlich ursprünglichem Kaufdatum und Einstand wird fortgeführt; beide Rohbuchungen werden nicht zusätzlich verarbeitet.
- **Mehrdeutige Tageskosten:** Bei mehreren Käufen/Verkäufen ohne eindeutige belegte Uhrzeiten kennzeichnet auch die Depotkostenfortschreibung die Loskosten als unbekannt, statt eine externe Import-ID als Reihenfolge zu verwenden.

Nicht geändert wurden die bereits korrekten Gebühren-, Dividenden-, Steuer-/417,70-€-Deduplizierungs-, Split-, Reverse-Split-, Fusions- und manuellen Transferpfade.

## Wirtschaftliche Vorher-/Nachherwerte

| Referenzkette | Vorher | Nachher |
|---|---:|---:|
| Kauf 100 EUR 09:00 → Verkauf 150 EUR 10:00 am selben Tag | realisiert unbekannt | Einstand 100 EUR, realisiert 50 EUR |
| Kauf 100 USD zu belegten 0,90 EUR/USD → Verkauf 150 USD zu 0,80 EUR/USD | 50 USD; kein EUR-Ergebnis | 50 USD und 30 EUR realisiert (90 EUR Einstand, 120 EUR Erlös) |
| Derselbe GBP-Fall nur mit Vortageskurs | kein belastbares EUR-Ergebnis | unverändert unbekannt; kein geschätzter oder fortgeschriebener Kurs |
| Kauf 2 Stück/200 EUR → bestätigter Depotübertrag → Verkauf 2 Stück/260 EUR | importierte Transfers machten FIFO unbekannt | Einstand 200 EUR, realisiert 60 EUR, Cashflow des Übertrags 0 EUR |

Die vorhandene vollständige Referenzkette Kauf → weiterer Kauf → Teilverkauf → manueller Teilübertrag → Split → Verkauf blieb unverändert bei realisierten Ergebnissen 40 EUR und 15 EUR sowie Restkosten 20 EUR (Quellposition) und 10 EUR (Zielposition).

## Testergebnisse

- Neue gezielte Regressionen: **4 bestanden** (`tests/test_p1_p2_completion.py`).
- FIFO-/Depot-/Steuer-/Dividenden-/Performance-Auswahl: **139 bestanden**.
- Vollständige Suite einschließlich Realimport-Akzeptanz auf dem finalen Stand: **1273 bestanden, 19 übersprungen, 5 Subtests bestanden**, 2 bestehende Qt-Deprecation-Warnungen; Laufzeit 413,40 s.
- Produktive `data/v09/portfolio.sqlite` ausschließlich per SQLite-URI `mode=ro`: `PRAGMA integrity_check = ok`, `PRAGMA foreign_key_check` ohne Befund. In dieser Datei lagen keine BUY/SELL/TRANSFER-Buchungen, Kapitalmaßnahmen, historischen FX-Kurse oder Ausführungszeiten vor; daraus wurden folglich keine wirtschaftlichen Werte abgeleitet.
- Die vorhandenen comdirect-Steuermitteilungen und die durch die Suite verwendeten Realbelege wurden nicht verändert. Die Belegsuche ergab keine Original-PDFs für Spin-off, Bezugsrecht, Kapitalrückzahlung oder Wertpapierumtausch; deren Kostenlogik wurde deshalb nicht anhand erfundener Beispiele produktiv aktiviert.

## Verbleibende Einschränkungen

- Spin-offs, Bezugsrechte und Kapitalrückzahlungen bleiben ohne konkrete Originalbelege und dokumentierte Kostenaufteilung offen. Sie werden nicht automatisch als Nullkostenereignis interpretiert. Splits/Reverse Splits, Fusionen/Umtausch, Transfers und deren Rücknahme sind vorhanden.
- Die Bestätigung eines importierten Wertpapierübertrags ist derzeit eine Repository-Funktion; eine neue GUI wurde gemäß Aufgabenbegrenzung nicht ergänzt. Bestehende manuelle Kapitalmaßnahmen bleiben als UI-Korrekturweg verfügbar.
- Historische Markt-/Referenzkurse dürfen weiter zur Bewertung dienen, aber nur ein exakt datierter, quellbelegter Kurs gelangt in die EUR-Kostenbasis. Fehlt er, bleiben `cost_eur` und `realized_eur` `None` und `fx_status` erklärt die Ursache.
- Handelswährungsübergreifende Losketten (beispielsweise Kauf in USD und Verkauf desselben Loses in GBP) werden nicht automatisch verrechnet. Ohne beidseitige belegte EUR-Werte bleibt die Kostenbasis unbekannt.
