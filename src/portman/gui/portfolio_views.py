"""Position tables, filters, tab routing and chart refresh."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidgetItem

from portman.holding import Holding


class PortfolioViewsMixin:
    def get_current_category(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())

    def get_filtered_holdings(self) -> list[Holding]:
        selected_region = self.combo_region.currentText()
        selected_cap = self.combo_cap.currentText()
        category = self.get_current_category()

        filtered = list(self.holdings.values())
        if category != "Alle":
            filtered = [h for h in filtered if h.asset_type == category]
        if selected_region != "Alle Regionen":
            filtered = [h for h in filtered if h.region == selected_region]
        if selected_cap != "Alle Cap-Größen":
            filtered = [h for h in filtered if h.cap_size == selected_cap]

        return filtered

    def on_tab_changed(self, index: int):
        if self.tabs.widget(index).objectName() == 'depotOverview':
            if hasattr(self, 'totals'): self.totals.hide()
            self.tabs.widget(index).refresh()
            return
        if hasattr(self, 'totals'): self.totals.show()
        category = self.get_current_category()
        self.dock_risk.setWindowTitle(f"Risiko & Kennzahlen ({category})")
        self.dock_rebalance.setWindowTitle(f"Rebalancing-Rechner ({category})")
        self.setup_rebalancing_ui()
        self.refresh_all_views()

    def apply_filters(self):
        self.refresh_tables()
        self.update_chart()
        self.update_risk_analysis()
        self.calculate_rebalancing()

    def refresh_all_views(self):
        self.refresh_tables()
        self.update_chart()
        self.update_risk_analysis()
        self.calculate_rebalancing()
        self.update_lookthrough_analysis()

    def refresh_tables(self):
        market_records = self.repository.market.records()
        all_holdings = list(self.holdings.values())
        selected_region = self.combo_region.currentText()
        selected_cap = self.combo_cap.currentText()

        for category, table in self.tables.items():
            table.setSortingEnabled(False)
            table.setRowCount(0)

            cat_holdings = all_holdings if category == "Alle" else [h for h in all_holdings if h.asset_type == category]
            if selected_region != "Alle Regionen": cat_holdings = [h for h in cat_holdings if h.region == selected_region]
            if selected_cap != "Alle Cap-Größen": cat_holdings = [h for h in cat_holdings if h.cap_size == selected_cap]
            query = self.position_search.text().strip().casefold() if hasattr(self, 'position_search') else ''
            if query: cat_holdings = [h for h in cat_holdings if query in (h.name + ' ' + h.isin).casefold()]

            category_total_val = sum(h.market_value for h in cat_holdings)

            for row_idx, h in enumerate(cat_holdings):
                table.insertRow(row_idx)
                table.setItem(row_idx, 0, QTableWidgetItem(h.isin))
                table.item(row_idx, 0).setData(Qt.ItemDataRole.UserRole, h.isin or ('WKN:' + h.wkn))
                table.setItem(row_idx, 1, QTableWidgetItem(h.name))
                table.item(row_idx, 1).setToolTip('Doppelklick: Anlageklasse, Region und Cap auswählen oder zurücksetzen.')
                table.setItem(row_idx, 2, QTableWidgetItem(h.asset_type))
                table.setItem(row_idx, 3, QTableWidgetItem(h.region))
                table.setItem(row_idx, 4, QTableWidgetItem(h.cap_size))

                item_amt = QTableWidgetItem()
                item_amt.setData(Qt.ItemDataRole.DisplayRole, round(h.amount, 4))
                table.setItem(row_idx, 5, item_amt)

                item_buy = QTableWidgetItem()
                item_buy.setData(Qt.ItemDataRole.DisplayRole, round(h.buy_value, 2) if h.buy_value > 0 else "–")
                table.setItem(row_idx, 6, item_buy)

                item_mkt = QTableWidgetItem()
                item_mkt.setData(Qt.ItemDataRole.DisplayRole, round(h.market_value, 2))
                table.setItem(row_idx, 7, item_mkt)

                item_pnl = QTableWidgetItem()
                item_pnl.setData(Qt.ItemDataRole.DisplayRole, round(h.profit_loss, 2) if h.buy_value > 0 else "–")
                if h.profit_loss < 0: item_pnl.setForeground(QColor(Qt.GlobalColor.red))
                elif h.profit_loss > 0: item_pnl.setForeground(QColor(Qt.GlobalColor.darkGreen))
                table.setItem(row_idx, 8, item_pnl)

                item_div_yield = QTableWidgetItem()
                item_div_yield.setData(Qt.ItemDataRole.DisplayRole, market_records.get(h.isin or h.wkn, {}).get('manual', {}).get('fields', {}).get('dividend_yield_pct', '–'))
                table.setItem(row_idx, 9, item_div_yield)

                item_div_val = QTableWidgetItem()
                item_div_val.setData(Qt.ItemDataRole.DisplayRole, round(h.market_value * market_records[h.isin or h.wkn]['manual']['fields']['dividend_yield_pct'] / 100, 2) if market_records.get(h.isin or h.wkn, {}).get('manual', {}).get('fields', {}).get('dividend_yield_pct') is not None else '–')
                table.setItem(row_idx, 10, item_div_val)

                share_pct = (h.market_value / category_total_val * 100.0) if category_total_val > 0 else 0.0
                item_share = QTableWidgetItem()
                item_share.setData(Qt.ItemDataRole.DisplayRole, round(share_pct, 2))
                table.setItem(row_idx, 11, item_share)

            table.setSortingEnabled(True)

    def update_chart(self):
        cat_holdings = self.get_filtered_holdings()
        category = self.get_current_category()
        view_type = self.combo_chart_type.currentText()

        if "Pie" in view_type:
            mapping = {"Pie: Asset/Region Allokation": "asset_type"}
            group_key = mapping.get(view_type, "region")
            self.chart_canvas.plot_pie_allocation(cat_holdings, group_by=group_key, title_suffix=category)
        elif "Heatmap" in view_type:
            self.chart_canvas.plot_performance_heatmap(cat_holdings)
        elif "Benchmarking" in view_type:
            self.chart_canvas.plot_benchmarking(cat_holdings)
