"""
workforce_intelligence/charts.py
────────────────────────────────
Enterprise-grade, React/Recharts-inspired dark visualization engine
for the Workforce Intelligence Dashboard.

Powered by Matplotlib natively embedded inside CustomTkinter via FigureCanvasTkAgg:
- Curated dark palette matching ui_components tokens (#0B1020, #111827, #1E293B)
- Anti-aliased vector rendering with sub-pixel precision
- Smooth monotone cubic spline interpolation (scipy PchipInterpolator)
- Multi-stop gradient area fills fading toward the baseline
- Interactive crosshairs and rich hover tooltips
- High-contrast diverging horizontal bar charts with embedded delta tags
- Zero webview, zero browser processes, pure desktop performance
"""

from datetime import datetime
import math
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import customtkinter as ctk
import matplotlib
matplotlib.use("Agg")  # Safe headless default; TkAgg is activated when canvas embeds
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

try:
    from scipy.interpolate import PchipInterpolator
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

import ui_components as ui


# ─────────────────────────────────────────────────────────────────────────────
# 1. Design Tokens & Color Palettes
# ─────────────────────────────────────────────────────────────────────────────

CHART_THEME = {
    "bg_card": "#111827",          # Card background matching ui.COLOR_CARD
    "bg_subtle": "#0F172A",        # Darker container bg
    "border": "#1E293B",           # Subtle border line
    "border_subtle": "#182234",    # Extremely soft gridline
    "text_primary": "#F8FAFC",     # Bright white for titles & values
    "text_secondary": "#94A3B8",   # Slate-400 for subtitles & axis labels
    "text_dim": "#64748B",         # Slate-500 for secondary tick marks
    "actual": "#06B6D4",           # Vibrant Cyan (main series)
    "actual_glow": "#22D3EE",      # Lighter Cyan highlight
    "benchmark": "#F59E0B",        # Amber-500 (Organisation benchmark)
    "historical": "#8B5CF6",       # Violet-500 (Historical baseline)
    "corridor": "#162032",         # Normal variation range fill
    "corridor_edge": "#25334D",    # Range corridor boundary
    "policy_marker": "#06B6D4",    # Policy effective line
    "success": "#10B981",          # Emerald-500 (improvement)
    "success_bg": "#064E3B",       # Emerald dark badge
    "danger": "#F43F5E",           # Rose-500 (deterioration / regression)
    "danger_bg": "#4C0519",        # Rose dark badge
    "font_family": "Segoe UI",     # Enterprise Segoe UI / Inter fallbacks
}


def apply_dark_theme(fig: Figure, ax=None):
    """Apply unified enterprise dark styling to Matplotlib Figure and Axes."""
    fig.patch.set_facecolor(CHART_THEME["bg_card"])
    fig.patch.set_edgecolor("none")

    if ax is not None:
        ax.set_facecolor(CHART_THEME["bg_card"])
        # Remove top, right, and left spines for a clean floating aesthetic
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_color(CHART_THEME["border"])
        ax.spines["bottom"].set_linewidth(1.0)

        # Subtle horizontal grid only
        ax.yaxis.grid(True, linestyle="--", linewidth=0.7, color=CHART_THEME["border_subtle"], alpha=0.9, zorder=0)
        ax.xaxis.grid(False)

        # Tick styling
        ax.tick_params(axis="x", colors=CHART_THEME["text_secondary"], labelsize=8.5, length=3, width=0.8)
        ax.tick_params(axis="y", colors=CHART_THEME["text_dim"], labelsize=8, length=0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. CTk Embedded Chart Canvas Container
# ─────────────────────────────────────────────────────────────────────────────

class ChartCanvas(ctk.CTkFrame):
    """
    Managed CustomTkinter wrapper around a native Matplotlib FigureCanvasTkAgg.
    Provides responsive resize debouncing, high-DPI awareness, and clean lifecycle management.
    """

    def __init__(self, parent, figsize=(8, 3), dpi=100, **kwargs):
        kwargs.setdefault("fg_color", CHART_THEME["bg_card"])
        kwargs.setdefault("corner_radius", 8)
        super().__init__(parent, **kwargs)

        self.fig = Figure(figsize=figsize, dpi=dpi, facecolor=CHART_THEME["bg_card"])
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.tk_widget = self.canvas.get_tk_widget()
        self.tk_widget.configure(bg=CHART_THEME["bg_card"], highlightthickness=0, bd=0)
        self.tk_widget.pack(fill="both", expand=True)

        self._resize_timer = None
        self.tk_widget.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        """Debounced idle redraw on container resize."""
        if self._resize_timer is not None:
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(40, self._do_resize_redraw)

    def _do_resize_redraw(self):
        self._resize_timer = None
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def draw(self):
        """Request a smooth, non-blocking redraw on the main UI loop."""
        try:
            self.canvas.draw_idle()
        except Exception:
            try:
                self.canvas.draw()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# 3. Time-Series Trend Chart Renderer (Spline, Gradient, Markers, Tooltip)
# ─────────────────────────────────────────────────────────────────────────────

def render_trend_time_series(
    fig: Figure,
    ax,
    chart_data: Dict[str, Any],
    benchmark_label: str = "Organisation",
) -> List[Dict[str, Any]]:
    """
    Renders an interactive, React-styled multi-line trend chart on the provided axes:
    - Smooth anti-aliased monotone cubic spline for the Actual trend line.
    - Multi-stop gradient fill fading from cyan into dark card background.
    - Dashed Amber benchmark line with node caps.
    - Dotted Violet historical baseline.
    - Translucent shaded Reference Range corridor.
    - Annotated Policy Effective Date vertical marker.
    - Regression (red double-ring) & Low-Volume (amber ring) visual flags.
    
    Returns node hit-test records for mouse hover inspections:
    [{ "x_px": ..., "y_px": ..., "data": {...} }]
    """
    ax.clear()
    apply_dark_theme(fig, ax)

    pts = chart_data.get("points", []) if chart_data else []
    if not pts:
        ax.text(
            0.5, 0.5, "No trend observation data available for active scope",
            transform=ax.transAxes, ha="center", va="center",
            color=CHART_THEME["text_dim"], fontsize=10, fontfamily=CHART_THEME["font_family"]
        )
        return []

    # 1. Parse numeric values
    n_pts = len(pts)
    x_indices = np.arange(n_pts)
    x_labels = [p.get("period_display", p.get("period", f"M{i+1}")) for i, p in enumerate(pts)]

    actual_vals = [p.get("actual") for p in pts]
    bench_vals = [p.get("benchmark") for p in pts]
    hist_vals = [p.get("historical") for p in pts]

    # Convert None/NaN to floats
    act_arr = np.array([float(v) if v is not None and not pd.isna(v) else np.nan for v in actual_vals])
    bn_arr = np.array([float(v) if v is not None and not pd.isna(v) else np.nan for v in bench_vals])
    hs_arr = np.array([float(v) if v is not None and not pd.isna(v) else np.nan for v in hist_vals])

    # Reference range
    ref_range = chart_data.get("reference_range")
    ref_low = float(ref_range[0]) if ref_range and ref_range[0] is not None else None
    ref_high = float(ref_range[1]) if ref_range and ref_range[1] is not None else None

    # Calculate Y-axis bounds
    all_num = []
    for arr in (act_arr, bn_arr, hs_arr):
        valid = arr[~np.isnan(arr)]
        if len(valid) > 0:
            all_num.extend(valid.tolist())
    if ref_low is not None:
        all_num.append(ref_low)
    if ref_high is not None:
        all_num.append(ref_high)

    if not all_num:
        all_num = [0.0, 10.0]

    min_v = min(all_num)
    max_v = max(all_num)
    y_min = max(0.0, min_v * 0.85 if min_v > 0 else min_v * 1.15)
    y_max = max_v * 1.18 if max_v > 0 else 1.0
    if y_max <= y_min:
        y_max = y_min + 1.0

    # 2. Draw Reference Band (Corridor)
    if ref_low is not None and ref_high is not None:
        ax.axhspan(ref_low, ref_high, color=CHART_THEME["corridor"], alpha=0.55, zorder=1)
        ax.axhline(ref_high, color=CHART_THEME["corridor_edge"], linestyle="--", linewidth=0.8, alpha=0.7, zorder=1)
        ax.axhline(ref_low, color=CHART_THEME["corridor_edge"], linestyle="--", linewidth=0.8, alpha=0.7, zorder=1)

    # 3. Draw Policy Effective Date Marker (e.g. 1 Oct 2026)
    pol_str = str(chart_data.get("policy_effective_date") or "2026-10-01")
    for i, p in enumerate(pts):
        p_str = str(p.get("period", ""))
        if p_str == pol_str or (i > 0 and pts[i - 1].get("period", "") < pol_str <= p_str):
            ax.axvline(i, color=CHART_THEME["policy_marker"], linestyle="--", linewidth=1.2, alpha=0.85, zorder=2)
            ax.text(
                i + 0.08, y_max * 0.94, "⚡ Policy Effective",
                color=CHART_THEME["policy_marker"], fontsize=7.5, fontweight="bold",
                fontfamily=CHART_THEME["font_family"], va="top", zorder=3
            )
            break

    # 4. Draw Historical Baseline (dotted purple)
    hs_valid_mask = ~np.isnan(hs_arr)
    if np.any(hs_valid_mask):
        ax.plot(
            x_indices[hs_valid_mask], hs_arr[hs_valid_mask],
            color=CHART_THEME["historical"], linestyle=":", linewidth=1.8,
            alpha=0.9, label="Historical Baseline", zorder=2
        )

    # 5. Draw Benchmark (dashed amber)
    bn_valid_mask = ~np.isnan(bn_arr)
    if np.any(bn_valid_mask):
        ax.plot(
            x_indices[bn_valid_mask], bn_arr[bn_valid_mask],
            color=CHART_THEME["benchmark"], linestyle="--", linewidth=2.0,
            alpha=0.95, label=f"{benchmark_label} Benchmark", zorder=3
        )

    # 6. Draw Actual Trend Line with Monotone Smooth Spline & Gradient Area
    act_valid_mask = ~np.isnan(act_arr)
    valid_x = x_indices[act_valid_mask]
    valid_y = act_arr[act_valid_mask]

    if len(valid_x) >= 2:
        if HAS_SCIPY and len(valid_x) >= 3:
            # Smooth monotone cubic interpolation (prevents false overshooting/undershooting)
            interp = PchipInterpolator(valid_x, valid_y)
            smooth_x = np.linspace(valid_x.min(), valid_x.max(), max(100, len(valid_x) * 25))
            smooth_y = interp(smooth_x)
            smooth_y = np.clip(smooth_y, y_min, y_max * 1.05)
        else:
            smooth_x = valid_x
            smooth_y = valid_y

        # Multi-layer gradient area fill beneath the curve
        alphas = [0.22, 0.14, 0.08, 0.03]
        num_layers = len(alphas)
        for l_idx, alpha_v in enumerate(alphas):
            # Progressive slice height
            frac = (l_idx + 1) / num_layers
            lower_bound = y_min + (smooth_y - y_min) * (1.0 - frac)
            ax.fill_between(
                smooth_x, lower_bound, smooth_y,
                color=CHART_THEME["actual"], alpha=alpha_v, edgecolor="none", zorder=2
            )

        # Glow edge + crisp actual line
        ax.plot(smooth_x, smooth_y, color=CHART_THEME["actual_glow"], linewidth=3.0, alpha=0.3, zorder=4)
        ax.plot(smooth_x, smooth_y, color=CHART_THEME["actual"], linewidth=2.0, alpha=1.0, zorder=5)

    elif len(valid_x) == 1:
        # Single point fallback
        ax.scatter(valid_x, valid_y, color=CHART_THEME["actual"], s=60, zorder=5)

    # 7. Nodes & Outlier Badges (Regression, Low Volume)
    node_records = []
    for i, p in enumerate(pts):
        y_val = act_arr[i]
        if np.isnan(y_val):
            continue

        is_reg = p.get("is_regression", False)
        is_low = p.get("is_low_volume", False)

        if is_reg:
            # Highlight regression with double-ring rose marker
            ax.scatter([i], [y_val], color=CHART_THEME["danger"], s=130, alpha=0.3, zorder=6)
            ax.scatter([i], [y_val], color=CHART_THEME["danger"], s=60, edgecolors="#FFFFFF", linewidth=1.5, zorder=7)
        elif is_low:
            # Amber hollow ring for low volume
            ax.scatter([i], [y_val], facecolors=CHART_THEME["bg_card"], edgecolors=CHART_THEME["benchmark"], s=55, linewidth=2.0, zorder=6)
        else:
            # Standard solid cyan node with crisp white outline
            ax.scatter([i], [y_val], color=CHART_THEME["actual"], s=42, edgecolors="#FFFFFF", linewidth=1.2, zorder=6)

        node_records.append({
            "index": i,
            "x_val": i,
            "y_val": y_val,
            "point": p,
        })

    # X-Axis configuration
    ax.set_xlim(-0.35, n_pts - 1 + 0.35)
    ax.set_xticks(x_indices)
    ax.set_xticklabels(x_labels, fontweight="normal")
    ax.set_ylim(y_min, y_max)

    # Y-Axis formatting based on metric format
    fmt_type = chart_data.get("format", "percentage")
    if fmt_type == "percentage":
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(xmax=100.0, decimals=0))
    elif fmt_type == "days":
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, pos: f"{v:.1f}d"))
    elif fmt_type in ("duration", "time"):
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, pos: f"{int(v)}m"))
    else:
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, pos: f"{v:.1f}"))

    # Tight clean margins with room for labels
    fig.subplots_adjust(left=0.08, right=0.96, top=0.92, bottom=0.18)

    return node_records


# ─────────────────────────────────────────────────────────────────────────────
# 4. What Changed? Driver Decomposition Chart (Diverging Horizontal Bars)
# ─────────────────────────────────────────────────────────────────────────────

def render_what_changed_bars(
    fig: Figure,
    ax,
    what_changed_data: Dict[str, Any],
):
    """
    Renders a modern diverging horizontal bar chart centered on zero:
    - Positive delta (deterioration in lower-is-better metrics) extends Right (Rose-500).
    - Negative delta (improvement / reduction) extends Left (Emerald-500).
    - Embedded value tags at the end of each bar.
    - BU and Exception Category badge tags.
    """
    ax.clear()
    apply_dark_theme(fig, ax)

    drivers = what_changed_data.get("drivers", []) if what_changed_data else []
    if not drivers:
        ax.text(
            0.5, 0.5, "Baseline period established • Stable trajectory",
            transform=ax.transAxes, ha="center", va="center",
            color=CHART_THEME["success"], fontsize=9.5, fontweight="bold",
            fontfamily=CHART_THEME["font_family"]
        )
        return

    # Take top 5 drivers in reverse order so top driver is at the top of the Y-axis
    top_drivers = list(reversed(drivers[:5]))
    names = [d.get("driver", "Driver") for d in top_drivers]
    deltas = [float(d.get("delta", 0.0)) for d in top_drivers]
    f_deltas = [d.get("formatted_delta", f"{d.get('delta', 0.0):+.1f}") for d in top_drivers]
    types = [d.get("type", "BU") for d in top_drivers]

    y_pos = np.arange(len(names))
    colors = [CHART_THEME["danger"] if val > 0 else CHART_THEME["success"] for val in deltas]

    # Bar thickness and subtle rounded aesthetic
    bar_height = 0.52
    bars = ax.barh(y_pos, deltas, height=bar_height, color=colors, alpha=0.88, zorder=3)

    # Vertical reference line at x = 0
    ax.axvline(0, color=CHART_THEME["border"], linewidth=1.5, zorder=2)

    # Calculate symmetric X range so zero is nicely balanced
    max_abs = max(0.5, max(abs(v) for v in deltas) * 1.35)
    ax.set_xlim(-max_abs, max_abs)
    ax.set_ylim(-0.6, len(names) - 0.4)

    # Value tags beside the bars
    for idx, (b, val, tag) in enumerate(zip(bars, deltas, f_deltas)):
        if val >= 0:
            x_txt = val + (max_abs * 0.03)
            ha_align = "left"
            txt_color = CHART_THEME["danger"]
        else:
            x_txt = val - (max_abs * 0.03)
            ha_align = "right"
            txt_color = CHART_THEME["success"]

        ax.text(
            x_txt, idx, tag,
            va="center", ha=ha_align,
            color=txt_color, fontsize=8.5, fontweight="bold",
            fontfamily=CHART_THEME["font_family"], zorder=4
        )

    # Clean Y-axis labels with [BU] or [CAT] prefix
    formatted_labels = []
    for n, t in zip(names, types):
        prefix = "🏢 " if t == "BU" else "⚡ "
        formatted_labels.append(f"{prefix}{n}")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(
        formatted_labels,
        color=CHART_THEME["text_primary"],
        fontsize=8.5,
        fontweight="bold",
        fontfamily=CHART_THEME["font_family"]
    )

    # Subdued X-axis percent formatting
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, pos: f"{v:+.1f}"))
    ax.tick_params(axis="x", colors=CHART_THEME["text_dim"], labelsize=7.5)

    # Margins
    fig.subplots_adjust(left=0.32, right=0.92, top=0.92, bottom=0.18)
