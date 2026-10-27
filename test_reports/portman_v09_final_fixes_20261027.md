# Portman V09 – Finale Fehlerkorrekturen

Datum: 2026-10-27

## 1. Ausgangscommit und Git-Status

- Arbeitsbranch: `main`
- Ausgangs-HEAD: `1e0a98702cb408750839f67309d3a9829f99d9f6`
- `origin/main` zu Arbeitsbeginn: `4d0ee438bdcf097f7b34bb46154de7e27ba2a8b8`
- Aktualisierung: sicherer Fast-Forward auf `4d0ee43`; keine lokale Datei wurde überschrieben.
- PR #41 ist damit lokal enthalten.
- Vorhandene lokale Änderungen an `storage.py`, `import_preview.py` und zugehörigen Tests blieben erhalten.

Vor der Änderung wurden alle betroffenen bestehenden Code- und Testdateien nach
`C:\Users\chris\Desktop\Portman_Final_Fixes_Backup_20261027_2310` kopiert. Das Backup enthält ein SHA-256-Manifest mit Dateigröße und Prüfsumme für zwölf Dateien.

Es wurden keine zusätzlichen Branches, Pull Requests oder Worktrees erstellt. Es erfolgte kein Push.

## 2. comdirect-Korrekturen

Technische Ursache: Der Wertpapierparser erkannte die Provision, jedoch nicht die historischen Zeilen `Abwickl.entgelt Clearstream` und `Börsenplatzabhäng. Entgelt`. Deshalb waren `fees` und `fee_items` unvollständig, obwohl Cashflow und Kurswert korrekt extrahiert wurden.

Korrektur in `pdf_plugins/comdirect_ertraege.py`:

- Erkennung des Clearstream-Abwicklungsentgelts;
- Erkennung des börsenplatzabhängigen Entgelts;
- weiterhin getrennte Erfassung der Provision;
- Summierung aller Komponenten ohne Doppelzählung;
- Abgleich der Komponenten mit der gedruckten Zeile `Summe Entgelte`;
- Ablehnung des Dokuments, wenn Einzelkomponenten und Entgeltsumme um mehr als einen Cent abweichen.

### Realbeleg-Abnahme

| SHA-Präfix | Kurswert | Gebühren vorher | Gebühren nachher | Cashflow | Ergebnis |
| --- | ---: | ---: | ---: | ---: | --- |
| `64964f227976` | 348,16 | 9,90 | 14,30 | −362,46 | VERIFIED_OK |
| `4182c3634c32` | 217,97 | 9,90 | 12,40 | −230,37 | VERIFIED_OK |
| `3fa4573e005a` | 1.396,20 | 9,90 | 15,30 | −1.411,50 | VERIFIED_OK |
| `338276d54480` | 460,56 | 9,90 | 12,40 | −472,96 | VERIFIED_OK |

Nach der Korrektur erzeugt keiner der vier Belege eine `NET_GROSS_MISMATCH`-Warnung oder einen Parserfehler. Bestehende Layouts mit ausschließlich Provision bleiben durch vorhandene und neue Regressionstests unverändert unterstützt.

## 3. FNZ-Korrektur

Technische Ursache: Die alternative PDF-Textextraktion lieferte `Zahlungsbetragaus Überweisung` ohne Leerzeichen zwischen `Zahlungsbetrag` und `aus`. Das reguläre Ausdrucksmuster verlangte dort mindestens ein Leerzeichen. Der Parser fiel deshalb auf den Anlagebetrag 39,92 zurück.

Korrektur in `pdf_plugins/fnz_finvesto.py`:

- tolerante Erkennung von `Zahlungsbetrag aus Überweisung` mit oder ohne Trennraum;
- keine Änderung der bestehenden wirtschaftlichen Prüfung `Anlagebetrag + Gebühr = Zahlungsbetrag`;
- keine erneute Subtraktion der Gebühr vom Cashflow.

Für beide betroffenen Käufe des SHA `bbba6c6cb39d` gilt nachher:

- Cashflow: −40,00 EUR
- Anlage-/Bruttobetrag: 39,92 EUR
- Gebühr: 0,08 EUR
- Gebührenkomponente: `transaktionsentgelt`
- `NET_GROSS_MISMATCH`: 0
- Parserfehler: 0

## 4. SQLite-Integritätspakete 1 bis 3

Die vorhandenen lokalen Implementierungen wurden nicht neu entwickelt oder ersetzt. Geprüft wurden insbesondere:

- globale Steuerereignis-ID-Konflikte;
- globale Steuerdetail-ID-Konflikte;
- identischer und inhaltlich abweichender Reimport;
- Transaktionskollisionen;
- Behalten, Überspringen und Ersetzen;
- revisionssichere Speicherung;
- Atomarität und Rollback;
- Undo;
- vollständiges Überspringen einer PDF bei nicht zugeordnetem Zielkonto;
- SQLite-Integritätsprüfer mit Schutz vor Produktivnamen, Symlinks, Sidecars und falschen Prüfsummen.

Gezielte Integritätssuite: **170 bestanden, 3 übersprungen, 0 fehlgeschlagen**, 2 bestehende Qt-Deprecation-Warnungen, 19,32 Sekunden.

Alle Datenbanktests verwendeten ausschließlich synthetische temporäre SQLite-Dateien. `data/v09/portfolio.sqlite` und bestehende SQLite-Testdatenbanken wurden nicht geöffnet oder migriert.

## 5. Geänderte Dateien

Vorgesehene Commit-Dateien:

- `pdf_plugins/comdirect_ertraege.py`
- `pdf_plugins/fnz_finvesto.py`
- `src/portfolio_v5/storage.py`
- `src/portman/import_preview.py`
- `tests/test_comdirect_pdf.py`
- `tests/test_import_overview.py`
- `tests/test_pdf_import.py`
- `tests/test_pdf_plugins.py`
- `tests/test_phase_c_fnz.py`
- `tests/test_sqlite_integrity_audit.py`
- `tests/test_tax_identity_conflicts.py`
- `tests/test_transaction_integrity_boundaries.py`
- `tools/sqlite_integrity_audit.py`
- `test_reports/portman_v09_final_fixes_20261027.md`

Nicht vorgesehen sind PDFs, SQLite-Dateien, private Auditverzeichnisse, CSV-Finanzdaten, Backups, `.vscode/settings.json`, ZIP-Dateien und historische lokale Auditwerkzeuge.

## 6. Tests und Ergebnisse

| Prüfung | Ergebnis |
| --- | --- |
| Parser-Nachbartests | 48 bestanden |
| SQLite-/Reimport-/UI-Integrität | 170 bestanden, 3 übersprungen |
| Vier comdirect-Originale | alle wirtschaftlichen Werte korrekt, 0 Parserfehler |
| FNZ-Original | beide Käufe korrekt, 0 Parserfehler |
| `python -m compileall -q src pdf_plugins tools` | bestanden |
| Ruff auf allen vorgesehenen Code-/Testdateien, `--select F` | bestanden |
| Vollständige Suite mit isoliertem Basetemp | 1.222 bestanden, 16 übersprungen, 5 Subtests bestanden, 0 fehlgeschlagen, 386,66 s |

Der exakt aufgerufene Befehl `python -m pytest -q` traf zunächst den bereits bekannten Zugriffsfehler des globalen Windows-Pytest-Tempverzeichnisses. Der Lauf wurde beendet und unverändert mit `--basetemp tmp/pytest_final_full` wiederholt; diese vollständige Suite war grün.

Der exakt verlangte globale Ruff-Lauf über `src pdf_plugins tools` meldet drei bereits vorhandene F401-Befunde ausschließlich in unversionierten historischen Werkzeugen:

- `tools/pdf_parser_audit.py`: ungenutztes `defaultdict`
- `tools/pdf_parser_audit_v1.py`: ungenutztes `defaultdict`
- `tools/pdf_parser_audit_v2.py`: ungenutztes `os`

Diese lokalen historischen Dateien sind nicht Bestandteil des vorgesehenen Commits und wurden nicht verändert. Alle freizugebenden Dateien bestehen Ruff `--select F`.

## 7. Vorher-/Nachher-Vergleich

| Bereich | Vorher | Nachher |
| --- | --- | --- |
| comdirect Gebühren | nur Provision; vier Netto-/Brutto-Warnungen | alle dokumentierten Komponenten; 0 Warnungen |
| comdirect Doppelzählungsschutz | kein Abgleich mit gedruckter Entgeltsumme | Komponenten müssen exakt zur Entgeltsumme passen |
| FNZ Cashflow | −39,92 bei zwei Käufen | −40,00 bei unverändert 39,92 Brutto und 0,08 Gebühr |
| Steuer-ID-Konflikt | lokale Schutzlogik noch nicht zur Commit-Vorschau zusammengeführt | geprüft und zur Aufnahme vorgesehen |
| PDF ohne zuordenbares Zielkonto | einzelne Identität wurde herausgefiltert | vollständige Quelldatei wird übersprungen |
| Vollregression | Abnahmebasis: 1.196 bestanden, Worktree-`.venv`-Fehler | 1.222 bestanden, 0 Fehler im Haupt-Worktree |

## 8. Noch offene Risiken

- Drei Ruff-F401-Befunde in nicht versionierten historischen Auditwerkzeugen; kein Produktcode-Risiko, spätere lokale Konsolidierung empfohlen.
- Zwei Qt-Deprecation-Warnungen in `tax_detail_view.py`; bestehend und funktional ohne Fehler.
- Das globale Windows-Pytest-Tempverzeichnis hat fehlerhafte Berechtigungen; vollständige Tests benötigen derzeit ein explizites `--basetemp`.
- Die Integritäts- und Parseränderungen sind zum Zeitpunkt dieses Berichts noch nicht committed; die Commit-Vorschau muss vor dem Commit bestätigt werden.

## 9. Release-Empfehlung

**READY WITH ACCEPTED WARNINGS**, sobald genau die in Abschnitt 5 aufgeführten Dateien committed sind.

Begründung:

- sämtliche bestätigten comdirect- und FNZ-Wirtschaftsfehler sind auf den Originalbelegen korrigiert;
- keine neuen Parserfehler;
- SQLite-Integritäts- und Reimportprüfungen sind grün;
- vollständige Suite ohne Produktfehler;
- verbleibende Warnungen betreffen ausschließlich lokale historische Werkzeuge, Qt-Deprecation und die globale Pytest-Tempkonfiguration.
