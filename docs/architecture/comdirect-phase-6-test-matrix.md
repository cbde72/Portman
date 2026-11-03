# Phase 6 – verbindliche comdirect Test-zu-Handler-Matrix

| Handler | Detection | Golden / wirtschaftliche Sollwerte | Cashregel | Status |
|---|---|---|---|---|
| `dividendengutschrift` | `test_all_nine_security_handlers_detect_and_parse` | gemeinsamer Ertragspfad | nur belegtes Settlement | synthetisch |
| `ertragsgutschrift` | eigener Golden-Test | Netto, Steuerkomponenten, Konto, Evidence | tatsächliche IBAN-Gutschrift | synthetisch vollständig |
| `einloesung` | eigener Golden-Test | Bestandabgang und Gutschrift | tatsächliche IBAN-Gutschrift | synthetisch vollständig |
| `kosteninformation_mifid_ii` | Handler-Matrix | informatorisches `CostEvent` | niemals Cash | synthetisch |
| `investment_ausschuettung` | Handler-Matrix | steuerliches Ereignis | kein automatischer Cashflow | synthetisch |
| `dividende_steuer_inland` | Handler-Matrix | Steuerkomponenten | kein automatischer Cashflow | synthetisch |
| `vorabpauschale` | Handler-Matrix und Phase-4-Steuertests | Bemessungswerte | niemals selbst Cash | synthetisch |
| `wertpapierkauf` | eigener Golden-Test | Bestand, Gebühr, Settlementrichtung | negativ; IBAN belegt | synthetisch vollständig |
| `wertpapierverkauf` | eigener Golden-Test | Bestand, Gebühr, Steuer, Settlement | positiv; IBAN belegt | synthetisch vollständig |
| `finanzreport` | Core-Konto- und Snapshot-Tests | Buchungen, Salden, Depotgesamtwert | tatsächliche Kontobuchungen | Core synthetisch; Legacy offen |

Produktive Layoutfreigaben bleiben ohne anonymisierte und bestätigte reale PDFs ausgeschlossen.
