import threading
import traceback
import sys
import os
import re
import json
import subprocess
import ctypes
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd
import customtkinter as ctk
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

import ui_components as ui
import time_series_analysis as tsa
from storage import snapshot_service
import id_card_module as id_card
import generate_id_cards as gen

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "Transformers"
WINDOW_SIZE = "1280x800"

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(1024, 700)

        try:
            myappid = 'moshpit.transformers.1.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

        try:
            if getattr(sys, 'frozen', False):
                base_path = Path(sys._MEIPASS)
            else:
                base_path = Path(__file__).parent
            icon_path = base_path / "icon.ico"
            if icon_path.exists():
                self.iconbitmap(str(icon_path))
        except Exception as e:
            pass

        # StringVars for file paths
        self.selected_input_file = ctk.StringVar()
        self.selected_gen_input_file = ctk.StringVar()
        self.selected_okr_input_file = ctk.StringVar()
        self.gen_mode_var = ctk.StringVar(value="Existing KRA Upload")
        self.absent_emp_file = ctk.StringVar()
        self.absent_att_file = ctk.StringVar()
        self.absent_wfh_file = ctk.StringVar()
        self.att_summary_file = ctk.StringVar()
        self.analyse_upload_file = ctk.StringVar()

        # ID Card Generator state
        self.id_card_mode_var = ctk.StringVar(value="Instant Email Sync")
        self.id_card_emails_var = ctk.StringVar(value="kanupriya.rathore@finbox.in; vinoth.kumar@finbox.in")
        self.id_card_excel_file = ctk.StringVar(value=id_card.get_default_excel_file())
        self.id_card_photos_dir = ctk.StringVar(value="")
        self.id_card_photo_match_mode = ctk.StringVar(value="Auto-Detect")
        self.id_card_preview_email = ctk.StringVar(value="kanupriya.rathore@finbox.in")
        self.id_card_design = ctk.StringVar(value="Modern")
        self.id_card_address_config_visible = False
        self.office_addresses_data = id_card.get_office_addresses()
        self.is_id_card_generating = False
        self.last_preview_pdf_path = None
        self.last_report_path = None
        self.last_id_card_output_dir = None

        # Connectors state (Slack & Keka)
        self.connector_active_tab = ctk.StringVar(value="Slack")
        default_slack_val = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_BOT_ID", "")
        self.slack_bot_token_var = ctk.StringVar(value=default_slack_val)
        self.keka_subdomain_var = ctk.StringVar(value=os.getenv("KEKA_SUBDOMAIN", "finbox"))
        self.keka_client_id_var = ctk.StringVar(value=os.getenv("KEKA_CLIENT_ID", ""))
        self.keka_client_secret_var = ctk.StringVar(value=os.getenv("KEKA_CLIENT_SECRET", ""))
        self.keka_api_key_var = ctk.StringVar(value=os.getenv("KEKA_API_KEY", ""))


        # Time Series Analysis state
        self.ts_dataset = None
        self.ts_file_path = ctk.StringVar()
        self.ts_bu_var = ctk.StringVar(value="All Business Units")
        self.ts_dept_var = ctk.StringVar(value="All Departments")
        self.ts_month_var = ctk.StringVar(value="All Months")
        self.ts_level_var = ctk.StringVar(value="Business Unit")
        self.ts_search_var = ctk.StringVar()
        self.is_ts_loading = False
        self._latest_ts_job_id = 0
        self._current_ts_breakdown_rows = []
        self._search_debounce_id = None

        # Time and Leave Master multi-file lists
        self.tl_perf_files = []
        self.tl_leave_active_files = []
        self.tl_leave_inactive_files = []
        self.tl_wfh_files = []
        
        # State flags
        self.is_processing = False
        self.is_generating = False
        self.is_analysing = False
        
        # Navigation state
        self.transform_menu_expanded = False
        self.analyse_menu_expanded = False
        self.settings_menu_expanded = False
        self.menu_expanded = False
        self.sidebar_collapsed = True
        self.current_active_frame = "dashboard"
        self.nav_parent_btn = None
        self.nav_chevron = None
        self.analyse_parent_btn = None
        self.analyse_chevron = None
        self.settings_parent_btn = None
        self.settings_chevron = None
        self.sub_nav_btns = {}
        self.floating_nav_popup = None
        self.floating_nav_group = None
        self._nav_hover_timer = None
        self._nav_leave_timer = None
        self._nav_outside_bind_id = None

        self._setup_window()
        self._build_layout()

        # Check initial requested tab (CLI flag, environment, or persistent .last_tab)
        initial_tab = "dashboard"
        if len(sys.argv) > 1:
            for i, arg in enumerate(sys.argv[:-1]):
                if arg == "--tab" and i + 1 < len(sys.argv):
                    initial_tab = sys.argv[i + 1]
        elif os.getenv("APP_INITIAL_TAB"):
            initial_tab = os.getenv("APP_INITIAL_TAB")
            os.environ.pop("APP_INITIAL_TAB", None)
        else:
            try:
                tab_file = Path(__file__).resolve().parent / "local_data" / ".last_tab"
                if tab_file.exists():
                    saved_tab = tab_file.read_text(encoding="utf-8").strip()
                    if saved_tab and saved_tab in self.frames:
                        initial_tab = saved_tab
            except Exception:
                pass

        # Global hot-reload keybinds: F5 or Ctrl+R
        self.bind_all("<F5>", lambda e: self.restart_app())
        self.bind_all("<Control-r>", lambda e: self.restart_app())
        self.bind_all("<Control-R>", lambda e: self.restart_app())

        self.select_frame_by_name(initial_tab if initial_tab in self.frames else "dashboard")

    def _setup_window(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.configure(fg_color=ui.COLOR_BG)

    def _build_layout(self):
        # Permanently Compact Navigation Rail (approx 64px)
        self.sidebar = ctk.CTkFrame(self, width=64, corner_radius=0, fg_color=ui.COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(10, weight=1)
        self.sidebar.grid_columnconfigure(0, weight=1)

        # Header with Compact Brand Mark (Row 0)
        self.sidebar_header = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_header.grid(row=0, column=0, sticky="ew", padx=6, pady=(18, 14))
        self.sidebar_header.grid_columnconfigure(0, weight=1)

        self.lbl_logo_compact = ctk.CTkLabel(
            self.sidebar_header,
            text="⚡",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=24, weight="bold"),
            text_color=ui.COLOR_ACCENT,
            anchor="center",
        )
        self.lbl_logo_compact.grid(row=0, column=0, sticky="nsew")

        # Compatibility attributes (kept ungridded)
        self.lbl_logo = ctk.CTkLabel(
            self.sidebar_header,
            text="Transformers",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=24, weight="bold"),
            text_color=ui.COLOR_ACCENT,
        )
        self.btn_sidebar_toggle = ctk.CTkButton(
            self.sidebar_header,
            text="◀",
            width=28,
            height=28,
            corner_radius=6,
            command=self.toggle_sidebar,
        )

        sep = ctk.CTkFrame(self.sidebar, height=1, fg_color=ui.COLOR_SIDEBAR_SEP)
        sep.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 14))

        # ── Compact Transform Navigation Rail Button (Row 2) ───────────────────
        self.nav_parent_frame = self.sidebar
        self.nav_chevron = ctk.CTkLabel(self.sidebar, text="▸")
        self.nav_parent_btn = ctk.CTkButton(
            self.sidebar,
            text=ui.ICON_HOME,
            width=46,
            height=42,
            corner_radius=8,
            anchor="center",
            fg_color=ui.COLOR_NAV_ACTIVE,
            hover_color=ui.COLOR_NAV_HOVER,
            text_color=ui.COLOR_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=18),
            command=self._on_transform_parent_clicked,
        )
        self.nav_parent_btn.grid(row=2, column=0, padx=6, pady=4)
        ui.create_tooltip(self.nav_parent_btn, "Transform")

        self.nav_parent_btn.bind("<Enter>", lambda e: self._on_nav_btn_enter("transform"), add="+")
        self.nav_parent_btn.bind("<Leave>", lambda e: self._on_nav_btn_leave("transform"), add="+")

        # Offscreen child buttons container for backward compatibility
        self._offscreen_compat = ctk.CTkFrame(self)
        self.sub_menu_frame = ctk.CTkFrame(self._offscreen_compat, fg_color="transparent")
        transform_sub_items = [
            ("transform", "KRA Management", ui.ICON_KRA),
            ("absent", "Absent Management", ui.ICON_ABSENT),
            ("att_summary", "Attendance Summary", ui.ICON_ATTENDANCE),
            ("time_leave", "Time and Leave Master", ui.ICON_TIME_LEAVE),
            ("id_card", "ID Card Generator", ui.ICON_IDCARD),
        ]
        for idx, (name, text, icon) in enumerate(transform_sub_items):
            btn = ui.create_sub_nav_button(
                self.sub_menu_frame,
                text=text,
                icon=icon,
                command=lambda n=name: self.select_frame_by_name(n),
                row=idx,
            )
            self.sub_nav_btns[name] = btn

        # ── Compact Analyse Navigation Rail Button (Row 3) ─────────────────────
        self.analyse_parent_frame = self.sidebar
        self.analyse_chevron = ctk.CTkLabel(self.sidebar, text="▸")
        self.analyse_parent_btn = ctk.CTkButton(
            self.sidebar,
            text=ui.ICON_ANALYSE,
            width=46,
            height=42,
            corner_radius=8,
            anchor="center",
            fg_color="transparent",
            hover_color=ui.COLOR_NAV_HOVER,
            text_color=ui.COLOR_TEXT_SEC,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=18),
            command=self._on_analyse_parent_clicked,
        )
        self.analyse_parent_btn.grid(row=3, column=0, padx=6, pady=4)
        ui.create_tooltip(self.analyse_parent_btn, "Analyse")

        self.analyse_parent_btn.bind("<Enter>", lambda e: self._on_nav_btn_enter("analyse"), add="+")
        self.analyse_parent_btn.bind("<Leave>", lambda e: self._on_nav_btn_leave("analyse"), add="+")

        # Offscreen child buttons container for Analyse backward compatibility
        self.analyse_sub_menu_frame = ctk.CTkFrame(self._offscreen_compat, fg_color="transparent")
        analyse_sub_items = [
            ("workforce_intelligence", "Workforce Intelligence", ui.ICON_ANALYSE),
            ("analyse_time_series", "Time Series Analysis", ui.ICON_DASHBOARD),
            ("analyse_upload", "Upload", ui.ICON_UPLOAD),
        ]
        for idx, (name, text, icon) in enumerate(analyse_sub_items):
            btn = ui.create_sub_nav_button(
                self.analyse_sub_menu_frame,
                text=text,
                icon=icon,
                command=lambda n=name: self.select_frame_by_name(n),
                row=idx,
            )
            self.sub_nav_btns[name] = btn

        # ── Compact Settings Navigation Rail Button (Row 4) ────────────────────
        self.settings_parent_frame = self.sidebar
        self.settings_chevron = ctk.CTkLabel(self.sidebar, text="▸")
        self.settings_parent_btn = ctk.CTkButton(
            self.sidebar,
            text=ui.ICON_SETTINGS,
            width=46,
            height=42,
            corner_radius=8,
            anchor="center",
            fg_color="transparent",
            hover_color=ui.COLOR_NAV_HOVER,
            text_color=ui.COLOR_TEXT_SEC,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=18),
            command=self._on_settings_parent_clicked,
        )
        self.settings_parent_btn.grid(row=4, column=0, padx=6, pady=4)
        ui.create_tooltip(self.settings_parent_btn, "Settings")

        self.settings_parent_btn.bind("<Enter>", lambda e: self._on_nav_btn_enter("settings"), add="+")
        self.settings_parent_btn.bind("<Leave>", lambda e: self._on_nav_btn_leave("settings"), add="+")

        # Quick Reload Button at bottom of sidebar (Row 11)
        self.reload_btn = ctk.CTkButton(
            self.sidebar,
            text="🔄",
            width=42,
            height=42,
            corner_radius=8,
            anchor="center",
            fg_color="transparent",
            hover_color=ui.COLOR_NAV_HOVER,
            text_color=ui.COLOR_TEXT_DIM,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=16),
            command=self.restart_app,
        )
        self.reload_btn.grid(row=11, column=0, padx=6, pady=(0, 10))
        ui.create_tooltip(self.reload_btn, "Reload App (F5 / Ctrl+R)")

        # Offscreen child buttons container for Settings backward compatibility
        self.settings_sub_menu_frame = ctk.CTkFrame(self._offscreen_compat, fg_color="transparent")
        settings_sub_items = [
            ("settings_connectors", "Connectors", "🔌"),
        ]
        for idx, (name, text, icon) in enumerate(settings_sub_items):
            btn = ui.create_sub_nav_button(
                self.settings_sub_menu_frame,
                text=text,
                icon=icon,
                command=lambda n=name: self.select_frame_by_name(n),
                row=idx,
            )
            self.sub_nav_btns[name] = btn

        # Main Content (Takes all remaining width permanently)
        self.main_content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.main_content.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        self.main_content.grid_rowconfigure(0, weight=1)
        self.main_content.grid_columnconfigure(0, weight=1)

        # Build Frames
        self.frames = {}
        self._build_dashboard_frame()
        self._build_transform_frame()
        self._build_generate_frame()
        self._build_absent_frame()
        self._build_att_summary_frame()
        self._build_time_leave_frame()
        self._build_id_card_frame()
        self._build_time_series_frame()
        self._build_analyse_upload_frame()
        self._build_workforce_intelligence_frame()
        self._build_settings_connectors_frame()

    def restart_app(self, target_tab=None):
        """Restarts the application immediately preserving the current active tab."""
        tab = target_tab or getattr(self, "current_active_frame", "dashboard")
        os.environ["APP_INITIAL_TAB"] = tab
        try:
            tab_file = Path(__file__).resolve().parent / "local_data" / ".last_tab"
            tab_file.parent.mkdir(parents=True, exist_ok=True)
            tab_file.write_text(tab, encoding="utf-8")
        except Exception:
            pass

        cmd = [sys.executable, sys.argv[0], "--tab", tab]
        try:
            subprocess.Popen(cmd)
            self.destroy()
            sys.exit(0)
        except Exception as e:
            print(f"Error restarting app: {e}")

    def toggle_sidebar(self, force_state=None):
        """Preserves permanent compact icon rail navigation (width 60-64px)."""
        if force_state is not None:
            self.sidebar_collapsed = force_state
        else:
            self.sidebar_collapsed = not self.sidebar_collapsed
        target_w = 64
        self.sidebar.configure(width=target_w)
        self.sidebar.grid_propagate(False)
        self.update_idletasks()

    def _on_nav_btn_enter(self, group: str):
        if self._nav_leave_timer:
            try:
                self.after_cancel(self._nav_leave_timer)
            except Exception:
                pass
            self._nav_leave_timer = None

        if self.floating_nav_popup and self.floating_nav_popup.winfo_exists():
            if self.floating_nav_group == group:
                return
            self.close_floating_nav()
            self._show_floating_nav(group)
            return

        if self._nav_hover_timer:
            try:
                self.after_cancel(self._nav_hover_timer)
            except Exception:
                pass
        self._nav_hover_timer = self.after(150, lambda: self._show_floating_nav(group))

    def _on_nav_btn_leave(self, group: str):
        if self._nav_hover_timer:
            try:
                self.after_cancel(self._nav_hover_timer)
            except Exception:
                pass
            self._nav_hover_timer = None
        self._nav_leave_timer = self.after(250, self._check_and_close_floating_nav)

    def _check_and_close_floating_nav(self):
        self._nav_leave_timer = None
        if not self.floating_nav_popup or not self.floating_nav_popup.winfo_exists():
            return
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            px = self.floating_nav_popup.winfo_rootx()
            py = self.floating_nav_popup.winfo_rooty()
            pw = self.floating_nav_popup.winfo_width()
            ph = self.floating_nav_popup.winfo_height()
            inside_popup = (px <= x <= px + pw) and (py <= y <= py + ph)

            if self.floating_nav_group == "transform":
                parent_btn = self.nav_parent_btn
            elif self.floating_nav_group == "analyse":
                parent_btn = self.analyse_parent_btn
            else:
                parent_btn = getattr(self, "settings_parent_btn", self.nav_parent_btn)
            bx = parent_btn.winfo_rootx()
            by = parent_btn.winfo_rooty()
            bw = parent_btn.winfo_width()
            bh = parent_btn.winfo_height()
            inside_btn = (bx <= x <= bx + bw) and (by <= y <= by + bh)

            if not inside_popup and not inside_btn:
                self.close_floating_nav()
        except Exception:
            self.close_floating_nav()

    def _on_transform_parent_clicked(self):
        """Clicking Transform opens/toggles its floating submenu."""
        if self.floating_nav_popup and self.floating_nav_popup.winfo_exists() and self.floating_nav_group == "transform":
            self.close_floating_nav()
        else:
            self._show_floating_nav("transform")
            if self.current_active_frame not in ("dashboard", "transform", "generate", "absent", "att_summary", "time_leave", "id_card"):
                self.select_frame_by_name("dashboard")

    def toggle_transform_menu(self, force_state=None):
        """Toggle Transform floating submenu."""
        if force_state is not None:
            self.transform_menu_expanded = force_state
        else:
            self.transform_menu_expanded = not self.transform_menu_expanded
        self.menu_expanded = self.transform_menu_expanded
        if self.transform_menu_expanded:
            if hasattr(self, "nav_chevron") and self.nav_chevron:
                self.nav_chevron.configure(text="▾")
            self._show_floating_nav("transform")
            if hasattr(self, "sub_menu_frame") and self.sub_menu_frame:
                self.sub_menu_frame.grid()
        else:
            if hasattr(self, "nav_chevron") and self.nav_chevron:
                self.nav_chevron.configure(text="▸")
            if hasattr(self, "sub_menu_frame") and self.sub_menu_frame:
                self.sub_menu_frame.grid_remove()
            if self.floating_nav_group == "transform":
                self.close_floating_nav()
        self._refresh_nav_active_states()

    def _on_analyse_parent_clicked(self):
        """Clicking Analyse opens/toggles its floating submenu."""
        if self.floating_nav_popup and self.floating_nav_popup.winfo_exists() and self.floating_nav_group == "analyse":
            self.close_floating_nav()
        else:
            self._show_floating_nav("analyse")
            if self.current_active_frame not in ("workforce_intelligence", "analyse_time_series", "analyse_upload"):
                self.select_frame_by_name("workforce_intelligence")

    def toggle_analyse_menu(self, force_state=None):
        """Toggle Analyse floating submenu."""
        if force_state is not None:
            self.analyse_menu_expanded = force_state
        else:
            self.analyse_menu_expanded = not self.analyse_menu_expanded
        if self.analyse_menu_expanded:
            if hasattr(self, "analyse_chevron") and self.analyse_chevron:
                self.analyse_chevron.configure(text="▾")
            self._show_floating_nav("analyse")
            if hasattr(self, "analyse_sub_menu_frame") and self.analyse_sub_menu_frame:
                self.analyse_sub_menu_frame.grid()
        else:
            if hasattr(self, "analyse_chevron") and self.analyse_chevron:
                self.analyse_chevron.configure(text="▸")
            if hasattr(self, "analyse_sub_menu_frame") and self.analyse_sub_menu_frame:
                self.analyse_sub_menu_frame.grid_remove()
            if self.floating_nav_group == "analyse":
                self.close_floating_nav()
        self._refresh_nav_active_states()

    def _on_settings_parent_clicked(self):
        """Clicking Settings opens/toggles its floating submenu."""
        if self.floating_nav_popup and self.floating_nav_popup.winfo_exists() and self.floating_nav_group == "settings":
            self.close_floating_nav()
        else:
            self._show_floating_nav("settings")
            if self.current_active_frame not in ("settings_connectors",):
                self.select_frame_by_name("settings_connectors")

    def toggle_settings_menu(self, force_state=None):
        """Toggle Settings floating submenu."""
        if force_state is not None:
            self.settings_menu_expanded = force_state
        else:
            self.settings_menu_expanded = not self.settings_menu_expanded
        if self.settings_menu_expanded:
            if hasattr(self, "settings_chevron") and self.settings_chevron:
                self.settings_chevron.configure(text="▾")
            self._show_floating_nav("settings")
            if hasattr(self, "settings_sub_menu_frame") and self.settings_sub_menu_frame:
                self.settings_sub_menu_frame.grid()
        else:
            if hasattr(self, "settings_chevron") and self.settings_chevron:
                self.settings_chevron.configure(text="▸")
            if hasattr(self, "settings_sub_menu_frame") and self.settings_sub_menu_frame:
                self.settings_sub_menu_frame.grid_remove()
            if self.floating_nav_group == "settings":
                self.close_floating_nav()
        self._refresh_nav_active_states()

    def _show_floating_nav(self, group: str):
        if self._nav_hover_timer:
            try:
                self.after_cancel(self._nav_hover_timer)
            except Exception:
                pass
            self._nav_hover_timer = None
        self.close_floating_nav()

        # Close any open filter dropdown
        if hasattr(ui, "SearchableDropdown") and ui.SearchableDropdown._active_dropdown:
            try:
                ui.SearchableDropdown._active_dropdown.close_dropdown()
            except Exception:
                pass

        self.update_idletasks()
        if group == "transform":
            parent_btn = self.nav_parent_btn
        elif group == "analyse":
            parent_btn = self.analyse_parent_btn
        else:
            parent_btn = getattr(self, "settings_parent_btn", self.nav_parent_btn)

        rx = self.sidebar.winfo_rootx() + self.sidebar.winfo_width() + 1
        ry = parent_btn.winfo_rooty()

        scale = 1.0
        if hasattr(self, "_get_widget_scaling"):
            try:
                scale = self._get_widget_scaling()
            except Exception:
                scale = 1.0

        if group == "transform":
            items = [
                ("dashboard", "Transform Overview", ui.ICON_HOME),
                ("transform", "KRA Management", ui.ICON_KRA),
                ("absent", "Absent Management", ui.ICON_ABSENT),
                ("att_summary", "Attendance Summary", ui.ICON_ATTENDANCE),
                ("time_leave", "Time and Leave Master", ui.ICON_TIME_LEAVE),
                ("id_card", "ID Card Generator", ui.ICON_IDCARD),
            ]
            title = "TRANSFORM"
            self.transform_menu_expanded = True
            if hasattr(self, "nav_chevron") and self.nav_chevron:
                self.nav_chevron.configure(text="▾")
        elif group == "analyse":
            items = [
                ("workforce_intelligence", "Workforce Intelligence", ui.ICON_ANALYSE),
                ("analyse_time_series", "Time Series Analysis", ui.ICON_DASHBOARD),
                ("analyse_upload", "Upload", ui.ICON_UPLOAD),
            ]
            title = "ANALYSE"
            self.analyse_menu_expanded = True
            if hasattr(self, "analyse_chevron") and self.analyse_chevron:
                self.analyse_chevron.configure(text="▾")
        else:
            items = [
                ("settings_connectors", "Connectors", "🔌"),
            ]
            title = "SETTINGS"
            self.settings_menu_expanded = True
            if hasattr(self, "settings_chevron") and self.settings_chevron:
                self.settings_chevron.configure(text="▾")

        import tkinter as tk
        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=ui.COLOR_CARD)
        self.floating_nav_popup = top
        self.floating_nav_group = group

        card = ctk.CTkFrame(
            top,
            fg_color=ui.COLOR_CARD,
            border_width=1,
            border_color=ui.COLOR_BORDER,
            corner_radius=8,
        )
        card.pack(fill="both", expand=True)

        lbl_hdr = ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w",
        )
        lbl_hdr.pack(fill="x", padx=14, pady=(12, 6))

        buttons = []
        for name, text, icon in items:
            is_active = (name == self.current_active_frame) or (name == "transform" and self.current_active_frame == "generate")
            bg_col = ui.COLOR_NAV_ACTIVE if is_active else "transparent"
            txt_col = ui.COLOR_TEXT if is_active else ui.COLOR_TEXT_SEC
            font_wt = "bold" if is_active else "normal"

            btn = ctk.CTkButton(
                card,
                text=f"  {icon}   {text}",
                height=36,
                corner_radius=6,
                anchor="w",
                fg_color=bg_col,
                hover_color=ui.COLOR_NAV_HOVER,
                text_color=txt_col,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight=font_wt),
                command=lambda n=name: self._on_flyout_item_selected(n),
            )
            btn.pack(fill="x", padx=8, pady=2)
            buttons.append(btn)

        ctk.CTkFrame(card, height=4, fg_color="transparent").pack(fill="x", pady=(0, 4))

        # Dynamic size calculation to guarantee zero clipping on all Windows DPI scales
        top.update_idletasks()
        req_w = top.winfo_reqwidth()
        req_h = top.winfo_reqheight()

        popup_w = max(int(270 * scale), req_w + int(8 * scale))
        popup_h = req_h + int(6 * scale)

        sh = self.winfo_screenheight()
        if ry + popup_h > sh - 20:
            ry = max(10, sh - popup_h - 20)
        if ry < 10:
            ry = 10

        top.geometry(f"{popup_w}x{popup_h}+{rx}+{ry}")

        # Flyout hover maintenance
        def _on_flyout_enter(e):
            if self._nav_leave_timer:
                try:
                    self.after_cancel(self._nav_leave_timer)
                except Exception:
                    pass
                self._nav_leave_timer = None

        def _on_flyout_leave(e):
            if self._nav_leave_timer:
                try:
                    self.after_cancel(self._nav_leave_timer)
                except Exception:
                    pass
            self._nav_leave_timer = self.after(250, self._check_and_close_floating_nav)

        card.bind("<Enter>", _on_flyout_enter)
        card.bind("<Leave>", _on_flyout_leave)
        for b in buttons:
            b.bind("<Enter>", _on_flyout_enter)
            b.bind("<Leave>", _on_flyout_leave)

        # Keyboard bindings
        top.bind("<Escape>", lambda e: self._on_flyout_escape())
        top.bind("<Down>", lambda e: self._on_flyout_cycle_focus(buttons, 1))
        top.bind("<Up>", lambda e: self._on_flyout_cycle_focus(buttons, -1))

        if buttons:
            buttons[0].focus_set()

        self._nav_outside_bind_id = self.bind("<ButtonPress-1>", self._on_nav_outside_click, add="+")

    def _on_flyout_item_selected(self, name: str):
        self.select_frame_by_name(name)
        self.close_floating_nav()

    def _on_flyout_escape(self):
        if self.floating_nav_group == "transform":
            parent_btn = self.nav_parent_btn
        elif self.floating_nav_group == "analyse":
            parent_btn = self.analyse_parent_btn
        else:
            parent_btn = getattr(self, "settings_parent_btn", self.nav_parent_btn)
        self.close_floating_nav()
        parent_btn.focus_set()

    def _on_flyout_cycle_focus(self, buttons, direction):
        focused = None
        for idx, b in enumerate(buttons):
            if b.focus_get() == b:
                focused = idx
                break
        if focused is None:
            nxt = 0 if direction > 0 else len(buttons) - 1
        else:
            nxt = (focused + direction) % len(buttons)
        buttons[nxt].focus_set()
        return "break"

    def _on_nav_outside_click(self, event):
        if not self.floating_nav_popup or not self.floating_nav_popup.winfo_exists():
            return
        try:
            x = event.x_root
            y = event.y_root
            px = self.floating_nav_popup.winfo_rootx()
            py = self.floating_nav_popup.winfo_rooty()
            pw = self.floating_nav_popup.winfo_width()
            ph = self.floating_nav_popup.winfo_height()
            inside_popup = (px <= x <= px + pw) and (py <= y <= py + ph)

            if self.floating_nav_group == "transform":
                parent_btn = self.nav_parent_btn
            elif self.floating_nav_group == "analyse":
                parent_btn = self.analyse_parent_btn
            else:
                parent_btn = getattr(self, "settings_parent_btn", self.nav_parent_btn)
            bx = parent_btn.winfo_rootx()
            by = parent_btn.winfo_rooty()
            bw = parent_btn.winfo_width()
            bh = parent_btn.winfo_height()
            inside_btn = (bx <= x <= bx + bw) and (by <= y <= by + bh)

            if not inside_popup and not inside_btn:
                self.close_floating_nav()
        except Exception:
            self.close_floating_nav()

    def close_floating_nav(self):
        if self._nav_hover_timer:
            try:
                self.after_cancel(self._nav_hover_timer)
            except Exception:
                pass
            self._nav_hover_timer = None
        if self._nav_leave_timer:
            try:
                self.after_cancel(self._nav_leave_timer)
            except Exception:
                pass
            self._nav_leave_timer = None
        if self._nav_outside_bind_id:
            try:
                self.unbind("<ButtonPress-1>", self._nav_outside_bind_id)
            except Exception:
                pass
            self._nav_outside_bind_id = None
        if self.floating_nav_popup:
            try:
                if self.floating_nav_popup.winfo_exists():
                    self.floating_nav_popup.destroy()
            except Exception:
                pass
            self.floating_nav_popup = None
        self.floating_nav_group = None
        self.transform_menu_expanded = False
        self.analyse_menu_expanded = False
        self.settings_menu_expanded = False
        self.menu_expanded = False
        if hasattr(self, "nav_chevron") and self.nav_chevron:
            self.nav_chevron.configure(text="▸")
        if hasattr(self, "analyse_chevron") and self.analyse_chevron:
            self.analyse_chevron.configure(text="▸")
        if hasattr(self, "settings_chevron") and self.settings_chevron:
            self.settings_chevron.configure(text="▸")
        if hasattr(self, "sub_menu_frame") and self.sub_menu_frame:
            self.sub_menu_frame.grid_remove()
        if hasattr(self, "analyse_sub_menu_frame") and self.analyse_sub_menu_frame:
            self.analyse_sub_menu_frame.grid_remove()
        if hasattr(self, "settings_sub_menu_frame") and self.settings_sub_menu_frame:
            self.settings_sub_menu_frame.grid_remove()

    def _refresh_nav_active_states(self):
        """Update parent navigation highlight on the rail based on current screen."""
        name = getattr(self, "current_active_frame", "dashboard")
        transform_children = ("dashboard", "transform", "generate", "absent", "att_summary", "time_leave", "id_card")
        analyse_children = ("workforce_intelligence", "analyse_time_series", "analyse_dashboard", "analyse_upload")
        settings_children = ("settings_connectors", "settings")

        is_transform_parent = name in transform_children
        is_analyse_parent = name in analyse_children
        is_settings_parent = name in settings_children

        if hasattr(self, "nav_parent_btn") and self.nav_parent_btn:
            ui.set_nav_active(self.nav_parent_btn, is_transform_parent)
        if hasattr(self, "analyse_parent_btn") and self.analyse_parent_btn:
            ui.set_nav_active(self.analyse_parent_btn, is_analyse_parent)
        if hasattr(self, "settings_parent_btn") and self.settings_parent_btn:
            ui.set_nav_active(self.settings_parent_btn, is_settings_parent)

        for n, btn in self.sub_nav_btns.items():
            is_active = (n == name) or (name == "generate" and n == "transform")
            ui.set_sub_nav_active(btn, is_active)

    def select_frame_by_name(self, name: str):
        if name == "analyse_dashboard":
            name = "analyse_time_series"
        self.current_active_frame = name

        try:
            tab_file = Path(__file__).resolve().parent / "local_data" / ".last_tab"
            tab_file.parent.mkdir(parents=True, exist_ok=True)
            tab_file.write_text(name, encoding="utf-8")
        except Exception:
            pass

        self._refresh_nav_active_states()

        # Hide all frames
        for f in self.frames.values():
            f.grid_forget()

        # Show selected
        if name in self.frames:
            self.frames[name].grid(row=0, column=0, sticky="nsew")
            if name == "workforce_intelligence" and hasattr(self, "workforce_dashboard_view"):
                self.workforce_dashboard_view.sync_snapshot_state()


    # ---------------------------------------------------------
    # Transform Hub / Overview
    # ---------------------------------------------------------
    def _build_dashboard_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["dashboard"] = f
        f.grid_columnconfigure((0, 1), weight=1)

        ui.create_page_header(f, "Transform", "Quick access to all data transformation and processing modules.").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 30))

        ui.create_dashboard_card(f, ui.ICON_KRA, "KRA Management", "Transform KRA Excel sheets and generate final KEKA upload files.", "Active", lambda: self.select_frame_by_name("transform"), 1, 0)
        ui.create_dashboard_card(f, ui.ICON_ABSENT, "Absent Management", "Process employee data to generate Absent Intimation Reports.", "Active", lambda: self.select_frame_by_name("absent"), 1, 1)
        ui.create_dashboard_card(f, ui.ICON_ATTENDANCE, "Attendance Summary", "Generate summarized attendance reports from raw portal data.", "Active", lambda: self.select_frame_by_name("att_summary"), 2, 0)
        ui.create_dashboard_card(f, ui.ICON_TIME_LEAVE, "Time and Leave Master", "Manage and process time and leave records.", "Active", lambda: self.select_frame_by_name("time_leave"), 2, 1)
        ui.create_dashboard_card(f, ui.ICON_IDCARD, "ID Card Generator", "Bulk generate employee ID cards with photo verification & barcodes.", "Active", lambda: self.select_frame_by_name("id_card"), 3, 0)
        ui.create_dashboard_card(f, ui.ICON_SETTINGS, "Connectors & Settings", "Configure Slack & Keka HRMS API keys, OAuth credentials & environments.", "Active", lambda: self.select_frame_by_name("settings_connectors"), 3, 1)

    # ---------------------------------------------------------
    # KRA Management
    # ---------------------------------------------------------
    def _build_transform_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["transform"] = f
        f.grid_columnconfigure(0, weight=1)

        hdr = ui.create_page_header(f, "KRA Management", "Transform raw KRA files and generate system uploads.")
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        
        # Actions wrapper
        actions = ctk.CTkFrame(hdr, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        ui.create_secondary_button(actions, "Go to Generation →", lambda: self.select_frame_by_name("generate"), 150).pack()

        card = ui.create_card(f)
        card.grid(row=1, column=0, sticky="nsew")

        ctk.CTkLabel(card, text="1. Transform Raw File", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"), text_color=ui.COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(card, text="Upload raw Excel sheet to structure KRA/KPI data.", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12), text_color=ui.COLOR_TEXT_SEC).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        ui.create_upload_row(card, self.selected_input_file, "Select Raw KRA Excel...", "Browse", 2)

        self.kra_prog = ctk.CTkProgressBar(card, mode="indeterminate", height=4, corner_radius=2, fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT)
        self.kra_prog.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))
        self.kra_prog.set(0)
        self.kra_prog.grid_remove()

        row4 = ctk.CTkFrame(card, fg_color="transparent")
        row4.grid(row=4, column=0, sticky="ew", padx=16, pady=(12, 16))
        
        _, self.kra_dot, self.kra_lbl = ui.create_status_badge(row4, "Ready")
        self.kra_lbl.master.pack(side="left")

        self.btn_kra_tf = ui.create_primary_button(row4, "Transform File", self.start_transform)
        self.btn_kra_tf.pack(side="right")

    def _build_generate_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["generate"] = f
        f.grid_columnconfigure(0, weight=1)

        hdr = ui.create_page_header(f, "Generate Upload", "Create final KEKA upload file using employee mappings.")
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        
        actions = ctk.CTkFrame(hdr, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        ui.create_secondary_button(actions, "← Back to Transform", lambda: self.select_frame_by_name("transform"), 150).pack()

        card = ui.create_card(f)
        card.grid(row=1, column=0, sticky="nsew")

        # Mode Selector
        mode_row = ctk.CTkFrame(card, fg_color="transparent")
        mode_row.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 10))

        ctk.CTkLabel(
            mode_row, text="Generation Mode:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(side="left", padx=(0, 12))

        self.gen_mode_seg = ctk.CTkSegmentedButton(
            mode_row,
            values=["Existing KRA Upload", "OKR Upload"],
            command=self._on_gen_mode_changed,
            selected_color=ui.COLOR_ACCENT,
            selected_hover_color=ui.COLOR_ACCENT_HOVER,
            unselected_color=ui.COLOR_INPUT_BG,
            unselected_hover_color=ui.COLOR_BTN_SEC_HOV,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
        )
        self.gen_mode_seg.set("Existing KRA Upload")
        self.gen_mode_seg.pack(side="left")

        # Dynamic Section Header Label
        self.gen_upload_title_lbl = ctk.CTkLabel(
            card, text="Upload Transformed File",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        )
        self.gen_upload_title_lbl.grid(row=1, column=0, sticky="w", padx=16, pady=(4, 4))

        # Upload controls for each mode
        self.gen_kra_upload_frame, _, _ = ui.create_upload_row(
            card, self.selected_gen_input_file, "Select transformed Excel...", "Browse", 2
        )
        self.gen_okr_upload_frame, _, _ = ui.create_upload_row(
            card, self.selected_okr_input_file, "Expected columns: OKR, Key Result Areas, Weightage", "Browse", 2
        )
        self.gen_okr_upload_frame.grid_remove()

        ctk.CTkLabel(
            card, text="Employee Mapping Format:\nEMP ID, Name, Designation (Sheet Name)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT, justify="left"
        ).grid(row=3, column=0, sticky="w", padx=16, pady=(12, 8))
        self.gen_mapping_text = ctk.CTkTextbox(
            card, height=80, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER, border_width=1,
            text_color=ui.COLOR_TEXT
        )
        self.gen_mapping_text.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 12))
        self.gen_mapping_text.insert("0.0", 'EMP001, John Doe, Manager\nEMP002, Jane Smith, Manager')

        self.gen_prog = ctk.CTkProgressBar(card, mode="indeterminate", height=4, corner_radius=2, fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT)
        self.gen_prog.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.gen_prog.set(0)
        self.gen_prog.grid_remove()

        row6 = ctk.CTkFrame(card, fg_color="transparent")
        row6.grid(row=6, column=0, sticky="ew", padx=16, pady=(12, 16))
        
        _, self.gen_dot, self.gen_lbl = ui.create_status_badge(row6, "Ready")
        self.gen_lbl.master.pack(side="left")

        self.btn_gen = ui.create_primary_button(row6, "Generate File", self.start_generate)
        self.btn_gen.pack(side="right")

    def _on_gen_mode_changed(self, mode: str):
        if mode == "OKR Upload":
            self.gen_upload_title_lbl.configure(text="Upload OKR Source File")
            self.gen_kra_upload_frame.grid_remove()
            self.gen_okr_upload_frame.grid()
        else:
            self.gen_upload_title_lbl.configure(text="Upload Transformed File")
            self.gen_okr_upload_frame.grid_remove()
            self.gen_kra_upload_frame.grid()

    # ---------------------------------------------------------
    # Absent Management
    # ---------------------------------------------------------
    def _build_absent_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["absent"] = f
        f.grid_columnconfigure(0, weight=1)

        ui.create_page_header(f, "Absent Management", "Generate absent intimation reports by comparing master, attendance and OD/WFH data.").grid(row=0, column=0, sticky="ew", pady=(0, 20))

        card = ui.create_card(f)
        card.grid(row=1, column=0, sticky="nsew")
        
        ctk.CTkLabel(card, text="Source Files", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"), text_color=ui.COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        ui.create_upload_row(card, self.absent_emp_file, "1. Employee Master (Expected: Employee Master.xlsx)", "Browse", 1)
        ui.create_upload_row(card, self.absent_att_file, "2. Attendance Report (Expected: Attendance Report.xlsx)", "Browse", 2)
        ui.create_upload_row(card, self.absent_wfh_file, "3. OD/WFH Application Report (Expected: OD_WFH Application Report.xlsx)", "Browse", 3)

        row4 = ctk.CTkFrame(card, fg_color="transparent")
        row4.grid(row=4, column=0, sticky="ew", padx=16, pady=(12, 16))
        
        _, self.absent_dot, self.absent_lbl = ui.create_status_badge(row4, "Ready")
        self.absent_lbl.master.pack(side="left")

        self.btn_absent = ui.create_primary_button(row4, "Process Data", self.start_process_absent)
        self.btn_absent.pack(side="right")

    # ---------------------------------------------------------
    # Attendance Summary
    # ---------------------------------------------------------
    def _build_att_summary_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["att_summary"] = f
        f.grid_columnconfigure(0, weight=1)

        ui.create_page_header(f, "Attendance Summary", "Generate employee-wise summary reports from raw attendance portal data.").grid(row=0, column=0, sticky="ew", pady=(0, 20))

        card = ui.create_card(f)
        card.grid(row=1, column=0, sticky="nsew")
        
        ctk.CTkLabel(card, text="Raw Data", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"), text_color=ui.COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        ui.create_upload_row(card, self.att_summary_file, "Select Attendance Raw File...", "Browse", 1)

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 16))
        
        _, self.att_dot, self.att_lbl = ui.create_status_badge(row2, "Ready")
        self.att_lbl.master.pack(side="left")

        self.btn_att = ui.create_primary_button(row2, "Summarize Data", self.start_process_att)
        self.btn_att.pack(side="right")

    # ---------------------------------------------------------
    # Time and Leave Master
    # ---------------------------------------------------------
    def _build_time_leave_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["time_leave"] = f
        f.grid_columnconfigure(0, weight=1)

        hdr = ui.create_page_header(
            f, "Time and Leave Master",
            "Upload single or multi-month records to reconcile Daily Performance Report with Leave and WFH applications."
        )
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 20))

        card = ui.create_card(f)
        card.grid(row=1, column=0, sticky="nsew")

        ctk.CTkLabel(
            card, text="Data Sources (Single or Multi-Month)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        # 1. Daily performance report
        ui.create_multi_upload_row(
            card, self.tl_perf_files,
            "1. Daily Performance Report (Supports multiple months)",
            placeholder="Select Daily Performance Report Excel/CSV files...",
            row=1
        )

        # 2. Leave application - Active
        ui.create_multi_upload_row(
            card, self.tl_leave_active_files,
            "2. Leave Application - Active (Supports multiple months)",
            placeholder="Select Active Leave Application files...",
            row=2
        )

        # 3. Leave application - Inactive
        ui.create_multi_upload_row(
            card, self.tl_leave_inactive_files,
            "3. Leave Application - Inactive (Supports multiple months)",
            placeholder="Select Inactive Leave Application files...",
            row=3
        )

        # 4. WFH applications
        ui.create_multi_upload_row(
            card, self.tl_wfh_files,
            "4. WFH Applications (Supports multiple months)",
            placeholder="Select WFH Application files...",
            row=4
        )

        # Determinate Progress bar based on actual data volume
        self.tl_prog = ctk.CTkProgressBar(
            card, mode="determinate", height=6, corner_radius=3,
            fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT
        )
        self.tl_prog.grid(row=5, column=0, sticky="ew", padx=16, pady=(8, 4))
        self.tl_prog.set(0)
        self.tl_prog.grid_remove()

        # Real-time progress detail label
        self.tl_prog_lbl = ctk.CTkLabel(
            card, text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left"
        )
        self.tl_prog_lbl.grid(row=6, column=0, sticky="w", padx=16, pady=(0, 4))
        self.tl_prog_lbl.grid_remove()

        # Action row
        row7 = ctk.CTkFrame(card, fg_color="transparent")
        row7.grid(row=7, column=0, sticky="ew", padx=16, pady=(8, 16))

        _, self.tl_dot, self.tl_lbl = ui.create_status_badge(row7, "Ready")
        self.tl_lbl.master.pack(side="left")

        self.btn_tl = ui.create_primary_button(row7, "Process & Update Report", self.start_process_time_leave, width=170)
        self.btn_tl.pack(side="right")

    # ---------------------------------------------------------
    # FinBox ID Card Generator
    # ---------------------------------------------------------
    def _build_id_card_frame(self):
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
        self.frames["id_card"] = f
        f.grid_columnconfigure(0, weight=1)

        hdr = ui.create_page_header(
            f, "ID Card Generator",
            "Ultra-fast dual-method ID card generation: Instant Keka Email Sync or Bulk Excel Upload."
        )
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        # Top-right quick actions
        top_actions = ctk.CTkFrame(hdr, fg_color="transparent")
        top_actions.grid(row=0, column=1, sticky="e")
        self.btn_toggle_addresses = ui.create_secondary_button(
            top_actions, "Configure Addresses 🏢", self.toggle_office_addresses_card, 175
        )
        self.btn_toggle_addresses.pack(side="left", padx=(0, 8))
        ui.create_secondary_button(top_actions, "Open Output Folder 📁", self.open_id_card_output_folder, 160).pack(side="left", padx=(0, 8))
        ui.create_secondary_button(top_actions, "Open Audit Report 📊", self.open_id_card_report_file, 160).pack(side="left")

        # 1. Global Preferences & Connectors Status Card
        pref_card = ui.create_card(f)
        pref_card.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        pref_card.grid_columnconfigure(0, weight=1)

        settings_row = ctk.CTkFrame(pref_card, fg_color="transparent")
        settings_row.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        settings_row.grid_columnconfigure(0, weight=1)
        settings_row.grid_columnconfigure(1, weight=1)

        # Template selection box
        design_box = ctk.CTkFrame(settings_row, fg_color=ui.COLOR_INPUT_BG, corner_radius=8, border_width=1, border_color=ui.COLOR_BORDER)
        design_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)

        ctk.CTkLabel(
            design_box, text="Card Design Template:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(anchor="w", padx=12, pady=(6, 4))

        self.id_card_seg_btn = ctk.CTkSegmentedButton(
            design_box, values=["Modern", "Classic"],
            variable=self.id_card_design,
            command=self._on_id_card_design_changed,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            selected_color=ui.COLOR_ACCENT,
            selected_hover_color=ui.COLOR_ACCENT_HOVER,
            unselected_color=ui.COLOR_BTN_SEC,
            unselected_hover_color=ui.COLOR_BTN_SEC_HOV
        )
        self.id_card_seg_btn.pack(fill="x", padx=12, pady=(0, 4))

        self.lbl_id_card_design_desc = ctk.CTkLabel(
            design_box,
            text="FinBox Modern format (Navy & Cyan with Slack Photo & QR)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w"
        )
        self.lbl_id_card_design_desc.pack(fill="x", padx=12, pady=(0, 6))

        # Photo Connectors Status Summary
        connectors_box = ctk.CTkFrame(settings_row, fg_color=ui.COLOR_INPUT_BG, corner_radius=8, border_width=1, border_color=ui.COLOR_BORDER)
        connectors_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)

        conn_hdr = ctk.CTkFrame(connectors_box, fg_color="transparent")
        conn_hdr.pack(fill="x", padx=12, pady=(6, 4))

        ctk.CTkLabel(
            conn_hdr, text="🔌 Photo Sources Status:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(side="left")

        btn_manage_conn = ui.create_secondary_button(
            conn_hdr, "Manage in Settings ⚙",
            lambda: self.select_frame_by_name("settings_connectors"),
            width=150, height=24
        )
        btn_manage_conn.pack(side="right")

        chips_row = ctk.CTkFrame(connectors_box, fg_color="transparent")
        chips_row.pack(fill="x", padx=12, pady=(6, 8))

        # Slack status badge
        slack_chip_box = ctk.CTkFrame(chips_row, fg_color="transparent")
        slack_chip_box.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(slack_chip_box, text="Slack:", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"), text_color=ui.COLOR_TEXT_DIM).pack(side="left", padx=(0, 4))
        self.id_card_slack_dot = ctk.CTkLabel(slack_chip_box, text=ui.ICON_DOT, font=ctk.CTkFont(size=10), text_color=ui.COLOR_TEXT_DIM)
        self.id_card_slack_dot.pack(side="left", padx=(0, 4))
        self.id_card_slack_lbl = ctk.CTkLabel(slack_chip_box, text="Checking...", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11), text_color=ui.COLOR_TEXT_DIM)
        self.id_card_slack_lbl.pack(side="left")

        # Keka status badge
        keka_chip_box = ctk.CTkFrame(chips_row, fg_color="transparent")
        keka_chip_box.pack(side="left")
        ctk.CTkLabel(keka_chip_box, text="Keka:", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"), text_color=ui.COLOR_TEXT_DIM).pack(side="left", padx=(0, 4))
        self.id_card_keka_dot = ctk.CTkLabel(keka_chip_box, text=ui.ICON_DOT, font=ctk.CTkFont(size=10), text_color=ui.COLOR_TEXT_DIM)
        self.id_card_keka_dot.pack(side="left", padx=(0, 4))
        self.id_card_keka_lbl = ctk.CTkLabel(keka_chip_box, text="Not connected", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11), text_color=ui.COLOR_TEXT_DIM)
        self.id_card_keka_lbl.pack(side="left")

        # 2. Office Locations & Addresses Configuration Card (Collapsible)
        self.card_office_addresses = ui.create_card(f)
        self.card_office_addresses.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        self.card_office_addresses.grid_columnconfigure(0, weight=1)
        self.card_office_addresses.grid_remove()  # Hidden by default

        addr_hdr = ctk.CTkFrame(self.card_office_addresses, fg_color="transparent")
        addr_hdr.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            addr_hdr, text="🏢 Office Locations & Addresses Configuration",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        ui.create_secondary_button(
            addr_hdr, "Done / Hide ✕", self.toggle_office_addresses_card, width=110, height=28
        ).pack(side="right")

        ui.create_primary_button(
            addr_hdr, "Save All Addresses 💾", self.save_office_addresses_ui, width=160, height=28
        ).pack(side="right", padx=(0, 8))

        ctk.CTkLabel(
            self.card_office_addresses,
            text="Pre-configure and save physical office addresses mapped to employee location cities in Keka/Excel. When an employee is processed, their card automatically prints the exact address configured for their location.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left"
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Container for address rows
        self.address_rows_container = ctk.CTkFrame(self.card_office_addresses, fg_color="transparent")
        self.address_rows_container.pack(fill="x", padx=16, pady=(0, 8))

        # Add new location bar
        add_loc_bar = ctk.CTkFrame(self.card_office_addresses, fg_color=ui.COLOR_INPUT_BG, corner_radius=6, border_width=1, border_color=ui.COLOR_BORDER)
        add_loc_bar.pack(fill="x", padx=16, pady=(4, 14))
        add_loc_bar.grid_columnconfigure(1, weight=1)

        self.entry_new_loc_name = ctk.CTkEntry(
            add_loc_bar, placeholder_text="Location City (e.g. Pune, Chennai)...",
            width=170, height=32, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_CARD, border_color=ui.COLOR_BORDER, border_width=1
        )
        self.entry_new_loc_name.grid(row=0, column=0, padx=8, pady=8)

        self.entry_new_loc_addr = ctk.CTkEntry(
            add_loc_bar, placeholder_text="Full Office Address (Street, Building, City, PIN)...",
            height=32, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_CARD, border_color=ui.COLOR_BORDER, border_width=1
        )
        self.entry_new_loc_addr.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ew")

        ui.create_primary_button(
            add_loc_bar, "+ Add Location", self.add_office_address, width=120, height=32
        ).grid(row=0, column=2, padx=(0, 8), pady=8)

        # 3. Workflow Mode Switcher Card
        mode_card = ui.create_card(f)
        mode_card.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        mode_card.grid_columnconfigure(0, weight=1)

        mode_hdr = ctk.CTkFrame(mode_card, fg_color="transparent")
        mode_hdr.pack(fill="x", padx=16, pady=(10, 10))

        ctk.CTkLabel(
            mode_hdr, text="Choose Generation Workflow:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(side="left", padx=(0, 14))

        self.id_card_mode_seg = ctk.CTkSegmentedButton(
            mode_hdr,
            values=["⚡ Method 1: Instant Email Sync (Auto-Fetch)", "📁 Method 2: Bulk Excel Upload"],
            variable=self.id_card_mode_var,
            command=self._on_id_card_mode_changed,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            selected_color=ui.COLOR_ACCENT,
            selected_hover_color=ui.COLOR_ACCENT_HOVER,
            unselected_color=ui.COLOR_BTN_SEC,
            unselected_hover_color=ui.COLOR_BTN_SEC_HOV,
            height=34
        )
        self.id_card_mode_seg.set("⚡ Method 1: Instant Email Sync (Auto-Fetch)")
        self.id_card_mode_seg.pack(side="left", fill="x", expand=True)

        # 4. Method 1: Instant Email Sync Container
        self.card_mode_email_sync = ui.create_card(f)
        self.card_mode_email_sync.grid(row=4, column=0, sticky="nsew", pady=(0, 10))
        self.card_mode_email_sync.grid_columnconfigure(0, weight=1)

        m1_hdr = ctk.CTkFrame(self.card_mode_email_sync, fg_color="transparent")
        m1_hdr.pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(
            m1_hdr, text="⚡ Method 1: Instant Email Sync (Auto-Fetch from Keka & Slack)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        ctk.CTkLabel(
            self.card_mode_email_sync,
            text="Enter employee email IDs separated by ';' (or commas / newlines). The generator automatically queries Keka HRMS for Display Name, Designation, EMP ID, Blood Group, Mobile, DOB, and Emergency Contacts. Profile photos are retrieved with automatic fallback (Local Folder ➔ Keka ➔ Slack). Office address is dynamically matched from your configured locations.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left"
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Email input box
        ctk.CTkLabel(
            self.card_mode_email_sync, text="Employee Email ID(s) — separated by semicolon (;):",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(anchor="w", padx=16, pady=(2, 4))

        self.id_card_emails_box = ctk.CTkTextbox(
            self.card_mode_email_sync, height=75,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.id_card_emails_box.pack(fill="x", padx=16, pady=(0, 10))
        self.id_card_emails_box.insert("0.0", "kanupriya.rathore@finbox.in; vinoth.kumar@finbox.in")

        # Optional Local Photos Folder Row
        m1_photo_frame = ctk.CTkFrame(self.card_mode_email_sync, fg_color="transparent")
        m1_photo_frame.pack(fill="x", padx=16, pady=(0, 10))
        m1_photo_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            m1_photo_frame, text="Local Photos Folder (Optional — overrides Keka/Slack if employee photo found locally):",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))

        ctk.CTkEntry(
            m1_photo_frame, textvariable=self.id_card_photos_dir,
            placeholder_text="No local photos folder selected (Keka & Slack will be used automatically)...",
            height=32, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER, border_width=1
        ).grid(row=1, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            m1_photo_frame, text="Browse Folder", width=120, height=32, corner_radius=6,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            fg_color=ui.COLOR_BTN_SEC, hover_color=ui.COLOR_BTN_SEC_HOV,
            command=self.browse_photos_directory
        ).grid(row=1, column=1)

        # Method 1 Action Row
        m1_actions = ctk.CTkFrame(self.card_mode_email_sync, fg_color="transparent")
        m1_actions.pack(fill="x", padx=16, pady=(4, 14))

        self.btn_id_card_email_gen = ui.create_primary_button(
            m1_actions, "Generate ID Cards 🚀", self.start_id_card_email_batch, width=190
        )
        self.btn_id_card_email_gen.pack(side="left", padx=(0, 10))

        self.btn_id_card_email_prev = ui.create_secondary_button(
            m1_actions, "Preview First Card 👁️", self.start_id_card_preview_from_email_mode, width=165
        )
        self.btn_id_card_email_prev.pack(side="left", padx=(0, 10))

        self.btn_id_card_email_view = ui.create_secondary_button(
            m1_actions, "View Preview PDF 📄", self.open_id_card_preview_pdf, width=150
        )
        self.btn_id_card_email_view.pack(side="left")

        # 5. Method 2: Bulk Excel Upload Container (Initially hidden)
        self.card_mode_bulk_excel = ui.create_card(f)
        self.card_mode_bulk_excel.grid(row=4, column=0, sticky="nsew", pady=(0, 10))
        self.card_mode_bulk_excel.grid_columnconfigure(0, weight=1)
        self.card_mode_bulk_excel.grid_remove()

        m2_hdr = ctk.CTkFrame(self.card_mode_bulk_excel, fg_color="transparent")
        m2_hdr.pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(
            m2_hdr, text="📁 Method 2: Bulk Excel Data Upload",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        ctk.CTkLabel(
            self.card_mode_bulk_excel,
            text="Upload an employee roster spreadsheet in Excel format. You can also specify a local folder containing employee photos and pick how photo files are matched (by Employee ID or Email ID). If photos are missing from the folder, Keka and Slack will be used automatically as fallback.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left"
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Excel File Browse Row
        m2_excel_frame = ctk.CTkFrame(self.card_mode_bulk_excel, fg_color="transparent")
        m2_excel_frame.pack(fill="x", padx=16, pady=(0, 10))
        m2_excel_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            m2_excel_frame, text="Employee Data Sheet (Excel .xlsx):",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))

        ctk.CTkEntry(
            m2_excel_frame, textvariable=self.id_card_excel_file,
            placeholder_text="No Excel file selected...",
            height=32, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER, border_width=1
        ).grid(row=1, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            m2_excel_frame, text="Browse File", width=120, height=32, corner_radius=6,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            fg_color=ui.COLOR_BTN_SEC, hover_color=ui.COLOR_BTN_SEC_HOV,
            command=lambda: ui._browse_file(self.id_card_excel_file)
        ).grid(row=1, column=1)

        # Local Photos Folder Browse Row
        m2_photo_frame = ctk.CTkFrame(self.card_mode_bulk_excel, fg_color="transparent")
        m2_photo_frame.pack(fill="x", padx=16, pady=(0, 10))
        m2_photo_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            m2_photo_frame, text="Employee Photos Folder (Optional):",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))

        ctk.CTkEntry(
            m2_photo_frame, textvariable=self.id_card_photos_dir,
            placeholder_text="No local photos folder selected (will use Keka / Slack)...",
            height=32, font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER, border_width=1
        ).grid(row=1, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            m2_photo_frame, text="Browse Folder", width=120, height=32, corner_radius=6,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            fg_color=ui.COLOR_BTN_SEC, hover_color=ui.COLOR_BTN_SEC_HOV,
            command=self.browse_photos_directory
        ).grid(row=1, column=1)

        # Photo Matching Rule
        rule_row = ctk.CTkFrame(self.card_mode_bulk_excel, fg_color=ui.COLOR_INPUT_BG, corner_radius=6, border_width=1, border_color=ui.COLOR_BORDER)
        rule_row.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            rule_row, text="Local Photo Naming Rule:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(side="left", padx=12, pady=8)

        self.seg_photo_rule = ctk.CTkSegmentedButton(
            rule_row,
            values=["Auto-Detect", "Employee ID (e.g. FINBP200.jpg)", "Email ID (e.g. name@finbox.in)"],
            variable=self.id_card_photo_match_mode,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            selected_color=ui.COLOR_ACCENT, selected_hover_color=ui.COLOR_ACCENT_HOVER,
            unselected_color=ui.COLOR_CARD, unselected_hover_color=ui.COLOR_BTN_SEC_HOV
        )
        self.seg_photo_rule.set("Auto-Detect")
        self.seg_photo_rule.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=8)

        # Preview and Bulk Actions Row
        m2_actions = ctk.CTkFrame(self.card_mode_bulk_excel, fg_color="transparent")
        m2_actions.pack(fill="x", padx=16, pady=(4, 14))

        # Left preview section
        prev_sub = ctk.CTkFrame(m2_actions, fg_color="transparent")
        prev_sub.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(prev_sub, text="Preview Single Employee:", font=ctk.CTkFont(size=11, weight="bold"), text_color=ui.COLOR_TEXT_DIM).pack(anchor="w", pady=(0, 2))
        prev_row = ctk.CTkFrame(prev_sub, fg_color="transparent")
        prev_row.pack(fill="x")

        ctk.CTkEntry(
            prev_row, textvariable=self.id_card_preview_email,
            placeholder_text="Enter employee email...", width=220, height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER, border_width=1
        ).pack(side="left", padx=(0, 8))

        self.btn_id_card_preview = ui.create_secondary_button(
            prev_row, "Generate Preview 👁", self.start_id_card_preview, width=145
        )
        self.btn_id_card_preview.pack(side="left", padx=(0, 8))

        self.btn_id_card_view_pdf = ui.create_secondary_button(
            prev_row, "View PDF 📄", self.open_id_card_preview_pdf, width=110
        )
        self.btn_id_card_view_pdf.pack(side="left")

        # Right bulk generation button
        self.btn_id_card_bulk = ui.create_primary_button(
            m2_actions, "Run Bulk Generation 📇", self.start_id_card_bulk, width=200, height=34
        )
        self.btn_id_card_bulk.pack(side="right", padx=(16, 0), pady=(14, 0))

        # 6. Live Activity & Generation Audit Trail Console Card
        log_card = ui.create_card(f)
        log_card.grid(row=5, column=0, sticky="nsew", pady=(0, 10))
        log_card.grid_columnconfigure(0, weight=1)

        log_hdr = ctk.CTkFrame(log_card, fg_color="transparent")
        log_hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        log_hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            log_hdr, text="Live Activity & Generation Audit Trail",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).grid(row=0, column=0, sticky="w")

        stat_frame = ctk.CTkFrame(log_hdr, fg_color="transparent")
        stat_frame.grid(row=0, column=1, sticky="w", padx=16)
        _, self.id_card_dot, self.id_card_lbl = ui.create_status_badge(stat_frame, "Ready")
        self.id_card_lbl.master.pack(side="left")

        ui.create_secondary_button(log_hdr, "Clear Log", self.clear_id_card_console, width=75, height=24).grid(row=0, column=2, sticky="e")

        self.id_card_prog = ctk.CTkProgressBar(
            log_card, mode="indeterminate", height=4, corner_radius=2,
            fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT
        )
        self.id_card_prog.grid(row=1, column=0, sticky="ew", padx=16, pady=(2, 6))
        self.id_card_prog.set(0)
        self.id_card_prog.grid_remove()

        self.id_card_log_text = ctk.CTkTextbox(
            log_card, height=170, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, text_color=ui.COLOR_TEXT, corner_radius=6
        )
        self.id_card_log_text.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.id_card_log_text.insert("0.0", "FinBox ID Card Generator ready.\nChoose 'Method 1: Instant Email Sync' or 'Method 2: Bulk Excel Upload', and click Generate.\n")
        self.id_card_log_text.configure(state="disabled")

        # Initial connectors health check
        self.after(300, self.refresh_slack_status)
        if os.getenv("KEKA_API_KEY") or (os.getenv("KEKA_CLIENT_ID") and os.getenv("KEKA_CLIENT_SECRET")):
            self.after(600, self.refresh_keka_status)


    # ---------------------------------------------------------
    # Settings & Workspace Connectors
    # ---------------------------------------------------------
    def _build_settings_connectors_frame(self):
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
        self.frames["settings_connectors"] = f
        self.frames["settings"] = f  # backwards-compatible alias
        f.grid_columnconfigure(0, weight=1)

        # 1. Page Header
        hdr = ui.create_page_header(
            f, "Settings & Connectors",
            "Configure workspace API integrations, OAuth credentials, and persistent environment configuration."
        )
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        top_actions = ctk.CTkFrame(hdr, fg_color="transparent")
        top_actions.grid(row=0, column=1, sticky="e")
        ui.create_primary_button(
            top_actions, "Save All Credentials 💾",
            lambda: self.save_connectors_credentials("all"),
            width=180
        ).pack(side="left", padx=(0, 8))
        ui.create_secondary_button(
            top_actions, "Refresh Statuses 🔄",
            self._refresh_all_connectors,
            width=150
        ).pack(side="left")

        # 2. Main Two-Column Integration Cards
        cards_grid = ctk.CTkFrame(f, fg_color="transparent")
        cards_grid.grid(row=1, column=0, sticky="nsew", pady=(0, 14))
        cards_grid.grid_columnconfigure((0, 1), weight=1)

        # ── Card 1: Keka HRMS Connector (Primary) ──
        keka_card = ui.create_card(cards_grid)
        keka_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)
        keka_card.grid_columnconfigure(0, weight=1)

        keka_hdr = ctk.CTkFrame(keka_card, fg_color="transparent")
        keka_hdr.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            keka_hdr, text="🏢 Keka HRMS Integration",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        # Primary Badge
        keka_badge = ctk.CTkLabel(
            keka_hdr, text="PRIMARY (1ST)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_ACCENT, fg_color=ui.COLOR_NAV_ACTIVE,
            corner_radius=4, padx=6, pady=2
        )
        keka_badge.pack(side="right")

        ctk.CTkLabel(
            keka_card,
            text="Primary photo source. Generates 24-hour OAuth Bearer tokens via login.keka.com and downloads high-res employee profile pictures.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left", wraplength=480
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Fields container
        keka_fields = ctk.CTkFrame(keka_card, fg_color="transparent")
        keka_fields.pack(fill="x", padx=16, pady=(0, 6))

        # Subdomain
        ctk.CTkLabel(
            keka_fields, text="Company Subdomain (.keka.com):",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        ).pack(fill="x", pady=(2, 2))
        self.entry_keka_subdomain = ctk.CTkEntry(
            keka_fields, textvariable=self.keka_subdomain_var,
            placeholder_text="e.g. finbox", height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.entry_keka_subdomain.pack(fill="x", pady=(0, 8))

        # Client ID
        ctk.CTkLabel(
            keka_fields, text="Keka Client ID:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        ).pack(fill="x", pady=(2, 2))
        self.entry_keka_client_id = ctk.CTkEntry(
            keka_fields, textvariable=self.keka_client_id_var,
            placeholder_text="Enter Keka OAuth Client ID...", height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.entry_keka_client_id.pack(fill="x", pady=(0, 8))

        # Client Secret
        ctk.CTkLabel(
            keka_fields, text="Keka Client Secret:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        ).pack(fill="x", pady=(2, 2))
        self.entry_keka_client_secret = ctk.CTkEntry(
            keka_fields, textvariable=self.keka_client_secret_var,
            placeholder_text="Enter Keka OAuth Client Secret...", show="*", height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.entry_keka_client_secret.pack(fill="x", pady=(0, 8))

        # API Key / Bearer Token
        ctk.CTkLabel(
            keka_fields, text="Keka API Key (or direct Bearer token):",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        ).pack(fill="x", pady=(2, 2))
        self.entry_keka_key = ctk.CTkEntry(
            keka_fields, textvariable=self.keka_api_key_var,
            placeholder_text="Enter Keka API Key (required for OAuth exchange)...", height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.entry_keka_key.pack(fill="x", pady=(0, 10))

        # Status & Action Buttons
        keka_footer = ctk.CTkFrame(keka_card, fg_color="transparent")
        keka_footer.pack(fill="x", padx=16, pady=(4, 14))

        _, self.settings_keka_dot, self.settings_keka_lbl = ui.create_status_badge(keka_footer, "Not connected", pack_side="left")

        self.settings_btn_connect_keka = ui.create_primary_button(
            keka_footer, "Connect & Test", self.connect_keka_now, width=125, height=32
        )
        self.settings_btn_connect_keka.pack(side="right", padx=(8, 0))

        ui.create_secondary_button(
            keka_footer, "Save Keka API 💾",
            lambda: self.save_connectors_credentials("keka"),
            width=125, height=32
        ).pack(side="right")

        # ── Card 2: Slack Workspace Connector (Fallback) ──
        slack_card = ui.create_card(cards_grid)
        slack_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=0)
        slack_card.grid_columnconfigure(0, weight=1)

        slack_hdr = ctk.CTkFrame(slack_card, fg_color="transparent")
        slack_hdr.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            slack_hdr, text="💬 Slack Workspace Integration",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        # Fallback Badge
        slack_badge = ctk.CTkLabel(
            slack_hdr, text="FALLBACK (2ND)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_WARNING, fg_color="#2A2000",
            corner_radius=4, padx=6, pady=2
        )
        slack_badge.pack(side="right")

        ctk.CTkLabel(
            slack_card,
            text="Secondary fallback source. Automatically queried via Slack users.lookupByEmail when Keka has no profile image.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left", wraplength=480
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Slack Fields container
        slack_fields = ctk.CTkFrame(slack_card, fg_color="transparent")
        slack_fields.pack(fill="x", padx=16, pady=(0, 6))

        # Slack Bot Token
        ctk.CTkLabel(
            slack_fields, text="Slack Bot Token (xoxb-...) or Bot ID (B...):",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        ).pack(fill="x", pady=(2, 2))
        self.entry_slack_token = ctk.CTkEntry(
            slack_fields, textvariable=self.slack_bot_token_var,
            placeholder_text="xoxb-your-slack-bot-token or Bot ID B0BE6TGNB09...", height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.entry_slack_token.pack(fill="x", pady=(0, 8))

        # Permissions Note Box
        perm_box = ctk.CTkFrame(slack_fields, fg_color=ui.COLOR_CARD, corner_radius=6, border_width=1, border_color=ui.COLOR_BORDER)
        perm_box.pack(fill="x", pady=(4, 12))
        ctk.CTkLabel(
            perm_box,
            text="Required OAuth Scopes:\n • users:read — Read user profiles and avatars\n • users:read.email — Match employees by corporate email\n\nFallback behavior:\n • Default generic Slack avatars are automatically rejected to prevent invalid ID cards.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_DIM, justify="left", anchor="w"
        ).pack(fill="x", padx=10, pady=8)

        # Slack Status & Action Buttons
        slack_footer = ctk.CTkFrame(slack_card, fg_color="transparent")
        slack_footer.pack(fill="x", padx=16, pady=(4, 14))

        _, self.settings_slack_dot, self.settings_slack_lbl = ui.create_status_badge(slack_footer, "Checking...", pack_side="left")

        self.settings_btn_connect_slack = ui.create_primary_button(
            slack_footer, "Connect & Test", self.connect_slack_now, width=125, height=32
        )
        self.settings_btn_connect_slack.pack(side="right", padx=(8, 0))

        ui.create_secondary_button(
            slack_footer, "Save Slack API 💾",
            lambda: self.save_connectors_credentials("slack"),
            width=125, height=32
        ).pack(side="right")

        # ── Card 3: Secure Environment Persistence & Live Diagnostics Console ──
        log_card = ui.create_card(f)
        log_card.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        log_card.grid_columnconfigure(0, weight=1)

        log_hdr = ctk.CTkFrame(log_card, fg_color="transparent")
        log_hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))

        ctk.CTkLabel(
            log_hdr, text="🔐 Persistent Configuration & Live Diagnostic Console",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        ctk.CTkLabel(
            log_hdr, text="Auto-loads from .env on startup",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(side="right")

        ctk.CTkLabel(
            log_card,
            text="Whenever you click 'Save API' or 'Save All Credentials', your tokens are securely written to the local project .env file. The application re-reads and validates them on every startup, eliminating the need to enter your API keys again.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, justify="left", anchor="w"
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))

        self.settings_log_text = ctk.CTkTextbox(
            log_card, height=130, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, text_color=ui.COLOR_TEXT, corner_radius=6
        )
        self.settings_log_text.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self.settings_log_text.insert("0.0", "Workspace Connectors Console ready.\nConfigure Slack and Keka credentials above, test connectivity, and save permanently to .env.\n")
        self.settings_log_text.configure(state="disabled")


    # ---------------------------------------------------------
    # Workforce Intelligence Dashboard
    # ---------------------------------------------------------
    def _build_workforce_intelligence_frame(self):
        from workforce_intelligence.dashboard_shell import WorkforceDashboardView
        self.workforce_dashboard_view = WorkforceDashboardView(self.main_content, app=self)
        self.frames["workforce_intelligence"] = self.workforce_dashboard_view

    # ---------------------------------------------------------
    # Time Series Analysis
    # ---------------------------------------------------------
    def _build_time_series_frame(self):
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
        self.frames["analyse_time_series"] = f
        self.frames["analyse_dashboard"] = f  # backwards-compatible alias
        f.grid_columnconfigure(0, weight=1)

        # Page Header
        hdr = ui.create_page_header(
            f, "Time Series Analysis",
            "Workforce compliance, exceptions, biometric swipes, and multi-level breakdown."
        )
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        # 1. Dataset Status Header Card
        self.ts_banner_card = ui.create_card(f)
        self.ts_banner_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self.ts_banner_card.grid_columnconfigure(0, weight=1)

        b_frame = ctk.CTkFrame(self.ts_banner_card, fg_color="transparent")
        b_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        b_frame.grid_columnconfigure(0, weight=1)

        self.ts_banner_lbl = ctk.CTkLabel(
            b_frame, text="⚠️ No dataset loaded yet. Please upload a dataset in the Upload section to begin analysis.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
            text_color=ui.COLOR_WARNING, anchor="w"
        )
        self.ts_banner_lbl.grid(row=0, column=0, sticky="w")

        self.btn_ts_go_upload = ui.create_secondary_button(
            b_frame, "📂 Go to Upload Section",
            lambda: self.select_frame_by_name("analyse_upload"), width=180
        )
        self.btn_ts_go_upload.grid(row=0, column=1, sticky="e", padx=(10, 0))

        # 2. Filter & Actions Toolbar
        self.card_filters = ui.create_card(f)
        self.card_filters.grid(row=2, column=0, sticky="ew", pady=(0, 14))

        f_header = ctk.CTkFrame(self.card_filters, fg_color="transparent")
        f_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            f_header, text="Filters & Scope",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        self.btn_ts_export = ui.create_secondary_button(
            f_header, "📥 Export Report to Excel", self._export_ts_excel, width=180
        )
        self.btn_ts_export.pack(side="right")

        f_body = ctk.CTkFrame(self.card_filters, fg_color="transparent")
        f_body.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        f_body.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # BU Combobox
        ctk.CTkLabel(f_body, text="Business Unit", font=ctk.CTkFont(size=11, weight="bold"), text_color=ui.COLOR_TEXT_DIM).grid(row=0, column=0, sticky="w", padx=4, pady=(0, 2))
        self.ts_bu_combo = ctk.CTkComboBox(
            f_body, variable=self.ts_bu_var, values=["All Business Units"],
            command=self._on_ts_filter_changed, height=32,
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            text_color=ui.COLOR_TEXT, dropdown_fg_color=ui.COLOR_CARD,
        )
        self.ts_bu_combo.grid(row=1, column=0, sticky="ew", padx=4)

        # Department Combobox
        ctk.CTkLabel(f_body, text="Department", font=ctk.CTkFont(size=11, weight="bold"), text_color=ui.COLOR_TEXT_DIM).grid(row=0, column=1, sticky="w", padx=4, pady=(0, 2))
        self.ts_dept_combo = ctk.CTkComboBox(
            f_body, variable=self.ts_dept_var, values=["All Departments"],
            command=self._on_ts_filter_changed, height=32,
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            text_color=ui.COLOR_TEXT, dropdown_fg_color=ui.COLOR_CARD,
        )
        self.ts_dept_combo.grid(row=1, column=1, sticky="ew", padx=4)

        # Month Combobox
        ctk.CTkLabel(f_body, text="Month", font=ctk.CTkFont(size=11, weight="bold"), text_color=ui.COLOR_TEXT_DIM).grid(row=0, column=2, sticky="w", padx=4, pady=(0, 2))
        self.ts_month_combo = ctk.CTkComboBox(
            f_body, variable=self.ts_month_var, values=["All Months"],
            command=self._on_ts_filter_changed, height=32,
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            text_color=ui.COLOR_TEXT, dropdown_fg_color=ui.COLOR_CARD,
        )
        self.ts_month_combo.grid(row=1, column=2, sticky="ew", padx=4)

        # Reset button
        btn_reset = ui.create_secondary_button(f_body, "Reset Filters", self._reset_ts_filters, width=100)
        btn_reset.grid(row=1, column=3, sticky="ew", padx=4)

        # 3. KPI Metrics Grid (8 cards, 4 per row)
        self.ts_kpi_frame = ctk.CTkFrame(f, fg_color="transparent")
        self.ts_kpi_frame.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        self.ts_kpi_frame.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="kpi")

        # Row 0
        c1, self.lbl_kpi_leave_val, self.lbl_kpi_leave_sub = ui.create_kpi_metric_card(self.ts_kpi_frame, "Leave Compliance Rate")
        c1.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        c2, self.lbl_kpi_appr_val, self.lbl_kpi_appr_sub = ui.create_kpi_metric_card(self.ts_kpi_frame, "Manager Approval Compliance")
        c2.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)

        c3, self.lbl_kpi_reg_val, self.lbl_kpi_reg_sub = ui.create_kpi_metric_card(self.ts_kpi_frame, "Attendance Exception Rate")
        c3.grid(row=0, column=2, sticky="nsew", padx=4, pady=4)

        c4, self.lbl_kpi_wfh_val, self.lbl_kpi_wfh_sub = ui.create_kpi_metric_card(self.ts_kpi_frame, "WFH Exception Rate (>3d)")
        c4.grid(row=0, column=3, sticky="nsew", padx=4, pady=4)

        # Row 1
        c5, self.lbl_kpi_rep_val, self.lbl_kpi_rep_sub = ui.create_kpi_metric_card(self.ts_kpi_frame, "Repeat Attendance Non-Compliance")
        c5.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        c6, self.lbl_kpi_in_val, self.lbl_kpi_in_sub = ui.create_kpi_metric_card(self.ts_kpi_frame, "AVG In Time (Present/MS)")
        c6.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)

        c7, self.lbl_kpi_out_val, self.lbl_kpi_out_sub = ui.create_kpi_metric_card(self.ts_kpi_frame, "AVG Out Time (Present/MS)")
        c7.grid(row=1, column=2, sticky="nsew", padx=4, pady=4)

        c8, self.lbl_kpi_hrs_val, self.lbl_kpi_hrs_sub = ui.create_kpi_metric_card(self.ts_kpi_frame, "AVG Working Hours")
        c8.grid(row=1, column=3, sticky="nsew", padx=4, pady=4)

        # 4. Multi-Level Breakdown Table Card
        card_table = ui.create_card(f)
        card_table.grid(row=4, column=0, sticky="ew", pady=(0, 20))

        tbl_top = ctk.CTkFrame(card_table, fg_color="transparent")
        tbl_top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            tbl_top, text="Multi-Level Breakdown Analysis",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left", padx=(0, 16))

        # Segmented Control for Levels
        self.ts_level_seg = ctk.CTkSegmentedButton(
            tbl_top,
            values=["Business Unit", "Department", "Reporting Manager", "Employee"],
            command=self._on_ts_level_changed,
            selected_color=ui.COLOR_ACCENT,
            selected_hover_color=ui.COLOR_ACCENT_HOVER,
            unselected_color=ui.COLOR_INPUT_BG,
            unselected_hover_color=ui.COLOR_BTN_SEC_HOV,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
        )
        self.ts_level_seg.set("Business Unit")
        self.ts_level_seg.pack(side="left")

        # Search box on right
        search_box = ctk.CTkEntry(
            tbl_top,
            textvariable=self.ts_search_var,
            placeholder_text="Search entity name...",
            width=200, height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, text_color=ui.COLOR_TEXT,
        )
        search_box.pack(side="right")
        self.ts_search_var.trace_add("write", self._on_ts_search_changed)

        # Treeview container
        tree_container = ctk.CTkFrame(card_table, fg_color=ui.COLOR_CARD)
        tree_container.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        tree_container.grid_columnconfigure(0, weight=1)

        # Style Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TS.Treeview",
            background=ui.COLOR_CARD,
            foreground=ui.COLOR_TEXT,
            fieldbackground=ui.COLOR_CARD,
            rowheight=28,
            font=(ui.FONT_FAMILY, 10),
            borderwidth=0,
        )
        style.configure(
            "TS.Treeview.Heading",
            background="#1A2340",
            foreground="#00FF99",
            font=(ui.FONT_FAMILY, 10, "bold"),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "TS.Treeview",
            background=[("selected", ui.COLOR_ACCENT)],
            foreground=[("selected", "#FFFFFF")],
        )
        style.map(
            "TS.Treeview.Heading",
            background=[("active", "#243052")],
        )

        cols = (
            "entity", "records", "emps", "leave_days", "leave_emp_pct",
            "appr_days", "appr_mgr_pct", "regularized", "wfh_excess",
            "repeat_dev", "in_time", "out_time", "work_hrs"
        )
        self.ts_tree = ttk.Treeview(
            tree_container, columns=cols, show="headings",
            style="TS.Treeview", height=10
        )

        col_configs = [
            ("entity", "Entity Name", 160, "w"),
            ("records", "Rows", 65, "center"),
            ("emps", "Emps", 60, "center"),
            ("leave_days", "Avg Leave Apply", 110, "center"),
            ("leave_emp_pct", "Emp Leave %", 90, "center"),
            ("appr_days", "Avg Approval", 95, "center"),
            ("appr_mgr_pct", "Mgr Appr %", 85, "center"),
            ("regularized", "Regularized", 85, "center"),
            ("wfh_excess", "WFH >3 Days", 85, "center"),
            ("repeat_dev", "Repeat Dev", 80, "center"),
            ("in_time", "AVG In Time", 95, "center"),
            ("out_time", "AVG Out Time", 95, "center"),
            ("work_hrs", "AVG Work Hrs", 95, "center"),
        ]

        for col_id, col_text, col_w, col_anchor in col_configs:
            self.ts_tree.heading(col_id, text=col_text)
            self.ts_tree.column(col_id, width=col_w, minwidth=60, anchor=col_anchor)

        v_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.ts_tree.yview)
        h_scroll = ttk.Scrollbar(tree_container, orient="horizontal", command=self.ts_tree.xview)
        self.ts_tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self.ts_tree.grid(row=0, column=0, sticky="ew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

    # ---------------------------------------------------------
    # Analyse Upload
    # ---------------------------------------------------------
    def _build_analyse_upload_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["analyse_upload"] = f
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        hdr = ui.create_page_header(
            f, "Upload Dataset",
            "Upload Daily Performance report or attendance logs (.xlsx, .xls, .csv) for Time Series Analysis."
        )
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        actions = ctk.CTkFrame(hdr, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        ui.create_secondary_button(actions, "← Workforce Intelligence", lambda: self.select_frame_by_name("workforce_intelligence"), 180).pack(side="left", padx=(0, 10))
        ui.create_secondary_button(actions, "← Time Series Analysis", lambda: self.select_frame_by_name("analyse_time_series"), 180).pack(side="left")

        # Upload Card
        card = ui.create_card(f)
        card.grid(row=1, column=0, sticky="nsew", pady=(0, 12))

        ctk.CTkLabel(
            card, text="1. Select Attendance / Performance Dataset",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 2))

        ctk.CTkLabel(
            card, text="Supported formats: Excel (.xlsx, .xls) and CSV (.csv).",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 8))

        ui.create_upload_row(card, self.ts_file_path, "Select performance dataset to ingest...", "Browse", 2)

        self.ts_prog = ctk.CTkProgressBar(
            card, mode="indeterminate", height=4, corner_radius=2,
            fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT
        )
        self.ts_prog.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.ts_prog.set(0)
        self.ts_prog.grid_remove()

        row4 = ctk.CTkFrame(card, fg_color="transparent")
        row4.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 12))

        _, self.ts_dot, self.ts_lbl = ui.create_status_badge(row4, "Ready")
        self.ts_lbl.master.pack(side="left")

        self.btn_ts_load = ui.create_primary_button(row4, "Load & Ingest Dataset", self.start_ts_analysis, width=170)
        self.btn_ts_load.pack(side="right")

        finbox_sample = Path("local_data/Daily Performance Report 01 Sep 2026 - 13 Sep 2026 - FinBox.xlsx")
        if finbox_sample.exists():
            def _load_sample():
                self.ts_file_path.set(str(finbox_sample.resolve()))
                self.start_ts_analysis()
            ui.create_secondary_button(row4, "📂 Load FinBox Sample", _load_sample, width=170).pack(side="right", padx=(0, 10))

        # Dataset Ingestion Summary Card
        res_card = ui.create_card(f)
        res_card.grid(row=2, column=0, sticky="nsew")
        res_card.grid_columnconfigure(0, weight=1)
        res_card.grid_rowconfigure(1, weight=1)

        res_top = ctk.CTkFrame(res_card, fg_color="transparent")
        res_top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            res_top, text="Dataset Summary & Metadata",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        self.btn_ts_open_tsa = ui.create_primary_button(
            res_top, "🚀 Open Time Series Analysis →",
            lambda: self.select_frame_by_name("analyse_time_series"), width=230
        )
        self.btn_ts_open_tsa.pack(side="right")
        self.btn_ts_open_tsa.configure(state="disabled")

        self.ts_upload_summary_text = ctk.CTkTextbox(
            res_card, height=140, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, text_color=ui.COLOR_TEXT, corner_radius=6
        )
        self.ts_upload_summary_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.ts_upload_summary_text.insert("0.0", "Select an attendance or performance dataset above and click 'Load & Ingest Dataset'.\nOnce loaded, all metrics and drilldowns will be instantly populated in Time Series Analysis.")
        self.ts_upload_summary_text.configure(state="disabled")



    # =========================================================
    # Time Series Analysis Event Handlers
    # =========================================================

    def start_ts_analysis(self):
        file_path = self.ts_file_path.get().strip()
        if not file_path:
            messagebox.showerror("Error", "Please select a dataset file to analyse.")
            return
        if not os.path.exists(file_path):
            messagebox.showerror("Error", f"File not found:\n{file_path}")
            return

        self.is_ts_loading = True
        self.btn_ts_load.configure(state="disabled")
        self.ts_prog.grid()
        self.ts_prog.start()
        ui.update_status(self.ts_dot, self.ts_lbl, "Loading and indexing dataset...", "processing")

        self._latest_ts_job_id += 1
        job_id = self._latest_ts_job_id
        threading.Thread(target=self._run_ts_load_job, args=(file_path, job_id), daemon=True).start()

    def _run_ts_load_job(self, file_path, job_id):
        try:
            snapshot = snapshot_service.prepare_dataset(file_path)
            self.after(0, lambda s=snapshot, p=file_path, j=job_id: self._ts_load_success(s, p, j))
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda m=err_msg, j=job_id: self._ts_load_error(m, j))

    def _ts_load_success(self, snapshot, file_path, job_id):
        if job_id < self._latest_ts_job_id:
            return  # Ignore stale completion

        self.is_ts_loading = False
        self.btn_ts_load.configure(state="normal")
        self.ts_prog.stop()
        self.ts_prog.grid_remove()

        self.ts_dataset = snapshot.fact_df
        total_rows = snapshot.row_count
        total_emps = snapshot.metadata.get("employee_count", 0)
        p_name = Path(file_path).name

        ui.update_status(self.ts_dot, self.ts_lbl, f"Active: {total_rows:,} records • {total_emps:,} employees", "success")

        # Update Workforce Intelligence Dashboard header metadata
        if hasattr(self, "workforce_dashboard_view"):
            self.workforce_dashboard_view.sync_snapshot_state(snapshot)

        # Enable Open Time Series Analysis button in Upload section
        if hasattr(self, "btn_ts_open_tsa"):
            self.btn_ts_open_tsa.configure(state="normal")

        # Update Summary text in Upload section
        if hasattr(self, "ts_upload_summary_text"):
            self.ts_upload_summary_text.configure(state="normal")
            self.ts_upload_summary_text.delete("0.0", "end")
            bus = snapshot.filter_options["business_units"]
            depts = snapshot.filter_options["departments"]
            rms = snapshot.filter_options["managers"]
            months = snapshot.filter_options["months"]
            min_d = snapshot.metadata.get("min_date", "N/A")
            max_d = snapshot.metadata.get("max_date", "N/A")

            summary_info = (
                f"✓ DATASET INGESTED SUCCESSFULLY\n"
                f"{'=' * 60}\n"
                f"File Name:            {p_name}\n"
                f"Total Row Count:      {total_rows:,}\n"
                f"Total Unique Emps:    {total_emps:,}\n"
                f"Date Range:           {min_d} to {max_d}\n"
                f"Business Units ({len(bus)}):   {', '.join(bus[:8])}{'...' if len(bus) > 8 else ''}\n"
                f"Departments ({len(depts)}):      {', '.join(depts[:8])}{'...' if len(depts) > 8 else ''}\n"
                f"Managers ({len(rms)}):         {', '.join(rms[:8])}{'...' if len(rms) > 8 else ''}\n"
                f"Months ({len(months)}):           {', '.join(months)}\n"
                f"{'=' * 60}\n"
                f"Status: Ready for Time Series Analysis! Click 'Open Time Series Analysis →' above."
            )
            self.ts_upload_summary_text.insert("0.0", summary_info)
            self.ts_upload_summary_text.configure(state="disabled")

        # Update Time Series banner
        if hasattr(self, "ts_banner_lbl"):
            self.ts_banner_lbl.configure(
                text=f"📊 Active Dataset: {p_name}  •  {total_rows:,} records  •  {total_emps:,} employees",
                text_color=ui.COLOR_SUCCESS
            )
            self.btn_ts_go_upload.configure(text="📂 Change Dataset")

        # Populate filters
        self.ts_bu_combo.configure(values=["All Business Units"] + bus)
        self.ts_bu_var.set("All Business Units")

        self.ts_dept_combo.configure(values=["All Departments"] + depts)
        self.ts_dept_var.set("All Departments")

        self.ts_month_combo.configure(values=["All Months"] + months)
        self.ts_month_var.set("All Months")

        self._refresh_ts_dashboard()

    def _ts_load_error(self, err_msg, job_id):
        if job_id < self._latest_ts_job_id:
            return  # Ignore stale error

        self.is_ts_loading = False
        self.btn_ts_load.configure(state="normal")
        self.ts_prog.stop()
        self.ts_prog.grid_remove()

        active_snap = snapshot_service.get_active_snapshot()
        if active_snap and active_snap.is_valid():
            total_rows = active_snap.row_count
            total_emps = active_snap.metadata.get("employee_count", 0)
            ui.update_status(self.ts_dot, self.ts_lbl, f"Active: {total_rows:,} records • {total_emps:,} employees", "success")
            if active_snap.raw_source:
                self.ts_file_path.set(str(active_snap.raw_source))
        else:
            ui.update_status(self.ts_dot, self.ts_lbl, "Failed to load dataset", "error")

        messagebox.showerror("Dataset Loading Error", f"Could not load and process dataset:\n{err_msg}")

    def _on_ts_filter_changed(self, choice=None):
        self._refresh_ts_dashboard()

    def _on_ts_level_changed(self, choice):
        self.ts_level_var.set(choice)
        self._refresh_ts_table(reload_data=True)

    def _reset_ts_filters(self):
        self.ts_bu_var.set("All Business Units")
        self.ts_dept_var.set("All Departments")
        self.ts_month_var.set("All Months")
        self.ts_search_var.set("")
        self._refresh_ts_dashboard()

    def _refresh_ts_dashboard(self):
        if not snapshot_service.has_active_snapshot():
            return

        bu = self.ts_bu_var.get()
        dept = self.ts_dept_var.get()
        month = self.ts_month_var.get()

        metrics = snapshot_service.get_dashboard_metrics(
            business_unit=bu, department=dept, month=month
        )

        # 1. Leave Compliance
        leave_days = metrics['avg_leave_apply_days']
        if leave_days >= 0:
            self.lbl_kpi_leave_val.configure(text=f"{leave_days:.1f} days")
            self.lbl_kpi_leave_sub.configure(text=f"In Advance • Emp: {metrics['applied_by_emp_pct']}% | Admin: {metrics['applied_by_admin_pct']}%")
        else:
            self.lbl_kpi_leave_val.configure(text=f"{abs(leave_days):.1f} days late")
            self.lbl_kpi_leave_sub.configure(text=f"Post-Leave • Emp: {metrics['applied_by_emp_pct']}% | Admin: {metrics['applied_by_admin_pct']}%")

        # 2. Manager Approval Compliance
        self.lbl_kpi_appr_val.configure(text=f"{metrics['avg_approval_days']:.1f} days")
        self.lbl_kpi_appr_sub.configure(text=f"Manager: {metrics['appr_mgr_pct']}%  |  Admin: {metrics['appr_admin_pct']}%")

        # 3. Attendance Exceptions
        self.lbl_kpi_reg_val.configure(text=f"{metrics['regularized_days']:,} days")
        self.lbl_kpi_reg_sub.configure(text=f"Regularization Rate: {metrics['reg_rate_pct']}%")

        # 4. WFH Exceptions (>3 Days)
        self.lbl_kpi_wfh_val.configure(text=f"{metrics['wfh_excess_days']:,} days")
        self.lbl_kpi_wfh_sub.configure(text=f"{metrics['wfh_violating_emp_count']} emps > 3 days ({metrics['wfh_exception_rate_pct']}%)")

        # 5. Repeat Non-Compliance
        self.lbl_kpi_rep_val.configure(text=f"{metrics['repeat_emp_count']:,} Emps ({metrics['repeat_emp_pct']}%)")
        self.lbl_kpi_rep_sub.configure(text=f"{metrics['repeat_rm_count']} Managers with repeat deviations")

        # 6. AVG In Time
        self.lbl_kpi_in_val.configure(text=metrics['avg_in_time'])
        self.lbl_kpi_in_sub.configure(text="Present & Missing Swipes")

        # 7. AVG Out Time
        self.lbl_kpi_out_val.configure(text=metrics['avg_out_time'])
        self.lbl_kpi_out_sub.configure(text="Present & Missing Swipes")

        # 8. AVG Working Hours
        self.lbl_kpi_hrs_val.configure(text=metrics['avg_working_hours'])
        self.lbl_kpi_hrs_sub.configure(text=f"{metrics['avg_working_hours_decimal']} decimal hours (P & MS)")

        # Refresh table
        self._refresh_ts_table(reload_data=True)

    def _refresh_ts_table(self, reload_data=True):
        if not snapshot_service.has_active_snapshot():
            return

        level = self.ts_level_var.get()
        bu = self.ts_bu_var.get()
        dept = self.ts_dept_var.get()
        month = self.ts_month_var.get()

        if reload_data or not hasattr(self, "_current_ts_breakdown_rows") or not self._current_ts_breakdown_rows:
            self._current_ts_breakdown_rows = snapshot_service.get_breakdown(
                level=level,
                business_unit=bu,
                department=dept,
                month=month,
            )

        self._render_ts_table_rows()

    def _on_ts_search_changed(self, *args):
        if hasattr(self, "_search_debounce_id") and self._search_debounce_id:
            try:
                self.after_cancel(self._search_debounce_id)
            except Exception:
                pass
        self._search_debounce_id = self.after(100, self._render_ts_table_rows)

    def _render_ts_table_rows(self):
        for item in self.ts_tree.get_children():
            self.ts_tree.delete(item)

        search_q = self.ts_search_var.get().strip().lower()
        rows = getattr(self, "_current_ts_breakdown_rows", [])

        for r in rows:
            e_name = str(r.get("Entity Name", ""))
            e_id = str(r.get("Entity ID", ""))
            if search_q and (search_q not in e_name.lower() and search_q not in e_id.lower()):
                continue

            vals = (
                e_name if e_name else e_id,
                f"{r.get('Total Records', 0):,}",
                f"{r.get('Unique Employees', 0):,}",
                f"{r.get('Avg Days to Apply Leave', 0.0)}d",
                r.get("Leave Applied % (Emp)", "0.0%"),
                f"{r.get('Avg Approval Days', 0.0)}d",
                r.get("Approval % (Mgr)", "0.0%"),
                f"{r.get('Regularized Days', 0):,}",
                f"{r.get('WFH Exception Days (>3)', 0):,}",
                f"{r.get('Repeat Deviant Emps', 0):,}",
                r.get("Avg In Time", "-"),
                r.get("Avg Out Time", "-"),
                r.get("Avg Working Hours", "-"),
            )
            self.ts_tree.insert("", "end", values=vals)

    def _export_ts_excel(self):
        if not snapshot_service.has_active_snapshot():
            messagebox.showwarning("Warning", "Please load a dataset first before exporting.")
            return

        out_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"Time_Series_Analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        if not out_path:
            return

        try:
            bu = self.ts_bu_var.get()
            dept = self.ts_dept_var.get()
            month = self.ts_month_var.get()
            saved_p = snapshot_service.export_report(
                output_path=out_path,
                business_unit=bu,
                department=dept,
                month=month,
            )
            messagebox.showinfo(
                "Export Complete",
                f"Time Series Analysis report successfully exported to:\n{saved_p}"
            )
        except Exception as e:
            messagebox.showerror("Export Failed", f"Failed to export Excel report:\n{e}")

    # =========================================================
    # Event Handlers (UI updates)
    # =========================================================

    def start_analyse(self):
        file_path = self.analyse_upload_file.get().strip()
        if not file_path:
            messagebox.showerror("Error", "Please select a file to analyse.")
            return
        if not os.path.exists(file_path):
            messagebox.showerror("Error", f"File not found:\n{file_path}")
            return

        self.is_analysing = True
        self.btn_analyse.configure(state="disabled")
        self.analyse_prog.grid()
        self.analyse_prog.start()
        ui.update_status(self.analyse_dot, self.analyse_lbl, "Analysing dataset...", "processing")

        threading.Thread(target=self._run_analyse_job, args=(file_path,), daemon=True).start()

    def _run_analyse_job(self, file_path):
        try:
            p = Path(file_path)
            ext = p.suffix.lower()
            file_size_kb = p.stat().st_size / 1024

            lines = []
            lines.append("=" * 64)
            lines.append(" DATASET ANALYSIS REPORT")
            lines.append("=" * 64)
            lines.append(f"File:      {p.name}")
            lines.append(f"Path:      {file_path}")
            lines.append(f"Size:      {file_size_kb:.1f} KB")
            lines.append(f"Analyzed:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("-" * 64)

            if ext == ".csv":
                df = pd.read_csv(file_path)
                lines.append("Format:    CSV (Single Table)")
                lines.append(f"Total Rows:    {len(df):,}")
                lines.append(f"Total Columns: {len(df.columns):,}")
                lines.append(f"Columns:       {', '.join(df.columns.astype(str))}")
                lines.append("")
                lines.append("Column Details:")
                for col in df.columns:
                    non_null = df[col].count()
                    null_cnt = df[col].isna().sum()
                    dtype = df[col].dtype
                    lines.append(f"  • {col}: {dtype} | {non_null:,} non-null, {null_cnt:,} nulls")
            else:
                with pd.ExcelFile(file_path) as xl:
                    lines.append("Format:    Excel Workbook")
                    lines.append(f"Sheets ({len(xl.sheet_names)}): {', '.join(xl.sheet_names)}")
                    lines.append("")
                    for sheet in xl.sheet_names:
                        df = xl.parse(sheet)
                        lines.append(f"--- Sheet: '{sheet}' ---")
                        lines.append(f"  Rows:    {len(df):,}")
                        lines.append(f"  Columns: {len(df.columns):,}")
                        cols_preview = ', '.join(df.columns.astype(str)[:10])
                        if len(df.columns) > 10:
                            cols_preview += "..."
                        lines.append(f"  Columns: {cols_preview}")
                        null_sum = df.isna().sum().sum()
                        lines.append(f"  Total Missing Cells: {null_sum:,}")
                        lines.append("")

            lines.append("=" * 64)
            lines.append("Status: Analysis complete.")
            report = "\n".join(lines)
            self.after(0, lambda: self._analyse_success(report))
        except Exception as e:
            self.after(0, lambda: self._analyse_error(str(e)))

    def _analyse_success(self, report):
        self.is_analysing = False
        self.btn_analyse.configure(state="normal")
        self.analyse_prog.stop()
        self.analyse_prog.grid_remove()
        ui.update_status(self.analyse_dot, self.analyse_lbl, "Analysis Complete", "success")

        self.analyse_result_text.configure(state="normal")
        self.analyse_result_text.delete("0.0", "end")
        self.analyse_result_text.insert("0.0", report)
        self.analyse_result_text.configure(state="disabled")

    def _analyse_error(self, err):
        self.is_analysing = False
        self.btn_analyse.configure(state="normal")
        self.analyse_prog.stop()
        self.analyse_prog.grid_remove()
        ui.update_status(self.analyse_dot, self.analyse_lbl, "Analysis Failed", "error")
        messagebox.showerror("Analysis Error", f"Failed to analyze file:\n{err}")

    # =========================================================
    # FinBox ID Card Generator Handlers
    # =========================================================

    def _append_id_card_log(self, text: str):
        """Thread-safe write to the ID Card console textbox."""
        def _update():
            try:
                self.id_card_log_text.configure(state="normal")
                self.id_card_log_text.insert("end", text)
                self.id_card_log_text.see("end")
                self.id_card_log_text.configure(state="disabled")
            except Exception:
                pass
        try:
            self.after(0, _update)
        except Exception:
            pass

    def _on_id_card_design_changed(self, choice: str):
        """Updates helper description when template changes."""
        if hasattr(self, "lbl_id_card_design_desc"):
            if choice == "Modern":
                self.lbl_id_card_design_desc.configure(
                    text="FinBox Modern format (Navy & Cyan with Slack Photo & QR)"
                )
            else:
                self.lbl_id_card_design_desc.configure(
                    text="FinBox Classic format (Deep Navy with Full Back Details & QR)"
                )

    def _on_connector_tab_changed(self, choice: str):
        """Switches between Slack and Keka connector views (compatibility)."""
        if hasattr(self, "panel_keka") and hasattr(self, "panel_slack"):
            if choice == "Slack":
                self.panel_keka.pack_forget()
                self.panel_slack.pack(fill="x")
            else:
                self.panel_slack.pack_forget()
                self.panel_keka.pack(fill="x")

    def _append_settings_log(self, text: str):
        """Thread-safe write to the Settings console textbox."""
        def _update():
            try:
                if hasattr(self, "settings_log_text") and self.settings_log_text:
                    self.settings_log_text.configure(state="normal")
                    self.settings_log_text.insert("end", text)
                    self.settings_log_text.see("end")
                    self.settings_log_text.configure(state="disabled")
            except Exception:
                pass
        try:
            self.after(0, _update)
        except Exception:
            pass

    def _append_connector_log(self, text: str):
        """Thread-safe write to both Settings and ID Card consoles."""
        self._append_settings_log(text)
        self._append_id_card_log(text)

    def _update_slack_badge(self, msg: str, status_type: str):
        """Updates Slack status badges across Settings and ID Card screens."""
        for dot, lbl in [
            (getattr(self, "settings_slack_dot", None), getattr(self, "settings_slack_lbl", None)),
            (getattr(self, "id_card_slack_dot", None), getattr(self, "id_card_slack_lbl", None)),
            (getattr(self, "slack_dot", None), getattr(self, "slack_lbl", None)),
        ]:
            if dot and lbl:
                try:
                    ui.update_status(dot, lbl, msg, status_type)
                except Exception:
                    pass

    def _update_keka_badge(self, msg: str, status_type: str):
        """Updates Keka status badges across Settings and ID Card screens."""
        for dot, lbl in [
            (getattr(self, "settings_keka_dot", None), getattr(self, "settings_keka_lbl", None)),
            (getattr(self, "id_card_keka_dot", None), getattr(self, "id_card_keka_lbl", None)),
            (getattr(self, "keka_dot", None), getattr(self, "keka_lbl", None)),
        ]:
            if dot and lbl:
                try:
                    ui.update_status(dot, lbl, msg, status_type)
                except Exception:
                    pass

    def save_connectors_credentials(self, which="all"):
        """
        Saves current entered credentials to .env file permanently.
        Allows users to store API keys and tokens so they never have to enter them each time.
        """
        saved_items = []
        if which in ("all", "slack"):
            slack_val = self.slack_bot_token_var.get().strip()
            if slack_val:
                if slack_val.startswith("xoxb-"):
                    id_card.save_env_variable("SLACK_BOT_TOKEN", slack_val)
                    saved_items.append("SLACK_BOT_TOKEN")
                elif slack_val.startswith("B") or slack_val.startswith("U"):
                    id_card.save_env_variable("SLACK_BOT_ID", slack_val)
                    saved_items.append("SLACK_BOT_ID")
                else:
                    id_card.save_env_variable("SLACK_BOT_TOKEN", slack_val)
                    saved_items.append("SLACK_BOT_TOKEN")

        if which in ("all", "keka"):
            sub = self.keka_subdomain_var.get().strip()
            cid = self.keka_client_id_var.get().strip()
            csec = self.keka_client_secret_var.get().strip()
            key = self.keka_api_key_var.get().strip()

            if sub:
                id_card.save_env_variable("KEKA_SUBDOMAIN", sub)
                saved_items.append("KEKA_SUBDOMAIN")
            if cid:
                id_card.save_env_variable("KEKA_CLIENT_ID", cid)
                saved_items.append("KEKA_CLIENT_ID")
            if csec:
                id_card.save_env_variable("KEKA_CLIENT_SECRET", csec)
                saved_items.append("KEKA_CLIENT_SECRET")
            if key:
                id_card.save_env_variable("KEKA_API_KEY", key)
                saved_items.append("KEKA_API_KEY")

        item_str = ", ".join(saved_items) if saved_items else "No credentials specified"
        log_msg = f"[SETTINGS] ✓ Saved to .env: {item_str}\n"
        self._append_connector_log(log_msg)
        messagebox.showinfo(
            "API Credentials Saved",
            f"Saved the following keys to your project .env file:\n\n{item_str}\n\n"
            "These credentials will be loaded automatically on every app startup, so you don't need to re-enter them."
        )

    def connect_slack_now(self):
        """Validates Slack token or Bot ID from entry and updates status in background."""
        token_or_id = self.slack_bot_token_var.get().strip()
        for btn in [getattr(self, "btn_connect_slack", None), getattr(self, "settings_btn_connect_slack", None)]:
            if btn:
                try:
                    btn.configure(text="...", state="disabled")
                except Exception:
                    pass
        self._update_slack_badge("Connecting to Slack...", "processing")
        self._append_connector_log("\n[CONNECTORS] Connecting to Slack Workspace API...\n")

        def _worker():
            is_conn, msg, user, *rest = id_card.check_slack_status(token_or_id)
            def _finish():
                try:
                    for btn in [getattr(self, "btn_connect_slack", None), getattr(self, "settings_btn_connect_slack", None)]:
                        if btn:
                            try:
                                btn.configure(text="Connect & Test", state="normal")
                            except Exception:
                                pass
                    if is_conn:
                        self._update_slack_badge(msg, "success")
                        self._append_connector_log(f"[CONNECTORS] ✓ Slack connected: {msg}\n")
                    else:
                        self._update_slack_badge(msg, "error")
                        self._append_connector_log(f"[CONNECTORS] ✕ Slack connection failed: {msg}\n")
                except Exception:
                    pass
            try:
                self.after(0, _finish)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def connect_keka_now(self):
        """Validates Keka API credentials from entry fields and updates status in background."""
        client_id = self.keka_client_id_var.get().strip()
        client_secret = self.keka_client_secret_var.get().strip()
        api_key = self.keka_api_key_var.get().strip()
        subdomain = self.keka_subdomain_var.get().strip()
        for btn in [getattr(self, "btn_connect_keka", None), getattr(self, "settings_btn_connect_keka", None)]:
            if btn:
                try:
                    btn.configure(text="...", state="disabled")
                except Exception:
                    pass
        self._update_keka_badge("Connecting to Keka...", "processing")
        self._append_connector_log(f"\n[CONNECTORS] Connecting to Keka HRMS ({subdomain}.keka.com)...\n")

        def _worker():
            is_conn, msg, details = id_card.check_keka_status(
                api_key=api_key, client_id=client_id, client_secret=client_secret, subdomain=subdomain
            )
            def _finish():
                try:
                    for btn in [getattr(self, "btn_connect_keka", None), getattr(self, "settings_btn_connect_keka", None)]:
                        if btn:
                            try:
                                btn.configure(text="Connect & Test", state="normal")
                            except Exception:
                                pass
                    if is_conn:
                        self._update_keka_badge(msg, "success")
                        self._append_connector_log(f"[CONNECTORS] ✓ Keka connected: {msg}\n")
                    else:
                        self._update_keka_badge(msg, "error")
                        self._append_connector_log(f"[CONNECTORS] ✕ Keka connection failed: {msg}\n")
                except Exception:
                    pass
            try:
                self.after(0, _finish)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def refresh_slack_status(self):
        """Checks Slack connection in background."""
        self.connect_slack_now()

    def refresh_keka_status(self):
        """Checks Keka connection in background."""
        self.connect_keka_now()

    def _refresh_all_connectors(self):
        """Refreshes both Slack and Keka connections."""
        self.connect_slack_now()
        self.connect_keka_now()

    def toggle_office_addresses_card(self):
        """Toggles visibility of the Office Address Configuration card."""
        self.id_card_address_config_visible = not self.id_card_address_config_visible
        if self.id_card_address_config_visible:
            self.card_office_addresses.grid()
            self._refresh_address_list_ui()
            if hasattr(self, "btn_toggle_addresses"):
                self.btn_toggle_addresses.configure(text="Hide Addresses ✕")
        else:
            self.card_office_addresses.grid_remove()
            if hasattr(self, "btn_toggle_addresses"):
                self.btn_toggle_addresses.configure(text="Configure Addresses 🏢")

    def _refresh_address_list_ui(self):
        """Rebuilds the interactive list of configured office addresses."""
        if not hasattr(self, "address_rows_container"):
            return
        for widget in self.address_rows_container.winfo_children():
            widget.destroy()

        self.address_entries_map = {}
        for loc, addr in sorted(self.office_addresses_data.items(), key=lambda x: (x[0].lower() != "default", x[0].lower())):
            row_frame = ctk.CTkFrame(self.address_rows_container, fg_color=ui.COLOR_INPUT_BG, corner_radius=6, border_width=1, border_color=ui.COLOR_BORDER)
            row_frame.pack(fill="x", padx=4, pady=3)
            row_frame.grid_columnconfigure(1, weight=1)

            # Location badge
            loc_lbl = ctk.CTkLabel(
                row_frame, text=loc, width=120,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
                text_color=ui.COLOR_ACCENT, fg_color=ui.COLOR_NAV_ACTIVE,
                corner_radius=4, padx=6, pady=4
            )
            loc_lbl.grid(row=0, column=0, padx=8, pady=6, sticky="w")

            # Address text entry (editable)
            addr_var = ctk.StringVar(value=addr)
            self.address_entries_map[loc] = addr_var
            addr_entry = ctk.CTkEntry(
                row_frame, textvariable=addr_var,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
                fg_color=ui.COLOR_CARD, border_color=ui.COLOR_BORDER,
                border_width=1, height=28, text_color=ui.COLOR_TEXT
            )
            addr_entry.grid(row=0, column=1, padx=(0, 8), pady=6, sticky="ew")

            # Delete button (cannot delete Default, but can edit)
            if loc.lower() != "default":
                del_btn = ctk.CTkButton(
                    row_frame, text="🗑", width=30, height=28, corner_radius=4,
                    font=ctk.CTkFont(size=12),
                    fg_color=ui.COLOR_CARD, hover_color="#441111",
                    text_color="#FF6B6B",
                    command=lambda k=loc: self.delete_office_address(k)
                )
                del_btn.grid(row=0, column=2, padx=(0, 8), pady=6)

    def add_office_address(self):
        """Adds a new location mapping to office_addresses_data."""
        loc = self.entry_new_loc_name.get().strip()
        addr = self.entry_new_loc_addr.get().strip()
        if not loc or not addr:
            messagebox.showwarning("Incomplete Data", "Please enter both Location City and Office Address.")
            return
        self.office_addresses_data[loc] = addr
        self.entry_new_loc_name.delete(0, "end")
        self.entry_new_loc_addr.delete(0, "end")
        self._refresh_address_list_ui()

    def delete_office_address(self, loc_key):
        """Removes a location from office_addresses_data."""
        if loc_key in self.office_addresses_data:
            del self.office_addresses_data[loc_key]
            self._refresh_address_list_ui()

    def save_office_addresses_ui(self):
        """Saves current address entries to local_data/office_addresses.json."""
        if hasattr(self, "address_entries_map"):
            for loc, var in self.address_entries_map.items():
                self.office_addresses_data[loc] = var.get().strip()
        id_card.save_office_addresses(self.office_addresses_data)
        count = len(self.office_addresses_data)
        self._append_id_card_log(f"\n[ADDRESSES] ✓ Saved {count} office locations to local_data/office_addresses.json\n")
        messagebox.showinfo(
            "Office Addresses Saved",
            f"Successfully saved {count} location addresses.\n\n"
            "Future ID card generations will automatically match employee city locations to these addresses."
        )

    def _on_id_card_mode_changed(self, choice=None):
        """Toggles view between Instant Email Sync and Bulk Excel Upload."""
        val = self.id_card_mode_seg.get()
        if "Instant Email Sync" in val:
            self.card_mode_email_sync.grid()
            self.card_mode_bulk_excel.grid_remove()
        else:
            self.card_mode_email_sync.grid_remove()
            self.card_mode_bulk_excel.grid()

    def browse_photos_directory(self):
        """Opens folder dialog to pick local photos directory."""
        d = filedialog.askdirectory(title="Select Local Photos Directory")
        if d:
            self.id_card_photos_dir.set(d)
            self._append_id_card_log(f"[PHOTOS] Selected local photos directory: {d}\n")

    def start_id_card_email_batch(self):
        """Runs Method 1: Instant Email Sync ID Card Generation."""
        if self.is_id_card_generating:
            messagebox.showwarning("In Progress", "An ID card generation job is already running.")
            return

        raw_emails = self.id_card_emails_box.get("0.0", "end").strip()
        if not raw_emails:
            messagebox.showerror("Error", "Please enter at least one employee email address.")
            return

        design = self.id_card_design.get().strip()
        photos_dir = self.id_card_photos_dir.get().strip() or None
        if photos_dir and not os.path.exists(photos_dir):
            messagebox.showwarning("Warning", f"Specified photos folder does not exist:\n{photos_dir}\nFalling back to Keka & Slack.")
            photos_dir = None

        m_str = self.id_card_photo_match_mode.get().lower()
        match_mode = "auto" if "auto" in m_str else ("emp_no" if "emp" in m_str else "email")

        self.is_id_card_generating = True
        self.btn_id_card_email_gen.configure(state="disabled")
        if hasattr(self, "btn_id_card_bulk"):
            self.btn_id_card_bulk.configure(state="disabled")
        self.id_card_prog.grid()
        self.id_card_prog.start()
        ui.update_status(self.id_card_dot, self.id_card_lbl, f"Syncing with Keka & generating ({design})...", "processing")
        self._append_id_card_log(f"\n{'='*60}\n[EMAIL SYNC] Starting Instant Email Sync ({design})\n{'='*60}\n")

        def _job():
            try:
                res = id_card.run_email_batch_job(
                    emails_input=raw_emails,
                    design_name=design,
                    photos_dir=photos_dir,
                    photo_match_mode=match_mode,
                    log_callback=self._append_id_card_log,
                    address_mapping=self.office_addresses_data
                )
                ok, report_path, msg = res[0], res[1], res[2]
                out_folder = res[3] if len(res) > 3 else (str(Path(report_path).parent.parent) if report_path else "")

                def _finish():
                    self.is_id_card_generating = False
                    self.btn_id_card_email_gen.configure(state="normal")
                    if hasattr(self, "btn_id_card_bulk"):
                        self.btn_id_card_bulk.configure(state="normal")
                    self.id_card_prog.stop()
                    self.id_card_prog.grid_remove()
                    if out_folder:
                        self.last_id_card_output_dir = out_folder
                    if ok:
                        self.last_report_path = report_path
                        ui.update_status(self.id_card_dot, self.id_card_lbl, "Email sync completed!", "success")
                        self._append_id_card_log(f"\n[✓] SUCCESS: Email batch generation finished!\n[📁] Output Folder: {out_folder}\n[📊] Report: {report_path}\n")
                        messagebox.showinfo(
                            "ID Cards Generated",
                            f"ID cards generated successfully via Instant Email Sync!\n\n"
                            f"📁 Output Folder in Downloads:\n{out_folder}\n\n"
                            f"📊 Audit Report:\n{report_path}"
                        )
                    else:
                        ui.update_status(self.id_card_dot, self.id_card_lbl, f"Finished: {msg}", "warning")
                        self._append_id_card_log(f"\n[!] Finished with warnings/errors: {msg}\n")
                self.after(0, _finish)
            except Exception as e:
                def _err():
                    self.is_id_card_generating = False
                    self.btn_id_card_email_gen.configure(state="normal")
                    if hasattr(self, "btn_id_card_bulk"):
                        self.btn_id_card_bulk.configure(state="normal")
                    self.id_card_prog.stop()
                    self.id_card_prog.grid_remove()
                    ui.update_status(self.id_card_dot, self.id_card_lbl, f"Error: {e}", "error")
                    self._append_id_card_log(f"\n[!] Unexpected Exception: {e}\n")
                self.after(0, _err)

        threading.Thread(target=_job, daemon=True).start()

    def start_id_card_preview_from_email_mode(self):
        """Picks the first email from the Email Sync text box and previews it."""
        raw_emails = self.id_card_emails_box.get("0.0", "end").strip()
        candidates = [e.strip() for e in re.split(r'[;,\n\r\t]+', raw_emails) if e.strip() and "@" in e]
        if not candidates:
            messagebox.showerror("Error", "Please enter at least one valid email address in the Email Sync box.")
            return
        target_email = candidates[0]
        self.start_id_card_preview(email_override=target_email)

    def start_id_card_preview(self, email_override=None):
        """Generates a single ID card preview PDF for testing."""
        if self.is_id_card_generating:
            messagebox.showwarning("In Progress", "An ID card generation job is already running.")
            return

        email = (email_override or self.id_card_preview_email.get()).strip()
        if not email:
            messagebox.showerror("Error", "Please enter an employee email for preview.")
            return

        excel_file = self.id_card_excel_file.get().strip() or None
        photos_dir = self.id_card_photos_dir.get().strip() or None
        m_str = self.id_card_photo_match_mode.get().lower()
        match_mode = "auto" if "auto" in m_str else ("emp_no" if "emp" in m_str else "email")

        design = self.id_card_design.get().strip()
        self.is_id_card_generating = True
        if hasattr(self, "btn_id_card_email_gen"):
            self.btn_id_card_email_gen.configure(state="disabled")
        if hasattr(self, "btn_id_card_bulk"):
            self.btn_id_card_bulk.configure(state="disabled")
        self.id_card_prog.grid()
        self.id_card_prog.start()
        ui.update_status(self.id_card_dot, self.id_card_lbl, f"Generating preview ({design})...", "processing")
        self._append_id_card_log(f"\n{'='*60}\n[PREVIEW] Starting {design} ID card preview for: {email}\n{'='*60}\n")

        def _job():
            try:
                res = id_card.run_preview_job(
                    preview_email=email,
                    design_name=design,
                    excel_path=excel_file,
                    photos_dir=photos_dir,
                    photo_match_mode=match_mode,
                    log_callback=self._append_id_card_log,
                    address_mapping=self.office_addresses_data
                )
                ok, pdf_path, msg = res[0], res[1], res[2]
                out_folder = res[3] if len(res) > 3 else (str(Path(pdf_path).parent) if pdf_path else "")

                def _finish():
                    self.is_id_card_generating = False
                    if hasattr(self, "btn_id_card_email_gen"):
                        self.btn_id_card_email_gen.configure(state="normal")
                    if hasattr(self, "btn_id_card_bulk"):
                        self.btn_id_card_bulk.configure(state="normal")
                    self.id_card_prog.stop()
                    self.id_card_prog.grid_remove()
                    if out_folder:
                        self.last_id_card_output_dir = out_folder
                    if ok:
                        self.last_preview_pdf_path = pdf_path
                        ui.update_status(self.id_card_dot, self.id_card_lbl, "Preview ready!", "success")
                        self._append_id_card_log(f"\n[✓] SUCCESS: Preview PDF generated: {pdf_path}\n[📁] Folder: {out_folder}\n")
                    else:
                        ui.update_status(self.id_card_dot, self.id_card_lbl, f"Preview failed: {msg}", "error")
                        self._append_id_card_log(f"\n[!] FAILED: {msg}\n")
                self.after(0, _finish)
            except Exception as e:
                def _err():
                    self.is_id_card_generating = False
                    if hasattr(self, "btn_id_card_email_gen"):
                        self.btn_id_card_email_gen.configure(state="normal")
                    if hasattr(self, "btn_id_card_bulk"):
                        self.btn_id_card_bulk.configure(state="normal")
                    self.id_card_prog.stop()
                    self.id_card_prog.grid_remove()
                    ui.update_status(self.id_card_dot, self.id_card_lbl, f"Error: {e}", "error")
                    self._append_id_card_log(f"\n[!] Unexpected Exception: {e}\n")
                self.after(0, _err)

        threading.Thread(target=_job, daemon=True).start()

    def start_id_card_bulk(self):
        """Runs bulk ID card generation for all employees in Excel."""
        if self.is_id_card_generating:
            messagebox.showwarning("In Progress", "An ID card generation job is already running.")
            return

        excel_file = self.id_card_excel_file.get().strip()
        if excel_file and not os.path.exists(excel_file):
            messagebox.showerror("Error", f"Selected Excel file does not exist:\n{excel_file}")
            return

        photos_dir = self.id_card_photos_dir.get().strip() or None
        m_str = self.id_card_photo_match_mode.get().lower()
        match_mode = "auto" if "auto" in m_str else ("emp_no" if "emp" in m_str else "email")

        design = self.id_card_design.get().strip()
        confirm = messagebox.askyesno(
            "Confirm Bulk Generation",
            f"Run Bulk ID Card Generation for design '{design}'?\n\n"
            f"Excel Source: {Path(excel_file).name if excel_file else 'Default'}\n"
            f"Photos Folder: {Path(photos_dir).name if photos_dir else 'Keka / Slack (Auto-Fetch)'}\n\n"
            f"This will validate all records, download photos, and create a new timestamped folder in Downloads."
        )
        if not confirm:
            return

        self.is_id_card_generating = True
        if hasattr(self, "btn_id_card_email_gen"):
            self.btn_id_card_email_gen.configure(state="disabled")
        if hasattr(self, "btn_id_card_bulk"):
            self.btn_id_card_bulk.configure(state="disabled")
        self.id_card_prog.grid()
        self.id_card_prog.start()
        ui.update_status(self.id_card_dot, self.id_card_lbl, f"Running Bulk Generation ({design})...", "processing")
        self._append_id_card_log(f"\n{'='*60}\n[BULK] Starting Bulk ID Card Generation ({design})\n{'='*60}\n")

        def _job():
            try:
                res = id_card.run_bulk_job(
                    design_name=design,
                    excel_path=excel_file,
                    photos_dir=photos_dir,
                    photo_match_mode=match_mode,
                    log_callback=self._append_id_card_log,
                    address_mapping=self.office_addresses_data
                )
                ok, report_path, summary, msg = res[0], res[1], res[2], res[3]
                out_folder = res[4] if len(res) > 4 else (str(Path(report_path).parent.parent) if report_path else "")

                def _finish():
                    self.is_id_card_generating = False
                    if hasattr(self, "btn_id_card_email_gen"):
                        self.btn_id_card_email_gen.configure(state="normal")
                    if hasattr(self, "btn_id_card_bulk"):
                        self.btn_id_card_bulk.configure(state="normal")
                    self.id_card_prog.stop()
                    self.id_card_prog.grid_remove()
                    if out_folder:
                        self.last_id_card_output_dir = out_folder
                    if ok:
                        self.last_report_path = report_path
                        ui.update_status(self.id_card_dot, self.id_card_lbl, "Bulk generation completed!", "success")
                        self._append_id_card_log(f"\n[✓] SUCCESS: Bulk generation finished!\n[📁] Output Folder: {out_folder}\n[📊] Report: {report_path}\n")
                        messagebox.showinfo(
                            "Bulk Generation Complete",
                            f"ID cards generated successfully!\n\n"
                            f"📁 Output Folder in Downloads:\n{out_folder}\n\n"
                            f"📊 Audit Report:\n{report_path}"
                        )
                    else:
                        ui.update_status(self.id_card_dot, self.id_card_lbl, f"Finished: {msg}", "warning")
                        self._append_id_card_log(f"\n[!] Finished with warnings/errors: {msg}\n")
                self.after(0, _finish)
            except Exception as e:
                def _err():
                    self.is_id_card_generating = False
                    if hasattr(self, "btn_id_card_email_gen"):
                        self.btn_id_card_email_gen.configure(state="normal")
                    if hasattr(self, "btn_id_card_bulk"):
                        self.btn_id_card_bulk.configure(state="normal")
                    self.id_card_prog.stop()
                    self.id_card_prog.grid_remove()
                    ui.update_status(self.id_card_dot, self.id_card_lbl, f"Error: {e}", "error")
                    self._append_id_card_log(f"\n[!] Unexpected Exception: {e}\n")
                self.after(0, _err)

        threading.Thread(target=_job, daemon=True).start()

    def open_id_card_preview_pdf(self):
        """Opens the generated single preview PDF."""
        target = self.last_preview_pdf_path
        if not target or not Path(target).exists():
            latest_dir = self.last_id_card_output_dir or id_card.get_latest_output_dir()
            if latest_dir and Path(latest_dir).exists():
                design = self.id_card_design.get().strip()
                out_name = "Modern" if design.lower() == "modern" else "Classic"
                fallback = Path(latest_dir) / out_name / f"IDCard_Preview_{out_name}.pdf"
                if fallback.exists():
                    target = str(fallback.resolve())

        if not target or not Path(target).exists():
            messagebox.showinfo("Preview Not Found", "No preview PDF found. Generate a preview card first.")
            return

        ok, err = id_card.open_system_path(target)
        if not ok:
            messagebox.showerror("Error", f"Could not open preview PDF:\n{err}")

    def open_id_card_output_folder(self):
        """Opens the latest generated output directory in Downloads."""
        target_dir = self.last_id_card_output_dir
        if not target_dir or not Path(target_dir).exists():
            target_dir = id_card.get_latest_output_dir()
        ok, err = id_card.open_system_path(str(target_dir))
        if not ok:
            messagebox.showerror("Error", f"Could not open folder:\n{err}")

    def open_id_card_report_file(self):
        """Opens the Excel generation audit report."""
        target = self.last_report_path
        if not target or not Path(target).exists():
            latest_dir = self.last_id_card_output_dir or id_card.get_latest_output_dir()
            if latest_dir and Path(latest_dir).exists():
                reports_dir = Path(latest_dir) / "Reports"
                if reports_dir.exists():
                    candidates = list(reports_dir.glob("*.xlsx"))
                    if candidates:
                        target = str(candidates[0].resolve())
                if not target:
                    candidates = list(Path(latest_dir).rglob("*Report*.xlsx"))
                    if candidates:
                        target = str(candidates[0].resolve())

        if not target or not Path(target).exists():
            messagebox.showinfo("Report Not Found", "No audit report found yet. Run bulk generation first.")
            return

        ok, err = id_card.open_system_path(str(target))
        if not ok:
            messagebox.showerror("Error", f"Could not open report:\n{err}")

    def clear_id_card_console(self):
        """Clears the live log console."""
        self.id_card_log_text.configure(state="normal")
        self.id_card_log_text.delete("0.0", "end")
        self.id_card_log_text.configure(state="disabled")


    def start_transform(self):
        if not self.selected_input_file.get():
            messagebox.showerror("Error", "Please select a file.")
            return
        self.is_processing = True
        self.btn_kra_tf.configure(state="disabled")
        self.kra_prog.grid()
        self.kra_prog.start()
        ui.update_status(self.kra_dot, self.kra_lbl, "Transforming...", "processing")
        threading.Thread(target=self._run_transform_job, daemon=True).start()

    def cancel_transform(self): pass # Unused currently, logic can be complex

    def _transform_success(self, out_path, cnt):
        self.is_processing = False
        self.btn_kra_tf.configure(state="normal")
        self.kra_prog.stop()
        self.kra_prog.grid_remove()
        ui.update_status(self.kra_dot, self.kra_lbl, f"Success • {cnt} sheets", "success")
        messagebox.showinfo("Done", f"File transformed successfully.\n\nSaved to:\n{out_path}")

    def _transform_error(self, err):
        self.is_processing = False
        self.btn_kra_tf.configure(state="normal")
        self.kra_prog.stop()
        self.kra_prog.grid_remove()
        ui.update_status(self.kra_dot, self.kra_lbl, "Failed", "error")
        messagebox.showerror("Error", err)

    def start_generate(self):
        mode = self.gen_mode_seg.get() if hasattr(self, 'gen_mode_seg') else "Existing KRA Upload"
        file_path = self.selected_okr_input_file.get() if mode == "OKR Upload" else self.selected_gen_input_file.get()
        if not file_path:
            messagebox.showerror("Error", "Please select a file.")
            return
        self.is_generating = True
        self.btn_gen.configure(state="disabled")
        self.gen_prog.grid()
        self.gen_prog.start()
        ui.update_status(self.gen_dot, self.gen_lbl, "Generating...", "processing")
        threading.Thread(target=self._run_generate_job, daemon=True).start()

    def cancel_generate(self): pass

    def _reset_gen_ui_state(self):
        self.is_generating = False

        self.btn_gen.configure(state="normal")
        self.gen_prog.stop()
        self.gen_prog.grid_remove()

    def _generate_success(self, out_path):
        self._reset_gen_ui_state()
        ui.update_status(self.gen_dot, self.gen_lbl, "Success", "success")
        messagebox.showinfo("Done", f"Generated successfully:\n{out_path}")

    def _generate_error(self, err):
        self._reset_gen_ui_state()
        ui.update_status(self.gen_dot, self.gen_lbl, "Failed", "error")
        messagebox.showerror("Error", err)

    def start_process_absent(self):
        if not (self.absent_emp_file.get() and self.absent_att_file.get() and self.absent_wfh_file.get()):
            messagebox.showerror("Error", "Please select all 3 files.")
            return
        self.btn_absent.configure(state="disabled")
        ui.update_status(self.absent_dot, self.absent_lbl, "Processing...", "processing")
        threading.Thread(target=self._run_absent_job, daemon=True).start()

    def _absent_success(self, path):
        self.btn_absent.configure(state="normal")
        ui.update_status(self.absent_dot, self.absent_lbl, "Success", "success")
        messagebox.showinfo("Done", f"Saved to:\n{path}")

    def _absent_error(self, err):
        self.btn_absent.configure(state="normal")
        ui.update_status(self.absent_dot, self.absent_lbl, "Failed", "error")
        messagebox.showerror("Error", err)

    def start_process_att(self):
        if not self.att_summary_file.get():
            messagebox.showerror("Error", "Select file first.")
            return
        self.btn_att.configure(state="disabled")
        ui.update_status(self.att_dot, self.att_lbl, "Processing...", "processing")
        threading.Thread(target=self._run_att_job, daemon=True).start()

    def _att_success(self, path):
        self.btn_att.configure(state="normal")
        ui.update_status(self.att_dot, self.att_lbl, "Success", "success")
        messagebox.showinfo("Done", f"Saved to:\n{path}")

    def _att_error(self, err):
        self.btn_att.configure(state="normal")
        ui.update_status(self.att_dot, self.att_lbl, "Failed", "error")
        messagebox.showerror("Error", err)

    def start_process_time_leave(self):
        if not self.tl_perf_files:
            messagebox.showerror("Error", "Please select at least one Daily Performance Report file.")
            return
        if not (self.tl_leave_active_files or self.tl_leave_inactive_files or self.tl_wfh_files):
            if not messagebox.askyesno("Confirm", "No Leave or WFH application files were selected. Proceed anyway?"):
                return

        out_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"Daily_Performance_Report_Updated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        if not out_path:
            return

        self.btn_tl.configure(state="disabled")
        self.tl_prog.grid()
        self.tl_prog.set(0)
        self.tl_prog_lbl.grid()
        self.tl_prog_lbl.configure(text="Initializing data reconciliation...")
        ui.update_status(self.tl_dot, self.tl_lbl, "Starting (0%)...", "processing")
        threading.Thread(target=self._run_time_leave_job, args=(out_path,), daemon=True).start()

    def _update_tl_progress(self, pct: float, msg: str):
        self.tl_prog.set(max(0.0, min(1.0, pct)))
        self.tl_prog_lbl.configure(text=msg)
        pct_int = int(round(pct * 100))
        ui.update_status(self.tl_dot, self.tl_lbl, f"Processing ({pct_int}%)", "processing")

    def _run_time_leave_job(self, out_path):
        def _on_progress(pct: float, msg: str):
            self.after(0, lambda p=pct, m=msg: self._update_tl_progress(p, m))

        try:
            import time_leave_master
            import importlib
            importlib.reload(time_leave_master)
            stats = time_leave_master.reconcile_time_and_leave(
                perf_files=self.tl_perf_files,
                leave_active_files=self.tl_leave_active_files,
                leave_inactive_files=self.tl_leave_inactive_files,
                wfh_files=self.tl_wfh_files,
                output_path=out_path,
                progress_callback=_on_progress
            )
            self.after(0, lambda s=stats, o=out_path: self._time_leave_success(s, o))
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda m=err_msg: self._time_leave_error(m))


    def _time_leave_success(self, stats, out_path):
        self.btn_tl.configure(state="normal")
        self.tl_prog.set(1.0)
        self.tl_prog_lbl.configure(text=f"Completed {stats['total_rows']:,} rows • {stats['matched_leave_count']:,} leaves, {stats['matched_wfh_count']:,} WFH matched")
        ui.update_status(self.tl_dot, self.tl_lbl, "Success", "success")

        msg = (
            f"Daily Performance Report updated successfully!\n\n"
            f"• Total Rows: {stats['total_rows']:,}\n"
            f"• Matched Leave records: {stats['matched_leave_count']:,}\n"
            f"• Matched WFH records: {stats['matched_wfh_count']:,}\n"
        )
        if stats.get('quantity_violation_count', 0) > 0:
            msg += f"\n⚠️ Warning: {stats['quantity_violation_count']} date entries have total quantity > 1.0 per employee."
        if stats.get('unmatched_applications_count', 0) > 0:
            msg += f"\nℹ️ Unmatched Applications: {stats['unmatched_applications_count']:,} applications could not be matched."

        msg += f"\n\nMain Output Saved to:\n{out_path}"
        if stats.get('error_log_path'):
            msg += f"\n\nError Log File Saved to:\n{stats['error_log_path']}"

        messagebox.showinfo("Done", msg)


    def _time_leave_error(self, err):
        self.btn_tl.configure(state="normal")
        self.tl_prog.set(0)
        self.tl_prog_lbl.configure(text=f"Error: {err}")
        ui.update_status(self.tl_dot, self.tl_lbl, "Failed", "error")
        messagebox.showerror("Error", err)

    def _run_absent_job(self):
        try:
            import absent_management
            out_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")], initialfile="Absent_Report.xlsx")
            if not out_path:
                self.after(0, lambda: self._absent_error("No output path selected"))
                return
            absent_management.process_absent_management(self.absent_emp_file.get(), self.absent_att_file.get(), self.absent_wfh_file.get(), out_path)
            self.after(0, lambda: self._absent_success(out_path))
        except Exception as e:
            self.after(0, lambda: self._absent_error(str(e)))

    def _run_att_job(self):
        try:
            import attendance_summary
            out_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")], initialfile="Attendance_Summary.xlsx")
            if not out_path:
                self.after(0, lambda: self._att_error("No output path selected"))
                return
            attendance_summary.process_attendance_summary(self.att_summary_file.get(), out_path)
            self.after(0, lambda: self._att_success(out_path))
        except Exception as e:
            self.after(0, lambda: self._att_error(str(e)))

    def _run_generate_job(self):
        try:
            mode = self.gen_mode_seg.get() if hasattr(self, 'gen_mode_seg') else "Existing KRA Upload"
            
            if mode == "OKR Upload":
                from generate_upload import generate_okr_upload_file
                input_path = Path(self.selected_okr_input_file.get())
            else:
                from generate_upload import generate_upload_file
                input_path = Path(self.selected_gen_input_file.get())
            
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            output_path = downloads / input_path.name

            mapping_text = self.gen_mapping_text.get("0.0", "end").strip()
            if not mapping_text:
                raise ValueError("Employee mapping cannot be empty.")
            
            employees = {}
            
            for line in mapping_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) == 3:
                    emp_id = parts[0].strip()
                    emp_name = parts[1].strip()
                    sheet_name = parts[2].strip()
                    
                    if sheet_name not in employees:
                        employees[sheet_name] = []
                    employees[sheet_name].append((emp_id, emp_name))
                else:
                    raise ValueError(f"Invalid format: '{line}'. Expected 'EMP ID, Name, Designation'.")

            if mode == "OKR Upload":
                generate_okr_upload_file(str(input_path), str(output_path), employees)
            else:
                generate_upload_file(str(input_path), str(output_path), employees)

            self.after(0, lambda: self._generate_success(output_path))

        except Exception as exc:
            import traceback
            error_text = f"{exc}\n\n{traceback.format_exc()}"
            self.after(0, lambda: self._generate_error(error_text))

    def _run_transform_job(self):
        try:
            input_path = Path(self.selected_input_file.get())
            output_path = self._build_output_path(input_path)

            transformed_sheets = {}

            with pd.ExcelFile(input_path) as excel_file:
                for sheet_name in excel_file.sheet_names:
                    df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)

                    transformed_df = App.transform_kra_dataframe(df)
                    if transformed_df is not None and not transformed_df.empty:
                        transformed_sheets[sheet_name] = transformed_df

            if not transformed_sheets:
                raise ValueError("No valid non-empty sheets found to transform.")

            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                for sheet_name, t_df in transformed_sheets.items():
                    safe_name = str(sheet_name)[:31] if sheet_name else "Sheet1"
                    export_df = t_df[["KRA", "KPI", "Weightage", "KPI %", "KRA %"]]
                    export_df.to_excel(writer, sheet_name=safe_name, index=False)

            self.apply_excel_formatting(output_path)
            self.after(0, lambda: self._transform_success(output_path, len(transformed_sheets)))

        except Exception as exc:
            error_text = f"{exc}\n\n{traceback.format_exc()}"
            self.after(0, lambda: self._transform_error(error_text))

    def _build_output_path(self, input_path: Path) -> Path:
        downloads = Path.home() / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        return downloads / input_path.name

    @staticmethod
    def is_effectively_empty(df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            return True
        temp = df.copy().dropna(how="all")
        return temp.empty

    @staticmethod
    def is_serial_number_series(series: pd.Series) -> bool:
        non_null = series.dropna()
        if non_null.empty:
            return False

        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if numeric.empty:
            return False

        # Ensure that at least 50% of the column is numeric so we don't 
        # misclassify text columns that happen to have a few sequential numbers
        if len(numeric) < len(non_null) * 0.5:
            return False

        values = numeric.astype(int).tolist()
        if len(values) < 2:
            return values[0] in [0, 1]

        sequential_matches = 0
        for i in range(1, len(values)):
            if values[i] == values[i - 1] + 1:
                sequential_matches += 1

        return sequential_matches >= max(1, len(values) - 2)

    @staticmethod
    def first_non_null(series: pd.Series):
        non_null = series.dropna()
        return non_null.iloc[0] if not non_null.empty else None

    @staticmethod
    def normalize_kra_pct(value):
        if pd.isna(value) or value == "":
            return ""
        try:
            num = float(value)
            if num <= 1.0:
                return int(round(num * 100))
            return int(round(num))
        except Exception:
            return ""

    @classmethod
    def transform_kra_dataframe(cls, df: pd.DataFrame):
        if cls.is_effectively_empty(df):
            return None

        df = df.copy()
        df = df.dropna(how="all").reset_index(drop=True)

        if df.shape[1] < 3:
            return None

        header_row_idx = -1
        kra_col_idx = -1
        kpi_col_idx = -1
        w_cols = []

        # 1. Dynamically find header row and columns based on keywords
        for i in range(min(30, len(df))):
            row_vals = df.iloc[i].astype(str).str.lower().str.strip()
            
            kc, pc = -1, -1
            wc = []
            
            for col_idx, val in enumerate(row_vals):
                if pd.isna(val) or len(val) < 2:
                    continue
                
                # Identify columns
                if kc == -1 and any(k in val for k in ["kra", "key result", "objective", "goal", "responsibility"]):
                    kc = col_idx
                elif pc == -1 and any(k in val for k in ["kpi", "key performance", "indicator", "measure", "metric", "parameter"]):
                    pc = col_idx
                elif any(k in val for k in ["weight", "wt", "wgt", "%", "proportion"]):
                    wc.append(col_idx)
            
            if kc != -1 and pc != -1:
                header_row_idx = i
                kra_col_idx = kc
                kpi_col_idx = pc
                w_cols = wc
                break

        # 2. Extract the appropriate columns
        if header_row_idx != -1:
            data_df = df.iloc[header_row_idx + 1:].reset_index(drop=True)
            kra_col = data_df.iloc[:, kra_col_idx]
            kpi_col = data_df.iloc[:, kpi_col_idx]
            
            if len(w_cols) >= 2:
                col3 = data_df.iloc[:, w_cols[0]]
                col4 = data_df.iloc[:, w_cols[1]]
            elif len(w_cols) == 1:
                col3 = data_df.iloc[:, w_cols[0]]
                col4 = None
            else:
                # Fallback to columns immediately following KPI if no weight keywords found
                next_cols = [c for c in range(data_df.shape[1]) if c > kpi_col_idx and c not in [kra_col_idx, kpi_col_idx]]
                if len(next_cols) >= 2:
                    col3 = data_df.iloc[:, next_cols[0]]
                    col4 = data_df.iloc[:, next_cols[1]]
                elif len(next_cols) == 1:
                    col3 = data_df.iloc[:, next_cols[0]]
                    col4 = None
                else:
                    return None
        else:
            # 3. Fallback to positional logic if headers are not explicitly found
            start_idx = 0
            if cls.is_serial_number_series(df.iloc[:, 0]):
                start_idx = 1
                
            if df.shape[1] - start_idx < 3:
                return None
                
            # Assume row 0 is the header (since we read with header=None) and skip it
            data_df = df.iloc[1:].reset_index(drop=True)
            
            kra_col = data_df.iloc[:, start_idx]
            kpi_col = data_df.iloc[:, start_idx + 1]
            col3 = data_df.iloc[:, start_idx + 2]
            col4 = data_df.iloc[:, start_idx + 3] if data_df.shape[1] - start_idx >= 4 else None

        # CASE A: 4 or more usable columns
        # KRA | KPI | KRA Weightage | KPI Weightage
        if col4 is not None:
            working = pd.DataFrame({
                "KRA_RAW": kra_col,
                "KPI_RAW": kpi_col,
                "KRA_W_RAW": col3,
                "KPI_W_RAW": col4,
            })

            working["KRA"] = working["KRA_RAW"].ffill()
            working["KRA"] = working["KRA"].astype(str).str.strip()
            working["KPI"] = working["KPI_RAW"].astype(str).str.strip()

            working = working[
                (working["KRA"].notna()) &
                (working["KRA"] != "") &
                (working["KRA"].str.lower() != "nan") &
                (working["KPI"].notna()) &
                (working["KPI"] != "") &
                (working["KPI"].str.lower() != "nan")
            ].copy()

            if working.empty:
                return None

            output_rows = []

            for kra_name, group in working.groupby("KRA", sort=False):
                group = group.copy().reset_index(drop=True)

                raw_kra_pct_value = cls.first_non_null(group["KRA_W_RAW"])
                kra_pct = cls.normalize_kra_pct(raw_kra_pct_value)

                numeric_weights = pd.to_numeric(group["KPI_W_RAW"], errors="coerce").fillna(0)
                total_w = numeric_weights.sum()

                if total_w > 0:
                    kpi_pcts = [round((w / total_w) * 100, 2) for w in numeric_weights.tolist()]
                    
                    diff = round(100.0 - sum(kpi_pcts), 2)
                    if kpi_pcts:
                        kpi_pcts[-1] = round(kpi_pcts[-1] + diff, 2)
                else:
                    kpi_pcts = [0.0] * len(group)

                for i, (_, row) in enumerate(group.iterrows()):
                    raw_weight = row["KPI_W_RAW"]
                    if pd.isna(raw_weight):
                        raw_weight = ""

                    output_rows.append({
                        "KRA": kra_name,
                        "KPI": row["KPI"],
                        "Weightage": raw_weight,
                        "KPI %": round(kpi_pcts[i], 2),
                        "KRA %": kra_pct,
                    })

            return pd.DataFrame(output_rows)

        # CASE B: exactly 3 usable columns
        # KRA | KPI | Row Weightage
        working = pd.DataFrame({
            "KRA_RAW": kra_col,
            "KPI_RAW": kpi_col,
            "ROW_W_RAW": col3,
        })

        working["KRA"] = working["KRA_RAW"].ffill()
        working["KRA"] = working["KRA"].astype(str).str.strip()
        working["KPI"] = working["KPI_RAW"].astype(str).str.strip()

        working = working[
            (working["KRA"].notna()) &
            (working["KRA"] != "") &
            (working["KRA"].str.lower() != "nan") &
            (working["KPI"].notna()) &
            (working["KPI"] != "") &
            (working["KPI"].str.lower() != "nan")
        ].copy()

        if working.empty:
            return None

        output_rows = []

        for kra_name, group in working.groupby("KRA", sort=False):
            group = group.copy().reset_index(drop=True)

            numeric_weights = pd.to_numeric(group["ROW_W_RAW"], errors="coerce").fillna(0)
            total_w = numeric_weights.sum()

            if total_w > 0:
                kpi_pcts = [round((w / total_w) * 100, 2) for w in numeric_weights.tolist()]
                
                diff = round(100.0 - sum(kpi_pcts), 2)
                if kpi_pcts:
                    kpi_pcts[-1] = round(kpi_pcts[-1] + diff, 2)
            else:
                kpi_pcts = [0.0] * len(group)

            kra_pct = cls.normalize_kra_pct(total_w)

            for i, (_, row) in enumerate(group.iterrows()):
                raw_weight = row["ROW_W_RAW"]
                if pd.isna(raw_weight):
                    raw_weight = ""

                output_rows.append({
                    "KRA": kra_name,
                    "KPI": row["KPI"],
                    "Weightage": raw_weight,
                    "KPI %": round(kpi_pcts[i], 2),
                    "KRA %": kra_pct,
                })

        return pd.DataFrame(output_rows)

    @staticmethod
    def apply_excel_formatting(output_path: Path):
        wb = load_workbook(output_path)

        header_fill = PatternFill(fill_type="solid", start_color="1F4E79", end_color="1F4E79")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        white_fill = PatternFill(fill_type="solid", start_color="FFFFFF", end_color="FFFFFF")
        blue_fill = PatternFill(fill_type="solid", start_color="DCE6F1", end_color="DCE6F1")
        yellow_fill = PatternFill(fill_type="solid", start_color="FFF2CC", end_color="FFF2CC")

        left_alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        center_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        row_font = Font(name="Calibri", size=10)

        thin_side = Side(style="thin", color="BFBFBF")
        thin_border = Border() # No border as requested

        for ws in wb.worksheets:
            headers = ["KRA", "KPI", "Weightage", "KPI %", "KRA %"]
            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(row=1, column=col_idx)
                cell.value = header
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_alignment
                cell.border = thin_border

            ws.row_dimensions[1].height = 30

            ws.column_dimensions["A"].width = 50
            ws.column_dimensions["B"].width = 80
            ws.column_dimensions["C"].width = 12
            ws.column_dimensions["D"].width = 10
            ws.column_dimensions["E"].width = 10

            current_fill_name = "white"
            previous_kra = None

            max_row = ws.max_row

            for row_num in range(2, max_row + 1):
                kra_value = ws.cell(row=row_num, column=1).value
                kra_pct_value = ws.cell(row=row_num, column=5).value

                if kra_value != previous_kra:
                    if previous_kra is not None:
                        current_fill_name = "blue" if current_fill_name == "white" else "white"
                    previous_kra = kra_value

                row_fill = white_fill if current_fill_name == "white" else blue_fill

                if kra_pct_value in [None, ""]:
                    row_fill = yellow_fill

                for col_num in range(1, 6):
                    cell = ws.cell(row=row_num, column=col_num)
                    cell.fill = row_fill
                    cell.border = thin_border
                    cell.font = row_font

                    if col_num in [1, 2]:
                        cell.alignment = left_alignment
                    else:
                        cell.alignment = center_alignment

                    if col_num == 4:
                        cell.number_format = "0.00"

                ws.row_dimensions[row_num].height = 30

        wb.save(output_path)


if __name__ == "__main__":
    app = App()
    app.mainloop()
