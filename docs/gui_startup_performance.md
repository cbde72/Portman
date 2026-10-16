# GUI- und Startperformance (V09)

Messdatum: 2026-10-16, Windows, Python 3.14, Qt offscreen. Gemessen wurde mit
`python benchmarks/benchmark_gui_startup.py --runs 3`; jeder Lauf verwendet
einen neuen Python-Prozess und ein neues leeres temporäres Portfolio. Der
Vorher-Wert stammt aus einem separaten Worktree von `main` (`6f96c9b`), der
Nachher-Wert aus `codex/gui-start-performance`. Angegeben ist jeweils der
Median. Produktive Finanzdaten wurden nicht geöffnet oder verändert.

| Funktion / Arbeitsschritt | Vorher | Nachher | Änderung | Betroffene Dateien |
|---|---:|---:|---:|---|
| Python-/Qt-/Portman-Importe | 990,47 ms | 942,57 ms | 4,8 % schneller* | – |
| SQLite-Verbindung und Initialisierung | 108,09 ms | 102,97 ms | 4,7 % schneller* | – |
| V09-Fenster einschließlich Widgets | 1.530,44 ms | 1.512,98 ms | 1,1 % schneller | `visualizations.py`, `visualization_board.py` |
| Vier Arbeitsbereichswechsel | 108,18 ms | 108,29 ms | 0,1 % langsamer* | – |
| Selektiver GUI-Refresh | 8,34 ms | 7,01 ms | 15,9 % schneller* | – |
| Zwei Theme-Wechsel | 6.289,69 ms | 6.201,22 ms | 1,4 % schneller | `theme.py` |
| SQL-Anweisungen im gemessenen Ablauf | 123 | 123 | unverändert | – |

\* Diese Schritte wurden nicht verändert; kleine Abweichungen sind Laufzeit-
und Dateisystemrauschen. Es wird hierfür kein Optimierungseffekt beansprucht.

Ein ergänzendes `cProfile` des GUI-Integrationstests zeigte für den eigentlichen
Fensterkonstruktor 3,183 s vorher und 2,823 s nachher (11,3 %), sowie für die
fünf `VisualizationsWidget`-Konstruktoren 1,013 s vorher und 0,653 s nachher
(35,5 %). Profilerwerte enthalten Instrumentierungs-Overhead und werden daher
nicht mit den Prozess-Medianen vermischt.

## Befund und Patch

- Drei nicht primäre Diagramme des Visualisierungsboards erzeugten schon beim
  Start jeweils ein Matplotlib-/Qt-Canvas, obwohl der Arbeitsbereich verborgen
  war. Diese Canvases entstehen nun erst beim ersten Refresh bzw. Öffnen. Das
  primäre Diagramm und alle öffentlichen Attribute bleiben kompatibel.
- `apply_theme()` installierte bei jedem Theme-Wechsel erneut den bereits
  aktiven Qt-Basisstil `Fusion`. Qt repolished dadurch sämtliche Widgets. Der
  Basisstil wird nun nur gewechselt, wenn er tatsächlich abweicht; Palette,
  Schrift und Stylesheet werden weiterhin vollständig angewendet.
- Der Benchmark erfasst Importe, Datenbankinitialisierung, Fensteraufbau,
  Workspace-Wechsel, selektiven Refresh und SQL-Anweisungen reproduzierbar.

Keine Finanzformel, Datenbankstruktur, Importlogik oder produktive Datei wurde
geändert. Die Diagrammdaten werden weiterhin über den vorhandenen Loader im
Hintergrund berechnet; Qt-Widgets werden ausschließlich im GUI-Thread erzeugt
und aktualisiert.

## Tests

- Gezielte GUI-, Diagramm-, Theme- und Hintergrundtests: 25 bestanden.
- Vollständige Suite: 927 bestanden, 9 übersprungen, 5 Subtests bestanden in
  219,43 s. Keine Fehler.

Verbleibendes Risiko: Der absolute Zeitgewinn hängt von Qt-Plattformstil,
Grafiktreiber, Virenscanner und gespeicherter Diagrammkonfiguration ab. Bei
erstmaligem Öffnen des Visualisierungsbereichs werden die verzögerten Canvases
einmalig aufgebaut; danach verhalten sie sich wie zuvor.
