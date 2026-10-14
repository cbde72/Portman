from .holding import Holding


def calculate_hhi(holdings: list[Holding]) -> float:
    total_val = sum(h.market_value for h in holdings if h.market_value > 0)
    if total_val == 0: return 0.0
    weights = [(h.market_value / total_val) * 100.0 for h in holdings if h.market_value > 0]
    return sum(w**2 for w in weights)


def get_concentration_warnings(holdings: list[Holding], threshold_pct: float = 10.0) -> list[dict]:
    total_val = sum(h.market_value for h in holdings if h.market_value > 0)
    if total_val == 0: return []
    warnings = []
    for h in holdings:
        pct = (h.market_value / total_val) * 100.0
        if pct >= threshold_pct:
            warnings.append({
                'isin': h.isin,
                'name': h.name,
                'weight_pct': pct,
                'market_value': h.market_value
            })
    return sorted(warnings, key=lambda x: x['weight_pct'], reverse=True)
