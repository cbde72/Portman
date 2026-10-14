import os
from types import SimpleNamespace
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portman.baader_pdf_import import baader_pdf_files


def test_recursive_pdf_discovery_ignores_other_files(tmp_path):
    for name in ('root.pdf', '2026/02/statement.PDF', '2025/report.pdf', '2026/note.txt'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test')
    (tmp_path / 'directory.pdf').mkdir()
    assert [p.relative_to(tmp_path).as_posix() for p in baader_pdf_files(tmp_path)] == [
        '2025/report.pdf', '2026/02/statement.PDF', 'root.pdf']
    assert baader_pdf_files(tmp_path / 'directory.pdf') == []
    with pytest.raises(ValueError, match='nicht gefunden'):
        baader_pdf_files(tmp_path / 'missing')


def test_baader_folder_action_uses_existing_import_pipeline(tmp_path, monkeypatch):
    from portman.gui import window_shell as gui
    from portman.gui import import_flow
    path = tmp_path / 'nested' / 'statement.pdf'
    path.parent.mkdir()
    path.write_bytes(b'test')
    selections = []
    messages = []
    window = SimpleNamespace(settings={}, status_bar=SimpleNamespace(showMessage=lambda *args: messages.append(args)),
                             run_repository_import=lambda paths: selections.append(paths))
    monkeypatch.setattr(import_flow.QFileDialog, 'getExistingDirectory', lambda *args: str(tmp_path))
    gui.MainWindow.import_baader_pdf(window)
    assert selections == [[path]]
    assert window.settings['baader_pdf_folder'] == str(tmp_path)
    assert window.settings['last_import_folder'] == str(tmp_path.resolve())
    dialog_calls = []
    monkeypatch.setattr(import_flow.QFileDialog, 'getExistingDirectory',
                        lambda *args: dialog_calls.append(args) or '')
    gui.MainWindow.import_baader_pdf(window)
    assert len(selections) == 1
    assert dialog_calls[0][2] == str(tmp_path.resolve())


def test_import_menu_separates_file_actions(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from portman.gui import window_shell as gui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(gui, 'HAS_WEBENGINE', False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    window = gui.MainWindow()
    try:
        labels = [a.text() for a in window.import_menu.actions()]
        assert any('Baader' in text and 'rekursiv' in text for text in labels)
        assert any('Renault' in text for text in labels)
        assert any('Tagesgeld' in text for text in labels)
        file_menu = next(a.menu() for a in window.menuBar().actions() if 'Datei' in a.text())
        assert not any('importieren' in a.text() for a in file_menu.actions())
    finally:
        window.close()
        app.processEvents()
