from dataclasses import dataclass


@dataclass
class Holding:
    isin: str
    wkn: str
    name: str
    asset_type: str        # 'Aktie', 'ETF', 'Krypto', 'Sonstiges'
    amount: float
    buy_value: float
    market_value: float
    region: str = "Unbekannt"     # USA, Europa, Welt, Japan, Emerging Markets, etc.
    cap_size: str = "Unbekannt"   # Small, Mid, Large, Unbekannt
    beta: float = 1.0             # Markt-Beta aus Yahoo Finance
    volatility: float = 15.0      # Volatilität (%) aus Yahoo Finance/Schätzung
    dividend_yield: float = 0.0   # Dividendenrendite in %

    @property
    def profit_loss(self) -> float:
        return self.market_value - self.buy_value

    @property
    def profit_loss_pct(self) -> float:
        return (self.profit_loss / self.buy_value * 100.0) if self.buy_value > 0 else 0.0

    @property
    def annual_dividend(self) -> float:
        return self.market_value * (self.dividend_yield / 100.0)
