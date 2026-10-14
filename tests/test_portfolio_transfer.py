import json
from decimal import Decimal
from types import SimpleNamespace
import pytest
from portman.repository_v09 import RepositoryV09
from portman.portfolio_transfer import export_accounts, read_package, import_accounts
from portman.portfolios import (create_portfolio, available_portfolios,
                                set_startup_portfolio, startup_portfolio)
from portfolio_v5.models import ImportBatch, Snapshot, Position, BankTransaction, Balance


def setup_source(path):
    repo = RepositoryV09(path, backups=False)
    repo.save_account('Cash', {'kind': 'Girokonto'})
    repo.save_account('Depot', {'kind': 'Depot'}, 'cash')
    repo.save_account('Private account', {'notes': 'DO NOT EXPORT'})
    repo.add_balance('Cash', '100,00', '2026-01-01')
    repo.commit_batches([ImportBatch('source', 'hash', transactions=[
        BankTransaction('Cash', 'one', '2026-01-02', 'BANK_BOOKING', '20', 'EUR'),
        BankTransaction('Private account', 'private', '2026-01-02', 'BANK_BOOKING', '999', 'EUR')],
        snapshots=[Snapshot('Depot', '2026-01', '2026-01-02', 'Depot', [Position('s', 'Fund', quantity='2', value='50')])],
        balances=[Balance('2026-01', 'Liquidität', 'Cash', '120', 'Online Test 2026-01-02', 1),
                  Balance('2026-01', 'Liquidität', 'Cash', '130', 'Online Test 2026-01-03', 2)])])
    return repo


def test_selection_roundtrip_history_parent_and_duplicate(tmp_path):
    source = setup_source(tmp_path / 'source.sqlite')
    target = RepositoryV09(tmp_path / 'target.sqlite', backups=False)
    try:
        path = tmp_path / 'accounts.portman.json'
        export_accounts(source, {'cash', 'depot'}, path)
        assert 'DO NOT EXPORT' not in path.read_text(encoding='utf-8')
        assert 'Private account' not in path.read_text(encoding='utf-8')
        package = read_package(path)
        assert len(package['batch']['balances']) == 2
        mapping = {'cash': 'Cash Copy', 'depot': 'Depot Copy'}
        assert import_accounts(target, package, mapping)['status'] == 'imported'
        assert import_accounts(target, package, mapping)['status'] == 'duplicate'
        assert target.accounts() == ['Cash Copy', 'Depot Copy']
        assert len(target.transactions()) == 1
        assert len(target.holdings()) == 1
        assert len(target.balance_history('Cash Copy')) == 1
        assert next(r for r in target.account_records() if r['name'] == 'Depot Copy')['parent_key'] == 'cash copy'
        for day, value in [('2026-01-02', Decimal('120')), ('2026-01-03', Decimal('130'))]:
            assert next(r for r in target.account_overview(day) if r['name'] == 'Cash Copy')['balance'] == value
        assert import_accounts(target, package, {'depot': 'Second Depot'})['status'] == 'imported'
        assert len(target.holdings(account='Depot Copy')) == len(target.holdings(account='Second Depot')) == 1
    finally:
        source.close(); target.close()


def test_import_subset_existing_details_and_rollback(tmp_path):
    source = setup_source(tmp_path / 'source.sqlite')
    target = RepositoryV09(tmp_path / 'target.sqlite', backups=False)
    try:
        package = export_accounts(source, {'cash', 'depot'}, tmp_path / 'package.json')
        target.save_account('Existing', {'notes': 'keep'})
        assert import_accounts(target, package, {'cash': 'Existing'})['status'] == 'imported'
        assert target.accounts() == ['Existing']
        assert json.loads(target.account_records()[0]['details'])['notes'] == 'keep'
        package['accounts'][0]['manual'][0]['effective_date'] = 'invalid'
        with pytest.raises(ValueError): import_accounts(target, package, {'cash': 'Broken', 'depot': 'Broken Depot'})
        assert 'Broken' not in target.accounts()
        assert 'Broken Depot' not in target.accounts()
        assert not target.holdings()
        assert len(target.imports()) == 1
    finally:
        source.close(); target.close()


def test_new_empty_and_demo_portfolios_are_independent(tmp_path):
    empty = create_portfolio(tmp_path, 'Another user')
    demo = create_portfolio(tmp_path, 'Demo', True)
    assert empty != demo
    a = RepositoryV09(empty / 'portfolio.sqlite', backups=False)
    b = RepositoryV09(demo / 'portfolio.sqlite', backups=False)
    try:
        assert not a.accounts()
        assert b.accounts() == ['Demo Depot', 'Demo Girokonto']
        assert len(b.holdings()) == 1
        a.save_account('Only here', {})
        assert 'Only here' not in b.accounts()
        assert not (empty / 'banking').exists()
        assert len(available_portfolios(tmp_path)) == 3
        with pytest.raises(ValueError): create_portfolio(tmp_path, 'demo')
    finally:
        a.close(); b.close()


def test_startup_portfolio_can_be_selected_and_falls_back_safely(tmp_path):
    standard = (tmp_path / 'data/v09').resolve()
    custom = create_portfolio(tmp_path, 'Start für Anna')
    assert startup_portfolio(tmp_path) == standard

    assert set_startup_portfolio(tmp_path, custom) == custom.resolve()
    assert startup_portfolio(tmp_path) == custom.resolve()
    saved = json.loads((tmp_path / 'data/startup_portfolio.json').read_text(encoding='utf-8'))
    assert saved['folder'].startswith('data/portfolios/')

    set_startup_portfolio(tmp_path, standard)
    assert startup_portfolio(tmp_path) == standard
    with pytest.raises(ValueError):
        set_startup_portfolio(tmp_path, tmp_path / 'unknown')

    (tmp_path / 'data/startup_portfolio.json').write_text('{broken', encoding='utf-8')
    assert startup_portfolio(tmp_path) == standard


def test_opening_current_portfolio_remembers_it_for_next_start(tmp_path, monkeypatch):
    from portman import portfolio_dialogs
    custom = create_portfolio(tmp_path, 'Zuletzt gewählt')
    calls = []
    window = SimpleNamespace(data_folder=custom, raise_=lambda: calls.append('raise'),
                             activateWindow=lambda: calls.append('activate'))
    monkeypatch.setattr(portfolio_dialogs, 'project_root', lambda: tmp_path)

    portfolio_dialogs.launch_portfolio(window, custom)

    assert startup_portfolio(tmp_path) == custom.resolve()
    assert calls == ['raise', 'activate']


def test_corrupt_package_is_rejected(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{"format":"portman-accounts","version":1,"accounts":[]}', encoding='utf-8')
    with pytest.raises(ValueError): read_package(path)


def test_identifiers_roundtrip_and_existing_account_merge(tmp_path):
    source = RepositoryV09(tmp_path / 'source.sqlite', backups=False)
    target = RepositoryV09(tmp_path / 'target.sqlite', backups=False)
    identifiers = {'iban': 'DE89370400440532013000', 'bic': 'COBADEFFXXX', 'number': '00532013000'}
    try:
        source.save_account('Cash', {**identifiers, 'notes': 'source'})
        source.save_account('Depot', {'number': '0001234567', 'kind': 'Depot'})
        path = tmp_path / 'identifiers.portman.json'
        export_accounts(source, {'cash', 'depot'}, path)
        package = read_package(path)
        assert import_accounts(target, package, {'cash': 'New Cash', 'depot': 'New Depot'})['status'] == 'imported'
        records = {r['name']: json.loads(r['details']) for r in target.account_records()}
        assert all(records['New Cash'][k] == v for k, v in identifiers.items())
        assert records['New Depot']['number'] == '0001234567'
        target.save_account('Parent', {})
        target.save_account('Existing', {'notes': 'keep', 'iban': 'DE89 3704 0044 0532 0130 00'}, 'parent')
        import_accounts(target, package, {'cash': 'Existing'})
        row = next(r for r in target.account_records() if r['name'] == 'Existing')
        details = json.loads(row['details'])
        assert details['notes'] == 'keep'
        assert details['bic'] == identifiers['bic']
        assert details['number'] == identifiers['number']
        assert row['parent_key'] == 'parent'
        assert import_accounts(target, package, {'cash': 'Existing'})['status'] == 'duplicate'
    finally:
        source.close(); target.close()


def test_identifier_conflict_rolls_back_entire_selection(tmp_path):
    source = RepositoryV09(tmp_path / 'source.sqlite', backups=False)
    target = RepositoryV09(tmp_path / 'target.sqlite', backups=False)
    try:
        source.save_account('Cash', {'number': '000123'})
        source.save_account('Depot', {'number': '000456'})
        target.save_account('Existing', {'number': '999999'})
        package = export_accounts(source, {'cash', 'depot'}, tmp_path / 'accounts.json')
        with pytest.raises(ValueError, match='Abweichende'):
            import_accounts(target, package, {'cash': 'New Cash', 'depot': 'Existing'})
        assert target.accounts() == ['Existing']
        assert json.loads(target.account_records()[0]['details'])['number'] == '999999'
        assert not target.imports()
    finally:
        source.close(); target.close()


def test_renamed_accounts_transfer_all_history_and_existing_targets(tmp_path):
    source = setup_source(tmp_path / 'source.sqlite')
    target = RepositoryV09(tmp_path / 'target.sqlite', backups=False)
    try:
        source.save_account('Renamed Cash', {'iban': 'DE89370400440532013000'}, original='Cash')
        source.save_account('Renamed Depot', {'kind': 'Depot'}, 'cash', original='Depot')
        path = tmp_path / 'renamed.portman.json'
        export_accounts(source, {'cash', 'depot'}, path)
        package = read_package(path)
        assert len(package['batch']['transactions']) == 1
        assert len(package['batch']['snapshots']) == 1
        assert len(package['batch']['balances']) == 2
        target.save_account('Old Target', {})
        target.save_account('Renamed Target', {}, original='Old Target')
        assert import_accounts(target, package, {'cash': 'Renamed Target', 'depot': 'New Depot'})['status'] == 'imported'
        assert target.accounts() == ['New Depot', 'Renamed Target']
        assert len(target.transactions(account='Renamed Target')) == 1
        assert len(target.balance_history('Renamed Target')) == 1
        assert len(target.holdings(account='New Depot')) == 1
        assert next(r for r in target.account_records() if r['name'] == 'New Depot')['parent_key'] == 'old target'
        for day, value in [('2026-01-02', Decimal('120')), ('2026-01-03', Decimal('130'))]:
            assert next(r for r in target.account_overview(day) if r['name'] == 'Renamed Target')['balance'] == value
    finally:
        source.close(); target.close()


def test_legacy_package_accepts_stable_key_after_rename(tmp_path):
    source = setup_source(tmp_path / 'source.sqlite')
    target = RepositoryV09(tmp_path / 'target.sqlite', backups=False)
    try:
        path = tmp_path / 'old.portman.json'
        package = export_accounts(source, {'cash'}, path)
        package['accounts'][0]['key'] = 'original cash key'
        package.pop('checksum')
        from portfolio_v5.models import digest
        package['checksum'] = digest(package)
        path.write_text(json.dumps(package), encoding='utf-8')
        loaded = read_package(path)
        import_accounts(target, loaded, {'original cash key': 'Imported'})
        assert len(target.transactions()) == 1
        assert len(target.balance_history('Imported')) == 1
    finally:
        source.close(); target.close()


@pytest.mark.parametrize('cash_target', ['new', 'existing', 'omitted'])
def test_settlement_links_after_account_creation(tmp_path, cash_target):
    source = RepositoryV09(tmp_path / 'source.sqlite', backups=False)
    target = RepositoryV09(tmp_path / 'target.sqlite', backups=False)
    try:
        source.save_account('Z Cash', {'kind': 'Girokonto', 'number': '000123'})
        source.save_account('A Depot', {'kind': 'Depot', 'cash_account_key': 'z cash'}, 'z cash')
        source.save_account('Renamed Cash', {'kind': 'Girokonto', 'number': '000123'}, original='Z Cash')
        package = export_accounts(source, {'a depot', 'z cash'}, tmp_path / 'settlement.json')
        targets = {'a depot': 'Imported Depot'}
        if cash_target != 'omitted':
            targets['z cash'] = 'Imported Cash'
        if cash_target == 'existing':
            target.save_account('Original Cash', {'kind': 'Verrechnungskonto'})
            target.save_account('Imported Cash', {'kind': 'Verrechnungskonto'}, original='Original Cash')
        assert import_accounts(target, package, targets)['status'] == 'imported'
        depot = next(r for r in target.account_records() if r['name'] == 'Imported Depot')
        details = json.loads(depot['details'])
        if cash_target == 'omitted':
            assert not details.get('cash_account_key')
            assert depot['parent_key'] is None
            assert target.accounts() == ['Imported Depot']
        else:
            cash = next(r for r in target.account_records() if r['name'] == 'Imported Cash')
            assert details['cash_account_key'] == cash['account_key']
            assert depot['parent_key'] == cash['account_key']
        assert import_accounts(target, package, targets)['status'] == 'duplicate'
    finally:
        source.close(); target.close()


def test_import_reports_visible_progress(tmp_path):
    source = setup_source(tmp_path / 'source.sqlite')
    target = RepositoryV09(tmp_path / 'target.sqlite', backups=False)
    updates = []
    try:
        package = export_accounts(source, {'cash', 'depot'}, tmp_path / 'progress.json')
        result = import_accounts(target, package, {'cash': 'Cash', 'depot': 'Depot'},
                                 lambda current, total, text: updates.append((current, total, text)))
        assert result['status'] == 'imported'
        assert updates[0][0] == 0
        assert updates[-1][0] == updates[-1][1]
        determinate = [current for current, total, _ in updates if total]
        assert determinate == sorted(determinate)
        assert any(total == 0 for _, total, _ in updates)
        assert any('Buchungen, Salden und Depotstände' in text for _, _, text in updates)
        assert any('Historie' in text for _, _, text in updates)
    finally:
        source.close(); target.close()
