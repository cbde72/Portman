"""Tests für Diagramm-Templates und den TemplateManager."""
import os
from io import BytesIO

os.environ.setdefault('MPLBACKEND', 'Agg')

import matplotlib
matplotlib.use('Agg')

from portman.chart_config import ChartConfig
from portman.chart_style import create_figure
from portman.chart_templates import (
    ChartTemplate,
    TemplateManager,
    get_templates,
)
from portman.dynamic_renderer import render_chart

from test_dynamic_renderer import _wealth, _positions, _accounts, _valuation


ERROR_MARKER = 'konnte nicht gezeichnet werden'


def _data_for(source):
    return {'wealth': _wealth(), 'positions': _positions(),
            'accounts': _accounts(), 'valuation': _valuation()}.get(source, {})


def _simple_config():
    return ChartConfig(id='t', title='Test', chart_type='line', data_source='wealth')


def test_built_in_templates_include_all_new_categories():
    names = [template.name for template in get_templates()]
    assert len(names) == 12
    assert 'Vermögensverlauf (Monatswerte)' in names
    assert 'Gewinnverteilung (Histogramm)' in names
    assert 'Regionen (Treemap)' in names
    assert 'Allokation (Radar)' in names
    assert 'Depotwert (Kalender-Heatmap)' in names


def test_every_built_in_template_renders():
    for template in get_templates():
        figure = create_figure()
        figure.clear()
        figure.set_layout_engine('constrained')
        note = render_chart(figure, _data_for(template.config.data_source),
                            template.config, {'as_of': '9999-12-31'})
        figure.savefig(BytesIO(), format='png')
        assert ERROR_MARKER not in (note or ''), template.name
        assert template.config.chart_type, template.name


def test_monthly_template_uses_monthly_aggregation():
    template = next(t for t in get_templates() if t.name == 'Vermögensverlauf (Monatswerte)')
    assert template.config.aggregation == {'type': 'monthly', 'method': 'last'}


def test_template_manager_add_save_load_roundtrip(tmp_path):
    manager = TemplateManager(tmp_path / 'custom_templates.json')
    template = ChartTemplate(name='Meine Vorlage', description='Test',
                             category='Eigene', config=_simple_config())
    assert manager.add(template) is None
    assert manager.get('Meine Vorlage').config == template.config
    manager.save()

    loaded = TemplateManager(tmp_path / 'custom_templates.json')
    loaded.load()
    restored = loaded.get('Meine Vorlage')
    assert restored is not None
    assert restored.name == 'Meine Vorlage'
    assert restored.description == 'Test'
    assert restored.category == 'Eigene'
    assert restored.config.to_dict() == template.config.to_dict()


def test_template_manager_rejects_duplicate_names(tmp_path):
    manager = TemplateManager(tmp_path / 'custom_templates.json')
    template = ChartTemplate(name='Doppelt', description='', category='Eigene',
                             config=_simple_config())
    assert manager.add(template) is None
    assert 'bereits eine Vorlage' in manager.add(template)
    # Mit overwrite=True wird ersetzt
    assert manager.add(template, overwrite=True) is None


def test_template_manager_validates_names(tmp_path):
    manager = TemplateManager(tmp_path / 'custom_templates.json')
    empty = ChartTemplate(name='   ', description='', category='Eigene', config=_simple_config())
    assert 'leer' in manager.add(empty)
    long_name = ChartTemplate(name='x' * 81, description='', category='Eigene',
                              config=_simple_config())
    assert '80 Zeichen' in manager.add(long_name)
    assert not manager.user()


def test_template_manager_remove_and_persistence(tmp_path):
    manager = TemplateManager(tmp_path / 'custom_templates.json')
    manager.add(ChartTemplate(name='Weg', description='', category='Eigene',
                              config=_simple_config()))
    assert manager.remove('Weg') is True
    assert manager.remove('Weg') is False
    assert manager.user() == []


def test_template_manager_user_and_all(tmp_path):
    manager = TemplateManager(tmp_path / 'custom_templates.json')
    manager.add(ChartTemplate(name='Eigene 1', description='', category='Eigene',
                              config=_simple_config()))
    built_in = get_templates()
    assert manager.user() == [manager.get('Eigene 1')]
    all_templates = manager.all()
    assert all_templates[:len(built_in)] == built_in
    assert all_templates[-1].name == 'Eigene 1'


def test_template_manager_load_missing_file_is_empty(tmp_path):
    manager = TemplateManager(tmp_path / 'not-there.json')
    assert manager.load() == {}
    manager.save()
    assert manager.path.exists()