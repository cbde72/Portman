"""Prepare chart inputs without accessing Qt widgets or drawing figures."""
from .visualization_data import wealth_at, wealth_history
from .performance_service import PerformanceService
from .chart_specs import chart_spec
from .chart_config import ALL_ACCOUNTS


def comparison_data(repo, as_of, account):
    records = repo.market.records()
    choices = [(p['key'], p['name']) for p in repo.current(as_of, account)
               if records.get(p['key'], {}).get('data', {}).get('prices')]
    chosen = {key for key, name in choices}
    if hasattr(repo, 'db'):
        from .price_history import historical_positions, stored_history
        mappings = repo.market.mappings()
        for position in historical_positions(repo, account):
            saved = stored_history(repo, position['key'], position['history_start'], as_of, mappings.get(position['key'], {}))
            if saved['prices']:
                records[position['key']] = {'data': saved}
                if position['key'] not in chosen:
                    chosen.add(position['key'])
                    choices.append((position['key'], position['name']))
            elif position['key'] in records:
                legacy = records[position['key']].get('data', {})
                legacy['prices'] = [p for p in legacy.get('prices', []) if p['date'] >= position['history_start']]
    return {'records': records, 'choices': choices}


def prepare_chart(repo, mode, as_of, account):
    spec = chart_spec(mode)
    if spec is None:
        return {'positions': [p for p in repo.current(as_of, account) if p.get('value') is not None]}
    if spec.data == 'comparison': return comparison_data(repo, as_of, account)
    if spec.data == 'wealth':
        return {'series': wealth_history(repo, as_of, account),
                'summary': wealth_at(repo, as_of, account)}
    if spec.data == 'accounts': return {'rows': repo.account_overview(as_of)}
    if spec.data == 'valuation':
        return {'rows': [r for r in PerformanceService(repo).valuation_series(account) if r['date'] <= as_of]}
    return {'positions': [p for p in repo.current(as_of, account) if p.get('value') is not None]}


def prepare_chart_for_config(repo, data_source: str, as_of: str, account, options: dict | None = None):
    """Bereitet Diagrammdaten basierend auf der Datenquelle für benutzerdefinierte Diagramme vor.

    Args:
        repo: Das Repository.
        data_source: Die Datenquelle (wealth, accounts, positions, valuation, comparison).
        as_of: Stichtag.
        account: Globaler Konto-Filter aus dem Kopfbereich.
        options: Optionale diagrammspezifische Auswahl. Unterstützt ``account``
            (setzt den Kontofilter außer Kraft; :data:`ALL_ACCOUNTS` erzwingt
            alle Konten) und ``positions`` (Liste von Wertpapier-Schlüsseln,
            auf die die Depotpositionen eingeschränkt werden).

    Returns:
        Aufbereitete Diagrammdaten.
    """
    options = options or {}
    scoped = options.get('account')
    if scoped == ALL_ACCOUNTS:
        scoped = None
    elif not scoped:
        scoped = account
    if data_source == 'comparison':
        return comparison_data(repo, as_of, scoped)
    if data_source == 'wealth':
        return {'series': wealth_history(repo, as_of, scoped),
                'summary': wealth_at(repo, as_of, scoped)}
    if data_source == 'accounts':
        return {'rows': repo.account_overview(as_of)}
    if data_source == 'valuation':
        return {'rows': [r for r in PerformanceService(repo).valuation_series(scoped) if r['date'] <= as_of]}
    positions = [p for p in repo.current(as_of, scoped) if p.get('value') is not None]
    selected = options.get('positions')
    if selected:
        wanted = set(selected)
        positions = [p for p in positions if p.get('key') in wanted]
    return {'positions': positions}
