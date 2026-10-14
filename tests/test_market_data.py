import math
import sqlite3
import unittest
from portman.market_data import YahooMarketProvider, MarketDataStore, calculate_metrics


class MarketTests(unittest.TestCase):
    def chart(self, symbol='ABC', currency='USD'):
        return {'chart': {'result': [{'meta': {'symbol': symbol, 'currency': currency, 'regularMarketPrice': 120,
                    'regularMarketTime': 1789761600}, 'timestamp': [1700000000 + i * 86400 for i in range(260)],
                    'indicators': {'quote': [{'close': [100 + i / 10 for i in range(260)]}],
                                   'adjclose': [{'adjclose': [100 + i / 10 for i in range(260)]}]}}]}}

    def test_ambiguous_isin_does_not_fetch_wrong_listing(self):
        calls = []
        def transport(url):
            calls.append(url)
            return {'quotes': [{'symbol': x, 'isYahooFinance': True, 'quoteType': 'EQUITY'} for x in ['ABC', 'ABC.DE']]}
        result = YahooMarketProvider(transport).fetch({'key': 'US0000000001', 'isin': 'US0000000001', 'name': 'ABC'})
        self.assertEqual(result['status'], 'mapping_needed'); self.assertEqual(len(calls), 1)

    def test_missing_currency_and_mismatched_symbol_are_errors(self):
        position = {'key': 'ABC', 'name': 'ABC'}
        for chart in [self.chart(currency=None), self.chart(symbol='OTHER')]:
            result = YahooMarketProvider(lambda url: chart).fetch(position, {'symbol': 'ABC'})
            self.assertEqual(result['status'], 'error')

    def test_price_retains_currency_and_time_and_metrics(self):
        result = YahooMarketProvider(lambda url: self.chart()).fetch({'key': 'ABC', 'name': 'ABC'}, {'symbol': 'ABC'})
        self.assertEqual(result['status'], 'ok'); self.assertEqual(result['currency'], 'USD')
        self.assertEqual(result['quote_time'], '2026-09-18T20:00:00+00:00')
        self.assertEqual(len(result['prices']), 260)
        self.assertIsNotNone(result['metrics']['return_1y_pct'])

    def test_drawdown_and_short_history(self):
        prices = [{'close': x, 'adjusted_close': x} for x in [100] * 20 + [80, 90]]
        metrics = calculate_metrics(prices)
        self.assertAlmostEqual(metrics['max_drawdown_pct'], -20)
        self.assertIsNone(metrics['return_1y_pct']); self.assertIsNone(metrics['ma_50'])
        self.assertTrue(math.isfinite(metrics['volatility_pct']))

    def test_failed_update_preserves_good_data_and_manual_values(self):
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
        store = MarketDataStore(db)
        good = YahooMarketProvider(lambda url: self.chart()).fetch({'key': 'ABC', 'name': 'ABC'}, {'symbol': 'ABC'})
        store.save_result(good)
        store.save_manual('ABC', {'ter_pct': '0,25'}, 'Factsheet', '2026-09-01')
        store.save_result({'security_key': 'ABC', 'attempted_at': '2026-09-19', 'status': 'error', 'message': 'Timeout'})
        record = store.records()['ABC']
        self.assertEqual(record['data']['metrics']['price'], 120)
        self.assertEqual(record['manual']['fields']['ter_pct'], .25)
        self.assertEqual(record['attempt']['status'], 'error')
        store.set_symbol('ABC', 'ABC.DE')
        self.assertNotIn('data', store.records()['ABC'])
        self.assertIn('manual', store.records()['ABC'])
        for value in ('nan', 'inf', '-1'):
            with self.assertRaises(ValueError): store.save_manual('ABC', {'ter_pct': value}, 'Factsheet', '2026-09-01')
        db.close()
