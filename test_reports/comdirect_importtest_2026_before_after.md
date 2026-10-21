# comdirect-Importstabilisierung P0 – Vorher/Nachher

## Gesamtergebnis

| Ergebnis | Vorher | Nachher | Differenz |
|---|---:|---:|---:|
| Geprüfte PDFs | 102 | 102 | 0 |
| Erfolgreich | 54 | 57 | +3 |
| Fehlerhaft | 3 | 0 | -3 |
| Generischer Fallback | 45 | 45 | 0 |

Es gab keine Regression bei den zuvor 54 erfolgreichen Dokumenten und keine neuen Fehler.

## Reparierte P0-Belege

| WKN | Status | ISIN | Stück | Kurs | Kurswert | Gebühren | Steuern | Gesamtbelastung |
|---|---|---|---:|---:|---:|---:|---:|---:|
| A111X9 | erfolgreich | IE00BKM4GZ66 | 0.63 | 48.401 | 30.49 | 0.46 | 0.00 | -30.95 |
| A0S9GB | erfolgreich | DE000A0S9GB0 | 0.147 | 121.20 | 17.82 | 0.27 | 0.00 | -18.09 |
| 716460 | erfolgreich | DE0007164600 | 0.221 | 129.52 | 28.62 | 0.43 | 0.00 | -29.05 |

## Ursachen und Korrekturen

- A111X9 und 716460 verwenden `Zum Mischkurs von`; die bestehende Regel akzeptierte nur `Zum Kurs von`.
- A0S9GB verwendet auf der Steuerseite `Geschäftsvorgang Nr.`; die bestehende Regel verlangte `Wertpapierkauf Nr.`. Der Geschäftstyp wird weiterhin nur aus dem expliziten Kauf-/Verkaufsmarker bestimmt.
- Nicht ausgewiesene Steuern bleiben `null`; nur ein tatsächlich gedrucktes `0,00` wird als `0.00` gespeichert.
- Finanzreport-Referenzartefakte `:`, `belastung`, `ntgelt` und reine `Konto <Nummer>`-Werte werden in regulärem und schnellem Extraktionsweg verworfen.

## Null/Unbekannt und Dublettenschutz

- Strukturierte Trades nachher: **41**; davon Steuern nachgewiesen 0,00 EUR: **41**, unbekannt: **0**.
- Identische PDF-Inhalte: **9 Paare**. Für jedes Paar sind Dateihash sowie alle erzeugten Transaktions- und Steuerereignis-IDs identisch. Ein erneuter Import erzeugt damit keine zweite fachliche Identität.
- Keine ungültigen Finanzreport-Referenzfragmente verbleiben.

## Verbleibende Einschränkungen

- 45 PDFs bleiben wie zuvor generisch: 23 Kosteninformationen, 10 Steuerbescheinigungen und 12 unbekannte Dokumente. Das ist unverändert und außerhalb dieses P0-Parserfixes.
- Es wurden keine Datenbanken geöffnet oder verändert und keine Imports gespeichert.

## Testnachweise

- Zieltests für comdirect-Plugin und Finanzreport: 48 bestanden.
- Vollständiger realer PDF-Lauf: 102/102 verarbeitet; 57 erfolgreich, 0 fehlerhaft, 45 generisch.
- Lokale Rohresultate: `test_reports/comdirect_importtest_2026_after.csv` (nicht in den PR aufgenommen,
  da die serialisierten Originalfelder personenbezogene Finanzdaten enthalten können).
