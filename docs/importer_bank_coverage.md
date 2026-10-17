# Bankabdeckung der Importer

Statuswerte: **unterstützt**, **teilweise**, **nicht unterstützt** und **nicht
verifiziert**. Ohne anonymisierte Fixture und Regressionstest gilt eine
Funktion nicht als nachgewiesen.

| Bank | Dokument / Format | Status nach Phase A | Layout / Tests | Fehlende Felder oder Vorgänge | Benötigte Fixtures / Risiko |
|---|---|---|---|---|---|
| Baader Bank | Quartalsaufstellung PDF | unterstützt | synthetische Parserfälle; Depotwertabgleich | Einstandswerte nicht ausgewiesen | weitere echte anonymisierte Layoutversionen; mittel |
| Baader Bank | Kauf/Verkauf PDF | teilweise | Kauf-/Verkaufs- und Validierungstests | breite Steuer-/FX-/Stornovarianten | Dividende, Steuer, Vorabpauschale, Übertrag; hoch |
| comdirect | Finanzreport PDF | unterstützt | alte/neue Layouts, Salden und Depotwert; fehlende Schlussseite getestet | einzelne historische Layouts | anonymisierte Varianten; mittel |
| comdirect | Ertrag/Kauf/Vorabpauschale PDF | teilweise | vorhandene Pluginregressionen | Verkauf, Korrektur, breite FX-/Steuerfälle | geeignete Belege; hoch |
| ING Deutschland | Kauf/Sparplan/Dividende PDF | teilweise | umfangreiche vorhandene Tests | Verkauf, Steuerkorrektur, FX-Varianten | geeignete Belege; hoch |
| ING Deutschland | Jahresdepotauszug PDF | unterstützt | Summe, Positionszahl, Seitenüberträge | gescannte Auszüge | anonymisierte Scans; hoch |
| Deka | Quartalsbericht PDF | teilweise | unvollständige Anteile bleiben `complete=False` | breite Umsätze/Steuern/Wechsel | Belege mit vollständiger Umsatzstrecke; hoch |
| Deka | Bestände/Umsätze XLSX | teilweise | Spezialimport setzt Bestände sicher partiell | Verkauf, Wechsel, Steuer, Kontrollen | anonymisierte Arbeitsmappen; hoch |
| FNZ Bank (ehemals ebase) | ebase-/FNZ-Dokumente | nicht unterstützt | nur historischer Tabellenhinweis, kein belastbarer Parser | gesamter Vorgangsumfang | alte ebase- und neue FNZ-Fixtures zwingend; kritisch |
| Renault Bank direkt | Kontoauszug PDF/FinTS | unterstützt für bekannte Layouts | Saldenabgleich und Überlappungstests | weitere Layouts/Stornos | mehrseitige anonymisierte Auszüge; mittel |
| Bank of Scotland | Kontoauszug PDF | unterstützt für bekannte Layouts | Saldenabgleich | weitere Layouts/Stornos | mehrseitige anonymisierte Auszüge; mittel |

FNZ Bank wird weder in Erkennung noch Kontenmodell mit finanzen.net zero
gleichgesetzt. FNZ/ebase erhält in Phase C eine eigene Quellidentität und erst
nach belegter Layoutanalyse eigene Parserregeln.

Die Phase-A-Änderung betrifft alle sieben Banken gemeinsam: sichere
Teilzuordnung, vollständige/partielle Zustände und konservative
Bestandsvollständigkeit. Neue bankspezifische Dokumenttypen wurden bewusst noch
nicht behauptet.
