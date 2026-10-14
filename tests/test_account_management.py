import tempfile
import unittest
from pathlib import Path
from portman.repository import PortfolioRepository
from portfolio_v5.models import ImportBatch, Balance

class AccountManagementTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.repo = PortfolioRepository(Path(self.folder.name) / 'test.sqlite')
    def tearDown(self):
        self.repo.close(); self.folder.cleanup()
    def test_hierarchy_and_deletion(self):
        r = self.repo
        r.save_account('Bank', {})
        r.save_account('Sparen', {'kind': 'Tagesgeld', 'interest': '2,5'}, 'bank')
        with self.assertRaises(ValueError): r.save_account('Bank', {}, 'sparen', 'Bank')
        r.set_account_active('Bank', False)
        self.assertEqual(r.accounts(), ['Sparen'])
        self.assertIsNone(next(x for x in r.account_records() if x['name']=='Sparen')['parent_key'])
    def test_balance_revisions_and_dates(self):
        r = self.repo; r.save_account('Bank', {})
        r.add_balance('Bank', '100', '2026-01-01')
        r.add_balance('Bank', '200', '2026-01-01')
        r.add_balance('Bank', '300', '2026-02-01')
        self.assertEqual(len(r.balance_history('Bank')), 3)
        self.assertEqual(r.account_overview('2026-01-31')[0]['balance'], 200)
        self.assertEqual(r.wealth_summary('2026-01-31')['value'], 200)
        self.assertEqual([x['total'] for x in r.wealth_series()], [200, 300])
        self.assertIsNone(r.account_overview('2025-12-31')[0]['balance'])
    def test_correction_keeps_original_and_is_atomic(self):
        r = self.repo
        iid = r.commit_batches([ImportBatch('test', 'hash', balances=[Balance('2026-01','Liquidität','Bank','100','ETF',1)])])[0]['id']
        bid = r.db.execute('SELECT id FROM balances').fetchone()[0]
        with self.assertRaises(ValueError): r.correct_import(iid, {'balances': {bid: {'value':'NaN'}}})
        self.assertEqual(len(r.imports()), 1)
        r.correct_import(iid, {'balances': {bid: {'value':'200'}}})
        self.assertEqual(r.balances()[0]['value'], '200.00')
        self.assertEqual(r.db.execute('SELECT value FROM balances WHERE id=?',(bid,)).fetchone()[0], '100')
        self.assertFalse(next(x for x in r.imports() if x['id']==iid)['active'])

def test_full_account_name_checked_while_typing(tmp_path):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from portman.account_editor import AccountEditor
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'names.sqlite')
    repo.save_account('Bank Tagesgeld', {})
    editor = AccountEditor(repo)
    assert not editor.save_button.isEnabled()
    editor.fields['name'].setText('  BANK   Tagesgeld  ')
    assert not editor.save_button.isEnabled()
    assert 'bereits' in editor.name_status.text()
    for name in ['Bank', 'Bank Festgeld', 'Bank Tagesgeld 2']:
        editor.fields['name'].setText(name)
        assert editor.save_button.isEnabled()
    editor.save()
    assert 'Bank Tagesgeld 2' in repo.accounts()
    editor.close()
    record = next(r for r in repo.account_records() if r['name'] == 'Bank Tagesgeld')
    editor = AccountEditor(repo, record)
    assert editor.save_button.isEnabled()
    editor.fields['name'].setText('Bank Tagesgeld 2')
    assert not editor.save_button.isEnabled()
    editor.close(); repo.close()
