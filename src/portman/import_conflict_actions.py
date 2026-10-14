from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton


def install_conflict_actions(wizard):
    bar = QHBoxLayout()
    wizard.layout().addLayout(bar)
    for label, callback in [
        ('Für alle Entscheidungen übernehmen', lambda: copy_first_decision(wizard)),
        ('Begründung für alle Ersatzentscheidungen übernehmen', lambda: copy_first_reason(wizard)),
    ]:
        button = QPushButton(label)
        button.clicked.connect(callback)
        bar.addWidget(button)


def apply_open_decisions(wizard, action):
    for row in range(wizard.conflict_table.rowCount()):
        combo = wizard.conflict_table.cellWidget(row, 0)
        index = combo.findData(action)
        if combo.currentData() is None and index >= 0:
            combo.setCurrentIndex(index)


def copy_first_decision(wizard):
    if not wizard.conflict_table.rowCount():
        return
    action = wizard.conflict_table.cellWidget(0, 0).currentData()
    if action is None:
        QMessageBox.information(wizard, 'Entscheidung übernehmen', 'Bitte zuerst die erste Entscheidung auswählen.')
        return
    apply_open_decisions(wizard, action)


def copy_first_reason(wizard):
    if not wizard.conflict_table.rowCount():
        return
    reason = wizard.conflict_table.cellWidget(0, 1).text().strip()
    if not reason:
        QMessageBox.information(wizard, 'Begründung übernehmen', 'Bitte zuerst die Begründung in der ersten Zeile eingeben.')
        return
    for row in range(1, wizard.conflict_table.rowCount()):
        editor = wizard.conflict_table.cellWidget(row, 1)
        if wizard.conflict_table.cellWidget(row, 0).currentData() == 'replace' and not editor.text().strip():
            editor.setText(reason)


def ask_conflict_policy(wizard):
    if not any(wizard.conflict_table.cellWidget(row, 0).currentData() is None
               for row in range(wizard.conflict_table.rowCount())):
        return
    box = QMessageBox(wizard)
    box.setWindowTitle('Überschneidungen behandeln')
    box.setText('Sollen alte Einträge durch neue ersetzt oder alle alten Einträge behalten werden?')
    box.setInformativeText('Die Auswahl gilt für offene Entscheidungen. Bei Ersatz bleiben Begründung und gegebenenfalls Gegenbeleg zu prüfen.')
    replace = box.addButton('Alte durch neue ersetzen', QMessageBox.ButtonRole.AcceptRole)
    keep = box.addButton('Alle alten behalten', QMessageBox.ButtonRole.AcceptRole)
    individual = box.addButton('Einzeln entscheiden', QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(individual)
    box.exec()
    if box.clickedButton() is replace:
        apply_open_decisions(wizard, 'replace')
    elif box.clickedButton() is keep:
        apply_open_decisions(wizard, 'skip')
