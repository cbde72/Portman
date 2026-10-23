"""Export and copy the visible, displayed contents of Qt tables."""
import csv
from io import StringIO
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _header(table):
    return table.horizontalHeader() if hasattr(table, 'horizontalHeader') else table.header()


def table_text(table, *, selected_only=False):
    model = table.model()
    header = _header(table)
    columns = [header.logicalIndex(i) for i in range(model.columnCount())
               if not table.isColumnHidden(header.logicalIndex(i))]
    rows = [[model.headerData(c, Qt.Orientation.Horizontal) or '' for c in columns]]
    if selected_only:
        indexes = table.selectionModel().selectedIndexes()
        if not indexes:
            return ''
        # Visual coordinates preserve proxy sorting and hierarchical tree order.
        row_keys = []
        for index in sorted(indexes, key=lambda item: (table.visualRect(item).top(),
                                                       header.visualIndex(item.column()))):
            key = (index.parent().internalId(), index.row())
            if key not in row_keys:
                row_keys.append(key)
        selected_columns = [c for c in columns if any(index.column() == c for index in indexes)]
        selected = {(index.parent().internalId(), index.row(), index.column()): index for index in indexes}
        rows = []
        for parent_id, row in row_keys:
            values = []
            for column in selected_columns:
                index = selected.get((parent_id, row, column))
                value = index.data(Qt.ItemDataRole.DisplayRole) if index is not None else None
                values.append(value if value is not None else '')
            rows.append(values)
    elif hasattr(model, 'rows'):
        from .tables_v09 import display
        rows.extend([display(row[c]) for c in columns] for row in model.rows)
    else:
        rows.extend([model.index(r, c).data() or '' for c in columns]
                    for r in range(model.rowCount()) if not table.isRowHidden(r))
    def safe(value):
        value = str(value)
        if selected_only:
            return value
        return "'" + value if value.startswith(('=', '+', '@')) or value.startswith('-') and not value[1:2].isdigit() else value
    output = StringIO(newline='')
    csv.writer(output, delimiter='\t', lineterminator='\n').writerows([safe(v) for v in row] for row in rows)
    return output.getvalue()


def copy_table(table):
    QApplication.clipboard().setText(table_text(table))


def copy_selected_rows(table):
    """Compatibility name: copy exactly the selected visible cells, without headers."""
    text = table_text(table, selected_only=True)
    if text:
        QApplication.clipboard().setText(text)


copy_selected_cells = copy_selected_rows
