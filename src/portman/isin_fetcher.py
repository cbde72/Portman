import http.client
import json
import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QThread, Signal
from .holding import Holding
from .security_hints import guess_region, guess_cap_size

logger = logging.getLogger(__name__)


class ISINOnlineFetcher(QThread):
    finished = Signal(list)
    progress = Signal(int, int)
    status_message = Signal(str)

    def __init__(self, holdings: list[Holding]):
        super().__init__()
        self.holdings = holdings

    def run(self):
        total = len(self.holdings)
        pending = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for h in self.holdings:
                if self.isInterruptionRequested(): break
                self.status_message.emit(f"Analysiere Online: {h.name or h.isin}")
                pending[pool.submit(self._enrich, h)] = h
            done = 0
            for future in as_completed(pending):
                if self.isInterruptionRequested():
                    for remaining in pending: remaining.cancel()
                    break
                done += 1
                h = pending[future]
                self.progress.emit(done, total)
                self.status_message.emit(f"Analysiert: {h.name or h.isin} ({done}/{total})")
        self.finished.emit(self.holdings)

    def _enrich(self, holding: Holding):
        try:
            self.enrich_holding_online(holding)
        except Exception:
            logger.exception('Online-Anreicherung fehlgeschlagen')

    def enrich_holding_online(self, holding: Holding):
        try:
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={holding.isin}&quotesCount=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4) as response:
                data = json.loads(response.read().decode())
                quotes = data.get('quotes', [])
                if quotes:
                    q = quotes[0]
                    quote_type = q.get('quoteType', '').upper()
                    long_name = q.get('longname', q.get('shortname', ''))
                    if long_name and re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', holding.isin or ''):
                        holding.name = re.sub(r'\s+', ' ', long_name).strip()

                    if quote_type == 'ETF':
                        holding.asset_type = 'ETF'
                    elif quote_type in ['EQUITY', 'STOCK']:
                        holding.asset_type = 'Aktie'
                    elif quote_type in ['CRYPTOCURRENCY', 'COIN']:
                        holding.asset_type = 'Krypto'

                    full_name = long_name if long_name else holding.name
                    if not holding.region or holding.region == "Unbekannt":
                        holding.region = guess_region(full_name, holding.isin)
                    if not holding.cap_size or holding.cap_size == "Unbekannt":
                        holding.cap_size = guess_cap_size(full_name)

                    symbol = q.get('symbol')
                    if symbol:
                        self.fetch_key_stats(symbol, holding)
        except (OSError, ValueError, http.client.HTTPException) as e:
            logger.warning('Online Fetcher Fehler für %s: %s', holding.isin, e)

    def fetch_key_stats(self, symbol: str, holding: Holding):
        try:
            url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=defaultKeyStatistics,financialData,summaryDetail"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4) as response:
                data = json.loads(response.read().decode())
                result = data.get('quoteSummary', {}).get('result', [])
                if result:
                    res_item = result[0]
                    key_stats = res_item.get('defaultKeyStatistics', {})
                    summary_detail = res_item.get('summaryDetail', {})

                    beta_val = key_stats.get('beta', {}).get('raw')
                    if beta_val is not None:
                        holding.beta = round(float(beta_val), 2)
                    
                    if holding.beta > 0 and holding.asset_type != 'Krypto':
                        holding.volatility = round(15.0 * holding.beta, 1)
                    elif holding.asset_type == 'Krypto':
                        holding.volatility = 65.0

                    div_yield = summary_detail.get('dividendYield', {}).get('raw')
                    if div_yield is not None:
                        holding.dividend_yield = round(float(div_yield) * 100.0, 2)
        except (OSError, ValueError, http.client.HTTPException):
            pass
