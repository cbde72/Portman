"""ISIN name resolution and online metadata enrichment."""
import re

from PySide6.QtWidgets import QMessageBox

from portman.holding import Holding
from portman.isin_fetcher import ISINOnlineFetcher


class IsinEnrichmentMixin:
    def resolve_isin_names(self):
        holdings = [h for h in self.holdings.values() if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', h.isin or '')]
        if not holdings:
            QMessageBox.information(self, "ISIN-Namen", "Keine Positionen mit gültiger ISIN vorhanden.")
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.fetcher = ISINOnlineFetcher(holdings)
        self.fetcher.progress.connect(self.update_progress)
        self.fetcher.status_message.connect(self.status_bar.showMessage)
        self.fetcher.finished.connect(self.on_online_fetch_complete)
        self.fetcher.start()

    def on_online_fetch_complete(self, enriched_holdings: list[Holding]):
        self.progress_bar.setVisible(False)
        for h in enriched_holdings:
            if h.isin in self.holdings:
                old = self.holdings[h.isin]
                old.asset_type = h.asset_type
                old.region = h.region
                old.cap_size = h.cap_size
                old.beta = h.beta
                old.volatility = h.volatility
                old.dividend_yield = h.dividend_yield
            else:
                self.holdings[h.isin] = h

        self.repository.save_metadata(self.holdings.values())
        self.reload_portfolio()
        self.status_bar.showMessage(f"{len(enriched_holdings)} Wertpapiere über ISIN aktualisiert.", 5000)
        QMessageBox.information(self, "ISIN-Auflösung", f"{len(enriched_holdings)} Wertpapiere wurden geprüft und die verfügbaren Anzeigenamen gespeichert.")
