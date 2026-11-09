# Parserauftrag – Bearbeitungsstand

Abgleich mit `PortmanV10/portman-v10/docs/Parserauftrag.md` vom 9. November 2026.
Die Statuspflege liegt im ParserLab; das V10-Repository wurde nicht geändert.

## Abhakliste

- [x] **Arbeitsphase A – Bestandsmatrix:** 42 Handler mit Status, Varianten,
  DTO-/Feldbefund, Evidenz, Testabdeckung, Lücken und Confidence-Grenzen erfasst.
  Ausführbarkeit wird ausdrücklich nicht als Formatfreigabe behandelt.
- [x] **V10-31-Auswahl:** Baader `wertpapierabrechnung` ist als Zweitbeleg für
  einen bestehenden Kauf/Verkauf festgehalten. Der Parserhandler existiert
  bereits; diese Arbeit hat keinen weiteren V10-31-Dokumenttyp implementiert
  oder freigeschaltet.
- [x] **V10-40-Vertrag:** `ExchangeRate` verwendet positive exakte `Decimal`-Werte,
  getrennte Basis-/Kurswährungen, Richtung „1 Basiswährung = Rate Kurswährung“,
  optionale Belegwerte für Datum/Art sowie verpflichtende Evidence. Der JSON-
  kompatible Decoder erhält Dezimalpräzision und weist Floats zurück.
- [x] **V10-52-Vertrag:** Gegenpartei und Zweck sind getrennte Rohtextfelder mit
  je eigener Evidence-Liste und können unabhängig fehlen.
- [x] **Begrenzte Parserextraktion:** Bank of Scotland übernimmt diese Felder
  nur aus ausdrücklich gelabelten Werten derselben Buchungszeile. Unvollständige
  und mehrdeutige Wechselkurse werden nicht ergänzt; Mehrdeutigkeit erzeugt
  einen Hinweis. Nachbarzeilen werden nicht übertragen.
- [x] **Versionen und Rückwärtslesbarkeit:** Paket `0.8.0`, API `0.7`, Ergebnis-
  schema `1.7.0`; Schemata `1.5.0` und `1.6.0` werden additiv normalisiert.
- [x] **Dokumentation und synthetische Prüfungen:** README, Handlermatrix und
  diese Statusliste aktualisiert. Tests decken exakte Dezimalwerte, Richtung,
  Evidenz, Sonderzeichen, lange/repetitive Rohwerte, unabhängiges Fehlen,
  Mehrdeutigkeit und Zeilenisolation ab. Es wurden keine echten Belege
  hinzugefügt.
- [x] **Automatische Prüfung und Wheel:** vollständige Parsersuite bestanden;
  `ruff check src tests` besteht ohne Findings. Das Paket-Wheel wurde gebaut,
  in ein frisches Ziel installiert und importiert; API, Schema und der
  Dezimal-Decoder wurden aus dem installierten Wheel geprüft.
- [x] **Vertragsprüfung:** JSON-Serialisierung/Deserialisierung der neuen
  Wechselkursdaten sowie Evidence, Präzision, Zeilenisolation, Mehrdeutigkeit
  und Rückwärtsnormalisierung sind getestet. Das Parserpaket konfiguriert keinen
  separaten Typprüfer.

## Ausgeführte Prüfkommandos

```powershell
python -m pytest -p no:cacheprovider --basetemp="C:\Users\chris\AppData\Local\Temp\opencode\pt"
python -m ruff check src tests
python -m pip wheel --no-deps --wheel-dir dist .
python -m pip install --no-deps --target <temporärer Zielordner> dist\portman_parsers-0.8.0-py3-none-any.whl
```

Ergebnis: **298 Tests bestanden**, Ruff ohne Findings; das installierte Wheel
importiert als Paket `0.8.0` mit API `0.7` und Schema `1.7.0`.

## Übergabe und Grenze

Der V10-Prüfstand dokumentiert weiterhin den Pin auf Parser `0.7.0` / API `0.6` /
Schema `1.6.0`. Dieser ParserLab-Stand ist `0.8.0` / API `0.7` / Schema `1.7.0`.
Die Integration und Pin-Änderung in V10 bleibt separat und wurde hier nicht
vorgenommen. Die V10-Allowlist, Buchungswirkung und Weboberfläche sind nicht
Bestandteil des Parserauftrags.
