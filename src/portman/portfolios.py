"""Independent portfolio folders; the original V09 portfolio stays available."""
import json
import uuid
from pathlib import Path
from datetime import date
from .persistence import atomic_json


STARTUP_PORTFOLIO_FILE = 'startup_portfolio.json'


def portfolio_name(folder):
    file = Path(folder) / 'portfolio.json'
    return json.loads(file.read_text(encoding='utf-8'))['name'] if file.exists() else 'Standardportfolio'


def available_portfolios(root):
    root = Path(root)
    return [('Standardportfolio', root / 'data/v09'), *(
        (portfolio_name(file.parent), file.parent)
        for file in sorted((root / 'data/portfolios').glob('*/portfolio.json'))
        if (file.parent / 'portfolio.sqlite').is_file())]


def startup_portfolio(root):
    """Return the configured startup portfolio or the standard portfolio."""
    root = Path(root).resolve()
    standard = (root / 'data/v09').resolve()
    file = root / 'data' / STARTUP_PORTFOLIO_FILE
    try:
        configured = json.loads(file.read_text(encoding='utf-8')).get('folder')
        candidate = (root / configured).resolve() if configured else standard
    except (OSError, TypeError, ValueError, AttributeError):
        return standard
    available = {folder.resolve() for _, folder in available_portfolios(root)}
    return candidate if candidate in available else standard


def set_startup_portfolio(root, folder):
    """Persist one of the known portfolios as the default for normal starts."""
    root = Path(root).resolve()
    selected = Path(folder).resolve()
    rows = available_portfolios(root)
    match = next(((name, path.resolve()) for name, path in rows if path.resolve() == selected), None)
    if match is None:
        raise ValueError('Das Startportfolio ist nicht mehr vorhanden.')
    name, selected = match
    atomic_json(root / 'data' / STARTUP_PORTFOLIO_FILE,
                {'folder': selected.relative_to(root).as_posix(), 'name': name})
    return selected


def create_portfolio(root, name, demo=False):
    from .repository_v09 import RepositoryV09
    from portfolio_v5.models import ImportBatch, Snapshot, Position, BankTransaction
    name = ' '.join(name.split())
    if not name or len(name) > 100: raise ValueError('Bitte einen Namen mit 1 bis 100 Zeichen eingeben.')
    if any(n.casefold() == name.casefold() for n, _ in available_portfolios(root)):
        raise ValueError('Ein Portfolio mit diesem Namen existiert bereits.')
    folder = Path(root) / 'data/portfolios' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    repo = RepositoryV09(folder / 'portfolio.sqlite', backups=False)
    try:
        if demo:
            today = date.today().isoformat()
            repo.save_account('Demo Girokonto', {'kind': 'Girokonto', 'institution': 'Demobank'})
            repo.save_account('Demo Depot', {'kind': 'Depot', 'institution': 'Demobank'})
            repo.add_balance('Demo Girokonto', '2500,00', today, 'Erfundener Demobestand')
            repo.commit_batches([ImportBatch('Demodaten', 'demo-v1',
                transactions=[BankTransaction('Demo Girokonto', 'demo-1', today, 'BANK_BOOKING', '2500.00', 'EUR', purpose='Erfundene Einzahlung')],
                snapshots=[Snapshot('Demo Depot', today[:7], today, 'Demo',
                    [Position('DEMO:FONDS', 'Beispielfonds (erfunden)', quantity='10', cost='900.00', value='1000.00')])])])
        atomic_json(folder / 'portfolio.json', {'name': name, 'demo': demo})
    finally:
        repo.close()
    return folder
