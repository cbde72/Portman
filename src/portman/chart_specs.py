"""Declarative chart registry.

Each chart is one ``ChartSpec``: its dropdown label, the data builder
(cache group) and the renderer. Adding a chart type = one entry here
instead of editing the duplicated dispatch chains in ``chart_data``,
``visualizations`` and ``data_key``.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ChartSpec:
    mode: int
    label: str
    data: str
    render: str
    comparison: bool = False
    cache_group: int = None

    def __post_init__(self):
        if self.cache_group is None:
            object.__setattr__(self, 'cache_group', self.mode)


CHART_SPECS = (
    ChartSpec(0, 'Vermögen & Anlageklassen', 'wealth', 'wealth', cache_group=0),
    ChartSpec(1, 'Kontenvergleich', 'accounts', 'accounts'),
    ChartSpec(2, 'Größte Depotpositionen', 'positions', 'positions'),
    ChartSpec(3, 'Buchgewinne und Verluste', 'positions', 'positions'),
    ChartSpec(4, 'Regionen im Depot', 'positions', 'positions'),
    ChartSpec(5, 'Depotwert & Rückgang', 'valuation', 'depot_value'),
    ChartSpec(6, 'Monatliche Vermögensänderung', 'wealth', 'wealth', cache_group=0),
    ChartSpec(7, 'Depotkonzentration', 'positions', 'positions'),
    ChartSpec(8, 'Vermögensstruktur im Verlauf', 'wealth', 'wealth', cache_group=0),
    ChartSpec(9, 'Kursvergleich · Basis 100', 'comparison', 'comparison', comparison=True),
)


def chart_spec(mode):
    return next((spec for spec in CHART_SPECS if spec.mode == mode), None)


def chart_views():
    return [spec.label for spec in CHART_SPECS]