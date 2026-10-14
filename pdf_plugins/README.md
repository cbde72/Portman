# PDF-Import-Plugin

Dieser Ordner enthält alle PDF-Import-Plugin für PortmanNL.

## Schnellstart

### TOML-Profil (empfohlen für einfache Layouts)

1. Kopieren Sie `example_bank.toml.example` als `.toml`-Datei
2. Passen Sie die Plugin-ID, Bankennamen und Regex-Muster an
3. Speichern Sie die Datei in diesem Ordner
4. Starten Sie die Anwendung neu oder klicken Sie auf "Neu laden" im Plugin-Dialog

### Python-Plugin (für komplexe Logik)

1. Kopieren Sie `example_plugin.py` als `.py`-Datei
2. Implementieren Sie die `detect()` und `parse()` Methoden
3. Exportieren Sie eine `plugin`-Variable mit der Plugin-Instanz
4. Speichern Sie die Datei in diesem Ordner

## Dokumentation

Die vollständige Dokumentation finden Sie in `docs/plugin-entwicklung.md`.

## Plugin-Dialog

Im Hauptfenster unter **Extras → PDF-Import-Plugins** können Sie:
- Alle geladenen Plugins sehen
- Den Plugin-Ordner öffnen
- Plugins neu laden
- Fehlermeldungen bei Ladeproblemen sehen

## Ordner-Struktur

```
pdf_plugins/
  example_bank.toml.example  # TOML-Vorlage
  example_plugin.py          # Python-Vorlage
  README.md                  # Diese Datei
  ...                        # Ihre eigenen Plugins
```
