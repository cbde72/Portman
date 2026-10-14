"""Gemeinsames, dock-taugliches Erscheinungsbild für PortMan-Diagramme."""

from __future__ import annotations

from typing import Any

from matplotlib.ticker import FuncFormatter
import matplotlib.dates as mdates

# Professionelle Farbpaletten
COLORS = {
    "blue": "#2563EB",
    "blue_light": "#93C5FD",
    "green": "#16A34A",
    "red": "#DC2626",
    "amber": "#D97706",
    "purple": "#7C3AED",
    "cyan": "#0891B2",
    "pink": "#DB2777",
    "slate": "#64748B",
    "grid": "#CBD5E1",
    "text": "#334155",
    "text_light": "#475569",
    "background": "#F1F5F9",
    "panel": "#FFFFFF",
    "muted": "#64748B",
    "border": "#E2E8F0",
    "grid_dark": "#334155",
    "text_dark": "#E2E8F0",
    "text_light_dark": "#94A3B8",
    "background_dark": "#0F172A",
    "panel_dark": "#1E293B",
    "muted_dark": "#64748B",
    "border_dark": "#475569",
}

# Standard-Palette
PALETTE = [
    "#2563EB",  # blue
    "#16A34A",  # green
    "#D97706",  # amber
    "#7C3AED",  # purple
    "#0891B2",  # cyan
    "#DB2777",  # pink
    "#64748B",  # slate
    "#EA580C",  # orange
    "#06B6D4",  # teal
    "#EC4899",  # rose
]

# Tableau 10 Palette (professioneller)
TABLEAU_PALETTE = [
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
]

# Viridis-ähnliche Palette
VIRIDIS_PALETTE = [
    "#440154",
    "#481567",
    "#482677",
    "#453781",
    "#3F4788",
    "#375792",
    "#2D6F8E",
    "#21888D",
    "#1FA187",
    "#23A983",
    "#36B677",
    "#54C369",
    "#80CF51",
    "#B5DE2B",
    "#FDE725",
]

# Corporate Palette
CORPORATE_PALETTE = [
    "#1A73E8",
    "#34A853",
    "#FB8C00",
    "#EA4335",
    "#9C27B0",
    "#00ACC1",
    "#795548",
    "#607D8B",
]

PALETTES = {
    "default": PALETTE,
    "tableau": TABLEAU_PALETTE,
    "viridis": VIRIDIS_PALETTE,
    "corporate": CORPORATE_PALETTE,
}

# Configurable chart appearance (settings key ``chart_v10``). Renderers and
# figure creation read these values; ``apply_chart_style`` merges persisted
# overrides and ``chart_style_signature`` invalidates cached renders.
CHART_STYLE = {
    "figure_width": 10.0,
    "figure_height": 4.1,
    "dpi": 100,
    "export_dpi": 180,
    "export_formats": ["png", "svg", "pdf", "jpg"],
    "base_fontsize": 8,
    "title_fontsize": 11,
    "subtitle_fontsize": 9,
    "axis_label_fontsize": 9,
    "legend_fontsize": 8,
    "tick_fontsize": 7,
    "annotation_fontsize": 7,
    "grid_alpha": 0.55,
    "line_width": 2.0,
    "marker_size": 4.0,
    "bar_width": 0.6,
    "stack_alpha": 0.75,
    "top_n": 10,
    "max_months": 12,
    "date_format": "%d.%m.%Y",
    "locale": "de_DE",
    "theme": "light",
    "palette": "default",
    "show_grid": True,
    "grid_axis": "both",
    "spine_color": "grid",
    "use_ridge": False,
    "show_legend": True,
    "legend_loc": "best",
    "tight_layout": True,
    "constrained_layout": True,
}


def get_current_colors(theme: str | None = None) -> dict[str, str]:
    """Return color set for current or specified theme."""
    theme = theme or CHART_STYLE.get("theme", "light")
    if theme == "dark":
        return {
            "blue": "#3B82F6",
            "blue_light": "#60A5FA",
            "green": "#22C55E",
            "red": "#EF4444",
            "amber": "#F59E0B",
            "purple": "#A855F7",
            "cyan": "#06B6D4",
            "pink": "#EC4899",
            "slate": "#94A3B8",
            "grid": "#475569",
            "text": "#E2E8F0",
            "text_light": "#CBD5E1",
            "background": "#0F172A",
            "panel": "#1E293B",
            "muted": "#64748B",
            "border": "#475569",
        }
    return {
        "blue": "#2563EB",
        "blue_light": "#93C5FD",
        "green": "#16A34A",
        "red": "#DC2626",
        "amber": "#D97706",
        "purple": "#7C3AED",
        "cyan": "#0891B2",
        "pink": "#DB2777",
        "slate": "#64748B",
        "grid": "#CBD5E1",
        "text": "#334155",
        "text_light": "#475569",
        "background": "#F1F5F9",
        "panel": "#FFFFFF",
        "muted": "#64748B",
        "border": "#E2E8F0",
    }


def apply_chart_style(config: dict[str, Any] | None = None) -> None:
    if config:
        CHART_STYLE.update(config)


def chart_style_signature() -> tuple:
    return tuple((key, CHART_STYLE[key]) for key in sorted(CHART_STYLE))


def get_palette(name: str | None = None) -> list[str]:
    name = name or CHART_STYLE.get("palette", "default")
    return list(PALETTES.get(name, PALETTE))


def create_figure(
    width: float | None = None,
    height: float | None = None,
    dpi: int | None = None,
    **kwargs: Any,
):
    from matplotlib.figure import Figure

    fig = Figure(
        figsize=(
            width or CHART_STYLE["figure_width"],
            height or CHART_STYLE["figure_height"],
        ),
        dpi=dpi or CHART_STYLE["dpi"],
        tight_layout=CHART_STYLE.get("tight_layout", True),
        **kwargs,
    )
    style_figure(fig)
    return fig


def create_figure_constrained(
    width: float | None = None,
    height: float | None = None,
    dpi: int | None = None,
    **kwargs: Any,
):
    from matplotlib.figure import Figure

    fig = Figure(
        figsize=(
            width or CHART_STYLE["figure_width"],
            height or CHART_STYLE["figure_height"],
        ),
        dpi=dpi or CHART_STYLE["dpi"],
        constrained_layout=True,
        **kwargs,
    )
    style_figure(fig)
    return fig


def save_figure(figure, path, dpi: int | None = None):
    """Speichert eine Figur; das Format ergibt sich aus der Dateiendung.

    Unterstützt werden die in ``CHART_STYLE['export_formats']`` konfigurierten
    Formate (Standard: png, svg, pdf, jpg). Rasterformate werden mit dem
    Export-DPI gespeichert, Vektorformate verlustfrei.
    """
    from pathlib import Path

    target = Path(path)
    suffix = target.suffix.lstrip('.').lower()
    supported = set(CHART_STYLE.get('export_formats', ['png']))
    if suffix not in supported:
        raise ValueError(
            f'Nicht unterstütztes Exportformat: {suffix!r} '
            f'(erlaubt: {", ".join(sorted(supported))})'
        )
    kwargs: dict[str, Any] = {'bbox_inches': 'tight', 'facecolor': figure.get_facecolor()}
    if suffix in ('png', 'jpg', 'jpeg'):
        kwargs['dpi'] = dpi or CHART_STYLE['export_dpi']
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, **kwargs)


def compact_number(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f} Mio. €".replace(".", ",")
    if absolute >= 1_000:
        return f"{value / 1_000:.0f} Tsd. €"
    if absolute < 1 and value != 0:
        return f"{value:.2f} €".replace(".", ",")
    return f"{value:.0f} €"


def currency_axis(axis):
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: compact_number(value)))


def percent_axis(axis, decimals: int = 0):
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.{decimals}f} %".replace(".", ",")))


def percent_x_axis(axis, decimals: int = 0):
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.{decimals}f} %".replace(".", ",")))


def number_axis(axis, decimals: int = 0):
    axis.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _pos: f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", "."))
    )


def date_axis(axis, ticks: int = 7):
    locator = mdates.AutoDateLocator(minticks=3, maxticks=ticks)
    axis.xaxis.set_major_locator(locator)
    axis.xaxis.set_major_formatter(mdates.DateFormatter(CHART_STYLE["date_format"]))


def style_axis(axis, horizontal_grid: bool = True, grid_axis: str | None = None):
    colors = get_current_colors(CHART_STYLE.get("theme"))
    axis.set_facecolor(colors["panel"])
    axis.tick_params(
        colors=colors["text"],
        labelsize=CHART_STYLE["tick_fontsize"],
        labelcolor=colors["text"],
    )
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    axis.spines["left"].set_color(colors["grid"])
    axis.spines["bottom"].set_color(colors["grid"])
    axis.spines["top"].set_color(colors["border"])
    axis.spines["right"].set_color(colors["border"])

    grid_ax = grid_axis or CHART_STYLE.get("grid_axis", "y" if horizontal_grid else "both")
    if grid_ax in ("y", "both"):
        axis.grid(
            axis="y",
            color=colors["grid"],
            alpha=CHART_STYLE["grid_alpha"],
            linewidth=0.7,
            linestyle="-",
        )
    if grid_ax in ("x", "both"):
        axis.grid(
            axis="x",
            color=colors["grid"],
            alpha=CHART_STYLE["grid_alpha"],
            linewidth=0.7,
            linestyle="-",
        )
    axis.set_axisbelow(True)


def style_figure(figure):
    colors = get_current_colors(CHART_STYLE.get("theme"))
    figure.set_facecolor(colors["background"])
    for ax in figure.axes:
        try:
            ax.set_facecolor(colors["panel"])
        except Exception:
            pass


def apply_professional_style(figure, ax, title: str | None = None, subtitle: str | None = None):
    colors = get_current_colors(CHART_STYLE.get("theme"))
    style_axis(ax)
    ax.set_title(
        title or "",
        loc="left",
        color=colors["text"],
        fontsize=CHART_STYLE["title_fontsize"],
        fontweight="bold",
        pad=16,
    )
    if subtitle:
        ax.text(
            0.01,
            0.98,
            subtitle,
            transform=ax.transAxes,
            ha="left",
            va="top",
            color=colors["text_light"],
            fontsize=CHART_STYLE["subtitle_fontsize"],
            alpha=0.8,
        )
    return ax
