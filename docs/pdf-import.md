# PDF-Import und Datenmodell

Diese Dokumentation beschreibt den vollständigen PDF-Import von PortmanNL:

1. den **Ablauf** von der Datei bis zum `ImportBatch`,
2. die **Plugin-Schnittstelle** und das **Laden/Auswählen** von Plugins,
3. **alle mitgelieferten PDF-Importer** im Ordner `pdf_plugins/`,
4. die **internen Parser-Helfer**,
5. das **Datenmodell** in `src/portfolio_v5/models.py`.

Für das Erstellen eigener Plugins (TOML und Python) siehe zusätzlich
[`plugin-entwicklung.md`](plugin-entwicklung.md).

---

## 1. Überblick

Der PDF-Import ist zweistufig aufgebaut:

| Ebene | Ort | Aufgabe |
|-------|-----|---------|
| **Kern** | `src/portfolio_v5/pdf_importer.py`, `src/portfolio_v5/pdf_plugins/` | PDF lesen, Text/OCR extrahieren, Plugins laden und auswählen, Ergebnis prüfen |
| **Plugins** | `pdf_plugins/` (Projekt), `~/.portman/pdf_plugins/`, `PORTMAN_PDF_PLUGIN_PATH`, Entry Points | Erkennung (`detect`) und Auswertung (`parse`) je Bank/Dokument |

Ein Plugin liefert immer einen `ImportBatch` (`models.py`). Der Kern fügt nur
Metadaten (Plugin-ID, Version, Handler, Erkennungssicherheit), Warnungen und
abgeleitete Steuerfelder hinzu und prüft das Ergebnis auf Konsistenz.

### Mitgelieferte Plugins

| Plugin-ID | Datei | Bank | Dokumenttypen |
|-----------|-------|------|---------------|
| `baader.pdf` | `pdf_plugins/baader.py` | Baader Bank | Quartalsaufstellung, Wertpapierabrechnung |
| `comdirect.finanzreport` | `pdf_plugins/comdirect_finanzreport.py` | comdirect | Finanzreport (altes und aktuelles Layout) |
| `user.comdirect-ertraege` | `pdf_plugins/comdirect_ertraege.py` | comdirect | Dividendengutschrift, Ertragsgutschrift, Einlösung, Wertpapierabrechnung Kauf, Steuermitteilung Vorabpauschale, MiFID-II-Kosteninformation |
| `user.ing-wertpapiere` | `pdf_plugins/ing_wertpapiere.py` | ING | Dividendengutschrift, Wertpapierabrechnung Kauf, Jahresdepotauszug |
| `user.pbb-direkt` | `pdf_plugins/pbb_direkt.py` | pbb direkt | Kontoauszug (ohne Umsätze), Steueroptimierung zum Jahresende |
| `user.bank-of-scotland-kontoauszug` | `pdf_plugins/bank_of_scotland_kontoauszug.py` | Bank of Scotland (Lloyds Bank GmbH) | Kontoauszug (Tagesgeld, Festgeld) |
| `user.baader-krypto` | `pdf_plugins/baader_krypto.py` | Baader Bank (finanzen.net zero Krypto) | Abrechnung Kauf von Kryptowerten |
| `user.deka-quartalsbericht` | `pdf_plugins/deka_quartalsbericht.py` | Deka Investments | Quartalsbericht (Depotübersicht, Umsatzübersicht) |
| `renault.kontoauszug` | `pdf_plugins/renault_kontoauszug.py` | Renault Bank direkt | Kontoauszug (altes und aktuelles Layout) |
| `generic.kontoauszug` | `pdf_plugins/generic_kontoauszug.py` | Allgemeiner PDF-Import | Kontoauszüge und Dokumentablage (Fallback) |
| `example.bank.python` | `pdf_plugins/example_plugin.py` | Example Bank | Vorlage, wird aber wie ein echtes Plugin geladen |

---

## 2. Ablauf von `parse_pdf`

Einstieg: `portfolio_v5.pdf_importer.parse_pdf(path, *, allow_ocr=True,
preferred_plugin=None, preferred_handler=None, profile_dirs=(),
document_tags=None, plugin_catalog=None)`.

1. **Datei einlesen**: `path.read_bytes()`, SHA-256 → `batch.file_hash`.
2. **Schneller comdirect-Pfad**: `pdf_plugins._comdirect_fast.try_fast_finanzreport`
   nutzt `pymupdf` mit Koordinaten. Bei Erfolg wird der Batch sofort
   zurückgegeben (Plugin-Metadaten werden auf `comdirect.finanzreport` / `2.0` /
   `finanzreport` gesetzt, Sicherheit 100 %). Bei Nicht-Finanzreports, Bildseiten
   oder Fehlern greift der reguläre Weg.
3. **Text lesen** (`pypdf.PdfReader`):
   - verschlüsselte PDFs werden mit leerem Passwort entsperrt, sonst Abbruch mit
     Hinweis auf eine entsperrte Kopie;
   - je Seite `pdf_text.extract_page_text` → `(text, needs_layout_review)`;
   - OCR (`pdf_ocr.ocr_page`) nur, wenn nötig (Layoutproblem, leerer Text, zu
     viele Ersatzzeichen oder kurzer Text mit Bildern) und `allow_ocr=True`.
     Eine rein textliche comdirect-Kontodaten-Übersicht mit Logo wird bewusst
     **nicht** per OCR gelesen.
4. **Dokument modellieren**: `PdfDocument` aus `PdfPage(number, text, used_ocr, confidence)`.
5. **Plugins laden**: `discover_plugins(profile_dirs)`, sofern kein
   `plugin_catalog` mitgegeben wurde. Die Anwendung lädt die Liste einmal je
   Import-Job (`portman/import_worker.py`), damit nicht jede PDF neu lädt.
6. **Plugin auswählen**:
   - mit `preferred_plugin` / `preferred_handler` wird genau dieses Plugin bzw.
     dieser Handler verwendet (sonst Fehler). Ohne `preferred_handler` wird der
     sicherste Treffer gewählt; meldet das Plugin mehrere **unterschiedliche**
     Handler mit weniger als `0.10` Abstand, bricht der Import mit der Bitte ab,
     den Handler ausdrücklich zu wählen;
   - ansonsten `select_plugin(document, plugins, minimum=0.70)`.
7. **Auswerten**: `plugin.parse(document, detection, ParseContext(batch))`.
   Danach setzt der Kern `plugin_id`, `plugin_version`, `plugin_handler`,
   `detection_confidence` und hängt eine Warnung mit Erkennungssicherheit an.
8. **Anreichern**: Für `BankTransaction` läuft `booking_details.enrich_details`,
   für alle Transaktionen `models.enrich_tax_details`.
9. **Prüfen** (`_validate_plugin_batch`):
   - `external_id` je Buchung eindeutig,
   - Konto, Kennung, Datum, Währung und Betrag vollständig,
   - Datum (`date.fromisoformat`) und Betrag (`Decimal`, endlich) gültig,
   - `check_transaction` wird auf jede Buchung angewendet: **harte** Verstöße
     (ungültige/nicht endliche Dezimalzahl, Exponentenschreibweise oder eine
     Vorabpauschale mit Geldbetrag/Steuer/Auswirkung auf den Bestand) brechen
     mit `ValueError` ab; alle übrigen Befunde werden zu `batch.warnings`;
   - Snapshots mit Konto, gültigem Stichtag und endlichen Zahlenfeldern
     (`quantity`, `cost`, `value`, `price`); ungültige ISINs werden nur als
     Warnung vermerkt (Originalwert bleibt erhalten),
   - der Plugin-Batch darf den `file_hash` nicht verändern.
10. **Fallback**: Wird kein Plugin ausgewählt, übernimmt
    `pdf_plugins._generic_document.parse_generic_document`
    (`plugin_id = generic.kontoauszug`, Version `2.0`).
11. **Fehlerbehandlung**: Fehler landen in `batch.errors`.
    - `comdirect Finanzreport` → Batch wird geleert und
      `_finanzreport_help.solution_for(error)` liefert eine Handlungsanleitung.
    - `Baader …` → Batch wird geleert, generische Meldung.
    - sonst generische Meldung „PDF konnte nicht gelesen werden“.

> Konvention für Plugins: Fehler werden als `ValueError` mit einer
> **handlungsorientierten** Meldung geworfen. Fachlich unsichere Ergebnisse
> werden nie stillschweigend importiert, sondern über `batch.warnings` und
> `pdf_booking_evidence[...]['review_required']` zur Prüfung markiert.

---

## 3. Plugin-Schnittstelle

Quelle: `src/portfolio_v5/pdf_plugins/api.py` (öffentlich über
`portfolio_v5.pdf_plugins` importierbar).

```python
from portfolio_v5.pdf_plugins import (Detection, PdfDocument, PdfPage,
                                      ParseContext, PdfImporterPlugin)

class MeinPlugin:
    plugin_id = "meine.bank.python"      # eindeutig, Format domain.name
    bank_name = "Meine Bank"
    version = "1.0.0"

    def detect(self, document: PdfDocument) -> list[Detection]: ...
    def parse(self, document: PdfDocument, detection: Detection,
              context: ParseContext) -> ImportBatch: ...
```

| Typ | Felder | Bedeutung |
|-----|--------|-----------|
| `PdfPage` (frozen) | `number`, `text`, `used_ocr=False`, `confidence=None` | Eine PDF-Seite; `confidence` ist die OCR-Konfidenz |
| `PdfDocument` (frozen) | `path`, `content` (bytes), `file_hash`, `pages: tuple[PdfPage, ...]` | `document.text` verkettet alle Seiten |
| `Detection` (frozen) | `confidence` (0…1), `document_type`, `handler_id`, `reason=''` | Ein erkannter Dokumenttyp |
| `ParseContext` | `batch: ImportBatch`, `options: dict` | `options` wird von der GUI gefüllt (z. B. `allow_ocr`) |
| `PdfImporterPlugin` | Protocol mit `plugin_id`, `bank_name`, `version`, `detect`, `parse` | Struktur-Vertrag, `runtime_checkable` |

Regeln:

- Ein Plugin darf **mehrere** Dokumenttypen anbieten (`document_types` als
  freies Attribut ist Konvention, nicht Teil des Protocols) und in `detect`
  mehrere `Detection`-Einträge zurückgeben.
- `detect` muss bei Nicht-Zutreffen eine leere Liste liefern; Ausnahmen
  markiert der Kern als Ladefehler des Plugins.
- `confidence` muss zwischen 0 und 1 liegen.
- `parse` erhält denselben `ImportBatch` aus `context.batch` und gibt ihn
  (angereichert) zurück.
- Nur GPT-/Text-Extraktion, keine Netzwerkzugriffe.

---

## 4. Plugins laden und auswählen

Quelle: `src/portfolio_v5/pdf_plugins/registry.py`.

### Suchorte (`profile_directories`)

1. `<Projekt>/pdf_plugins`
2. `<aktuelles Arbeitsverzeichnis>/pdf_plugins`
3. `~/.portman/pdf_plugins`
4. Verzeichnisse aus `PORTMAN_PDF_PLUGIN_PATH` (mit `os.pathsep` getrennt)
5. zusätzlich übergebene Verzeichnisse

### Entry Points

Gruppen `portman.pdf_importers` (empfohlen) und `portman.pdf_importer` (Legacy).
Der Entry Point darf eine Klasse oder eine Instanz liefern.

### Dateien im Plugin-Ordner

- `*.toml` → `ConfigPdfPlugin` (deklaratives Profil, siehe Abschnitt 5),
- `*.py` **ohne** führenden Unterstrich → dynamisch importiert; erwartet wird
  eine `plugin`- oder `Plugin`-Variable (Instanz oder Klasse). Dateien mit
  führendem `_` sind private Helfer und werden nicht als Plugin geladen.
  Gesetzte `plugin.source_path` dient nur der Anzeige.

Eine Plugin-ID darf nur einmal vorkommen; Duplikate werden verworfen und als
Fehler gemeldet.

### Auswahl (`select_plugin`)

1. Alle Plugins werden befragt (`detect`).
2. Pro `(plugin_id, handler_id)` zählt nur der **beste** Treffer – meldet ein
   Plugin denselben Handler mehrfach (überlappende Signaturen), ist das ein
   Kandidat und nicht künstliche Mehrdeutigkeit.
3. Sortierung nach `(confidence, plugin_id, handler_id)` absteigend.
4. Der beste Treffer muss `confidence >= 0.70` erreichen, sonst kein Plugin.
5. Liegen die beiden besten **unterschiedlichen** Treffer weniger als `0.10`
   auseinander, wird eine `ValueError` geworfen (Mehrdeutigkeit →
   Erkennungsregeln präzisieren).

Der generische Fallback (`generic.kontoauszug`) meldet bewusst exakt `0.70`,
also die Untergrenze – er greift nur, wenn nichts Spezifischeres passt.

---

## 5. TOML-Profile (`ConfigPdfPlugin`)

Quelle: `src/portfolio_v5/pdf_plugins/config.py`; Vorlage:
`pdf_plugins/example_bank.toml.example`.

Aufbau: `[plugin]` (Pflicht) mit `id`, `bank`, `version`; ein oder mehrere
`[[documents]]` mit `id`, `type`, `required`, `optional`, `confidence` sowie
optionalen Extraktionsfeldern. Erkennung: alle `required`-Muster müssen als
Regex (case-insensitiv, `MULTILINE`) vorkommen; jedes passende `optional`-Muster
erhöht die Konfidenz um `0.05` (max. `+0.20`, Obergrenze `0.99`).

Unterstützte Auswertefelder je Dokument:

| Feld | Wirkung |
|------|---------|
| `account_regex`, `account_prefix` | Konto-/Depotkennung (Named Group `id` oder Gruppe 1) |
| `currency` | Standardwährung (Default `EUR`) |
| `transaction_regex` | Buchungen; Gruppen `date`, `value_date`, `purpose`, `amount`, `currency`, `kind`, `bank_reference`/`reference`/`transaction_reference`/`transaction_id`, `withholding_tax`, `withholding_country`, `withholding_tax_rate`, `tax_rate`, `per_share_amount`, `per_share_currency` |
| `balance_regex`, `balance_category`, `document_date_regex` | Saldo (Gruppen `date`, `amount`), Kategorie (Default `Liquidität`), Belegdatum |
| `snapshot_date_regex`, `position_regex`, `asset_type`, `complete_snapshot` | Depotstand (Gruppen `isin`/`wkn`/`key`, `name`, `quantity`, `cost`, `value`, `currency`, `asset_type`) |
| `dotall` | Regex-`DOTALL` (Default `false`) |

`ConfigPdfPlugin` erzeugt `BankTransaction`-Buchungen mit
`external_id = "<plugin-id>-<handler-id>-<digest[:24]>"`, dazu
`pdf_booking_evidence` je Buchung, optional einen `Balance` oder `Snapshot`
sowie in jedem Fall ein `BankDocument` und `batch.pdf_text`.

Grenzen: keine ISIN-Prüfung, keine Saldenabstimmung, kein OCR-Sonderweg –
für solche Fälle ist ein Python-Plugin nötig. Details zum Erstellen:
[`plugin-entwicklung.md`](plugin-entwicklung.md).

---

## 6. Mitgelieferte Plugins im Detail

Alle Pfade sind relativ zum Projektwurzelverzeichnis.

### 6.1 `baader.pdf` – Baader Bank (Depot)

- **Dateien**: `pdf_plugins/baader.py` (Erkennung/Weiche), `pdf_plugins/_baader_core.py` (Parser).
- **Erkennung** (Sicherheit `1.0`): `Baader Bank`, `Depot-Nr.: <nr>` und
  `Quartalsaufstellung` **oder** `Wertpapierabrechnung:`. Stornobelege werden
  abgelehnt.
- **Handler**: `quartalsaufstellung`, `wertpapierabrechnung`.
- **Ergebnis**:
  - *Quartalsaufstellung* → ein `Snapshot` (vollständig) mit ISIN, Name,
    Stückzahl und Kurswert; Anlageklasse über `importers.asset_type`
    (Aktie/Fonds). Prüfungen: gültige ISIN (Luhn), `Stück × Kurs = Kurswert`,
    Positionssumme gegen ausgewiesenen `Depotwert`, keine doppelten ISINs.
  - *Wertpapierabrechnung* → eine `BankTransaction` mit
    `kind = BUY/SELL` und `affects_cash=False`. Prüfungen: genau ein Handelstag,
    `Stück × Ausführungskurs = Kurswert`, `Kurswert ± (Gebühren + Steuern) =
    Abrechnungsbetrag`, Kauf/Verkauf gegen Lasten/Gunsten.
- **Besonderheiten**: OCR wird abgelehnt (`used_ocr` → Fehler), da der
  Depotbestand sicher sein muss. Warnung: keine Einstandswerte im Depotstand;
  Verkäufe bauen Einstand nach FIFO ab; keine Kontobuchung erzeugt.
- **Tests**: `tests/test_baader_pdf_import.py`, `tests/test_baader_portfolio_history.py`.

### 6.2 `comdirect.finanzreport` – comdirect Finanzreport

- **Dateien**: `pdf_plugins/comdirect_finanzreport.py`,
  `_comdirect_finanzreport_core.py` (aktuelles Layout + Cash),
  `_comdirect_finanzreport_legacy.py` (altes Layout, Zweck zuerst),
  `_comdirect_depot.py` (Depotbestand), `_finanzreport_help.py` (Diagnose),
  `_comdirect_fast.py` (schneller Pfad mit Koordinaten).
- **Erkennung** (Sicherheit `1.0`): `Finanzreport Nr.` **und** `comdirect`.
- **Handler**: `finanzreport` (Kontoumsätze und Depotbestand in einem Beleg).
- **Ergebnis**:
  - Kontobuchungen (`BankTransaction`, `kind = BANK_BOOKING`) je Kontobereich;
    Quartalsabschluss-Zinsen werden über `enrich_interest_closing` zu
    strukturierten `INTEREST`-Buchungen inkl. Brutto, Steuern und Zeitraum;
  - `Balance` für Alter/Neuer Saldo je Konto;
  - bei Depotbestand ein `Snapshot` (`WKN:`-Schlüssel) mit Prüfung gegen
    `Gesamtkurswert` und Kontoübersicht;
  - ein `BankDocument` je zugeordnetem Konto, `batch.account_names`.
- **Besonderheiten**: strikte Saldenprüfung (Anfangssaldo + Buchungen =
  Endsaldo, Kontoübersicht = Endsaldo). Abweichungen brechen ab und liefern über
  `solution_for` einen Handlungsvorschlag. OCR-Seiten werden abgelehnt. Der
  schnelle Pfad (`pymupdf`) füllt zusätzlich Spalten wie Vorgang, Auftraggeber,
  Buchungstext, Gegenkonto (IBAN/BIC) und führt **dieselbe** Abstimmung durch;
  bei Zweifeln fällt er auf den regulären Leser zurück.
- **Tests**: `tests/test_comdirect_pdf.py`, `tests/test_comdirect_simple_import.py`.

### 6.3 `user.comdirect-ertraege` – comdirect Wertpapier-Erträge

- **Datei**: `pdf_plugins/comdirect_ertraege.py`.
- **Erkennung** (nur wenn `comdirect` im Text):
  - `0.99` `kosteninformation_mifid_ii` (`Kosteninformation zum Wertpapiergeschäft`
    mit Datum/Uhrzeit, `WKN:` und ausgewiesenen Gesamtkosten),
  - `0.99` `vorabpauschale` (`Steuerliche Behandlung: Vorabpauschale Ausland…` + Wertpapierzeile),
  - `0.97` `wertpapierkauf` (`Wertpapierkauf` + `Provision: EUR …`),
  - `0.95` je Handler aus `HANDLERS`, sofern eine Abrechnungszeile
    (`SETTLEMENT`) existiert: `dividendengutschrift`, `ertragsgutschrift`
    (beide `DIVIDEND`), `einloesung` (`BANK_BOOKING`).
- **Ergebnis**:
  - `BankTransaction` mit `income_basis='gross'` (der ausgewiesene Betrag ist
    die Gutschrift **vor** Steuern, Steuerabzug steht in der separaten
    Steuermitteilung) für Dividende/Ertrag; `einloesung` als neutrale
    Kontogutschrift;
  - `wertpapierkauf` → `BankTransaction` mit negativem Betrag, `FeeItem`
    `provision` und WKN/ISIN in `booking_text`/`purpose`;
  - `vorabpauschale` → `TaxEvent` mit `advance_tax_base`, Teilfreistellung,
    Steuerbemessungsgrundlage und verbrauchtem Freistellungsauftrag (geprüft:
    Bemessungsgrundlage = Vorabpauschale − Teilfreistellung; verbrauchter
    Freibetrag ≤ Bemessungsgrundlage), kein Cash-Abgang;
  - `kosteninformation_mifid_ii` → ein `CostReport` je PDF mit Dokumentdatum,
    Sparplan-/Referenzkennung, WKN (optional ISIN), Wertpapiername,
    Ausführungsplatz, angenommenem Sparbetrag (monatlich/jährlich), Kauf-,
    Haltedauer- und Verkaufskosten, Gesamtkosten, Renditewirkung,
    Betrachtungszeitraum und Jahresprojektion. Jede gedruckte Kostenzeile bleibt
    als `CostItem` mit Originalbezeichnung, Phase (`kauf`, `haltedauer`,
    `verkauf`), Kategorie (`eigen`/`fremd`/`produkt`) und `annual` erhalten;
  - `SecurityInfo` (inkl. `domicile` aus `Emissionsland`) und `BankDocument`.
- **Besonderheiten**: Alte comdirect-Belege haben defekte Schriften. Fehlt ISIN
  oder Stückzahl, versucht das Plugin lokale OCR (`ocr_holding`) nur mit
  Konfidenz `≥ 0.90` und prüft die Stückzahl gegen `Stück × Satz ≈ Kurswert`.
  Die stabile `external_id` nutzt **native** (nicht per OCR ergänzte) Werte.
  Ergänzte Felder werden in `field_sources` und `review_required` markiert.
  MiFID-II-Kosteninformationen sind **Kostensimulationen und keine ausgeführten
  Transaktionen**: Sie erzeugen keine `BankTransaction`, keinen Cashflow, keine
  Salden-/Depotveränderung und keine tatsächlichen Gebühren. Fehlende
  Kostenzeilen bleiben `None`; gedruckte `0,00` bleiben `0.00`. Die
  Kategoriesummen und die Gesamtkosten werden gegen den Druck geprüft, die
  Summe der Einzelpositionen je Phase gegen den Blockausweis. Die
  Original-PDF wird als `BankDocument` mit der Kennzeichnung
  „MiFID-II-Kosteninformation – keine ausgeführte Transaktion“ archiviert.
  Die Importvorschau zeigt Kostenkomponenten und Summen im Reiter
  `MiFID-II-Kosten`; Doppelklick öffnet das Original. Da die Belege keine
  Depotnummer und keine ISIN enthalten, erfolgt die Depotzuordnung manuell und
  die Wertpapierkennung über `WKN:<wkn>` ohne geratene ISIN.
- **Tests**: `tests/test_comdirect_pdf.py`, `tests/test_pdf_plugins.py`,
  `tests/test_comdirect_mifid_cost.py`.

### 6.4 `user.ing-wertpapiere` – ING

- **Datei**: `pdf_plugins/ing_wertpapiere.py`.
- **Erkennung** (Marker `ING-DiBa` oder `ing.de`, Sicherheit `0.95`):
  - `dividendengutschrift`: `Dividendengutschrift` + `Gesamtbetrag zu Ihren Gunsten`,
  - `kauf`: `Wertpapierabrechnung Kauf…` + `Endbetrag zu Ihren Lasten`,
  - `jahresdepotauszug`: `Jahresdepotauszug` + `Gesamtkurswert` + `zum … abgeschlossene Aufstellung`.
- **Ergebnis**:
  - *Dividende* → `BankTransaction` (`DIVIDEND`) mit Netto-Betrag, Brutto in
    `gross_amount`, `TaxItem('quellensteuer', …)` mit Satz und
    Originalwährung, optional `TaxEvent` (Freistellung / anrechenbare
    Quellensteuer, Depot getrennt vom Cash-Konto);
  - *Kauf* → `Transaction` (`BUY`, Negativbetrag) mit Entgelten als Differenz
    Endbetrag − Kurswert (inkl. Prüfung Kurs × Stückzahl ≈ Kurswert),
    `order_subtype` `sparplan`/`wiederanlage`;
  - *Jahresdepotauszug* → `Snapshot` mit Stückzahl, Kurs, Kurswert,
    Verwahrart/Lagerland; Prüfungen: `Übertrag Kurswert` je Seite,
    `Gesamtkurswert` gesamt, `Anzahl Posten`, keine doppelten ISINs.
- **Besonderheiten**: Je Abrechnung genau **ein** Gesamtbetrag erwartet.
  Dividende/Kauf erlauben OCR (Felder markiert); der Depotauszug verlangt
  eingebetteten Text (fehlende Einstandswerte werden als Warnung gemeldet).
  Automatische Wiederanlage erzeugt keine eigene Kaufbuchung.
- **Tests**: `tests/test_pdf_plugins.py`, `tests/test_income_costs_widget.py`,
  `tests/test_tax_overview.py`.

### 6.5 `user.pbb-direkt` – pbb direkt

- **Datei**: `pdf_plugins/pbb_direkt.py`.
- **Erkennung** (Marker `pbb direkt` oder `Pfandbriefbank`, Sicherheit `0.95`):
  - `steueroptimierung`: `Steueroptimierung zum Jahresende <jahr>` + `Erstattung` + Betrag,
  - `kontoauszug`: nur Auszüge mit `Kontoauszug Nr.`, `Alter Saldo`, `Neuer Saldo` **und** „keine Umsätze“.
- **Ergebnis**:
  - *Steueroptimierung* → `BankTransaction` (Gutschrift) mit
    `purpose` aus den Positionen (Kapitalertragsteuer, Solidaritätszuschlag,
    Kirchensteuer) und ein `TaxEvent` mit `refund_kapst`/`refund_solz`/`refund_kist`;
  - *Kontoauszug* → `AccountStatement` (Zeitraum, Alt-/Neusaldo) und
    `AccountInfo` (Kontotyp, IBAN/BIC/BLZ).
- **Besonderheiten**: Auszüge **mit** Umsätzen werden bewusst dem generischen
  Parser überlassen (Format nicht unterstützt). Fehlt die IBAN, wird sie aus
  BLZ und Kontonummer abgeleitet (ISO 13616) und mit Warnung versehen;
  vorhandene IBANs werden über die Prüfziffer validiert. Prüfungen: Summe der
  Steuerpositionen = Erstattungsbetrag, Saldo unverändert bei „keine Umsätze“.
- **Tests**: `tests/test_pdf_plugins.py`, `tests/test_pdf_account_suggestions.py`.

### 6.6 `user.bank-of-scotland-kontoauszug` – Bank of Scotland

- **Datei**: `pdf_plugins/bank_of_scotland_kontoauszug.py`.
- **Erkennung** (Sicherheit `0.95`): `Bank of Scotland`/`Lloyds Bank GmbH` +
  Buchungstabellenkopf (`Buchungstag Wertstellung Beschreibung Soll Haben`) +
  `RECHNUNGSABSCHLUSS`. Bewusst nicht auf „KONTOAUSZUG“ oder die Absenderzeile
  gestützt, weil pypdf sie im Layout-Modus teils weglässt.
- **Ergebnis**: `BankTransaction` je Buchung (mit Gegen-IBAN/BIC aus der
  Beschreibung), `AccountStatement`, `AccountInfo`, `BankDocument`.
- **Besonderheiten**: Mehrzeilige Buchungstexte werden ober- und unterhalb der
  Datumszeile eingesammelt und bei direkt aufeinanderfolgenden Buchungen in der
  Mitte geteilt. Soll/Haben wird über die größte Lücke der rechten
  Betragskanten je Seite bestimmt; ist das nicht eindeutig, entscheidet der
  Saldenabgleich. Es gelten: Saldenprüfung (Alter Saldo + Haben − Soll = Neuer
  Saldo) und Vergleich mit der Summenzeile.
- **Tests**: `tests/test_pdf_plugins.py`.

### 6.7 `user.baader-krypto` – Baader/finanzen.net zero Krypto

- **Datei**: `pdf_plugins/baader_krypto.py`.
- **Erkennung** (Sicherheit `1.0`): `Abrechnung über den Kauf von Kryptowerten`
  + Belastungszeile (`Zu Lasten Konto … Valuta …`).
- **Handler**: `kauf`.
- **Ergebnis**: `Transaction` (`BUY`, Negativbetrag) mit Entgelten als
  Differenz Belastung − Kurswert, `SecurityInfo` mit
  `identifier_type='ticker'`, `asset_class='Krypto'`, `custody_type='Wallet'`,
  `BankDocument` und Buchungsnachweis. Es wird keine Kontobuchung erzeugt.
- **Besonderheiten**: Krypto hat keine ISIN → das Kürzel dient als Schlüssel.
  Kopf- und Ausführungszeile müssen in Stückzahl **und** Kurs übereinstimmen;
  `Stück × Kurs = Kurswert`; nur EUR. Weicht etwas ab, wird nichts importiert.
  OCR wird unterstützt (Felder markiert), Ergebnisse werden gegengeprüft.
- **Tests**: `tests/test_pdf_plugins.py`, `tests/test_zero_crypto_separation.py`.

### 6.8 `user.deka-quartalsbericht` – Deka Investments

- **Datei**: `pdf_plugins/deka_quartalsbericht.py`.
- **Erkennung** (Sicherheit `0.95`, nur ohne OCR): `Deka` +
  `Quartalsbericht per <datum>` + `Depotübersicht`.
- **Handler**: `quartalsbericht`.
- **Ergebnis**: `Snapshot` je Unterdepot (Schlüssel `<isin>:<unterdepot>`);
  Ausschüttungen aus der Umsatzübersicht zusätzlich als
  `Transaction(kind='dividende')`; `BankDocument`.
- **Besonderheiten**: Die Depotübersicht ist maßgeblich; die Summe der
  Positionen muss `Gesamt in EUR` entsprechen. Anteile stammen je Unterdepot aus
  der Umsatzübersicht (Bestand am Stichtag, Bewertung zum Rücknahmepreis).
  Nicht unterstützte Umsätze werden je Zeile als Warnung ausgelassen;
  `VL-Vertrag:`-Hinweise werden übernommen. Kosteninformationen werden nicht
  importiert. Anteilsbewegungen werden gegen Anfangs-/Endbestand geprüft.
- **Tests**: `tests/test_pdf_plugins.py`.

### 6.9 `renault.kontoauszug` – Renault Bank direkt

- **Datei**: `pdf_plugins/renault_kontoauszug.py` (nutzt den generischen Parser).
- **Erkennung** (Sicherheit `0.98`): `Renault`/`RCI Banque` **oder** die
  BIC-Kennung `RCIDDE3N…` im Kopfbereich über der Buchungstabelle (neuere
  Auszüge tragen die Marke nur als Grafik).
- **Handler**: `kontoauszug`.
- **Ergebnis**: Delegiert an `parse_generic_document`; ist der erkannte
  Dokumenttyp nicht `Kontoauszug`, bricht das Plugin mit Hinweis ab.
- **Besonderheiten**: Für den Ein-Klick-Import über die GUI siehe
  `_renault_import.py` in Abschnitt 7.4.
- **Tests**: `tests/test_renault_pdf_import.py`, `tests/test_pdf_bookings.py`.

### 6.10 `generic.kontoauszug` – allgemeiner Fallback

- **Datei**: `pdf_plugins/generic_kontoauszug.py`.
- **Erkennung**: immer `Detection(0.70, <classify_document>, 'generic', …)`.
- **Ergebnis**: Dokumentklassifizierung, bei `Kontoauszug` konservativ
  erkannte Buchungen, sonst nur Dokumentablage (je erkanntem Konto ein
  `BankDocument`). Es entstehen **keine** Depotpositionen und **keine** Salden;
  alle Buchungen sind prüfpflichtig.
- **Tests**: `tests/test_pdf_import.py`, `tests/test_pdf_bookings.py`,
  `tests/test_import_document_tags.py`.

### 6.11 `example.bank.python` – Vorlage

- **Datei**: `pdf_plugins/example_plugin.py`.
- Demonstriert die Python-Schnittstelle für eine fiktive „Example Bank“
  (`0.90` Kontoauszug, `0.85` Depotstand). Da die Datei im Plugin-Ordner liegt
  und nicht mit `_` beginnt, wird sie **wie ein echtes Plugin geladen** – als
  Vorlage gedacht, in Tests aber nützlich.

---

## 7. Interne Parser-Helfer (`pdf_plugins/_*.py`)

Dateien mit führendem Unterstrich werden nicht als Plugin geladen, sondern von
Plugins und Kern importiert.

### 7.1 `_generic_document.py`

`analyse_pages(pages)` sucht Konto-/Depotkennungen (Labels `IBAN`, `Depot…`,
`Konto…`) und liefert `{Name: Seitenmengen}`; deutsche IBANs werden auf 22
Zeichen gekürzt. `parse_generic_document(document, batch, document_tags=None)`
setzt den Dokumenttyp, parst bei `Kontoauszug` Buchungen, vereinigt
Kontonummern mit passender IBAN (letzte 10 Stellen ohne führende Nullen),
erzeugt Dokumente je Konto und setzt die Warnungen (inkl. „Kontokennungen
können auch Gegenkonten sein“).

### 7.2 `_statement_classification.py`

`classify_document(pages, tags=None)` klassifiziert über `DOCUMENT_TAGS`
(`Kontoauszug`, `Steuerbescheinigung`, `Zinsmitteilung`,
`Wertpapierabrechnung`, `Depotauszug`, `Kosteninformation`,
`Wertpapierinformation`, `Produktinformation`). Eine explizite
Kontoauszugs-Überschrift hat Vorrang vor Erwähnungen im Buchungstext; zuletzt
entscheidet ein Buchungstabellenkopf. `normalized_document_tags` erlaubt
benutzerdefinierte, bereinigte Tags.

### 7.3 `_statement_bookings.py`

Konservative Buchungstabellen-Erkennung für Text-PDFs und OCR:
`statement_end` (Auszugsdatum), `booking_date` (zweistellige Jahre werden gegen
das Auszugsdatum aufgelöst), `owner_from_header` (IBAN-Prüfziffer, sonst
eindeutige Kontonummer), `parse_bookings(pages, identify)`.
Eigenschaften: Soll/Haben über Vorzeichen oder Spaltenposition, Valuta aus
explizitem Feld oder benachbarter Spalte, Saldenabstimmungswarnung,
`external_id = "pdf-booking-<digest>-<n>"`, Anreicherung über
`booking_details.enrich_details`.

### 7.4 `_renault_import.py`

Ein-Schritt-Import für Renault-Kontoauszüge:
`is_renault_statement(text)`, `prepare_renault_batch(repository, original)`,
`import_renault_batches(repository, batches)`.
`prepare_renault_batch` akzeptiert nur geprüfte, ausgeglichene Auszüge, prüft
Buchungsdaten gegen den Auszugszeitraum und ersetzt den vollständigen Zeitraum
(`force_import`, `replace_bank_bookings`). Wird über
`portman/renault_pdf_import.py` (Kompatibilitäts-Reexport) verwendet.

### 7.5 `_baader_core.py`

`is_baader_portfolio(pages)` und `parse_baader_portfolio(batch, pages, content)`
für Baader-Depotbelege (Details in Abschnitt 6.1).

### 7.6 `_comdirect_*` und `_finanzreport_help.py`

- `_comdirect_finanzreport_core.py`: aktuelles Finanzreport-Layout, Cash-Tabellen,
  `enrich_interest_closing` (Abschluss-Zinsen), `is_finanzreport`,
  `flush_pending`.
- `_comdirect_finanzreport_legacy.py`: altes Layout (Zweck zuerst, zwei Daten je
  Zeile); Anfangssalden ohne Datum dienen nur der Prüfung.
- `_comdirect_depot.py`: Depotbestand beider Layouts, Abstimmung gegen
  `Gesamtkurswert` und Depotübersicht.
- `_comdirect_fast.py`: `try_fast_finanzreport` (pymupdf mit Koordinaten),
  `booking_columns` (Spaltenzuordnung) – nutzt dieselbe Abstimmung wie der
  reguläre Weg.
- `_finanzreport_help.py`: `report_date`, `balance_error`, `solution_for`
  (Handlungsanleitungen für Fehlermeldungen).

---

## 8. Fallback, OCR und Sonderfälle

- **Kein Plugin passt** → generischer Import (nur Klassifizierung, Dokumentablage,
  ggf. konservative Buchungen).
- **OCR**: Nur wenn nötig. Seiten mit OCR werden in der Vorschau als
  prüfpflichtig markiert (`review_required`); Plugins, die Bestände sicher
  prüfen müssen (Baader, Deka, ING-Jahresdepot, comdirect-Finanzreport),
  lehnen OCR-Seiten ab.
- **Layoutauffälligkeiten**: Betrifft eine Seite die alternative
  Textextraktion, werden alle Buchungsnachweise dieser Datei als
  prüfpflichtig markiert.
- **Gedrehte/Bildseiten** und passwortgeschützte PDFs: siehe Warnungen/Abbruch
  in Abschnitt 2.
- **Mehrdeutige Erkennung** (`< 0.10` Abstand): Import bricht mit Hinweis ab.

---

## 9. Anwendungsebene (Portman)

| Modul | Aufgabe |
|-------|---------|
| `portfolio_v5/importers.py::parse_file` | Weiche: PDF → `parse_pdf`, sonst CSV/Excel |
| `portman/import_worker.py` | `QThread`; lädt die Plugin-Liste einmal je Job, parst Dateien parallel |
| `portman/gui/import_flow.py` | Import-Aktionen (`import_csv`, `import_baader_pdf`, `import_comdirect_pdf`, `import_renault_pdf`) und Vorschau |
| `portman/import_preview.py`, `comdirect_pdf_preview.py`, `renault_pdf_preview.py` | Prüfansicht mit Buchungsnachweisen und Kontozuordnung |
| `portman/pdf_plugin_dialog.py` | Dialog **Extras → PDF-Import-Plugins** (Plugins, Ordner öffnen, neu laden, Fehler) |
| `portman/import_jobs.py`, `import_v09.py` | Sitzung, Konflikte, atomares Speichern |

Weitere Importwege (Excel/CSV, Krypto-Wallet, Online-Banking) sind nicht Teil
dieser Dokumentation.

---

## 10. Datenmodell `src/portfolio_v5/models.py`

Alle Beträge, Stückzahlen und Kurse werden als **Strings** mit Dezimalpunkt
ohne Exponentenschreibweise gespeichert (Dezimalzahlen statt `float`), Datumsangaben
als ISO-Strings (`YYYY-MM-DD`).

### 10.1 Hilfsfunktionen

| Funktion | Verhalten |
|----------|-----------|
| `text(value)` | `None` → `''`, sonst `str(value).strip()` |
| `norm(value)` | ASCII-normalisierte, kleingeschriebene Zeichenkette nur aus `a-z0-9` (Vergleichsschlüssel) |
| `plain_number(value)` | Formatierung als `Decimal` ohne Exponent (`'f'`) |
| `number(value, *, number_format='auto')` | Kompatibilitäts-Wrapper um `parse_decimal`; `number_format` ∈ `auto`/`de`/`en`/`canonical` |
| `money(value, *, number_format='auto')` | Kompatibilitäts-Wrapper um `parse_money` (Währung `EUR`) |
| `parse_decimal(value, locale='de_DE')` | Zahl mit **explizitem Quell-Locale** parsen (`de_DE`/`en_US`/`canonical`, `auto` nur für eindeutige Formen); leer/`-`/`--` → `None` |
| `parse_money(value, currency='EUR', *, locale='de_DE')` | wie `parse_decimal`, aber Rundung auf die Minor-Units der Währung (Default 2, u. a. `JPY` 0, `BHD`/`JOD`/`KWD`/`OMR`/`TND` 3, `CLF` 4, `BTC` 8, `ETH` 18); entfernt Währungszeichen |
| `parse_quantity(value, precision=12, *, locale='de_DE')` | Stückzahl; mehr als `precision` Nachkommastellen werden **abgelehnt**, nicht gerundet |
| `_number(value, *, number_format)` | interner Parser: entfernt Leerzeichen/`EUR`/`€`/`Stück`/`%`, lehnt uneindeutige einzelne Trennzeichen mit drei Nachkommastellen ab, prüft Tausendergruppen und verlangt endliche Zahlen |
| `correction_number(value)` | für Editor-/Korrekturwerte: ein Punkt ist **nie** Tausendertrennzeichen; Fehlermeldung mit Beispiel |
| `parse_date(value)` | `datetime`/`date` → ISO; sonst erstes `YYYY-MM-DD` oder `DD.MM.YYYY` im Text, sonst `None` |
| `digest(value)` | SHA-256 über kanonisches JSON (sortierte Schlüssel) – Basis der stabilen `external_id`s |
| `valid_isin(value)` | ISO-6166-Form + Luhn-Prüfziffer |

> Hinweis: Neue Importer sollten `parse_decimal`/`parse_money`/`parse_quantity`
> mit explizitem `locale` verwenden; `number`/`money` bleiben als
> kompatible Wrapper für bestehende Aufrufer erhalten.

### 10.2 Buchungsarten (`Kind`) und Mengen

`Kind`: `BANK_BOOKING`, `DIVIDEND`, `DISTRIBUTION`, `BUY`, `SELL`,
`REDEMPTION`, `INTEREST`, `TAX`, `TAX_REFUND`, `ADVANCE_LUMP_SUM`, `TRANSFER`,
`TRANSFER_IN`, `TRANSFER_OUT`, `DEPOSIT`, `WITHDRAWAL`, `FEE`, `REVERSAL`,
`SPLIT`.

- `INCOME_KINDS = {DIVIDEND, DISTRIBUTION, REDEMPTION, INTEREST}`
- `OUTFLOW_KINDS = {BUY}`
- `TRANSACTION_KINDS` = alle `Kind`-Werte
- `REVIEW_STATES = ('offen', 'geprueft', 'verworfen')`

Hinweis: Plugins dürfen umgangssprachliche Werte liefern (z. B. `'dividende'`);
`portfolio_v5.settlement.kind_of`/`portfolio_cash_kind` normalisieren sie
(`dividend|dividende|dividenden → DIVIDEND`, `kauf → BUY`, `verkauf → SELL`)
und klassifizieren reine `BANK_BOOKING`-Texte konservativ nach Wortlaut.

### 10.3 Datenklassen

**TaxItem**: `kind`, `amount`, `rate`, `original_amount`, `original_currency`, `country`
**FeeItem**: `kind`, `amount`
**SecurityInfo**: `key`, `identifier_type='isin'`, `isin`, `wkn`, `symbol`, `name`,
`name_aliases`, `asset_class`, `distribution`, `domicile`, `quote_currency`,
`custody_type`, `custody_country`, `custodian`
**AccountInfo**: `key`, `account_type`, `bank_name`, `iban`, `bic`, `bank_code`,
`account_no`, `customer_no`, `currency='EUR'`, `owners`, `linked_account`
**AccountStatement**: `account`, `statement_no`, `period_start`, `period_end`,
`opening_balance`, `opening_date`, `closing_balance`, `closing_date`,
`currency='EUR'`, `closed`, `external_id`
**TaxEvent**: `external_id`, `account`, `type`, `date`, `tax_year`, `security_ref`,
`quantity`, `currency` sowie Steuerbasen und Erstattungen (`taxable_income`,
`advance_tax_base`, `partial_exemption_amount`, `used_exemption`,
`allowance_before/after`, `withholding_pot_before/after`,
`creditable_withholding`, `per_unit`, `after_partial_exemption`,
`partial_exemption_rate`, `refund_kapst`, `refund_solz`, `refund_kist`,
`reference_no`, `related_transaction_id`)
**CostItem**: `security_ref`, `service_costs`, `inducements`, `product_costs`,
`fx_costs`, `total`; optional `label`, `phase`, `category`, `annual`,
`percentage`, `source_text`
**CostReport**: `external_id`, `account`, `period_start`, `period_end`, `currency`,
`items: list[CostItem]`, `overhead_costs`, `total_costs`, `ongoing_pct`,
`entry_exit_pct`, `avg_capital`, `turnover_volume`; optionale MiFID-II-Felder
`document_date`, `document_time`, `reference`, `sparplan_number`,
`security_name`, `wkn`, `isin`, `execution_venue`, `customer_number`,
`monthly_savings`, `annual_savings`, `purchase_costs`, `holding_costs`,
`sale_costs`, `service_costs`, `service_pct`, `product_costs`, `product_pct`,
`foreign_pct`, `inducements`, `assumed_years`, `holding_years`,
`annual_projection` (JSON, keine SQL-Schemaänderung)
**CorporateEvent**: `external_id`, `account`, `type`, `security_ref`, `event_date`,
`record_date`, `registration_deadline`, `location`, `eligible_quantity`
**Balance**: `period`, `category`, `account`, `value`, `sheet`, `row`, `priority=20`
**BankDocument**: `account`, `external_id`, `title`, `date`, `content_b64`
(`repr=False`), `media_type='application/pdf'`, `document_type`, `bank_name`,
`document_no`, `page_count`, `extraction_method`, `linked_ids`

#### Position

Kern: `key`, `name`, `isin`, `wkn`, `asset_type`, `quantity`, `cost`, `value`,
`currency`, `quote_date`, `row`, `security_ref`, `price`, `price_currency`,
`price_basis`, `sub_account`, `owner`.
Zusatz: `restriction`, `restriction_until`, `cost_per_unit`, `acquisition_date`,
`performance_amount`, `performance_since`, `custody_type`, `custody_country`.
Schlüsselkonvention: ISIN, sonst `WKN:<wkn>`; Krypto nutzt das Kürzel.

#### Snapshot

`account`, `period`, `as_of`, `sheet`, `positions: list[Position]`,
`complete=True`, `date_basis='document'`, `warnings`, `reported_total_value`,
`reported_position_count`, `statement_type`, `statement_no`.
`effective_date` = `as_of` oder `<period>-01` (unbekannter Tag sortiert am
Monatsanfang). `complete=False` bedeutet unvollständiger Bestand.

#### Transaction

Pflicht: `account`, `external_id`, `date`, `kind`, `amount`, `currency`.
Wertfelder: `security`, `quantity`, `fees`, `taxes`, `gross_amount`,
`original_amount`, `original_currency`, `fx_rate`, `price`, `price_currency`,
`per_share_amount`, `per_share_currency`, `tax_items`, `fee_items`.
Datumsfelder: `trade_date`, `value_date`, `pay_date`, `ex_date`, `row`,
`executed_at`, `fiscal_period_start`, `fiscal_period_end`.
Zuordnung/Referenzen: `cash_account`, `depot_account`, `security_ref`,
`group_id`, `related_ids`, `is_reversal`, `reverses_external_id`, `order_id`,
`execution_ref`, `venue`, `order_subtype`, `document_reference`,
`transaction_reference`, `field_sources`, `review_state='offen'`.
Steuern: `solidarity_tax`, `withholding_tax`, `withholding_country`,
`withholding_tax_rate`, `tax_rate`, `advance_tax_base`, `advance_tax_currency`.
Devisen (keyword-only): `fx_from_currency`, `fx_to_currency` – bei gesetztem
Paar gilt explizit `Betrag(from) × fx_rate = Betrag(to)`.
`__post_init__` summiert `taxes`/`fees` aus den Items, leitet
`solidarity_tax` ab, ruft `enrich_tax_details` auf **und** hinterlegt in
`_component_consistency_problems` (kein Dataclass-Feld, daher ohne
Auswirkung auf Konstruktor/Serialisierung) Abweichungen zwischen
Gesamtsteuer/-gebühr und den dokumentierten Einzelpositionen.

#### BankTransaction (Unterklasse von Transaction)

„Unklassifizierte gebuchte Zahlung“ – wird nie automatisch als Wertpapiergeschäft
gedeutet. Zusätzlich: `value_date`, `purpose`, `counterparty`, `bank_reference`,
`operation`, `booking_text`, `counterparty_iban`, `counterparty_bic`, `raw_text`,
`affects_cash=True`, `performance_depot_key`, `gross_income`, `gross_currency`,
`income_basis='net'`.

### 10.4 Regeln, Ableitungen und Prüfungen

**`enrich_tax_details(tx)`** (läuft in `__post_init__` und nach jedem Plugin-Parse):
- `withholding_tax` aus Quellensteuer-Items, `withholding_tax_rate` aus
  dokumentiertem Satz oder berechnet (`Quellensteuer ÷ Bruttobetrag × 100`);
- `withholding_country` nur aus einem ausdrücklich im Beleg genannten
  Quellenstaat (`country` des Steuer-Items) – es wird **nicht** aus der ISIN
  geraten;
- `tax_rate` = Steuern ÷ Bruttobetrag × 100 (Brutto ist `gross_amount`, sonst
  bei passender Währung `gross_income`);
- `transaction_reference` aus `bank_reference` oder `document_reference`.
Jede Ableitung wird in `field_sources` dokumentiert.

**Einzelpositionen statt Summen**: `_documented_component_total` summiert
`tax_items`/`fee_items` und liefert `None`, sobald ein Betrag fehlt/ungültig
ist (fehlende Positionen sind *unbekannt*, nicht null). In `__post_init__`
werden `taxes`/`fees` nur dann aus den Items abgeleitet, wenn die Summe
eindeutig ist. `_component_consistency_problems` vergleicht – nur wenn eine
Detailliste **und** eine Gesamtsumme vorliegen – Gesamt gegen Einzelpositionen
(Toleranz 0,011) und meldet Widersprüche.

**Vorabpauschale**: Die Steuerbasis `advance_tax_base`/`advance_tax_currency`
wird **von den Importern/Plugins** aus dem Beleg gesetzt (kein automatisches
Erraten mehr); sie ist die Steuerbasis, **nicht** gezahlte Steuer.

**`check_transaction(tx)`** liefert eine Liste von Konventionsverstößen (ohne
Daten zu verändern):
- unbekannte `kind`, Exponentenschreibweise in Zahlenfeldern,
  ungültige/nicht endliche Dezimalzahlen (auch in `tax_items`/`fee_items`),
  kein gültiges ISO-Datum (`date.fromisoformat`-Roundtrip), unbekannter
  Prüfstatus;
- Vorzeichen der Zahlungsströme: `BUY`/`TAX`/`FEE` müssen negativ,
  `TAX_REFUND` und die `INCOME_KINDS` positiv sein (jeweils außer bei Storno);
  negative Steuer-/Gebührenbeträge sind nur bei Storno oder `TAX_REFUND`
  zulässig;
- Quellensteuer/Solidaritätszuschlag dürfen die ausgewiesene Gesamtsteuer nicht
  übersteigen;
- Abgleich Gesamtsumme ↔ dokumentierte Einzelpositionen
  (`_component_consistency_problems`);
- Brutto/Netto-Identität, wenn `gross_amount` gesetzt ist:
  - `BUY`: `-(gross + taxes + fees)`,
  - `INCOME_KINDS` (Dividende, Ausschüttung, Einlösung, Zinsen), `SELL`,
    `TAX_REFUND`: `gross − taxes − fees`,
  - `REVERSAL`: Ein- und Auszahlungsidentität (mit/ohne Vorzeichen) werden
    akzeptiert,
  - andere Arten: keine Prüfung;
- Devisen:
  - ohne explizites Paar: `fx_rate` endlich und `> 0`, `original_amount` und
    `original_currency` müssen gesetzt sein, gleiche Währungen erzwingen
    `fx_rate = 1`, und `original_amount ÷ fx_rate ≈ gross_amount`
    (historische Konvention);
  - bei gesetztem `fx_from_currency`/`fx_to_currency`: beide Währungen
    dreistellig und passend zu Original-/Buchungswährung, Kurs erforderlich,
    und `original_amount × fx_rate ≈ gross_amount`;
- `price × quantity ≈ gross_amount` bei Kauf/Verkauf;
- Währung der Vorabpauschale: nur bei gesetzter strukturierter Steuerbasis,
  gültiger Code; `ADVANCE_LUMP_SUM` darf keinen Geldbetrag, keine
  tatsächlichen Steuern und keine Auswirkung auf den Geldbestand
  (`affects_cash`) haben.

### 10.5 ImportBatch

Container eines Importvorgangs. Basis: `path`, `file_hash`, `snapshots`,
`balances`, `transactions`, `warnings`, `errors`, `account_names`,
`account_assignments`, `remember_assignments`.
Erweitert: `source_sheet`, `force_import`, `documents`, `new_accounts`,
`pdf_text`, `pdf_booking_evidence`, `document_type`, `pdf_reviewed`,
`replace_bank_bookings`, `history_end`, `plugin_id`, `plugin_version`,
`plugin_handler`, `detection_confidence` sowie die Modell-Listen `securities`,
`accounts`, `statements`, `tax_events`, `cost_reports`, `events`.

- `pdf_booking_evidence` ist eine **parallel zu `transactions`** geführte Liste
  von Nachweisen (`page`, `line`, `text`, `ocr`, `confidence`, `review_required`).
  Plugins müssen sie synchron halten (der Kern füllt fehlende Einträge auf und
  markiert Layoutfälle als prüfpflichtig).
- `summary()` liefert Zählwerte für die Vorschau.
- Persistenz: `asdict(batch)` beim Speichern einer Sitzung;
  `portman.import_v09.decode_batch` baut daraus wieder echte Dataclass-Objekte
  (`BankTransaction`, wenn Bankfelder vorhanden sind; verschachtelte
  `TaxItem`/`FeeItem`/`CostItem`).

### 10.6 Konventionen

- **Vorzeichen**: Mittelabfluss negativ (Kauf negativ), Gutschriften positiv;
  `fees`/`taxes`/`solidarity_tax` sind positive Abzugsbeträge.
- **Datum**: ISO-Strings; `period` = `YYYY-MM`.
- **Zahlen**: Dezimal-Strings ohne Exponent; Währungen als dreibuchstabige Codes.
- **`external_id`**: stabil und über Neuimporte hinweg gleich (Hashes aus
  Konto, Kennung, Datum, Betrag; Roman-/Mehrfachvorkommen werden durchnummeriert).
- **Herkunft**: `field_sources` belegt je Feld, wie der Wert entstand
  (z. B. `'Berechnet: …'`, `'quellenstaat im Beleg'`, `'ocr:0.94'`,
  `'comdirect Finanzreport · Tabellenspalte'`).

---

## 11. Tests

| Themenbereich | Tests |
|---------------|-------|
| Kern/Plugin-Auswahl, Buchungen | `tests/test_pdf_plugins.py`, `tests/test_pdf_import.py`, `tests/test_pdf_bookings.py` |
| comdirect | `tests/test_comdirect_pdf.py`, `tests/test_comdirect_simple_import.py` |
| Baader | `tests/test_baader_pdf_import.py`, `tests/test_baader_portfolio_history.py` |
| Renault | `tests/test_renault_pdf_import.py` |
| OCR/Text/Seiten | `tests/test_pdf_ocr_cache.py`, `tests/test_pdf_text.py` |
| Konto-Zuordnung/Tags | `tests/test_pdf_account_suggestions.py`, `tests/test_import_document_tags.py` |
| Datenmodell | `tests/test_models_v2.py`, `tests/test_booking_details.py`, `tests/test_settlement.py`, `tests/test_tax_overview.py` |

---

## 12. Weiterführende Dokumente

- [`plugin-entwicklung.md`](plugin-entwicklung.md) – eigene TOML-/Python-Plugins erstellen
- [`pdf_plugins/README.md`](../pdf_plugins/README.md) – Ordner und Plugin-Dialog
- [`depot-verrechnungskonto.md`](depot-verrechnungskonto.md) – Cash- und Depotkonto
- [`portfolio-performance-integration.md`](portfolio-performance-integration.md) – Datenexport/-import
