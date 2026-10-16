"""Date/account scope controls and portfolio reload."""
from portman.busy_indicator import busy_operation
from portman.date_display import display_dates
from portman.holding import Holding
from PySide6.QtCore import QTimer, QDate


class DateScopeMixin:
    def selected_accounts(self):
        """Konten, die per Checkbox-Mehrfachauswahl aktiviert sind.

        Gibt eine Liste der gewählten Kontennamen zurück; bei keiner aktiven
        Auswahl eine leere Liste.
        """
        mapping = getattr(self, 'account_checkbox_accounts', None)
        if mapping and getattr(self, 'account_checkboxes', None):
            return [account for cb, account in mapping.items() if cb.isChecked()]
        return []

    def selected_account(self):
        """Einzelnes Konto für Widgets, die nur einen Scope akzeptieren.

        Bei aktiver Mehrfachauswahl wird das erste gewählte Konto geliefert,
        sonst der Wert der Combo-Box (None = alle Konten).
        """
        selected = self.selected_accounts()
        if selected:
            return selected[0]
        return self.combo_account.currentData() if hasattr(self, 'combo_account') else None

    def selected_date(self):
        if hasattr(self, 'date_selector'):
            return self.date_selector.date().toString('yyyy-MM-dd')
        return self.combo_snapshot.currentData() if hasattr(self, 'combo_snapshot') else '9999-12-31'

    def select_calendar_date(self, value):
        stamp = value.toString('yyyy-MM-dd')
        index = self.combo_snapshot.findData(stamp)
        if index < 0:
            self.combo_snapshot.addItem(display_dates(stamp), stamp)
            index = self.combo_snapshot.count() - 1
        self.combo_snapshot.setCurrentIndex(index)

    def step_snapshot(self, offset):
        self.shift_date(days=-offset)

    def shift_date(self, days=0, months=0):
        self.date_selector.setDate(self.date_selector.date().addMonths(months).addDays(days))

    def update_date_navigation(self, *args):
        self.btn_previous_date.setEnabled(self.date_selector.date() > self.date_selector.minimumDate())
        self.btn_next_date.setEnabled(self.date_selector.date() < self.date_selector.maximumDate())
        for button in (self.btn_previous_week, self.btn_previous_month):
            button.setEnabled(self.btn_previous_date.isEnabled())
        for button in (self.btn_next_week, self.btn_next_month):
            button.setEnabled(self.btn_next_date.isEnabled())

    def dashboard_scope(self):
        return self.selected_account(), self.selected_date()

    @busy_operation
    def reload_portfolio(self, refresh=True, visible_only=False):
        self._reload_pending = False
        if getattr(self, '_refresh_timer', None) is not None and self._refresh_timer.isActive():
            self._refresh_timer.stop()
        selected_accounts = self.selected_accounts()
        rows = self.repository.current(self.selected_date(), self.selected_account())
        if selected_accounts:
            allowed = set(selected_accounts)
            rows = [p for p in rows if allowed & (p.get('accounts') or {p.get('account', '')})]
        self.holdings = {}
        for p in rows:
            key = p.get('isin') or p['key']
            self.holdings[key] = Holding(
                isin=p.get('isin') or p['key'], wkn=p.get('wkn',''), name=p.get('name',key),
                asset_type=p.get('asset_type','Sonstiges'), amount=float(p.get('quantity') or 0),
                buy_value=float(p.get('cost') or 0), market_value=float(p.get('value') or 0),
                region=p.get('region','Unbekannt'), cap_size=p.get('cap_size','Unbekannt'),
                beta=float(p.get('beta',1)), volatility=float(p.get('volatility',15)),
                dividend_yield=float(p.get('dividend_yield',0)))
        if refresh and hasattr(self, 'tabs'):
            if hasattr(self, '_scope_refreshers'):
                self.refresh_visible_scope()
                return
            if visible_only:
                return
            self.refresh_all_views()
            if hasattr(self, 'history_widget'): self.history_widget.refresh()
            if hasattr(self, 'dashboard'): self.dashboard.refresh()
            if hasattr(self, 'performance_widget'): self.performance_widget.refresh()
            if hasattr(self, 'quality_widget'): self.quality_widget.refresh()
            if hasattr(self, 'accounts_widget'): self.accounts_widget.refresh()
            if hasattr(self, 'visuals_widget'): self.visuals_widget.refresh()
            if hasattr(self, 'chart_grid_widget'): self.chart_grid_widget.refresh()
            if hasattr(self, 'market_widget'): self.market_widget.refresh()
            self._scope_dirty = set()

    def _schedule_reload(self, refresh=True, visible_only=False):
        self._reload_pending = True
        if getattr(self, '_refresh_timer', None) is None:
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.setInterval(200)
            self._refresh_timer.timeout.connect(lambda r=refresh, v=visible_only: self.reload_portfolio(refresh=r, visible_only=v))
        elif self._refresh_timer.isActive():
            return
        self._refresh_timer.start()

    def on_portfolio_scope_changed(self):
        if hasattr(self, 'date_selector'):
            stamp = self.combo_snapshot.currentData()
            value = QDate.currentDate() if stamp == '9999-12-31' else QDate.fromString(stamp or '', 'yyyy-MM-dd')
            if value.isValid():
                self.date_selector.blockSignals(True)
                self.date_selector.setDate(value)
                self.date_selector.blockSignals(False)
        self._schedule_reload(visible_only=hasattr(self, '_scope_refreshers'))

    def refresh_scope_choices(self):
        account = self.selected_account()
        self.combo_account.blockSignals(True); self.combo_account.clear(); self.combo_account.addItem("Alle Konten",None)
        for value in self.repository.accounts(): self.combo_account.addItem(value,value)
        idx=self.combo_account.findData(account); self.combo_account.setCurrentIndex(max(0,idx)); self.combo_account.blockSignals(False)
        if hasattr(self, 'rebuild_account_checkboxes'):
            self.rebuild_account_checkboxes()
        selected=self.selected_date(); self.combo_snapshot.blockSignals(True); self.combo_snapshot.clear(); self.combo_snapshot.addItem('Aktuell','9999-12-31')
        for label, value in self.repository.scope_dates(): self.combo_snapshot.addItem(display_dates(label),value)
        if selected and self.combo_snapshot.findData(selected) < 0:
            self.combo_snapshot.addItem(selected, selected)
        idx=self.combo_snapshot.findData(selected); self.combo_snapshot.setCurrentIndex(max(0,idx)); self.combo_snapshot.blockSignals(False)
        self.update_date_navigation()
