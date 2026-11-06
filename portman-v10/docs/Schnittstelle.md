# Anwendungsschnittstelle 0.2

Die transportneutralen Dataclasses und `ApplicationService` in `src/portman_v10/application/contracts.py` sind der gemeinsame Vertrag für lokale Oberfläche und spätere Adapter. Der zustandsbehaftete `FakeService` in `application/fake_service.py` füllt ihn mit synthetischen Daten für Tests und Oberflächenentwicklung. Kein Vertrag enthält Qt-, SQL-, Parser- oder Dateisystempfadobjekte.

## Eingaben und Ausgaben

| Anwendungsfall | Eingabe | Ausgabe |
|---|---|---|
| Konten lesen/anlegen/ändern/deaktivieren | `AccountInput`, erwartete Konto-Revision (`None` bei Neuanlage), Cursor/Limit; Deaktivierung mit Konto-ID und erwarteter Revision | `Account`, `AccountPage`, Datenrevision; deaktivierte Konten bleiben lesbar |
| Instrument anlegen/lesen/ändern | `InstrumentInput`, erwartete Instrument-Revision; Lesen per stabiler ID, Listen mit Cursor/Limit | `Instrument`, `InstrumentPage` |
| Eröffnungsbestand speichern/lesen | `OpeningBalanceInput` mit Konto, Stichtag und genau einer Geld- oder Mengenposition; Lesen per `opening_id` | `OpeningBalance` mit exaktem Wert, `source_kind="manual"`, `history_scope="starting_balance"` und Kostenbasisstatus |
| PDF ablegen/öffnen | `DocumentUpload` mit Originalnamen, Bytes und optionaler Kontovorgabe / opaque Dokument-ID | `DocumentUploadResult` (einschließlich bereits gespeicherter identischer Bytes) / `DocumentContent` mit Bytes, ohne Pfad |
| Import starten/Job lesen/abbrechen | Dokument-IDs und optionale Kontovorgabe / Job-ID und erwartete Job-Revision | persistenter `ImportJob` (`queued`, `running`, `needs_review`, `failed`, `cancelled`); `completed` bleibt der späteren produktiven Übernahme vorbehalten |
| Vorschau/Konfliktentscheidung | Import-ID / Kandidat, typisierte `ConflictDecision` samt Kandidatenrevision und erwarteter Vorschau-Revision | erneut lesbares `ImportPreview` mit Dokument-/Handleridentität, Paket/API-/Plugin-/Schema-/Aufbereitungsversionen, exakten Bewegungen, erklärenden Komponenten, Datumsarten, Quellen, Warnungen und offenen Zuordnungen |
| Import übernehmen | `CommitImport(import_id, preview_revision, request_id)` | `CommitReport`, Vorgangs-IDs und Datenrevision |
| Rücknahme vorschauen/ausführen | explizite Importauswahl oder `all_imports=True` / Plan-ID, erwartete Planrevision, `request_id` | `RollbackPreview` mit Auswirkungen/Abhängigkeiten / `RollbackReport` |
| Buchungen suchen/Details | `Search` mit Text, Konten, Instrumenten, Typ, Datum, Währung, exaktem Betrag, Status, Cursor/Limit / Vorgangs-ID | stabile `TransactionPage` / vollständiges `TransactionDetail` mit Positionen, Komponenten und Beleg-IDs |
| Dokument öffnen | opaque Dokument-ID | Metadaten und Inhalt als Bytes, nie als Serverpfad |
| gemeinsame Stichtagsübersicht | Stichtag, optionale Kontoauswahl | `Overview` mit Geld- und Mengenlinien sowie gemeinsamer `data_revision` |
| Freistellungsauftrag/Verbrauch | Steuerbezug, Jahr, Gültigkeit, exakter Betrag und erwartete Auftragsrevision / Steuerbezug und Jahr | `ExemptionOrder` / belegte Einzel- und kumulative `TaxConsumption`, genutzt/verfügbar, Quellenstichtag und Vollständigkeit |

## Vertragsregeln

- IDs sind stabile opaque Strings. Erforderliche IDs/Namen dürfen nicht leer sein. Geld und Mengen sind `ExactValue` mit kanonischem endlichem Dezimalstring ohne Exponent: keine Floatwerte, keine feste Stellenbegrenzung, keine stillschweigende Decimal-Kontextrundung. Das entspricht V10-05 unverändert. Interne rationale Kostenanteile sind kein Ersatz für belegte Originalbeträge in Transportfeldern; gerundete Anzeigen gehören nicht zurück in Eingaben.
- Währung und Instrumentzuordnung stehen separat. Bei Geldkonten ist Währung erforderlich; Bestandskonten verwenden Instrumentzuordnung in den Positionen. Optionale/unbekannte Angaben sind `None`, nie eine erfundene Null. Details sind von bestandswirksamen Positionen unterscheidbar. `PreviewItem.disposition="unclassified"` bedeutet ausdrücklich, dass noch kein Dublettenabgleich stattfand.
- Konten verwenden ausschließlich die vereinbarten Paare: Geldkonto mit Giro/Tagesgeld/Festgeld/Verrechnungskonto und Währung; Bestandskonto mit Depot/Kryptokonto ohne Kontowährung. Referenzkonten müssen Geldkonten sein. Kennungen sind durch Typ und Kontext bestimmt; ein Kennungswert ist nicht global eindeutig. Konten mit Historie werden deaktiviert statt gelöscht.
- Stammdaten-Eingaben sind vollständige Datensatzstände (kein PATCH): Bei Änderungen sind alle beizubehaltenden Kennungen erneut mitzusenden; leere Kennungslisten entfernen bisherige Kennungen.
- Instrumente besitzen stabile IDs. Name oder Ticker sind kein Identitätsschlüssel. ISIN/WKN sind eigene optionale Felder; weitere Kennungen benötigen Anbieter, Typ, Kontext (z. B. Börse oder Netzwerk) und Wert.
- Vorschaukontozuordnungen kennzeichnen `exact_identifier`, `user_hint`, `unresolved` oder `conflict`; eine Kontovorgabe ersetzt nie widersprechende Belegdaten. Zuordnungen per Namensähnlichkeit sind ausgeschlossen.
- Eröffnungen erzeugen genau einen expliziten Startbestandsvorgang und keine synthetischen Käufe oder Geldgegenbuchungen. Einstandsdaten und bekannte Kosten bleiben am Eröffnungslot; unbekannte Kosten sind `None`. Die Eröffnung belegt nicht die vollständige frühere Historie. Eintrag und Position schreiben die gemeinsame Datenrevision fort.
- Die Eröffnungs- und Buchungsschreibpfade pflegen den Bestandsindex noch nicht. Sie lassen deshalb vorhandene Indexzeilen auf ihrer älteren Revision stehen; ein Stichtagsleser muss sie als ungültig behandeln. Der aktuelle SQLiteStore liefert keinen Bestand aus diesem Index. Die Anzeige des Eröffnungsstartwerts ist nicht mit vollständiger Kontohistorie gleichzusetzen.
- Datum ist `date` (ISO-Serialisierung dem Transportadapter vorbehalten). Handelsdatum, Buchungstag und Valuta dürfen nicht zusammengezogen werden. Zeitpunkte benötigen später einen expliziten Zeitzonenvertrag.
- `revision` eines Datensatzes, `ImportPreview.revision`, `RollbackPreview.revision` und gemeinsame `data_revision` sind getrennte Zähler. Änderungsbefehle prüfen die erwartete Revision und antworten andernfalls mit `STALE_REVISION`.
- Suche sortiert stabil nach Buchungsdatum absteigend und Vorgangs-ID absteigend. Cursor bindet Offset und Datenrevision; bei Revisionswechsel ist die Suche neu zu beginnen. Standardlimit 100, zulässig 1–500. Deaktivierte Konten bleiben standardmäßig enthalten.
- Schreibbefehle haben `request_id`. Gleiche ID plus gleiche typisierte Eingabe liefert dasselbe Ergebnis mit `replayed=True`; gleiche ID mit abweichender Eingabe ergibt `REQUEST_ID_REUSED`. Produktiv muss der Schlüssel dauerhaft und atomar gespeichert werden.
- Fehler werden als `ApplicationError` plus `ErrorCode` transportiert: `VALIDATION_ERROR`, `STALE_REVISION`, `POSSIBLE_DUPLICATE`, `SOURCE_CONFLICT`, `DEPENDENCY_CONFLICT`, `UNRESOLVED_ACCOUNT`, `NOT_FOUND`, `CANCELLED`, `REQUEST_ID_REUSED`, `INVALID_DOCUMENT`, `ENCRYPTED_DOCUMENT`, `UNSUPPORTED_DOCUMENT`, `INCOMPLETE_RESULT`, `PARSER_ERROR`, `STORAGE_ERROR`, `JOB_INTERRUPTED`. Fehlermeldung dient der Erklärung, nicht als maschinenlesbarer Schlüssel.
- Verbrauchsbelege kennzeichnen `individual` oder `cumulative`. Kumulierte Stände dürfen nicht zu enthaltenen Einzelverbräuchen addiert werden. Fehlender Auftrag, Verbrauch oder verfügbarer Betrag bleibt unbekannt.

## Grenzen der Nachweise

V10-12/13 ergänzen einen begrenzten echten Upload-/Ablage-/Parser-/Vorschaupfad für comdirect Wertpapierkauf, persistente Jobs und normalisierte Vorschauen. Konten/Instrumente werden ausschließlich per exakter kontextbezogener Kennung vorgeschlagen; unaufgelöste Werte bleiben offen. Parserobjekte bleiben in der Infrastruktur. Gebühren-/Steuer-/Trade-Details tragen keine zusätzliche Bewegungswirkung. Parserprozessaufrufe sind nicht sofort unterbrechbar; Abbruch wird danach kooperativ ausgewertet. Jobs, die beim Neustart noch laufen/queued sind, werden als `JOB_INTERRUPTED` fehlgeschlagen markiert und nicht automatisch wiederholt.

Diese Schritte legen keine produktiven Vorgänge/Positionen an. Es gibt noch keinen fachlichen Dublettenabgleich, keine dokumentübergreifende Zusammenführung, keine Übernahme und keine Rücknahme. Vollständiger Bewegungspfad ist nur comdirect Wertpapierkauf; comdirect MiFID-Kosteninformation ist ausdrücklich nur informationsneutral zugelassen. Weitere Handler bleiben auf V10-Seite `unsupported`. Persistenz-/Absturz-/Timeout-Verhalten ist nur mit lokalen temporären Datenbanken getestet, nicht als Produktionsgarantie bewiesen. Keine HTTP-Schicht und keine GUI.
