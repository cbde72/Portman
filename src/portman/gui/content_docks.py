"""Detach existing views without copying models, charts or signal connections."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QPushButton,
    QTableView, QTreeView, QSplitter, QStackedWidget, QTabWidget, QGroupBox)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg


class ContentDock(QDockWidget):
    def closeEvent(self, event):
        self.manager.attach(self.key)
        event.accept()


def replace_view(parent, old, new):
    if isinstance(parent, QSplitter):
        sizes = parent.sizes()
        parent.replaceWidget(parent.indexOf(old), new)
        parent.setSizes(sizes)
    elif isinstance(parent, QStackedWidget):
        index, current = parent.indexOf(old), parent.currentIndex()
        tabs = parent.parentWidget()
        if isinstance(tabs, QTabWidget):
            label, icon, tip, enabled = tabs.tabText(index), tabs.tabIcon(index), tabs.tabToolTip(index), tabs.isTabEnabled(index)
            with QSignalBlocker(tabs):
                tabs.removeTab(index)
                tabs.insertTab(index, new, icon, label)
                tabs.setTabToolTip(index, tip)
                tabs.setTabEnabled(index, enabled)
                tabs.setCurrentIndex(current)
        else:
            with QSignalBlocker(parent):
                parent.removeWidget(old)
                parent.insertWidget(index, new)
                parent.setCurrentIndex(current)
    elif parent.layout() is not None:
        item = parent.layout().replaceWidget(old, new)
        if item is None:
            raise ValueError('Ansicht konnte nicht aus dem Layout gelöst werden.')
        del item
    else:
        raise ValueError('Diese Ansicht besitzt keinen austauschbaren Layoutplatz.')
    old.hide()


class ContentDocks:
    def __init__(self, window):
        self.window, self.entries = window, {}
        menu = window.view_menu.addMenu('&Tabellen und Graphen')
        if hasattr(window, 'register_expert_action'):
            window.register_expert_action(menu.menuAction())
        reset = menu.addAction('&Alle in ursprüngliche Bereiche zurücklegen')
        reset.triggered.connect(self.attach_all)
        menu.addSeparator()
        for owner in list(window.docks):
            # Das Diagramm-Raster verwaltet seine Kacheln selbst; einzelne
            # Kacheln sollen nicht über das Ansichten-Menü abgelöst werden.
            if owner.objectName() == 'dock_grid':
                continue
            submenu = menu.addMenu(owner.windowTitle())
            views = [w for w in owner.findChildren(QWidget)
                     if isinstance(w, (QTableView, QTreeView, FigureCanvasQTAgg))]
            for number, view in enumerate(views):
                parent = view.parentWidget()
                if parent is None or (parent.layout() is None and not isinstance(parent, (QSplitter, QStackedWidget))):
                    continue
                key = owner.objectName() + '.view.' + str(number)
                title = self.title(view, owner, number)
                action = submenu.addAction(title)
                action.setCheckable(True)
                action.toggled.connect(lambda checked, k=key: self.detach(k) if checked else self.attach(k))
                self.entries[key] = dict(view=view, parent=parent, owner=owner, title=title,
                                         action=action, dock=None, placeholder=None)
        for key in window.settings.get('detached_views', []):
            if key in self.entries:
                self.detach(key, restoring=True)
        state = window.settings.get('dock_state')
        if state:
            try: window.restoreState(bytes.fromhex(state), 2)
            except (ValueError, TypeError): pass

    @staticmethod
    def title(view, owner, number):
        labels = []
        current = view
        while current is not None and current is not owner:
            parent = current.parentWidget()
            if isinstance(current, QGroupBox) and current.title(): labels.append(current.title())
            if isinstance(parent, QStackedWidget) and isinstance(parent.parentWidget(), QTabWidget):
                tabs = parent.parentWidget()
                labels.append(tabs.tabText(parent.indexOf(current)))
            current = parent
        kind = 'Graph' if isinstance(view, FigureCanvasQTAgg) else 'Tabelle'
        if isinstance(view, QTableView) and view.model() is not None:
            headers = [str(view.model().headerData(i, Qt.Orientation.Horizontal) or '')
                       for i in range(min(2, view.model().columnCount()))]
            kind += ' · ' + ' / '.join(headers)
        return ' · '.join(list(reversed(labels)) + [kind, str(number + 1)])

    def detach(self, key, restoring=False):
        entry = self.entries[key]
        if entry['placeholder'] is not None: return
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        button = QPushButton('Ansicht zurückholen: ' + entry['title'])
        button.clicked.connect(lambda: self.attach(key))
        layout.addWidget(button)
        replace_view(entry['parent'], entry['view'], placeholder)
        entry['placeholder'] = placeholder
        dock = entry['dock']
        if dock is None:
            dock = ContentDock(entry['owner'].windowTitle() + ' · ' + entry['title'], self.window)
            dock.manager, dock.key = self, key
            dock.setObjectName('content.' + key)
            dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
            entry['dock'] = dock
            for signal in (dock.dockLocationChanged, dock.topLevelChanged, dock.visibilityChanged):
                signal.connect(self.window.schedule_layout_save)
        dock.setWidget(entry['view'])
        self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        if not restoring: dock.setFloating(True)
        dock.resize(800, 500)
        dock.show()
        entry['view'].show()
        self.window.refresh_scope_dock(entry['owner'])
        entry['action'].blockSignals(True); entry['action'].setChecked(True); entry['action'].blockSignals(False)
        self.changed()

    def attach(self, key):
        entry = self.entries[key]
        placeholder = entry['placeholder']
        if placeholder is None: return
        view = entry['view']
        view.setParent(entry['parent'])
        replace_view(entry['parent'], placeholder, view)
        view.show()
        entry['dock'].hide()
        placeholder.deleteLater()
        entry['placeholder'] = None
        entry['action'].blockSignals(True); entry['action'].setChecked(False); entry['action'].blockSignals(False)
        self.changed()

    def attach_all(self):
        for key in self.entries: self.attach(key)

    def changed(self):
        self.window.settings['detached_views'] = [k for k, e in self.entries.items() if e['placeholder'] is not None]
        self.window.schedule_layout_save()

    def visible_for(self, owner):
        return any(e['owner'] is owner and e['placeholder'] is not None and e['dock'].isVisible()
                   for e in self.entries.values())
