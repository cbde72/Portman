# Bankabdeckung der Importer

Statuswerte: **unterstützt**, **teilweise**, **nicht unterstützt** und **nicht
verifiziert**. Ohne anonymisierte Fixture und Regressionstest gilt eine
Funktion nicht als nachgewiesen.

| Bank | Dokument / Format | Status nach Phase A | Layout / Tests | Fehlende Felder oder Vorgänge | Benötigte Fixtures / Risiko |
|---|---|---|---|---|---|
| Baader Bank | Quartalsaufstellung PDF | unterstützt | synthetische Parserfälle; Depotwertabgleich | Einstandswerte nicht ausgewiesen | weitere echte anonymisierte Layoutversionen; mittel |
| Baader Bank | Kauf/Verkauf PDF | teilweise | Kauf-/Verkaufs- und Validierungstests; lokale Stichproben | breite Steuer-/FX-/Stornovarianten | weitere anonymisierte Layoutvarianten; hoch |
| Baader Bank | Dividende/Vorabpauschale PDF | unterstützt für belegte Varianten | synthetische Regressionen; lokale Originale geprüft | Steuerkorrektur, abweichende FX-Layouts | anonymisierte Varianten; mittel |
| Baader Bank | Depotübertrag PDF | unterstützt für belegte Variante | mengenbezogener Ein-/Ausgang; lokale Originale | Einstandsdaten nicht ausgewiesen | weitere Varianten; mittel |
| Baader Bank | Jahresdepotauszug PDF | unterstützt für belegte Variante | Depotwertabgleich; lokale Originale | historische Layouts | anonymisierte Varianten; mittel |
| comdirect | Finanzreport PDF | unterstützt | alte/neue Layouts, Salden und Depotwert; fehlende Schlussseite getestet | einzelne historische Layouts | anonymisierte Varianten; mittel |
| comdirect | Ertrag/Kauf/Vorabpauschale PDF | teilweise | vorhandene Pluginregressionen | breite FX-/Steuerfälle | geeignete Belege; hoch |
| comdirect | Kauf/Verkauf PDF, kompaktes Layout | teilweise | `compact-v1`, synthetische Fixture; lokale Kaufbelege gegen Richtung/Beträge geprüft | lokale PDFs können Stückzahlen wegen eingebetteter Schrift nur als `0` liefern und werden dann sicher abgewiesen; separate Steuerbehandlung | OCR-fähige oder anonymisierte textextrahierbare Belege; hoch |
| ING Deutschland | Kauf/Sparplan/Dividende PDF | teilweise | umfangreiche vorhandene Tests | weitere FX-/Layoutvarianten | geeignete Belege; mittel |
| ING Deutschland | Verkauf PDF | unterstützt | `current-v1`; zwei lokale Originalbelege (mit/ohne Gebühr) gegen Stückzahl, Kennung, Konten und Brutto/Netto geprüft | Kapitalmaßnahmen- und Altvarianten | anonymisierte Varianten; mittel |
| ING Deutschland | Vorabpauschale PDF | unterstützt für belegte Variante | `current-v1`, Steuerbasis/Komponenten/Kontobelastung | negative/steuerfreie Varianten | weitere anonymisierte Varianten; mittel |
| ING Deutschland | nachträgliche Verlustverrechnung PDF | teilweise | `current-v1`, Erstattung und Summenkontrolle | Belastung, Kirchensteuer und mehrseitige Varianten nicht mit Fixture verifiziert | passende Belege; hoch |
| ING Deutschland | Jahresdepotauszug PDF | unterstützt | Summe, Positionszahl, Seitenüberträge | gescannte Auszüge | anonymisierte Scans; hoch |
| Deka | Quartals-/Jahresbericht PDF | teilweise | 37 lokale PDFs; Bestandsabgleich; Ausschüttung/Wiederanlage | Verkauf, Fondswechsel, Steuer, Übertrag | anonymisierte Umsatzvarianten; hoch |
| Deka | Bestände/Umsätze XLSX | teilweise | Spezialimport setzt Bestände sicher partiell | Verkauf, Wechsel, Steuer, Kontrollen | anonymisierte Arbeitsmappen; hoch |
| FNZ Bank (ehemals ebase) | Umsatzabrechnung PDF | teilweise | anonymisierte `fnz-current-v1`; 12 lokale Dokumente geprüft | Verkauf, Vorabpauschale, Übertrag, reine Gebührenfälle | passende anonymisierte Belege; hoch |
| FNZ Bank (ehemals ebase) | Quartalsdepotauszug PDF | unterstützt für belegte Variante | Gesamtsummenabgleich, Manipulationstest | weitere Layoutversionen | anonymisierte Varianten; mittel |
| FNZ Bank (ehemals ebase) | historischer ebase-Kontoauszug PDF | nicht verifiziert | lokales Dokument ohne Buchungszeilen | Konto-Umsätze und Saldenfolge | Auszug mit anonymisierten Umsätzen; hoch |
| Renault Bank direkt | Kontoauszug PDF/FinTS | unterstützt für belegte Layouts | 200 lokale PDFs; Zins, KapESt, Soli, Erstattung, Valuta, Storno, Saldo, Überlappung | Kirchensteuer und weitere Korrekturtexte nicht lokal belegt | anonymisierte Varianten; mittel |
| Bank of Scotland | Kontoauszug PDF | unterstützt für belegte Layouts | 75 lokale PDFs; 17 vollständige Auszüge; Zins, Abgeltungssteuer, Soli, Valuta, Mehrseitigkeit | Steuererstattung, Storno und Kirchensteuer nicht lokal belegt | passende anonymisierte Belege; mittel |

FNZ Bank wird weder in Erkennung noch Kontenmodell mit finanzen.net zero
gleichgesetzt. Die eigene Erkennung stützt sich auf verifizierte FNZ-/finvesto-
Merkmale; historische ebase-Kontoumsätze werden ohne Beleg nicht geraten.

Die Phase-A-Änderung betrifft alle sieben Banken gemeinsam: sichere
Teilzuordnung, vollständige/partielle Zustände und konservative
Bestandsvollständigkeit. Neue bankspezifische Dokumenttypen wurden bewusst noch
nicht behauptet. Die Phase-B-Erweiterungen übernehmen keinen Quellcode aus
Portfolio Performance. Verglichen wurden Dokumentmerkmale und erwartete
fachliche Ergebnisse am Commit `805c20dff5d999e987675181b4f1d82f81df10c0`.
