# Portman V10 – Claude Code

@AGENTS.md

Die gemeinsame AGENTS.md im selben Verzeichnis ist die verbindliche Projektgrundlage. Keine Kopie ihrer Architektur- und Datenregeln hier pflegen. Falls der Import nicht aufgelöst werden kann, AGENTS.md ausdrücklich lesen, bevor Dateien geändert werden.

## Rolle
- Standard: Nur den konkret beauftragten Arbeitsschritt umsetzen und passend testen.
- Bei Review-Auftrag: zunächst nur lesen und prüfen, keine Dateien ändern. Relevante Spezifikation, Diff und Tests prüfen; Befunde mit Datei/Zeile, Auswirkung und gezieltem Korrekturvorschlag nennen.
- Keine weiteren Agenten ohne ausdrücklichen Auftrag starten.
- Keine gleichzeitigen Schreibänderungen im Worktree eines anderen Agenten.

## Arbeitsweise
- Auf Deutsch und knapp kommunizieren. Bereits geklärte Architektur nicht erneut diskutieren.
- Projektkontext gezielt laden; vollständigen Bauplan nur lesen, wenn die Aufgabe ihn tatsächlich benötigt.
- Technische Isolation nicht aus dieser Datei ableiten; Berechtigungen der Umgebung gelten unabhängig.
- Abschluss: umgesetzt/geprüft, ausgeführte Tests und verbleibende Einschränkungen. Nicht ausgeführte Prüfungen ausdrücklich benennen.
