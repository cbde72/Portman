# Portman V09 – OCR-Validierung unter Windows

Prüfdatum: 22.10.2026  
Branch: `fix/windows-ocr-targeted-validation` (Basis `main` @ `55b2eda`)  
Umgebung: Windows 11 (10.0.26220), Projekt-`.venv`
(`C:\Users\chris\Desktop\programming\PortmanNL\.venv\Scripts\python.exe`,
Python 3.13.9, 64 Bit)  
Produktivdatenbank und Original-PDFs wurden nur lesend verwendet und nicht
verändert. Es wurden keine Pakete installiert oder aktualisiert.

## Kurzfazit

- Die installierte OCR-Kette ist mit dem Projekt-`.venv` kompatibel:
  `rapidocr 3.10.0`, `onnxruntime 1.31.0`, `pypdfium2 5.14.0`.
- ONNX rechnet auf der CPU (`CPUExecutionProvider`); die Modelle
  `PP-OCRv6_det_small`, `PP-OCRv6_rec_small` und der Klassifikator liegen
  vollständig im Paket und im Portman-Modellcache.
- Die drei gemeldeten comdirect-Familien LS9AVX, A2H57N und LYX05A werden
  weiterhin korrekt als Kauf erkannt. Bei den beschädigten Januar-Belegen läuft
  OCR nur auf den zwei betroffenen Seiten, nicht auf dem gesamten Dokument.
- Neue, vollständig textliche Varianten derselben Familien lösen **keine** OCR
  mehr aus. Sie werden in ca. 0,4 s geparst, statt unnötig 13–20 s OCR zu
  durchlaufen.
- Ein Sicherheits-Schwellwert (`MIN_SAFE_CONFIDENCE = 0.80`) verhindert, dass
  OCR-Text mit geringer Konfidenz native Buchungstexte ersetzt. Fehlende Pakete
  oder OCR-Fehler erzeugen Warnungen und weiterhin eine Dokumentablage, aber
  keine falschen Buchungen.
- Die vollständige Testsuite läuft durch: **1090 passed, 12 skipped**.
- Der Beleg-Diagnosetest über alle sechs Referenzvarianten bestätigt die
  Qualität: **PASS 20, WARN 0, FAIL 0**.

## Installierte Versionen

| Paket | Installiert | Anforderung `requirements.txt` | Status |
|---|---:|---|---|
| rapidocr | 3.10.0 | `>=3.9.2,<4` | PASS |
| onnxruntime | 1.31.0 | `>=1.23,<2` | PASS |
| pypdfium2 | 5.14.0 | `>=4,<6` | PASS |
| pypdf | 6.19.0 | `>=6,<7` | PASS |
| PyMuPDF | 1.28.2 | `>=1.26,<2` | PASS |
| numpy | 2.3.5 | – | PASS |
| Pillow | 12.3.0 | – | PASS |
| opencv-python-headless | 5.0.0.93 | – | PASS |
| PySide6 | 6.9.2 | `>=6.7,<7` | installiert |

## OCR-Modelle und ONNX

- Modellcache: `%LOCALAPPDATA%\PortMan\rapidocr-models`
- Enthalten: `PP-OCRv6_det_small.onnx`, `PP-OCRv6_rec_small.onnx`,
  `ch_ppocr_mobile_v2.0_cls_mobile.onnx` (zusammen ca. 30,3 MiB)
- Cache und Paketmodelle stimmen in Anzahl und Dateigröße überein.
- Verfügbare Provider: `AzureExecutionProvider`, `CPUExecutionProvider`
- Aktives Gerät: `CPU`
- Engine-Initialisierung: ca. 2,2 s (kalter Prozess)

## Diagnosewerkzeug

Aufruf:

```powershell
.venv\Scripts\python.exe tools\check_ocr_windows.py
.venv\Scripts\python.exe tools\check_ocr_windows.py --pdf <beleg.pdf> --pdf <beleg2.pdf>
.venv\Scripts\python.exe tools\check_ocr_windows.py --pdf-dir <ordner> --json
```

Ausgabeformat:

- `[PASS]`, `[WARN]`, `[FAIL]` je Prüfung mit verständlichem Detail und Hinweis
- Gesamtergebnis ist der schlechteste Einzelstatus
- Exitcode `0` bei PASS/WARN, `1` bei FAIL (mit `--strict` auch bei WARN),
  `2` bei Aufruffehlern
- `--json` liefert dieselben Prüfungen maschinenlesbar
- `--skip-recognition` überspringt den synthetischen OCR-Test

Lokaler Lauf ohne Belege: `PASS 15, WARN 1, FAIL 0` (die WARN weist lediglich
darauf hin, dass keine realen PDFs übergeben wurden).

Synthetischer Erkenner-Test: 82 Zeichen, 4 Boxen, Konfidenz 0,97, ca. 6,1 s,
Treffer `COMDIRECT`, `LS9AVX`, `DE000LS9AVX3`.

## Reale comdirect-Belege

Geprüft wurden die zuvor problematischen Januar-Belege und die neuen,
vollständig textlichen Varianten (nur lesend):

| Familie | Dokument | Seiten | OCR-Seiten | OCR-Zeit | Parser | Min. Konfidenz | Ergebnis |
|---|---|---:|---:|---:|---:|---:|---|
| LS9AVX | Kauf 0,006 St. vom 07.01.2026 (beschädigt) | 3 | 2 | 15,5 s | 1,6 s | 0,84 | PASS |
| A2H57N | Kauf 0,227 St. vom 02.01.2026 (beschädigt) | 3 | 2 | 13,6 s | 2,5 s | 0,84 | PASS |
| LYX05A | Kauf 0,667 St. vom 02.01.2026 (beschädigt) | 3 | 2 | 13,2 s | 2,6 s | 0,84 | PASS |
| LS9AVX | Kauf 0,006 St. vom 01.06.2026 (vollständig) | 3 | 0 | – | 0,4 s | – | PASS |
| A2H57N | Kauf 0,217 St. vom 01.06.2026 (vollständig) | 3 | 0 | – | 0,4 s | – | PASS |
| LYX05A | Kauf 0,579 St. vom 01.06.2026 (vollständig) | 3 | 0 | – | 0,4 s | – | PASS |

Validierte Buchungsdaten (jeweils genau eine Buchung, keine Parserfehler):

| Familie | Dokument | ISIN | Stück | Kurs | Kurswert | Betrag | Art |
|---|---|---:|---:|---:|---:|---:|---|
| LS9AVX | 07.01.2026 | DE000LS9AVX3 | 0,006 | 4152,91 | 24,92 | −24,92 | BUY |
| A2H57N | 02.01.2026 | LU1681041973 | 0,227 | 219,45 | 49,82 | −49,82 | BUY |
| LYX05A | 02.01.2026 | LU2090063673 | 0,667 | 74,92 | 49,97 | −49,97 | BUY |
| LS9AVX | 01.06.2026 | DE000LS9AVX3 | 0,006 | 3662,71 | 21,98 | −21,98 | BUY |
| A2H57N | 01.06.2026 | LU1681041973 | 0,217 | 230,35 | 49,99 | −49,99 | BUY |
| LYX05A | 01.06.2026 | LU2090063673 | 0,579 | 86,27 | 49,95 | −49,95 | BUY |

Laufzeit beim ersten Import der beschädigten Belege inklusive OCR: ca. 15–18 s
pro Beleg. Die beiden beschädigten Seiten dominieren; ein zweiter Parserlauf im
selben Prozess benötigt dank des Seiten-Caches nur noch 2–3 s. Die vollständigen
Varianten brauchen ohne OCR ca. 0,4 s.

Qualitätshinweis: In der A2H57N-Belegbeschreibung kann ein kosmetisches
OCR-Artefakt auftreten (`AIS-ĀM` statt `AIS-AM`). Die validierten Felder ISIN,
Stückzahl, Kurs, Kurswert und Betrag waren davon nicht betroffen. Eine
feldgenaue Nachkorrektur wäre ein separater Plugin-Schritt und wurde bewusst
nicht eingebaut.

## Schadenserkennung

Die beschädigten comdirect-Belege zeigen keine Ersatzzeichen, sondern lange
Wiederholungen eines Buchstabens aus einer defekten Schriftzuordnung
(`zzzz…` bei LS9AVX, `RRRR…` bei A2H57N, `üüü…` bei LYX05A). `pypdf` meldet
zusätzlich ein Layoutproblem, aber auch die neuen, vollständigen Belege lösen
diese Meldung aus. Deshalb entscheidet nicht mehr das Layout-Flag allein,
sondern der erkannte Textschaden:

- kein sichtbarer Text, oder
- mehr als 5 % Ersatzzeichen `U+FFFD`, oder
- mindestens 20 gleiche Buchstaben in Folge (Unicode-Buchstaben; Ziffern und
  Unterstriche zählen nicht).

`layout_review` bleibt als Prüfhinweis in den Warnungen erhalten, löst aber
keine OCR mehr aus.

## Änderungen

### `src/portfolio_v5/pdf_ocr.py`

- Sicherheits-Schwellwert `MIN_SAFE_CONFIDENCE = 0.80` und
  `text_is_reliable(text, confidence, minimum=...)`
- Text- und Regions-Cache pro Seite mit Dateipfad, `mtime_ns`, `ctime_ns`,
  Dateigröße und Seitenindex; `clear_cache()` für Tests/Diagnose
- Leere OCR-Ergebnisse (`None`/keine Textboxen) liefern sauber `('', 0.0)`
- Prüfung des Seitenindex mit klarer Fehlermeldung
- Handlungsfähigere Fehlermeldungen bei fehlenden Paketen/Enginefehlern
- `seed_model_cache` toleriert ein fehlendes Quellverzeichnis
- Cache-Schreiben erfolgt unter demselben Lock wie Rendering und Erkennung

### `src/portfolio_v5/pdf_importer.py`

- Zentrale, testbare Entscheidung `text_is_damaged(...)` und `needs_ocr(...)`
- OCR nur bei fehlendem Text, erkanntem Textschaden oder kurzem Text mit Bild –
  mit Ausnahme des textlichen Finanzreport-Anhangs (Banklogo)
- `layout_review` allein löst keine OCR mehr aus
- `allow_ocr` wird über `ParseContext.options` an Plugins weitergereicht;
  `allow_ocr=False` wird damit auch im comdirect-Plugin wirksam
- OCR-Text ersetzt nativen Text nur noch ab 0,80 Konfidenz
- Unterhalb der Schwelle bleibt der native Text erhalten; Warnung:
  „OCR-Ergebnis mit geringer Sicherheit (…) nicht übernommen“
- Fehlende Pakete/OCR-Fehler erzeugen weiterhin nur Warnungen und eine
  Dokumentablage, keine Buchung

### `pdf_plugins/comdirect_ertraege.py`

- Die gezielte Handels-OCR verwendet denselben Schwellwert
  `MIN_SAFE_CONFIDENCE` statt eines separaten Literals `0.80`
- Die feldgenaue Prüfung bleibt strenger (`OCR_MIN_CONFIDENCE = 0.90`)

### Neue Dateien

- `src/portfolio_v5/ocr_diagnostics.py` – lesende Prüflogik
- `tools/check_ocr_windows.py` – CLI mit PASS/WARN/FAIL und JSON
- `tests/test_pdf_ocr_safety.py` – Fehler-, Paket-, Schwellwert- und
  Weitergabetests
- `tests/test_ocr_diagnostics.py` – Diagnose- und Validierungstests
- `tests/test_ocr_windows_real_pdfs.py` – opt-in-Test mit echten Belegen

## Tests

| Testlauf | Ergebnis |
|---|---|
| Neue OCR-Sicherheits-/Diagnosetests | 17 passed in 4,7 s |
| Gezielte PDF-/OCR-Regression (`test_pdf_import`, comdirect, Plugins, Text, OCR) | 59 passed, 1 skipped in 24,0 s |
| Reale Belege, opt-in (`PORTMAN_REAL_OCR=1`) | 3 passed in 50,4 s |
| Vollständige Suite | 1090 passed, 12 skipped in 354,6 s |

Opt-in-Test:

```powershell
$env:PORTMAN_REAL_OCR='1'
$env:PORTMAN_COMDIRECT_PDF_DIR='C:\Users\chris\Desktop\history\comdirect\2026\Januar'
.venv\Scripts\python.exe -m pytest tests/test_ocr_windows_real_pdfs.py -q
```

Abgedeckte Fehlerszenarien:

- fehlende `rapidocr`-/`onnxruntime`-Pakete
- fehlschlagende Engine-Initialisierung
- leerer oder fehlgeschlagener OCR-Lauf
- OCR-Ergebnis mit 0,42 bzw. 0,10 Konfidenz
- Erhalt des nativen Texts bei geringer OCR-Konfidenz
- `allow_ocr=False` wird an Plugins weitergegeben
- lange Buchstabenfolgen und Ersatzzeichen als Schadenssignale
- ungültige/fehlende Beträge, ISINs und Kurs-/Stückzahlkombinationen in der
  Belegdiagnose

## Empfehlungen

1. Die OCR-Schwelle 0,80 beibehalten; der comdirect-Plugin-Schwellwert 0,90
   bleibt zusätzlich für feldgenaue Prüfungen bestehen.
2. `tools/check_ocr_windows.py` vor einem Release oder nach
   Python-/Paketupdates ausführen, idealerweise mit `--pdf` für die drei
   Referenzbelege.
3. Bei neuen beschädigten Belegvarianten die Diagnose mit `--pdf` nutzen; sie
   zeigt OCR-Seiten, Laufzeit, minimale Konfidenz und Feldfehler getrennt.
4. Eine automatische Modellnachbesserung (z. B. `AIS-ĀM`) nicht in den
   Importpfad aufnehmen, solange die validierten Finanzfelder korrekt sind.
5. Keine Paketinstallation durch Portman selbst; bei fehlenden Abhängigkeiten
   bleibt es bei der Warnung und der Dokumentablage.
