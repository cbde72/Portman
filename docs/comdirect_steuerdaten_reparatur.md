# comdirect-Steuerdaten: Zuordnung, Prüfung und Reparatur

## Fehlerursache

comdirect druckt auf Steuermitteilungen die Depotnummer zusammen mit einer
zweistelligen Unterkontokennung. Im Referenzfall stand deshalb `476492400` im
PDF, während das Portman-Depot `4764924` heißt. Die frühere allgemeine
Kontonummernsuche fand die vollständige Ziffernfolge im Girokonto und schlug
dieses als Ziel vor. Dabei wurde der fachliche Quelltyp „Depot-Steuerereignis“
nicht gegen den Kontotyp des Ziels geprüft.

Die neue Logik löst die zusätzliche Kennung ausschließlich für eine als
comdirect erkannte PDF-Depotquelle auf. Ein Treffer ist nur zulässig, wenn genau
ein aktives Portman-Konto vom Typ `Depot` passt. Es werden weder allgemein
führende noch nachgestellte Ziffern entfernt. Steuerereignisse und
Steuerdetail-CSV-Daten können auch über gespeicherte Regeln oder direkte
Repository-Aufrufe nicht einem Giro- oder Verrechnungskonto zugeordnet werden.

## Kontrollierte Reparatur bestehender Imports

`RepositoryV09.tax_assignment_issues()` liefert eine schreibgeschützte Vorschau
aller aktiven Altimporte, deren Steuerquelle aktuell nicht auf ein aktives Depot
zeigt. Enthalten sind Import-ID, Datei, erkannte Quellkennung, bisheriges Ziel
und – nur bei eindeutigem Treffer – ein vorgeschlagenes Depot samt Begründung.

Die eigentliche Korrektur erfolgt über die vorhandene Funktion „Importkonten
nachträglich zuordnen“. Dort sind bei Steuerquellen nur Depots auswählbar; die
Tabelle zeigt Quelle, bisheriges Konto und neues Ziel vor dem Speichern. Die
Änderung schreibt ausschließlich `import_account_links` und die protokollierte
`assignment_history`. Import-ID, Originalbeleg, Transaktionen, Depotstände,
Stückzahlen und Einstandskosten bleiben unverändert. Eine Rückkehr zum vorherigen
Depot erfolgt über dieselbe Zuordnung; vor Änderungen erzeugt V09 regulär eine
Sicherung.

## Lokaler Referenzabgleich

Die privaten Referenzdateien wurden nur lokal in einer temporären Datenbank
verarbeitet und nicht versioniert. Ergebnis:

- 38 CSV-Einzelvorgänge, davon 14 Vorabpauschalen und 3 steuerpflichtige;
- 192,24 EUR FSA-Verbrauch aus Vorabpauschalen, 411,00 EUR insgesamt;
- 508,89 EUR Bemessungsgrundlage nach Verlustverrechnung und 97,89 EUR nach FSA;
- 24,47 EUR Kapitalertragsteuer, 1,32 EUR Solidaritätszuschlag und 25,79 EUR Gesamtsteuer;
- keine Steuerzahlung auf Vorabpauschalen;
- eine bereitgestellte PDF wurde eindeutig mit ihrer CSV-Zeile verbunden;
- die übrigen 37 CSV-Zeilen blieben unverknüpft, weil dafür keine zugehörigen
  PDF-Belege Teil des Referenzsatzes waren; dies ist keine Datenabweichung;
- ein identischer CSV-Wiederholungsimport wurde als Dublette erkannt;
- es entstanden keine Transaktionen und keine Depotpositionen.

Die CSV führt Belastungen mit negativem Vorzeichen. Die fachlichen Summen oben
sind die Absolutbeträge; es wurden keine Sollwerte in der Importlogik erzwungen.

## Verknüpfungs- und Quellenpriorität

Eine identische Referenznummer ist der stärkste Schlüssel. Bei abweichenden oder
fehlenden Referenzen werden Depot, WKN/ISIN, steuerliches Datum beziehungsweise
Buchungstag und steuerpflichtiger Betrag gemeinsam verlangt. Mehrere Treffer
führen zum Status `ambiguous`; dann findet keine automatische Zusammenführung
statt. Ein verknüpftes PDF liefert die genauere Stückzahl, Vorabpauschale,
Teilfreistellung und das Belegdatum. Die CSV behält trotzdem alle 32
Originalspalten. Eine echte Steuerabbuchung bleibt eine separate, eindeutig
verknüpfte Geldbuchung.

## Fachlich offene Grenzen

- Bei Fondsverschmelzungen, Depotüberträgen oder fehlenden Stückzahlen ist eine
  automatische stückanteilige Zuordnung alter Vorabpauschalen nicht belastbar;
  der steuerliche Verkaufswert bleibt dann unbekannt und muss anhand der
  Steuerabrechnung geprüft werden.
- Korrektur- und Stornobelege mit gleicher Referenz benötigen weitere reale,
  anonymisierbare Muster, bevor eine automatische Saldierung zulässig wäre.
- Portman zeigt die rechnerische Anrechnung historischer steuerpflichtiger
  Vorabpauschalen. Sie ersetzt keine Steuerbescheinigung und keine steuerliche
  Beratung.
