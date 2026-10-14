"""Virtual position tables; numeric sorting and proxy filters without cell widgets."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QTableView, QTableWidgetItem
from PySide6.QtGui import QColor, QFont
from .theme import TABLE_FONTS, DEFAULT_TABLE_FONT

HEADERS = ['ISIN', 'Name', 'Typ', 'Region', 'Cap', 'Anzahl', 'Kaufwert (€)', 'Marktwert (€)',
           'Gewinn/Verlust (€)', 'Div.Rend(%)', 'Dividende(€/J)', 'Anteil (%)',
           'Gewinn/Verlust (%)', 'Symbol', 'WKN', 'Erste Aktivität']
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


_BOLD_FONT_CACHE = {}


def _bold_font():
    config = TABLE_FONTS.get('positions') or DEFAULT_TABLE_FONT
    key = (str(config.get('family') or ''), int(config.get('size') or 0))
    font = _BOLD_FONT_CACHE.get(key)
    if font is None:
        font = QFont(key[0], key[1])
        font.setBold(True)
        _BOLD_FONT_CACHE[key] = font
    return font


class PositionsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent); self.rows = []; self.market = {}; self.mappings = {}; self.first_activity = {}
    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.rows)
    def columnCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(HEADERS)
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal: return HEADERS[section]
    def reset(self, holdings, market, mappings=None, first_activity=None):
        self.first_activity = first_activity or {}
        self.beginResetModel(); self.rows = list(holdings); self.market = market; self.mappings = mappings or {}; self.endResetModel()
    def _dividend(self, key):
        record = self.market.get(key, {})
        return record.get('manual', {}).get('fields', {}).get('dividend_yield_pct',
                                                               record.get('data', {}).get('metrics', {}).get('dividend_yield_pct'))

    def _value(self, h, key, c):
        # Compute only the requested column; building the full row per cell made
        # sorting and painting O(columns) more expensive than necessary.
        if c == 0: return h.isin or h.wkn
        if c == 1: return h.name
        if c == 2: return h.asset_type
        if c == 3: return h.region
        if c == 4: return h.cap_size
        if c == 5: return h.amount
        if c == 6: return h.buy_value if h.buy_value > 0 else None
        if c == 7: return h.market_value
        if c == 8: return h.profit_loss if h.buy_value > 0 else None
        if c == 9: return self._dividend(key)
        if c == 10:
            dividend = self._dividend(key)
            return h.market_value * dividend / 100 if dividend is not None else None
        if c == 11: return None
        if c == 12: return h.profit_loss / h.buy_value * 100 if h.buy_value > 0 else None
        if c == 13: return self.mappings.get(key, {}).get('symbol') or self.market.get(key, {}).get('data', {}).get('symbol')
        if c == 14: return h.wkn or None
        if c == 15: return self.first_activity.get(key)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        h = self.rows[index.row()]; c = index.column(); key = h.isin or ('WKN:' + h.wkn)
        if role == Qt.ItemDataRole.UserRole: return key
        if role == Qt.ItemDataRole.TextAlignmentRole: return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ForegroundRole and c in (8, 12) and h.buy_value > 0:
            if h.profit_loss > 0: return QColor('#16803c')
            if h.profit_loss < 0: return QColor('#dc2626')
        if role == Qt.ItemDataRole.FontRole and c in (8, 12) and h.buy_value > 0 and h.profit_loss != 0:
            return _bold_font()
        if role == Qt.ItemDataRole.ToolTipRole:
            if c == 0: return 'Doppelklick: Wertpapier bearbeiten.'
            return 'Doppelklick: Belege und Datenherkunft anzeigen.'
        if role not in (Qt.ItemDataRole.DisplayRole, SORT_ROLE): return None
        value = h.market_value if c == 11 and role == SORT_ROLE else self._value(h, key, c)
        if role == SORT_ROLE: return value
        if value is None: return '–'
        if c == 15: return '.'.join(reversed(value.split('-')))
        if isinstance(value, (int, float)):
            return f'{value:,.4f}' .replace(',', 'X').replace('.', ',').replace('X', '.') if c == 5 else f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        return value


class PositionFilter(QSortFilterProxyModel):
    def __init__(self, category, parent=None):
        super().__init__(parent); self.category = category; self.region = ''; self.cap = ''; self.query = ''; self.total = 0
        self.setSortRole(SORT_ROLE)
    def filterAcceptsRow(self, row, parent):
        h = self.sourceModel().rows[row]
        return ((self.category == 'Alle' or h.asset_type == self.category)
                and (self.region in ('', 'Alle Regionen') or h.region == self.region)
                and (self.cap in ('', 'Alle Cap-Größen') or h.cap_size == self.cap)
                and self.query in (h.name + ' ' + h.isin + ' ' + h.wkn + ' ' + self.sourceModel().mappings.get(h.isin or ('WKN:' + h.wkn), {}).get('symbol', '')).casefold())
    def filters(self, region, cap, query):
        self.region, self.cap, self.query = region, cap, query.strip().casefold()
        self.invalidate()
        total = sum(h.market_value for i, h in enumerate(self.sourceModel().rows) if self.filterAcceptsRow(i, QModelIndex()))
        # Column 11 shows the share of the filtered total; only repaint it when
        # the total actually changed (invalidate already refreshed row membership).
        changed = total != self.total
        self.total = total
        if changed and self.rowCount(): self.dataChanged.emit(self.index(0, 11), self.index(self.rowCount() - 1, 11))
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.column() == 11 and role in (Qt.ItemDataRole.DisplayRole, SORT_ROLE):
            h = self.sourceModel().rows[self.mapToSource(index).row()]
            value = h.market_value / self.total * 100 if self.total else 0
            return value if role == SORT_ROLE else f'{value:.2f}'.replace('.', ',')
        return super().data(index, role)

    def totals(self):
        holdings = [self.sourceModel().rows[row] for row in range(self.sourceModel().rowCount())
                    if self.filterAcceptsRow(row, QModelIndex())]
        cost = sum(h.buy_value for h in holdings if h.buy_value > 0)
        market = sum(h.market_value for h in holdings)
        profit = sum(h.profit_loss for h in holdings if h.buy_value > 0)
        percent = profit / cost * 100 if cost else None
        return cost, market, profit, percent


class PositionTable(QTableView):
    def columnCount(self): return self.model().columnCount()
    def rowCount(self): return self.model().rowCount()
    def horizontalHeaderItem(self, col): return QTableWidgetItem(HEADERS[col])
    def item(self, row, col):
        index = self.model().index(row, col)
        item = QTableWidgetItem(str(index.data() or ''))
        item.setData(Qt.ItemDataRole.UserRole, index.data(Qt.ItemDataRole.UserRole))
        return item
