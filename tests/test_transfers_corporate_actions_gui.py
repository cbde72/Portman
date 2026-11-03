from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from portfolio_v5.models import BankTransaction, ImportBatch
from portman.analysis_v09 import realized_profit
from portman.repository_v09 import RepositoryV09, reference
from portman.widgets_v09 import ActionsDialog
from portman.workflows_v09 import OperationsDialog


def repository(tmp_path):
    return RepositoryV09(tmp_path / 'gui-actions.sqlite', backups=False)


def transfer_chain(repo):
    repo.commit_batches([ImportBatch('transfer.pdf','transfer',transactions=[
        BankTransaction('A','buy','2026-01-01','BUY','-200','EUR',security='TEST',quantity='2'),
        BankTransaction('A','out','2026-01-02','TRANSFER_OUT','0','EUR',security='TEST',quantity='2'),
        BankTransaction('B','in','2026-01-03','TRANSFER_IN','0','EUR',security='TEST',quantity='2'),
        BankTransaction('B','sell','2026-01-04','SELL','260','EUR',security='TEST',quantity='2')])])


def test_gui_suggests_confirms_and_revokes_security_transfer(tmp_path,qtbot,monkeypatch):
    repo=repository(tmp_path)
    try:
        transfer_chain(repo)
        dialog=ActionsDialog(repo); qtbot.addWidget(dialog)
        assert dialog.security_table.rowCount()==1
        dialog.security_table.selectRow(0)
        dialog.transfer_note.setText('Übertragsbeleg')
        dialog.transfer_out.setCurrentIndex(0); dialog.transfer_in.setCurrentIndex(0)
        qtbot.mouseClick(dialog.confirm_security_button, Qt.MouseButton.LeftButton)
        assert dialog.result()==QDialog.DialogCode.Accepted and len(repo.security_transfer_pairs())==1
        operations=OperationsDialog(repo); qtbot.addWidget(operations)
        pair=repo.security_transfer_pairs()[0]
        monkeypatch.setattr(operations,'selected',lambda key: pair)
        monkeypatch.setattr(operations,'reason',lambda: 'falsche Zuordnung')
        operations.revoke_security_transfer()
        assert repo.security_transfer_pairs()==[]
    finally: repo.close()


def test_gui_creates_and_corrects_documented_spinoff(tmp_path,qtbot):
    repo=repository(tmp_path)
    try:
        dialog=ActionsDialog(repo); qtbot.addWidget(dialog)
        values={'day':'2026-01-02','depot':'A','security':'OLD','target':'NEW','ratio':'0.5',
                'cost_ratio':'0.2','source':'Abspaltungsbeleg'}
        for key,value in values.items(): dialog.action_editors[key].setText(value)
        dialog.action_editors['kind'].setCurrentText('SPINOFF')
        dialog.save_action_button.click()
        action=repo.actions('2026-01-01','2026-12-31')[0]
        assert (action['kind'],action['cost_ratio'])==('SPINOFF','0.2')
        edit=ActionsDialog(repo,action=action); qtbot.addWidget(edit)
        edit.action_editors['cost_ratio'].setText('0.25'); edit.action_editors['source'].setText('Korrekturbeleg')
        edit.save_action_button.click()
        active=repo.actions('2026-01-01','2026-12-31')
        assert len(active)==1 and active[0]['cost_ratio']=='0.25'
    finally: repo.close()


def test_spinoff_and_capital_repayment_change_fifo_only_by_documented_values(tmp_path):
    repo=repository(tmp_path)
    try:
        repo.commit_batches([ImportBatch('actions.pdf','actions',transactions=[
            BankTransaction('A','buy','2026-01-01','BUY','-100','EUR',security='OLD',quantity='10'),
            BankTransaction('A','new-sell','2026-01-03','SELL','30','EUR',security='NEW',quantity='5'),
            BankTransaction('A','old-sell','2026-01-05','SELL','100','EUR',security='OLD',quantity='10')])])
        repo.add_action('2026-01-02','A','OLD','SPINOFF','Abspaltungsbeleg',target='NEW',ratio='0.5',cost_ratio='0.2')
        repo.add_action('2026-01-04','A','OLD','CAPITAL_REPAYMENT','Rückzahlungsbeleg',cost_amount='20',cost_currency='EUR')
        repo.confirm_coverage('A','0001-01-01','2026-12-31')
        rows=realized_profit(repo,'2026-01-01','2026-12-31')
        assert [(r['security'],r['cost'],r['realized']) for r in rows]==[
            ('NEW',Decimal('20'),Decimal('10')),('OLD',Decimal('60'),Decimal('40'))]
    finally: repo.close()


def test_cost_allocating_action_requires_explicit_documented_value(tmp_path):
    repo=repository(tmp_path)
    try:
        import pytest
        with pytest.raises(ValueError,match='Kostenaufteilung'):
            repo.add_action('2026-01-02','A','OLD','RIGHTS','Bezugsrechtsbeleg',target='RIGHT',ratio='1')
    finally: repo.close()
