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

from pathlib import Path
import queue
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import customtkinter as ctk
import pandas as pd

from storage import AnalyticalSnapshot, snapshot_service
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
    and operational context footnote.
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

        self.grid_columnconfigure(0, weight=1)

        # Header: Number & Title with color dot indicator
        h_frame = ctk.CTkFrame(self, fg_color="transparent")
        h_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        h_frame.grid_columnconfigure(1, weight=1)

        dot = ctk.CTkLabel(
            h_frame,
            text="●",
            font=ctk.CTkFont(size=10),
            text_color=accent_color,
            width=10,
        )
        dot.grid(row=0, column=0, sticky="w", padx=(0, 3))

        self.lbl_title = ctk.CTkLabel(
            h_frame,
            text=title,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
        )
        self.lbl_title.grid(row=0, column=1, sticky="w")

        # Primary Value Label
        self.lbl_val = ctk.CTkLabel(
            self,
            text="—",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=19, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        )
        self.lbl_val.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 1))

        # Secondary / Percentage Label
        self.lbl_sub = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=accent_color,
            anchor="w",
        )
        self.lbl_sub.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 1))

        # Footnote / Explanation Label
        self.lbl_note = ctk.CTkLabel(
            self,
            text=tooltip_text,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        self.lbl_note.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 6))

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
        inner.grid_columnconfigure(1, weight=1)

        # Left: Title
        lbl_title = ctk.CTkLabel(
            inner,
            text="Workforce Intelligence",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=16, weight="bold"),
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
            f_ds, text="📄", font=ctk.CTkFont(size=10), text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 3))
        self.lbl_dataset_name = ctk.CTkLabel(
            f_ds, text="No dataset loaded", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_WARNING, anchor="w"
        )
        self.lbl_dataset_name.pack(side="left")

        # 2. Reporting Period
        f_per = ctk.CTkFrame(meta_strip, fg_color="transparent")
        f_per.pack(side="left", padx=(0, 10), pady=3)
        ctk.CTkLabel(
            f_per, text="📅", font=ctk.CTkFont(size=10), text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 3))
        self.lbl_period = ctk.CTkLabel(
            f_per, text="N/A", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT, anchor="w"
        )
        self.lbl_period.pack(side="left")

        # 3. Status
        f_stat = ctk.CTkFrame(meta_strip, fg_color="transparent")
        f_stat.pack(side="left", padx=(0, 10), pady=3)
        self.lbl_status_dot = ctk.CTkLabel(
            f_stat, text="●", font=ctk.CTkFont(size=10), text_color=ui.COLOR_WARNING
        )
        self.lbl_status_dot.pack(side="left", padx=(0, 3))
        self.lbl_status_text = ctk.CTkLabel(
            f_stat, text="Awaiting Ingestion", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_WARNING, anchor="w"
        )
        self.lbl_status_text.pack(side="left")

        # 4. Data Quality
        f_dq = ctk.CTkFrame(meta_strip, fg_color="transparent")
        f_dq.pack(side="left", padx=(0, 8), pady=3)
        ctk.CTkLabel(
            f_dq, text="DQ:", font=ctk.CTkFont(size=10, weight="bold"), text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 3))
        self.lbl_dq_info = ctk.CTkLabel(
            f_dq, text="Standard", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        )
        self.lbl_dq_info.pack(side="left")

        # Right: Go to Upload Section button
        self.btn_go_upload = ui.create_secondary_button(
            inner,
            "📂 Upload",
            command=self._on_go_to_upload,
            width=85,
            height=26,
        )
        self.btn_go_upload.grid(row=0, column=2, sticky="e")

    def _on_go_to_upload(self):
        """Navigate user to the upload section to load/replace data."""
        if self.app and hasattr(self.app, "select_frame_by_name"):
            self.app.select_frame_by_name("analyse_upload")

    # ─────────────────────────────────────────────────────────────────────────
    # B. Future Filters Toolbar Placeholder (Step 22)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_filters_placeholder(self):
        """Build the clearly labelled single-row placeholder for future global filter toolbar."""
        self.filter_card = ui.create_card(self)
        self.filter_card.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        inner = ctk.CTkFrame(self.filter_card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=10, pady=4)
        inner.grid_columnconfigure((1, 2, 3, 4, 5), weight=1)

        # Tag label
        ctk.CTkLabel(
            inner,
            text="Filters:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
        ).grid(row=0, column=0, padx=(2, 6), sticky="w")

        filter_configs = [
            (1, "Date Range", "All Dates"),
            (2, "Business Unit", "All Business Units"),
            (3, "Department", "All Departments"),
            (4, "Reporting Manager", "All Reporting Managers"),
            (5, "Employee", "All Employees"),
        ]

        for col_idx, flbl, def_val in filter_configs:
            combo = ctk.CTkComboBox(
                inner,
                values=[f"{flbl}: {def_val}"],
                state="disabled",
                height=26,
                fg_color=ui.COLOR_INPUT_BG,
                border_color=ui.COLOR_BORDER,
                text_color=ui.COLOR_TEXT_SEC,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10),
            )
            combo.set(f"{flbl}: {def_val}")
            combo.grid(row=0, column=col_idx, sticky="ew", padx=3)

        btn_reset = ctk.CTkButton(
            inner,
            text="Reset",
            state="disabled",
            height=26,
            width=60,
            fg_color=ui.COLOR_BTN_SEC,
            text_color=ui.COLOR_TEXT_DIM,
            corner_radius=6,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10),
        )
        btn_reset.grid(row=0, column=6, sticky="ew", padx=(3, 2))

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
            height=34,
        )
        self.nav_card.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.nav_card.grid_columnconfigure(tuple(range(len(VIEW_KEYS))), weight=1)

        for idx, key in enumerate(VIEW_KEYS):
            cfg = VIEW_CONFIGS[key]
            text = f"{cfg['icon']}  {cfg['tab_title']}"
            btn = ctk.CTkButton(
                self.nav_card,
                text=text,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="normal"),
                height=28,
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

        ctk.CTkLabel(
            self.scope_strip,
            text="Executive Overview • Complete Active Population (All Business Units • All Dates)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=2)

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
        row1_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        row1_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="kpi_r1")

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
            card.grid(row=0, column=col, sticky="nsew", padx=3, pady=2)
            self.kpi_cards[cid] = card

        # ── Row 2: 5 Cards (Uniform columns 0–4) ──
        row2_frame = ctk.CTkFrame(self.overview_kpi_frame, fg_color="transparent")
        row2_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        row2_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="kpi_r2")

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
            card.grid(row=0, column=col, sticky="nsew", padx=3, pady=2)
            self.kpi_cards[cid] = card

        # ── Reconciliation & Composition Transparency Card ──
        self.recon_card = ui.create_card(self.overview_kpi_frame)
        self.recon_card.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.recon_card.grid_columnconfigure(0, weight=1)

        r_inner = ctk.CTkFrame(self.recon_card, fg_color="transparent")
        r_inner.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
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
        )
        self.lbl_recon_title.grid(row=0, column=1, sticky="w")

        self.lbl_recon_desc = ctk.CTkLabel(
            r_inner,
            text="All recorded attendance days are reconciled across Present, OD, Leave, WFH, Holiday, Week Off, and Absent.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        self.lbl_recon_desc.grid(row=1, column=1, sticky="w", pady=(1, 0))

        # Initial state: Empty
        self._set_overview_state("empty")

    def _set_overview_state(self, state: str, message: str = ""):
        """Switch visibility between empty, loading, error, and ready states."""
        if state == "empty":
            self.overview_empty_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
            self.overview_loading_frame.grid_remove()
            self.overview_error_frame.grid_remove()
            self.overview_kpi_frame.grid_remove()
            self.overview_prog.stop()
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

        def _worker(jid: int, d_id: str, q: queue.Queue):
            try:
                bundle = workforce_bridge.get_workforce_metrics()
                q.put(("success", bundle, jid, d_id))
            except Exception as e:
                err_msg = str(e)
                q.put(("error", err_msg, jid, d_id))

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

        # Dynamic Data Quality Status Indicator
        unclass_cnt = bundle.get("unclassified_records_count", 0)
        unclass_days = bundle.get("kpi_unclassified_days", 0.0)
        unclass_pct = bundle.get("kpi_unclassified_pct", 0.0)
        conflicts_cnt = bundle.get("conflicting_employee_days_count", 0)

        if conflicts_cnt > 0:
            day_word = "conflicting employee-day" if conflicts_cnt == 1 else "conflicting employee-days"
            self.lbl_dq_info.configure(
                text=f"Loaded • {conflicts_cnt} {day_word} requires review",
                text_color=ui.COLOR_WARNING,
            )
        elif unclass_cnt > 0:
            rec_word = "record requires" if unclass_cnt == 1 else "records require"
            self.lbl_dq_info.configure(
                text=f"Loaded • {unclass_cnt} {rec_word} review",
                text_color=ui.COLOR_WARNING,
            )
        else:
            self.lbl_dq_info.configure(
                text="Clean • Ready for Analysis",
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
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    hover_color=ui.COLOR_NAV_HOVER,
                    text_color=ui.COLOR_TEXT_SEC,
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="normal"),
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
            disp_name = raw_name if len(raw_name) <= 36 else raw_name[:33] + "..."
            total_rows = snap.row_count
            total_emps = snap.metadata.get("employee_count", 0)
            min_d = snap.metadata.get("min_date", "N/A")
            max_d = snap.metadata.get("max_date", "N/A")

            self.lbl_dataset_name.configure(text=disp_name, text_color=ui.COLOR_TEXT)
            self.lbl_period.configure(text=f"{min_d} to {max_d}")
            self.lbl_status_dot.configure(text="●", text_color=ui.COLOR_SUCCESS)
            emp_str = "employee" if total_emps == 1 else "employees"
            rec_str = "record" if total_rows == 1 else "records"
            self.lbl_status_text.configure(
                text=f"{total_rows:,} {rec_str} • {total_emps:,} {emp_str}",
                text_color=ui.COLOR_SUCCESS,
            )
            self.lbl_dq_info.configure(text="Clean • Ready for Analysis", text_color=ui.COLOR_SUCCESS)

            dataset_id = getattr(snap, "dataset_id", snap.key)
            if dataset_id != self._current_dataset_id or self._last_metrics_bundle is None:
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
            self.lbl_dq_info.configure(text="Standard", text_color=ui.COLOR_TEXT_SEC)

            self._current_dataset_id = None
            self._last_metrics_bundle = None
            self._set_overview_state("empty")
