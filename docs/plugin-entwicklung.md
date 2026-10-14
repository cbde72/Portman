# Plugin-Entwicklung für PortmanNL

Externe Anbieter können PDF-Import-Plugins für Banken und Depotstellen erstellen.
Zwei Ansätze sind verfügbar:

| Ansatz | Wann verwenden | Aufwand |
|--------|---------------|---------|
| **TOML-Profil** | Regelmäßige, tabellarische Layouts (Kontoauszüge, Depotstände) | Niedrig – keine Python-Kenntnisse erforderlich |
| **Python-Plugin** | Komplexe Logik, spezielle Parsing-Anforderungen, Multi-Dokumente | Mittel – Python-Kenntnisse erforderlich |

---

## TOML-Profil erstellen

### Schritt 1: Datei anlegen

Erstellen Sie eine `.toml`-Datei im Ordner `pdf_plugins/` im Projektverzeichnis
oder im Benutzerverzeichnis unter `~/.portman/pdf_plugins/`.

```
pdf_plugins/
  meine_bank.toml
```

### Schritt 2: Grundstruktur

```toml
[plugin]
id = "meine.bank"          # Eindeutige Plugin-ID (Format: domain.name)
bank = "Meine Bank"        # Anzeigename der Bank
version = 1                # Versionsnummer

# Dokumenttyp 1: Kontoauszug
[[documents]]
id = "kontoauszug"                    # Eindeutige Dokument-ID
type = "Meine Bank Kontoauszug"       # Anzeigename des Dokumenttyps
required = ["Meine Bank", "Buchungstag"]  # Pflichtmerkmale (alle müssen vorkommen)
optional = ["IBAN", "Kontostand"]         # Optionale Merkmale (erhöhen Konfidenz)
confidence = 0.80                      # Basis-Konfidenz (0.0–1.0)

# Kontoerkennung
account_regex = "IBAN\\s*:?[ \\t]*(?P<id>[A-Z]{2}[0-9]{2}[A-Z0-9 ]{11,30})"
account_prefix = "Meine Bank "         # Präfix vor der erkannten Kontonummer
currency = "EUR"

# Buchungen
transaction_kind = "BANK_BOOKING"
transaction_regex = "(?m)^(?P<date>\\d{2}\\.\\d{2}\\.\\d{4})[ \\t]+(?P<value_date>\\d{2}\\.\\d{2}\\.\\d{4})[ \\t]+(?P<purpose>.*?)[ \\t]+(?P<amount>[+-]?[0-9.]+,[0-9]{2})$"

# Saldo
balance_regex = "Kontostand(?: zum)?[ \\t]+(?P<date>\\d{2}\\.\\d{2}\\.\\d{4})[ \\t]+(?P<amount>[+-]?[0-9.]+,[0-9]{2})"
balance_category = "Liquidität"

# Dokumentdatum
document_date_regex = "Stand(?: zum)?[ \\t]+(?P<date>\\d{2}\\.\\d{2}\\.\\d{4})"

# Dokumenttyp 2: Depotstand
[[documents]]
id = "depotstand"
type = "Meine Bank Depotstand"
required = ["Meine Bank", "Depotübersicht"]
confidence = 0.85

account_regex = "Depot(?:nummer|-Nr\\.)?[ \\t]*:?[ \\t]*(?P<id>[0-9/-]+)"
snapshot_date_regex = "Bewertung zum[ \\t]+(?P<date>\\d{2}\\.\\d{2}\\.\\d{4})"
position_regex = "(?m)^(?P<isin>[A-Z]{2}[A-Z0-9]{9}[0-9])[ \\t]+(?P<name>.*?)[ \\t]+(?P<quantity>[0-9.,]+)[ \\t]+(?P<value>[0-9.]+,[0-9]{2})[ \\t]+(?P<currency>[A-Z]{3})$"
asset_type = "Sonstiges"
complete_snapshot = true
```

### Schritt 3: Plugin laden

Das Plugin wird automatisch erkannt, wenn die Datei im richtigen Verzeichnis liegt.
Im Hauptfenster unter **Extras → PDF-Import-Plugins** können Sie die Erkennung
prüfen.

### Referenz: Alle TOML-Felder

#### `[plugin]` (Pflicht)

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `id` | string | Ja | Eindeutige Plugin-ID |
| `bank` | string | Ja | Anzeigename der Bank |
| `version` | integer | Nein | Versionsnummer (Standard: 1) |

#### `[[documents]]` (mindestens 1)

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `id` | string | Ja | Eindeutige Dokument-ID |
| `type` | string | Ja | Anzeigename des Dokumenttyps |
| `required` | string[] | Ja | Regex-Merkmale, die alle vorkommen müssen |
| `optional` | string[] | Nein | Regex-Merkmale, die Konfidenz erhöhen |
| `confidence` | float | Nein | Basis-Konfidenz (Standard: 0.75) |
| `account_regex` | string | Nein | Regex mit Named Group `id` |
| `account_prefix` | string | Nein | Präfix vor Kontonummer |
| `currency` | string | Nein | Währung (Standard: EUR) |
| `transaction_kind` | string | Nein | Buchungsart (Standard: BANK_BOOKING) |
| `transaction_regex` | string | Nein | Regex mit Gruppen: date, amount, purpose |
| `balance_regex` | string | Nein | Regex mit Gruppen: date, amount |
| `balance_category` | string | Nein | Saldo-Kategorie |
| `document_date_regex` | string | Nein | Regex mit Gruppe: date |
| `snapshot_date_regex` | string | Nein | Depotstichtag |
| `position_regex` | string | Nein | Regex mit Gruppen: isin/wkn, name, quantity, value, currency |
| `asset_type` | string | Nein | Anlageklasse (Standard: Sonstiges) |
| `complete_snapshot` | bool | Nein | Vollständiger Depotstand (Standard: true) |
| `dotall` | bool | Nein | Regex-DOTALL-Modus (Standard: false) |

---

## Python-Plugin erstellen

### Schnittstelle

```python
from portfolio_v5.pdf_plugins import PdfImporterPlugin, PdfDocument, PdfPage, Detection, ParseContext

class MeinPlugin:
    plugin_id = "meine.bank.python"
    bank_name = "Meine Bank"
    version = "1.0.0"

    def detect(self, document: PdfDocument) -> list[Detection]:
        """Prüft, ob dieses Plugin das Dokument verarbeiten kann."""
        if "Meine Bank" not in document.text:
            return []
        return [Detection(
            confidence=0.90,
            document_type="Meine Bank Kontoauszug",
            handler_id="kontoauszug",
            reason="Bankenname erkannt"
        )]

    def parse(self, document: PdfDocument, detection: Detection, context: ParseContext) -> ImportBatch:
        """Parst das Dokument und gibt einen ImportBatch zurück."""
        batch = context.batch
        # Parsing-Logik hier ...
        return batch
```

### Installation als Python-Paket

Erstellen Sie eine `pyproject.toml` mit Entry Point:

```toml
[project.entry-points."portman.pdf_importers"]
meine_bank = "meine_bank_plugin:Plugin"
```

Installieren Sie das Paket in die Umgebung:

```bash
pip install -e .
```

### Entry-Point-Gruppen

| Gruppe | Beschreibung |
|--------|--------------|
| `portman.pdf_importers` | Standard-Empfohlene Gruppe |
| `portman.pdf_importer` | Legacy-Gruppe (wird ebenfalls geladen) |

### Python-Modul direkt im Plugin-Ordner

Alternativ kann eine `.py`-Datei direkt im `pdf_plugins/` Ordner abgelegt werden.
Die Datei muss eine `plugin` oder `Plugin` Variable mit einer Instanz des Plugins exportieren.

```python
# pdf_plugins/meine_bank_direct.py
class _Plugin:
    plugin_id = "meine.bank.direct"
    bank_name = "Meine Bank"
    version = "1.0"
    def detect(self, document): ...
    def parse(self, document, detection, context): ...

plugin = _Plugin()
```

---

## Erkennungslogik

Das Plugin-System arbeitet mit **Konfidenzwerten** (0.0 bis 1.0):

1. Alle registrierten Plugins werden durchlaufen
2. Jedes Plugin prüft Pflichtmerkmale (`required`)
3. Optionale Merkmale (`optional`) erhöhen die Konfidenz
4. Das Plugin mit der höchsten Konfidenz gewinnt
5. Bei Konfidenz < 0.70 wird das Plugin nicht verwendet
6. Bei weniger als 0.10 Unterschied zwischen den beiden besten Plugins
   wird eine gewählt (Mehrdeutigkeit)

**Tipp:** Verwenden Sie spezifische Pflichtmerkmale wie Bankenname,
IBAN-Format oder typische Dokumentüberschriften, um Fehlurkennungen
zu vermeiden.

---

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| Plugin wird nicht geladen | Datei im richtigen Ordner? `.toml`-Endung? Syntax gültig? |
| Erkennung schlägt fehl | Pflichtmerkmale zu streng? Textlayout anders als erwartet? |
| Parsing liefert keine Daten | Regex-Gruppen benannt? Format der Buchungen geprüft? |
| Mehrdeutigkeits-Fehler | Pflichtmerkmale präzisieren oder Confidence anpassen |

---

## Beispiele im Projekt

Das Projekt enthält mehrere Beispiel-Plugins:

- `pdf_plugins/example_bank.toml.example` – Grundgerüst für TOML-Profile
- `pdf_plugins/generic_kontoauszug.py` – Einfacher TOML-Importer
- `pdf_plugins/baader.py` – Python-Plugin mit komplexem Parsing
- `pdf_plugins/comdirect_finanzreport.py` – Multi-Dokument-Plugin

Weitere Plugins können im Verzeichnis `pdf_plugins/` abgelegt werden
und werden automatisch erkannt.
