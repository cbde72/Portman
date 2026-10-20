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
        indexes = table.selectionModel().selectedIndexes()
        if not indexes:
            return ''
        selected_rows = sorted({index.row() for index in indexes})
        selected_columns = [c for c in columns if any(index.column() == c for index in indexes)]
        selected = {(index.row(), index.column()) for index in indexes}
        rows = [[model.headerData(c, Qt.Orientation.Horizontal) or '' for c in selected_columns]]
        rows.extend([model.index(r, c).data() if (r, c) in selected and model.index(r, c).data() is not None else ''
                     for c in selected_columns] for r in selected_rows if not table.isRowHidden(r))
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
