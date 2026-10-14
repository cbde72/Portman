"""Combo-Box mit Checkbox-Einträgen für die Konten- und Depotauswahl.

Die Combo-Box bleibt die gewohnte Dropdown-Bedienung, zeigt aber pro Eintrag
eine Checkbox. Mehrere Konten können so direkt im vorhandenen Menü an- und
abgewählt werden, ohne dass sich das Dropdown nach jedem Klick schließt.
"""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox

ALL_ROLE = Qt.ItemDataRole.UserRole + 1
DATA_ROLE = Qt.ItemDataRole.UserRole


class CheckableComboBox(QComboBox):
    """Dropdown-Liste mit Checkbox-Einträgen.

    Der erste Eintrag ist ein spezieller „Alle“-Eintrag mit Checkbox: Er
    setzt jede Einzelauswahl zurück. Die übrigen Einträge lassen sich einzeln an-
    und abwählen; das Dropdown bleibt dabei geöffnet.
    """

    checked_items_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setMinimumWidth(190)
        self.setObjectName('accountScopeCombo')
        self.view().setObjectName('accountScopeList')
        self.view().setAlternatingRowColors(False)
        self.view().pressed.connect(self._handle_item_pressed)
        self.view().viewport().installEventFilter(self)

    # --- Aufbau -------------------------------------------------------
    def set_items(self, all_label, values):
        """Füllt die Liste neu; ``values`` sind (Text, Daten)-Paare."""
        self._all_label = all_label
        self.set_updating(True)
        self._model.clear()
        all_item = QStandardItem(all_label)
        all_item.setData(True, ALL_ROLE)
        all_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsSelectable)
        all_item.setCheckState(Qt.CheckState.Checked)
        self._model.appendRow(all_item)
        for text, data in values:
            item = QStandardItem(text)
            item.setData(data, DATA_ROLE)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._model.appendRow(item)
        self.set_updating(False)
        self._refresh_display_text()

    def checked_data(self):
        """Daten aller angehakten Einträge (Reihenfolge der Liste)."""
        result = []
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if (item is not None and not item.data(ALL_ROLE)
                    and item.checkState() == Qt.CheckState.Checked):
                result.append(item.data(DATA_ROLE))
        return result

    def restore_checked(self, values):
        """Setzt die Haken auf die angegebenen Werte (z. B. nach Refresh)."""
        self.set_updating(True)
        wanted = set(values)
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is not None and item.data(ALL_ROLE):
                item.setCheckState(Qt.CheckState.Checked if not wanted else Qt.CheckState.Unchecked)
            elif item is not None:
                item.setCheckState(Qt.CheckState.Checked if item.data(DATA_ROLE) in wanted
                                   else Qt.CheckState.Unchecked)
        self.set_updating(False)
        self._refresh_display_text()

    # --- Verhalten ----------------------------------------------------
    def set_updating(self, updating):
        """Schaltet Signal-Weiterleitungen beim Programmesse aus/ein."""
        self._model.blockSignals(updating)

    def _handle_item_pressed(self, index):
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        if item.data(ALL_ROLE):
            self.clear_selection()
            self.hidePopup()
            return
        all_item = self._model.item(0)
        if all_item is not None:
            all_item.setCheckState(Qt.CheckState.Unchecked)
        item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                            else Qt.CheckState.Checked)
        if not self.checked_data() and all_item is not None:
            all_item.setCheckState(Qt.CheckState.Checked)
        self._refresh_display_text()
        self.checked_items_changed.emit()

    def clear_selection(self):
        """Entfernt alle Haken („Alle Konten“)."""
        self.set_updating(True)
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if item.data(ALL_ROLE)
                                   else Qt.CheckState.Unchecked)
        self.set_updating(False)
        self._refresh_display_text()
        self.checked_items_changed.emit()

    def _refresh_display_text(self):
        checked = [self._model.item(row).text()
                   for row in range(self._model.rowCount())
                   if self._model.item(row) is not None
                   and not self._model.item(row).data(ALL_ROLE)
                   and self._model.item(row).checkState() == Qt.CheckState.Checked]
        all_label = getattr(self, '_all_label', 'Alle Konten')
        if not checked:
            display = all_label if self._model.rowCount() else '–'
        elif len(checked) == 1:
            display = checked[0]
        else:
            display = f'{len(checked)} ausgewählt'
        self.blockSignals(True)
        self.setCurrentText(display)
        self.blockSignals(False)

    # --- Popup offen halten -------------------------------------------
    def eventFilter(self, watched, event):
        """Verhindert, dass sich das Dropdown beim Klick auf eine Checkbox schließt."""
        if watched is self.view().viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            return True
        return super().eventFilter(watched, event)
