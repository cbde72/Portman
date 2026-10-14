"""Shared confirmation for permanent portfolio resets."""
from PySide6.QtWidgets import QMessageBox


def confirm_reset(parent, repository, *, accounts=False):
    title = 'Alle Konten löschen' if accounts else 'Alle Importe löschen'
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(title + ' und bei null anfangen?')
    details = ('Alle aktiven und zurückgenommenen Importe, Depotstände, importierten Salden, '
               'Transaktionen, archivierten Bankdokumente, Korrekturen und gemerkten '
               'Import- und Depotzuordnungen werden endgültig gelöscht.\n\n')
    details += ('Zusätzlich werden alle Konten und Unterkonten (auch entfernte Konten) '
                'sowie manuelle Salden gelöscht.\n\n' if accounts else
                'Konten und manuelle Salden bleiben erhalten.\n\n')
    box.setInformativeText(details + 'Die ursprünglichen Dateien bleiben erhalten. '
                           'Das Löschen kann nicht rückgängig gemacht werden.')
    delete = box.addButton('Endgültig löschen', QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton('Abbrechen', QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    if box.clickedButton() != delete:
        return False
    try:
        if accounts:
            repository.delete_all_accounts()
        else:
            repository.delete_all_imports()
    except Exception as error:
        QMessageBox.warning(parent, 'Löschen fehlgeschlagen', str(error))
        return False
    return True
