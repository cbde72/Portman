"""Read-only chart tooltips with value, date and the view's source explanation."""
import numpy as np
import matplotlib.dates as mdates
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QToolTip


def number(value):
    return f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def install_chart_tooltips(canvas, note):
    cache = {}
    def prepare(event=None):
        cache.clear()
        for axis in canvas.figure.axes:
            for line in axis.lines:
                xy = line.get_xydata()
                if len(xy):
                    pixels = axis.transData.transform(xy)
                    cache[line] = (xy, pixels, bool(np.all(np.diff(pixels[:, 0]) >= 0)))
    canvas.mpl_connect('draw_event', prepare)
    def hover(event):
        axis = event.inaxes
        if axis is None:
            QToolTip.hideText(); return
        for line in axis.lines:
            if not line.get_visible() or line not in cache: continue
            xy, pixels, sorted_x = cache[line]
            left, right = (np.searchsorted(pixels[:, 0], [event.x - 12, event.x + 12]) if sorted_x else (0, len(xy)))
            if left == right: continue
            distance = np.linalg.norm(pixels[left:right] - [event.x, event.y], axis=1)
            nearest = int(np.argmin(distance))
            if distance[nearest] > 12: continue
            index = left + nearest
            x, y = xy[index]
            formatter = axis.xaxis.get_major_formatter()
            stamp = mdates.num2date(x).strftime('%d.%m.%Y') if isinstance(formatter, (mdates.DateFormatter, mdates.AutoDateFormatter, mdates.ConciseDateFormatter)) else f'{x:g}'
            label = line.get_label()
            if label.startswith('_'): label = axis.get_title()
            QToolTip.showText(QCursor.pos(), f'{label}\n{stamp}: {number(y)}\n{note()}', canvas)
            return
        for patch in axis.patches:
            hit, _ = patch.contains(event)
            if hit and hasattr(patch, 'get_width'):
                tick = int(round(patch.get_y() + patch.get_height() / 2))
                labels = axis.get_yticklabels()
                label = labels[tick].get_text() if 0 <= tick < len(labels) else axis.get_title()
                QToolTip.showText(QCursor.pos(), f'{label}: {number(patch.get_width())}\n{note()}', canvas)
                return
        QToolTip.hideText()
    canvas.mpl_connect('motion_notify_event', hover)
