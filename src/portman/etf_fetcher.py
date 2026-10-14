import json
import re
import html as html_lib
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from .holding import Holding
from .etf_factsheets import download_factsheet, factsheet_path, parse_factsheet

logger = logging.getLogger(__name__)


class ETFLookThroughFetcher(QThread):
    finished = Signal(dict, dict)
    progress = Signal(str)
    
    def __init__(self, etf_holdings: list[Holding], factsheet_dir):
        super().__init__()
        self.etf_holdings = etf_holdings
        self.factsheet_dir = Path(factsheet_dir)

    def run(self):
        result_map = {}
        failures = {}
        pending = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for h in self.etf_holdings:
                if self.isInterruptionRequested(): break
                self.progress.emit(f"Prüfe Factsheet für: {h.name}")
                pending[pool.submit(self._process, h)] = h
            for future in as_completed(pending):
                if self.isInterruptionRequested():
                    for remaining in pending: remaining.cancel()
                    break
                h = pending[future]
                self.progress.emit(f"Fertig: {h.name}")
                try:
                    isin, holdings_data, reason = future.result()
                except Exception:
                    logger.exception('Look-Through-Abruf fehlgeschlagen')
                    continue
                if holdings_data:
                    result_map[isin] = holdings_data
                else:
                    failures[isin] = reason
        self.finished.emit(result_map, failures)

    def _process(self, h: Holding):
        local_pdf = factsheet_path(self.factsheet_dir, h.isin)
        download_error = None
        if local_pdf is None:
            local_pdf, download_error = download_factsheet(
                h.isin, h.name, self.factsheet_dir
            )
        holdings_data = parse_factsheet(local_pdf, h.isin) if local_pdf else []
        if not holdings_data:
            holdings_data = self.fetch_top_holdings_justetf(h.isin)
        if not holdings_data:
            holdings_data = self.fetch_top_holdings_yahoo(h.isin)
        if holdings_data:
            return h.isin, holdings_data, None
        reason = f"{h.name}: Factsheet, justETF und Yahoo lieferten keine Top-Positionen"
        if download_error: reason += f" ({download_error})"
        return h.isin, [], reason

    def fetch_top_holdings_justetf(self, isin: str) -> list[dict]:
        try:
            url = f"https://www.justetf.com/de/etf-profile.html?isin={isin}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=6) as resp:
                html = resp.read().decode('utf-8')
                matches = re.findall(
                    r'data-testid="tl_etf-holdings_top-holdings_link_name"[^>]*'
                    r'href="[^"]*/stock-profiles/([^"/]+)"[^>]*title="([^"]+)"[^>]*>'
                    r'.*?data-testid="tl_etf-holdings_top-holdings_value_percentage">\s*([\d.,]+)\s*%',
                    html, re.DOTALL | re.IGNORECASE)
                parsed = []
                for security_id, name, pct_str in matches:
                    pct = float(pct_str.replace('.', '').replace(',', '.'))
                    parsed.append({'name': html_lib.unescape(name).strip(), 'isin': security_id,
                                   'weight_pct': pct, 'source': 'justETF'})
                return parsed
        except Exception as exc:
            print(f"justETF-Abruf für {isin} fehlgeschlagen: {exc}")
            return []

    def fetch_top_holdings_yahoo(self, isin: str) -> list[dict]:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            url_search = f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}&quotesCount=1"
            req = urllib.request.Request(url_search, headers=headers)
            
            symbol = None
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                quotes = data.get('quotes', [])
                if quotes: symbol = quotes[0].get('symbol')

            if not symbol: return []

            url_top = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=topHoldings"
            req_top = urllib.request.Request(url_top, headers=headers)
            with urllib.request.urlopen(req_top, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                res = data.get('quoteSummary', {}).get('result', [])
                if res:
                    holdings_raw = res[0].get('topHoldings', {}).get('holdings', [])
                    parsed = []
                    for item in holdings_raw:
                        h_name = item.get('holdingName', '')
                        pct = item.get('holdingPercent', {}).get('raw', 0) * 100.0
                        if h_name and pct > 0:
                            parsed.append({'name': h_name, 'weight_pct': round(pct, 2), 'source': 'Yahoo Finance'})
                    return parsed
        except Exception as exc:
            print(f"Yahoo-Holdings für {isin} fehlgeschlagen: {exc}")
        return []
