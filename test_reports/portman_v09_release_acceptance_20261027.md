# Portman V09 - FNZ-Mengenprüfung und Release-Abnahme

Stand: 28.10.2026

## 1. Executive Summary

Bewertung: **READY WITH ACCEPTED WARNINGS**.

Die verbliebenen FNZ-Befunde betreffen 15 physische Dateien, sechs eindeutige
Dateiinhalte und sieben Kauftransaktionen. Die wirtschaftliche Prüfung bestätigte
die Transaktionen; die Warnungen entstanden beim Vergleich von Kurs- und
Buchungswährungen ohne Umrechnung. Der Parser gab den im Dokument enthaltenen
Devisenkurs nicht an die Validierung weiter.

Der Fix übergibt den Devisenkurs zur Validierung und prüft Beträge in derselben
Währung. Geprüfte Transaktionswerte und Zahlungsflüsse werden nicht verändert.
Alle gezielten und vollständigen Regressionstests sind erfolgreich. Produktive
Datenbanken und Originaldokumente wurden nicht verändert.

## 2. Ausgangscommit und Git-Status

- Branch: `main`
- Ausgangs-HEAD und `origin/main`: `cf2e04ca31d03482ed618aec67729419884d5525`
- Vorhandene lokale Nachbesserungen wurden erhalten:
  `src/portfolio_v5/storage.py`, `tests/test_advance_tax_events.py` und
  `test_reports/portman_v09_final_fixes_20261027.md`.
- Vor der Bearbeitung wurde außerhalb des Repositorys ein SHA-256-Manifest der
  betroffenen Ausgangsdateien erstellt.

## 3. FNZ-QUANTITY_CONFLICT-Ergebnisse

Grundlage war das abgeschlossene PDF-Audit V3. Die Quelldokumente wurden nur
lesend geprüft. Die 15 physischen Dateien entsprechen sechs eindeutigen Inhalten
und sieben betroffenen Einzeltransaktionen. Jede Transaktion wurde anhand der
gedruckten Währungsangaben, Mengen, Kurse, Gebühren und Zahlungsbeträge geprüft.

Verwendete Beziehung: `Stückzahl × Kurs ÷ dokumentierter Umrechnungsfaktor =
Anlagebetrag`. Die Beträge stimmen innerhalb der dokumentierten Rundungsgenauigkeit
überein. Es gab keine falsche Tabellenzeilenzuordnung, keinen OCR-Zahlendreher,
keinen abweichenden Kursfaktor und keine Korrekturbuchung. Andere, nicht von der
Währungsumrechnung betroffene Buchungsarten wurden separat kontrolliert.

## 4. Parser- und Validierungskorrektur

- `pdf_plugins/fnz_finvesto.py` übergibt bei Kaufzeilen den explizit gedruckten
  Devisenkurs an das Transaktionsmodell.
- `src/portfolio_v5/models.py` vergleicht Preis und Kurswert bei unterschiedlichen
  Preis-/Buchungswährungen erst nach dokumentierter Umrechnung.
- Fehlt bei einer währungsübergreifenden Kursprüfung der Devisenkurs, wird weiterhin
  eine konkrete `FX_RATE_MISSING`-Warnung ausgegeben. Warnungen werden nicht
  unterdrückt.
- Gleichwährige Geschäfte und explizite FX-Währungspaare behalten ihre bisherige
  Prüflogik.

## 5. Wirtschaftlicher Vorher-/Nachher-Vergleich

| Feld | Vorher | Nachher |
| --- | --- | --- |
| Stückzahl, Kurs und Beträge | aus dem Dokument gelesen | unverändert |
| Gebühren und Zahlungsflüsse | aus dem Dokument gelesen | unverändert |
| Devisenkurs | erkannt, aber bei Käufen nicht weitergegeben | als Prüfmetadatum erhalten |
| Mengenprüfung | Werte in unterschiedlichen Währungen verglichen | vor dem Vergleich umgerechnet |

## 6. Testabdeckung

- Neue Modellregression für einen FNZ-Fremdwährungskauf sowie einen fehlenden
  Devisenkurs.
- FNZ-Regression mit synthetischen Fremdwährungskäufen und Gebühren-/Cashflow-
  Prüfung.
- Lesende Neuprüfung aller sechs eindeutigen Original-PDFs: sieben relevante
  Käufe, keine Parserfehler, keine Validierungsbefunde.
- Gezielte Parser-/Modellprüfung: 47 bestanden.
- Gezielte Release-Suite (FNZ, comdirect, Deka, PDF-Audit, SQLite, Import,
  Steuer, Performance und GUI-Komponenten): 199 bestanden, 1 übersprungen.

## 7. GUI-Smoketests

Die echte Klasse `src/Gui/PortMan_V09.py::MainWindow` wurde mit
`QT_QPA_PLATFORM=offscreen` und einer neu erzeugten temporären SQLite-Datenbank
gestartet. Hauptfenster, Repository und V09-Initialisierung waren bereit; das
Fenster wurde anschließend sauber geschlossen.

Automatisiert abgedeckt sind Depot-/Kontoansichten, Importvorschau,
Konfliktbehandlung, Steuer-/Performance-Komponenten, Diagrammrenderer und
Exportfunktionen. Eine vollständige manuelle Bedienabnahme mit realer Anzeige,
Maus und Tastatur wurde nicht durchgeführt und wird nicht behauptet.

## 8. SQLite-Integritätsprüfung

Die Tests decken idempotenten Reimport, Dubletten-/ID-Konflikte, Atomarität,
Revisionen, Undo, FIFO-Einstandswerte, realisierte Gewinne und Cashflow-Konsistenz
ab. Der zusätzliche Vorabpauschalen-Reimporttest bestätigt: gleicher
wirtschaftlicher Sachverhalt mit neuer Dokumentidentität wird nicht dupliziert;
echte Wertabweichungen bleiben blockiert.

Sämtliche Datenbankprüfungen verwendeten temporäre synthetische Datenbanken.
`data/v09/portfolio.sqlite` wurde nicht geöffnet oder migriert.

## 9. Vollständige Regression

| Befehl | Ergebnis |
| --- | --- |
| `python -m compileall -q src pdf_plugins tools` | bestanden |
| `python -m ruff check src pdf_plugins --select F` | bestanden |
| `python -m pytest -q --basetemp tmp/pytest_v09_release` | 1.224 bestanden, 16 übersprungen, 5 Subtests bestanden, 0 Fehler, 375,70 s |

## 10. Offene Warnungen und Risiken

- Zwei bestehende Qt-Deprecation-Warnungen in `tax_detail_view.py` für
  `QSortFilterProxyModel.invalidateFilter()`; kein funktionaler Fehler.
- Eine manuelle visuelle End-to-End-GUI-Abnahme bleibt für den Releaseprozess
  empfehlenswert.
- Historische unversionierte Auditwerkzeuge und private Auditdaten sind nicht Teil
  des vorgesehenen Commits.

## 11. Release-Empfehlung

**READY WITH ACCEPTED WARNINGS**.

Die sieben FNZ-Fälle sind fachlich aufgeklärt und nach der minimalen Korrektur
ohne Warnung reproduzierbar. Es gibt keine neuen wirtschaftlichen
Inkonsistenzen, alle Regressionen sind grün, und produktive Daten wurden nicht
verändert. Vor einer Auslieferung wird nur noch eine kurze manuelle GUI-Sichtprobe
empfohlen.
