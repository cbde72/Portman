# Deka PDF-Audit V3: Ursachenanalyse der drei Timeouts

Datum: 2026-10-27
Branch: `fix/v09-deka-audit-timeouts`

## 1. Umfang und Schutzmaßnahmen

Untersucht wurden ausschließlich die drei im vollständigen V3-Audit als `TIMEOUT` erfassten Deka-PDFs. Die Zuordnung erfolgte über den im Auditbericht gespeicherten SHA-256-Wert und wurde gegen die Quelldatei geprüft. Es wurde weder der vollständige Bestand von 3.736 PDFs erneut verarbeitet noch eine Datenbank geöffnet oder verändert. Original-PDFs und vorhandene Auditberichte blieben unverändert.

Der Bericht enthält keine Konto-, Depot-, Personen- oder Transaktionsdaten. Dateinamen und technische Prüfsummen werden zur reproduzierbaren Identifikation angegeben.

## 2. Betroffene Dateien

| Datei | SHA-256 | Größe | Ergebnis im ursprünglichen Lauf |
| --- | --- | ---: | --- |
| `Deka/Jahresabschlüsse/DEKA20141231_21006142.pdf` | `fd956eb4177e717851880fd81c134fe0cdd0002e31d0812ed326c451847c3220` | 1.747.645 Byte | `TIMEOUT` nach 300,346 s |
| `Deka/Jahresabschlüsse/DEKA20161231_25781817.pdf` | `7e9aa007daa448aeddd56d7621c389a9d240983d8831e4d7c1528f6bf01370af` | 573.823 Byte | `TIMEOUT` nach 300,384 s |
| `Deka/Jahresabschlüsse/DEKA20171231_29524960.pdf` | `5dc3f7f351f6b3f7624bf9aa54049f1535437fbd4690ac8742b783167e55fd97` | 1.030.138 Byte | `TIMEOUT` nach 300,256 s |

## 3. Isolierte Verarbeitungsschritte

Die Verarbeitung wurde stufenweise untersucht: PDF-Öffnen und Textextraktion, OCR-Kandidatenerkennung, OCR, Plugin-Erkennung, Deka-Parser und Ergebnisaufbereitung.

Ohne OCR waren alle übrigen Schritte schnell:

| Datei | Seiten | OCR-Kandidaten | Öffnen/Text/Erkennung/Parser gesamt | Parserergebnis |
| --- | ---: | ---: | ---: | --- |
| 2014 | 13 | 4 (Seiten 2, 6, 7, 8) | ca. 1,25 s | 10 Buchungen, 1 Snapshot, 5 Positionen |
| 2016 | 9 | 4 (Seiten 3–6) | ca. 0,53 s | 8 Buchungen, 1 Snapshot, 4 Positionen |
| 2017 | 10 | 6 (Seiten 3–8) | ca. 0,51 s | 16 Buchungen, 1 Snapshot, 4 Positionen |

Plugin und Handler wurden jeweils korrekt als `user.deka-quartalsbericht` und `quartalsbericht` erkannt. Einzelne OCR-Seiten benötigten dagegen ungefähr 10 bis 29 Sekunden. Weder PDF-Öffnen, eingebettete Textextraktion, Plugin-Erkennung, reguläre Ausdrücke, Deka-Parsing noch Serialisierung zeigten ein Hängen.

## 4. Reproduktion und Ursache

Die drei Dateien wurden einzeln mit dem produktiven V3-Worker und aktivierter OCR verarbeitet. Sie beendeten die Verarbeitung in ungefähr 73 bis 121 Sekunden und damit jeweils unterhalb des 300-Sekunden-Limits. Die PDFs verursachen folglich keinen intrinsischen Endloslauf.

Der vollständige Audit startete bis zu vier Dateien gleichzeitig. OCR läuft dabei in separaten Prozessen; RapidOCR/ONNX nutzt zusätzlich interne Rechen-Threads und rendert die Kandidatenseiten in hoher Auflösung. Bei mehreren gleichzeitig OCR-intensiven PDFs konkurrieren die Prozesse um CPU und Arbeitsspeicher. Die betroffenen Dateien benötigen vier bis sechs OCR-Seiten und überschritten unter dieser Konkurrenz jeweils das äußere 300-Sekunden-Limit.

Die wahrscheinliche und durch die Vergleichsläufe bestätigte Hauptursache ist daher Prozesskonkurrenz bei vier parallelen OCR-Workern, nicht eine fehlerhafte Deka-Parserregel. Eine belastbare historische RSS-Messung des ursprünglichen Laufs liegt nicht vor; die Aussage zur Speicherbelastung ist deshalb eine technische Folgerung aus der OCR-Architektur und dem reproduzierbaren Parallelitätsverhalten, keine nachträglich gemessene Spitzenbelegung.

## 5. Minimale Korrektur

`tools/pdf_audit_v3.py` bestimmt die Workerzahl nun zentral:

- Audit mit OCR: höchstens 2 parallele Worker
- Audit ohne OCR: weiterhin höchstens 4 parallele Worker
- auf Systemen mit nur einer CPU: 1 Worker

Es wurden keine Bankparser-, Import-, OCR- oder PDF-Inhalte geändert. Ein zunächst untersuchtes Überspringen einzelner OCR-Seiten wurde verworfen, weil dies bei künftigen Dokumentvarianten relevante Inhalte auslassen könnte. Die Korrektur reduziert ausschließlich die parallele Ressourcenbelastung des Audit-Werkzeugs.

## 6. Ergebnis nach der Korrektur

Die drei Zieldateien wurden mit derselben neuen Zwei-Worker-Konfiguration und einem Timeout von 300 Sekunden geprüft:

| Datei | Dauer | Status | Buchungen | Snapshots | Positionen | Fehler | OCR-Seiten |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 2014 | 123,618 s | `WARNING` | 10 | 1 | 5 | 0 | 4 |
| 2016 | 124,593 s | `WARNING` | 8 | 1 | 4 | 0 | 4 |
| 2017 | 115,159 s | `WARNING` | 16 | 1 | 4 | 0 | 6 |

Alle drei Läufe endeten deutlich vor 300 Sekunden. Die Warncodes waren `DIVIDEND_TAX`, `OCR_FAILED` und `UNCLASSIFIED_WARNING`; es gab keine Parserfehler. Warnmeldungsinhalte werden wegen möglicher Finanzdaten hier nicht wiedergegeben.

Für das Dokument von 2014 wurden zusätzlich die wirtschaftlichen Signaturen mit und ohne OCR verglichen. Buchungs- und Positionssignatur waren identisch. Dies bestätigt für diesen Fall, dass die langsam extrahierten OCR-Seiten das wirtschaftliche Ergebnis nicht verändern; die produktive OCR-Verarbeitung bleibt dennoch aus Sicherheitsgründen aktiviert.

## 7. Kontrollgruppe

Drei weitere Deka-Dokumente wurden unter derselben Zwei-Worker-Konfiguration geprüft:

| SHA-256 | Dauer | Status | OCR | Fehler |
| --- | ---: | --- | ---: | ---: |
| `6c4269f2913989c06edb9a12e647933245ec18b4c392d46e40e7a7db55999001` | 0,853 s | `INFO` | 0 | 0 |
| `be704b29cb7d264b2e909fef34b60092ca38628b6f32188bd9f4bb21396774c3` | 0,861 s | `WARNING` | 0 | 0 |
| `7024a466ca7587e313584cc0c9578d5a48d8d32549c28249a840334ba9c539ba` | 0,885 s | `INFO` | 0 | 0 |

Plugin und Handler wurden auch in der Kontrollgruppe korrekt erkannt. Die Änderung serialisiert normale Dokumente nicht und verändert deren Parserergebnis nicht.

## 8. Automatisierte Absicherung

Ein Regressionstest prüft die Workergrenzen für OCR- und Nicht-OCR-Audits sowie Ein-CPU-Systeme. Die gezielte Testsuite umfasst das V3-Audit, die Deka/Baader-Parserfälle und die PDF-Plugins.

Ein vollständiger Auditlauf wurde absichtlich nicht gestartet. Für einen späteren vollständigen Lauf wird empfohlen, einen neuen, leeren Ausgabepfad zu verwenden, OCR aktiviert zu lassen, die neue Zwei-Worker-Grenze beizubehalten und den vorhandenen Bericht niemals zu überschreiben.

## 9. Fazit

Die drei Timeouts wurden durch übermäßige Parallelität bei OCR-intensiven Dokumenten ausgelöst. Die minimale Scheduler-Korrektur beseitigt den reproduzierten Timeout, ohne Parserverhalten oder Finanzdaten zu verändern. Alle drei Ziel-PDFs und die Kontrollgruppe wurden erfolgreich verarbeitet; Originale, Datenbanken, bestehende Reports und die lokale Python-Umgebung blieben unverändert.
