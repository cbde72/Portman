import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from portman.repository import PortfolioRepository
from portman.accounts_widget import AccountsWidget
from portfolio_v5.models import ImportBatch,Snapshot,Position


def test_collapsed_hierarchy_and_sum_without_double_counting(tmp_path):
    QApplication.instance() or QApplication([])
    repo=PortfolioRepository(tmp_path/'test.sqlite')
    repo.save_account('Bank',{})
    repo.save_account('Cash',{},'bank')
    repo.save_account('Depot',{'kind':'Depot'},'bank')
    repo.save_account('Reserve',{},'cash')
    repo.add_balance('Cash','100','2026-01-01')
    repo.add_balance('Reserve','25','2026-01-01')
    repo.add_balance('Depot','200','2026-01-01')
    repo.commit_batches([ImportBatch('positions','hash',snapshots=[Snapshot('Depot','2026-01','2026-01-01','Depot',[Position('s','Aktie',quantity='1',value='200')])])])
    widget=AccountsWidget(repo,lambda:'2026-01-31')
    root=widget.tree.topLevelItem(0)
    assert root.text(0)=='Ohne Institut'
    assert root.child(0).text(0)=='Bank'
    assert root.text(6)=='325,00 €'
    assert root.text(1)=='200,00 €'
    assert root.text(2)=='325,00 €'
    assert not root.isExpanded()
    for i in range(root.childCount()):
        assert not root.child(i).isExpanded()
    assert widget.tree.isColumnHidden(1)
    assert not widget.tree.isColumnHidden(6)
    widget.tree.setColumnWidth(0, 345)
    root.setExpanded(True);widget.refresh()
    assert widget.tree.topLevelItem(0).isExpanded()
    assert widget.tree.columnWidth(0) == 345
    widget.show_extra.setChecked(True)
    assert not widget.tree.isColumnHidden(1)
    widget.refresh()
    assert not widget.tree.isColumnHidden(1)
    assert widget.tree.topLevelItem(0).text(7) != '–' 
    widget.close();repo.close()


def test_institution_groups_preserve_accounts_and_selection(tmp_path):
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'groups.sqlite')
    repo.save_account('comdirect Giro', {})
    repo.save_account('Reserve', {'institution': ' COMDIRECT '})
    repo.save_account('Fremdbank', {'institution': 'Andere Bank'}, 'reserve')
    repo.save_account('Unbekannt', {})
    repo.add_balance('comdirect Giro', '100', '2026-01-01')
    repo.add_balance('Reserve', '25', '2026-01-02')
    repo.add_balance('Fremdbank', '50', '2026-01-02')
    before = repo.account_records()
    widget = AccountsWidget(repo, lambda: '2026-01-31')
    groups = {widget.tree.topLevelItem(i).text(0).casefold(): widget.tree.topLevelItem(i)
              for i in range(widget.tree.topLevelItemCount())}
    group = groups['comdirect']
    assert group.childCount() == 2
    assert group.text(6) == '125,00 €'
    assert group.text(7) == 'Mehrere Stände'
    assert groups['andere bank'].text(6) == '50,00 €'
    assert groups['ohne institut'].child(0).text(0) == 'Unbekannt'
    assert not group.isExpanded()
    selected = []
    widget.account_selected.connect(selected.append)
    widget.select_account(group, 0)
    assert selected == []
    account = group.child(0)
    widget.select_account(account, 0)
    assert selected == [account.text(0)]
    group.setExpanded(True)
    widget.tree.setCurrentItem(account)
    widget.refresh()
    assert widget.tree.currentItem().text(0) == selected[0]
    assert widget.tree.currentItem().parent().isExpanded()
    assert repo.account_records() == before
    widget.close()
    repo.close()
