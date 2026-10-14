from .portfolio_storage import PortfolioStorage
from .persistence import read_json


class StorageV07(PortfolioStorage):
    def __init__(self, folder):
        super().__init__(str(folder / 'legacy-holdings.json'), str(folder / 'portfolio_settings.json'), str(folder / 'etf_cache.json'))
    def load_settings(self):
        settings = read_json(self.settings_filename)
        if not settings.get('v07_initialized'):
            settings.update(v07_initialized=True, dock_layout_locked=True)
        return settings
    def load_etf_cache(self): return read_json(self.etf_filename)
