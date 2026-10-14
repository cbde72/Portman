"""Tests für das frei konfigurierbare Diagramm-Raster und die Depot-Auswahl."""
import os

os.environ.setdefault('MPLBACKEND', 'Agg')

import matplotlib
matplotlib.use('Agg')

import pytest
from portfolio_v5.models import ImportBatch, Snapshot, Position
from PySide6.QtCore import Qt
from portman.repository_v09 import RepositoryV09
from portman.chart_config import ChartConfig, ALL_ACCOUNTS
from portman.chart_data import prepare_chart_for_config


@pytest.fixture
def repo(tmp_path):
    r = RepositoryV09(tmp_path / 'grid.sqlite', backups=False)
    r.commit_batches([ImportBatch('test', 'test', snapshots=[
        Snapshot('Depot A', '2026-01', '2026-01-01', 'Test',
                 [Position('A', 'Aktie A', quantity='1', value='100', cost='80')]),
        Snapshot('Depot B', '2026-01', '2026-01-01', 'Test',
                 [Position('B', 'Aktie B', quantity='2', value='400', cost='300')]),
    ])])
    yield r
    r.close()


def _keys(data):
    return [p['key'] for p in data['positions']]


def test_prepare_chart_for_config_supports_position_subset(repo):
    data = prepare_chart_for_config(repo, 'positions', '2026-02-01', None)
    keys = _keys(data)
    assert len(keys) >= 2
    subset = prepare_chart_for_config(repo, 'positions', '2026-02-01', None,
                                      {'positions': [keys[0]]})
    assert _keys(subset) == [keys[0]]


def test_prepare_chart_for_config_supports_account_override(repo):
    accounts = repo.accounts()
    assert len(accounts) >= 2
    first, second = accounts[0], accounts[1]
    scoped = prepare_chart_for_config(repo, 'positions', '2026-02-01', None, {'account': first})
    assert scoped['positions']
    assert all(first in p.get('accounts', set()) for p in scoped['positions'])
    other = prepare_chart_for_config(repo, 'positions', '2026-02-01', None, {'account': second})
    assert {p['key'] for p in scoped['positions']}.isdisjoint({p['key'] for p in other['positions']})


def test_prepare_chart_for_config_all_accounts_sentinel(repo):
    accounts = repo.accounts()
    everything = prepare_chart_for_config(repo, 'positions', '2026-02-01', None)
    forced_all = prepare_chart_for_config(repo, 'positions', '2026-02-01', accounts[0],
                                          {'account': ALL_ACCOUNTS})
    assert {p['key'] for p in forced_all['positions']} == {p['key'] for p in everything['positions']}


def test_grid_store_roundtrip(tmp_path):
    from portman.chart_grid import ChartGridStore
    store = ChartGridStore(tmp_path / 'grid.json')
    config = ChartConfig(id='a', title='Wert', chart_type='line', data_source='wealth')
    store.save(2, 3, {'0,0': config})
    state = store.load()
    assert state['rows'] == 2 and state['cols'] == 3
    assert state['cells']['0,0']['title'] == 'Wert'
    assert ChartConfig.from_dict(state['cells']['0,0']).data_source == 'wealth'


def test_grid_store_handles_missing_or_broken_file(tmp_path):
    from portman.chart_grid import ChartGridStore
    assert ChartGridStore(tmp_path / 'missing.json').load() == {}
    broken = tmp_path / 'broken.json'
    broken.write_text('{not json', encoding='utf-8')
    assert ChartGridStore(broken).load() == {}


def test_grid_widget_persists_cells_and_renders(repo, qtbot):
    from portman.chart_grid import ChartGridWidget, ChartGridStore, default_grid_path
    widget = ChartGridWidget(repo, lambda: (None, '2026-02-01'))
    qtbot.addWidget(widget)
    try:
        assert len(widget.tiles) == widget.rows * widget.cols
        config = ChartConfig(id='grid_0', title='Positionen', chart_type='barh',
                             data_source='positions', options={'top_n': 10, 'sort_by': 'value'})
        widget.set_cell('0,0', config)
        assert widget.cells['0,0'].title == 'Positionen'

        widget.spin_cols.setValue(3)
        widget.spin_rows.setValue(2)
        assert widget.cols == 3 and widget.rows == 2
        assert len(widget.tiles) == 6

        widget.refresh()
        assert widget.tile_map['0,0']._figure.axes

        state = ChartGridStore(default_grid_path(repo)).load()
        assert state['rows'] == 2 and state['cols'] == 3
        assert state['cells']['0,0']['title'] == 'Positionen'
    finally:
        widget.close()


def test_grid_widget_clear_all_removes_cells(repo, qtbot):
    from portman.chart_grid import ChartGridWidget
    widget = ChartGridWidget(repo, lambda: (None, '2026-02-01'))
    qtbot.addWidget(widget)
    try:
        widget.set_cell('0,0', ChartConfig(id='g', title='T', chart_type='bar',
                                           data_source='positions'))
        assert widget.cells
        widget.clear_all()
        assert widget.cells == {}
    finally:
        widget.close()


def test_chart_config_dialog_exposes_scope_selection(repo, qtbot):
    from portman.chart_config_dialog import ChartConfigDialog
    config = ChartConfig(id='grid_0', title='Test', chart_type='barh', data_source='positions',
                         options={'top_n': 10, 'sort_by': 'value', 'account': ALL_ACCOUNTS})
    dialog = ChartConfigDialog(config, repo=repo, scope_getter=lambda: (None, '2026-02-01'))
    qtbot.addWidget(dialog)
    try:
        dialog._preview_timer.stop()
        assert dialog.account_scope.currentData() == ALL_ACCOUNTS
        assert dialog.positions_list.count() >= 2
        # Einzelne Position abwählen -> explizite Auswahl in den Optionen.
        dialog.positions_list.item(0).setCheckState(Qt.CheckState.Unchecked)
        built = dialog._build_config(require_id=True)
        assert built.options.get('account') == ALL_ACCOUNTS
        assert len(built.options.get('positions', [])) == dialog.positions_list.count() - 1
    finally:
        dialog._preview_timer.stop()
        dialog.close()
