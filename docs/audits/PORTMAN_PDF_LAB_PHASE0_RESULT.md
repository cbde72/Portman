# Portman PDF Lab – Phase 0 Ergebnis

**Branch:** `feat/portman-pdf-lab-phase0-stabilization`  
**Basis:** `codex/transfers-corporate-actions-gui` / `9e52e4e`  
**Ausgangsstand:** `feat/comdirect-document-reference` / `54a1fc3`  
**PR 46:** offen, nicht gemergt  
**PR 47:** offen, als Ausgangsbasis enthalten und korrigiert

## 1. Ausgangsstand und Commits

Vor Beginn wurden Arbeitsbaum, Branches, PRs und die Überschneidungen von PR 46
und PR 47 geprüft. PR 46 wurde nicht ungeprüft integriert. Seine koordinaten-
basierte Layoutausweitung bleibt Phase 2. Phase 0 ändert Portman V09 nicht und
implementiert keine automatische Buchungszuordnung.

| Commit | Inhalt |
|---|---|
| `b6dbc7b` | Referenzlabelvarianten, Referenzstatus und Event-/Child-Evidencevalidierung |
| `b561171` | JSON-Schema 1.6.0, Legacy-Adapter, Registry-Reifegrad und GUI-Kennzeichnung |

Vorhandene untracked Diagnose-/Exportdateien wurden nicht aufgenommen.

## 2. Behobene Auditbefunde

| Audit-ID | Maßnahme | Ergebnis | Testnachweis | Reststatus |
|---|---|---|---|---|
| A-001 | Regex unterstützt vier comdirect-Labelvarianten; Originalwert bleibt unverändert. | Missing/Recognized/Invalid/Ambiguous werden unterschieden. | `test_comdirect.py` | Für comdirect-Hauptparser behoben |
| A-002 | Zentrale Prüfung aller Event-/Child-Evidence-Listen. | Fehlende Verweise werden ERROR-Issues; fremde Dokument-Evidence wird abgewiesen. | `test_phase0_integrity.py` | Behoben |
| A-004 | `HandlerMetadata.readiness` mit vier Statuswerten; Registry und GUI werten ihn aus. | 42 Handler: 22 implementiert, 20 metadata-only. | `test_registry_readiness.py` | Behoben |
| A-011 | Resultatschema 1.6.0 und Legacy-Adapter für 1.5.0. | Alte Resultate bleiben lesbar, neue Felder sind versioniert. | API-/SQLite-Contracttests | Behoben |

## 3. Geänderte Dateien

### Parserbibliothek

- `plugins/comdirect.py`: tolerante Referenzlabels, Originalwert, Status,
  Evidence und Issues für ungültige/mehrdeutige Referenzen.
- `api/events.py`: `bank_reference_status` am `FinancialEvent`.
- `validation/consistency.py`: zentrale Prüfung von Event-, Identity-,
  Bankreferenz-, Trade-, Movement-, Tax-, Fee-, Cost- und Allocation-Evidence.
- `api/results.py`, `api/__init__.py`: Schema 1.6.0 und
  `normalize_result_payload()`.
- `registry/allowlist.py`, `registry/registry.py`: Reifegradvertrag und Lookup.

### PDF Lab

- `storage/repository.py`: Legacy-Resultate werden beim Lesen normalisiert,
  gespeicherte JSON-Daten werden nicht überschrieben.
- `ui/main_window.py`: tatsächlicher Parser-Reifegrad als Tooltip; reine
  metadata-only Plugins erscheinen nicht als produktive Auswahl.

### Tests

- `portman-parsers/tests/unit/test_comdirect.py`
- `portman-parsers/tests/unit/test_phase0_integrity.py`
- `portman-parsers/tests/contract/test_api_contract.py`
- `portman-parsers/tests/contract/test_registry_readiness.py`
- `portman-pdf-lab/tests/unit/test_reference_repository.py`

## 4. DTO-/JSON-Vertrag

Die aktuelle Resultatschema-Version ist **1.6.0**. Legacy-Resultate mit 1.5.0
werden beim Lesen kopiert und um optionale Wertpapieridentitäts-,
Bankreferenz- und Evidence-Felder ergänzt. Die ursprünglichen SQLite-JSON-
Strings werden nicht umgeschrieben. Beträge, Datumswerte und Buchungsrichtungen
bleiben unverändert. Unbekannte zukünftige Schemata werden kontrolliert
abgewiesen.

Der Bankreferenzvertrag lautet:

```text
bank_reference:              Originalwert oder MissingValue
bank_reference_status:       MISSING | RECOGNIZED | INVALID | AMBIGUOUS
bank_reference_evidence_ids: konkrete PDF-Fundstellen
```

`MissingValue.UNKNOWN`, `NOT_FOUND` und `NOT_APPLICABLE` bleiben explizite
serialisierte Werte. Die Verarbeitung verwendet explizite Statusprüfungen und
keine unzuverlässige `isinstance(value, str)`-Unterscheidung.

## 5. Evidence-Regeln

`validate_parsed_document()` prüft zentral:

1. Existenz jeder referenzierten Evidence-ID.
2. Zugehörigkeit zum Resultatdokument.
3. Event-, Security-Identity- und Bankreferenz-Evidence.
4. Trade-, Cash-/SecurityMovement-, Tax-, Fee-, Cost- und Allocation-Evidence.

Fehlende IDs erzeugen `EVIDENCE_REFERENCE_MISSING` mit ERROR. Dokumentfremde
Evidence erzeugt `EVIDENCE_DOCUMENT_MISMATCH`. Fehlende PDF-Quads löschen einen
ansonsten belegten Wert nicht; Seite und Excerpt bleiben gültige Evidence.

## 6. Parser-Reifegrad

| Status | Anzahl | Bedeutung |
|---|---:|---|
| `IMPLEMENTED` | 22 | registriert und ausführbar |
| `PARTIAL` | 0 | Status vorbereitet, aktuell nicht verwendet |
| `METADATA_ONLY` | 20 | registriert, ohne produktiven Parserpfad |
| `DISABLED` | 0 | Status vorbereitet, aktuell nicht verwendet |

Die GUI zeigt nur Plugins mit implementierten/teilweisen Handlern und stellt
den Reifegrad als Tooltip bereit. Automatische und manuelle Auswahl verwenden
dieselben Registry-Metadaten.

## 7. PR-46-/PR-47-Konfliktprüfung

PR 46 und PR 47 überschneiden sich bei `FinancialEvent`, `comdirect.py`,
Wertpapieridentität, Evidence und Tests. Phase 0 basiert auf PR 47, übernimmt
aber PR 46 nicht. Die koordinatenbasierte Layoutanalyse und weitere Identitäts-
änderungen aus PR 46 bleiben Phase 2. PR 46 muss vor Integration gegen Schema
1.6.0, Evidence-Invarianten und Reifegradvertrag geprüft werden.

Keine künstlichen Cash- oder SecurityMovements wurden eingeführt.

## 8. Testergebnisse

Ausgangslauf auf `54a1fc3`:

```text
test_comdirect.py: 16 passed, 2 failed
portman-pdf-lab/tests/unit: 120 passed
```

Die Fehler waren die fehlende Referenzlabelvariante ohne Doppelpunkt und die
falsche Typannahme für `MissingValue`.

Gezielte Phase-0-Tests:

```text
Parser-Referenz/Integrität/Contract: 35 passed
portman-parsers/tests/unit: 108 passed
portman-pdf-lab/tests/unit: 122 passed
```

Akzeptanzlauf:

```text
python -m pytest portman-pdf-lab/tests/unit portman-parsers/tests/unit -vv --tb=short -o faulthandler_timeout=30
230 passed, 0 failed, 0 skipped
```

Keine GUI-Hänger, Fixtureänderungen oder SQLite-Dateisperren wurden beobachtet.

## 9. Verbleibende Risiken

- Bankreferenzen sind weiterhin nur im comdirect-Hauptparser vollständig erfasst;
  parserübergreifende Referenzen gehören in Phase 1.
- PDFium-/Koordinatenanalyse und echte Golden-PDFs gehören weiterhin in Phase 2.
- Es gibt keine physische Migration alter JSON-Dateien; die Lesekompatibilität
  erfolgt über den expliziten In-Memory-Adapter.
- `MissingValue` bleibt aus Kompatibilitätsgründen ein `StrEnum`.
- Worker-/SQLite-Skalierung und dokumentübergreifender Abgleich sind nicht Teil
  von Phase 0.

## 10. Entscheidung für Phase 1/2

Phase 1 kann beginnen: gemeinsames `SecurityIdentity`-Value-Object,
parserübergreifende Bankreferenzen und ein Reconciliation-Kandidatenvertrag
sollten auf den neuen Evidence-/Schema-Invarianten aufbauen.

Phase 2 sollte PR 46 erst nach Prüfung gegen Schema 1.6.0 integrieren und reale,
anonymisierte Golden-PDFs für Rotation, Mehrseitigkeit, Tabellenvarianten sowie
pypdf-/PDFium-Abweichungen verlangen.

**Entscheidung:** Phase 0 ist auf diesem Arbeitsbranch vollständig implementiert,
getestet und technisch mergefähig. Ein automatischer Merge wurde nicht
durchgeführt.
