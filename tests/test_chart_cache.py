"""Tests für den Chart-Reihen-Cache (chart_cache)."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

from portman.chart_cache import _clone, cached_series


class _Cursor:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return (self._value,)


class _FakeDb:
    def __init__(self):
        self.in_transaction = False
        self.total_changes = 0
        self.version = 1

    def execute(self, sql):
        return _Cursor(self.version)


class _Custom:
    def __init__(self, value):
        self.value = value


def test_clone_is_deepcopy_equivalent():
    structure = {
        'rows': [
            {'date': '2023-01-01', 'value': Decimal('100.00'), 'tags': ('a', 'b'), 'flags': {'x', 'y'}},
            {'date': '2023-01-02', 'value': 150, 'name': None},
        ],
        'summary': {'total': 250.5},
    }
    assert _clone(structure) == structure
    assert _clone(structure) == deepcopy(structure)


def test_clone_is_isolated_from_original():
    structure = {'rows': [{'date': '2023-01-01', 'value': 100},
                          {'date': '2023-01-02', 'value': 200}]}
    clone = _clone(structure)
    clone['rows'][0]['value'] = 999
    clone['rows'].append({'date': '2023-01-03', 'value': 300})
    clone['extra'] = True
    assert structure['rows'][0]['value'] == 100
    assert len(structure['rows']) == 2
    assert 'extra' not in structure
    assert structure['rows'][0] == {'date': '2023-01-01', 'value': 100}


def test_clone_preserves_value_types():
    values = [None, True, 1, 2.5, 'text', Decimal('12.34'), b'bytes']
    for value in values:
        clone = _clone([value])[0]
        assert clone == value
        assert type(clone) is type(value)


def test_clone_falls_back_to_deepcopy_for_unknown_types():
    original = _Custom([1, 2, 3])
    clone = _clone({'o': original})['o']
    assert isinstance(clone, _Custom)
    assert clone is not original
    assert clone.value == original.value


def test_cached_series_reuses_and_clones_results():
    db = _FakeDb()
    repo = SimpleNamespace(db=db)
    builds = []

    def build():
        builds.append(1)
        return {'rows': [{'date': '2023-01-01', 'value': Decimal('1.5')}]}

    first = cached_series(repo, 'key', build)
    second = cached_series(repo, 'key', build)
    assert len(builds) == 1              # zweiter Aufruf nutzt den Cache
    assert first == second
    assert first is not second           # Klon statt geteilter Referenz
    assert isinstance(first['rows'][0]['value'], Decimal)
    second['rows'][0]['value'] = 999
    assert first['rows'][0]['value'] == Decimal('1.5')


def test_cached_series_rebuilds_after_db_change():
    db = _FakeDb()
    repo = SimpleNamespace(db=db)
    builds = []
    cached_series(repo, 'k', lambda: builds.append(1) or {'v': 1})
    db.total_changes = 5
    cached_series(repo, 'k', lambda: builds.append(1) or {'v': 1})
    assert len(builds) == 2


def test_cached_series_evicts_oldest_entry():
    db = _FakeDb()
    repo = SimpleNamespace(db=db)
    counts = {}

    def build(key):
        counts[key] = counts.get(key, 0) + 1
        return {'key': key}

    for index in range(9):
        cached_series(repo, f'k{index}', lambda key=f'k{index}': build(key))
    cached_series(repo, 'k0', lambda: build('k0'))
    assert counts['k0'] == 2             # k0 wurde verdrängt und neu gebaut
    cached_series(repo, 'k8', lambda: build('k8'))
    assert counts['k8'] == 1             # k8 war noch im Cache


def test_cached_series_bypasses_cache_in_transaction():
    db = _FakeDb()
    db.in_transaction = True
    repo = SimpleNamespace(db=db)
    builds = []
    cached_series(repo, 'k', lambda: builds.append(1) or {'v': 1})
    cached_series(repo, 'k', lambda: builds.append(1) or {'v': 1})
    assert len(builds) == 2