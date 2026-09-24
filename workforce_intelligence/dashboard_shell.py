"""
workforce_intelligence/dashboard_shell.py
──────────────────────────────────────────
Desktop navigation shell, screen containers, and live Executive Overview
for the Transformers 2.0 Workforce Intelligence Dashboard.

Implements Step 21 & Step 23 requirements:
1. Compact header displaying active dataset name, reporting period, dataset status,
   and data-quality information.
2. Clearly labelled placeholder for future global filter toolbar (Step 22).
3. Horizontal navigation bar with exactly six analytical views:
   - Overview (Live 9 KPI cards + Reconciliation status)
   - Attendance (Placeholder)
   - Leave (Placeholder)
   - WFH (Placeholder)
   - Working Hours (Placeholder)
   - Investigations (Placeholder)
4. Nine primary Executive Overview KPI cards rendered with ACTUAL computed values
   from the active AnalyticalSnapshot via WorkforceIntelligenceBridge:
   - 1. EMP HC (Observed Headcount)
   - 2. Attendance Days (Recorded Days)
   - 3. Present (Physical attendance quantity-weighted days)
   - 4. On Duty (Quantity-weighted days)
   - 5. Leave (Quantity-weighted days)
   - 6. WFH (Quantity-weighted days)
   - 7. Holiday (Quantity-weighted days)
   - 8. Week Off (Quantity-weighted days)
   - 9. Attendance Exceptions (Qualifying exception overlay)
5. Empty, loading, and error states with non-blocking worker threads and main-thread
   Tkinter updates protected by stale job fencing.
6. Pure CustomTkinter/Tkinter desktop implementation (zero Qt, zero web dependencies).
"""

from datetime import date, datetime, timedelta
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import customtkinter as ctk
import pandas as pd

from storage import AnalyticalSnapshot, snapshot_service
import time_series_analysis as tsa
import ui_components as ui
from workforce_intelligence.snapshot_bridge import workforce_bridge


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Day Quantity Formatting
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_days(val: Optional[Union[float, int]]) -> str:
    """Format day quantities with strict singular/plural grammar (e.g. 1 day, 2 days, 14.5 days)."""
    if val is None or pd.isna(val):
        return "N/A"
    try:
        f_val = float(val)
        if f_val % 1 == 0:
            i_val = int(f_val)
            unit = "day" if i_val == 1 else "days"
            return f"{i_val:,} {unit}"
        return f"{f_val:,.1f} days"
    except (ValueError, TypeError):
        return str(val)


# ─────────────────────────────────────────────────────────────────────────────
# View Configuration & Metadata
# ─────────────────────────────────────────────────────────────────────────────

VIEW_KEYS = [
    "overview",
    "attendance",
    "leave",
    "wfh",
    "working_hours",
    "investigations",
]

VIEW_CONFIGS: Dict[str, Dict[str, str]] = {
    "overview": {
        "title": "Executive Overview",
        "tab_title": "Overview",
        "icon": "⊞",
        "subtitle": "High-level workforce headcount, attendance composition, and governance indicators.",
        "badge": "Step 23 — Live KPI Overview",
        "placeholder_text": "Executive workforce and attendance metrics will appear here.",
        "future_scope": (
            "• Nine Executive Overview KPI Cards (Headcount, Attendance Days, Present, On Duty, Leave, WFH, Holiday, Week Off, Exceptions)\n"
            "• Single 100% Additive Quantity-Weighted Attendance Composition Bar\n"
            "• Business Unit Attendance Distribution Comparison Table"
        ),
    },
    "attendance": {
        "title": "Attendance Composition & Exceptions",
        "tab_title": "Attendance",
        "icon": "◧",
        "subtitle": "Physical attendance composition and exception analytics will appear here.",
        "badge": "Step 24 — Attendance Analytics",
        "placeholder_text": "Detailed attendance composition and exception analytics will appear here.",
        "future_scope": (
            "• Daily Physical Attendance & Missing Swipe Ratios\n"
            "• Attendance Exceptions Breakdown (Missing Swipes, Absent, Regularized)\n"
            "• Business Unit Attendance Regularity Patterns & Department Variations"
        ),
    },
    "leave": {
        "title": "Leave Intelligence & Turnaround",
        "tab_title": "Leave",
        "icon": "◫",
        "subtitle": "Leave application, approval, and request-level analytics will appear here.",
        "badge": "Step 25 — Leave Intelligence",
        "placeholder_text": "Leave application, approval, and request-level analytics will appear here.",
        "future_scope": (
            "• 8 Executive Leave KPIs (Total Leave Days, Leave Headcount, Lead Time, Turnaround)\n"
            "• Application Timing Breakdown (Prior >0d, Same-Day 0d, Retrospective <0d)\n"
            "• Applicant Ownership (Employee vs. Admin) & Manager Approval Turnaround\n"
            "• Request-Level Leave Audit Table with Signed Lead Times"
        ),
    },
    "wfh": {
        "title": "WFH Intelligence & Allowance Tracking",
        "tab_title": "WFH",
        "icon": "🏠",
        "subtitle": "Monthly WFH utilization, allowance, and request analytics will appear here.",
        "badge": "Step 26 — WFH Intelligence",
        "placeholder_text": "Monthly WFH utilization, allowance, and request analytics will appear here.",
        "future_scope": (
            "• Monthly WFH Utilization & Penetration Rates\n"
            "• 3-Day Calendar-Month WFH Allowance Tracking & Reset\n"
            "• Additional WFH Days (Excess Days) & Exceeding Headcount Analysis\n"
            "• Cross-BU Transfer Tracking & Partial-Month Observation Badges"
        ),
    },
    "working_hours": {
        "title": "Working Hours & Punch Intelligence",
        "tab_title": "Working Hours",
        "icon": "⏱",
        "subtitle": "Working-hour distributions and biometric punch analytics will appear here.",
        "badge": "Step 27 — Working Hours",
        "placeholder_text": "Working-hour distributions and biometric punch analytics will appear here.",
        "future_scope": (
            "• Biometric Punch Completeness (Complete Swipes, Missing In, Missing Out)\n"
            "• Duration Band Distribution strictly reconciling to complete swipes (<4h, 4–8h, 8–9h, >9h)\n"
            "• Descriptive Business Unit Punch Deviations in Minutes vs. Cohort Benchmark (>60 min variance)"
        ),
    },
    "investigations": {
        "title": "Workforce Investigations & Audit Dossiers",
        "tab_title": "Investigations",
        "icon": "🔍",
        "subtitle": "Employee investigation dossiers and audit drilldown tables will appear here.",
        "badge": "Step 28 — Investigations",
        "placeholder_text": "Employee investigation dossiers and audit drilldown tables will appear here.",
        "future_scope": (
            "• Repeated Attendance Exceptions Detector with Adjustable Threshold\n"
            "• Employee Repeat Exception Dossiers & Risk Flag Overlays\n"
            "• Comprehensive Multi-Factor Source-Record Audit Table & Drilldowns"
        ),
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Reusable ExecutiveKPICard Component
# ─────────────────────────────────────────────────────────────────────────────

class ExecutiveKPICard(ctk.CTkFrame):
    """
    Styled, high-contrast KPI metric card for Executive Overview.
    Presents card number/title, primary value, secondary percentage/qualification,
    and operational context footnote with responsive text wrapping and managed padding.
    """

    def __init__(
        self,
        master,
        card_id: str,
        title: str,
        accent_color: str = ui.COLOR_ACCENT,
        default_unit: str = "",
        tooltip_text: str = "",
        **kwargs,
    ):
        super().__init__(
            master,
            corner_radius=8,
            fg_color=ui.COLOR_CARD,
            border_width=1,
            border_color=ui.COLOR_BORDER,
            **kwargs,
        )
        self.card_id = card_id
        self.accent_color = accent_color
        self.default_unit = default_unit
        self.tooltip_text = tooltip_text
        self._last_cfg_w: int = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=1)

        # Header: Number & Title with color dot indicator
        h_frame = ctk.CTkFrame(self, fg_color="transparent")
        h_frame.grid(row=0, column=0, sticky="ew", padx=7, pady=(5, 2))
        h_frame.grid_columnconfigure(1, weight=1)

        dot = ctk.CTkLabel(
            h_frame,
            text="●",
            font=ctk.CTkFont(size=11),
            text_color=accent_color,
            width=10,
        )
        dot.grid(row=0, column=0, sticky="nw", padx=(0, 3), pady=(2, 0))

        self.lbl_title = ctk.CTkLabel(
            h_frame,
            text=title,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
            justify="left",
            wraplength=140,
        )
        self.lbl_title.grid(row=0, column=1, sticky="ew")

        # Primary Value Label
        self.lbl_val = ctk.CTkLabel(
            self,
            text="—",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=22, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
            justify="left",
            wraplength=160,
        )
        self.lbl_val.grid(row=1, column=0, sticky="ew", padx=7, pady=(0, 1))

        # Secondary / Percentage Label
        self.lbl_sub = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=accent_color,
            anchor="w",
            justify="left",
            wraplength=160,
        )
        self.lbl_sub.grid(row=2, column=0, sticky="ew", padx=7, pady=(0, 1))

        # Footnote / Explanation Label
        self.lbl_note = ctk.CTkLabel(
            self,
            text=tooltip_text,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
            justify="left",
            wraplength=160,
        )
        self.lbl_note.grid(row=3, column=0, sticky="ew", padx=7, pady=(0, 5))

        self.bind("<Configure>", self._on_card_configure)

    def _on_card_configure(self, event):
        w = event.width
        if abs(w - self._last_cfg_w) < 4:
            return
        self._last_cfg_w = w
        scaling = self._get_widget_scaling() if hasattr(self, "_get_widget_scaling") else 1.0
        unscaled_w = w / (scaling if scaling > 0 else 1.0)
        inner_w = max(90, int(unscaled_w - 14))
        title_w = max(75, int(inner_w - 14))

        self.lbl_title.configure(wraplength=title_w)
        self.lbl_val.configure(wraplength=inner_w)
        self.lbl_sub.configure(wraplength=inner_w)
        self.lbl_note.configure(wraplength=inner_w)

    def update_values(
        self,
        primary: str,
        secondary: str = "",
        note: Optional[str] = None,
        val_color: Optional[str] = None,
    ):
        """Update displayed card values on the main thread."""
        self.lbl_val.configure(
            text=primary,
            text_color=val_color or ui.COLOR_TEXT,
        )
        self.lbl_sub.configure(
            text=secondary,
            text_color=self.accent_color,
        )
        if note is not None:
            self.lbl_note.configure(text=note)


# ─────────────────────────────────────────────────────────────────────────────
# Executive Overview Visualization Widgets
# ─────────────────────────────────────────────────────────────────────────────

class AttendanceCompositionWidget(ctk.CTkFrame):
    """
    Compact organization-wide horizontal stacked attendance composition chart.
    Displays all 8 attendance categories with quantity-weighted day equivalents and
    percentages in a clean, responsive legend grid that reflows on width change.
    """
    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            corner_radius=10,
            fg_color=ui.COLOR_CARD,
            border_width=1,
            border_color=ui.COLOR_BORDER,
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        self._composition_data: List[Dict[str, Any]] = []
        self._denominator: float = 0.0
        self._current_cols: int = 4

        # Header block
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 2))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        t_box = ctk.CTkFrame(hdr, fg_color="transparent")
        t_box.grid(row=0, column=0, sticky="w")
        self.lbl_title = ctk.CTkLabel(
            t_box,
            text="Attendance Composition",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        )
        self.lbl_title.pack(anchor="w")

        self.lbl_sub = ctk.CTkLabel(
            t_box,
            text="Quantity-weighted day equivalents & % of composition denominator",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        self.lbl_sub.pack(anchor="w")

        self.lbl_denom_badge = ctk.CTkLabel(
            hdr,
            text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_ACCENT,
            anchor="e",
        )
        self.lbl_denom_badge.grid(row=0, column=1, sticky="e")

        # Stacked bar canvas
        self.bar_canvas = tk.Canvas(
            self,
            height=18,
            bg=ui.COLOR_CARD,
            bd=0,
            highlightthickness=0,
        )
        self.bar_canvas.grid(row=1, column=0, sticky="ew", padx=12, pady=(3, 5))
        self.bar_canvas.bind("<Configure>", lambda e: self._draw_bar())

        # Legend / Breakdown area
        self.legend_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.legend_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 6))
        self.legend_frame.bind("<Configure>", self._on_legend_configure)

        # Empty state label
        self.lbl_empty = ctk.CTkLabel(
            self,
            text="No attendance data available in active dataset",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_DIM,
        )

        self.reset()

    def update_data(self, composition_data: List[Dict[str, Any]], denominator: float):
        self._composition_data = composition_data or []
        self._denominator = float(denominator) if denominator else 0.0

        if self._denominator <= 0 or not self._composition_data:
            self.bar_canvas.grid_remove()
            self.legend_frame.grid_remove()
            self.lbl_denom_badge.configure(text="")
            self.lbl_empty.grid(row=1, column=0, rowspan=2, pady=20)
            return

        self.lbl_empty.grid_remove()
        self.bar_canvas.grid()
        self.legend_frame.grid()
        self.lbl_denom_badge.configure(text=f"Total: {_fmt_days(self._denominator)}")
        self._draw_bar()
        self._populate_legend()

    def reset(self):
        self._composition_data = []
        self._denominator = 0.0
        self.bar_canvas.delete("all")
        for child in self.legend_frame.winfo_children():
            child.destroy()
        self.lbl_denom_badge.configure(text="")
        self.bar_canvas.grid_remove()
        self.legend_frame.grid_remove()
        self.lbl_empty.grid(row=1, column=0, rowspan=2, pady=20)

    def _on_legend_configure(self, event):
        w = event.width
        if w <= 10:
            return
        target_cols = 4 if w >= 460 else 2
        if target_cols != self._current_cols:
            self._current_cols = target_cols
            if self._composition_data:
                self._populate_legend()

    def _draw_bar(self):
        self.bar_canvas.delete("all")
        w = self.bar_canvas.winfo_width()
        h = self.bar_canvas.winfo_height()
        if w <= 10 or h <= 4 or self._denominator <= 0 or not self._composition_data:
            return

        # Outer track with rounded border
        self.bar_canvas.create_rectangle(0, 1, w, h - 1, fill=ui.COLOR_INPUT_BG, outline=ui.COLOR_BORDER, width=1)

        active_items = [c for c in self._composition_data if c.get("days", 0.0) > 0]
        if not active_items:
            return

        total_w = float(w - 2)
        x_curr = 1.0
        for i, item in enumerate(active_items):
            days = float(item.get("days", 0.0))
            color = item.get("color", "#3B82F6")
            seg_w = max(2.0, (days / self._denominator) * total_w)
            x_next = min(float(w - 1), x_curr + seg_w)
            self.bar_canvas.create_rectangle(int(x_curr), 2, int(x_next), h - 2, fill=color, outline="")
            if i > 0:
                self.bar_canvas.create_line(int(x_curr), 2, int(x_curr), h - 2, fill=ui.COLOR_CARD, width=1)
            x_curr = x_next

    def _populate_legend(self):
        for child in self.legend_frame.winfo_children():
            child.destroy()

        if not self._composition_data:
            return

        num_cols = self._current_cols
        for c in range(8):
            self.legend_frame.grid_columnconfigure(c, weight=0)
        for c in range(num_cols):
            self.legend_frame.grid_columnconfigure(c, weight=1, uniform="comp_leg_col")

        for idx, item in enumerate(self._composition_data):
            r_idx = idx // num_cols
            c_idx = idx % num_cols

            cat_name = item.get("category", "")
            days = float(item.get("days", 0.0))
            pct = float(item.get("pct", 0.0))
            color = item.get("color", ui.COLOR_TEXT_DIM)
            is_unclass = "unclass" in cat_name.lower() or "unresolved" in cat_name.lower()

            short_name = "Unclassified" if is_unclass else cat_name

            cell = ctk.CTkFrame(
                self.legend_frame,
                fg_color="#141D2E",
                corner_radius=4,
                border_width=1,
                border_color="#1E293B",
            )
            cell.grid(row=r_idx, column=c_idx, sticky="ew", padx=2, pady=2)
            cell.grid_columnconfigure(1, weight=1)

            dot_text = "⚠️" if (is_unclass and days > 0) else "●"
            dot_color = ui.COLOR_WARNING if (is_unclass and days > 0) else color
            dot_size = 8 if dot_text == "●" else 10

            lbl_dot = ctk.CTkLabel(
                cell,
                text=dot_text,
                font=ctk.CTkFont(size=dot_size),
                text_color=dot_color,
                width=10,
            )
            lbl_dot.grid(row=0, column=0, sticky="w", padx=(4, 2), pady=(2, 0))

            cat_col = ui.COLOR_WARNING if (is_unclass and days > 0) else ui.COLOR_TEXT
            lbl_name = ctk.CTkLabel(
                cell,
                text=short_name,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
                text_color=cat_col,
                anchor="w",
            )
            lbl_name.grid(row=0, column=1, sticky="w", padx=(0, 4), pady=(2, 0))

            val_str = f"{_fmt_days(days)} | {pct:.1f}%"
            val_col = ui.COLOR_WARNING if (is_unclass and days > 0) else ui.COLOR_TEXT_SEC
            lbl_val = ctk.CTkLabel(
                cell,
                text=val_str,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
                text_color=val_col,
                anchor="w",
            )
            lbl_val.grid(row=1, column=0, columnspan=2, sticky="w", padx=(6, 4), pady=(0, 2))


class DailyAttendanceTrendWidget(ctk.CTkFrame):
    """
    Compact daily attendance trend chart tracking Present, WFH, and Leave
    in quantity-weighted employee-day equivalents per date across the reporting period.
    Features responsive horizontal scrolling for long periods (90, 180, 365+ days),
    a fixed Y-axis scale, antialiased lines, grid lines, and mouse hover inspection.
    """
    def __init__(self, parent, **kwargs):
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("fg_color", ui.COLOR_CARD)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", ui.COLOR_BORDER)
        super().__init__(
            parent,
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._trend_data: List[Dict[str, Any]] = []
        self._reporting_period: str = ""
        self._hover_coords: List[Tuple[float, Dict[str, Any]]] = []
        self._max_val: float = 1.0
        self._expanded_dialog: Optional["ExpandedDailyAttendanceTrendDialog"] = None
        self._scroll_active: bool = False

        # Header block (Row 0)
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 2))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)
        hdr.grid_columnconfigure(2, weight=0)

        t_box = ctk.CTkFrame(hdr, fg_color="transparent")
        t_box.grid(row=0, column=0, sticky="w")
        self.lbl_title = ctk.CTkLabel(
            t_box,
            text="Daily Attendance Trend",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        )
        self.lbl_title.pack(anchor="w")
        self.lbl_subtitle = ctk.CTkLabel(
            t_box,
            text="Present • WFH • Leave trends by calendar date",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        self.lbl_subtitle.pack(anchor="w")

        # Top-right series legend
        leg = ctk.CTkFrame(hdr, fg_color="transparent")
        leg.grid(row=0, column=1, sticky="e")
        for s_name, s_col in [("Present", "#10B981"), ("WFH", "#6366F1"), ("Leave", "#8B5CF6")]:
            ctk.CTkLabel(
                leg,
                text=f"● {s_name}",
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
                text_color=s_col,
            ).pack(side="left", padx=(6, 0))

        # Expand button (Row 0, Col 2)
        self.btn_expand = ctk.CTkButton(
            hdr,
            text="⛶",
            width=28,
            height=24,
            font=ctk.CTkFont(size=14),
            fg_color="transparent",
            text_color=ui.COLOR_TEXT_SEC,
            hover_color=ui.COLOR_CARD_HOVER,
            command=self._on_expand_clicked,
        )
        self.btn_expand.grid(row=0, column=2, sticky="e", padx=(8, 0))
        ui.create_tooltip(self.btn_expand, "Expand Daily Attendance Trend")

        # Chart Container (Row 1): Fixed Y-axis (Col 0) + Scrollable Plot Canvas (Col 1)
        self.plot_container = ctk.CTkFrame(self, fg_color="transparent")
        self.plot_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 2))
        self.plot_container.grid_columnconfigure(0, weight=0, minsize=28)
        self.plot_container.grid_columnconfigure(1, weight=1)
        self.plot_container.grid_rowconfigure(0, weight=1)
        self.plot_container.grid_rowconfigure(1, weight=0)

        # Fixed Y-axis canvas on left
        self.y_axis_canvas = tk.Canvas(
            self.plot_container,
            width=28,
            height=135,
            bg=ui.COLOR_CARD,
            bd=0,
            highlightthickness=0,
        )
        self.y_axis_canvas.grid(row=0, column=0, sticky="ns", padx=(0, 0), pady=0)

        # Scrollable plot canvas (retaining self.chart_canvas for test backwards compatibility)
        self.chart_canvas = tk.Canvas(
            self.plot_container,
            height=135,
            bg=ui.COLOR_CARD,
            bd=0,
            highlightthickness=0,
        )
        self.chart_canvas.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

        # Horizontal Scrollbar (directly beneath the plot canvas)
        self.h_scrollbar = ctk.CTkScrollbar(
            self.plot_container,
            orientation="horizontal",
            command=self.chart_canvas.xview,
            height=9,
        )
        self.chart_canvas.configure(xscrollcommand=self.h_scrollbar.set)

        self.chart_canvas.bind("<Configure>", lambda e: self._draw_chart())
        self.chart_canvas.bind("<Motion>", self._on_canvas_motion)
        self.chart_canvas.bind("<Leave>", self._on_canvas_leave)
        self.chart_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.chart_canvas.bind("<Shift-MouseWheel>", self._on_mousewheel)

        # Hover coordinate & value inspector label (Row 2)
        self.lbl_hover_info = ctk.CTkLabel(
            self,
            text="Hover over chart line to inspect daily values",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
        )
        self.lbl_hover_info.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))

        # Empty state label
        self.lbl_empty = ctk.CTkLabel(
            self,
            text="No daily attendance records in active dataset",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_DIM,
        )

        self.reset()

    def _on_expand_clicked(self):
        """Open the dedicated enlarged Daily Attendance Trend dialog."""
        if self._expanded_dialog is not None and self._expanded_dialog.winfo_exists():
            self._expanded_dialog.lift()
            self._expanded_dialog.focus_force()
            return
        if not self._trend_data:
            return
        self._expanded_dialog = ExpandedDailyAttendanceTrendDialog(
            parent_widget=self,
            trend_data=self._trend_data,
            reporting_period=self._reporting_period,
        )

    def _on_mousewheel(self, event):
        """Allow horizontal scrolling with mouse wheel when scrollbar is active."""
        if self._scroll_active:
            delta = event.delta
            if delta != 0:
                self.chart_canvas.xview_scroll(int(-1 * (delta / 120)), "units")

    def update_data(self, trend_data: List[Dict[str, Any]], reporting_period: str = ""):
        self._trend_data = trend_data or []
        self._reporting_period = reporting_period

        if self._expanded_dialog is not None and self._expanded_dialog.winfo_exists():
            try:
                self._expanded_dialog.update_data(self._trend_data, reporting_period=self._reporting_period)
            except Exception:
                pass

        if not self._trend_data:
            self.reset()
            return

        self.lbl_empty.grid_remove()
        self.plot_container.grid()
        self.lbl_hover_info.grid()
        self._draw_chart()
        self.after_idle(self._draw_chart)

    def reset(self):
        self._trend_data = []
        self._reporting_period = ""
        self._hover_coords = []
        self._max_val = 1.0
        self._scroll_active = False
        self.chart_canvas.delete("all")
        self.y_axis_canvas.delete("all")
        self.h_scrollbar.grid_remove()
        self.lbl_hover_info.configure(text="Hover over chart line to inspect daily values")
        self.plot_container.grid_remove()
        self.lbl_hover_info.grid_remove()
        self.lbl_empty.grid(row=1, column=0, rowspan=2, pady=25)
        if self._expanded_dialog is not None and self._expanded_dialog.winfo_exists():
            try:
                self._expanded_dialog.destroy()
            except Exception:
                pass
            self._expanded_dialog = None

    def _draw_chart(self):
        self.chart_canvas.delete("all")
        self.y_axis_canvas.delete("all")
        self._hover_coords = []
        visible_w = self.chart_canvas.winfo_width()
        h = self.chart_canvas.winfo_height()
        if visible_w <= 40 or h <= 20 or not self._trend_data:
            return

        pad_top = 16.0
        pad_bottom = 18.0
        pad_h = 6.0  # Horizontal padding inside plot canvas for first & last points
        h_avail = max(10.0, h - pad_top - pad_bottom)
        n_dates = len(self._trend_data)

        # Determine vertical scale max
        max_val = 1.0
        for d in self._trend_data:
            max_val = max(
                max_val,
                float(d.get("present_days", 0.0)),
                float(d.get("wfh_days", 0.0)),
                float(d.get("leave_days", 0.0)),
            )
        if max_val < 4.0:
            max_val = 4.0
        max_val = math.ceil(max_val)
        self._max_val = float(max_val)

        # Draw Y-axis scale on fixed y_axis_canvas
        # Unit label at top right of Y-axis canvas
        self.y_axis_canvas.create_text(
            26, 5.0, text="days", anchor="e", fill=ui.COLOR_TEXT_DIM, font=(ui.FONT_FAMILY, 8)
        )
        grid_fracs = [0.0, 0.5, 1.0] if max_val <= 6 else [0.0, 0.333, 0.667, 1.0]
        for frac in grid_fracs:
            y = pad_top + frac * h_avail
            val_at_y = int(round(max_val * (1.0 - frac)))
            self.y_axis_canvas.create_text(
                22, y, text=f"{val_at_y}", anchor="e", fill=ui.COLOR_TEXT_DIM, font=(ui.FONT_FAMILY, 9)
            )
            # Extension tick line connecting cleanly with chart grid line
            self.y_axis_canvas.create_line(23, y, 28, y, fill=ui.COLOR_BORDER, width=1)

        # Determine horizontal layout:
        # Minimum spacing per point = 24px
        min_spacing = 24.0
        natural_w = pad_h * 2 + (n_dates - 1) * min_spacing if n_dates > 1 else pad_h * 2

        if natural_w > visible_w:
            # Long range: activate scrollbar
            plot_w = natural_w
            x_step = min_spacing
            self._scroll_active = True
            self.h_scrollbar.grid(row=1, column=1, sticky="ew", padx=0, pady=(2, 0))
            self.chart_canvas.configure(scrollregion=(0, 0, plot_w, h))
        else:
            # Short range: fits in visible width, no scrollbar
            plot_w = visible_w
            x_step = (visible_w - 2 * pad_h) / max(1, n_dates - 1) if n_dates > 1 else 0.0
            self._scroll_active = False
            self.h_scrollbar.grid_remove()
            self.chart_canvas.configure(scrollregion=(0, 0, visible_w, h))
            self.chart_canvas.xview_moveto(0.0)

        # Horizontal grid lines across plot canvas
        for frac in grid_fracs:
            y = pad_top + frac * h_avail
            self.chart_canvas.create_line(0, y, plot_w, y, fill=ui.COLOR_BORDER, width=1)

        # Calculate coordinates for each date point
        for i, d_rec in enumerate(self._trend_data):
            if n_dates == 1:
                x = plot_w / 2.0
            else:
                x = pad_h + i * x_step
            self._hover_coords.append((x, d_rec))

        # Plot 3 Series: Leave (#8B5CF6), WFH (#6366F1), Present (#10B981)
        series_configs = [
            ("leave_days", "#8B5CF6"),
            ("wfh_days", "#6366F1"),
            ("present_days", "#10B981"),
        ]

        for s_key, s_color in series_configs:
            pts = []
            for x, d_rec in self._hover_coords:
                val = float(d_rec.get(s_key, 0.0))
                y = pad_top + (1.0 - (val / self._max_val)) * h_avail
                pts.extend([x, y])

            if len(pts) >= 4:
                self.chart_canvas.create_line(pts, fill=s_color, width=2)
            for j in range(0, len(pts), 2):
                px, py = pts[j], pts[j + 1]
                self.chart_canvas.create_oval(
                    px - 2.5, py - 2.5, px + 2.5, py + 2.5,
                    fill=s_color, outline=ui.COLOR_CARD, width=1
                )

        # Date axis labels (subsampled based on point spacing)
        # Avoid label collisions by ensuring at least ~65px between labels
        label_spacing_step = max(1, math.ceil(65.0 / max(1.0, x_step)))
        sample_indices = set(range(0, n_dates, label_spacing_step))
        sample_indices.add(n_dates - 1)  # Always include final observed date!

        # If the penultimate sample is too close to the final date (< 60% of step), prune it
        if n_dates > 2 and (n_dates - 1) in sample_indices:
            candidates = sorted([idx for idx in sample_indices if idx < n_dates - 1])
            if candidates and ((n_dates - 1) - candidates[-1]) < max(1, int(label_spacing_step * 0.6)):
                sample_indices.remove(candidates[-1])

        for i, (x, d_rec) in enumerate(self._hover_coords):
            if i in sample_indices:
                d_lbl = d_rec.get("date_str", "")
                if len(d_lbl) == 10 and d_lbl[4] == "-" and d_lbl[7] == "-":
                    try:
                        dt = datetime.strptime(d_lbl, "%Y-%m-%d")
                        d_lbl = dt.strftime("%d %b")
                    except Exception:
                        d_lbl = d_lbl[5:]

                # Alignment: First date anchors "w", last date anchors "e", others "center"
                if i == 0:
                    anchor = "w"
                    lx = 2.0
                elif i == n_dates - 1:
                    anchor = "e"
                    lx = plot_w - 2.0
                else:
                    anchor = "center"
                    lx = x

                self.chart_canvas.create_text(
                    lx,
                    h - 7,
                    text=d_lbl,
                    anchor=anchor,
                    fill=ui.COLOR_TEXT_DIM,
                    font=(ui.FONT_FAMILY, 9),
                )

    def _on_canvas_motion(self, event):
        if not self._hover_coords:
            return
        # Translate event.x into canvas coordinate space to support scrolling
        canvas_x = self.chart_canvas.canvasx(event.x)
        nearest_x, nearest_rec = min(self._hover_coords, key=lambda item: abs(item[0] - canvas_x))
        h = self.chart_canvas.winfo_height()
        pad_top = 16.0
        pad_bottom = 18.0
        h_avail = max(10.0, h - pad_top - pad_bottom)

        self.chart_canvas.delete("hover_indicator")
        # Vertical guide line
        self.chart_canvas.create_line(
            nearest_x, pad_top, nearest_x, h - pad_bottom,
            fill="#3B82F6", width=1, dash=(2, 2), tags="hover_indicator"
        )
        # Highlight points on hover
        for s_key, s_col in [("present_days", "#10B981"), ("wfh_days", "#6366F1"), ("leave_days", "#8B5CF6")]:
            val = float(nearest_rec.get(s_key, 0.0))
            y_pt = pad_top + (1.0 - (val / self._max_val)) * h_avail
            self.chart_canvas.create_oval(
                nearest_x - 4.5, y_pt - 4.5, nearest_x + 4.5, y_pt + 4.5,
                fill=s_col, outline="#FFFFFF", width=1.5, tags="hover_indicator"
            )

        d_str = nearest_rec.get("date_str", "")
        pres = float(nearest_rec.get("present_days", 0.0))
        wfh = float(nearest_rec.get("wfh_days", 0.0))
        lv = float(nearest_rec.get("leave_days", 0.0))

        self.lbl_hover_info.configure(
            text=f"📅 {d_str}   •   Present: {_fmt_days(pres)}   •   WFH: {_fmt_days(wfh)}   •   Leave: {_fmt_days(lv)}",
            text_color=ui.COLOR_TEXT,
        )

    def _on_canvas_leave(self, event):
        self.chart_canvas.delete("hover_indicator")
        self.lbl_hover_info.configure(
            text="Hover over chart line to inspect daily values",
            text_color=ui.COLOR_TEXT_DIM,
        )


class ExpandedDailyAttendanceTrendDialog(ctk.CTkToplevel):
    """
    Dedicated enlarged, resizable modal/dialog displaying the Daily Attendance Trend.
    Reuses prepared trend data without reloading Excel or recomputing KPIs.
    Supports horizontal scrolling for long reporting periods, hover inspection,
    and Escape key to close. Prevents duplicate dialogs.
    """
    def __init__(self, parent_widget: "DailyAttendanceTrendWidget", trend_data: List[Dict[str, Any]], reporting_period: str = ""):
        super().__init__()
        self.parent_widget = parent_widget
        self._trend_data = trend_data
        self._reporting_period = reporting_period

        self.title("Daily Attendance Trend — Expanded Analysis")
        self.geometry("1100x650")
        self.minsize(800, 450)
        self.configure(fg_color=ui.COLOR_BG)

        # Center on screen or parent
        self.update_idletasks()
        try:
            x = max(50, parent_widget.winfo_rootx() - 100)
            y = max(50, parent_widget.winfo_rooty() - 100)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top Header Bar
        hdr = ctk.CTkFrame(self, fg_color=ui.COLOR_CARD, corner_radius=0, height=52)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        t_box = ctk.CTkFrame(hdr, fg_color="transparent")
        t_box.grid(row=0, column=0, sticky="w", padx=20, pady=10)

        period_str = f" • Reporting Period: {reporting_period}" if reporting_period else ""
        ctk.CTkLabel(
            t_box,
            text="Daily Attendance Trend — Expanded Analysis",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=16, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        ).pack(anchor="w")
        self.lbl_subtitle = ctk.CTkLabel(
            t_box,
            text=f"Present • WFH • Leave quantity-weighted daily time series{period_str}",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        self.lbl_subtitle.pack(anchor="w")

        r_box = ctk.CTkFrame(hdr, fg_color="transparent")
        r_box.grid(row=0, column=1, sticky="e", padx=20, pady=10)

        btn_close = ui.create_secondary_button(
            r_box,
            "✕ Close",
            command=self._on_close,
            width=80,
            height=28,
        )
        btn_close.pack(side="right")

        # Body: embed an expanded DailyAttendanceTrendWidget
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 16))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.expanded_trend = DailyAttendanceTrendWidget(body, fg_color=ui.COLOR_CARD)
        self.expanded_trend.grid(row=0, column=0, sticky="nsew")
        # Hide the inner expand button in the expanded view
        if hasattr(self.expanded_trend, "btn_expand"):
            self.expanded_trend.btn_expand.grid_remove()

        self.expanded_trend.update_data(self._trend_data, reporting_period=self._reporting_period)

        # Protocols and key bindings
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())
        self.focus_force()

    def update_data(self, trend_data: List[Dict[str, Any]], reporting_period: str = ""):
        """Update expanded chart view live with new filtered trend data."""
        self._trend_data = trend_data or []
        self._reporting_period = reporting_period
        period_str = f" • Reporting Period: {reporting_period}" if reporting_period else ""
        if hasattr(self, "lbl_subtitle"):
            self.lbl_subtitle.configure(text=f"Present • WFH • Leave quantity-weighted daily time series{period_str}")
        if hasattr(self, "expanded_trend"):
            self.expanded_trend.update_data(self._trend_data, reporting_period=self._reporting_period)

    def _on_close(self):
        if hasattr(self.parent_widget, "_expanded_dialog"):
            self.parent_widget._expanded_dialog = None
        self.destroy()



class DateRangePickerDialog(ctk.CTkToplevel):
    """
    Compact modal dialog for selecting custom start and end dates from observed dataset dates.
    Validates start_date <= end_date. Prevents duplicate dialogs.
    """
    def __init__(
        self,
        parent_view: "WorkforceDashboardView",
        available_dates: List[date],
        current_start: Optional[date] = None,
        current_end: Optional[date] = None,
        on_apply: Optional[Any] = None,
    ):
        super().__init__()
        self.parent_view = parent_view
        self._available_dates = sorted(available_dates)
        self._on_apply = on_apply
        self._date_strings = [d.isoformat() for d in self._available_dates]

        self.title("Select Custom Date Range")
        self.geometry("380x250")
        self.resizable(False, False)
        self.configure(fg_color=ui.COLOR_BG)

        # Center on parent_view
        self.update_idletasks()
        try:
            x = max(50, parent_view.winfo_rootx() + 150)
            y = max(50, parent_view.winfo_rooty() + 100)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

        # Content frame
        frame = ctk.CTkFrame(self, fg_color=ui.COLOR_CARD, corner_radius=8)
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            frame,
            text="Custom Date Range",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            text_color=ui.COLOR_TEXT,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        # Start Date row
        f_start = ctk.CTkFrame(frame, fg_color="transparent")
        f_start.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            f_start,
            text="Start Date:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC,
            width=80,
            anchor="w",
        ).pack(side="left")

        default_start_str = current_start.isoformat() if current_start else (self._date_strings[0] if self._date_strings else "")
        self.combo_start = ctk.CTkComboBox(
            f_start,
            values=self._date_strings or ["N/A"],
            height=28,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        if default_start_str in self._date_strings:
            self.combo_start.set(default_start_str)
        self.combo_start.pack(side="left", fill="x", expand=True)

        # End Date row
        f_end = ctk.CTkFrame(frame, fg_color="transparent")
        f_end.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            f_end,
            text="End Date:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC,
            width=80,
            anchor="w",
        ).pack(side="left")

        default_end_str = current_end.isoformat() if current_end else (self._date_strings[-1] if self._date_strings else "")
        self.combo_end = ctk.CTkComboBox(
            f_end,
            values=self._date_strings or ["N/A"],
            height=28,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        if default_end_str in self._date_strings:
            self.combo_end.set(default_end_str)
        self.combo_end.pack(side="left", fill="x", expand=True)

        # Error / Validation Label
        self.lbl_error = ctk.CTkLabel(
            frame,
            text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_ERROR,
            anchor="w",
        )
        self.lbl_error.pack(fill="x", padx=16, pady=(4, 2))

        # Button row
        btn_box = ctk.CTkFrame(frame, fg_color="transparent")
        btn_box.pack(fill="x", padx=16, pady=(6, 12))

        btn_cancel = ui.create_secondary_button(
            btn_box,
            "Cancel",
            command=self._on_close,
            width=70,
            height=26,
        )
        btn_cancel.pack(side="right", padx=(6, 0))

        btn_apply = ui.create_primary_button(
            btn_box,
            "Apply Range",
            command=self._on_apply_clicked,
            width=90,
            height=26,
        )
        btn_apply.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())
        self.focus_force()

    def _on_apply_clicked(self):
        s_val = self.combo_start.get().strip()
        e_val = self.combo_end.get().strip()
        parsed_s = tsa.parse_date_value(s_val)
        parsed_e = tsa.parse_date_value(e_val)

        if not parsed_s or not parsed_e:
            self.lbl_error.configure(text="Invalid date selection.")
            return

        if parsed_s > parsed_e:
            self.lbl_error.configure(text="Start date cannot be after end date.")
            return

        if self._on_apply:
            self._on_apply(parsed_s, parsed_e)
        self._on_close()

    def _on_close(self):
        if hasattr(self.parent_view, "_date_picker_dialog"):
            self.parent_view._date_picker_dialog = None
        # If user cancelled and custom range was not set, revert combobox display
        if hasattr(self.parent_view, "combo_date_range") and hasattr(self.parent_view, "_filter_state"):
            cur_preset = self.parent_view._filter_state.get("date_preset", "All Dates")
            if cur_preset != "Custom Range":
                self.parent_view.combo_date_range.set(cur_preset)
        self.destroy()


class DataQualityDetailDialog(ctk.CTkToplevel):
    """
    Dedicated modal dialog providing complete transparency on data quality findings,
    unclassified records, conflicting employee-days, and attendance composition reconciliation.
    Easily closed via Close button or Escape key.
    """
    def __init__(self, parent_view: "WorkforceDashboardView", bundle: Dict[str, Any], full_bundle: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.parent_view = parent_view
        self._bundle = bundle or {}
        self._full_bundle = full_bundle or self._bundle

        self.title("Data Quality & Governance Diagnostics")
        self.geometry("620x520")
        self.minsize(500, 400)
        self.configure(fg_color=ui.COLOR_BG)

        # Center on screen or parent
        self.update_idletasks()
        try:
            x = max(50, parent_view.winfo_rootx() + 50)
            y = max(50, parent_view.winfo_rooty() + 50)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top Header Bar
        hdr = ctk.CTkFrame(self, fg_color=ui.COLOR_CARD, corner_radius=0, height=52)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        t_box = ctk.CTkFrame(hdr, fg_color="transparent")
        t_box.grid(row=0, column=0, sticky="w", padx=20, pady=10)

        ctk.CTkLabel(
            t_box,
            text="Data Quality Diagnostics & Reconciliation",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=16, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            t_box,
            text="Comprehensive validation findings for active workforce intelligence dataset",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        ).pack(anchor="w")

        btn_close = ui.create_secondary_button(
            hdr,
            "✕ Close",
            command=self._on_close,
            width=70,
            height=28,
        )
        btn_close.grid(row=0, column=1, sticky="e", padx=20, pady=10)

        # Scrollable content frame
        content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew", padx=20, pady=12)
        content.grid_columnconfigure(0, weight=1)

        # Extract bundle values
        unclass_cnt = self._bundle.get("unclassified_records_count", 0)
        unclass_days = self._bundle.get("kpi_unclassified_days", 0.0)
        unclass_pct = self._bundle.get("kpi_unclassified_pct", 0.0)
        conflicts_cnt = self._bundle.get("conflicting_employee_days_count", 0)
        denom = self._bundle.get("attendance_composition_denominator", 0.0)
        excp_days = self._bundle.get("kpi_9_attendance_exceptions_days", 0)

        q_pres = self._bundle.get("kpi_3_present_days", 0.0)
        q_od = self._bundle.get("kpi_4_od_days", 0.0)
        q_leave = self._bundle.get("kpi_5_leave_days", 0.0)
        q_wfh = self._bundle.get("kpi_6_wfh_days", 0.0)
        q_hol = self._bundle.get("kpi_7_holiday_days", 0.0)
        q_wo = self._bundle.get("kpi_8_week_off_days", 0.0)
        q_ab = self._bundle.get("kpi_absent_days", 0.0)
        categorized = round(q_pres + q_od + q_leave + q_wfh + q_hol + q_wo + q_ab, 1)

        # 1. Status Overview Card
        c1 = ctk.CTkFrame(content, fg_color=ui.COLOR_CARD, corner_radius=8, border_width=1, border_color=ui.COLOR_BORDER)
        c1.pack(fill="x", pady=(0, 10))
        c1.grid_columnconfigure(1, weight=1)

        is_clean = (unclass_cnt == 0 and conflicts_cnt == 0)
        icon_txt = "🛡️" if is_clean else "⚠️"
        status_txt = "Clean • Ready for Analysis" if is_clean else f"Review Needed ({conflicts_cnt + unclass_cnt} issue(s) detected)"
        status_col = ui.COLOR_SUCCESS if is_clean else ui.COLOR_WARNING

        ctk.CTkLabel(c1, text=icon_txt, font=ctk.CTkFont(size=24)).grid(row=0, column=0, rowspan=2, padx=14, pady=12)
        ctk.CTkLabel(
            c1, text=status_txt, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            text_color=status_col, anchor="w",
        ).grid(row=0, column=1, sticky="w", pady=(10, 0))
        desc_txt = (
            "All attendance records successfully resolved and classified into standard attendance buckets."
            if is_clean else
            "Certain records contain unclassified statuses or multiple contradictory entries on the same employee-date."
        )
        ctk.CTkLabel(
            c1, text=desc_txt, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", wraplength=480,
        ).grid(row=1, column=1, sticky="w", pady=(0, 10))

        # 2. Key Findings Card
        c2 = ctk.CTkFrame(content, fg_color=ui.COLOR_CARD, corner_radius=8, border_width=1, border_color=ui.COLOR_BORDER)
        c2.pack(fill="x", pady=(0, 10))
        c2.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            c2, text="Diagnostic Findings", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT, anchor="w",
        ).pack(anchor="w", padx=14, pady=(10, 6))

        findings = [
            ("Conflicting Employee-Days", f"{conflicts_cnt:,} dates",
             "Employee-dates with multiple overlapping or contradictory attendance rows resolved to unresolved state."),
            ("Unclassified Source Records", f"{unclass_cnt:,} records",
             "Source attendance rows with unrecognized attendance type/code that could not be classified."),
            ("Unresolved Attendance Days", f"{_fmt_days(unclass_days)} ({unclass_pct:.1f}%)",
             "Total day equivalents left unresolved in the attendance composition denominator."),
        ]
        full_unclass = self._full_bundle.get("unclassified_records_count", 0)
        full_conflicts = self._full_bundle.get("conflicting_employee_days_count", 0)
        if full_unclass != unclass_cnt or full_conflicts != conflicts_cnt:
            findings.append((
                "Dataset-Wide Quality Baseline",
                f"{full_conflicts:,} conflicts • {full_unclass:,} unclassified",
                "Total unresolved data quality findings detected across the entire uploaded dataset.",
            ))
        for f_title, f_val, f_desc in findings:
            f_row = ctk.CTkFrame(c2, fg_color="transparent")
            f_row.pack(fill="x", padx=14, pady=4)
            f_row.grid_columnconfigure(0, weight=1)
            f_row.grid_columnconfigure(1, weight=0)

            ctk.CTkLabel(f_row, text=f_title, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
                         text_color=ui.COLOR_TEXT).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(f_row, text=f_val, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
                         text_color=ui.COLOR_WARNING if ("0" not in f_val and f_val != "0.0") else ui.COLOR_SUCCESS).grid(row=0, column=1, sticky="e")
            ctk.CTkLabel(f_row, text=f_desc, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10),
                         text_color=ui.COLOR_TEXT_DIM, wraplength=480, anchor="w").grid(row=1, column=0, columnspan=2, sticky="w", pady=(1, 4))

        # 3. Attendance Composition Reconciliation Card
        c3 = ctk.CTkFrame(content, fg_color=ui.COLOR_CARD, corner_radius=8, border_width=1, border_color=ui.COLOR_BORDER)
        c3.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            c3, text="Attendance Reconciliation", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT, anchor="w",
        ).pack(anchor="w", padx=14, pady=(10, 6))

        recon_items = [
            ("Composition Denominator", _fmt_days(denom)),
            ("Categorized Attendance Days", _fmt_days(categorized)),
            ("Unresolved Balance", _fmt_days(unclass_days)),
        ]
        for r_name, r_val in recon_items:
            r_frame = ctk.CTkFrame(c3, fg_color="transparent")
            r_frame.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(r_frame, text=r_name, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
                         text_color=ui.COLOR_TEXT_SEC).pack(side="left")
            ctk.CTkLabel(r_frame, text=r_val, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
                         text_color=ui.COLOR_TEXT).pack(side="right")

        # 4. Governance & Attendance Exceptions Notice Card
        c4 = ctk.CTkFrame(content, fg_color="transparent")
        c4.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(
            c4,
            text=(
                f"ℹ️ Governance Distinction:\n"
                f"Attendance Exceptions ({excp_days:,} Regularized employee-days) represent approved operational swipe regularizations. "
                f"They are legitimate attendance events tracked for policy governance, and are separate from data-quality validation findings."
            ),
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10),
            text_color=ui.COLOR_TEXT_DIM,
            justify="left",
            anchor="w",
            wraplength=480,
        ).pack(fill="x", padx=4)

        # Key bindings and protocol
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())
        self.focus_force()

    def _on_close(self):
        if hasattr(self.parent_view, "_dq_dialog"):
            self.parent_view._dq_dialog = None
        self.destroy()


TABLE_COLUMNS = [
    # (col_id, title, min_width, anchor)
    ("bu", "Business Unit", 150, "w"),
    ("hc", "Headcount", 55, "e"),
    ("rec_days", "Rec. Days", 60, "e"),
    ("present", "Present", 65, "e"),
    ("pres_pct", "Pres %", 50, "e"),
    ("leave", "Leave", 60, "e"),
    ("leave_pct", "Leave %", 50, "e"),
    ("wfh", "WFH", 65, "e"),
    ("wfh_pct", "WFH %", 50, "e"),
    ("od", "OD Days", 55, "e"),
    ("absent", "Absent", 55, "e"),
    ("exceptions", "Exceptions", 60, "e"),
    ("excp_rate", "Excp Rate", 55, "e"),
]
TOTAL_TABLE_WIDTH = sum(c[2] for c in TABLE_COLUMNS)  # exactly 780 logical width (~1,170px at 1.5x scaling)
TOTAL_TABLE_MIN_WIDTH = TOTAL_TABLE_WIDTH  # Backwards compatibility alias


class BusinessUnitComparisonTableWidget(ctk.CTkFrame):
    """
    Compact scrollable Business Unit comparison table with strict column alignment.
    Displays BU-level Observed Headcount, Recorded Days, Present Days & %, Leave Days & %,
    WFH Days & %, OD Days, Absent Days, Attendance Exceptions & Exception Rate,
    and total organization-wide summary row.
    Features:
    - Bounded fixed-height rows viewport (6-8 rows visible, e.g. 192px).
    - Sticky header pinned at the top with dynamic DPI-aware height (zero text clipping).
    - Pinned Organization-Wide Total row directly beneath the data rows with dynamic DPI-aware height.
    - Synchronized horizontal scrolling across Header, Data Rows, and Total Row.
    - Clearly visible, functional vertical scrollbar for BU rows.
    - Smart horizontal scrollbar that appears only when columns overflow and spans all 13 columns.
    - Mouse-wheel isolation: scrolling over BU rows scrolls only the table, not the outer page.
    - Full BU text accessible via hover inspection line.
    """
    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            corner_radius=10,
            fg_color=ui.COLOR_CARD,
            border_width=1,
            border_color=ui.COLOR_BORDER,
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        self._bu_data: List[Dict[str, Any]] = []
        self._bu_total: Dict[str, Any] = {}

        # Header block (Row 0)
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        t_box = ctk.CTkFrame(hdr, fg_color="transparent")
        t_box.grid(row=0, column=0, sticky="w")
        self.lbl_title = ctk.CTkLabel(
            t_box,
            text="Business Unit Attendance Comparison",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        )
        self.lbl_title.pack(anchor="w")

        self.lbl_sub = ctk.CTkLabel(
            t_box,
            text="Organizational breakdown with effective BU mapping & Regularized exception rates",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        self.lbl_sub.pack(anchor="w")

        self.lbl_bu_count = ctk.CTkLabel(
            hdr,
            text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="e",
        )
        self.lbl_bu_count.grid(row=0, column=1, sticky="e")

        # Table Grid Container (Row 1)
        # Contains:
        # Col 0: header_canvas, rows_canvas, total_canvas, h_scrollbar
        # Col 1: header_spacer, v_scrollbar, total_spacer, h_scrollbar_spacer
        self.grid_box = ctk.CTkFrame(self, fg_color="transparent")
        self.grid_box.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 2))
        self.grid_box.grid_columnconfigure(0, weight=1)
        self.grid_box.grid_columnconfigure(1, weight=0)

        # 1. Sticky Header Canvas (Row 0 of grid_box)
        self.header_canvas = tk.Canvas(
            self.grid_box,
            height=26,
            bg=ui.COLOR_INPUT_BG,
            bd=0,
            highlightthickness=0,
        )
        self.header_canvas.grid(row=0, column=0, sticky="ew")

        self.header_spacer = ctk.CTkFrame(self.grid_box, width=10, height=26, fg_color=ui.COLOR_INPUT_BG)
        self.header_spacer.grid(row=0, column=1, sticky="ns")

        self.table_hdr_frame = ctk.CTkFrame(self.header_canvas, fg_color=ui.COLOR_INPUT_BG, corner_radius=0)
        self.header_window = self.header_canvas.create_window((0, 0), window=self.table_hdr_frame, anchor="nw")

        # 2. Data Rows Viewport Canvas (Row 1 of grid_box)
        self.rows_canvas = tk.Canvas(
            self.grid_box,
            height=176,
            bg=ui.COLOR_CARD,
            bd=0,
            highlightthickness=0,
        )
        self.rows_canvas.grid(row=1, column=0, sticky="nsew")

        self.v_scrollbar = ctk.CTkScrollbar(
            self.grid_box,
            orientation="vertical",
            command=self.rows_canvas.yview,
            width=10,
            button_color="#334155",
            button_hover_color="#475569",
        )
        self.v_scrollbar.grid(row=1, column=1, sticky="ns", padx=(2, 0))
        self.rows_canvas.configure(yscrollcommand=self.v_scrollbar.set)

        self.rows_inner_frame = ctk.CTkFrame(self.rows_canvas, fg_color="transparent")
        self.rows_frame = self.rows_inner_frame  # Backwards compatibility alias for tests
        self.rows_window = self.rows_canvas.create_window((0, 0), window=self.rows_inner_frame, anchor="nw")

        # 3. Pinned Organization-Wide Total Canvas (Row 2 of grid_box)
        self.total_canvas = tk.Canvas(
            self.grid_box,
            height=28,
            bg="#18233C",
            bd=0,
            highlightthickness=0,
        )
        self.total_canvas.grid(row=2, column=0, sticky="ew")

        self.total_spacer = ctk.CTkFrame(self.grid_box, width=10, height=28, fg_color="#18233C")
        self.total_spacer.grid(row=2, column=1, sticky="ns")

        self.total_frame = ctk.CTkFrame(self.total_canvas, fg_color="#18233C", corner_radius=0)
        self.total_window = self.total_canvas.create_window((0, 0), window=self.total_frame, anchor="nw")

        # 4. Horizontal Scrollbar (Row 3 of grid_box)
        self.h_scrollbar = ctk.CTkScrollbar(
            self.grid_box,
            orientation="horizontal",
            command=self._on_h_scroll,
            height=10,
            button_color="#334155",
            button_hover_color="#475569",
        )
        self.h_scrollbar.grid(row=3, column=0, sticky="ew", pady=(3, 2))

        self.h_scrollbar_spacer = ctk.CTkFrame(self.grid_box, width=10, height=10, fg_color="transparent")
        self.h_scrollbar_spacer.grid(row=3, column=1, sticky="ns")

        # Connect xscrollcommand from rows_canvas to h_scrollbar
        self.rows_canvas.configure(xscrollcommand=self._on_canvas_xscroll)

        # Backwards compatibility aliases
        self.table_canvas = self.rows_canvas
        self.table_viewport = self.grid_box
        self.table_inner_frame = self.rows_inner_frame

        # Row 2 of Widget: Interactive Info Tip / Full BU Name Display
        self.lbl_info = ctk.CTkLabel(
            self,
            text="Tip: Shift + MouseWheel to scroll columns horizontally  •  Hover row for full BU details",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
        )
        self.lbl_info.grid(row=2, column=0, sticky="w", padx=12, pady=(2, 0))

        # Row 3 of Widget: Footnote
        self.lbl_note = ctk.CTkLabel(
            self,
            text="* Headcount reflects observed unique employees in each BU; Total reflects deduplicated organization-wide unique headcount. Exception rate = Regularized employee-days / Recorded employee-days.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
        )
        self.lbl_note.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 4))

        # Empty state label
        self.lbl_empty = ctk.CTkLabel(
            self,
            text="No Business Unit data available in active dataset",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_DIM,
        )

        # Mouse wheel & configure bindings
        self.rows_canvas.bind("<MouseWheel>", self._on_rows_mousewheel)
        self.rows_canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.rows_inner_frame.bind("<MouseWheel>", self._on_rows_mousewheel)
        self.rows_inner_frame.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

        self.header_canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.total_canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

        self.grid_box.bind("<Configure>", self._on_grid_box_configure)
        self.rows_canvas.bind("<Configure>", lambda e: self._sync_table_geometry())

        self.reset()

    def _on_h_scroll(self, *args):
        """Scroll Header, Data Rows, and Total Row horizontally in lockstep."""
        self.header_canvas.xview(*args)
        self.rows_canvas.xview(*args)
        self.total_canvas.xview(*args)

    def _on_canvas_xscroll(self, first, last):
        """Synchronize horizontal scrollbar thumb with current canvas view."""
        self.h_scrollbar.set(first, last)

    def _on_rows_mousewheel(self, event):
        """Scroll BU rows vertically while stopping event propagation to outer page."""
        delta = -1 if event.delta > 0 else 1
        self.rows_canvas.yview_scroll(delta, "units")
        return "break"

    def _on_shift_mousewheel(self, event):
        """Scroll all three canvases horizontally via Shift + MouseWheel."""
        delta = -1 if event.delta > 0 else 1
        self.header_canvas.xview_scroll(delta, "units")
        self.rows_canvas.xview_scroll(delta, "units")
        self.total_canvas.xview_scroll(delta, "units")
        return "break"

    def _on_row_enter(self, b_rec: Dict[str, Any]):
        """Display full unclipped BU details in the info tip line on hover."""
        bu_full = b_rec.get("business_unit", "")
        h_c = b_rec.get("observed_headcount", 0)
        r_d = b_rec.get("recorded_employee_days", 0)
        p_pct = b_rec.get("present_pct", 0.0)
        e_c = b_rec.get("exception_days", 0)
        self.lbl_info.configure(
            text=f"🏢 {bu_full}  •  Headcount: {h_c:,}  •  Recorded Days: {r_d:,}  •  Present: {p_pct:.1f}%  •  Exceptions: {e_c:,}",
            text_color=ui.COLOR_TEXT,
        )

    def _on_row_leave(self):
        """Restore default navigation tip when mouse leaves row."""
        self.lbl_info.configure(
            text="Tip: Shift + MouseWheel to scroll columns horizontally  •  Hover row for full BU details",
            text_color=ui.COLOR_TEXT_DIM,
        )

    def _on_grid_box_configure(self, event):
        """Ensure canvases and scrollbars dynamically adapt when container width changes."""
        if getattr(self, "_last_grid_w", None) != event.width:
            self._last_grid_w = event.width
            self._sync_table_geometry()

    def _sync_table_geometry(self):
        """
        Synchronize canvas heights, widths, and scrollregions based on measured physical dimensions.
        Completely prevents vertical text clipping under any display scaling factor, auto-adjusts
        columns across the available width when expanded to eliminate dead space, and ensures
        horizontal scrollbar properly activates when columns exceed visible viewport.
        """
        self.update_idletasks()

        hdr_h = max(26, self.table_hdr_frame.winfo_reqheight())
        tot_h = max(28, self.total_frame.winfo_reqheight())

        hdr_w = self.table_hdr_frame.winfo_reqwidth()
        tot_w = self.total_frame.winfo_reqwidth()
        rows_w = self.rows_inner_frame.winfo_reqwidth()
        table_min_w = max(hdr_w, tot_w, rows_w, TOTAL_TABLE_WIDTH)

        vis_w = self.rows_canvas.winfo_width()
        table_real_w = max(vis_w, table_min_w) if vis_w > 10 else table_min_w

        # Ensure rows_inner_frame expands across child row frames
        self.rows_inner_frame.grid_columnconfigure(0, weight=1)

        # Update embedded canvas windows to table_real_w so all frames expand
        self.header_canvas.itemconfigure(self.header_window, width=table_real_w)
        self.rows_canvas.itemconfigure(self.rows_window, width=table_real_w)
        self.total_canvas.itemconfigure(self.total_window, width=table_real_w)

        # 1. Update Header Canvas & Spacer
        self.header_canvas.configure(height=hdr_h, scrollregion=(0, 0, table_real_w, hdr_h))
        self.header_spacer.configure(height=hdr_h, fg_color=ui.COLOR_INPUT_BG)

        # 2. Update Total Canvas & Spacer
        self.total_canvas.configure(height=tot_h, scrollregion=(0, 0, table_real_w, tot_h))
        self.total_spacer.configure(height=tot_h, fg_color="#18233C")

        # 3. Update Rows Canvas Viewport
        row_count = len(self._bu_data)
        visible_rows = min(8, max(4, row_count)) if row_count > 0 else 4
        canvas_h = visible_rows * 24
        req_rows_h = max(canvas_h, self.rows_inner_frame.winfo_reqheight())
        self.rows_canvas.configure(height=canvas_h, scrollregion=(0, 0, table_real_w, req_rows_h))

        # 4. Show/hide vertical scrollbar and spacers depending on row count
        if row_count > 8:
            self.v_scrollbar.grid(row=1, column=1, sticky="ns", padx=(2, 0))
            self.header_spacer.grid(row=0, column=1, sticky="ns")
            self.total_spacer.grid(row=2, column=1, sticky="ns")
        else:
            self.v_scrollbar.grid_remove()
            self.header_spacer.grid_remove()
            self.total_spacer.grid_remove()

        # 5. Show/hide horizontal scrollbar based on whether columns fit in visible viewport
        if vis_w > 10 and vis_w >= table_min_w:
            self.h_scrollbar.grid_remove()
            self.h_scrollbar_spacer.grid_remove()
        else:
            self.h_scrollbar.grid(row=3, column=0, sticky="ew", pady=(3, 2))
            if row_count > 8:
                self.h_scrollbar_spacer.grid(row=3, column=1, sticky="ns")
            else:
                self.h_scrollbar_spacer.grid_remove()

    def _configure_frame_columns(self, container: ctk.CTkFrame):
        container.grid_columnconfigure(0, minsize=TABLE_COLUMNS[0][2], weight=3)
        for idx in range(1, len(TABLE_COLUMNS)):
            container.grid_columnconfigure(idx, minsize=TABLE_COLUMNS[idx][2], weight=1)

    def update_data(self, bu_data: List[Dict[str, Any]], bu_total: Dict[str, Any]):
        self._bu_data = bu_data or []
        self._bu_total = bu_total or {}

        if not self._bu_data:
            self.grid_box.grid_remove()
            self.lbl_info.grid_remove()
            self.lbl_bu_count.configure(text="")
            self.lbl_empty.grid(row=1, column=0, pady=30)
            return

        self.lbl_empty.grid_remove()
        self.grid_box.grid()
        self.lbl_info.grid()
        bu_cnt = len(self._bu_data)
        bu_unit = "Business Unit" if bu_cnt == 1 else "Business Units"
        self.lbl_bu_count.configure(text=f"{bu_cnt} {bu_unit}")

        self._render_headers()
        self._render_rows()
        self._render_total()

        self._sync_table_geometry()

        # Reset horizontal scroll to left
        self._on_h_scroll("moveto", "0.0")

    def reset(self):
        self._bu_data = []
        self._bu_total = {}
        for child in self.table_hdr_frame.winfo_children():
            child.destroy()
        for child in self.rows_inner_frame.winfo_children():
            child.destroy()
        for child in self.total_frame.winfo_children():
            child.destroy()
        self.lbl_bu_count.configure(text="")
        self.lbl_info.grid_remove()
        self.grid_box.grid_remove()
        self.lbl_empty.grid(row=1, column=0, pady=30)

    def _render_headers(self):
        for child in self.table_hdr_frame.winfo_children():
            child.destroy()
        self._configure_frame_columns(self.table_hdr_frame)

        for idx, (col_id, title, col_w, anchor) in enumerate(TABLE_COLUMNS):
            lbl = ctk.CTkLabel(
                self.table_hdr_frame,
                text=title,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9, weight="bold"),
                text_color=ui.COLOR_TEXT_SEC,
                width=col_w,
                height=20,
                anchor=anchor,
            )
            lbl.grid(row=0, column=idx, sticky="nsew", padx=2, pady=3)
            lbl.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

    def _render_rows(self):
        for child in self.rows_inner_frame.winfo_children():
            child.destroy()

        row_count = len(self._bu_data)
        for row_idx, b in enumerate(self._bu_data):
            row_bg = "transparent" if row_idx % 2 == 0 else "#0D1424"
            row_box = ctk.CTkFrame(self.rows_inner_frame, fg_color=row_bg, corner_radius=2, height=24)
            row_box.grid(row=row_idx, column=0, sticky="ew", pady=1)
            self._configure_frame_columns(row_box)

            bu_name = b.get("business_unit", "")
            disp_name = bu_name if len(bu_name) <= 38 else bu_name[:35] + "..."

            hc = b.get("observed_headcount", 0)
            rec_days = b.get("recorded_employee_days", 0)
            pres_d = b.get("present_days", 0.0)
            pres_pct = b.get("present_pct", 0.0)
            lv_d = b.get("leave_days", 0.0)
            lv_pct = b.get("leave_pct", 0.0)
            wfh_d = b.get("wfh_days", 0.0)
            wfh_pct = b.get("wfh_pct", 0.0)
            od_d = b.get("od_days", 0.0)
            ab_d = b.get("absent_days", 0.0)
            excp_d = b.get("exception_days", 0)
            excp_rate = b.get("exception_rate_pct", 0.0)

            cells = [
                (disp_name, "w", ui.COLOR_TEXT, True),
                (f"{hc:,}", "e", ui.COLOR_TEXT, False),
                (f"{rec_days:,}", "e", ui.COLOR_TEXT, False),
                (_fmt_days(pres_d), "e", ui.COLOR_TEXT, False),
                (f"{pres_pct:.1f}%", "e", "#10B981", False),
                (_fmt_days(lv_d), "e", ui.COLOR_TEXT, False),
                (f"{lv_pct:.1f}%", "e", "#8B5CF6", False),
                (_fmt_days(wfh_d), "e", ui.COLOR_TEXT, False),
                (f"{wfh_pct:.1f}%", "e", "#6366F1", False),
                (_fmt_days(od_d), "e", ui.COLOR_TEXT, False),
                (_fmt_days(ab_d), "e", ui.COLOR_ERROR if ab_d > 0 else ui.COLOR_TEXT_SEC, False),
                (f"{excp_d:,}", "e", "#F43F5E" if excp_d > 0 else ui.COLOR_TEXT_SEC, False),
                (f"{excp_rate:.1f}%", "e", "#F43F5E" if excp_d > 0 else ui.COLOR_TEXT_SEC, False),
            ]

            row_box.bind("<Enter>", lambda e, rec=b: self._on_row_enter(rec))
            row_box.bind("<Leave>", lambda e: self._on_row_leave())
            row_box.bind("<MouseWheel>", self._on_rows_mousewheel)
            row_box.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

            for c_idx, (txt, anch, col, is_b) in enumerate(cells):
                col_w = TABLE_COLUMNS[c_idx][2]
                lbl = ctk.CTkLabel(
                    row_box,
                    text=txt,
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9, weight="bold" if is_b else "normal"),
                    text_color=col,
                    width=col_w,
                    height=20,
                    anchor=anch,
                )
                lbl.grid(row=0, column=c_idx, sticky="nsew", padx=2, pady=1)
                lbl.bind("<Enter>", lambda e, rec=b: self._on_row_enter(rec))
                lbl.bind("<Leave>", lambda e: self._on_row_leave())
                lbl.bind("<MouseWheel>", self._on_rows_mousewheel)
                lbl.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

    def _render_total(self):
        for child in self.total_frame.winfo_children():
            child.destroy()

        if not self._bu_total:
            return

        self._configure_frame_columns(self.total_frame)
        tot = self._bu_total
        tot_hc = tot.get("observed_headcount", 0)
        tot_rec = tot.get("recorded_employee_days", 0)
        tot_pres_d = tot.get("present_days", 0.0)
        tot_pres_pct = tot.get("present_pct", 0.0)
        tot_lv_d = tot.get("leave_days", 0.0)
        tot_lv_pct = tot.get("leave_pct", 0.0)
        tot_wfh_d = tot.get("wfh_days", 0.0)
        tot_wfh_pct = tot.get("wfh_pct", 0.0)
        tot_od_d = tot.get("od_days", 0.0)
        tot_ab_d = tot.get("absent_days", 0.0)
        tot_excp_d = tot.get("exception_days", 0)
        tot_excp_rate = tot.get("exception_rate_pct", 0.0)

        cells = [
            ("Total (Organization-Wide)", "w", ui.COLOR_TEXT),
            (f"{tot_hc:,}", "e", ui.COLOR_TEXT),
            (f"{tot_rec:,}", "e", ui.COLOR_TEXT),
            (_fmt_days(tot_pres_d), "e", ui.COLOR_TEXT),
            (f"{tot_pres_pct:.1f}%", "e", "#10B981"),
            (_fmt_days(tot_lv_d), "e", ui.COLOR_TEXT),
            (f"{tot_lv_pct:.1f}%", "e", "#8B5CF6"),
            (_fmt_days(tot_wfh_d), "e", ui.COLOR_TEXT),
            (f"{tot_wfh_pct:.1f}%", "e", "#6366F1"),
            (_fmt_days(tot_od_d), "e", ui.COLOR_TEXT),
            (_fmt_days(tot_ab_d), "e", ui.COLOR_ERROR if tot_ab_d > 0 else ui.COLOR_TEXT),
            (f"{tot_excp_d:,}", "e", "#F43F5E" if tot_excp_d > 0 else ui.COLOR_TEXT),
            (f"{tot_excp_rate:.1f}%", "e", "#F43F5E" if tot_excp_d > 0 else ui.COLOR_TEXT),
        ]

        for c_idx, (txt, anch, col) in enumerate(cells):
            col_w = TABLE_COLUMNS[c_idx][2]
            lbl = ctk.CTkLabel(
                self.total_frame,
                text=txt,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9, weight="bold"),
                text_color=col,
                width=col_w,
                height=20,
                anchor=anch,
            )
            lbl.grid(row=0, column=c_idx, sticky="nsew", padx=2, pady=3)
            lbl.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)


# ─────────────────────────────────────────────────────────────────────────────
# WorkforceDashboardView Component
# ─────────────────────────────────────────────────────────────────────────────

class WorkforceDashboardView(ctk.CTkFrame):
    """
    Main container frame for the Transformers 2.0 Workforce Intelligence Dashboard.
    Provides header with dataset status, future filter toolbar placeholder,
    horizontal 6-view navigation bar, and live Executive Overview KPI cards.
    """

    def __init__(self, master, app=None, **kwargs):
        super().__init__(master, fg_color="transparent", corner_radius=0, **kwargs)
        self.app = app
        self.active_view = "overview"
        self.tab_buttons: Dict[str, ctk.CTkButton] = {}
        self.view_containers: Dict[str, ctk.CTkScrollableFrame] = {}

        # Metric state & thread-safety tracking
        self._current_dataset_id: Optional[str] = None
        self._latest_job_id: int = 0
        self._is_loading_metrics: bool = False
        self._last_metrics_bundle: Optional[Dict[str, Any]] = None
        self._metrics_queue: queue.Queue = queue.Queue()
        self.kpi_cards: Dict[str, ExecutiveKPICard] = {}

        # Global Filter state & debounce tracking
        self._filter_state: Dict[str, Any] = {
            "date_range": None,
            "business_unit": None,
            "department": None,
            "manager": None,
            "employee": None,
            "date_preset": "All Dates",
        }
        self._filter_debounce_timer: Optional[str] = None
        self._full_dataset_dq_bundle: Optional[Dict[str, Any]] = None
        self._available_dates: List[date] = []
        self._emp_key_map: Dict[str, str] = {}
        self._emp_disp_map: Dict[str, str] = {}
        self._date_picker_dialog = None

        self.grid_rowconfigure(0, weight=0)  # Header + Metadata
        self.grid_rowconfigure(1, weight=0)  # Future Filters Placeholder
        self.grid_rowconfigure(2, weight=0)  # Horizontal Navigation Tabs
        self.grid_rowconfigure(3, weight=1)  # Content Area
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_filters_placeholder()
        self._build_tab_navigation()
        self._build_content_containers()

        # Initialize with overview
        self.select_view("overview")

    # ─────────────────────────────────────────────────────────────────────────
    # A. Header & Metadata Section
    # ─────────────────────────────────────────────────────────────────────────

    def _build_header(self):
        """Build the compact dashboard toolbar with dataset metadata and quick actions."""
        self.header_card = ui.create_card(self)
        self.header_card.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.header_card.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(self.header_card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=12, pady=5)
        inner.grid_columnconfigure(0, weight=0)
        inner.grid_columnconfigure(1, weight=1)
        inner.grid_columnconfigure(2, weight=0)
        inner.grid_columnconfigure(3, weight=0)

        # Left: Title
        lbl_title = ctk.CTkLabel(
            inner,
            text="Workforce Intelligence",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=18, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        )
        lbl_title.grid(row=0, column=0, sticky="w", padx=(0, 10))

        # Center: Metadata Badges Strip
        meta_strip = ctk.CTkFrame(inner, fg_color=ui.COLOR_INPUT_BG, corner_radius=6)
        meta_strip.grid(row=0, column=1, sticky="w", padx=(0, 10))

        # 1. Dataset Name
        f_ds = ctk.CTkFrame(meta_strip, fg_color="transparent")
        f_ds.pack(side="left", padx=(8, 10), pady=3)
        ctk.CTkLabel(
            f_ds, text="📄", font=ctk.CTkFont(size=11), text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 3))
        self.lbl_dataset_name = ctk.CTkLabel(
            f_ds, text="No dataset loaded", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_WARNING, anchor="w"
        )
        self.lbl_dataset_name.pack(side="left")
        ui.create_tooltip(self.lbl_dataset_name, "Active analytical dataset identity")

        # 2. Reporting Period
        f_per = ctk.CTkFrame(meta_strip, fg_color="transparent")
        f_per.pack(side="left", padx=(0, 10), pady=3)
        ctk.CTkLabel(
            f_per, text="📅", font=ctk.CTkFont(size=11), text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 3))
        self.lbl_period = ctk.CTkLabel(
            f_per, text="N/A", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT, anchor="w"
        )
        self.lbl_period.pack(side="left")

        # 3. Status
        f_stat = ctk.CTkFrame(meta_strip, fg_color="transparent")
        f_stat.pack(side="left", padx=(0, 8), pady=3)
        self.lbl_status_dot = ctk.CTkLabel(
            f_stat, text="●", font=ctk.CTkFont(size=11), text_color=ui.COLOR_WARNING
        )
        self.lbl_status_dot.pack(side="left", padx=(0, 3))
        self.lbl_status_text = ctk.CTkLabel(
            f_stat, text="Awaiting Ingestion", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_WARNING, anchor="w"
        )
        self.lbl_status_text.pack(side="left")
        ui.create_tooltip(self.lbl_status_text, "Active record and unique employee count")

        # 4. Data Quality Badge (Clickable to open DataQualityDetailDialog, placed at Column 2 for guaranteed visibility)
        self.f_dq = ctk.CTkFrame(
            inner,
            fg_color=ui.COLOR_CARD,
            corner_radius=6,
            cursor="hand2",
            border_width=1,
            border_color=ui.COLOR_BORDER,
        )
        self.f_dq.grid(row=0, column=2, sticky="e", padx=(4, 8))
        self.lbl_dq_info = ctk.CTkLabel(
            self.f_dq,
            text="DQ: Standard",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
            cursor="hand2",
        )
        self.lbl_dq_info.pack(side="left", padx=8, pady=2)
        self.f_dq.bind("<Button-1>", lambda e: self._show_dq_details_dialog())
        self.lbl_dq_info.bind("<Button-1>", lambda e: self._show_dq_details_dialog())
        ui.create_tooltip(self.lbl_dq_info, "Click to view Data Quality diagnostics and reconciliation details")

        # Right: Go to Upload Section button
        self.btn_go_upload = ui.create_secondary_button(
            inner,
            "📂 Upload",
            command=self._on_go_to_upload,
            width=90,
            height=28,
        )
        self.btn_go_upload.grid(row=0, column=3, sticky="e")

    def _on_go_to_upload(self):
        """Navigate user to the upload section to load/replace data."""
        if self.app and hasattr(self.app, "select_frame_by_name"):
            self.app.select_frame_by_name("analyse_upload")

    # ─────────────────────────────────────────────────────────────────────────
    # B. Global Filters Toolbar (Functional Step 29)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_filters_placeholder(self):
        """Build the functional, single-row compact global filter toolbar."""
        self.filter_card = ui.create_card(self)
        self.filter_card.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        inner = ctk.CTkFrame(self.filter_card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=10, pady=4)
        inner.grid_columnconfigure((1, 2, 3, 4, 5), weight=1)

        # Tag label
        ctk.CTkLabel(
            inner,
            text="Filters:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
        ).grid(row=0, column=0, padx=(2, 6), sticky="w")
        # 1. Date Range
        self.combo_date_range = ui.SearchableDropdown(
            inner,
            values=["All Dates"],
            height=28,
            placeholder="All Dates",
            command=self._on_date_range_selected,
        )
        self.combo_date_range.set("All Dates")
        self.combo_date_range.configure(state="disabled")
        self.combo_date_range.grid(row=0, column=1, sticky="ew", padx=3)

        # 2. Business Unit
        self.combo_bu = ui.SearchableDropdown(
            inner,
            values=["All Business Units"],
            height=28,
            placeholder="All Business Units",
            command=self._on_bu_selected,
        )
        self.combo_bu.set("All Business Units")
        self.combo_bu.configure(state="disabled")
        self.combo_bu.grid(row=0, column=2, sticky="ew", padx=3)

        # 3. Department
        self.combo_dept = ui.SearchableDropdown(
            inner,
            values=["All Departments"],
            height=28,
            placeholder="All Departments",
            command=self._on_dept_selected,
        )
        self.combo_dept.set("All Departments")
        self.combo_dept.configure(state="disabled")
        self.combo_dept.grid(row=0, column=3, sticky="ew", padx=3)

        # 4. Reporting Manager
        self.combo_manager = ui.SearchableDropdown(
            inner,
            values=["All Reporting Managers"],
            height=28,
            placeholder="All Reporting Managers",
            command=self._on_manager_selected,
        )
        self.combo_manager.set("All Reporting Managers")
        self.combo_manager.configure(state="disabled")
        self.combo_manager.grid(row=0, column=4, sticky="ew", padx=3)

        # 5. Employee
        self.combo_employee = ui.SearchableDropdown(
            inner,
            values=["All Employees"],
            height=28,
            placeholder="All Employees",
            command=self._on_employee_selected,
        )
        self.combo_employee.set("All Employees")
        self.combo_employee.configure(state="disabled")
        self.combo_employee.grid(row=0, column=5, sticky="ew", padx=3)

        # 6. Reset Filters Button
        self.btn_reset_filters = ctk.CTkButton(
            inner,
            text="Reset",
            state="disabled",
            height=28,
            width=65,
            fg_color=ui.COLOR_BTN_SEC,
            hover_color=ui.COLOR_NAV_HOVER,
            text_color=ui.COLOR_TEXT_DIM,
            corner_radius=6,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            command=self._on_reset_filters_clicked,
        )
        self.btn_reset_filters.grid(row=0, column=6, sticky="ew", padx=(3, 0))

    def _disable_filters(self):
        """Disable all filter controls when no valid dataset is active."""
        if hasattr(self, "combo_date_range"):
            self.combo_date_range.configure(state="normal")
            self.combo_date_range.set("All Dates")
            self.combo_date_range.configure(values=["All Dates"], state="disabled")
        if hasattr(self, "combo_bu"):
            self.combo_bu.configure(state="normal")
            self.combo_bu.set("All Business Units")
            self.combo_bu.configure(values=["All Business Units"], state="disabled")
        if hasattr(self, "combo_dept"):
            self.combo_dept.configure(state="normal")
            self.combo_dept.set("All Departments")
            self.combo_dept.configure(values=["All Departments"], state="disabled")
        if hasattr(self, "combo_manager"):
            self.combo_manager.configure(state="normal")
            self.combo_manager.set("All Reporting Managers")
            self.combo_manager.configure(values=["All Reporting Managers"], state="disabled")
        if hasattr(self, "combo_employee"):
            self.combo_employee.configure(state="normal")
            self.combo_employee.set("All Employees")
            self.combo_employee.configure(values=["All Employees"], state="disabled")
        if hasattr(self, "btn_reset_filters"):
            self.btn_reset_filters.configure(state="disabled", text_color=ui.COLOR_TEXT_DIM)

    def _populate_filters_from_snapshot(self, snap: AnalyticalSnapshot):
        """Populate initial filter choices from active snapshot dataset."""
        if not snap or not snap.is_valid():
            self._disable_filters()
            return

        df = snap.fact_df
        if df is None or len(df) == 0:
            self._disable_filters()
            return

        from workforce_intelligence.kpi_engine import ensure_clean_dataframe, get_effective_bu
        work_df = ensure_clean_dataframe(df)

        # 1. Dates
        dates = []
        if "_date" in work_df.columns:
            for d in work_df["_date"].dropna():
                if isinstance(d, datetime):
                    dates.append(d.date())
                elif isinstance(d, date):
                    dates.append(d)
                elif isinstance(d, str):
                    try:
                        parsed = tsa.parse_date_value(d)
                        if parsed:
                            dates.append(parsed)
                    except Exception:
                        pass
        self._available_dates = sorted(list(set(dates)))

        date_options = ["All Dates"]
        if self._available_dates:
            min_d = self._available_dates[0]
            max_d = self._available_dates[-1]
            span_days = (max_d - min_d).days + 1

            # Months observed
            months_seen = []
            for d in self._available_dates:
                m_str = d.strftime("%b %Y")
                if m_str not in months_seen:
                    months_seen.append(m_str)
            if len(months_seen) > 1:
                date_options.extend(months_seen)

            if span_days >= 7:
                date_options.append("Last 7 Days")
            if span_days >= 14:
                date_options.append("Last 14 Days")
            if span_days >= 30:
                date_options.append("Last 30 Days")

        date_options.append("Custom Range...")

        self.combo_date_range.configure(values=date_options, state="normal")
        cur_preset = self._filter_state.get("date_preset", "All Dates")
        self.combo_date_range.set(cur_preset)

        # 2. Business Units (using effective BU attribution)
        if "_eff_bu" in work_df.columns:
            bus = sorted([str(b).strip() for b in work_df["_eff_bu"].unique() if pd.notna(b) and str(b).strip() not in ("", "nan", "None")])
        else:
            bus = sorted([get_effective_bu(b, d) for b, d in zip(work_df["_bu"], work_df["_dept"])])
            bus = sorted(list(set(bus)))
        bu_options = ["All Business Units"] + [b for b in bus if b != "Unknown / Unassigned"]
        if "Unknown / Unassigned" in bus:
            bu_options.append("Unknown / Unassigned")

        self.combo_bu.configure(values=bu_options, state="normal")
        cur_bu = self._filter_state.get("business_unit")
        self.combo_bu.set(cur_bu if cur_bu else "All Business Units")

        # 3. Department, Manager, Employee based on current scope
        self._update_dependent_filter_options(changed_level="initial", work_df=work_df)

        self.btn_reset_filters.configure(state="normal", text_color=ui.COLOR_TEXT)

    def _update_dependent_filter_options(self, changed_level: str = "initial", work_df: Optional[pd.DataFrame] = None):
        """Update dependent dropdown options (Department, Manager, Employee) based on higher-level active filters."""
        if work_df is None:
            snap = snapshot_service.get_active_snapshot()
            if not snap or not snap.is_valid():
                return
            from workforce_intelligence.kpi_engine import ensure_clean_dataframe
            work_df = ensure_clean_dataframe(snap.fact_df)

        sub_df = work_df

        # Filter by active date range
        dr = self._filter_state.get("date_range")
        if dr and len(dr) == 2 and "_date" in sub_df.columns:
            s_d, e_d = dr
            sub_df = sub_df[sub_df["_date"].apply(lambda d: s_d <= d <= e_d if isinstance(d, (date, datetime)) else False)]

        # Filter by active Business Unit
        sel_bu = self._filter_state.get("business_unit")
        if sel_bu and sel_bu not in ("All", "All Business Units"):
            bu_lower = str(sel_bu).strip().lower()
            if bu_lower in ("unknown", "unknown / unassigned"):
                sub_df = sub_df[sub_df["_eff_bu"].astype(str).str.strip().str.lower().isin(("unknown / unassigned", "unknown", "", "nan", "none"))]
            else:
                sub_df = sub_df[
                    (sub_df["_eff_bu"].astype(str).str.strip().str.lower() == bu_lower) |
                    (sub_df["_bu"].astype(str).str.strip().str.lower() == bu_lower)
                ]

        # Departments in this scope
        depts = sorted(list(set(
            str(d).strip() for d in sub_df["_dept"].dropna().unique()
            if str(d).strip() not in ("", "nan", "None")
        )))
        dept_options = ["All Departments"] + [d for d in depts if d != "Unknown / Unassigned"]
        if "Unknown / Unassigned" in depts:
            dept_options.append("Unknown / Unassigned")

        cur_dept = self._filter_state.get("department")
        if cur_dept and cur_dept not in depts and cur_dept not in ("All", "All Departments"):
            self._filter_state["department"] = None
            cur_dept = None

        self.combo_dept.configure(values=dept_options, state="normal")
        self.combo_dept.set(cur_dept if cur_dept else "All Departments")

        # Filter further by active Department
        sel_dept = self._filter_state.get("department")
        if sel_dept and sel_dept not in ("All", "All Departments"):
            dept_lower = str(sel_dept).strip().lower()
            if dept_lower in ("unknown", "unknown / unassigned"):
                sub_df = sub_df[sub_df["_dept"].isna() | sub_df["_dept"].astype(str).str.strip().str.lower().isin(("unknown / unassigned", "unknown", "", "nan", "none"))]
            else:
                sub_df = sub_df[sub_df["_dept"].astype(str).str.strip().str.lower() == dept_lower]

        # Managers in this scope
        mgrs = sorted(list(set(
            str(m).strip() for m in sub_df["_rm"].dropna().unique()
            if str(m).strip() not in ("", "nan", "None")
        )))
        mgr_options = ["All Reporting Managers"] + [m for m in mgrs if m != "Unknown / Unassigned"]
        if "Unknown / Unassigned" in mgrs:
            mgr_options.append("Unknown / Unassigned")

        cur_mgr = self._filter_state.get("manager")
        if cur_mgr and cur_mgr not in mgrs and cur_mgr not in ("All", "All Reporting Managers"):
            self._filter_state["manager"] = None
            cur_mgr = None

        self.combo_manager.configure(values=mgr_options, state="normal")
        self.combo_manager.set(cur_mgr if cur_mgr else "All Reporting Managers")

        # Filter further by active Manager
        sel_mgr = self._filter_state.get("manager")
        if sel_mgr and sel_mgr not in ("All", "All Reporting Managers"):
            mgr_lower = str(sel_mgr).strip().lower()
            if mgr_lower in ("unknown", "unknown / unassigned"):
                sub_df = sub_df[sub_df["_rm"].isna() | sub_df["_rm"].astype(str).str.strip().str.lower().isin(("unknown / unassigned", "unknown", "", "nan", "none"))]
            else:
                sub_df = sub_df[sub_df["_rm"].astype(str).str.strip().str.lower() == mgr_lower]

        # Employees in this scope
        emp_pairs = []
        if "_emp_num" in sub_df.columns:
            for _, r in sub_df[["_emp_num", "_emp_name"]].drop_duplicates().iterrows():
                e_id = str(r["_emp_num"]).strip()
                e_nm = str(r["_emp_name"]).strip() if pd.notna(r["_emp_name"]) else e_id
                if e_id and e_id not in ("", "nan", "None"):
                    if e_nm and e_nm != e_id and e_nm.lower() not in ("nan", "none"):
                        emp_pairs.append((e_id, f"{e_id} — {e_nm}"))
                    else:
                        emp_pairs.append((e_id, e_id))

        emp_pairs.sort(key=lambda x: x[0])
        self._emp_key_map = {disp: eid for eid, disp in emp_pairs}
        self._emp_disp_map = {eid: disp for eid, disp in emp_pairs}

        emp_display_options = ["All Employees"] + [disp for _, disp in emp_pairs]

        cur_emp = self._filter_state.get("employee")
        if cur_emp and cur_emp not in self._emp_disp_map and cur_emp not in ("All", "All Employees"):
            self._filter_state["employee"] = None
            cur_emp = None

        self.combo_employee.configure(values=emp_display_options, state="normal")
        cur_disp = self._emp_disp_map.get(cur_emp, "All Employees") if cur_emp else "All Employees"
        self.combo_employee.set(cur_disp)

    def _on_date_range_selected(self, val: str):
        val = val.strip()
        if val == "All Dates":
            self._filter_state["date_range"] = None
            self._filter_state["date_preset"] = "All Dates"
            if self._available_dates:
                self.lbl_period.configure(text=f"{self._available_dates[0]} to {self._available_dates[-1]}")
            self._update_dependent_filter_options(changed_level="date")
            self._schedule_metrics_load()
        elif val == "Custom Range...":
            self._show_date_range_picker_dialog()
        elif val == "Last 7 Days" and self._available_dates:
            max_d = self._available_dates[-1]
            start_d = max_d - timedelta(days=6)
            self._filter_state["date_range"] = (start_d, max_d)
            self._filter_state["date_preset"] = "Last 7 Days"
            self.lbl_period.configure(text=f"{start_d.isoformat()} to {max_d.isoformat()}")
            self._update_dependent_filter_options(changed_level="date")
            self._schedule_metrics_load()
        elif val == "Last 14 Days" and self._available_dates:
            max_d = self._available_dates[-1]
            start_d = max_d - timedelta(days=13)
            self._filter_state["date_range"] = (start_d, max_d)
            self._filter_state["date_preset"] = "Last 14 Days"
            self.lbl_period.configure(text=f"{start_d.isoformat()} to {max_d.isoformat()}")
            self._update_dependent_filter_options(changed_level="date")
            self._schedule_metrics_load()
        elif val == "Last 30 Days" and self._available_dates:
            max_d = self._available_dates[-1]
            start_d = max_d - timedelta(days=29)
            self._filter_state["date_range"] = (start_d, max_d)
            self._filter_state["date_preset"] = "Last 30 Days"
            self.lbl_period.configure(text=f"{start_d.isoformat()} to {max_d.isoformat()}")
            self._update_dependent_filter_options(changed_level="date")
            self._schedule_metrics_load()
        else:
            # Check if val is an observed month, e.g. "Sep 2026"
            matched_dates = [d for d in self._available_dates if d.strftime("%b %Y") == val]
            if matched_dates:
                start_d = matched_dates[0]
                end_d = matched_dates[-1]
                self._filter_state["date_range"] = (start_d, end_d)
                self._filter_state["date_preset"] = val
                self.lbl_period.configure(text=f"{start_d.isoformat()} to {end_d.isoformat()}")
                self._update_dependent_filter_options(changed_level="date")
                self._schedule_metrics_load()
            else:
                self._filter_state["date_range"] = None
                self._filter_state["date_preset"] = "All Dates"
                self._update_dependent_filter_options(changed_level="date")
                self._schedule_metrics_load()

    def _show_date_range_picker_dialog(self):
        if hasattr(self, "_date_picker_dialog") and self._date_picker_dialog is not None and self._date_picker_dialog.winfo_exists():
            self._date_picker_dialog.lift()
            self._date_picker_dialog.focus_force()
            return

        cur_dr = self._filter_state.get("date_range")
        cur_s = cur_dr[0] if cur_dr else None
        cur_e = cur_dr[1] if cur_dr else None

        def _on_custom_apply(start_d: date, end_d: date):
            self._filter_state["date_range"] = (start_d, end_d)
            self._filter_state["date_preset"] = "Custom Range"
            self.combo_date_range.set(f"{start_d.isoformat()} to {end_d.isoformat()}")
            self.lbl_period.configure(text=f"{start_d.isoformat()} to {end_d.isoformat()}")
            self._update_dependent_filter_options(changed_level="date")
            self._schedule_metrics_load()

        self._date_picker_dialog = DateRangePickerDialog(
            parent_view=self,
            available_dates=self._available_dates,
            current_start=cur_s,
            current_end=cur_e,
            on_apply=_on_custom_apply,
        )

    def _on_bu_selected(self, val: str):
        val = str(val).strip()
        if hasattr(self, "combo_bu"):
            self.combo_bu.set(val)
        if val in ("All Business Units", "All", ""):
            self._filter_state["business_unit"] = None
        else:
            self._filter_state["business_unit"] = val
        self._update_dependent_filter_options(changed_level="bu")
        self._schedule_metrics_load()

    def _on_dept_selected(self, val: str):
        val = str(val).strip()
        if hasattr(self, "combo_dept"):
            self.combo_dept.set(val)
        if val in ("All Departments", "All", ""):
            self._filter_state["department"] = None
        else:
            self._filter_state["department"] = val
        self._update_dependent_filter_options(changed_level="dept")
        self._schedule_metrics_load()

    def _on_manager_selected(self, val: str):
        val = str(val).strip()
        if hasattr(self, "combo_manager"):
            self.combo_manager.set(val)
        if val in ("All Reporting Managers", "All Managers", "All", ""):
            self._filter_state["manager"] = None
        else:
            self._filter_state["manager"] = val
        self._update_dependent_filter_options(changed_level="manager")
        self._schedule_metrics_load()

    def _on_employee_selected(self, val: str):
        val = str(val).strip()
        if hasattr(self, "combo_employee"):
            self.combo_employee.set(val)
        if val in ("All Employees", "All", ""):
            self._filter_state["employee"] = None
        else:
            emp_id = getattr(self, "_emp_key_map", {}).get(val, val)
            if " — " in emp_id:
                emp_id = emp_id.split(" — ")[0].strip()
            self._filter_state["employee"] = emp_id
        self._schedule_metrics_load()

    def _on_reset_filters_clicked(self):
        """Reset all active filters and restore full reporting scope."""
        self._filter_state = {
            "date_range": None,
            "business_unit": None,
            "department": None,
            "manager": None,
            "employee": None,
            "date_preset": "All Dates",
        }
        if hasattr(self, "combo_date_range"):
            self.combo_date_range.set("All Dates")
        if hasattr(self, "combo_bu"):
            self.combo_bu.set("All Business Units")
        if hasattr(self, "combo_dept"):
            self.combo_dept.set("All Departments")
        if hasattr(self, "combo_manager"):
            self.combo_manager.set("All Reporting Managers")
        if hasattr(self, "combo_employee"):
            self.combo_employee.set("All Employees")
        snap = snapshot_service.get_active_snapshot()
        if snap and snap.is_valid():
            self._populate_filters_from_snapshot(snap)
            min_d = snap.metadata.get("min_date", "N/A")
            max_d = snap.metadata.get("max_date", "N/A")
            if hasattr(self, "lbl_period"):
                self.lbl_period.configure(text=f"{min_d} to {max_d}")
        self._load_overview_metrics()

    def _schedule_metrics_load(self):
        """Debounce metric loading by 150ms to prevent rapid consecutive recalculations."""
        if hasattr(self, "_filter_debounce_timer") and self._filter_debounce_timer is not None:
            try:
                self.after_cancel(self._filter_debounce_timer)
            except Exception:
                pass
        self._filter_debounce_timer = self.after(150, self._load_overview_metrics)

    def _update_active_scope_label(self):
        """Update the active scope label beneath the tab navigation."""
        if not hasattr(self, "lbl_active_scope"):
            return
        parts = []
        d_val = self.combo_date_range.get() if hasattr(self, "combo_date_range") else "All Dates"
        bu_val = self.combo_bu.get() if hasattr(self, "combo_bu") else "All Business Units"
        dept_val = self.combo_dept.get() if hasattr(self, "combo_dept") else "All Departments"
        mgr_val = self.combo_manager.get() if hasattr(self, "combo_manager") else "All Reporting Managers"
        emp_val = self.combo_employee.get() if hasattr(self, "combo_employee") else "All Employees"

        if d_val and d_val not in ("All Dates", ""):
            parts.append(d_val)
        else:
            parts.append("All Dates")

        if bu_val and bu_val not in ("All Business Units", "All", ""):
            parts.append(bu_val)
        if dept_val and dept_val not in ("All Departments", "All", ""):
            parts.append(dept_val)
        if mgr_val and mgr_val not in ("All Reporting Managers", "All Managers", "All", ""):
            parts.append(mgr_val)
        if emp_val and emp_val not in ("All Employees", "All", ""):
            parts.append(emp_val)

        if len(parts) == 1:
            scope_desc = f"Complete Active Population ({parts[0]})"
        else:
            scope_desc = " • ".join(parts)
        self.lbl_active_scope.configure(
            text=f"Executive Overview • {scope_desc}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # C. Horizontal Navigation Bar (6 Views)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_tab_navigation(self):
        """Build the compact horizontal navigation bar containing exactly the six views."""
        self.nav_card = ctk.CTkFrame(
            self,
            fg_color=ui.COLOR_CARD,
            border_width=1,
            border_color=ui.COLOR_BORDER,
            corner_radius=6,
            height=36,
        )
        self.nav_card.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.nav_card.grid_columnconfigure(tuple(range(len(VIEW_KEYS))), weight=1)

        for idx, key in enumerate(VIEW_KEYS):
            cfg = VIEW_CONFIGS[key]
            text = f"{cfg['icon']}  {cfg['tab_title']}"
            btn = ctk.CTkButton(
                self.nav_card,
                text=text,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="normal"),
                height=30,
                corner_radius=5,
                fg_color="transparent",
                hover_color=ui.COLOR_NAV_HOVER,
                text_color=ui.COLOR_TEXT_SEC,
                command=lambda k=key: self.select_view(k),
            )
            btn.grid(row=0, column=idx, padx=2, pady=3, sticky="ew")
            self.tab_buttons[key] = btn

    # ─────────────────────────────────────────────────────────────────────────
    # D. Reusable View Containers
    # ─────────────────────────────────────────────────────────────────────────

    def _build_content_containers(self):
        """Create and register the six view containers."""
        self.content_area = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.content_area.grid(row=3, column=0, sticky="nsew")
        self.content_area.grid_rowconfigure(0, weight=1)
        self.content_area.grid_columnconfigure(0, weight=1)

        for key in VIEW_KEYS:
            container = ctk.CTkScrollableFrame(self.content_area, fg_color="transparent")
            container.grid_columnconfigure(0, weight=1)
            if key == "overview":
                self._build_overview_content(container)
            else:
                self._populate_view_placeholder(container, key)
            self.view_containers[key] = container

    def _populate_view_placeholder(self, parent: ctk.CTkScrollableFrame, key: str):
        """Populate initial view content with title, description, and clear placeholder."""
        cfg = VIEW_CONFIGS[key]

        hdr = ui.create_page_header(parent, cfg["title"], cfg["subtitle"])
        hdr.grid(row=0, column=0, sticky="ew", pady=(4, 16))

        card = ui.create_card(parent)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        card.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=24, pady=24)
        inner.grid_columnconfigure(0, weight=1)

        badge_row = ctk.CTkFrame(inner, fg_color="transparent")
        badge_row.grid(row=0, column=0, sticky="w", pady=(0, 12))

        lbl_icon = ctk.CTkLabel(
            badge_row,
            text=cfg["icon"],
            font=ctk.CTkFont(size=24),
            text_color=ui.COLOR_ACCENT,
        )
        lbl_icon.pack(side="left", padx=(0, 12))

        lbl_badge = ctk.CTkLabel(
            badge_row,
            text=cfg["badge"],
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            fg_color=ui.COLOR_NAV_ACTIVE,
            text_color=ui.COLOR_ACCENT_HOVER,
            corner_radius=4,
            padx=10,
            pady=4,
        )
        lbl_badge.pack(side="left")

        lbl_main = ctk.CTkLabel(
            inner,
            text=f"📌 {cfg['placeholder_text']}",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        )
        lbl_main.grid(row=1, column=0, sticky="w", pady=(0, 8))

        lbl_expl = ctk.CTkLabel(
            inner,
            text="This screen container is ready for analytical widget integration in subsequent development steps.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        lbl_expl.grid(row=2, column=0, sticky="w", pady=(0, 16))

        scope_box = ctk.CTkFrame(inner, fg_color=ui.COLOR_INPUT_BG, corner_radius=8)
        scope_box.grid(row=3, column=0, sticky="ew")
        scope_box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            scope_box,
            text="PLANNED ANALYTICAL CAPABILITIES",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            scope_box,
            text=cfg["future_scope"],
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 14))

    # ─────────────────────────────────────────────────────────────────────────
    # E. Executive Overview: Live 9 KPI Cards & State Management
    # ─────────────────────────────────────────────────────────────────────────

    def _build_overview_content(self, parent: ctk.CTkScrollableFrame):
        """Construct the live Executive Overview view structure."""
        # 1. Compact Scope & Status Indicator Strip
        self.scope_strip = ctk.CTkFrame(parent, fg_color="transparent")
        self.scope_strip.grid(row=0, column=0, sticky="ew", pady=(2, 4))
        self.scope_strip.grid_columnconfigure(0, weight=1)

        self.lbl_active_scope = ctk.CTkLabel(
            self.scope_strip,
            text="Executive Overview • Complete Active Population (All Business Units • All Dates)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        self.lbl_active_scope.grid(row=0, column=0, sticky="w", padx=2)

        # 2. State Containers (Empty, Loading, Error, KPI Grid)
        # 2A. Empty State Container
        self.overview_empty_frame = ui.create_card(parent)
        self.overview_empty_frame.grid_columnconfigure(0, weight=1)
        e_inner = ctk.CTkFrame(self.overview_empty_frame, fg_color="transparent")
        e_inner.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        e_inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            e_inner, text="⚠️", font=ctk.CTkFont(size=22), text_color=ui.COLOR_WARNING
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            e_inner,
            text="No workforce dataset loaded. Upload a dataset to view Executive Overview metrics.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        ).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(
            e_inner,
            text="Executive overview metrics require an ingested performance dataset or attendance logs.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        ).pack(anchor="w", pady=(0, 10))

        ui.create_secondary_button(
            e_inner,
            "📂 Go to Upload Section",
            command=self._on_go_to_upload,
            width=160,
            height=28,
        ).pack(anchor="w")

        # 2B. Loading State Container
        self.overview_loading_frame = ui.create_card(parent)
        self.overview_loading_frame.grid_columnconfigure(0, weight=1)
        l_inner = ctk.CTkFrame(self.overview_loading_frame, fg_color="transparent")
        l_inner.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        l_inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            l_inner,
            text="⏳ Calculating Executive Overview metrics...",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))
        self.overview_prog = ctk.CTkProgressBar(
            l_inner, mode="indeterminate", height=3, corner_radius=2,
            fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT,
        )
        self.overview_prog.pack(fill="x")
        self.overview_prog.set(0)

        # 2C. Error State Container
        self.overview_error_frame = ui.create_card(parent)
        self.overview_error_frame.grid_columnconfigure(0, weight=1)
        err_inner = ctk.CTkFrame(self.overview_error_frame, fg_color="transparent")
        err_inner.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        err_inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            err_inner,
            text="❌ Failed to calculate Executive Overview metrics",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_ERROR,
            anchor="w",
        ).pack(anchor="w", pady=(0, 2))
        self.lbl_error_msg = ctk.CTkLabel(
            err_inner,
            text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        self.lbl_error_msg.pack(anchor="w")

        # 2D. Live 10-Card KPI Grid Frame
        self.overview_kpi_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.overview_kpi_frame.grid_columnconfigure(0, weight=1)

        # ── Row 1: 5 Cards (Uniform columns 0–4) ──
        row1_frame = ctk.CTkFrame(self.overview_kpi_frame, fg_color="transparent")
        row1_frame.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        row1_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="kpi_r1")
        row1_frame.grid_rowconfigure(0, weight=1)

        card_configs_r1 = [
            ("kpi_1_emp_hc", "1. EMP HC", "#3B82F6", "employees", "Observed Headcount"),
            ("kpi_2_attendance_days", "2. ATTENDANCE DAYS", "#06B6D4", "days", "Distinct recorded employee-days"),
            ("kpi_3_present", "3. PRESENT", "#10B981", "days", "Physical attendance days"),
            ("kpi_4_od", "4. ON DUTY", "#0EA5E9", "days", "Official duty assignments"),
            ("kpi_5_leave", "5. LEAVE", "#8B5CF6", "days", "Quantity-weighted leave days"),
        ]

        for col, (cid, title, color, unit, tip) in enumerate(card_configs_r1):
            card = ExecutiveKPICard(
                row1_frame,
                card_id=cid,
                title=title,
                accent_color=color,
                default_unit=unit,
                tooltip_text=tip,
            )
            card.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)
            self.kpi_cards[cid] = card

        # ── Row 2: 5 Cards (Uniform columns 0–4) ──
        row2_frame = ctk.CTkFrame(self.overview_kpi_frame, fg_color="transparent")
        row2_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        row2_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="kpi_r2")
        row2_frame.grid_rowconfigure(0, weight=1)

        card_configs_r2 = [
            ("kpi_6_wfh", "6. WFH", "#6366F1", "days", "Work from home days"),
            ("kpi_7_holiday", "7. HOLIDAY", "#F59E0B", "days", "Recognized organization holidays"),
            ("kpi_8_week_off", "8. WEEK OFF", "#94A3B8", "days", "Scheduled weekly rest days"),
            ("kpi_absent", "9. ABSENT", "#EF4444", "days", "Recorded employee absence days"),
            ("kpi_9_attendance_exceptions", "10. ATTENDANCE EXCEPTIONS", "#F43F5E", "days", "Regularized attendance exceptions"),
        ]

        for col, (cid, title, color, unit, tip) in enumerate(card_configs_r2):
            card = ExecutiveKPICard(
                row2_frame,
                card_id=cid,
                title=title,
                accent_color=color,
                default_unit=unit,
                tooltip_text=tip,
            )
            card.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)
            self.kpi_cards[cid] = card

        # ── Reconciliation & Composition Transparency Card ──
        self.recon_card = ui.create_card(self.overview_kpi_frame)
        self.recon_card.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        self.recon_card.grid_columnconfigure(0, weight=1)

        r_inner = ctk.CTkFrame(self.recon_card, fg_color="transparent")
        r_inner.grid(row=0, column=0, sticky="ew", padx=10, pady=4)
        r_inner.grid_columnconfigure(1, weight=1)

        self.lbl_recon_icon = ctk.CTkLabel(
            r_inner, text="✓", font=ctk.CTkFont(size=14, weight="bold"), text_color=ui.COLOR_SUCCESS, width=18
        )
        self.lbl_recon_icon.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 6), pady=(1, 0))

        self.lbl_recon_title = ctk.CTkLabel(
            r_inner,
            text="Complete Additive Attendance Composition (100.0% Reconciled)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_SUCCESS,
            anchor="w",
            justify="left",
            wraplength=600,
        )
        self.lbl_recon_title.grid(row=0, column=1, sticky="ew")

        self.lbl_recon_desc = ctk.CTkLabel(
            r_inner,
            text="All recorded attendance days are reconciled across Present, OD, Leave, WFH, Holiday, Week Off, and Absent.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
            justify="left",
            wraplength=600,
        )
        self.lbl_recon_desc.grid(row=1, column=1, sticky="ew", pady=(0, 0))

        self.recon_card.bind("<Configure>", self._on_recon_card_configure)

        # ── Middle Row: 2 Analytical Visualizations Side-by-Side ──
        self.charts_row_frame = ctk.CTkFrame(self.overview_kpi_frame, fg_color="transparent")
        self.charts_row_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 5))
        self.charts_row_frame.grid_columnconfigure((0, 1), weight=1, uniform="overview_charts")
        self.charts_row_frame.grid_rowconfigure(0, weight=1)

        self.comp_widget = AttendanceCompositionWidget(self.charts_row_frame)
        self.comp_widget.grid(row=0, column=0, sticky="nsew", padx=(0, 3), pady=0)

        self.trend_widget = DailyAttendanceTrendWidget(self.charts_row_frame)
        self.trend_widget.grid(row=0, column=1, sticky="nsew", padx=(3, 0), pady=0)

        # ── Bottom Row: Business Unit Comparison Table ──
        self.bu_table_frame = ctk.CTkFrame(self.overview_kpi_frame, fg_color="transparent")
        self.bu_table_frame.grid(row=4, column=0, sticky="nsew", pady=(0, 6))
        self.bu_table_frame.grid_columnconfigure(0, weight=1)

        self.bu_table_widget = BusinessUnitComparisonTableWidget(self.bu_table_frame)
        self.bu_table_widget.grid(row=0, column=0, sticky="nsew")

        # Initial state: Empty
        self._set_overview_state("empty")

    def _on_recon_card_configure(self, event):
        w = event.width
        if abs(w - getattr(self, "_last_recon_w", 0)) < 4:
            return
        self._last_recon_w = w
        scaling = self.recon_card._get_widget_scaling() if hasattr(self.recon_card, "_get_widget_scaling") else 1.0
        unscaled_w = w / (scaling if scaling > 0 else 1.0)
        wrap_w = max(200, int(unscaled_w - 45))
        if hasattr(self, "lbl_recon_title"):
            self.lbl_recon_title.configure(wraplength=wrap_w)
        if hasattr(self, "lbl_recon_desc"):
            self.lbl_recon_desc.configure(wraplength=wrap_w)

    def _set_overview_state(self, state: str, message: str = ""):
        """Switch visibility between empty, loading, error, and ready states."""
        if state != "ready":
            if hasattr(self, "comp_widget"):
                self.comp_widget.reset()
            if hasattr(self, "trend_widget"):
                self.trend_widget.reset()
            if hasattr(self, "bu_table_widget"):
                self.bu_table_widget.reset()

        if state == "empty":
            self.overview_empty_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
            self.overview_loading_frame.grid_remove()
            self.overview_error_frame.grid_remove()
            self.overview_kpi_frame.grid_remove()
            self.overview_prog.stop()
            self._current_bundle = {}
        elif state == "loading":
            self.overview_loading_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
            self.overview_empty_frame.grid_remove()
            self.overview_error_frame.grid_remove()
            self.overview_kpi_frame.grid_remove()
            self.overview_prog.start()
        elif state == "error":
            self.overview_error_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
            self.lbl_error_msg.configure(text=message)
            self.overview_empty_frame.grid_remove()
            self.overview_loading_frame.grid_remove()
            self.overview_kpi_frame.grid_remove()
            self.overview_prog.stop()
        elif state == "ready":
            self.overview_kpi_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
            self.overview_empty_frame.grid_remove()
            self.overview_loading_frame.grid_remove()
            self.overview_error_frame.grid_remove()
            self.overview_prog.stop()

    def _load_overview_metrics(self):
        """Asynchronously compute Executive Overview metrics in a worker thread."""
        snap = snapshot_service.get_active_snapshot()
        if not snap or not snap.is_valid():
            self._set_overview_state("empty")
            return

        self._latest_job_id += 1
        job_id = self._latest_job_id
        self._is_loading_metrics = True
        self._set_overview_state("loading")

        dataset_id = getattr(snap, "dataset_id", snap.key)

        bu = self._filter_state.get("business_unit")
        dept = self._filter_state.get("department")
        mgr = self._filter_state.get("manager")
        emp = self._filter_state.get("employee")
        dr = self._filter_state.get("date_range")

        def _worker(jid: int, d_id: str, q: queue.Queue, b=bu, d=dept, m=mgr, e=emp, r=dr):
            try:
                bundle = workforce_bridge.get_workforce_metrics(
                    business_unit=b,
                    department=d,
                    manager=m,
                    employee=e,
                    date_range=r,
                )
                q.put(("success", bundle, jid, d_id))
            except Exception as err:
                q.put(("error", str(err), jid, d_id))

        threading.Thread(
            target=_worker,
            args=(job_id, dataset_id, self._metrics_queue),
            daemon=True,
        ).start()

        # Begin main-thread queue polling
        self._poll_metrics_queue(job_id)

    def _poll_metrics_queue(self, job_id: int):
        """Poll the calculation queue on the main UI thread via after()."""
        if job_id != self._latest_job_id:
            return  # Stale job; ignore

        try:
            while True:
                msg_type, payload, msg_job_id, msg_dataset_id = self._metrics_queue.get_nowait()
                if msg_job_id == self._latest_job_id:
                    if msg_type == "success":
                        self._on_metrics_calc_success(payload, msg_job_id, msg_dataset_id)
                    else:
                        self._on_metrics_calc_error(payload, msg_job_id)
                    return
        except queue.Empty:
            if self._is_loading_metrics and job_id == self._latest_job_id:
                try:
                    self.after(30, lambda: self._poll_metrics_queue(job_id))
                except Exception:
                    pass

    def _on_metrics_calc_success(self, bundle: Dict[str, Any], job_id: int, dataset_id: str):
        """Handle successful KPI calculation on the main UI thread."""
        if job_id != self._latest_job_id:
            return  # Stale completion from older job; ignore

        self._is_loading_metrics = False
        self._current_dataset_id = dataset_id
        self._last_metrics_bundle = bundle
        self._render_overview_kpis(bundle)
        self._set_overview_state("ready")

    def _on_metrics_calc_error(self, error_msg: str, job_id: int):
        """Handle calculation failure on the main UI thread."""
        if job_id != self._latest_job_id:
            return  # Stale completion from older job; ignore

        self._is_loading_metrics = False
        self._set_overview_state("error", error_msg)

    def _render_overview_kpis(self, bundle: Dict[str, Any]):
        """Populate the 10 KPI cards and reconciliation status card from bundle."""
        if not bundle:
            return

        self._update_active_scope_label()

        # 1. EMP HC
        emp_hc = bundle.get("kpi_1_emp_hc", 0)
        hc_unit = "employee" if emp_hc == 1 else "employees"
        self.kpi_cards["kpi_1_emp_hc"].update_values(
            primary=f"{emp_hc:,}",
            secondary="Observed Headcount",
            note=f"Distinct observed {hc_unit} (not roster)",
        )

        # 2. Attendance Days
        att_days = bundle.get("kpi_2_attendance_days", 0)
        att_unit = "day" if att_days == 1 else "days"
        self.kpi_cards["kpi_2_attendance_days"].update_values(
            primary=f"{att_days:,} {att_unit}",
            secondary="100.0% of recorded period",
            note="Distinct employee-day records",
        )

        # 3. Present
        q_pres = bundle.get("kpi_3_present_days", 0.0)
        pct_pres = bundle.get("kpi_3_present_pct", 0.0)
        self.kpi_cards["kpi_3_present"].update_values(
            primary=_fmt_days(q_pres),
            secondary=f"{pct_pres:.1f}% of recorded days",
            note="Physical attendance days (inc. single swipes)",
        )

        # 4. On Duty
        q_od = bundle.get("kpi_4_od_days", 0.0)
        pct_od = bundle.get("kpi_4_od_pct", 0.0)
        self.kpi_cards["kpi_4_od"].update_values(
            primary=_fmt_days(q_od),
            secondary=f"{pct_od:.1f}% of recorded days",
            note="Official duty assignments",
        )

        # 5. Leave
        q_leave = bundle.get("kpi_5_leave_days", 0.0)
        pct_leave = bundle.get("kpi_5_leave_pct", 0.0)
        self.kpi_cards["kpi_5_leave"].update_values(
            primary=_fmt_days(q_leave),
            secondary=f"{pct_leave:.1f}% of recorded days",
            note="Quantity-weighted leave days",
        )

        # 6. WFH
        q_wfh = bundle.get("kpi_6_wfh_days", 0.0)
        pct_wfh = bundle.get("kpi_6_wfh_pct", 0.0)
        self.kpi_cards["kpi_6_wfh"].update_values(
            primary=_fmt_days(q_wfh),
            secondary=f"{pct_wfh:.1f}% of recorded days",
            note="Work from home days",
        )

        # 7. Holiday
        q_hol = bundle.get("kpi_7_holiday_days", 0.0)
        pct_hol = bundle.get("kpi_7_holiday_pct", 0.0)
        self.kpi_cards["kpi_7_holiday"].update_values(
            primary=_fmt_days(q_hol),
            secondary=f"{pct_hol:.1f}% of recorded days",
            note="Recognized organization holidays",
        )

        # 8. Week Off
        q_wo = bundle.get("kpi_8_week_off_days", 0.0)
        pct_wo = bundle.get("kpi_8_week_off_pct", 0.0)
        self.kpi_cards["kpi_8_week_off"].update_values(
            primary=_fmt_days(q_wo),
            secondary=f"{pct_wo:.1f}% of recorded days",
            note="Scheduled weekly rest days",
        )

        # 9. Absent (10th KPI)
        q_ab = bundle.get("kpi_absent_days", 0.0)
        pct_ab = bundle.get("kpi_absent_pct", 0.0)
        self.kpi_cards["kpi_absent"].update_values(
            primary=_fmt_days(q_ab),
            secondary=f"{pct_ab:.1f}% of recorded days",
            note="Recorded employee absence days",
        )

        # 10. Attendance Exceptions
        excp_days = bundle.get("kpi_9_attendance_exceptions_days", 0)
        excp_rate = bundle.get("kpi_9_attendance_exceptions_rate_pct", 0.0)
        affected_emps = bundle.get("kpi_9_attendance_exceptions_affected_emps", 0)
        excp_day_unit = "exception day" if excp_days == 1 else "exception days"
        emp_unit = "affected employee" if affected_emps == 1 else "affected employees"
        self.kpi_cards["kpi_9_attendance_exceptions"].update_values(
            primary=f"{excp_days:,} {excp_day_unit}",
            secondary=f"{excp_rate:.1f}% of recorded employee-days",
            note=f"{affected_emps:,} {emp_unit}",
        )

        # Dynamic Data Quality Status Indicator (Concise dataset-derived status)
        self._current_bundle = bundle
        unclass_cnt = bundle.get("unclassified_records_count", 0)
        unclass_days = bundle.get("kpi_unclassified_days", 0.0)
        unclass_pct = bundle.get("kpi_unclassified_pct", 0.0)
        conflicts_cnt = bundle.get("conflicting_employee_days_count", 0)

        full_b = getattr(self, "_full_dataset_dq_bundle", None) or bundle
        ds_unclass = full_b.get("unclassified_records_count", 0)
        ds_conflicts = full_b.get("conflicting_employee_days_count", 0)
        ds_issues = ds_unclass + ds_conflicts

        if conflicts_cnt > 0:
            self.lbl_dq_info.configure(
                text=f"DQ: {conflicts_cnt} to review",
                text_color=ui.COLOR_WARNING,
            )
        elif unclass_cnt > 0:
            self.lbl_dq_info.configure(
                text=f"DQ: {unclass_cnt} to review",
                text_color=ui.COLOR_WARNING,
            )
        elif ds_issues > 0:
            # Active scope is clean, but dataset contains unresolved records
            self.lbl_dq_info.configure(
                text=f"DQ: Scope Clean ({ds_issues} in dataset)",
                text_color=ui.COLOR_TEXT_SEC,
            )
        else:
            self.lbl_dq_info.configure(
                text="DQ: Clean",
                text_color=ui.COLOR_SUCCESS,
            )

        # Reconciliation & Composition Transparency Card
        denom = bundle.get("attendance_composition_denominator", float(att_days))
        categorized = round(q_pres + q_od + q_leave + q_wfh + q_hol + q_wo + q_ab, 1)

        denom_str = _fmt_days(denom)
        cat_str = _fmt_days(categorized)
        unclass_day_str = _fmt_days(unclass_days)

        if conflicts_cnt > 0:
            day_noun = "Employee-Day" if conflicts_cnt == 1 else "Employee-Days"
            self.lbl_recon_icon.configure(text="⚠️", text_color=ui.COLOR_WARNING)
            self.lbl_recon_title.configure(
                text=f"Reconciliation Notice: {conflicts_cnt:,} Conflicting {day_noun} ({unclass_day_str} / {unclass_pct:.1f}%)",
                text_color=ui.COLOR_WARNING,
            )
            self.lbl_recon_desc.configure(
                text=f"{conflicts_cnt:,} employee-date(s) contain multiple overlapping records resolved to {unclass_day_str} unresolved day in composition denominator ({denom_str}). Categorized attendance totals {cat_str} across Present, OD, Leave, WFH, Holiday, Week Off, and Absent.",
            )
        elif unclass_cnt > 0:
            rec_noun = "Record" if unclass_cnt == 1 else "Records"
            rec_lower = "record is" if unclass_cnt == 1 else "records are"
            self.lbl_recon_icon.configure(text="⚠️", text_color=ui.COLOR_WARNING)
            self.lbl_recon_title.configure(
                text=f"Reconciliation Notice: {unclass_cnt:,} Unclassified {rec_noun} ({unclass_day_str} / {unclass_pct:.1f}%)",
                text_color=ui.COLOR_WARNING,
            )
            self.lbl_recon_desc.configure(
                text=f"All {unclass_cnt:,} unclassified {rec_lower} accounted for in the composition denominator ({denom_str}). Categorized attendance totals {cat_str} across Present, OD, Leave, WFH, Holiday, Week Off, and Absent.",
            )
        else:
            self.lbl_recon_icon.configure(text="✓", text_color=ui.COLOR_SUCCESS)
            self.lbl_recon_title.configure(
                text="Complete Additive Attendance Composition (100.0% Reconciled)",
                text_color=ui.COLOR_SUCCESS,
            )
            self.lbl_recon_desc.configure(
                text=f"All {denom_str} recorded attendance days are categorized across Present ({_fmt_days(q_pres)}), OD ({_fmt_days(q_od)}), Leave ({_fmt_days(q_leave)}), WFH ({_fmt_days(q_wfh)}), Holiday ({_fmt_days(q_hol)}), Week Off ({_fmt_days(q_wo)}), and Absent ({_fmt_days(q_ab)}).",
            )

        if hasattr(self, "recon_card") and self.recon_card.winfo_width() > 10:
            scaling = self.recon_card._get_widget_scaling() if hasattr(self.recon_card, "_get_widget_scaling") else 1.0
            unscaled_w = self.recon_card.winfo_width() / (scaling if scaling > 0 else 1.0)
            wrap_w = max(200, int(unscaled_w - 45))
            if hasattr(self, "lbl_recon_title"):
                self.lbl_recon_title.configure(wraplength=wrap_w)
            if hasattr(self, "lbl_recon_desc"):
                self.lbl_recon_desc.configure(wraplength=wrap_w)

        # Update the 3 analytical visualizations
        comp_data = bundle.get("attendance_composition", [])
        if hasattr(self, "comp_widget"):
            self.comp_widget.update_data(comp_data, denom)

        trend_data = bundle.get("daily_attendance_trend", [])
        period_str = self.lbl_period.cget("text") if hasattr(self, "lbl_period") else ""
        if hasattr(self, "trend_widget"):
            self.trend_widget.update_data(trend_data, reporting_period=period_str)

        bu_data = bundle.get("bu_attendance_comparison", [])
        bu_total = bundle.get("bu_comparison_total", {})
        if hasattr(self, "bu_table_widget"):
            self.bu_table_widget.update_data(bu_data, bu_total)

    def _show_dq_details_dialog(self):
        """Open the accessible Data Quality diagnostics and reconciliation dialog."""
        if hasattr(self, "_dq_dialog") and self._dq_dialog is not None and self._dq_dialog.winfo_exists():
            self._dq_dialog.lift()
            self._dq_dialog.focus_force()
            return
        full_b = getattr(self, "_full_dataset_dq_bundle", None)
        self._dq_dialog = DataQualityDetailDialog(
            self,
            bundle=getattr(self, "_current_bundle", {}),
            full_bundle=full_b,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # F. Navigation State & View Switching
    # ─────────────────────────────────────────────────────────────────────────

    def select_view(self, view_key: str):
        """
        Switch active view instantaneously with zero I/O and zero recalculation.
        Toggles pre-instantiated view containers and updates tab styling.
        """
        if view_key not in VIEW_KEYS:
            return

        self.active_view = view_key

        # Update tab button styling
        for key, btn in self.tab_buttons.items():
            if key == view_key:
                btn.configure(
                    fg_color=ui.COLOR_ACCENT,
                    hover_color=ui.COLOR_ACCENT_HOVER,
                    text_color=ui.COLOR_TEXT,
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    hover_color=ui.COLOR_NAV_HOVER,
                    text_color=ui.COLOR_TEXT_SEC,
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="normal"),
                )

        # Toggle view containers
        for key, container in self.view_containers.items():
            if key == view_key:
                container.grid(row=0, column=0, sticky="nsew")
            else:
                container.grid_remove()

        # If switching to overview and metrics haven't loaded yet for active snapshot, trigger load
        if view_key == "overview":
            snap = snapshot_service.get_active_snapshot()
            if snap and snap.is_valid():
                dataset_id = getattr(snap, "dataset_id", snap.key)
                if dataset_id != self._current_dataset_id or self._last_metrics_bundle is None:
                    if not self._is_loading_metrics:
                        self._load_overview_metrics()

    # ─────────────────────────────────────────────────────────────────────────
    # G. Snapshot Metadata Synchronization & Metric Refresh
    # ─────────────────────────────────────────────────────────────────────────

    def sync_snapshot_state(self, snap: Optional[AnalyticalSnapshot] = None):
        """
        Synchronize header metadata and refresh Executive Overview KPI metrics.
        If dataset changed or was replaced, dispatches background KPI calculation.
        If same dataset and metrics already cached, immediately renders them.
        """
        if snap is None:
            snap = snapshot_service.get_active_snapshot()

        if snap and snap.is_valid():
            raw_name = Path(snap.raw_source).name if snap.raw_source else "Active In-Memory Dataset"
            self._full_dataset_name = raw_name
            disp_name = raw_name if len(raw_name) <= 30 else raw_name[:27] + "..."
            total_rows = snap.row_count
            total_emps = snap.metadata.get("employee_count", 0)
            min_d = snap.metadata.get("min_date", "N/A")
            max_d = snap.metadata.get("max_date", "N/A")

            self.lbl_dataset_name.configure(text=disp_name, text_color=ui.COLOR_TEXT)
            ui.create_tooltip(self.lbl_dataset_name, f"Dataset: {raw_name}")
            self.lbl_period.configure(text=f"{min_d} to {max_d}")
            self.lbl_status_dot.configure(text="●", text_color=ui.COLOR_SUCCESS)
            emp_str = "employee" if total_emps == 1 else "employees"
            rec_str = "record" if total_rows == 1 else "records"
            self.lbl_status_text.configure(
                text=f"{total_rows:,} {rec_str} • {total_emps:,} {emp_str}",
                text_color=ui.COLOR_SUCCESS,
            )
            ui.create_tooltip(self.lbl_status_text, f"{total_rows:,} {rec_str} across {total_emps:,} unique {emp_str}")
            self.lbl_dq_info.configure(text="DQ: Clean", text_color=ui.COLOR_SUCCESS)

            dataset_id = getattr(snap, "dataset_id", snap.key)
            if dataset_id != self._current_dataset_id:
                self._current_dataset_id = dataset_id
                self._last_metrics_bundle = None
                self._filter_state = {
                    "date_range": None,
                    "business_unit": None,
                    "department": None,
                    "manager": None,
                    "employee": None,
                    "date_preset": "All Dates",
                }
                try:
                    self._full_dataset_dq_bundle = workforce_bridge.get_workforce_metrics()
                except Exception:
                    self._full_dataset_dq_bundle = None
                self._populate_filters_from_snapshot(snap)
                self._load_overview_metrics()
            elif self._last_metrics_bundle is None:
                self._load_overview_metrics()
            else:
                self._render_overview_kpis(self._last_metrics_bundle)
                self._set_overview_state("ready")
        else:
            self._full_dataset_name = "No dataset loaded"
            self.lbl_dataset_name.configure(text="No dataset loaded", text_color=ui.COLOR_WARNING)
            self.lbl_period.configure(text="N/A")
            self.lbl_status_dot.configure(text="●", text_color=ui.COLOR_WARNING)
            self.lbl_status_text.configure(
                text="Awaiting Dataset Ingestion",
                text_color=ui.COLOR_WARNING,
            )
            self.lbl_dq_info.configure(text="DQ: Standard", text_color=ui.COLOR_TEXT_SEC)

            self._disable_filters()
            self._current_dataset_id = None
            self._last_metrics_bundle = None
            self._full_dataset_dq_bundle = None
            self._set_overview_state("empty")
