# Portman V09 – Deka Parser P2

## Ergebnis

**PASS MIT HINWEISEN.** Die sieben verbliebenen Deka-Fehlerpfade werden nach
Abgleich mit den Original-PDFs vom Deka-Handler erkannt und ohne Parserfehler
verarbeitet. Der ungecachete Gesamtaudit umfasst 38 physische Dateien und 38
eindeutige SHA-256-Inhalte. Er endet mit 0 Fehlern und 0 neuen Regressionen.

Ausgangscommit: `3cacf36` (`origin/main`), Branch: `fix/deka-parser-p2`.

## Inventar und Baseline

| Kennzahl | Baseline V2 | Nachher |
|---|---:|---:|
| Deka-PDFs | 38 | 38 |
| Eindeutige SHA-256 | 38 | 38 |
| Parserfehler | 7 | 0 |
| Deka-Handler | 28 erfolgreich, 7 fehlerhaft | 35 erfolgreich |
| Generischer Handler | 3 | 3 |
| Cachetreffer | nicht maßgeblich | 0 |
| Neue Parserfehler | 0 | 0 |

Die drei generischen Dokumente (2022–2024) bestanden bereits in der Baseline
und sind nicht Teil der sieben Fehlerpfade. Sie wurden nicht durch eine breitere
Deka-Erkennung künstlich umklassifiziert.

## Originalbelegprüfung der sieben Fehlerpfade

Alle 66 Seiten wurden aus den Original-PDFs gerendert und visuell geprüft.
Jeder Pfad hat einen eigenen SHA-256-Inhalt.

| Dokument | SHA-256 (gekürzt) | Typ | Ursache vorher | Ergebnis nachher |
|---|---|---|---|---|
| `Jahresabschlüsse/DEKA20131231_19013465.pdf` | `02619272da60` | Jahresdepotauszug | OCR-Seite führte zum Gesamtabbruch; altes Ausschüttungslayout | 1 vollständiger Snapshot, 4 Ausschüttungs-/Wiederanlagepaare |
| `Jahresabschlüsse/DEKA20141231_21006142.pdf` | `fd956eb4177e` | Jahresdepotauszug | wie 2013; weiches Trennzeichen im Titel | 1 vollständiger Snapshot, 5 Paare |
| `Jahresabschlüsse/DEKA20161231_25781817.pdf` | `7e9aa007daa4` | Jahresdepotauszug | wiederholter Unterdepotkopf über Seitengrenze überschrieb den ersten Block | 1 vollständiger Snapshot, 4 Paare |
| `Jahresabschlüsse/DEKA20171231_29524960.pdf` | `5dc3f7f351f6` | Jahresdepotauszug | OCR-Seite führte zum Gesamtabbruch | 1 vollständiger Snapshot, 8 Paare |
| `Jahresabschlüsse/DEKA20181231_34032032.pdf` | `8095a950a033` | Quartalsbericht | Seitennummer im Umsatzüberschrift-Layout | 1 vollständiger Snapshot, 4 Paare |
| `Jahresabschlüsse/DEKA20191231_41371929.pdf` | `0a06bb595de5` | Quartalsbericht | Seitennummer im Umsatzüberschrift-Layout | 1 vollständiger Snapshot, 4 Paare |
| `Quartalsbericht/DEKA20200331_44534894.pdf` | `c58b51e71322` | Quartalsbericht | OCR-Seite führte zum Gesamtabbruch | 1 vollständiger Snapshot, 4 Paare |

## Änderungen und Buchungssemantik

- Die pauschale Ablehnung eines ansonsten lesbaren Berichts wegen einzelner
  OCR-Seiten entfällt. Pflichtfelder, Positionssumme und Stichtagsbestände
  werden weiterhin strikt validiert.
- Umsatzüberschriften mit weichem Trennzeichen, Ersatzzeichen und optionaler
  Seitennummer werden erkannt.
- Das historische Layout `Abrechnungsbetrag Ausschüttung` wird zusätzlich zum
  neueren Layout erkannt.
- Umsatzblöcke werden dokumentweit ausgewertet und wiederholte Blöcke desselben
  Unterdepots über Seitengrenzen zusammengeführt.
- Ausschüttung und automatische Wiederanlage bleiben als verknüpftes Paar mit
  identischem Betrag und entgegengesetztem Vorzeichen erhalten. Damit ist der
  Netto-Cashflow jedes Paares null; es entsteht keine erfundene Kontobelastung.
- Reguläre Käufe, Lastschriften, Steuer- und Kosteninformationen werden nicht
  heuristisch in neue wirtschaftliche Buchungen umgedeutet. Nicht unterstützte
  Umsatzzeilen bleiben mit konkreter Warnung sichtbar.
- Quartalsberichte und Jahresdepotauszüge erzeugen einen archivierten
  `BankDocument` und einen bestandsgeprüften Snapshot. Original-PDFs und die
  produktive Datenbank wurden nicht verändert.

## Audit und Qualitätssicherung

Ungecacheter Audit:
`test_reports/pdf_parser_audit/deka_p2_after/` (Parser-Fingerprint
`9bcd330a1c0c6b14`, 38/38 Dateien, 0 Fehler, 23 Warnungen, 15 Info).

Die Warnungen sind transparent: Deka-Steuer-/Kosteninformationen werden nicht
als zusätzliche Buchungen importiert, OCR-Nutzung bleibt prüfpflichtig, und die
drei bestehenden generischen Dokumente bleiben generisch. Der Audit greift auf
keine Portman-Datenbank zu.

Prüfungen:

- `python -m compileall -q src/portman src/portfolio_v5 pdf_plugins`: PASS
- `python -m ruff check src/portman src/portfolio_v5 pdf_plugins --select F`: PASS
- gezielte Deka-/Plugin-Tests: 23 bestanden
- vollständige Suite: 1178 bestanden, 15 übersprungen; ein ausschließlich durch
  den separaten Worktree fehlender `.venv`-Pfad verursachter Test wurde nach
  Einbinden der vorhandenen Projektumgebung separat erneut ausgeführt: 1 bestanden
- Audit: 38 Dateien, 38 eindeutige SHA, 0 Cachetreffer, 0 Parserfehler

## Verbleibende Hinweise und Risiken

OCR-Warnungen sind kein vollständiger fachlicher Freigabeersatz; deshalb bleiben
sie bewusst bestehen. Kosten- und Steuerinformationen innerhalb der Berichte
werden weiterhin nicht strukturiert importiert. Die drei generischen Dokumente
sind ein separater Klassifizierungsfall. Diese Grenzen wurden nicht durch
Fallbacks, Nullwerte oder Ausgleichsbuchungen kaschiert.
