from .date_display import display_dates
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget
from .data_quality import DataQualityService

class DataQualityWidget(QWidget):
    def __init__(self,repository,scope_getter,parent=None):
        super().__init__(parent);self.service=DataQualityService(repository);self.scope_getter=scope_getter
        layout=QVBoxLayout(self);bar=QHBoxLayout();self.summary=QLabel();refresh=QPushButton('Neu prüfen');refresh.clicked.connect(self.refresh);bar.addWidget(self.summary);bar.addStretch();bar.addWidget(refresh);layout.addLayout(bar)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Schweregrad','Bereich','Kennung','Position/Quelle','Hinweis']);self.table.setAlternatingRowColors(True);layout.addWidget(self.table);self.refresh()
    def refresh(self):
        if getattr(self.service.repo,'defer_initial_views',False): return
        account,as_of=self.scope_getter();issues=self.service.issues(as_of,account);self.table.setRowCount(len(issues));counts={x:sum(i[0]==x for i in issues) for x in ('Fehler','Warnung','Hinweis')};self.summary.setText(display_dates(f"{counts['Fehler']} Fehler · {counts['Warnung']} Warnungen · {counts['Hinweis']} Hinweise"))
        colors={'Fehler':'#b71c1c','Warnung':'#e65100','Hinweis':'#1565c0'}
        for r,row in enumerate(issues):
            for c,value in enumerate(row):
                item=QTableWidgetItem(display_dates(str(value)));
                if c==0:item.setForeground(Qt.GlobalColor.white);item.setBackground(QColor(colors[row[0]]))
                self.table.setItem(r,c,item)
        self.table.resizeColumnsToContents()
