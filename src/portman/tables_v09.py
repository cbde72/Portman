from .date_display import display_dates
"""Virtual, searchable tables with numeric sorting and a frozen identifier column."""
from decimal import Decimal
from PySide6.QtCore import Qt,QAbstractTableModel,QModelIndex,Signal
from PySide6.QtWidgets import QTableView,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QLabel,QAbstractItemView
from .widgets_v09 import table_tools

def display(value):
    if value is None: return 'Unbekannt'
    if isinstance(value,Decimal): return f'{value:,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    if isinstance(value,(list,dict)): return display_dates(str(value))
    return display_dates(str(value))

class RowsModel(QAbstractTableModel):
    def __init__(self,headers=(),rows=(),parent=None):
        super().__init__(parent); self.headers=list(headers); self.raw=list(rows); self.rows=list(rows); self.loaded=min(256,len(self.rows))
    def rowCount(self,parent=QModelIndex()): return 0 if parent.isValid() else self.loaded
    def columnCount(self,parent=QModelIndex()): return len(self.headers)
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole: return self.headers[section] if orientation==Qt.Orientation.Horizontal else section+1
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        value=self.rows[index.row()][index.column()]
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole): return display(value)
        if role==Qt.ItemDataRole.UserRole: return value
        if role==Qt.ItemDataRole.TextAlignmentRole and isinstance(value,(Decimal,int,float)): return Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter
    def canFetchMore(self,parent=QModelIndex()): return not parent.isValid() and self.loaded<len(self.rows)
    def fetchMore(self,parent=QModelIndex()):
        n=min(256,len(self.rows)-self.loaded)
        if n: self.beginInsertRows(QModelIndex(),self.loaded,self.loaded+n-1); self.loaded+=n; self.endInsertRows()
    def reset(self,headers,rows):
        self.beginResetModel(); self.headers=list(headers); self.raw=list(rows); self.rows=list(rows); self.loaded=min(256,len(self.rows)); self.endResetModel()
    def filter(self,text):
        query=text.casefold().strip(); self.beginResetModel(); self.rows=[r for r in self.raw if query in ' '.join(display(v) for v in r).casefold()]; self.loaded=min(256,len(self.rows)); self.endResetModel()
    def sort(self,column,order=Qt.SortOrder.AscendingOrder):
        def key(row):
            v=row[column]
            if v is None: return (2,'')
            if isinstance(v,(Decimal,int,float)): return (0,Decimal(str(v)))
            return (1,str(v).casefold())
        self.beginResetModel(); self.rows.sort(key=key,reverse=order==Qt.SortOrder.DescendingOrder); self.endResetModel()

class RowsView(QTableView):
    cellDoubleClicked=Signal(int,int)
    def __init__(self,parent=None):
        super().__init__(parent); self.doubleClicked.connect(lambda i:self.cellDoubleClicked.emit(i.row(),i.column()))
    def rowCount(self): return self.model().rowCount()
    def columnCount(self): return self.model().columnCount()
    def currentRow(self): return self.currentIndex().row()
    def horizontalHeaderItem(self,column):
        from PySide6.QtWidgets import QTableWidgetItem
        return QTableWidgetItem(self.model().headers[column])
    def item(self,row,column):
        from PySide6.QtWidgets import QTableWidgetItem
        return QTableWidgetItem(display(self.model().rows[row][column]))
    def set_rows(self,rows): self.model().reset(self.model().headers,rows)

class DataTable(QWidget):
    def __init__(self,headers=(),rows=(),parent=None):
        super().__init__(parent); layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        bar=QHBoxLayout(); layout.addLayout(bar); self.search=QLineEdit(); self.search.setPlaceholderText('Tabelle durchsuchen · alle Datensätze'); bar.addWidget(self.search)
        self.note=QLabel(); bar.addWidget(self.note)
        self.view=RowsView(); self.model=RowsModel(headers,rows,self); self.view.setModel(self.model); self.view.setSortingEnabled(True); self.view.setAlternatingRowColors(True); self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); layout.addWidget(self.view)
        table_tools(self.view); self.search.textChanged.connect(self.filter); self.reset(headers,rows)
        self.frozen=QTableView(self.view); self.frozen.setModel(self.model); self.frozen.setSelectionModel(self.view.selectionModel()); self.frozen.setFocusPolicy(Qt.FocusPolicy.NoFocus); self.frozen.verticalHeader().hide(); self.frozen.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.frozen.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.frozen.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.frozen.doubleClicked.connect(self.view.doubleClicked.emit)
        self.view.verticalScrollBar().valueChanged.connect(self.frozen.verticalScrollBar().setValue); self.frozen.verticalScrollBar().valueChanged.connect(self.view.verticalScrollBar().setValue)
        self.view.horizontalHeader().sectionResized.connect(lambda *a:self.place_frozen()); self.model.modelReset.connect(self.place_frozen)
        self.place_frozen()
        self.view.set_rows=lambda rows:self.reset(self.model.headers,rows)
    def place_frozen(self):
        if not hasattr(self,'frozen'): return
        for c in range(1,self.model.columnCount()): self.frozen.setColumnHidden(c,True)
        self.frozen.setColumnWidth(0,self.view.columnWidth(0)); self.frozen.setGeometry(self.view.verticalHeader().width()+self.view.frameWidth(),self.view.frameWidth(),self.view.columnWidth(0),self.view.viewport().height()+self.view.horizontalHeader().height())
        self.frozen.setVisible(self.model.columnCount()>0)
    def resizeEvent(self,event): super().resizeEvent(event); self.place_frozen()
    def reset(self,headers,rows):
        self.model.reset(headers,rows); self.filter(self.search.text())
        for i in range(len(headers)): self.view.setColumnWidth(i,180 if i==0 else 145)
    def filter(self,text): self.model.filter(text); self.note.setText(f'{len(self.model.rows)} / {len(self.model.raw)} Datensätze')
