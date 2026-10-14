from PySide6.QtCore import QTimer
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from .holding import Holding
from .chart_style import COLORS, PALETTE, compact_number, percent_x_axis, style_axis, style_figure, create_figure


class PortfolioChartCanvas(FigureCanvas):
    def __init__(self, parent=None):
        fig = create_figure(6, 5, 100)
        style_figure(fig)
        self.axes = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)
        self.setMinimumHeight(340)

    def showEvent(self, event):
        """Toleriert den kurzen QWindow-Wechsel beim Andocken unter Qt 6."""
        try:
            super().showEvent(event)
        except RuntimeError as exc:
            if "QWindow" not in str(exc) or "already deleted" not in str(exc):
                raise
            # Qt erzeugt beim Wechsel floating -> docked sofort ein neues
            # natives Fenster. Der nächste Event-Loop-Durchlauf besitzt den
            # gültigen Handle; ein redraw genügt, ohne den Canvas zu ersetzen.
            QTimer.singleShot(0, self.draw_idle)

    def plot_pie_allocation(self, holdings: list[Holding], group_by: str = "asset_type", title_suffix: str = "Alle"):
        self.axes.clear()
        if not holdings:
            self.draw()
            return

        if group_by == "asset_type" and title_suffix != "Alle":
            group_by = "region"

        grouped = {}
        for holding in holdings:
            name = getattr(holding, group_by)
            grouped[name] = grouped.get(name, 0) + holding.market_value
        groups = sorted(((name, value) for name, value in grouped.items() if value > 0),
                        key=lambda item: (-item[1], item[0]))
        if not groups:
            self.draw()
            return

        total = sum(value for _, value in groups)
        major = [(name, value) for name, value in groups if value / total >= .025]
        minor = sum(value for _, value in groups if value / total < .025)
        labels = [name for name, _ in major]
        values = [value for _, value in major]
        if minor:
            labels.append("Sonstige"); values.append(minor)
        wedges, _ = self.axes.pie(values, startangle=90, colors=PALETTE[:len(values)],
                                  wedgeprops={"width": .40, "edgecolor": "white", "linewidth": 2})
        self.axes.text(0, 0, compact_number(total), ha="center", va="center",
                       fontsize=11, fontweight="bold", color=COLORS["text"])
        self.axes.legend(wedges, [f"{name}  {value / total * 100:.1f} %" for name, value in zip(labels, values)],
                         loc="lower center", bbox_to_anchor=(.5, -.16), frameon=False,
                         fontsize=8, ncol=2)
        self.axes.set_title(f"Allokation · {title_suffix}", loc="left", fontsize=11,
                            fontweight="bold", color=COLORS["text"])
        self.figure.subplots_adjust(left=.08, right=.96, top=.90, bottom=.20)
        self.draw_idle()

    def plot_performance_heatmap(self, holdings: list[Holding]):
        self.axes.clear()
        self.axes.set_aspect('auto')
        if not holdings:
            self.draw()
            return

        ordered = sorted([h for h in holdings if h.buy_value > 0], key=lambda x: x.profit_loss_pct, reverse=True)
        selected = ordered if len(ordered) <= 10 else ordered[:5] + ordered[-5:]
        sorted_h = sorted({h.isin or h.name: h for h in selected}.values(),
                          key=lambda x: x.profit_loss_pct, reverse=True)
        names = [h.name[:24] + "…" if len(h.name) > 25 else h.name for h in sorted_h]
        pnl_pcts = [h.profit_loss_pct for h in sorted_h]
        colors = [COLORS['green'] if p >= 0 else COLORS['red'] for p in pnl_pcts]

        y_pos = range(len(names))
        bars = self.axes.barh(y_pos, pnl_pcts, color=colors, align='center', alpha=.88)
        self.axes.set_yticks(y_pos)
        self.axes.set_yticklabels(names)
        self.axes.invert_yaxis()
        self.axes.axvline(0, color=COLORS['text'], linewidth=.8)
        self.axes.bar_label(bars, labels=[f"{value:+.1f} %" for value in pnl_pcts],
                            padding=4, fontsize=8)
        self.axes.set_xlabel('Buchrendite')
        self.axes.set_title('Positionen nach Buchrendite', loc='left', fontsize=11,
                            fontweight='bold', color=COLORS['text'])
        percent_x_axis(self.axes);style_axis(self.axes)
        self.axes.margins(x=.16)
        self.figure.subplots_adjust(left=.30,right=.94,top=.90,bottom=.12)
        self.draw_idle()

    def plot_benchmarking(self, holdings: list[Holding]):
        self.axes.clear()
        self.axes.set_aspect('auto')
        holdings = [h for h in holdings if h.buy_value > 0]
        if not holdings:
            self.draw()
            return

        total_buy = sum(h.buy_value for h in holdings)
        total_mkt = sum(h.market_value for h in holdings)
        portfolio_return = ((total_mkt - total_buy) / total_buy * 100.0) if total_buy > 0 else 0.0

        bar = self.axes.barh(['Portfolio'], [portfolio_return],
                             color=COLORS['green'] if portfolio_return >= 0 else COLORS['red'], height=.42)
        self.axes.axvline(0,color=COLORS['text'],linewidth=.8)
        self.axes.bar_label(bar,labels=[f'{portfolio_return:+.1f} %'],padding=5,fontweight='bold')
        self.axes.text(.5,.12,'Nur bekannte Einstandswerte. Kursvergleiche unter Visualisierungen.',transform=self.axes.transAxes,
                       ha='center',color=COLORS['slate'],fontsize=9)
        self.axes.set_title('Buchrendite des aktuellen Bestands',loc='left',fontsize=11,
                            fontweight='bold',color=COLORS['text'])
        percent_x_axis(self.axes);style_axis(self.axes);self.axes.margins(x=.25,y=.8)
        self.figure.subplots_adjust(left=.18,right=.94,top=.88,bottom=.14)
        self.draw_idle()
