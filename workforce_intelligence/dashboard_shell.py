"""
workforce_intelligence/dashboard_shell.py
──────────────────────────────────────────
Desktop navigation shell and reusable screen structure for the
Transformers 2.0 Workforce Intelligence Dashboard.

Implements Step 21 requirements:
1. Compact header displaying active dataset name, reporting period, dataset status,
   and data-quality information.
2. Clearly labelled placeholder for future global filter toolbar (Step 22).
3. Horizontal navigation bar with exactly six analytical views:
   - Overview
   - Attendance
   - Leave
   - WFH
   - Working Hours
   - Investigations
4. Clear visual active-tab indicator with hover and selection styling.
5. Reusable, scrollable view containers for each view, pre-instantiated once
   and toggled via Tkinter grid layout (zero file I/O, zero recalculation, 0ms switch).
6. Pure CustomTkinter/Tkinter desktop implementation (zero Qt, zero web dependencies).
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path
import customtkinter as ctk

import ui_components as ui
from storage import snapshot_service, AnalyticalSnapshot


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
        "subtitle": "Executive workforce and attendance metrics will appear here.",
        "badge": "Step 23 — Executive Overview",
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
# WorkforceDashboardView Component
# ─────────────────────────────────────────────────────────────────────────────

class WorkforceDashboardView(ctk.CTkFrame):
    """
    Main container frame for the Transformers 2.0 Workforce Intelligence Dashboard.
    Provides header with dataset status, future filter toolbar placeholder,
    horizontal 6-view navigation bar, and pre-built view containers.
    """

    def __init__(self, master, app=None, **kwargs):
        super().__init__(master, fg_color="transparent", corner_radius=0, **kwargs)
        self.app = app
        self.active_view = "overview"
        self.tab_buttons: Dict[str, ctk.CTkButton] = {}
        self.view_containers: Dict[str, ctk.CTkScrollableFrame] = {}

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
        """Build the dashboard title and active dataset metadata card."""
        self.header_card = ui.create_card(self)
        self.header_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.header_card.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(self.header_card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        inner.grid_columnconfigure(0, weight=1)

        # Top row: Title + Upload quick navigation button
        top_row = ctk.CTkFrame(inner, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)

        lbl_title = ctk.CTkLabel(
            top_row,
            text="Workforce Intelligence",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=24, weight="bold"),
            text_color=ui.COLOR_TEXT,
            anchor="w",
        )
        lbl_title.grid(row=0, column=0, sticky="w")

        self.btn_go_upload = ui.create_secondary_button(
            top_row,
            "📂 Go to Upload Section",
            command=self._on_go_to_upload,
            width=170,
        )
        self.btn_go_upload.grid(row=0, column=1, sticky="e", padx=(10, 0))

        lbl_subtitle = ctk.CTkLabel(
            inner,
            text="Executive oversight, attendance composition, leave & WFH governance, and working-hour intelligence.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
        )
        lbl_subtitle.grid(row=1, column=0, sticky="w", pady=(2, 10))

        # Bottom row: 4 Designated Metadata Badges
        # 1. Active Dataset Name
        # 2. Selected Reporting Period
        # 3. Dataset Status
        # 4. Data-Quality Information
        self.meta_frame = ctk.CTkFrame(inner, fg_color=ui.COLOR_INPUT_BG, corner_radius=8)
        self.meta_frame.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        self.meta_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # 1. Dataset Name
        f_ds = ctk.CTkFrame(self.meta_frame, fg_color="transparent")
        f_ds.grid(row=0, column=0, sticky="w", padx=12, pady=8)
        ctk.CTkLabel(
            f_ds, text="DATASET", font=ctk.CTkFont(size=10, weight="bold"), text_color=ui.COLOR_TEXT_DIM
        ).pack(anchor="w")
        self.lbl_dataset_name = ctk.CTkLabel(
            f_ds, text="No dataset loaded", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_WARNING, anchor="w"
        )
        self.lbl_dataset_name.pack(anchor="w")

        # 2. Reporting Period
        f_per = ctk.CTkFrame(self.meta_frame, fg_color="transparent")
        f_per.grid(row=0, column=1, sticky="w", padx=12, pady=8)
        ctk.CTkLabel(
            f_per, text="REPORTING PERIOD", font=ctk.CTkFont(size=10, weight="bold"), text_color=ui.COLOR_TEXT_DIM
        ).pack(anchor="w")
        self.lbl_period = ctk.CTkLabel(
            f_per, text="N/A", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT, anchor="w"
        )
        self.lbl_period.pack(anchor="w")

        # 3. Status
        f_stat = ctk.CTkFrame(self.meta_frame, fg_color="transparent")
        f_stat.grid(row=0, column=2, sticky="w", padx=12, pady=8)
        ctk.CTkLabel(
            f_stat, text="DATASET STATUS", font=ctk.CTkFont(size=10, weight="bold"), text_color=ui.COLOR_TEXT_DIM
        ).pack(anchor="w")
        stat_inner = ctk.CTkFrame(f_stat, fg_color="transparent")
        stat_inner.pack(anchor="w")
        self.lbl_status_dot = ctk.CTkLabel(
            stat_inner, text="●", font=ctk.CTkFont(size=12), text_color=ui.COLOR_WARNING
        )
        self.lbl_status_dot.pack(side="left", padx=(0, 4))
        self.lbl_status_text = ctk.CTkLabel(
            stat_inner, text="Awaiting Dataset Ingestion", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_WARNING, anchor="w"
        )
        self.lbl_status_text.pack(side="left")

        # 4. Data Quality
        f_dq = ctk.CTkFrame(self.meta_frame, fg_color="transparent")
        f_dq.grid(row=0, column=3, sticky="w", padx=12, pady=8)
        ctk.CTkLabel(
            f_dq, text="DATA QUALITY", font=ctk.CTkFont(size=10, weight="bold"), text_color=ui.COLOR_TEXT_DIM
        ).pack(anchor="w")
        self.lbl_dq_info = ctk.CTkLabel(
            f_dq, text="Standard", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        )
        self.lbl_dq_info.pack(anchor="w")

    def _on_go_to_upload(self):
        """Navigate user to the upload section to load/replace data."""
        if self.app and hasattr(self.app, "select_frame_by_name"):
            self.app.select_frame_by_name("analyse_upload")

    # ─────────────────────────────────────────────────────────────────────────
    # B. Future Filters Toolbar Placeholder (Step 22)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_filters_placeholder(self):
        """Build the clearly labelled placeholder for the future global filter toolbar."""
        self.filter_card = ui.create_card(self)
        self.filter_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        inner = ctk.CTkFrame(self.filter_card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=16, pady=10)
        inner.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        # Header row for filters
        f_head = ctk.CTkFrame(inner, fg_color="transparent")
        f_head.grid(row=0, column=0, columnspan=6, sticky="ew", pady=(0, 6))
        f_head.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            f_head,
            text="Global Scope & Filters",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT,
        ).grid(row=0, column=0, sticky="w")

        badge = ctk.CTkLabel(
            f_head,
            text="Step 22 Placeholder",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            fg_color=ui.COLOR_CARD_HOVER,
            text_color=ui.COLOR_TEXT_DIM,
            corner_radius=4,
            padx=8,
            pady=2,
        )
        badge.grid(row=0, column=1, sticky="e")

        # 5 Filter controls placeholders + 1 Reset button placeholder
        filter_labels = [
            ("Date Range", "All Dates"),
            ("Business Unit", "All Business Units"),
            ("Department", "All Departments"),
            ("Reporting Manager", "All Reporting Managers"),
            ("Employee", "All Employees"),
        ]

        for idx, (flbl, def_val) in enumerate(filter_labels):
            box = ctk.CTkFrame(inner, fg_color="transparent")
            box.grid(row=1, column=idx, sticky="ew", padx=3)
            ctk.CTkLabel(
                box, text=flbl, font=ctk.CTkFont(size=10, weight="bold"), text_color=ui.COLOR_TEXT_DIM
            ).pack(anchor="w", pady=(0, 2))
            combo = ctk.CTkComboBox(
                box,
                values=[def_val],
                state="disabled",
                height=30,
                fg_color=ui.COLOR_INPUT_BG,
                border_color=ui.COLOR_BORDER,
                text_color=ui.COLOR_TEXT_SEC,
            )
            combo.set(def_val)
            combo.pack(fill="x")

        # Reset button placeholder
        btn_box = ctk.CTkFrame(inner, fg_color="transparent")
        btn_box.grid(row=1, column=5, sticky="ew", padx=3)
        ctk.CTkLabel(
            btn_box, text="Actions", font=ctk.CTkFont(size=10, weight="bold"), text_color=ui.COLOR_TEXT_DIM
        ).pack(anchor="w", pady=(0, 2))
        btn_reset = ctk.CTkButton(
            btn_box,
            text="Reset Filters",
            state="disabled",
            height=30,
            fg_color=ui.COLOR_BTN_SEC,
            text_color=ui.COLOR_TEXT_DIM,
            corner_radius=6,
        )
        btn_reset.pack(fill="x")

    # ─────────────────────────────────────────────────────────────────────────
    # C. Horizontal Navigation Bar (6 Views)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_tab_navigation(self):
        """Build the horizontal navigation bar containing exactly the six views."""
        self.nav_card = ctk.CTkFrame(
            self,
            fg_color=ui.COLOR_CARD,
            border_width=1,
            border_color=ui.COLOR_BORDER,
            corner_radius=8,
            height=46,
        )
        self.nav_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.nav_card.grid_columnconfigure(tuple(range(len(VIEW_KEYS))), weight=1)

        for idx, key in enumerate(VIEW_KEYS):
            cfg = VIEW_CONFIGS[key]
            text = f"{cfg['icon']}  {cfg['tab_title']}"
            btn = ctk.CTkButton(
                self.nav_card,
                text=text,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="normal"),
                height=36,
                corner_radius=6,
                fg_color="transparent",
                hover_color=ui.COLOR_NAV_HOVER,
                text_color=ui.COLOR_TEXT_SEC,
                command=lambda k=key: self.select_view(k),
            )
            btn.grid(row=0, column=idx, padx=4, pady=5, sticky="ew")
            self.tab_buttons[key] = btn

    # ─────────────────────────────────────────────────────────────────────────
    # D. Reusable View Containers (6 Pre-instantiated Views)
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
            self._populate_view_placeholder(container, key)
            self.view_containers[key] = container

    def _populate_view_placeholder(self, parent: ctk.CTkScrollableFrame, key: str):
        """Populate initial view content with title, description, and clear placeholder."""
        cfg = VIEW_CONFIGS[key]

        # 1. View Header
        hdr = ui.create_page_header(parent, cfg["title"], cfg["subtitle"])
        hdr.grid(row=0, column=0, sticky="ew", pady=(4, 16))

        # 2. Clearly Labelled Placeholder Card
        card = ui.create_card(parent)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        card.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=24, pady=24)
        inner.grid_columnconfigure(0, weight=1)

        # Icon and Stage Badge
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

        # Main Placeholder Notice
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

        # Planned Capabilities Box
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
    # E. Navigation State & View Switching
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

    # ─────────────────────────────────────────────────────────────────────────
    # F. Snapshot Metadata Synchronization
    # ─────────────────────────────────────────────────────────────────────────

    def sync_snapshot_state(self, snap: Optional[AnalyticalSnapshot] = None):
        """
        Synchronize header metadata cards from the active AnalyticalSnapshot.
        Pure metadata readout: zero workbook reads, zero snapshot rebuilds.
        """
        if snap is None:
            snap = snapshot_service.get_active_snapshot()

        if snap and snap.is_valid():
            ds_name = Path(snap.raw_source).name if snap.raw_source else "Active In-Memory Dataset"
            total_rows = snap.row_count
            total_emps = snap.metadata.get("employee_count", 0)
            min_d = snap.metadata.get("min_date", "N/A")
            max_d = snap.metadata.get("max_date", "N/A")

            self.lbl_dataset_name.configure(text=ds_name, text_color=ui.COLOR_TEXT)
            self.lbl_period.configure(text=f"{min_d} to {max_d}")
            self.lbl_status_dot.configure(text="●", text_color=ui.COLOR_SUCCESS)
            self.lbl_status_text.configure(
                text=f"Active: {total_rows:,} records • {total_emps:,} employees",
                text_color=ui.COLOR_SUCCESS,
            )
            self.lbl_dq_info.configure(text="Clean • Ready for Analysis", text_color=ui.COLOR_SUCCESS)
        else:
            self.lbl_dataset_name.configure(text="No dataset loaded", text_color=ui.COLOR_WARNING)
            self.lbl_period.configure(text="N/A")
            self.lbl_status_dot.configure(text="●", text_color=ui.COLOR_WARNING)
            self.lbl_status_text.configure(
                text="Awaiting Dataset Ingestion",
                text_color=ui.COLOR_WARNING,
            )
            self.lbl_dq_info.configure(text="Standard", text_color=ui.COLOR_TEXT_SEC)
