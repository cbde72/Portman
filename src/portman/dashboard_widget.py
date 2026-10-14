from .date_display import display_dates
from decimal import Decimal
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                              QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from .performance_service import PerformanceService
from .visualizations import VisualizationsWidget
from .formatting import euro


class DashboardWidget(QWidget):
    navigate = Signal(str)

    def __init__(self, repository, scope_getter, parent=None):
        super().__init__(parent)
        self.repo, self.scope_getter = repository, scope_getter
        self.service = PerformanceService(repository)
        self.cards = {}
        root = QVBoxLayout(self); root.setContentsMargins(18, 8, 18, 14); root.setSpacing(12)
        heading = QHBoxLayout()
        heading.addStretch()
        for text, page in [('Konten ansehen', 'accounts'), ('Performance', 'performance')]:
            button = QPushButton(text); button.clicked.connect(lambda checked=False, p=page: self.navigate.emit(p))
            heading.addWidget(button)
        root.addLayout(heading)
        self.wealth_box = QGroupBox('Gesamtvermögen'); self.wealth_box.setObjectName('wealthHero')
        hero = QVBoxLayout(self.wealth_box)
        self.cards['wealth'] = QLabel('–'); self.cards['wealth'].setStyleSheet('font-size: 36px; font-weight: 700;')
        hero.addWidget(self.cards['wealth'])
        self.wealth_note = QLabel(); self.wealth_note.setWordWrap(True); hero.addWidget(self.wealth_note)
        self.estimate_note = QLabel(); self.estimate_note.setWordWrap(True); hero.addWidget(self.estimate_note)
        review = QPushButton('Bewertung und Daten prüfen'); review.clicked.connect(self.review_valuation); hero.addWidget(review)
        root.addWidget(self.wealth_box)
        grid = QGridLayout(); grid.setSpacing(12)
        for i, (key, title) in enumerate([('value', 'Depotwert'), ('cost', 'Einstandswert'),
                                         ('pnl', 'Buchgewinn / Verlust'), ('return', 'Buchrendite')]):
            box = QGroupBox(title); lay = QVBoxLayout(box)
            label = QLabel('–'); label.setObjectName('metricValue'); lay.addWidget(label)
            self.cards[key] = label; grid.addWidget(box, 0, i)
        root.addLayout(grid)
        self.visuals = VisualizationsWidget(repository, scope_getter, self)
        self.visuals.setMaximumHeight(365)
        root.addWidget(self.visuals, 3)
        detail = QHBoxLayout()
        label = QLabel('GRÖSSTE DEPOTPOSITIONEN'); label.setObjectName('muted'); detail.addWidget(label)
        detail.addStretch(); self.cards['quality'] = QLabel(); self.cards['quality'].setObjectName('muted')
        detail.addWidget(self.cards['quality']); root.addLayout(detail)
        self.top = QTableWidget(0, 5)
        self.top.setHorizontalHeaderLabels(['Wertpapier', 'Typ', 'Depotwert', 'Anteil', 'Buchgewinn'])
        self.top.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.top.setAlternatingRowColors(True); self.top.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.top.verticalHeader().hide(); self.top.setMinimumHeight(130)
        root.addWidget(self.top, 1)
        self.refresh()

    def scope(self):
        return self.scope_getter()

    def review_valuation(self):
        from .valuation_dialog import ValuationDialog
        ValuationDialog(self.repo, self.scope()[0], self).exec()
        window = self.window()
        if hasattr(window, 'reload_portfolio'): window.reload_portfolio()
        else: self.refresh()

    def refresh(self):
        account, as_of = self.scope()
        wealth = self.repo.wealth_summary(as_of, account)
        if isinstance(wealth, list):
            wealth = wealth[0] if wealth else {}
        if not isinstance(wealth, dict):
            wealth = {}
        self.wealth_box.setTitle('Gesamtvermögen' if account is None else f'Kontovermögen · {account}')
        wealth_val = wealth.get('value')
        self.cards['wealth'].setText(display_dates('–' if wealth_val is None else euro(wealth_val)))
        if wealth_val is None:
            self.wealth_note.setText('Noch keine Kontosalden für diese Auswahl. Excel-Dateien über „Import“ einlesen.')
        else:
            dates_list = wealth.get('dates') or []
            period = wealth.get('period') or (dates_list[-1] if dates_list else 'unbekannt')
            self.wealth_note.setText(display_dates(f"Datenstand {period} · {wealth.get('accounts', 0)} Konten · "
                                    'inklusive Altersvorsorge, abzüglich Schulden · ohne Immobilienschätzungen'))
        categories = wealth.get('categories') or {}
        self.cards['wealth'].setToolTip(display_dates('\n'.join(f'{k}: {euro(v)}' for k, v in sorted(categories.items()))))
        if as_of == '9999-12-31':
            from .valuation import current_wealth
            estimate = current_wealth(self.repo, account)
            self.estimate_note.setText(display_dates('Neu bewertet: ' + (euro(estimate['value']) if estimate['value'] is not None else '–')
                + ' · Schätzung aus gemischten Datenständen; Details unter „Bewertung und Daten prüfen“.'))
        else:
            self.estimate_note.setText('Historischer Excel-Stand; aktuelle Kurse werden hier nicht rückwirkend angewendet.')
        data = self.service.overview(as_of, account)
        for key in ('value', 'cost', 'pnl'): self.cards[key].setText(display_dates(euro(data[key])))
        self.cards['return'].setText(display_dates('–' if data['pnl_pct'] is None else f"{data['pnl_pct'] * 100:.2f} %".replace('.', ',')))
        self.cards['quality'].setText(display_dates(f"{len(data['positions'])} Positionen · {len(data['issues'])} Datenhinweise"))
        self.cards['quality'].setToolTip(display_dates('\n'.join(data['issues'][:20])))
        for key in ('cost', 'pnl', 'return'):
            self.cards[key].setToolTip(display_dates('Nur Positionen mit bekanntem positivem Einstandswert.'
                                      if not data['cost_complete'] else 'Einstandswerte vollständig verfügbar.'))
        if not data['cost_complete']:
            self.cards['quality'].setText(display_dates(self.cards['quality'].text() + ' · Buchgewinn nur für bekannte Einstandswerte'))
        positions = sorted(data['positions'], key=lambda p: Decimal(p['value'] or 0), reverse=True)[:8]
        self.top.setRowCount(len(positions))
        for row, p in enumerate(positions):
            gain = None if p.get('value') is None or p.get('cost') is None or Decimal(p['cost']) <= 0 else Decimal(p['value']) - Decimal(p['cost'])
            values = [p['name'], p['asset_type'], euro(p['value']),
                      f"{Decimal(p['value']) / data['value'] * 100:.1f} %".replace('.', ',') if data['value'] else '–',
                      euro(gain) if gain is not None else '–']
            for col, value in enumerate(values):
                item = QTableWidgetItem(display_dates(value))
                if col >= 2: item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.top.setItem(row, col, item)
        for col in range(1, 5): self.top.resizeColumnToContents(col)
        self.visuals.refresh()
