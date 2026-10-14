import pytest
from portfolio_v5.models import ImportBatch, Balance, Snapshot, Position, BankTransaction
from portman.chart_reader import open_chart_reader
from portman.chart_data import prepare_chart
from portman.repository_v09 import RepositoryV09
from portman.chart_specs import CHART_SPECS, chart_spec, chart_views
from portman.chart_style import CHART_STYLE, apply_chart_style, chart_style_signature, create_figure, save_figure


def _repo(tmp_path):
    path = tmp_path / 'events.sqlite'
    repo = RepositoryV09(path, backups=False)
    repo.create_accounts(['Cash'])
    repo.commit_batches([ImportBatch('events', 'events', balances=[
        Balance('2025-01', 'Liquidität', 'Cash', '100', 'Online ING · 2025-01-10', 1),
        Balance('2025-02', 'Liquidität', 'Cash', '300', 'Online ING · 2025-02-10', 2)],
        snapshots=[
            Snapshot('Depot', '2025-01', '2025-01-05', 'Test', [Position('A', 'A', quantity='2', value='40', cost='30')]),
            Snapshot('Depot', '2025-02', '2025-02-05', 'Test', [Position('A', 'A', quantity='3', value='60', cost='45')])],
        transactions=[
            BankTransaction('Cash', 'cash-1', '2025-01-11', 'DEPOSIT', '5', 'EUR'),
            BankTransaction('Depot', 'baader-trade-1', '2025-01-15', 'BUY', '10', 'EUR',
                            security='A', quantity='1', affects_cash=False)])])
    repo.add_balance('Cash', '180', '2025-01-20')
    return repo


def test_chart_registry_is_complete_and_stable():
    assert len(CHART_SPECS) == 10
    assert all(0 <= spec.mode <= 9 for spec in CHART_SPECS)
    assert len(chart_views()) == 10
    for mode in range(10):
        spec = chart_spec(mode)
        assert spec.mode == mode and spec.data and spec.render
    assert chart_spec(0).cache_group == chart_spec(6).cache_group == chart_spec(8).cache_group
    assert chart_spec(9).comparison and chart_spec(9).render == 'comparison'


def test_chart_style_apply_and_signature():
    original = dict(CHART_STYLE)
    sig0 = chart_style_signature()
    apply_chart_style({'top_n': 7, 'figure_width': 12})
    assert CHART_STYLE['top_n'] == 7 and CHART_STYLE['figure_width'] == 12
    assert CHART_STYLE['export_dpi'] == original['export_dpi']
    assert chart_style_signature() != sig0
    apply_chart_style(original)
    assert chart_style_signature() == sig0


def test_create_figure_honours_config():
    apply_chart_style({'figure_width': 9.5, 'figure_height': 3.25, 'dpi': 120})
    fig = create_figure()
    assert tuple(round(v, 2) for v in fig.get_size_inches()) == (9.5, 3.25)
    assert fig.dpi == 120
    assert tuple(round(v, 2) for v in create_figure(6, 5, 100).get_size_inches()) == (6, 5)


def test_prepare_chart_dispatches_all_modes_like_repository(tmp_path):
    repo = _repo(tmp_path)
    reader = None
    try:
        reader = open_chart_reader(tmp_path / 'events.sqlite', RepositoryV09, lambda: False)
        from portman.chart_specs import chart_spec
        for mode in range(10):
            spec = chart_spec(mode)
            if spec and spec.comparison:
                continue
            assert prepare_chart(reader, mode, '2025-02-20', None) == prepare_chart(repo, mode, '2025-02-20', None)
    finally:
        if reader: reader.close()
        repo.close()


def test_save_figure_writes_valid_files_for_each_format(tmp_path):
    figure = create_figure()
    magics = {'png': b'\x89PNG\r\n\x1a\n', 'svg': b'<?xml', 'pdf': b'%PDF', 'jpg': b'\xff\xd8\xff'}
    for fmt in CHART_STYLE['export_formats']:
        assert fmt in magics, f'Neues Format {fmt} braucht einen Magic-Byte-Check'
    for fmt, magic in magics.items():
        target = tmp_path / f'chart.{fmt}'
        save_figure(figure, target)
        data = target.read_bytes()
        assert data.startswith(magic), fmt
        assert len(data) > 0


def test_save_figure_creates_parent_directories(tmp_path):
    target = tmp_path / 'nested' / 'dirs' / 'chart.svg'
    save_figure(create_figure(), target)
    assert target.exists()


def test_save_figure_supports_dpi_for_raster_formats(tmp_path):
    figure = create_figure(6, 3)
    low, high = tmp_path / 'low.png', tmp_path / 'high.png'
    save_figure(figure, low, dpi=50)
    save_figure(figure, high, dpi=150)
    low_pixels = int.from_bytes(low.read_bytes()[16:20], 'big') * int.from_bytes(low.read_bytes()[20:24], 'big')
    high_pixels = int.from_bytes(high.read_bytes()[16:20], 'big') * int.from_bytes(high.read_bytes()[20:24], 'big')
    assert high_pixels > low_pixels


def test_save_figure_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError, match='Nicht unterstütztes Exportformat'):
        save_figure(create_figure(), tmp_path / 'chart.xyz')
    with pytest.raises(ValueError, match='erlaubt'):
        save_figure(create_figure(), tmp_path / 'chart')