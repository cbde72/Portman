"""Export the complete filtered table, including rows not yet fetched by Qt."""
import csv
from io import StringIO
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def table_text(table, *, selected_only=False):
    model = table.model()
    header = table.horizontalHeader()
    columns = [header.logicalIndex(i) for i in range(model.columnCount())
               if not table.isColumnHidden(header.logicalIndex(i))]
    rows = [[model.headerData(c, Qt.Orientation.Horizontal) or '' for c in columns]]
    if selected_only:
        selected = sorted({index.row() for index in table.selectionModel().selectedIndexes()})
        if not selected:
            return ''
        rows.extend([model.index(r, c).data() if model.index(r, c).data() is not None else '' for c in columns]
                    for r in selected if not table.isRowHidden(r))
    elif hasattr(model, 'rows'):
        from .tables_v09 import display
        rows.extend([display(row[c]) for c in columns] for row in model.rows)
    else:
        rows.extend([model.index(r, c).data() or '' for c in columns]
                    for r in range(model.rowCount()) if not table.isRowHidden(r))
    def safe(value):
        value = str(value)
        return "'" + value if value.startswith(('=', '+', '@')) or value.startswith('-') and not value[1:2].isdigit() else value
    output = StringIO(newline='')
    csv.writer(output, delimiter='\t', lineterminator='\n').writerows([safe(v) for v in row] for row in rows)
    return output.getvalue()


def copy_table(table):
    QApplication.clipboard().setText(table_text(table))


def copy_selected_rows(table):
    text = table_text(table, selected_only=True)
    if text:
        QApplication.clipboard().setText(text)
