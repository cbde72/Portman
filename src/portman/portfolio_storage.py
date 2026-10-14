import logging
import os
import json
from .persistence import atomic_json

logger = logging.getLogger(__name__)


class PortfolioStorage:
    def __init__(self, db_filename="portfolio_db.json", settings_filename="portfolio_settings.json", etf_filename="etf_cache.json"):
        self.db_filename = db_filename
        self.settings_filename = settings_filename
        self.etf_filename = etf_filename

    def save_settings(self, settings: dict):
        atomic_json(self.settings_filename, settings)

    def load_settings(self) -> dict:
        if not os.path.exists(self.settings_filename): return {}
        try:
            with open(self.settings_filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            logger.warning('Fehler beim Laden der Einstellungen: %s', e)
            return {}

    def save_etf_cache(self, etf_data: dict):
        atomic_json(self.etf_filename, etf_data)

    def load_etf_cache(self) -> dict:
        if not os.path.exists(self.etf_filename): return {}
        try:
            with open(self.etf_filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            logger.warning('Fehler beim Laden des ETF-Caches: %s', e)
            return {}
