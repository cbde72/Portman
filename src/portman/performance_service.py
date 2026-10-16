from collections import defaultdict
from datetime import date
from decimal import Decimal
import json

from portfolio_v5.performance import security_performance, xirr
from portfolio_v5.accounts import canonical_depot
from .chart_cache import cached_series

ZERO = Decimal(0)
PERFORMANCE_KINDS = {"BUY", "SELL", "DIVIDEND", "INTEREST", "FEE", "TAX"}


def _minus_years(value, years):
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def _interval_equation(previous_value, current_value, flows, days, g):
    """F(g) = previous*g**days + sum(amount*g**remaining) - current (Decimal)."""
    total = previous_value * (g ** days)
    for remaining, amount in flows:
        total -= amount * (g ** remaining)
    return total - current_value


def _solve_daily_growth(previous_value, current_value, flows, days, guess):
    """Exact daily TWR growth factor ``g`` for a valuation interval.

    End-of-day flows: ``previous * g**days + sum(amount * g**remaining) == current``.
    ``flows`` is a list of ``(remaining_days, amount)``. Without flows the
    solution is the pure geometric growth; with flows a Newton iteration starts
    from the flow-ignoring growth (the financially smooth root) and is only
    accepted when the residual actually improves over the Modified-Dietz guess.
    """
    days = int(days)
    if not flows:
        if previous_value <= 0 or current_value < 0:
            return None
        if current_value == 0:
            return ZERO
        return (current_value / previous_value) ** (Decimal(1) / Decimal(days))
    if previous_value <= 0:
        return None
    if current_value > 0:
        start = (current_value / previous_value) ** (Decimal(1) / Decimal(days))
    else:
        start = Decimal(1)
    g = start
    residual = abs(_interval_equation(previous_value, current_value, flows, days, g))
    for _ in range(120):
        total = previous_value * (g ** days)
        derivative = previous_value * days * (g ** (days - 1))
        for remaining, amount in flows:
            total -= amount * (g ** remaining)
            derivative -= amount * remaining * (g ** (remaining - 1))
        error = total - current_value
        if error == 0 or derivative == 0:
            break
        step = error / derivative
        g -= step
        if not (Decimal('1e-12') < g < Decimal(100)):
            g = start
            residual = abs(_interval_equation(previous_value, current_value, flows, days, g))
            break
        new_residual = abs(_interval_equation(previous_value, current_value, flows, days, g))
        if new_residual > residual:  # convergence broken: retry with half steps
            g += step
            for _ in range(60):
                g -= step / 2
                if g <= 0:
                    g = start
                    break
                new_residual = abs(_interval_equation(previous_value, current_value, flows, days, g))
                if new_residual <= residual:
                    residual = new_residual
                    break
            else:
                residual = min(residual, new_residual)
            continue
        residual = new_residual
        if residual == 0:
            break
    if residual > abs(_interval_equation(previous_value, current_value, flows, days, guess)):
        return guess
    return g


def _daily_valuation_index(interval_risks):
    """Canonical daily total-return series (start 100).

    Each ``(d0, d1, g, flows_by_day)`` entry advances the index by the daily
    growth factor ``g``. External flows are neutralized at their calendar day
    (recorded in ``flow``, never a jump of the index). Every point contains its
    daily return; the origin point has no preceding return.
    """
    from datetime import timedelta
    daily_index = []
    for d0, d1, daily_growth, flows_by_day in interval_risks:
        days = (d1 - d0).days
        if days <= 0 or daily_growth is None or daily_growth < 0:
            continue
        if not daily_index:
            daily_index.append({'date': d0.isoformat(), 'index': Decimal(100),
                                'return': None, 'flow': ZERO, 'flows': ZERO})
        base = Decimal(daily_index[-1]['index'])
        for offset in range(1, days + 1):
            previous_base = base
            if daily_growth == 0:
                if offset == days:
                    base = ZERO
            else:
                base *= daily_growth
            day = (d0 + timedelta(days=offset)).isoformat()
            flow = flows_by_day.get(day, ZERO)
            daily_return = (ZERO if previous_base == 0 else
                            base / previous_base - Decimal(1))
            daily_index.append({'date': day, 'index': base,
                                'return': daily_return,
                                'flow': flow, 'flows': flow})
    return daily_index


def _index_risk(daily_index):
    """Risk profile of a daily index (volatility, semivolatility, drawdowns)."""
    if len(daily_index) < 2:
        return {'volatility_annualized': None, 'semivolatility_annualized': None,
                'max_drawdown': None, 'current_drawdown': None, 'longest_drawdown_days': 0}
    returns = [point['return'] for point in daily_index[1:]]
    if returns:
        mean = sum(returns, ZERO) / Decimal(len(returns))
        variance = sum((value - mean) ** 2 for value in returns) / Decimal(len(returns))
        volatility = variance.sqrt() * Decimal(365).sqrt() if variance >= 0 else None
        downside = [min(value, ZERO) for value in returns]
        downside_variance = sum((value * value for value in downside), ZERO) / Decimal(len(returns))
        semivolatility = (downside_variance.sqrt() * Decimal(365).sqrt()
                          if downside_variance >= 0 else None)
    else:
        volatility = semivolatility = None
    peak = Decimal(daily_index[0]['index'])
    max_drawdown = ZERO
    current_drawdown = ZERO
    run = 0
    longest = 0
    for point in daily_index:
        value = Decimal(point['index'])
        if value > peak:
            peak = value
            run = 0
        else:
            run += 1
            longest = max(longest, run)
        if peak:
            drawdown = (peak - value) / peak
            max_drawdown = max(max_drawdown, drawdown)
    if peak:
        current_drawdown = (peak - Decimal(daily_index[-1]['index'])) / peak
    return {'volatility_annualized': volatility, 'semivolatility_annualized': semivolatility,
            'max_drawdown': max_drawdown, 'current_drawdown': current_drawdown,
            'longest_drawdown_days': longest}


class PerformanceService:
    def __init__(self, repository):
        self.repo = repository

    def valuation_series(self, account=None):
        return cached_series(self.repo, ('valuation', account), lambda: self._valuation_series(account))

    def _valuation_series(self, account=None):
        rows = [s for s in self.repo.snapshots(account) if s["as_of"]]
        states, out, current_date = {}, [], None
        daily_values = {(r['snapshot_id'], r['security_key']): dict(r)
                        for r in self.repo.db.execute('SELECT * FROM wallet_daily_values')}

        def emit(day):
            if day is not None:
                if any(p.get('value') is None for positions in states.values()
                       for p in positions.values()):
                    return
                value = sum((Decimal(p["value"]) for positions in states.values()
                             for p in positions.values()), ZERO)
                currencies = {p.get('currency') for positions in states.values() for p in positions.values()}
                out.append({"date": day, "value": value, "currencies": currencies,
                            "depots": tuple(sorted(states))})

        for snap in rows:
            if current_date is not None and snap["effective_date"] != current_date:
                emit(current_date)
            current_date = snap["effective_date"]
            data, account_name = json.loads(snap["payload"]), snap.get("depot", snap["account"])
            # Portfolio packages retain target, source account and original depot
            # in the source alias. Online refreshes later use only the original
            # depot name. Both describe the same physical depot.
            account_name = canonical_depot(account_name)
            if snap["complete"] or account_name not in states:
                states[account_name] = {}
            for position in data["positions"]:
                saved = daily_values.get((snap['id'], position['key']))
                if saved and Decimal(position['quantity']) == Decimal(saved['quantity']):
                    position = {**position, 'value': saved['value'], 'currency': saved['currency']}
                states[account_name][position["key"]] = position
        emit(current_date)
        return out

    def available_range(self, account=None):
        series = self.valuation_series(account)
        return (series[0]["date"], series[-1]["date"]) if series else (None, None)

    def preset_ranges(self, account=None):
        first, last = self.available_range(account)
        if not first:
            return {}
        first_day, end = date.fromisoformat(first), date.fromisoformat(last)
        return {
            "Jahr": (max(first_day, date(end.year, 1, 1)), end),
            "1 Jahr": (max(first_day, _minus_years(end, 1)), end),
            "3 Jahre": (max(first_day, _minus_years(end, 3)), end),
            "5 Jahre": (max(first_day, _minus_years(end, 5)), end),
            "10 Jahre": (max(first_day, _minus_years(end, 10)), end),
            "Max": (first_day, end),
        }

    def overview(self, as_of="9999-12-31", account=None):
        positions = self.repo.current(as_of, account)
        value = sum((Decimal(p["value"]) for p in positions), ZERO) if all(p['value'] is not None for p in positions) else None
        cost = sum((Decimal(p["cost"] or 0) for p in positions), ZERO)
        known = [p for p in positions if p.get('value') is not None and p.get('cost') is not None and Decimal(p['cost']) > 0]
        pnl = sum((Decimal(p['value']) - Decimal(p['cost']) for p in known), ZERO)
        known_cost = sum((Decimal(p['cost']) for p in known), ZERO)
        by_type, issues = defaultdict(Decimal), []
        for position in positions:
            if position['value'] is not None:
                by_type[position["asset_type"]] += Decimal(position["value"])
            else:
                issues.append(f"{position['name']}: Kurswert fehlt; nur Stückzahl und Einstand belegt")
            if not position.get("isin"): issues.append(f"{position['name']}: ISIN fehlt")
            if position.get("cost") is None or Decimal(position.get("cost") or 0) <= 0:
                issues.append(f"{position['name']}: Einstandswert fehlt")
            if position.get("region", "Unbekannt") == "Unbekannt":
                issues.append(f"{position['name']}: Region unbekannt")
        return {"value": value, "cost": cost, "pnl": pnl,
                "pnl_pct": (pnl / known_cost if known_cost else None), "positions": positions,
                "cost_complete": len(known) == len(positions), "known_cost_positions": len(known),
                "by_type": dict(by_type), "issues": issues}

    def _transactions(self, account, start, end):
        from portfolio_v5.settlement import performance_transactions
        result = performance_transactions(self.repo.store,
            [t for t in self.repo.transactions() if start < t['date'] <= end], account)
        from .depot_purchase_flows import purchase_flows
        result.extend(t for t in purchase_flows(self.repo)
                      if (account is None or t['account'] == account) and start < t['date'] <= end)
        return sorted(result, key=lambda t: (t['date'], t['external_id']))

    def analyze(self, account, requested_start, requested_end, benchmark=None):
        """Berechnet verkettete Modified-Dietz-TWR, tägliche TTWROR, XIRR und Chartreihen.

        ``benchmark`` ist optional ein Symbol aus den Marktdaten-Feeds; dann wird
        der Vergleichsindex aus der Kurshistorie ergänzt (aktive Rendite, Tracking
        Error) und unter ``result['benchmark']`` abgelegt.
        """
        def failed(message, action):
            return {'error': message, 'issues': [dict(level='error', title=message, action=action)]}
        points = [p for p in self.valuation_series(account)
                  if requested_start <= p["date"] <= requested_end]
        if len(points) < 2:
            return failed('Mindestens zwei historische Bewertungen im Zeitraum erforderlich.',
                          'Einen größeren Zeitraum wählen oder mindestens zwei datierte Depotbestände importieren.')
        if any(p['currencies'] - {'EUR'} for p in points):
            return failed('Rendite nicht berechenbar: historische Bewertungen müssen in EUR vorliegen.',
                          'Historische Wechselkurse ergänzen und die Bewertungen erneut erzeugen.')
        if any(p['depots'] != points[0]['depots'] for p in points):
            return failed('Rendite nicht berechenbar: Depotabdeckung ändert sich im Zeitraum.',
                          'Ein einzelnes Depot oder einen Zeitraum mit gleicher Depotabdeckung wählen.')
        start, end = points[0]["date"], points[-1]["date"]
        try:
            transactions = self._transactions(account, start, end)
        except ValueError as error:
            return failed(str(error), 'Verrechnungskonto am Depot und Depotzuordnung der Dividenden prüfen.')
        if any(t["kind"] in ("TRANSFER_IN", "TRANSFER_OUT") for t in transactions):
            return failed('Depotüberträge im Zeitraum müssen vor der Renditeberechnung abgestimmt werden.',
                          'Ein- und ausgehende Überträge miteinander verknüpfen oder als Kapitalmaßnahme erfassen.')
        relevant = [t for t in transactions if t["kind"] in PERFORMANCE_KINDS]
        if any(t.get('currency') != 'EUR' for t in relevant):
            return failed('Rendite nicht berechenbar: Zahlungsströme benötigen historische EUR-Werte.',
                          'Für alle Fremdwährungsbuchungen den historischen EUR-Gegenwert ergänzen.')
        if any((t['kind'] == 'BUY' and Decimal(t['amount']) > 0)
               or (t['kind'] == 'SELL' and Decimal(t['amount']) < 0) for t in relevant):
            return failed('Rendite nicht berechenbar: Vorzeichen der Käufe/Verkäufe sind widersprüchlich.',
                          'Käufe als negative und Verkäufe als positive Zahlungsströme erfassen.')

        twr_factor = Decimal(1)
        twr_series = [{"date": start, "index": Decimal(100)}]
        cumulative_receipts = ZERO
        capital_series = [{"date": start, "value": points[0]["value"]}]
        # Zahlungsströme sind aufsteigend sortiert; ein laufender Zeiger
        # verteilt sie in einem Durchgang auf die Teilperioden (O(Punkte + Ströme)
        # statt O(Punkte × Ströme) durch erneutes Durchsuchen je Intervall).
        relevant.sort(key=lambda t: (t['date'], t['external_id']))
        pointer = 0
        interval_risks = []
        for previous, current in zip(points, points[1:]):
            d0, d1 = date.fromisoformat(previous["date"]), date.fromisoformat(current["date"])
            interval_days = max((d1 - d0).days, 1)
            interval_txs = []
            while pointer < len(relevant) and relevant[pointer]["date"] <= current["date"]:
                if relevant[pointer]["date"] > previous["date"]:
                    interval_txs.append(relevant[pointer])
                pointer += 1
            receipts = sum((Decimal(t["amount"]) for t in interval_txs), ZERO)
            weighted_receipts = sum(
                (Decimal(t["amount"]) * Decimal((d1 - date.fromisoformat(t["date"])).days)
                 / Decimal(interval_days) for t in interval_txs), ZERO)
            denominator = previous["value"] - weighted_receipts
            if denominator <= 0:
                return failed(f"Modified Dietz am {current['date']} nicht berechenbar: Kapitalbasis ist nicht positiv.",
                              'Bewertung und Zahlungsströme dieser Teilperiode prüfen.')
            interval_return = (current["value"] - previous["value"] + receipts) / denominator
            if interval_return < -1:
                return failed(f"Modified Dietz am {current['date']} nicht verkettbar: Teilperiodenrendite unter −100 %.",
                              'Bewertungen, Käufe, Verkäufe und Überträge dieser Teilperiode prüfen.')
            twr_factor *= Decimal(1) + interval_return
            twr_series.append({"date": current["date"], "index": twr_factor * Decimal(100)})
            flows_by_day = {}
            true_flows = []
            for t in interval_txs:
                remaining = (d1 - date.fromisoformat(t["date"])).days
                flows_by_day.setdefault(t["date"], ZERO)
                flows_by_day[t["date"]] += Decimal(t["amount"])
                true_flows.append((remaining, Decimal(t["amount"])))
            daily_growth = _solve_daily_growth(previous["value"], current["value"],
                                               true_flows, interval_days,
                                               ((Decimal(1) + interval_return)
                                                ** (Decimal(1) / Decimal(interval_days))))
            interval_risks.append((d0, d1, daily_growth, flows_by_day))
            cumulative_receipts += receipts
            capital_series.append({"date": current["date"],
                                   "value": points[0]["value"] - cumulative_receipts})

        opening, closing = points[0]["value"], points[-1]["value"]
        # Kenngrößen in einem einzigen Durchgang über die Zahlungsströme
        # zusammenfassen (statt vier separater Listen-Generatoren).
        receipts = ZERO
        dividends = ZERO
        gross_dividends = ZERO
        gross_complete = True
        dividend_net_complete = True
        fees = ZERO
        taxes = ZERO
        for t in relevant:
            amount = Decimal(t["amount"])
            receipts += amount
            if t["kind"] == "DIVIDEND":
                dividends += amount
                if t.get("income_basis") == "gross":
                    dividend_net_complete = False
                if t.get('gross_income') is None or t.get('gross_currency') != 'EUR':
                    gross_complete = False
                else:
                    gross_dividends += Decimal(t['gross_income'])
            fees += Decimal(t.get("fees") or 0)
            taxes += Decimal(t.get("taxes") or 0)
        gross_dividends = gross_dividends if gross_complete else None
        profit = closing - opening + receipts
        flows = [(start, -opening), *[(t["date"], Decimal(t["amount"])) for t in relevant],
                 (end, closing)]
        xirr_rate, xirr_error = xirr(flows)
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        twr = twr_factor - Decimal(1)
        annualized = ((Decimal(1) + twr) ** (Decimal(365) / Decimal(days)) - Decimal(1)
                      if days > 0 and twr >= -1 else None)
        coverage = bool(account and self.repo.has_coverage(account, start, end))
        snapshots = self.repo.snapshots(account)
        latest_by_day = [{}, {}]
        for snap in snapshots:
            if snap['effective_date'] <= start:
                latest_by_day[0][canonical_depot(snap['depot'])] = snap
            if snap['effective_date'] <= end:
                latest_by_day[1][canonical_depot(snap['depot'])] = snap
        boundary_proofs = [
            bool(latest and all(s['complete'] and s['as_of'] == day for s in latest.values()))
            for latest, day in zip(latest_by_day, (start, end))]
        valuation_confirmed = all(boundary_proofs)
        excluded = [t for t in transactions if t['kind'] not in PERFORMANCE_KINDS]
        issues = []
        if not dividend_net_complete:
            issues.append(dict(level='warning', title='Dividenden enthalten Gutschriften vor separat abgerechneten Steuern.',
                               action='Separate Steuerbuchungen zuordnen; die angezeigten Dividendenzuflüsse sind noch kein belegter Nettoertrag.'))
        if not account:
            issues.append(dict(level='warning', title='Alle Konten gemeinsam sind nicht lückenlos bestätigt.',
                               action='Für eine prüfbare Rendite ein einzelnes Konto oder Depot auswählen.'))
        elif not coverage:
            issues.append(dict(level='warning', title='Die Buchungsabdeckung ist nicht bestätigt.',
                               action='Anfangs- und Enddatum der importierten Buchungen prüfen und fehlende Buchungen importieren.'))
        if not valuation_confirmed:
            issues.append(dict(level='warning', title='Anfangs- oder Endbewertung ist nicht tagesgenau vollständig.',
                               action='Vollständige Depotstände genau für Beginn und Ende des Zeitraums importieren.'))
        if excluded:
            kinds = ', '.join(sorted({t['kind'] for t in excluded}))
            issues.append(dict(level='warning', title=f'{len(excluded)} Buchungen wurden nicht als Performance-Zahlungsstrom verwendet ({kinds}).',
                               action='Buchungsarten prüfen und gegebenenfalls korrekt klassifizieren.'))
        if xirr_error:
            issues.append(dict(level='warning', title='XIRR ist nicht berechenbar: ' + xirr_error,
                               action='Es werden mindestens ein negativer und ein positiver datierter Zahlungsstrom benötigt.'))
        if start != requested_start or end != requested_end:
            issues.append(dict(level='info', title=f'Berechnet wurde der verfügbare Zeitraum {start} bis {end}.',
                               action='Für den gewünschten Randzeitraum zusätzliche Depotbewertungen importieren.'))
        daily_index = _daily_valuation_index(interval_risks)
        risk = _index_risk(daily_index)
        daily_returns = [{'date': point['date'], 'return': point['return']}
                         for point in daily_index[1:]]
        ttr_factor = Decimal(daily_index[-1]['index']) / Decimal(100) if daily_index else None
        ttwror = ttr_factor - 1 if ttr_factor is not None else None
        ttwror_annualized = (ttr_factor ** (Decimal(365) / Decimal(days)) - 1
                             if ttr_factor is not None and days > 0 and ttr_factor >= 0 else None)
        benchmark_result = None
        if benchmark and daily_index:
            from .benchmark_service import benchmark_daily_index, compare_daily_indexes
            benchmark_points = benchmark_daily_index(self.repo, benchmark, date.fromisoformat(start), date.fromisoformat(end))
            if benchmark_points:
                comparison = compare_daily_indexes(daily_index, benchmark_points)
                benchmark_result = {
                    'symbol': benchmark, 'index': benchmark_points,
                    'comparison': comparison,
                }
                if comparison is None:
                    issues.append(dict(level='info', title=f'Benchmark {benchmark}: kein gemeinsamer Zeitraum mit dem Portfolio.',
                                       action='Kurshistorie des Vergleichsindex für den Auswertungszeitraum ergänzen.'))
            else:
                issues.append(dict(level='warning', title=f'Benchmark {benchmark}: keine Kursdaten im Zeitraum.',
                                   action='Kurshistorie des Vergleichsindex importieren oder Symbol in den Marktdaten prüfen.'))
        return {
            "start": start, "end": end, "opening": opening, "closing": closing,
            "value_change": (closing / opening - 1) if opening else None,
            "twr": twr, "twr_annualized": annualized, "xirr": xirr_rate,
            "xirr_error": xirr_error, "profit": profit, "net_contributions": -receipts,
            "ttwror": ttwror, "ttwror_annualized": ttwror_annualized,
            "total_return": ttwror,
            "total_return_annualized": ttwror_annualized,
            "dividends": dividends,
            "dividends_net_complete": dividend_net_complete,
            "gross_dividends": gross_dividends,
            "fees": fees,
            "taxes": taxes,
            "transaction_count": len(transactions), "coverage_confirmed": coverage,
            "quality": "vollständig" if coverage else "geschätzt",
            "valuation_confirmed": valuation_confirmed,
            "method": "Verketteter Modified Dietz (Näherung)",
            "cash_flow_timing": "Tagesende; Starttag bereits im Anfangswert enthalten",
            "valuation_series": points, "capital_series": capital_series,
            "twr_series": twr_series, "transactions": relevant,
            "daily_index": daily_index, "daily_returns": daily_returns,
            "daily_total_return_series": daily_index,
            "benchmark": benchmark_result,
            "volatility_annualized": risk['volatility_annualized'],
            "semivolatility_annualized": risk['semivolatility_annualized'],
            "max_drawdown": risk['max_drawdown'],
            "current_drawdown": risk['current_drawdown'],
            "longest_drawdown_days": risk['longest_drawdown_days'],
            "issues": issues,
        }

    def comparison(self, account=None):
        rows = []
        for label, (start, end) in self.preset_ranges(account).items():
            result = self.analyze(account, start.isoformat(), end.isoformat())
            result["label"] = label
            rows.append(result)
        return rows

    def period(self, account, start, end):
        result = security_performance(self.repo.store, account, start, end)
        try:
            tx = self._transactions(account, start, end)
        except ValueError as error:
            return {'error': str(error)}
        result["transaction_count"] = len(tx)
        result["fees"] = sum((Decimal(t["fees"] or 0) for t in tx), ZERO)
        result["taxes"] = sum((Decimal(t["taxes"] or 0) for t in tx), ZERO)
        result["coverage_confirmed"] = bool(account and self.repo.has_coverage(account, start, end))
        return result
