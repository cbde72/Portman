"""Risk, ETF look-through and rebalancing analysis panes."""
from decimal import Decimal

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QMessageBox, QSpinBox, QTreeWidgetItem

from portman.etf_fetcher import ETFLookThroughFetcher
from portman.portfolio_risk import calculate_hhi, get_concentration_warnings
from portman.rebalancing import plan_rebalancing
from portman.security_classification import ASSET_TYPES, REGIONS

from portman.gui.window_compat import project_root


class AnalysisMixin:
    def setup_rebalancing_ui(self):
        category = self.get_current_category()
        while self.target_form.rowCount() > 0:
            self.target_form.removeRow(0)
        self.spin_targets.clear()

        if category == "Alle":
            self.target_group.setTitle("Ziel-Allokation nach Assetklassen (%)")
            groups = ASSET_TYPES
            defaults = {"Aktie": 40, "ETF": 50, "Krypto": 10, "Sonstiges": 0}
        else:
            self.target_group.setTitle(f"Ziel-Allokation ({category}) nach Regionen (%)")
            groups = REGIONS
            defaults = {"USA": 40, "Europa": 30, "Welt": 20, "Emerging Markets": 10, "Japan": 0, "Sonstige": 0}

        for g in groups:
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setValue(defaults.get(g, 0))
            spin.valueChanged.connect(self.calculate_rebalancing)
            self.spin_targets[g] = spin
            self.target_form.addRow(f"Ziel {g} (%):", spin)

    def update_lookthrough_analysis(self):
        self.tree_lookthrough.clear()
        all_holdings = list(self.holdings.values())
        cumulated = {}

        for h in all_holdings:
            if h.asset_type == 'Aktie':
                sname = h.name
                if sname not in cumulated:
                    cumulated[sname] = {'direct': 0.0, 'via_etf': {}, 'total': 0.0}
                cumulated[sname]['direct'] += h.market_value
                cumulated[sname]['total'] += h.market_value

        for h in all_holdings:
            if h.asset_type == 'ETF':
                top_list = self.etf_cache.get(h.isin, [])
                for item in top_list:
                    sname = item['name']
                    weight = item['weight_pct'] / 100.0
                    val_via_etf = h.market_value * weight

                    if sname not in cumulated:
                        cumulated[sname] = {'direct': 0.0, 'via_etf': {}, 'total': 0.0}

                    cumulated[sname]['via_etf'][h.name] = cumulated[sname]['via_etf'].get(h.name, 0.0) + val_via_etf
                    cumulated[sname]['total'] += val_via_etf

        sorted_stocks = sorted(cumulated.items(), key=lambda x: x[1]['total'], reverse=True)

        for stock_name, data in sorted_stocks:
            total_via_etf = sum(data['via_etf'].values())

            root_item = QTreeWidgetItem([
                stock_name,
                "Kumuliert",
                f"{round(data['direct'], 2)} €",
                f"{round(total_via_etf, 2)} €",
                f"{round(data['total'], 2)} €"
            ])
            root_item.setFont(0, QFont("Arial", 9, QFont.Bold))

            if data['direct'] > 0:
                child_dir = QTreeWidgetItem([
                    "  └─ Direkt im Depot",
                    "Aktie",
                    f"{round(data['direct'], 2)} €",
                    "0.00 €",
                    f"{round(data['direct'], 2)} €"
                ])
                root_item.addChild(child_dir)

            for etf_name, etf_val in data['via_etf'].items():
                child_etf = QTreeWidgetItem([
                    f"  └─ via {etf_name}",
                    "ETF Anteil",
                    "0.00 €",
                    f"{round(etf_val, 2)} €",
                    f"{round(etf_val, 2)} €"
                ])
                root_item.addChild(child_etf)

            self.tree_lookthrough.addTopLevelItem(root_item)

    def update_risk_analysis(self):
        cat_holdings = self.get_filtered_holdings()
        category = self.get_current_category()

        if not cat_holdings:
            self.lbl_hhi.setText("<b>Diversifikations-Score (HHI):</b> -")
            self.lbl_beta.setText("<b>Gewichtetes Markt-Beta:</b> -")
            self.lbl_vola.setText("<b>Gewichtete Einzelvolatilität:</b> -")
            self.lbl_div_total.setText("<b>Hinterlegte Dividendenrendite:</b> -")
            self.tree_warnings.clear()
            return

        hhi = calculate_hhi(cat_holdings)
        if hhi < 1500: hhi_text = f"<font color='green'>{round(hhi, 1)} (Gut diversifiziert)</font>"
        elif hhi < 2500: hhi_text = f"<font color='orange'>{round(hhi, 1)} (Moderate Konzentration)</font>"
        else: hhi_text = f"<font color='red'>{round(hhi, 1)} (Hohe Konzentration!)</font>"
        self.lbl_hhi.setText(f"<b>Diversifikations-Score ({category}):</b> {hhi_text}")

        records = self.repository.market.records()
        total_val = sum(h.market_value for h in cat_holdings if h.market_value > 0)
        for label, metric, title, suffix in (
            (self.lbl_beta, 'beta', 'Gewichtetes Beta', ''),
            (self.lbl_vola, 'volatility_pct', 'Gewichtete Einzelvolatilität', ' % p.a.'),
            (self.lbl_div_total, 'dividend_yield_pct', 'Hinterlegte Dividendenrendite', ' %'),
        ):
            weighted = covered = 0.0
            for h in cat_holdings:
                record = records.get(h.isin or h.wkn, {})
                manual = record.get('manual', {}).get('fields', {})
                value = manual.get(metric, record.get('data', {}).get('metrics', {}).get(metric))
                if value is not None and h.market_value > 0:
                    weighted += h.market_value * float(value); covered += h.market_value
            text = f'{weighted / covered:.2f}{suffix} · Abdeckung {covered / total_val * 100:.0f} %' if covered and total_val else 'keine belegten Daten'
            label.setText(f'<b>{title}:</b> {text}')
            label.setToolTip('Gespeicherte Online- oder manuelle Kennzahlen, nicht historisiert. Einzelvolatilitäten berücksichtigen keine Korrelationen und sind keine Portfoliovolatilität.')

        threshold = float(self.spin_threshold.value())
        warnings = get_concentration_warnings(cat_holdings, threshold)
        self.tree_warnings.clear()
        for w in warnings:
            item = QTreeWidgetItem([
                w['name'], w['isin'],
                f"{round(w['weight_pct'], 2)} %", f"{round(w['market_value'], 2)} €"
            ])
            item.setBackground(2, QColor(255, 230, 230))
            self.tree_warnings.addTopLevelItem(item)

    def calculate_rebalancing(self):
        cat_holdings = self.get_filtered_holdings()
        category = self.get_current_category()
        self.tree_rebalance.clear()
        if not cat_holdings:
            self.lbl_rebalance_summary.setText('Keine Positionen für diese Auswahl.')
            return
        current={}
        for group_name in self.spin_targets:
            current[group_name]=sum(h.market_value for h in cat_holdings if (h.asset_type if category=="Alle" else h.region)==group_name)
        result=plan_rebalancing(current,{g:s.value() for g,s in self.spin_targets.items()},self.spin_rebalance_cash.value(),self.spin_rebalance_tolerance.value(),self.spin_rebalance_minimum.value(),self.spin_rebalance_fee.value(),self.combo_rebalance_mode.currentIndex()==0)
        valid=abs(result['target_sum']-100)<Decimal('0.01')
        self.lbl_rebalance_summary.setText(f"Zielsumme: {result['target_sum']} % · Kaufbudget inkl. Gebühren: {result['cash_used']:.2f} € · Verkäufe: {result['sales']:.2f} €" + ("" if valid else " · ⚠ Zielgewichte ergeben nicht 100 %"))
        for row in result['rows']:
            action=row['action'];action_str="Keine Order" if not action else (f"+{action:.2f} Kaufen" if action>0 else f"{action:.2f} Verkaufen")
            item=QTreeWidgetItem([row['group'],f"{row['current_pct']:.2f} %",f"{row['target_pct']:.2f} %",f"{row['current']:.2f} €",f"{row['target_value']:.2f} €",action_str,f"{row['fee']:.2f} €",f"{row['after_pct']:.2f} %"])
            if action>0:item.setBackground(5,QColor(230,255,230))
            elif action<0:item.setBackground(5,QColor(255,230,230))
            elif row['within_tolerance']:item.setBackground(5,QColor(235,235,235))
            self.tree_rebalance.addTopLevelItem(item)

    def fetch_etf_holdings_online(self):
        etfs = [h for h in self.holdings.values() if h.asset_type == 'ETF']
        if not etfs:
            QMessageBox.information(self, "Info", "Keine ETFs im Portfolio gefunden.")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(50)
        self.etf_fetcher = ETFLookThroughFetcher(etfs, project_root() / "factsheets")
        self.etf_fetcher.progress.connect(self.status_bar.showMessage)
        self.etf_fetcher.finished.connect(self.on_etf_fetch_done)
        self.etf_fetcher.start()

    def on_etf_fetch_done(self, new_etf_data: dict, failures: dict):
        self.progress_bar.setVisible(False)
        self.etf_cache.update(new_etf_data)
        self.storage.save_etf_cache(self.etf_cache)
        self.update_lookthrough_analysis()
        count = sum(len(v) for v in new_etf_data.values())
        factsheet_count = sum(
            1 for values in new_etf_data.values()
            if values and str(values[0].get('source', '')).startswith('Factsheet')
        )
        self.status_bar.showMessage(f"{count} Positionen aus {len(new_etf_data)} ETFs geladen; {len(failures)} ohne Ergebnis.", 7000)
        details = (f"{count} Einzelpositionen aus {len(new_etf_data)} ETFs geladen.\n"
                   f"Davon {factsheet_count} ETFs aus lokalen Factsheets.")
        if failures:
            details += "\n\nOhne Ergebnis:\n" + "\n".join(failures.values())
            QMessageBox.warning(self, "ETF-Durchrechnung teilweise geladen", details)
        else:
            QMessageBox.information(self, "ETF-Durchrechnung", details)
