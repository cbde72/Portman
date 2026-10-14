"""Consistent, readable account selectors used by import dialogs."""


def style_target_account_combo(combo):
    """Give long account names enough room without oversized popup text."""
    font = combo.font()
    font.setPointSizeF(9.0)
    combo.setFont(font)
    combo.setMinimumHeight(38)
    combo.setMaxVisibleItems(18)

    view = combo.view()
    view.setFont(font)
    view.setSpacing(1)
    view.setStyleSheet(
        'QAbstractItemView { font-size: 9pt; } '
        'QAbstractItemView::item { min-height: 34px; padding: 5px 8px; }'
    )
    return combo
