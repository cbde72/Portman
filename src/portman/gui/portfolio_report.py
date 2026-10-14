"""HTML portfolio report and rebalancing CSV export."""
import csv
import html as html_lib
from datetime import datetime

from PySide6.QtWidgets import QFileDialog, QMessageBox

from portman.performance_service import PerformanceService


class PortfolioReportMixin:
    def export_portfolio_report(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Bericht speichern", "portfolio_bericht.html", "HTML Files (*.html)")
        if not filepath: return

        summary = PerformanceService(self.repository).overview(self.selected_date(), self.selected_account())
        total_val, total_buy, pnl = (float(summary[k]) for k in ('value', 'cost', 'pnl'))
        pnl_pct_text = '–' if summary['pnl_pct'] is None else f"{float(summary['pnl_pct']) * 100:.2f} %"
        coverage = f"Einstand und Gewinn nur für {summary['known_cost_positions']} von {len(summary['positions'])} Positionen mit bekanntem Einstand."
        records = self.repository.market.records()

        html = f"""
        <html>
        <head><meta charset="utf-8"><title>Portfolio Bericht</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
            h1 {{ color: #2c3e50; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
            th {{ background-color: #f4f4f4; }}
            .green {{ color: green; font-weight: bold; }}
            .red {{ color: red; font-weight: bold; }}
        </style>
        </head>
        <body>
            <h1>📊 Portfolio-Gesamtbericht</h1>
            <p><b>Erstellt am:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
            <ul>
                <li><b>Gesamtwert:</b> {round(total_val, 2)} €</li>
                <li><b>Gesamteinstand:</b> {round(total_buy, 2)} €</li>
                <li><b>Gewinn / Verlust:</b> <span class="{'green' if pnl >= 0 else 'red'}">{round(pnl, 2)} € ({pnl_pct_text})</span></li>
                <li>{coverage}</li>
            </ul>
            <h2>Bestandspositionen</h2>
            <table>
                <tr><th>ISIN</th><th>Name</th><th>Typ</th><th>Marktwert (€)</th><th>G/V (%)</th><th>Div. Rendite (%)</th></tr>
        """
        for h in self.holdings.values():
            pnl_color = "green" if h.profit_loss_pct >= 0 else "red"
            gain = f'{h.profit_loss_pct:.2f} %' if h.buy_value > 0 else '–'
            div = records.get(h.isin or h.wkn, {}).get('manual', {}).get('fields', {}).get('dividend_yield_pct')
            div_text = f'{div:.2f} %' if div is not None else '–'
            html += f"<tr><td>{html_lib.escape(h.isin)}</td><td>{html_lib.escape(h.name)}</td><td>{html_lib.escape(h.asset_type)}</td><td>{h.market_value:.2f} €</td><td class='{pnl_color}'>{gain}</td><td>{div_text}</td></tr>"

        html += "</table></body></html>"

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        QMessageBox.information(self, "Export erfolgreich", f"Bericht wurde unter {filepath} gespeichert.")

    def export_rebalancing_plan(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Rebalancing-Plan speichern", "rebalancing_order.csv", "CSV Files (*.csv)")
        if not filepath: return

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow([self.tree_rebalance.headerItem().text(i) for i in range(self.tree_rebalance.columnCount())])
            for i in range(self.tree_rebalance.topLevelItemCount()):
                item = self.tree_rebalance.topLevelItem(i)
                writer.writerow([item.text(col) for col in range(self.tree_rebalance.columnCount())])
        QMessageBox.information(self, "Export erfolgreich", "Rebalancing-Plan als CSV exportiert.")
