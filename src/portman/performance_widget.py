from .date_display import display_dates
from bisect import bisect_left
from datetime import date
from decimal import Decimal
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QTabWidget,
)

from .performance_service import PerformanceService
from .safe_canvas import SafeFigureCanvas
from .chart_style import (COLORS, currency_axis, date_axis,
                          style_axis, style_figure, create_figure)
from .formatting import euro


def percent(value, annualized=False):
    if value is None:
        return "–"
    suffix = " p.a." if annualized else ""
    number = f"{float(value) * 100:+.2f}".replace(".", ",")
    return f"{number} %{suffix}"


class PerformanceWidget(QWidget):
    PRESETS = ["Jahr", "1 Jahr", "3 Jahre", "5 Jahre", "10 Jahre", "Max", "Benutzerdefiniert"]

    def __init__(self, repository, account_getter, parent=None):
        super().__init__(parent)
        self.service = PerformanceService(repository)
        self.account_getter = account_getter
        self.current_result = None
        root = QVBoxLayout(self); root.setContentsMargins(8, 8, 8, 8); root.setSpacing(7)

        bar = QHBoxLayout()
        self.range_combo = QComboBox()
        self.range_combo.addItems(self.PRESETS)
        self.range_combo.setCurrentText("1 Jahr")
        self.range_combo.currentTextChanged.connect(self.on_preset_changed)
        self.start = QDateEdit(); self.end = QDateEdit()
        for editor in (self.start, self.end):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd.MM.yyyy")
        self.start.dateChanged.connect(self.on_date_changed)
        self.end.dateChanged.connect(self.on_date_changed)
        go = QPushButton("Berechnen")
        go.clicked.connect(self.calculate)
        self.benchmark_combo = QComboBox()
        self.benchmark_combo.addItem("Kein Benchmark")
        self.benchmark_combo.currentTextChanged.connect(self.calculate)
        for widget in (QLabel("Zeitraum"), self.range_combo, QLabel("Von"), self.start,
                       QLabel("bis"), self.end, go, QLabel("Benchmark"), self.benchmark_combo):
            bar.addWidget(widget)
        bar.addStretch()
        root.addLayout(bar)

        grid = QGridLayout()
        self.labels = {}
        cards = [
            ("value_change", "Depotwert-Veränderung"),
            ("twr", "Rendite · Modified Dietz (Näherung)"),
            ("annualized", "Dietz-Näherung annualisiert"),
            ("xirr", "XIRR mit Zahlungsströmen"),
            ("profit", "Gewinn nach Zahlungsströmen"),
            ("contributions", "Netto-Zukäufe"),
            ("volatility", "Volatilität (Tagesindex)"),
            ("drawdown", "Max. Drawdown (Tagesindex)"),
            ("semivolatility", "Semivolatilität (Tagesindex)"),
            ("drawdown_current", "Aktueller Drawdown (Tagesindex)"),
            ("drawdown_duration", "Längste Drawdown-Dauer"),
            ("benchmark", "Benchmark (Zeitraum)"),
            ("active", "Aktive Rendite"),
            ("tracking", "Tracking Error (p.a.)"),
        ]
        explanations = {
            'value_change': 'Endwert geteilt durch Anfangswert minus 1. Ein- und Auszahlungen sind darin nicht bereinigt.',
            'twr': 'Verkettete Modified-Dietz-Näherung. Zahlungsströme werden innerhalb jeder Teilperiode zeitlich gewichtet.',
            'annualized': 'Modified-Dietz-Rendite auf 365 Tage hochgerechnet.',
            'xirr': 'Geldgewichtete annualisierte Rendite anhand aller datierten Zahlungsströme.',
            'profit': 'Endwert minus Anfangswert plus Verkäufe und Erträge minus Käufe, Gebühren und Steuern.',
            'contributions': 'Käufe und sonstige Netto-Zuflüsse in das Depot abzüglich Verkäufen und Ausschüttungen.',
            'volatility': 'Jährliche Volatilität des täglichen Bewertungsindex; Teilperiodenrenditen werden geometrisch auf Kalendertage verteilt.',
            'drawdown': 'Größter Rückgang des täglichen Bewertungsindex vom bisherigen Höchststand.',
            'semivolatility': 'Jährliche Abwärtsvolatilität: nur negative Tagesrenditen des Bewertungsindex fließen ein.',
            'drawdown_current': 'Rückgang des Tagesindex vom bisherigen Höchststand zum aktuellen Stand.',
            'drawdown_duration': 'Längster Zeitraum, in dem der Tagesindex unter seinem bisherigen Höchststand lag.',
            'benchmark': 'Rendite des gewählten Vergleichsindex über den gemeinsamen Zeitraum mit dem Portfolio.',
            'active': 'Rendite des Portfolios minus Benchmark-Rendite über den gemeinsamen Zeitraum.',
            'tracking': 'Jährliche Standardabweichung der täglichen Renditedifferenz Portfolio minus Benchmark.',
        }
        for index, (key, title) in enumerate(cards):
            box = QGroupBox(title)
            layout = QVBoxLayout(box)
            label = QLabel("–")
            label.setStyleSheet("font-size:18px;font-weight:bold")
            box.setToolTip(explanations[key]); label.setToolTip(explanations[key])
            layout.addWidget(label)
            grid.addWidget(box, index // 3, index % 3)
            self.labels[key] = label
        root.addLayout(grid)

        self.quality = QLabel(); self.quality.setWordWrap(True); self.quality.setTextFormat(Qt.TextFormat.RichText)
        self.quality.setObjectName('performanceQuality'); root.addWidget(self.quality)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName('muted')
        root.addWidget(self.note)

        self.views = QTabWidget(); root.addWidget(self.views, 1)
        chart_page = QWidget(); chart_layout = QVBoxLayout(chart_page); chart_layout.setContentsMargins(0, 4, 0, 0)
        comparison_page = QWidget(); comparison_layout = QVBoxLayout(comparison_page); comparison_layout.setContentsMargins(0, 4, 0, 0)
        self.comparison = QTableWidget(0, 9)
        self.comparison.setHorizontalHeaderLabels([
            "Zeitraum", "Von", "Bis", "Endwert", "Ergebnis", "Wertänderung",
            "Dietz (Näherung)", "Dietz p.a.", "XIRR",
        ])
        self.comparison.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.comparison.horizontalHeader().setStretchLastSection(True)
        self.comparison.setAlternatingRowColors(True)
        comparison_layout.addWidget(self.comparison)

        chart_bar = QHBoxLayout()
        self.chart_checks = {}
        for key, title, checked in (
            ("value", "Depotwert", True), ("capital", "Investiertes Kapital", True),
            ("profit", "Gewinn/Verlust", True), ("twr", "Dietz-Index (Näherung)", True),
            ("daily", "Tagesindex (Bewertung)", False),
            ("transactions", "Transaktionen", True),
        ):
            checkbox = QCheckBox(title); checkbox.setChecked(checked)
            checkbox.toggled.connect(self.draw_chart)
            self.chart_checks[key] = checkbox
            chart_bar.addWidget(checkbox)
        chart_bar.addStretch()
        chart_layout.addLayout(chart_bar)
        self.fig = create_figure(9, 4)
        # Dieser Verlauf positioniert Achsen und Zeilenabstand selbst
        # (GridSpec mit hspace und subplots_adjust). tight_layout würde die
        # manuell gesetzten Werte übergehen und warnt zudem bei GridSpecs mit
        # lokalem hspace, deshalb hier bewusst kein Layout-Engine.
        self.fig.set_layout_engine("none")
        style_figure(self.fig)
        self.canvas = SafeFigureCanvas(self.fig)
        self.canvas.setMinimumHeight(320)
        chart_layout.addWidget(self.canvas, 1)
        self.views.addTab(chart_page, 'Verlauf')
        self.views.addTab(comparison_page, 'Zeiträume vergleichen')
        from .chart_interaction import install_chart_tooltips
        install_chart_tooltips(self.canvas, self.note.text)
        self.refresh()

    def refresh(self):
        if getattr(self.service.repo,'defer_initial_views',False): return
        ranges = self.service.preset_ranges(self.account_getter())
        if not ranges:
            self.current_result = None
            self.comparison.setRowCount(0)
            for label in self.labels.values(): label.setText('–')
            self.show_quality([dict(level='error', title='Keine historischen Bewertungen vorhanden.',
                action='Über Imports mindestens zwei datierte Depotbestände ergänzen.')])
            self.note.clear()
            self.draw_chart()
            return
        selected = self.range_combo.currentText()
        if selected == 'Benutzerdefiniert':
            start = date.fromisoformat(self.start.date().toString('yyyy-MM-dd'))
            end = date.fromisoformat(self.end.date().toString('yyyy-MM-dd'))
        elif selected not in ranges:
            selected = "Max"
            start, end = ranges[selected]
        else:
            start, end = ranges[selected]
        self._setting_dates = True
        self.start.setDate(QDate(start.year, start.month, start.day))
        self.end.setDate(QDate(end.year, end.month, end.day))
        self._setting_dates = False
        symbols = self._benchmark_symbols()
        current = self.benchmark_combo.currentText()
        self.benchmark_combo.blockSignals(True)
        self.benchmark_combo.clear()
        self.benchmark_combo.addItem("Kein Benchmark")
        self.benchmark_combo.addItems(symbols)
        if current in symbols:
            self.benchmark_combo.setCurrentText(current)
        self.benchmark_combo.blockSignals(False)
        self.benchmark_combo.setEnabled(len(symbols) > 0)
        self.fill_comparison()
        self.calculate()

    def on_preset_changed(self, name):
        if name == "Benutzerdefiniert":
            return
        value = self.service.preset_ranges(self.account_getter()).get(name)
        if value:
            self._setting_dates = True
            for editor, day in zip((self.start, self.end), value):
                editor.setDate(QDate(day.year, day.month, day.day))
            self._setting_dates = False
            self.calculate()

    def on_date_changed(self):
        if not getattr(self, "_setting_dates", False):
            self.range_combo.blockSignals(True)
            self.range_combo.setCurrentText("Benutzerdefiniert")
            self.range_combo.blockSignals(False)

    def fill_comparison(self):
        rows = self.service.comparison(self.account_getter())
        self.comparison.setRowCount(len(rows))
        for row_index, result in enumerate(rows):
            if result.get("error"):
                values = [result["label"], "–", "–", "–", result["error"], "–", "–", "–", "–"]
            else:
                values = [
                    result["label"], result["start"], result["end"], euro(result["closing"]),
                    euro(result["profit"]), percent(result["value_change"]), percent(result["twr"]),
                    percent(result["twr_annualized"], True), percent(result["xirr"], True),
                ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(display_dates(str(value)))
                if column >= 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.comparison.setItem(row_index, column, item)

    def _benchmark_symbols(self):
        symbols = sorted({str(m.get('symbol')) for m in self.service.repo.market.mappings().values()
                          if m.get('symbol')})
        return symbols

    def calculate(self):
        start = self.start.date().toString("yyyy-MM-dd")
        end = self.end.date().toString("yyyy-MM-dd")
        benchmark = self.benchmark_combo.currentText()
        if benchmark == "Kein Benchmark":
            benchmark = None
        result = self.service.analyze(self.account_getter(), start, end, benchmark)
        self.current_result = result
        if result.get("error"):
            for label in self.labels.values(): label.setText("nicht berechenbar")
            self.show_quality(result.get('issues', []))
            self.note.clear()
            self.draw_chart()
            return
        self.labels["value_change"].setText(display_dates(percent(result["value_change"])))
        self.labels["twr"].setText(display_dates(percent(result["twr"])))
        self.labels["annualized"].setText(display_dates(percent(result["twr_annualized"], True)))
        self.labels["xirr"].setText(display_dates(percent(result["xirr"], True)))
        self.labels["profit"].setText(display_dates(euro(result["profit"])))
        self.labels["contributions"].setText(display_dates(euro(result["net_contributions"])))
        volatility = result.get("volatility_annualized")
        self.labels["volatility"].setText(display_dates(percent(volatility, True)))
        self.labels["volatility"].setStyleSheet(
            f'font-size:18px;font-weight:700;color:'
            f'{COLORS["green"] if volatility is not None and volatility > 0 else COLORS["text"]}')
        drawdown = result.get("max_drawdown")
        self.labels["drawdown"].setText(
            display_dates(percent(-drawdown) if drawdown is not None and drawdown > 0 else '–'))
        self.labels["drawdown"].setStyleSheet(
            f'font-size:18px;font-weight:700;color:'
            f'{COLORS["red"] if drawdown is not None and drawdown > 0 else COLORS["text"]}')
        semivolatility = result.get("semivolatility_annualized")
        self.labels["semivolatility"].setText(display_dates(percent(semivolatility, True)))
        self.labels["semivolatility"].setStyleSheet(
            f'font-size:18px;font-weight:700;color:'
            f'{COLORS["green"] if semivolatility is not None and semivolatility > 0 else COLORS["text"]}')
        current_drawdown = result.get("current_drawdown")
        self.labels["drawdown_current"].setText(
            display_dates(percent(-current_drawdown) if current_drawdown is not None and current_drawdown > 0 else '–'))
        self.labels["drawdown_current"].setStyleSheet(
            f'font-size:18px;font-weight:700;color:'
            f'{COLORS["red"] if current_drawdown is not None and current_drawdown > 0 else COLORS["text"]}')
        drawdown_days = result.get("longest_drawdown_days") or 0
        self.labels["drawdown_duration"].setText(
            display_dates(f"{int(drawdown_days)} Tage" if drawdown_days > 0 else '–'))
        self.labels["drawdown_duration"].setStyleSheet('font-size:18px;font-weight:700;color:%s' % COLORS["text"])
        benchmark = result.get("benchmark")
        comparison = (benchmark or {}).get("comparison")
        if benchmark and comparison:
            self.labels["benchmark"].setText(
                display_dates(f"{benchmark['symbol']}: {percent(comparison['benchmark_return'])}"))
            self.labels["active"].setText(display_dates(percent(comparison["active_return"])))
            self.labels["tracking"].setText(display_dates(percent(comparison["tracking_error_annualized"], True)))
            active = comparison["active_return"]
            self.labels["active"].setStyleSheet(
                f'font-size:18px;font-weight:700;color:'
                f'{COLORS["green"] if active is not None and active > 0 else COLORS["red"] if active is not None and active < 0 else COLORS["text"]}')
            self.labels["tracking"].setStyleSheet('font-size:18px;font-weight:700;color:%s' % COLORS["text"])
        else:
            for key in ('benchmark', 'active', 'tracking'):
                self.labels[key].setText('–')
                self.labels[key].setStyleSheet('font-size:18px;font-weight:700;color:%s' % COLORS["text"])
        for key in ('value_change', 'twr', 'annualized', 'xirr', 'profit', 'contributions'):
            value = result.get({'value_change':'value_change','twr':'twr','annualized':'twr_annualized',
                'xirr':'xirr','profit':'profit','contributions':'net_contributions'}[key])
            color = (COLORS['text'] if key == 'contributions' else
                     COLORS['green'] if value is not None and value > 0 else
                     COLORS['red'] if value is not None and value < 0 else COLORS['text'])
            self.labels[key].setStyleSheet(f'font-size:18px;font-weight:700;color:{color}')
        self.labels['twr'].setText(display_dates('≈ ' + self.labels['twr'].text()))
        self.labels['annualized'].setText(display_dates('≈ ' + self.labels['annualized'].text()))
        if not result['coverage_confirmed'] or not result.get('valuation_confirmed'):
            for key in ('xirr', 'profit', 'contributions'):
                self.labels[key].setText(display_dates('≈ ' + self.labels[key].text()))
                self.labels[key].setToolTip('Schätzung: Buchungsabdeckung oder Grenzbewertungen unvollständig.')
        detail = (f"Effektiver Bewertungszeitraum {result['start']} bis {result['end']} · "
                  f"Buchungsstatus: {result['quality']} · {len(result['transactions'])} auswertbare Wertpapierbuchungen / {result['transaction_count']} Buchungen insgesamt · "
                  f"{'Dividenden netto' if result.get('dividends_net_complete', True) else 'Dividendenzuflüsse vor separaten Steuern'} {euro(result['dividends'])} · "
                  f"brutto {euro(result['gross_dividends']) if result.get('gross_dividends') is not None else 'nicht vollständig in EUR belegt'}")
        if result["xirr_error"]:
            detail += f" · XIRR nicht berechenbar: {result['xirr_error']}"
        if result["quality"] == "geschätzt":
            detail += " · Transaktionsabdeckung für diesen Zeitraum ist nicht bestätigt."
        detail += " · Grenzbewertungen: " + ("tagesgenau und vollständig" if result.get("valuation_confirmed") else "nicht vollständig tagesgenau belegt")
        if result.get("benchmark") and result["benchmark"].get("comparison"):
            comparison = result["benchmark"]["comparison"]
            detail += (f" · Benchmark {result['benchmark']['symbol']}: {percent(comparison['benchmark_return'])} "
                       f"im gemeinsamen Zeitraum {comparison['common_start']} bis {comparison['common_end']}, "
                       f"aktiv {percent(comparison['active_return'])}, Tracking Error {percent(comparison['tracking_error_annualized'])} p.a.")
        self.show_quality(result.get('issues', []))
        self.note.setText(display_dates(detail + " · Modified Dietz misst die zeitgewichtete Entwicklung näherungsweise. XIRR ist die geldgewichtete annualisierte Rendite. Der Tagesindex verteilt die Teilperiodenrenditen geometrisch auf alle Kalendertage."))
        self.draw_chart()

    def show_quality(self, issues):
        if not issues:
            self.quality.setStyleSheet('padding:8px;border-left:4px solid #16a34a;background:rgba(22,163,74,0.10);')
            self.quality.setText('<b>✓ Berechnung vollständig prüfbar</b><br>Bewertungen und Buchungsabdeckung sind für den Zeitraum bestätigt.')
            return
        severe = any(item.get('level') == 'error' for item in issues)
        color = '#dc2626' if severe else '#d97706'
        heading = 'Berechnung nicht möglich' if severe else 'Berechnung mit Hinweisen'
        rows = ''.join(f"<li><b>{item['title']}</b><br>{item['action']}</li>" for item in issues)
        self.quality.setStyleSheet(f'padding:8px;border-left:4px solid {color};background:rgba(217,119,6,0.10);')
        self.quality.setText(f'<b>{heading}</b><ul>{rows}</ul>')

    def draw_chart(self):
        self.fig.clear()
        result = self.current_result or {}
        show_twr = self.chart_checks["twr"].isChecked()
        if show_twr:
            grid = self.fig.add_gridspec(2, 1, height_ratios=[2.2, 1], hspace=.08)
            axis = self.fig.add_subplot(grid[0])
            twr_axis = self.fig.add_subplot(grid[1], sharex=axis)
            axis.tick_params(labelbottom=False)
        else:
            axis, twr_axis = self.fig.add_subplot(111), None
        if result.get("error") or not result.get("valuation_series"):
            axis.text(.5, .5, result.get("error", "Keine Daten"), ha="center", va="center",
                      transform=axis.transAxes)
            style_axis(axis)
            self.canvas.draw_idle()
            return
        valuations = result["valuation_series"]
        dates = [date.fromisoformat(point["date"]) for point in valuations]
        values = [float(point["value"]) for point in valuations]
        capital = [float(point["value"]) for point in result["capital_series"]]
        if self.chart_checks["value"].isChecked():
            axis.plot(dates, values, label="Depotwert", color=COLORS["blue"], linewidth=2.2)
            axis.fill_between(dates, values, alpha=.08, color=COLORS["blue"])
            axis.annotate(euro(values[-1]), (dates[-1], values[-1]), xytext=(-5, 8),
                          textcoords="offset points", ha="right", fontsize=8,
                          color=COLORS["blue"], fontweight="bold")
        if self.chart_checks["capital"].isChecked():
            axis.plot(dates, capital, label="Investiertes Kapital", color=COLORS["slate"],
                      linestyle="--", linewidth=1.5)
        if self.chart_checks["profit"].isChecked():
            axis.plot(dates, [v - c for v, c in zip(values, capital)], label="Gewinn/Verlust",
                      color=COLORS["green"], linewidth=1.6)
        if twr_axis:
            if self.chart_checks["daily"].isChecked() and result.get("daily_index"):
                daily_dates = [date.fromisoformat(point["date"]) for point in result["daily_index"]]
                daily_values = [float(point["index"]) for point in result["daily_index"]]
                twr_axis.plot(daily_dates, daily_values, label="Tagesindex (Bewertung)",
                              color=COLORS["amber"], linewidth=1.0, alpha=.55)
            benchmark = result.get("benchmark")
            if benchmark and benchmark.get("index"):
                benchmark_dates = [date.fromisoformat(point["date"]) for point in benchmark["index"]]
                benchmark_values = [float(point["index"]) for point in benchmark["index"]]
                twr_axis.plot(benchmark_dates, benchmark_values, label="Benchmark",
                              color=COLORS["cyan"], linewidth=1.2, linestyle="--")
            twr_values = [float(point["index"]) for point in result["twr_series"]]
            twr_axis.plot(dates, twr_values, label="Dietz-Index (Näherung)", color=COLORS["purple"], linewidth=1.8)
            twr_axis.axhline(100, color=COLORS["slate"], linewidth=.8, alpha=.6)
            twr_axis.fill_between(dates, 100, twr_values, where=[v >= 100 for v in twr_values],
                                  color=COLORS["green"], alpha=.08)
            twr_axis.fill_between(dates, 100, twr_values, where=[v < 100 for v in twr_values],
                                  color=COLORS["red"], alpha=.08)
            twr_axis.set_ylabel("Dietz · Start 100", fontsize=8)
            style_axis(twr_axis); date_axis(twr_axis)
        if self.chart_checks["transactions"].isChecked():
            for transaction in result["transactions"]:
                tx_date = date.fromisoformat(transaction["date"])
                position = bisect_left(dates, tx_date)
                if position >= len(dates):
                    nearest = len(dates) - 1
                elif position > 0 and abs((dates[position] - tx_date).days) >= abs((dates[position - 1] - tx_date).days):
                    nearest = position - 1
                else:
                    nearest = position
                is_buy = Decimal(transaction["amount"]) < 0
                axis.scatter(tx_date, values[nearest], marker="^" if is_buy else "v", s=35,
                             color=COLORS["green"] if is_buy else COLORS["amber"],
                             edgecolor="white", linewidth=.6, zorder=5)
        style_axis(axis); currency_axis(axis)
        if not twr_axis: date_axis(axis)
        axis.margins(x=.015)
        axis.set_ylabel("Portfoliowert", fontsize=8)
        handles, labels = axis.get_legend_handles_labels()
        if twr_axis:
            h2, l2 = twr_axis.get_legend_handles_labels(); handles += h2; labels += l2
        if handles:
            axis.legend(handles, labels, loc="upper left", ncol=min(4, len(labels)), fontsize=8,
                        frameon=False)
        axis.set_title(f"Performance · {result['start']} bis {result['end']}", loc="left",
                       fontsize=11, fontweight="bold", color=COLORS["text"])
        self.fig.subplots_adjust(left=.09, right=.97, top=.90, bottom=.12)
        self.canvas.draw_idle()
