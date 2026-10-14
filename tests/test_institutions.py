import json
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portman.repository import PortfolioRepository
from portman.institutions import account_institution


def test_rename_inherited_inactive_and_inferred_accounts_survives_reopen(tmp_path):
    path = tmp_path / 'test.sqlite'
    repo = PortfolioRepository(path)
    repo.save_account('ING Giro', {'owner': 'Test'})
    repo.save_account('Reserve', {'kind': 'Tagesgeld'}, parent='ING Giro')
    repo.save_account('Archiv', {'institution': 'ING'})
    repo.set_account_active('Archiv', False)
    repo.save_account('Andere', {'institution': 'Fremdbank'}, parent='ING Giro')
    repo.add_balance('ING Giro', '100', '2026-09-01')
    before = {r['account_key']: r for r in repo.account_records()}
    assert repo.rename_institution('ING', ' Meine Bank ') == 3
    repo.close()
    repo = PortfolioRepository(path)
    after = {r['account_key']: r for r in repo.account_records()}
    assert after.keys() == before.keys()
    for key, record in after.items():
        assert record['name'] == before[key]['name']
        assert record['parent_key'] == before[key]['parent_key']
        assert record['active'] == before[key]['active']
        assert account_institution(record, after) == ('Fremdbank' if record['name'] == 'Andere' else 'Meine Bank')
    giro = next(record for record in after.values() if record['name'] == 'ING Giro')
    assert json.loads(giro['details'])['owner'] == 'Test'
    assert next(row for row in repo.account_overview() if row['name'] == 'ING Giro')['balance'] == 100
    repo.close()


def test_collision_and_empty_name_do_not_change_data(tmp_path):
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.save_account('Eins', {'institution': 'Bank A'})
    repo.save_account('Zwei', {'institution': 'Bank B'})
    before = repo.account_records()
    for name in (' ', 'BANK B', 'x' * 121):
        with pytest.raises(ValueError):
            repo.rename_institution('Bank A', name)
        assert repo.account_records() == before
    repo.rename_institution('Bank A', 'bank a')
    assert json.loads(repo.account_records()[0]['details'])['institution'] == 'bank a'
    repo.close()


def test_rename_button_uses_selected_institution(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QInputDialog
    from portman.accounts_widget import AccountsWidget
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    repo.save_account('Konto', {'institution': 'Bank'})
    widget = AccountsWidget(repo, lambda: '9999-12-31')
    widget.tree.setCurrentItem(widget.tree.topLevelItem(0))
    assert widget.rename_institute.isEnabled()
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **kw: ('Neuer Name', True))
    widget.rename_institute.click()
    assert widget.tree.topLevelItem(0).text(0) == 'Neuer Name'
    assert widget.tree.topLevelItem(0).child(0).text(0) == 'Konto'
    widget.tree.setCurrentItem(widget.tree.topLevelItem(0).child(0))
    assert not widget.rename_institute.isEnabled()
    widget.close()
    repo.close()
