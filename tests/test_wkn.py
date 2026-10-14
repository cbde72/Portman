import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from portfolio_v5.models import ImportBatch, Position, Snapshot
from portman.repository_v09 import RepositoryV09
from portman.positions_model import PositionsModel, HEADERS
from portman.gui import position_tables


def seed(repo, day='2026-01-01'):
    repo.commit_batches([ImportBatch(day, day, snapshots=[Snapshot('Depot', day[:7], day, 'Online', [
        Position('US0378331005', 'Apple', isin='US0378331005', quantity='1', value='100')])])])


def test_wkn_survives_import_and_restart(tmp_path):
    path = tmp_path / 'wkn.sqlite'
    repo = RepositoryV09(path, backups=False)
    seed(repo)
    with repo.db:
        repo.db.execute("INSERT INTO security_master(security_key,wkn,canonical_name) VALUES('WKN:865985','865985','Apple')")
    repo.save_wkn('US0378331005', ' 865985 ')
    seed(repo, '2026-02-01')
    assert repo.current()[0]['wkn'] == '865985'
    repo.close()
    repo = RepositoryV09(path, backups=False)
    try:
        assert repo.current()[0]['wkn'] == '865985'
        for bad in ('', '12345', '1234567', 'A B123', 'Ä12345'):
            with pytest.raises(ValueError): repo.save_wkn('US0378331005', bad)
        with pytest.raises(ValueError): repo.save_wkn('missing', '123456')
        assert repo.current()[0]['wkn'] == '865985'
    finally:
        repo.close()


def test_wkn_cell_opens_editor_and_saves(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = RepositoryV09(tmp_path / 'ui.sqlite', backups=False)
    seed(repo)
    model = PositionsModel()
    model.reset([SimpleNamespace(isin='US0378331005', wkn='', name='Apple', buy_value=0)], {})
    refreshed = []
    window = SimpleNamespace(repository=repo, reload_portfolio=lambda: refreshed.append(True))
    monkeypatch.setattr(position_tables.QInputDialog, 'getText', lambda *args, **kwargs: ('865985', True))
    try:
        assert position_tables.edit_wkn_cell(window, model.index(0, HEADERS.index('WKN')))
        assert repo.current()[0]['wkn'] == '865985' and refreshed == [True]
        assert not position_tables.edit_wkn_cell(window, model.index(0, 1))
        monkeypatch.setattr(position_tables.QInputDialog, 'getText', lambda *args, **kwargs: ('', False))
        assert position_tables.edit_wkn_cell(window, model.index(0, HEADERS.index('WKN')))
        assert refreshed == [True]
    finally:
        repo.close()


def test_later_isin_reuses_existing_wkn_master_key(tmp_path):
    repo = RepositoryV09(tmp_path / 'later-isin.sqlite', backups=False)
    try:
        with repo.db:
            repo.db.execute("""INSERT INTO security_master
                (security_key,isin,wkn,canonical_name) VALUES('WKN:865985','US0378331005','865985','Apple')""")
        seed(repo)

        rows = repo.db.execute(
            'SELECT security_key,isin,wkn FROM security_master WHERE isin=?', ('US0378331005',)).fetchall()
        assert [tuple(row) for row in rows] == [('WKN:865985', 'US0378331005', '865985')]
    finally:
        repo.close()
