import pytest
from portfolio_v5.models import ImportBatch, Snapshot, Position, Transaction
from portman.repository_v09 import RepositoryV09


@pytest.fixture
def repo(tmp_path):
    r = RepositoryV09(tmp_path / 'assets.sqlite', backups=False)
    r.commit_batches([ImportBatch('statement', 's1', snapshots=[
        Snapshot('Depot A', '2020-01', '2020-01-01', 'Test', [Position('US0378331005', 'Apple',
            isin='US0378331005', wkn='865985', quantity='2.5', cost='200', value='250')]),
        Snapshot('Depot B', '2020-01', '2020-01-01', 'Test', [Position('US0378331005', 'Apple',
            isin='US0378331005', wkn='865985', quantity='1', cost='90', value='100')])], transactions=[
        Transaction('Depot A', 'buy-1', '2019-12-01', 'BUY', '-200.50', 'EUR', 'US0378331005', '2.5', fees='0.50')])])
    yield r
    r.close()


KEY = 'US0378331005'


def test_stable_identity_aliases_and_positions_survive_restart(repo):
    asset = repo.assets.identity(KEY)
    assert repo.assets.identity('ISIN:' + KEY) == asset
    assert repo.assets.identity('WKN:865985') == asset
    positions = repo.assets.positions(KEY)
    assert len(positions) == 2 and positions[0]['uuid'] != positions[1]['uuid']
    other = RepositoryV09(repo.store.path, backups=False)
    try:
        assert other.assets.identity(KEY) == asset
        assert other.assets.positions(KEY) == positions
    finally: other.close()


def test_facts_are_dated_audited_and_do_not_mutate_imports(repo):
    original = repo.db.execute('SELECT payload FROM snapshots').fetchall()
    revision = repo.revision()
    repo.assets.save_facts(KEY, 'security', '', '2020-01-01', {'sector': 'Technologie'}, 'Beleg A')
    repo.assets.save_facts(KEY, 'security', '', '2021-01-01', {'sector': 'IT', 'notes': 'Notiz'}, 'Beleg B')
    assert repo.assets.facts(KEY, 'security', as_of='2020-12-31')['values'] == {'sector': 'Technologie'}
    assert repo.assets.facts(KEY, 'security')['values']['sector'] == 'IT'
    assert repo.revision() > revision
    assert len(repo.assets.audit(KEY)) == 2
    repo.assets.save_facts(KEY, 'security', '', '2021-01-01', {'sector': 'IT', 'notes': 'Notiz'}, 'Beleg B')
    assert len(repo.assets.audit(KEY)) == 2
    assert repo.db.execute('SELECT payload FROM snapshots').fetchall() == original


def test_notations_preserved_when_active_feed_changes(repo):
    repo.market.set_feed(KEY, 'yahoo', 'AAPL', 'USD', 'XNAS')
    repo.market.set_feed(KEY, 'yahoo', 'APC.DE', 'EUR', 'XETR')
    assert {r['symbol'] for r in repo.assets.listings(KEY)} == {'AAPL', 'APC.DE'}
    assert repo.market.mappings()[KEY]['symbol'] == 'APC.DE'


def test_acquisition_details_are_separate_and_fees_not_counted_twice(repo):
    tx = repo.assets.transactions(KEY)[0]
    assert tx['acquisition_cost'] == '200.50'
    assert tx['unit_cost_including_fees'] == '80.2'
    repo.assets.save_facts(KEY, 'trade', tx['reference'], '2019-12-01',
        {'fx_rate': '0.91', 'base_currency': 'EUR', 'fees': '0.5'}, 'Kaufabrechnung')
    assert repo.assets.transactions(KEY)[0]['amount'] == '-200.50'
    repo.assets.sync()
    assert repo.assets.transactions(KEY)[0]['lot_uuid'] == tx['lot_uuid']


@pytest.mark.parametrize('scope,values', [
    ('security', {'issuer_lei': 'falsch'}), ('security', {'primary_mic': 'Nasdaq'}),
    ('trade', {'fx_rate': '1'}), ('position', {'blocked_quantity': '-1'}),
    ('tax', {'partial_exemption': '101'}), ('tax', {'tax_cost': '1'}),
    ('trade', {'fees': 'NaN'}), ('security', {'unknown_field': 'x'}),
])
def test_invalid_facts_rejected(repo, scope, values):
    with pytest.raises(ValueError): repo.assets.save_facts(KEY, scope, '', '2020-01-01', values, 'Test')


def test_position_facts_are_depot_specific_and_unknown_is_not_zero(repo):
    a, b = repo.assets.positions(KEY)
    repo.assets.save_facts(KEY, 'position', a['uuid'], '2020-01-01', {'blocked_quantity': '0', 'custody_location': ''}, 'Bank')
    assert repo.assets.facts(KEY, 'position', a['uuid'])['values'] == {'blocked_quantity': '0'}
    assert repo.assets.facts(KEY, 'position', b['uuid'])['values'] == {}


def test_dated_facts_survive_reimport_and_reopen(repo):
    repo.assets.save_facts(KEY, 'security', '', '2020-01-01', {'issuer_name': 'Apple Inc.'}, 'Geschäftsbericht')
    repo.commit_batches([ImportBatch('next-statement', 's2', snapshots=[
        Snapshot('Depot A', '2021-01', '2021-01-01', 'Test', [Position(KEY, 'Importname', isin=KEY,
            quantity='2.5', value='300')])])])
    other = RepositoryV09(repo.store.path, backups=False)
    try:
        assert other.assets.facts(KEY, 'security')['values']['issuer_name'] == 'Apple Inc.'
        assert len(other.assets.audit(KEY)) == 1
    finally: other.close()


def test_extended_schema_is_in_database_backup(repo, tmp_path):
    import sqlite3
    repo.assets.save_facts(KEY, 'security', '', '2020-01-01', {'notes': 'Gesichert'}, 'Manuell')
    path = tmp_path / 'copy.sqlite'
    with sqlite3.connect(path) as backup: repo.db.backup(backup)
    other = RepositoryV09(path, backups=False)
    try:
        assert other.assets.identity(KEY) == repo.assets.identity(KEY)
        assert other.assets.facts(KEY, 'security')['values']['notes'] == 'Gesichert'
    finally: other.close()


def test_isin_added_later_keeps_existing_uuid_and_facts(tmp_path):
    r = RepositoryV09(tmp_path / 'identity.sqlite', backups=False)
    try:
        r.commit_batches([ImportBatch('wkn-only', 'w1', snapshots=[Snapshot('Depot', '2020-01', '2020-01-01', 'Test',
            [Position('WKN:865985', 'Apple', wkn='865985', quantity='1', value='100')])])])
        old = r.assets.identity('WKN:865985')
        r.assets.save_facts('WKN:865985', 'security', '', '2020-01-01', {'notes': 'Bleibt erhalten'}, 'Manuell')
        r.commit_batches([ImportBatch('with-isin', 'w2', snapshots=[Snapshot('Depot', '2021-01', '2021-01-01', 'Test',
            [Position(KEY, 'Apple', isin=KEY, wkn='865985', quantity='1', value='110')])])])
        assert r.assets.identity(KEY) == old
        assert r.assets.facts(KEY, 'security')['values']['notes'] == 'Bleibt erhalten'
    finally: r.close()


def test_editor_loads_existing_holdings_and_saves(qtbot, repo):
    from portman.asset_details_dialog import AssetDetailsDialog
    dialog = AssetDetailsDialog(repo, KEY)
    qtbot.addWidget(dialog)
    editor = dialog.tabs.widget(1)
    editor.inputs['issuer_name'].setText('Apple Inc.')
    editor.source.setText('Geschäftsbericht')
    editor.save()
    assert repo.assets.facts(KEY, 'security')['values']['issuer_name'] == 'Apple Inc.'
    assert dialog.trade_table.rowCount() == 1
