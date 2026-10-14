"""Shared post-construction installs for the V07 and V09 windows."""
from portman.gui.position_tables import install_edit_button
from portman.gui.quality_issues import install_quality_links
from portman.gui.version_menu import install_version_menu
from portman.widgets_shared import TablePreferences


def install_version_basics(window, title):
    window.guided_import = True
    window.lock_docks_action.setText('Layout bearbeiten')
    window.lock_docks_action.setChecked(window.lock_editable_checked())
    window.set_docks_locked(window.settings.get('dock_layout_locked', True))
    window.install_latest_scope()
    install_version_menu(window, title)
    install_quality_links(window)
    install_edit_button(window)
    window.preferences = TablePreferences(window)
