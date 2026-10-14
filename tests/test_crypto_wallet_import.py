import csv
import os
from decimal import Decimal
import pytest
from portman.crypto_wallet_import import COLUMNS, read_wallet_csv, save_wallet
from portman.repository import PortfolioRepository


def write_csv(tmp_path, changes=None, delimiter=';', encoding='utf-8-sig'):
    rows = []
    for i, change in enumerate(changes or [{}]):
        row = dict.fromkeys(COLUMNS, '')
        row.update({'Dateiname': f'Kauf-{i}.pdf', 'Depot-Nr.': '123', 'Vorgangs-Nr.': str(i),
                    'Wertpapierbezeichnung': 'Bitcoin', 'Handelsdatum': '07.10.2026',
                    'Nominale_num': '0.001', 'Endbetrag_num': '-60.50'})
        row.update(change); rows.append(row)
    path = tmp_path / 'wallet.csv'
    with path.open('w', encoding=encoding, newline='') as handle:
        writer = csv.DictWriter(handle, COLUMNS, delimiter=delimiter)
        writer.writeheader(); writer.writerows(rows)
    return path


@pytest.mark.parametrize('delimiter,encoding', [(';', 'utf-8-sig'), (',', 'utf-8'), ('\t', 'cp1252')])
def test_precision_and_cash_free_import(tmp_path, delimiter, encoding):
    batch = read_wallet_csv(write_csv(tmp_path, delimiter=delimiter, encoding=encoding), 'Wallet')
    position = batch.snapshots[-1].positions[0]
    assert Decimal(position.quantity) == Decimal('0.001')
    assert Decimal(position.cost) == Decimal('60.50')
    assert position.value is None
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    try:
        save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch)
        assert len(repo.holdings()) == 1
        assert not repo.balances()
        assert repo.transactions()[0]['affects_cash'] is False
    finally:
        repo.close()


def test_fifo_and_complete_sale(tmp_path):
    path = write_csv(tmp_path, [
        {'Handelsdatum': '01.10.2026', 'Nominale_num': '2', 'Endbetrag_num': '100'},
        {'Handelsdatum': '02.10.2026', 'Nominale_num': '1', 'Endbetrag_num': '80'},
        {'Handelsdatum': '03.10.2026', 'Nominale_num': '-2.5', 'Endbetrag_num': '200'},
        {'Handelsdatum': '04.10.2026', 'Nominale_num': '-0.5', 'Endbetrag_num': '50'}])
    batch = read_wallet_csv(path, 'Wallet', 'signed')
    assert Decimal(batch.snapshots[-2].positions[0].cost) == Decimal('40')
    assert batch.snapshots[-1].positions == []


def test_wallet_timeline_survives_reopening(tmp_path):
    from portman.repository_v09 import RepositoryV09
    path = write_csv(tmp_path, [
        {'Handelsdatum': '01.10.2026', 'Nominale_num': '2', 'Endbetrag_num': '100'},
        {'Handelsdatum': '01.10.2026', 'Nominale_num': '1', 'Endbetrag_num': '80'},
        {'Handelsdatum': '03.10.2026', 'Nominale_num': '-2.5', 'Endbetrag_num': '200'},
        {'Handelsdatum': '04.10.2026', 'Nominale_num': '-0.5', 'Endbetrag_num': '50'}])
    database = tmp_path / 'timeline.sqlite'
    repo = RepositoryV09(database, backups=False)
    try:
        save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None,
                    read_wallet_csv(path, 'Wallet-Vorschau', 'signed'))
    finally:
        repo.close()
    repo = RepositoryV09(database, backups=False)
    try:
        assert {day for _, day in repo.scope_dates()} == {
            '2026-10-01', '2026-10-03', '2026-10-04'}
        assert not repo.holdings('2026-09-30', 'Wallet')
        for day, quantity, cost in [('2026-10-01', '3', '180'),
                                    ('2026-10-02', '3', '180'),
                                    ('2026-10-03', '0.5', '40')]:
            position, = repo.holdings(day, 'Wallet')
            assert Decimal(position['quantity']) == Decimal(quantity)
            assert Decimal(position['cost']) == Decimal(cost)
        assert not repo.holdings('2026-10-04', 'Wallet')
        assert len(repo.transactions()) == 4
    finally:
        repo.close()


@pytest.mark.parametrize('change,mode', [({'Nominale_num': 'NaN'}, 'buys'),
    ({'Nominale_num': '-1'}, 'signed'), ({'Dateiname': 'Verkauf.pdf'}, 'buys'),
    ({'Dateiname': '123.pdf'}, 'filename'), ({'Handelsdatum': '31.02.2026'}, 'buys')])
def test_reject_bad_or_incomplete_history(tmp_path, change, mode):
    with pytest.raises(ValueError):
        read_wallet_csv(write_csv(tmp_path, [change]), 'Wallet', mode)


def test_save_rollback(tmp_path, monkeypatch):
    batch = read_wallet_csv(write_csv(tmp_path), 'Wallet')
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    def fail(batches):
        repo.store.import_batch(batches[0])
        return [{'status': 'error', 'errors': ['Testfehler']}]
    monkeypatch.setattr(repo, 'commit_batches', fail)
    try:
        with pytest.raises(ValueError, match='Testfehler'):
            save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch)
        assert not repo.accounts()
        assert not repo.imports()
    finally:
        repo.close()


def test_editor_stage_cancel_save(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from portman.account_editor import AccountEditor
    QApplication.instance() or QApplication([])
    repo = PortfolioRepository(tmp_path / 'test.sqlite')
    try:
        editor = AccountEditor(repo)
        editor.kind.setCurrentText('Krypto Wallet')
        editor.fields['name'].setText('Mein Wallet')
        editor.crypto_import.path = str(write_csv(tmp_path))
        editor.crypto_import.reload()
        assert editor.crypto_import.table.rowCount() == 1
        assert not repo.accounts()
        editor.reject()
        assert not repo.accounts()
        editor.save()
        assert repo.accounts() == ['Mein Wallet']
        assert repo.holdings()[0]['account'] == 'Mein Wallet'
    finally:
        repo.close()


@pytest.mark.parametrize('version', ['base', 'v09'])
def test_import_keeps_gui_responsive(tmp_path, monkeypatch, version):
    from threading import Event
    from PySide6.QtCore import QThread, QTimer
    from PySide6.QtWidgets import QApplication
    from portman.account_editor import AccountEditor
    from portman import crypto_wallet_import, crypto_wallet_panel
    app = QApplication.instance() or QApplication([])
    from portman.repository_v09 import RepositoryV09
    factory = RepositoryV09 if version == 'v09' else PortfolioRepository
    repo = factory(tmp_path / 'responsive.sqlite')
    ticks, workers = [], []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    def wrap(function):
        def checked(*args, **kwargs):
            workers.append(QThread.currentThread() != app.thread())
            Event().wait(.05)
            return function(*args, **kwargs)
        return checked
    monkeypatch.setattr(crypto_wallet_panel, 'read_wallet_csv', wrap(crypto_wallet_panel.read_wallet_csv))
    monkeypatch.setattr(crypto_wallet_import, 'save_wallet', wrap(crypto_wallet_import.save_wallet))
    editor = AccountEditor(repo)
    try:
        editor.kind.setCurrentText('Krypto Wallet')
        editor.fields['name'].setText('Wallet')
        editor.crypto_import.path = str(write_csv(tmp_path))
        timer.start(5)
        editor.crypto_import.reload()
        assert ticks
        ticks.clear()
        editor.save()
        assert ticks
        assert workers == [True, True]
        assert repo.holdings()[0]['account'] == 'Wallet'
    finally:
        timer.stop()
        editor.close()
        repo.close()


@pytest.mark.parametrize('version', ['base', 'v09'])
def test_cancel_wallet_save_rolls_back_history(tmp_path, version):
    from portman.repository_v09 import RepositoryV09
    factory = RepositoryV09 if version == 'v09' else PortfolioRepository
    repo = factory(tmp_path / 'cancel.sqlite')
    try:
        batch = read_wallet_csv(write_csv(tmp_path), 'Wallet')
        with pytest.raises(ValueError, match='abgebrochen'):
            save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch,
                        cancelled=lambda: bool(repo.imports()))
        assert not repo.accounts()
        assert not repo.imports()
        assert not repo.snapshots()
        if version == 'v09':
            assert repo.backups_enabled
    finally:
        repo.close()


def test_wallet_backup_precedes_write_transaction(tmp_path, monkeypatch):
    from portman.repository_v09 import RepositoryV09
    repo = RepositoryV09(tmp_path / 'backup.sqlite', backups=True)
    original_backup = repo.backup
    backups = []
    def checked_backup(reason):
        assert not repo.db.in_transaction, 'SQLite backup inside wallet write transaction would hang'
        backups.append(original_backup(reason))
    monkeypatch.setattr(repo, 'backup', checked_backup)
    try:
        batch = read_wallet_csv(write_csv(tmp_path), 'Wallet')
        save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch)
        assert len(backups) == 1
        assert repo.backups_enabled
        assert len(repo.holdings()) == 1
        previous = RepositoryV09(backups[0], backups=False)
        try:
            assert not previous.accounts()
            assert not previous.imports()
        finally:
            previous.close()
    finally:
        repo.close()


def test_duplicates_and_german_values(tmp_path):
    change = {'Vorgangs-Nr.': 'same', 'Dateiname': 'Kauf.pdf', 'Nominale_num': '',
              'Nominale': '0,00001234', 'Endbetrag_num': '', 'Endbetrag': '-1.234,56 EUR'}
    path = write_csv(tmp_path, [change, change])
    batch = read_wallet_csv(path, 'Wallet')
    assert len(batch.transactions) == 1
    assert Decimal(batch.snapshots[-1].positions[0].cost) == Decimal('1234.56')
    path = write_csv(tmp_path, [change, {**change, 'Endbetrag': '100'}])
    with pytest.raises(ValueError, match='unterschiedlichen Daten'):
        read_wallet_csv(path, 'Wallet')


def test_baader_crypto_summary_format(tmp_path):
    path = write_csv(tmp_path, [
        {'ISIN': 'BTC', 'WKN': 'BTC', 'Handelsuhrzeit': '16:25:24:90',
         'Stamm-Nr.': '123', 'Vorgangs-Nr.': 'KRY 123\nAbrechnung',
         'Kurswert_num': '60,50', 'Endbetrag_num': '60,50'},
        {'ISIN': 'BTC', 'WKN': 'BTC', 'Handelsuhrzeit': '16:25:24:91',
         'Kurswert_num': '60,50', 'Endbetrag_num': '60,50'}])
    footer = dict.fromkeys(COLUMNS, '')
    footer.update(Kurswert='121,00', Kurswert_num='121,00', Endbetrag_num='121,00')
    with path.open('a', encoding='utf-8', newline='') as handle:
        csv.DictWriter(handle, COLUMNS, delimiter=';').writerow(footer)
    batch = read_wallet_csv(path, 'Wallet')
    assert len(batch.transactions) == 2
    position = batch.snapshots[-1].positions[0]
    assert position.key == 'KRYPTO:btc'
    assert position.isin == position.wkn == ''
    assert Decimal(position.quantity) == Decimal('0.002')
    assert Decimal(position.cost) == Decimal('121')
    path.write_text(path.read_text(encoding='utf-8-sig').replace('121,00', '122,00'), encoding='utf-8')
    with pytest.raises(ValueError, match='Summenzeile'):
        read_wallet_csv(path, 'Wallet')


def test_v09_wallet_and_source_change(tmp_path):
    from portman.repository_v09 import RepositoryV09
    path = write_csv(tmp_path)
    batch = read_wallet_csv(path, 'Wallet')
    repo = RepositoryV09(tmp_path / 'v09.sqlite', backups=False)
    try:
        path.write_text('changed', encoding='utf-8')
        with pytest.raises(ValueError, match='verändert'):
            save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch)
        assert not repo.accounts()
        path = write_csv(tmp_path)
        save_wallet(repo, 'Wallet', {'kind': 'Krypto Wallet'}, None, batch)
        assert repo.current()[0]['asset_type'] == 'Krypto'
        assert repo.current()[0]['value'] is None
        assert repo.account_overview()[0]['balance'] is None
    finally:
        repo.close()
