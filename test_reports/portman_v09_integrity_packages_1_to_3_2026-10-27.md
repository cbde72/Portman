# Portman V09 – Ergebnisbericht Integritätspakete 1 bis 3

**Datum:** 27.10.2026  
**Repository:** `C:\Users\chris\Desktop\programming\PortmanNL`  
**Ausgangsstand:** `main`, Commit `1e0a98702cb408750839f67309d3a9829f99d9f6`  
**Status:** lokal umgesetzt und getestet, nicht committed, nicht gepusht

## 1. Zusammenfassung

Die drei aus dem SQLite-Datenintegritätsaudit abgeleiteten Pakete wurden lokal umgesetzt:

1. Schutz vor widersprüchlichen Steuerereignis- und Steuerdetail-Identitäten.
2. Regressionstests für Transaktionskollisionen und die Grenze zwischen Warnung und blockierendem Fehler.
3. Ein strikt lesender, aggregierter SQLite-Abnahmeprüfer für eine ausdrücklich angegebene Testkopie.

Die geprüfte Datenbank `data\v09\portfolio_test.sqlite` bestand alle ausgeführten Integritätsprüfungen. Die produktive Datei `data\v09\portfolio.sqlite` wurde nicht geöffnet oder verändert. Es wurde keine vollständige Pytest-Suite gestartet, um den parallel laufenden PDF-Audit nicht zu belasten.

## 2. Paket 1 – Konflikttests für Steueridentitäten

### Ziel

Bereits gespeicherte Steuer-IDs dürfen nur dann als idempotente Wiederholung behandelt werden, wenn ihre unveränderlichen Quellfakten übereinstimmen. Eine identische ID mit abweichenden Steuerdaten darf nicht still übersprungen werden.

### Umsetzung

Geändert wurde `src/portfolio_v5/storage.py`:

- doppelte oder leere `TaxEvent.external_id` innerhalb eines Batches werden vor der Duplikatabkürzung abgewiesen;
- eine vorhandene Steuerereignis-ID mit abweichenden Quellfakten erzeugt einen expliziten Fehler;
- eine vorhandene Steuerdetail-ID mit abweichenden Quellfakten erzeugt ebenfalls einen expliziten Fehler;
- die ID wird weiterhin global behandelt, sodass dieselbe ID auf einem anderen Konto oder bei einem anderen Institut als Konflikt gilt;
- abgeleitete Verknüpfungsfelder dürfen sich ändern, ohne einen falschen Quellkonflikt auszulösen;
- bei Steuerereignissen ist `related_transaction_id` ein abgeleitetes Abgleichsfeld;
- bei Steuerdetails sind `linked_tax_event_id`, `linked_transaction_id` und `match_status` abgeleitet;
- `source_name` ist nur der lokale CSV-Dateiname und kein unveränderlicher Steuerquellfakt.

Unverändert streng verglichen werden insbesondere Konto, Institut, Steuerart, Steuerwerte und die verlustfrei gespeicherte Originalzeile.

### Neue Tests

Datei: `tests/test_tax_identity_conflicts.py`

- identisches Steuerereignis bleibt idempotent;
- widersprüchlicher Steuerwert unter derselben ID wird abgewiesen;
- dieselbe ID auf einem anderen Konto wird abgewiesen;
- doppelte IDs innerhalb eines Reimports werden abgewiesen;
- identisches Steuerdetail bleibt trotz neuem Linkstatus idempotent;
- abweichende Originalwerte oder Kontenzuordnung unter derselben Detail-ID werden abgewiesen.

### Testergebnis

| Testgruppe | Ergebnis |
| --- | ---: |
| Paket-1- und direkt zugehörige Bestandstests | 8 bestanden |
| Erweiterte Steuer-/Importregressionen | 37 bestanden, 3 Subtests bestanden |
| Fehler | 0 |

Es traten zwei bestehende Qt-Deprecation-Warnungen in `tax_detail_view.py` auf. Sie stehen nicht im Zusammenhang mit der Änderung.

### Bewertung

**VERIFIED_OK:** Der zuvor identifizierte stille Konfliktpfad ist geschlossen. Idempotente Wiederholungen und spätere reine Reconciliation-Änderungen bleiben möglich.

## 3. Paket 2 – Transaktionskollisionen und Validierungsgrenzen

### Ziel

Die Behandlung derselben Transaktions-ID mit abweichenden wirtschaftlichen Feldern sollte explizit getestet werden. Außerdem sollte festgelegt werden, welche Datenprobleme den Import blockieren und welche als sichtbare Warnung übernommen werden.

### Architekturentscheidung

Der Storage darf geänderte Quelldaten bewusst als neue Revision speichern. Dieses Verhalten wird für korrigierte Belege und Parser-Upgrades benötigt. Die Sicherheitsgrenze liegt deshalb im geführten V09-Import:

- eine Kollision wird erkannt;
- ohne Benutzerentscheidung darf sie nicht übernommen werden;
- mögliche Entscheidungen sind Behalten, Überspringen oder begründetes Ersetzen;
- beim Behalten erhält die neue Buchung eine kollisionsfreie V09-ID;
- beim Ersetzen wird die Supersession revisionssicher protokolliert und bleibt rückgängig machbar.

### Neue Tests

Datei: `tests/test_transaction_integrity_boundaries.py`

Kollisionen derselben Konto-/Transaktions-ID werden geprüft bei:

- abweichendem Betrag;
- abweichender Währung;
- abweichendem Buchungstyp;
- abweichender Wertpapierkennung.

Zusätzlich geprüft:

- Import ohne Konfliktentscheidung wird abgewiesen;
- ausdrückliches Behalten benennt die neue ID um und erhält beide Vorgänge;
- positives Kaufvorzeichen, positive Gebühr und negative Steuererstattung bleiben sichtbare Auditwarnungen;
- `NaN`, `Infinity` und Exponentschreibweise sind blockierende Fehler;
- ein blockierter Import hinterlässt weder Import- noch Transaktionszeilen;
- bestehende Replace-, Supersession- und Undo-Pfade bleiben funktionsfähig.

### Testergebnis

| Testgruppe | Ergebnis |
| --- | ---: |
| Neue Paket-2-Tests | 11 bestanden |
| Bestehende Konflikt-, Revisions- und Atomaritätstests | 7 bestanden |
| Fehler | 0 |

### Bewertung

**VERIFIED_OK:** Wirtschaftliche Identitätskollisionen sind im geführten Import entscheidungspflichtig. Die bestehende Revisionsfähigkeit wurde nicht durch eine zu breite Storage-Sperre beschädigt.

**Dokumentierte Grenze:** Fachlich ungewöhnliche, aber historisch mögliche Vorzeichen werden importiert und im Importbericht gewarnt. Strukturell ungültige Zahlen blockieren atomar.

## 4. Paket 3 – Read-only SQLite-Abnahme

### Ziel

Bereitstellung eines Prüfers, der ausschließlich eine ausdrücklich angegebene Testkopie liest, sensible Inhalte nicht ausgibt und eine versehentliche Prüfung der Produktivdatei verhindert.

### Umsetzung

Prüfer: `tools/sqlite_integrity_audit.py`  
Tests: `tests/test_sqlite_integrity_audit.py`

Schutzmaßnahmen:

- `--database` ist zwingend erforderlich;
- `portfolio.sqlite` wird abgewiesen;
- ein zusätzlich angegebener Produktionspfad wird abgewiesen;
- Symlinks werden abgewiesen;
- vorhandene `-wal`, `-shm` oder `-journal`-Sidecars führen zum Abbruch;
- die Verbindung verwendet `mode=ro&immutable=1`;
- ein optional vorgegebener SHA-256 muss vor dem Öffnen übereinstimmen;
- Größe und SHA-256 werden vor und nach der Prüfung verglichen;
- ausgegeben werden ausschließlich aggregierte Zähler, keine Konten, Buchungstexte, IDs oder Payloads.

### Geprüfte Testdatenbank

| Merkmal | Wert |
| --- | --- |
| Pfad | `C:\Users\chris\Desktop\programming\PortmanNL\data\v09\portfolio_test.sqlite` |
| Größe | 176.492.544 Bytes |
| Änderungsdatum | 25.10.2026 09:37:56 |
| SHA-256 | `b88dc1d922fb3d78d1caf91630e5744eccec593a413aa179763b95476cdbbf8a` |
| Hash nach Prüfung | unverändert |

### Abnahmeergebnis

| Prüfung | Ergebnis |
| --- | ---: |
| SQLite `integrity_check` | OK |
| SQLite-Fremdschlüsselfehler | 0 |
| Wiederholte aktive Transaktionsidentitäten | 0 |
| Aktive Transaktionsidentitäten mit abweichendem Content-Hash | 0 |
| Widersprüchliche aktive Steuerereignis-IDs | 0 |
| Widersprüchliche aktive Steuerdetail-IDs | 0 |
| Nicht-endliche aktive Transaktionswerte | 0 |

### Sicherheitstests

| Testgruppe | Ergebnis |
| --- | ---: |
| Ausgeführte Schutztests | 2 bestanden |
| Symlink-Test | 1 übersprungen, da die Windows-Umgebung keinen Test-Symlink zuließ |
| Fehler | 0 |

Die Symlink-Sperre wird vor der Pfadauflösung im Code geprüft; der Skip betrifft nur die Betriebssystemberechtigung des synthetischen Tests.

### Bewertung

**VERIFIED_OK:** Die freigegebene Testkopie zeigt in den implementierten aggregierten Prüfungen keine Integritätsverletzung. Daraus folgt keine Garantie für fachliche Vollständigkeit aller historischen Buchungen, wohl aber ein sauberer Befund für Schema-, Foreign-Key-, Identitäts- und Zahlenkonsistenz im geprüften Umfang.

## 5. Gesamtbewertung

| Bereich | Bewertung | Ergebnis |
| --- | --- | --- |
| Steueridentitäten | VERIFIED_OK | widersprüchliche Payloads werden nicht mehr still verworfen |
| Transaktionskollisionen | VERIFIED_OK | geführter Import verlangt eine ausdrückliche Entscheidung |
| Importatomarität | VERIFIED_OK | harte Validierungsfehler hinterlassen keine Teilimporte |
| Warnungsgrenze | VERIFIED_OK | ungewöhnliche fachliche Werte bleiben nachvollziehbar gewarnt |
| SQLite-Struktur | VERIFIED_OK | Integritätsprüfung erfolgreich |
| Foreign Keys | VERIFIED_OK | keine Verstöße in der Testkopie |
| Aktive ID-Kollisionen | VERIFIED_OK | keine Befunde in der Testkopie |
| Datenschutz | VERIFIED_OK | Prüfbericht enthält nur Aggregate und technische Metadaten |
| Vollständige Regression | OFFEN | aus Rücksicht auf den parallelen PDF-Audit nicht ausgeführt |

## 6. Lokaler Änderungsumfang

| Datei | Status | Zweck |
| --- | --- | --- |
| `src/portfolio_v5/storage.py` | geändert | Steuer-ID-Konflikte explizit abweisen |
| `tests/test_tax_identity_conflicts.py` | neu | Paket-1-Regressionstests |
| `tests/test_transaction_integrity_boundaries.py` | neu | Paket-2-Regressionstests |
| `tools/sqlite_integrity_audit.py` | neu | Read-only-Abnahmeprüfer |
| `tests/test_sqlite_integrity_audit.py` | neu | Paket-3-Sicherheitstests |
| dieser Bericht | neu | konsolidierte Dokumentation |

`git diff --check` meldet keine Formatierungsfehler. Es wurden keine Commits, Pushes oder Pull Requests erstellt.

## 7. Empfohlene nächste Schritte

1. Nach Abschluss des PDF-V3-Audits die vollständige Test-Suite in einer ruhigen Umgebung ausführen.
2. Den Bericht und die fünf Implementierungs-/Testdateien gemeinsam reviewen.
3. Vor einem Commit prüfen, dass keine privaten Testberichte, Original-PDFs, SQLite-Dateien oder sonstigen unversionierten Finanzdaten versehentlich aufgenommen werden.
4. Die produktive Datenbank weiterhin nicht direkt mit dem Abnahmeprüfer öffnen; für Wiederholungen ausschließlich eine ausdrücklich freigegebene konsistente Testkopie verwenden.

## 8. Reproduzierbarer Read-only-Aufruf

```powershell
$db = 'C:\Users\chris\Desktop\programming\PortmanNL\data\v09\portfolio_test.sqlite'
$prod = 'C:\Users\chris\Desktop\programming\PortmanNL\data\v09\portfolio.sqlite'
$hash = (Get-FileHash -LiteralPath $db -Algorithm SHA256).Hash.ToLowerInvariant()

.\.venv\Scripts\python.exe tools\sqlite_integrity_audit.py `
  --database $db `
  --production $prod `
  --expected-sha256 $hash
```

Der Aufruf führt keine Migration, keine Reparatur und keine Änderung der Datenbank durch.
