# Anwendungsschnittstelle 0.1

Getrennte Entwicklung über typisierte DTOs und Protocols. ReadApplication enthält den ersten konkretisierten Lesekern. Die folgenden Schreibverträge sind Spezifikation und noch nicht implementiert; vollständige DTOs werden beim ersten vertikalen Ablauf ergänzt, keine Methoden mit beliebigen Dictionaries.

| Aufruf | Eingabe | Ausgabe |
|---|---|---|
| save_account | Kontodaten, expected_revision | Konto-ID, Revision |
| start_import | Inhaltsstreams, optionale Kontovorgabe | Job-ID |
| get_job/cancel_job | Job-ID | Fortschritt/Abbruchstatus |
| get_import_preview | Import-ID | Kandidaten, neue Vorgänge, Ergänzungen, Konflikte, Revision |
| resolve_import_item | Kandidat, Entscheidung, expected_revision | aktualisierte Vorschau |
| commit_import | Import-ID, Vorschaurevision, request_id | neue/ergänzte IDs, Abschlussbericht |
| preview_rollback | explizite Auswahl oder alle | Plan-ID, Revision, Abhängigkeiten, nötige Entscheidungen |
| execute_rollback | Plan-ID, Revision, Entscheidungen, request_id | Rücknahmebericht |
| get_transaction/get_document | ID | Details bzw. Inhalt, keine Serverpfade |
| list_imports | Filter, Cursor | Importhistorie |
| save_exemption_order | Steuerbezug, Jahr, Gültigkeit, Betrag, Revision | Auftragsrevision |
| get_tax_summary | Steuerbezug, Stichtag | erteilt/genutzt/verfügbar, Quellenstand, Vollständigkeit |

Geld/Menge: Dezimalstrings, nie JSON-Floats. ISO-Datum; Zeitpunkte mit Zeitzone. Null ist unbekannt, nicht null Euro. IDs sind opaque. Kontenübersicht gebündelt mit gemeinsamer Datenrevision. Fehler: VALIDATION_ERROR, STALE_REVISION, POSSIBLE_DUPLICATE, SOURCE_CONFLICT, DEPENDENCY_CONFLICT, UNRESOLVED_ACCOUNT, NOT_FOUND, CANCELLED.

Schreibbefehle verwenden erwartete Revisionen und dauerhafte request_id mit Hash der Eingabe. Gleiche ID mit anderer Eingabe ist ein Konflikt; gleiche Eingabe liefert denselben Abschluss. Nach Timeout Status abfragen. Änderungen an Buchungen, Importherkunft und persistentem Bestandsindex erfolgen atomar. Speicherindex wird revisionsgleich veröffentlicht; Oberfläche verwirft alte Antworten und Cacheeinträge.

Späterer HTTP-Adapter übersetzt ausschließlich. Lokale Aufrufe verwenden dieselben DTOs. Web-Uploads übertragen Inhalte, keine frei wählbaren Serverpfade. FakeService und echter Service müssen dieselbe Vertragssuite bestehen. HTTP, Jobverwaltung, komplette DTOs und Serviceimplementierungen sind ausdrücklich noch ausstehend.
