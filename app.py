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

from dotenv import load_dotenv
load_dotenv(override=True)

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
        now_dt = datetime.now()
        first_day_of_month = now_dt.replace(day=1)
        self.absent_from_date_var = ctk.StringVar(value=first_day_of_month.strftime("%d-%m-%Y"))
        self.absent_to_date_var = ctk.StringVar(value=now_dt.strftime("%d-%m-%Y"))
        self.absent_include_portal_var = ctk.BooleanVar(value=True)
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
        self.last_time_leave_output_path = None

        # Connectors state (Slack & Keka)
        self.connector_active_tab = ctk.StringVar(value="Slack")
        default_slack_val = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_BOT_ID", "")
        self.slack_bot_token_var = ctk.StringVar(value=default_slack_val)
        self.keka_subdomain_var = ctk.StringVar(value=os.getenv("KEKA_SUBDOMAIN", "moshpit"))
        self.keka_client_id_var = ctk.StringVar(value=os.getenv("KEKA_CLIENT_ID", ""))
        self.keka_client_secret_var = ctk.StringVar(value=os.getenv("KEKA_CLIENT_SECRET", ""))
        self.keka_api_key_var = ctk.StringVar(value=os.getenv("KEKA_API_KEY", ""))
        self.keka_login_email_var = ctk.StringVar(value=os.getenv("KEKA_LOGIN_EMAIL", ""))
        self.keka_login_password_var = ctk.StringVar(value=os.getenv("KEKA_LOGIN_PASSWORD", ""))


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

        # Time and Leave Master multi-file lists & state
        self.tl_perf_files = []
        self.tl_leave_active_files = []
        self.tl_leave_inactive_files = []
        self.tl_wfh_files = []
        self.tl_emp_master_files = []
        self.tl_from_date_var = ctk.StringVar(value=first_day_of_month.strftime("%d-%m-%Y"))
        self.tl_to_date_var = ctk.StringVar(value=now_dt.strftime("%d-%m-%Y"))
        
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
            text="",
            image=ui.get_icon("zap", size=(24, 24), color=ui.COLOR_ACCENT),
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
            text="",
            image=ui.get_icon("home", size=(22, 22), color=ui.COLOR_TEXT),
            width=46,
            height=42,
            corner_radius=8,
            anchor="center",
            fg_color=ui.COLOR_NAV_ACTIVE,
            hover_color=ui.COLOR_NAV_HOVER,
            command=self._on_transform_parent_clicked,
        )
        self.nav_parent_btn._icon_name = "home"
        self.nav_parent_btn.grid(row=2, column=0, padx=6, pady=4)
        ui.create_tooltip(self.nav_parent_btn, "Transform")

        self.nav_parent_btn.bind("<Enter>", lambda e: self._on_nav_btn_enter("transform"), add="+")
        self.nav_parent_btn.bind("<Leave>", lambda e: self._on_nav_btn_leave("transform"), add="+")

        # Offscreen child buttons container for backward compatibility
        self._offscreen_compat = ctk.CTkFrame(self)
        self.sub_menu_frame = ctk.CTkFrame(self._offscreen_compat, fg_color="transparent")
        transform_sub_items = [
            ("transform", "KRA Management", "kra"),
            ("time_leave", "Time and Leave Master", "calendar"),
            ("att_summary", "Attendance Summary", "attendance"),
            ("id_card", "ID Card Generator", "id_card"),
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
            text="",
            image=ui.get_icon("chart", size=(22, 22), color=ui.COLOR_TEXT_SEC),
            width=46,
            height=42,
            corner_radius=8,
            anchor="center",
            fg_color="transparent",
            hover_color=ui.COLOR_NAV_HOVER,
            command=self._on_analyse_parent_clicked,
        )
        self.analyse_parent_btn._icon_name = "chart"
        self.analyse_parent_btn.grid(row=3, column=0, padx=6, pady=4)
        ui.create_tooltip(self.analyse_parent_btn, "Analyse")

        self.analyse_parent_btn.bind("<Enter>", lambda e: self._on_nav_btn_enter("analyse"), add="+")
        self.analyse_parent_btn.bind("<Leave>", lambda e: self._on_nav_btn_leave("analyse"), add="+")

        # Offscreen child buttons container for Analyse backward compatibility
        self.analyse_sub_menu_frame = ctk.CTkFrame(self._offscreen_compat, fg_color="transparent")
        analyse_sub_items = [
            ("workforce_intelligence", "Workforce Intelligence", "users"),
            ("analyse_upload", "Upload", "upload"),
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
            text="",
            image=ui.get_icon("settings", size=(22, 22), color=ui.COLOR_TEXT_SEC),
            width=46,
            height=42,
            corner_radius=8,
            anchor="center",
            fg_color="transparent",
            hover_color=ui.COLOR_NAV_HOVER,
            command=self._on_settings_parent_clicked,
        )
        self.settings_parent_btn._icon_name = "settings"
        self.settings_parent_btn.grid(row=4, column=0, padx=6, pady=4)
        ui.create_tooltip(self.settings_parent_btn, "Settings")

        self.settings_parent_btn.bind("<Enter>", lambda e: self._on_nav_btn_enter("settings"), add="+")
        self.settings_parent_btn.bind("<Leave>", lambda e: self._on_nav_btn_leave("settings"), add="+")

        # Quick Reload Button at bottom of sidebar (Row 11)
        self.reload_btn = ctk.CTkButton(
            self.sidebar,
            text="",
            image=ui.get_icon("refresh", size=(18, 18), color=ui.COLOR_TEXT_DIM),
            width=42,
            height=42,
            corner_radius=8,
            anchor="center",
            fg_color="transparent",
            hover_color=ui.COLOR_NAV_HOVER,
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
                ("dashboard", "Transform Overview", "home"),
                ("transform", "KRA Management", "kra"),
                ("time_leave", "Time and Leave Master", "calendar"),
                ("att_summary", "Attendance Summary", "attendance"),
                ("id_card", "ID Card Generator", "id_card"),
            ]
            title = "TRANSFORM"
            self.transform_menu_expanded = True
            if hasattr(self, "nav_chevron") and self.nav_chevron:
                self.nav_chevron.configure(text="▾")
        elif group == "analyse":
            items = [
                ("workforce_intelligence", "Workforce Intelligence", "users"),
                ("analyse_upload", "Upload Dataset", "upload"),
            ]
            title = "ANALYSE"
            self.analyse_menu_expanded = True
            if hasattr(self, "analyse_chevron") and self.analyse_chevron:
                self.analyse_chevron.configure(text="▾")
        else:
            items = [
                ("settings_connectors", "Connectors & Settings", "connectors"),
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

            ic_img = ui.get_icon(icon, size=(18, 18), color=txt_col)
            btn = ctk.CTkButton(
                card,
                text=f"  {text}",
                image=ic_img,
                compound="left",
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
    # Operations Command Center (Redesigned Home Page)
    # ---------------------------------------------------------
    def _build_dashboard_frame(self):
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
        self.frames["dashboard"] = f
        f.grid_columnconfigure((0, 1), weight=1)

        # ── 1. Hero Header with System Status & Fast Actions ─────────────────
        hdr = ui.create_page_header(
            f, "Operations Command Center",
            "Real-time workforce intelligence, transformation pipelines & automated HRMS integrations."
        )
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))

        hdr_actions = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_actions.grid(row=0, column=1, sticky="e")

        ui.create_primary_button(
            hdr_actions, "Quick Reconcile",
            lambda: self.select_frame_by_name("time_leave"),
            width=140, height=34, icon="calendar"
        ).pack(side="left", padx=(0, 8))

        ui.create_secondary_button(
            hdr_actions, "Settings & Connectors",
            lambda: self.select_frame_by_name("settings_connectors"),
            width=165, height=34, icon="settings"
        ).pack(side="left")

        # ── 2. Top Metric KPI Strip (4 Live Summary Cards) ────────────────────
        kpi_grid = ctk.CTkFrame(f, fg_color="transparent")
        kpi_grid.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        kpi_grid.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Helper to create sleek KPI mini-card
        def _make_kpi_card(parent, col, icon_name, title, main_val, sub_val, accent_color=ui.COLOR_ACCENT):
            c = ctk.CTkFrame(parent, fg_color=ui.COLOR_CARD, corner_radius=10, border_width=1, border_color=ui.COLOR_BORDER)
            c.grid(row=0, column=col, sticky="nsew", padx=4, pady=0)
            c.grid_columnconfigure(0, weight=1)

            top_r = ctk.CTkFrame(c, fg_color="transparent")
            top_r.pack(fill="x", padx=14, pady=(12, 4))

            ic_lbl = ctk.CTkLabel(top_r, text="", image=ui.get_icon(icon_name, size=(22, 22), color=accent_color))
            ic_lbl.pack(side="left", padx=(0, 8))

            ctk.CTkLabel(
                top_r, text=title.upper(),
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
                text_color=ui.COLOR_TEXT_DIM
            ).pack(side="left")

            ctk.CTkLabel(
                c, text=main_val,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=20, weight="bold"),
                text_color=ui.COLOR_TEXT, anchor="w"
            ).pack(fill="x", padx=14, pady=(2, 0))

            ctk.CTkLabel(
                c, text=sub_val,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
                text_color=ui.COLOR_TEXT_SEC, anchor="w"
            ).pack(fill="x", padx=14, pady=(2, 12))
            return c

        _make_kpi_card(kpi_grid, 0, "users", "Headcount Active", "500+ Profiles", "8 Business Units mapped", ui.COLOR_ACCENT)
        _make_kpi_card(kpi_grid, 1, "refresh", "HRMS Stream", "Live API Online", "OAuth Bearer token verified", ui.COLOR_SUCCESS)
        _make_kpi_card(kpi_grid, 2, "calendar", "Reconciliation", "Ready to Run", "Performance, Leaves & WFH", "#A78BFA")
        _make_kpi_card(kpi_grid, 3, "id_card", "Identity Hub", "Dual Sync Active", "Keka Photos + Slack fallback", ui.COLOR_WARNING)

        # ── 3. Main Center Operations Grid (2 Columns) ────────────────────────
        center_grid = ctk.CTkFrame(f, fg_color="transparent")
        center_grid.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        center_grid.grid_columnconfigure((0, 1), weight=1)

        # ══ LEFT COLUMN: Operational Workflow Launchpads ══
        left_col = ctk.CTkFrame(center_grid, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_col.grid_columnconfigure(0, weight=1)

        sec_hdr_left = ctk.CTkFrame(left_col, fg_color="transparent")
        sec_hdr_left.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            sec_hdr_left, text="⚡ Core Transformation Pipelines",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        # Workflow Card Builder
        def _make_workflow_card(parent, icon_name, title, badge_text, desc, btn_text, command):
            card = ctk.CTkFrame(parent, fg_color=ui.COLOR_CARD, corner_radius=10, border_width=1, border_color=ui.COLOR_BORDER)
            card.pack(fill="x", pady=(0, 10))
            card.grid_columnconfigure(0, weight=1)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=16, pady=(12, 4))

            ic = ctk.CTkLabel(top, text="", image=ui.get_icon(icon_name, size=(22, 22), color=ui.COLOR_ACCENT))
            ic.pack(side="left", padx=(0, 10))

            ctk.CTkLabel(
                top, text=title,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
                text_color=ui.COLOR_TEXT
            ).pack(side="left")

            if badge_text:
                b = ctk.CTkLabel(
                    top, text=badge_text,
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
                    text_color=ui.COLOR_ACCENT, fg_color=ui.COLOR_NAV_ACTIVE,
                    corner_radius=4, padx=6, pady=2
                )
                b.pack(side="right")

            ctk.CTkLabel(
                card, text=desc,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
                text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left", wraplength=460
            ).pack(fill="x", padx=16, pady=(2, 10))

            bot = ctk.CTkFrame(card, fg_color="transparent")
            bot.pack(fill="x", padx=16, pady=(0, 12))

            ui.create_primary_button(
                bot, btn_text, command,
                width=160, height=30, icon="launch"
            ).pack(side="right")

        _make_workflow_card(
            left_col, "calendar",
            "Time & Leave Reconciliation Hub", "AUTOMATED SYNC",
            "Reconcile monthly Daily Performance logs, approved leave applications, and OD/WFH requests directly against Keka HRMS.",
            "Launch Master Hub →",
            lambda: self.select_frame_by_name("time_leave")
        )

        _make_workflow_card(
            left_col, "kra",
            "KRA & Performance Management", "FORMAT CONVERTER",
            "Transform unstructured KRA Excel sheets, validate weighting distributions, and compile official Keka bulk upload formats.",
            "Open KRA Studio →",
            lambda: self.select_frame_by_name("transform")
        )

        _make_workflow_card(
            left_col, "id_card",
            "Instant ID Card Studio", "DUAL PIPELINE",
            "Generate print-ready corporate ID cards in bulk. Auto-fetches profile photos from Keka API with automated Slack fallback and QR codes.",
            "Open ID Studio →",
            lambda: self.select_frame_by_name("id_card")
        )

        _make_workflow_card(
            left_col, "time_series",
            "Workforce Intelligence & Analytics", "ANALYTICS ENGINE",
            "Deep-dive into workforce compliance trends, biometric swipe patterns, and multi-level departmental breakdowns across all business units.",
            "View Analytics →",
            lambda: self.select_frame_by_name("workforce_intelligence")
        )

        # ══ RIGHT COLUMN: Live System Matrix & Diagnostics ══
        right_col = ctk.CTkFrame(center_grid, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right_col.grid_columnconfigure(0, weight=1)

        sec_hdr_right = ctk.CTkFrame(right_col, fg_color="transparent")
        sec_hdr_right.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            sec_hdr_right, text="🛡️ System Integrations & Health Matrix",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        # 1. Live Connector Status Matrix Card
        conn_card = ctk.CTkFrame(right_col, fg_color=ui.COLOR_CARD, corner_radius=10, border_width=1, border_color=ui.COLOR_BORDER)
        conn_card.pack(fill="x", pady=(0, 10))

        conn_hdr = ctk.CTkFrame(conn_card, fg_color="transparent")
        conn_hdr.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            conn_hdr, text="🔌 Connector Health Status",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        def _make_conn_row(parent, icon_name, name, status_text, is_active=True):
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=4)
            ic = ctk.CTkLabel(r, text="", image=ui.get_icon(icon_name, size=(16, 16), color=ui.COLOR_ACCENT))
            ic.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                r, text=name,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
                text_color=ui.COLOR_TEXT
            ).pack(side="left")
            
            badge_col = ui.COLOR_SUCCESS if is_active else ui.COLOR_TEXT_DIM
            ctk.CTkLabel(
                r, text=f"●  {status_text}",
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
                text_color=badge_col
            ).pack(side="right")

        _make_conn_row(conn_card, "settings", "Keka HRMS REST API", "Active (Bearer Token)", True)
        _make_conn_row(conn_card, "eye", "Keka Web Automation", "Session Active (SSO Ready)", True)
        _make_conn_row(conn_card, "slack", "Slack Profile Photo Sync", "Workspace Online", True)

        conn_btn_row = ctk.CTkFrame(conn_card, fg_color="transparent")
        conn_btn_row.pack(fill="x", padx=16, pady=(8, 12))
        ui.create_secondary_button(
            conn_btn_row, "Configure Integrations →",
            lambda: self.select_frame_by_name("settings_connectors"),
            width=180, height=28, icon="settings"
        ).pack(side="right")

        # 2. Automation Engines Matrix Card
        auto_card = ctk.CTkFrame(right_col, fg_color=ui.COLOR_CARD, corner_radius=10, border_width=1, border_color=ui.COLOR_BORDER)
        auto_card.pack(fill="x", pady=(0, 10))

        auto_hdr = ctk.CTkFrame(auto_card, fg_color="transparent")
        auto_hdr.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            auto_hdr, text="⚡ Active Automation Engines",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        bullet_items = [
            ("zap", "Offline Neural OCR Captcha solver (~50ms instant bypass)"),
            ("users", "Parent-Child BU & Department hierarchy auto-mapping"),
            ("lock", "Persistent 2FA browser session & SSO authentication"),
            ("excel", "Multi-sheet Excel normalization & Keka upload validation"),
        ]
        for ic_name, b_text in bullet_items:
            b_row = ctk.CTkFrame(auto_card, fg_color="transparent")
            b_row.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(b_row, text="", image=ui.get_icon(ic_name, size=(14, 14), color=ui.COLOR_SUCCESS)).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                b_row, text=b_text,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
                text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left"
            ).pack(side="left")

        ctk.CTkFrame(auto_card, height=6, fg_color="transparent").pack()

        # 3. Environment & Quick Shortcuts Card
        env_card = ctk.CTkFrame(right_col, fg_color=ui.COLOR_CARD, corner_radius=10, border_width=1, border_color=ui.COLOR_BORDER)
        env_card.pack(fill="x")

        env_hdr = ctk.CTkFrame(env_card, fg_color="transparent")
        env_hdr.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            env_hdr, text="⌨️ Workspace Shortcuts",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        shortcuts = [
            ("F5 / Ctrl+R", "Instant Hot-Reload workspace & preserve active tab"),
            ("Escape", "Dismiss flyout navigation & modal overlays"),
            ("Tab Key", "Cycle keyboard focus across form inputs & actions"),
        ]
        for key_combo, desc in shortcuts:
            s_row = ctk.CTkFrame(env_card, fg_color="transparent")
            s_row.pack(fill="x", padx=16, pady=2)
            
            badge = ctk.CTkLabel(
                s_row, text=key_combo,
                font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
                text_color=ui.COLOR_TEXT, fg_color=ui.COLOR_INPUT_BG,
                corner_radius=4, padx=6, pady=1
            )
            badge.pack(side="left", padx=(0, 8))
            
            ctk.CTkLabel(
                s_row, text=desc,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
                text_color=ui.COLOR_TEXT_DIM, anchor="w"
            ).pack(side="left")

        ctk.CTkFrame(env_card, height=10, fg_color="transparent").pack()

    # ---------------------------------------------------------
    # KRA Management
    # ---------------------------------------------------------
    def _build_transform_frame(self):
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
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
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
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
    def _tl_update_dates_from_dropdowns(self):
        """Sync the tl_from_date_var / tl_to_date_var from the Month+Year dropdowns."""
        import calendar as _cal_mod
        _months = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
        try:
            month_name = self._tl_month_var.get()
            year_str   = self._tl_year_var.get()
            month_idx  = _months.index(month_name) + 1  # 1-based
            year       = int(year_str)
            last_day   = _cal_mod.monthrange(year, month_idx)[1]
            from_str   = f"01-{month_idx:02d}-{year}"
            to_str     = f"{last_day:02d}-{month_idx:02d}-{year}"
            self.tl_from_date_var.set(from_str)
            self.tl_to_date_var.set(to_str)
            # Update the range display label
            if hasattr(self, "tl_date_range_lbl"):
                self.tl_date_range_lbl.configure(
                    text=f"01 {month_name[:3]} {year}  →  {last_day:02d} {month_name[:3]} {year}"
                )
        except Exception:
            pass

    def _open_calendar_dialog(self, target_var, title="Select Date"):
        """Opens a premium dark-themed custom calendar popup for date selection."""
        import calendar as _cal
        from datetime import date as _date

        # Parse current value to pre-select the date
        val = target_var.get().strip()
        now = _date.today()
        sel_year, sel_month, sel_day = now.year, now.month, now.day
        if val:
            for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    from datetime import datetime as _dt
                    d = _dt.strptime(val, fmt).date()
                    sel_year, sel_month, sel_day = d.year, d.month, d.day
                    break
                except ValueError:
                    continue

        top = ctk.CTkToplevel(self)
        top.title(title)
        top.geometry("360x420")
        top.resizable(False, False)
        top.attributes("-topmost", True)
        top.grab_set()
        top.configure(fg_color=ui.COLOR_BG)

        # State
        _year  = [sel_year]
        _month = [sel_month]
        _chosen_day = [sel_day]

        MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        WEEKDAYS    = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

        # ── Header bar ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(top, fg_color=ui.COLOR_CARD, corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text=f"📅  {title}",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).place(relx=0.5, rely=0.5, anchor="center")

        # ── Month/Year navigation bar ──────────────────────────────────────
        nav = ctk.CTkFrame(top, fg_color=ui.COLOR_CARD, corner_radius=0, height=46)
        nav.pack(fill="x", pady=(1, 0))
        nav.pack_propagate(False)
        nav.grid_columnconfigure(1, weight=1)

        month_year_lbl = ctk.CTkLabel(
            nav, text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            text_color=ui.COLOR_TEXT
        )
        month_year_lbl.place(relx=0.5, rely=0.5, anchor="center")

        # Calendar grid container
        grid_frame = ctk.CTkFrame(top, fg_color=ui.COLOR_BG, corner_radius=0)
        grid_frame.pack(fill="both", expand=True, padx=12, pady=(8, 4))

        # Confirm / Cancel footer
        footer = ctk.CTkFrame(top, fg_color=ui.COLOR_CARD, corner_radius=0, height=54)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        day_btns = {}

        def _render_calendar():
            """Redraw the calendar grid for current _year/_month."""
            for w in grid_frame.winfo_children():
                w.destroy()
            day_btns.clear()

            month_year_lbl.configure(
                text=f"{MONTH_NAMES[_month[0]-1]}  {_year[0]}"
            )

            # Weekday headers
            for col, wd in enumerate(WEEKDAYS):
                is_weekend = col >= 5
                ctk.CTkLabel(
                    grid_frame,
                    text=wd,
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
                    text_color=ui.COLOR_ACCENT if is_weekend else ui.COLOR_TEXT_DIM,
                    width=42, height=28
                ).grid(row=0, column=col, padx=1, pady=(0, 4))

            # Compute month grid (Monday-first)
            first_weekday, num_days = _cal.monthrange(_year[0], _month[0])
            row, col = 1, first_weekday
            for day in range(1, num_days + 1):
                is_today   = (day == now.day and _month[0] == now.month and _year[0] == now.year)
                is_sel     = (day == _chosen_day[0])
                is_weekend = (col >= 5)

                if is_sel:
                    fg   = ui.COLOR_ACCENT
                    txt  = "#FFFFFF"
                    hover = ui.COLOR_ACCENT
                    border = 0
                elif is_today:
                    fg    = "transparent"
                    txt   = ui.COLOR_ACCENT
                    hover = ui.COLOR_CARD_HOVER
                    border = 2
                elif is_weekend:
                    fg    = "transparent"
                    txt   = ui.COLOR_TEXT_SEC
                    hover = ui.COLOR_CARD_HOVER
                    border = 0
                else:
                    fg    = "transparent"
                    txt   = ui.COLOR_TEXT
                    hover = ui.COLOR_CARD_HOVER
                    border = 0

                def _on_click(d=day):
                    _chosen_day[0] = d
                    _render_calendar()

                btn = ctk.CTkButton(
                    grid_frame,
                    text=str(day),
                    width=40, height=36,
                    corner_radius=8,
                    fg_color=fg,
                    hover_color=hover,
                    text_color=txt,
                    border_width=border,
                    border_color=ui.COLOR_ACCENT,
                    font=ctk.CTkFont(
                        family=ui.FONT_FAMILY,
                        size=12,
                        weight="bold" if is_sel or is_today else "normal"
                    ),
                    command=_on_click
                )
                btn.grid(row=row, column=col, padx=2, pady=2)
                day_btns[day] = btn

                col += 1
                if col > 6:
                    col = 0
                    row += 1

        def _prev_month():
            if _month[0] == 1:
                _month[0] = 12
                _year[0] -= 1
            else:
                _month[0] -= 1
            import calendar as _cm
            last = _cm.monthrange(_year[0], _month[0])[1]
            if _chosen_day[0] > last:
                _chosen_day[0] = last
            _render_calendar()

        def _next_month():
            if _month[0] == 12:
                _month[0] = 1
                _year[0] += 1
            else:
                _month[0] += 1
            import calendar as _cm
            last = _cm.monthrange(_year[0], _month[0])[1]
            if _chosen_day[0] > last:
                _chosen_day[0] = last
            _render_calendar()

        # Prev / Next nav buttons
        ctk.CTkButton(
            nav, text="❮", width=36, height=36,
            corner_radius=8, fg_color="transparent",
            hover_color=ui.COLOR_CARD_HOVER,
            text_color=ui.COLOR_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=16, weight="bold"),
            command=_prev_month
        ).place(relx=0.05, rely=0.5, anchor="w")

        ctk.CTkButton(
            nav, text="❯", width=36, height=36,
            corner_radius=8, fg_color="transparent",
            hover_color=ui.COLOR_CARD_HOVER,
            text_color=ui.COLOR_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=16, weight="bold"),
            command=_next_month
        ).place(relx=0.95, rely=0.5, anchor="e")

        def _confirm():
            from datetime import datetime as _dt
            try:
                import calendar as _cm
                last = _cm.monthrange(_year[0], _month[0])[1]
                d = min(_chosen_day[0], last)
                dt = _dt(_year[0], _month[0], d)
                target_var.set(dt.strftime("%d-%m-%Y"))
            except Exception:
                pass
            top.destroy()

        ui.create_primary_button(
            footer, "Confirm ✓", _confirm, width=130, height=34
        ).pack(side="right", padx=14, pady=10)

        ui.create_secondary_button(
            footer, "Cancel", top.destroy, width=80, height=34
        ).pack(side="right", padx=(0, 8), pady=10)

        # Selected date preview
        self._cal_preview_lbl = ctk.CTkLabel(
            footer, text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_ACCENT
        )
        self._cal_preview_lbl.pack(side="left", padx=14)

        orig_render = _render_calendar

        def _render_with_preview():
            orig_render()
            m = MONTH_NAMES[_month[0] - 1][:3]
            self._cal_preview_lbl.configure(
                text=f"{_chosen_day[0]:02d} {m} {_year[0]}"
            )

        _render_calendar = _render_with_preview
        _render_calendar()

    def _build_absent_frame(self):
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
        self.frames["absent"] = f
        f.grid_columnconfigure(0, weight=1)

        ui.create_page_header(f, "Absent Management", "Generate absent intimation reports by comparing master, attendance and OD/WFH data.").grid(row=0, column=0, sticky="ew", pady=(0, 12))

        # Notice banner pointing to Unified Time & Leave Master
        banner = ctk.CTkFrame(f, fg_color=ui.COLOR_CARD, corner_radius=8, border_width=1, border_color=ui.COLOR_ACCENT)
        banner.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        banner.grid_columnconfigure(0, weight=1)

        b_content = ctk.CTkFrame(banner, fg_color="transparent")
        b_content.pack(fill="x", padx=16, pady=10)

        ctk.CTkLabel(
            b_content,
            text="💡 Unified HR Hub Available: Absent Management is consolidated into Time & Leave Master with Daily Performance + Mailer in one go!",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_ACCENT
        ).pack(side="left")

        ui.create_secondary_button(
            b_content,
            "Go to Time & Leave Master →",
            lambda: self.select_frame_by_name("time_leave"),
            width=200, height=28
        ).pack(side="right")

        # -------------------------------------------------------------
        # 1. Keka Direct Sync Card
        # -------------------------------------------------------------
        sync_card = ui.create_card(f)
        sync_card.grid(row=2, column=0, sticky="nsew", pady=(0, 16))

        sync_hdr = ctk.CTkFrame(sync_card, fg_color="transparent")
        sync_hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        sync_hdr.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(sync_hdr, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="⚡ Pull from Keka HRMS",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text="Fetch Employee Master & OD/WFH requests directly from Keka API into the source fields below.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(anchor="w", pady=(2, 0))

        # Date parameters row with Calendar Pickers
        dates_row = ctk.CTkFrame(sync_card, fg_color="transparent")
        dates_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 12))

        # From Date Entry + 📅 Button
        ctk.CTkLabel(
            dates_row, text="From Date:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 6))

        self.absent_from_entry = ctk.CTkEntry(
            dates_row, textvariable=self.absent_from_date_var, width=105, height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.absent_from_entry.pack(side="left", padx=(0, 4))

        self.btn_from_cal = ui.create_secondary_button(
            dates_row, "",
            lambda: self._open_calendar_dialog(self.absent_from_date_var, "Select From Date"),
            width=36, height=32, icon="calendar"
        )
        self.btn_from_cal.pack(side="left", padx=(0, 16))

        # To Date Entry + 📅 Button
        ctk.CTkLabel(
            dates_row, text="To Date:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 6))

        self.absent_to_entry = ctk.CTkEntry(
            dates_row, textvariable=self.absent_to_date_var, width=105, height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.absent_to_entry.pack(side="left", padx=(0, 4))

        self.btn_to_cal = ui.create_secondary_button(
            dates_row, "",
            lambda: self._open_calendar_dialog(self.absent_to_date_var, "Select To Date"),
            width=36, height=32, icon="calendar"
        )
        self.btn_to_cal.pack(side="left", padx=(0, 20))

        self.absent_portal_cb = ctk.CTkCheckBox(
            dates_row,
            text="Also fetch Attendance Report (Daily Performance via API ⚡)",
            variable=self.absent_include_portal_var,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC,
            fg_color=ui.COLOR_ACCENT,
            hover_color=ui.COLOR_ACCENT_HOVER
        )
        self.absent_portal_cb.pack(side="left")

        # Action bar in sync card
        sync_action_row = ctk.CTkFrame(sync_card, fg_color="transparent")
        sync_action_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))

        _, self.absent_keka_dot, self.absent_keka_lbl = ui.create_status_badge(sync_action_row, "Ready")
        self.absent_keka_lbl.master.pack(side="left")

        self.btn_pull_keka = ui.create_primary_button(
            sync_action_row, "⚡ Pull from Keka", self.pull_keka_absent_data, width=160
        )
        self.btn_pull_keka.pack(side="right")

        # ── Real-Time Progress Bar & Live Status Monitor ──
        self.absent_progress_card = ctk.CTkFrame(
            sync_card, fg_color=ui.COLOR_CARD, corner_radius=8,
            border_width=1, border_color=ui.COLOR_BORDER
        )
        self.absent_progress_card.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.absent_progress_card.grid_columnconfigure(0, weight=1)

        prog_hdr = ctk.CTkFrame(self.absent_progress_card, fg_color="transparent")
        prog_hdr.pack(fill="x", padx=12, pady=(10, 4))

        self.absent_progress_step_lbl = ctk.CTkLabel(
            prog_hdr,
            text="Ready to pull Keka data",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT
        )
        self.absent_progress_step_lbl.pack(side="left")

        self.absent_progress_pct_lbl = ctk.CTkLabel(
            prog_hdr,
            text="0%",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_ACCENT
        )
        self.absent_progress_pct_lbl.pack(side="right")

        self.absent_progress_bar = ctk.CTkProgressBar(
            self.absent_progress_card,
            height=8,
            corner_radius=4,
            progress_color=ui.COLOR_ACCENT,
            fg_color=ui.COLOR_INPUT_BG,
            border_width=0
        )
        self.absent_progress_bar.set(0.0)
        self.absent_progress_bar.pack(fill="x", padx=12, pady=(2, 4))

        self.absent_progress_detail_lbl = ctk.CTkLabel(
            self.absent_progress_card,
            text="Select dates above and click '⚡ Pull from Keka' for high-speed multi-threaded sync.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w"
        )
        self.absent_progress_detail_lbl.pack(fill="x", padx=12, pady=(0, 8))

        # -------------------------------------------------------------
        # 2. Source Files Card
        # -------------------------------------------------------------
        card = ui.create_card(f)
        card.grid(row=3, column=0, sticky="nsew", pady=(0, 24))
        
        ctk.CTkLabel(card, text="Source Files (Auto-filled by Keka sync or browse manually)", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"), text_color=ui.COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        ui.create_upload_row(card, self.absent_emp_file, "1. Employee Master (Expected: Employee Master.xlsx)", "Browse", 1)
        ui.create_upload_row(card, self.absent_att_file, "2. Attendance Report (Daily Performance report.xlsx)", "Browse", 2)
        ui.create_upload_row(card, self.absent_wfh_file, "3. OD/WFH Application Report (Expected: OD_WFH Application Report.xlsx)", "Browse", 3)

        row4 = ctk.CTkFrame(card, fg_color="transparent")
        row4.grid(row=4, column=0, sticky="ew", padx=16, pady=(12, 16))
        
        _, self.absent_dot, self.absent_lbl = ui.create_status_badge(row4, "Ready")
        self.absent_lbl.master.pack(side="left")

        self.btn_absent = ui.create_primary_button(row4, "Process Data →", self.start_process_absent, width=140, height=36)
        self.btn_absent.pack(side="right")

    # ---------------------------------------------------------
    # Attendance Summary
    # ---------------------------------------------------------
    def _build_att_summary_frame(self):
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
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
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
        self.frames["time_leave"] = f
        f.grid_columnconfigure(0, weight=1)

        hdr = ui.create_page_header(
            f, "Time and Leave Master",
            "Unified HR Hub: Sync directly from Keka HRMS or upload monthly files to reconcile Performance, Leaves, and Absent Intimations."
        )
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        # -------------------------------------------------------------
        # Single Unified Card for Time and Leave Master
        # -------------------------------------------------------------
        card = ui.create_card(f)
        card.grid(row=1, column=0, sticky="nsew", pady=(0, 24))
        card.grid_columnconfigure(0, weight=1)

        sync_hdr = ctk.CTkFrame(card, fg_color="transparent")
        sync_hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        sync_hdr.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(sync_hdr, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="⚡ Pull from Keka HRMS & Auto-Reconcile",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text="One-click live sync: Pulls Employee Master, OD/WFH, and Attendance logs via Keka API, then generates the consolidated report with both Daily Performance and Absent Mailer.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(anchor="w", pady=(2, 0))

        # ── Improved Date Range Selector ──────────────────────────────────
        # Month/Year dropdowns auto-fill From (1st) and To (last day) of the month.
        import calendar as _cal_mod
        _months = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
        _cur_year = datetime.now().year
        _years = [str(y) for y in range(_cur_year - 3, _cur_year + 2)]

        # Pill container with subtle border
        dates_outer = ctk.CTkFrame(
            card, fg_color=ui.COLOR_INPUT_BG, corner_radius=10,
            border_width=1, border_color=ui.COLOR_BORDER
        )
        dates_outer.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 14))
        dates_outer.grid_columnconfigure((0, 1, 2, 3), weight=0)

        # — Month segment
        left_seg = ctk.CTkFrame(dates_outer, fg_color="transparent")
        left_seg.grid(row=0, column=0, padx=(14, 6), pady=10)

        ctk.CTkLabel(
            left_seg, text="📅  Month",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(anchor="w", pady=(0, 3))

        _init_month_idx = datetime.now().month - 1
        self._tl_month_var = ctk.StringVar(value=_months[_init_month_idx])
        self.tl_month_menu = ctk.CTkOptionMenu(
            left_seg,
            variable=self._tl_month_var,
            values=_months,
            width=148, height=34,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
            fg_color=ui.COLOR_CARD,
            button_color=ui.COLOR_ACCENT,
            button_hover_color=ui.COLOR_ACCENT,
            dropdown_fg_color=ui.COLOR_CARD,
            dropdown_text_color=ui.COLOR_TEXT,
            text_color=ui.COLOR_TEXT,
            corner_radius=7,
            command=lambda _v: self._tl_update_dates_from_dropdowns()
        )
        self.tl_month_menu.pack()

        # Divider
        ctk.CTkFrame(dates_outer, width=1, height=52, fg_color=ui.COLOR_BORDER).grid(
            row=0, column=1, padx=6, pady=8
        )

        # — Year segment
        right_seg = ctk.CTkFrame(dates_outer, fg_color="transparent")
        right_seg.grid(row=0, column=2, padx=(6, 8), pady=10)

        ctk.CTkLabel(
            right_seg, text="📆  Year",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(anchor="w", pady=(0, 3))

        self._tl_year_var = ctk.StringVar(value=str(_cur_year))
        self.tl_year_menu = ctk.CTkOptionMenu(
            right_seg,
            variable=self._tl_year_var,
            values=_years,
            width=100, height=34,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
            fg_color=ui.COLOR_CARD,
            button_color=ui.COLOR_ACCENT,
            button_hover_color=ui.COLOR_ACCENT,
            dropdown_fg_color=ui.COLOR_CARD,
            dropdown_text_color=ui.COLOR_TEXT,
            text_color=ui.COLOR_TEXT,
            corner_radius=7,
            command=lambda _v: self._tl_update_dates_from_dropdowns()
        )
        self.tl_year_menu.pack()

        # — Resolved date range display
        date_display_seg = ctk.CTkFrame(dates_outer, fg_color="transparent")
        date_display_seg.grid(row=0, column=3, padx=(2, 14), pady=10)

        ctk.CTkLabel(
            date_display_seg, text="Range",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(anchor="w", pady=(0, 3))

        self.tl_date_range_lbl = ctk.CTkLabel(
            date_display_seg,
            text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_ACCENT,
            width=200,
            anchor="w"
        )
        self.tl_date_range_lbl.pack(anchor="w")

        # — Custom range override (always visible below dropdowns)
        custom_row = ctk.CTkFrame(dates_outer, fg_color="transparent")
        custom_row.grid(row=1, column=0, columnspan=4, padx=14, pady=(0, 8), sticky="w")

        ctk.CTkLabel(
            custom_row, text="Custom range:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 8))

        self.tl_from_entry = ctk.CTkEntry(
            custom_row, textvariable=self.tl_from_date_var, width=95, height=28,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT,
            placeholder_text="DD-MM-YYYY"
        )
        self.tl_from_entry.pack(side="left", padx=(0, 3))

        ui.create_secondary_button(
            custom_row, "📅",
            lambda: self._open_calendar_dialog(self.tl_from_date_var, "Select From Date"),
            width=30, height=28
        ).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            custom_row, text="→",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(0, 6))

        self.tl_to_entry = ctk.CTkEntry(
            custom_row, textvariable=self.tl_to_date_var, width=95, height=28,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT,
            placeholder_text="DD-MM-YYYY"
        )
        self.tl_to_entry.pack(side="left", padx=(0, 3))

        ui.create_secondary_button(
            custom_row, "📅",
            lambda: self._open_calendar_dialog(self.tl_to_date_var, "Select To Date"),
            width=30, height=28
        ).pack(side="left", padx=(0, 6))

        # Initialise display label and date vars from current dropdowns
        self._tl_update_dates_from_dropdowns()

        # Action bar in sync card
        sync_action_row = ctk.CTkFrame(card, fg_color="transparent")
        sync_action_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))

        _, self.tl_keka_dot, self.tl_keka_lbl = ui.create_status_badge(sync_action_row, "Ready")
        self.tl_keka_lbl.master.pack(side="left")

        self.btn_pull_keka_tl = ui.create_primary_button(
            sync_action_row, "⚡ Pull from Keka & Generate Master Report", self.pull_keka_time_leave_data, width=280
        )
        self.btn_pull_keka_tl.pack(side="right")

        # Real-time progress bar & live status monitor
        self.tl_keka_progress_card = ctk.CTkFrame(
            card, fg_color=ui.COLOR_CARD, corner_radius=8,
            border_width=1, border_color=ui.COLOR_BORDER
        )
        self.tl_keka_progress_card.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.tl_keka_progress_card.grid_columnconfigure(0, weight=1)

        prog_hdr = ctk.CTkFrame(self.tl_keka_progress_card, fg_color="transparent")
        prog_hdr.pack(fill="x", padx=12, pady=(10, 4))

        self.tl_keka_progress_step_lbl = ctk.CTkLabel(
            prog_hdr,
            text="Ready to pull unified data from Keka",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_TEXT
        )
        self.tl_keka_progress_step_lbl.pack(side="left")

        self.tl_keka_progress_pct_lbl = ctk.CTkLabel(
            prog_hdr,
            text="0%",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            text_color=ui.COLOR_ACCENT
        )
        self.tl_keka_progress_pct_lbl.pack(side="right")

        self.tl_keka_progress_bar = ctk.CTkProgressBar(
            self.tl_keka_progress_card,
            height=8,
            corner_radius=4,
            progress_color=ui.COLOR_ACCENT,
            fg_color=ui.COLOR_INPUT_BG,
            border_width=0
        )
        self.tl_keka_progress_bar.set(0.0)
        self.tl_keka_progress_bar.pack(fill="x", padx=12, pady=(2, 4))

        self.tl_keka_progress_detail_lbl = ctk.CTkLabel(
            self.tl_keka_progress_card,
            text="Select dates above and click '⚡ Pull from Keka & Generate Master Report' to auto-generate the consolidated workbook.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_DIM,
            anchor="w"
        )
        self.tl_keka_progress_detail_lbl.pack(fill="x", padx=12, pady=(0, 8))

        # -------------------------------------------------------------
        # Collapsible Manual File Uploads Section (Inside the SAME Card)
        # -------------------------------------------------------------
        toggle_frame = ctk.CTkFrame(card, fg_color="transparent")
        toggle_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 8))

        manual_container = ctk.CTkFrame(card, fg_color="transparent")
        manual_container.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 16))
        manual_container.grid_columnconfigure(0, weight=1)
        manual_container.grid_remove()  # Collapsed by default to keep single clean card

        self.manual_expanded = False
        def toggle_manual_section():
            self.manual_expanded = not self.manual_expanded
            if self.manual_expanded:
                manual_container.grid()
                self.btn_toggle_manual.configure(text="📁 Manual Monthly File Uploads ▴ (Click to collapse)")
            else:
                manual_container.grid_remove()
                self.btn_toggle_manual.configure(text="📁 Need manual monthly file upload? Click to expand ▾")

        self.btn_toggle_manual = ctk.CTkButton(
            toggle_frame,
            text="📁 Need manual monthly file upload? Click to expand ▾",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12, weight="bold"),
            fg_color="transparent",
            hover_color=ui.COLOR_CARD_HOVER,
            text_color=ui.COLOR_TEXT_SEC,
            anchor="w",
            command=toggle_manual_section
        )
        self.btn_toggle_manual.pack(fill="x")

        # 1. Daily performance report
        ui.create_multi_upload_row(
            manual_container, self.tl_perf_files,
            "1. Daily Performance Report (Supports multiple months)",
            placeholder="Select Daily Performance Report Excel/CSV files...",
            row=0
        )

        # 2. Leave application - Active
        ui.create_multi_upload_row(
            manual_container, self.tl_leave_active_files,
            "2. Leave Application - Active (Supports multiple months)",
            placeholder="Select Active Leave Application files...",
            row=1
        )

        # 3. Leave application - Inactive
        ui.create_multi_upload_row(
            manual_container, self.tl_leave_inactive_files,
            "3. Leave Application - Inactive (Supports multiple months)",
            placeholder="Select Inactive Leave Application files...",
            row=2
        )

        # 4. WFH applications
        ui.create_multi_upload_row(
            manual_container, self.tl_wfh_files,
            "4. WFH Applications (Supports multiple months)",
            placeholder="Select WFH Application files...",
            row=3
        )

        # 5. Employee Master (Optional)
        ui.create_multi_upload_row(
            manual_container, self.tl_emp_master_files,
            "5. Employee Master (Optional - for Reporting Manager, Location & LWD enrichment)",
            placeholder="Select Employee Master Excel/CSV files...",
            row=4
        )

        # Determinate Progress bar based on actual data volume
        self.tl_prog = ctk.CTkProgressBar(
            manual_container, mode="determinate", height=6, corner_radius=3,
            fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT
        )
        self.tl_prog.grid(row=5, column=0, sticky="ew", padx=0, pady=(8, 4))
        self.tl_prog.set(0)
        self.tl_prog.grid_remove()

        # Real-time progress detail label
        self.tl_prog_lbl = ctk.CTkLabel(
            manual_container, text="",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left"
        )
        self.tl_prog_lbl.grid(row=6, column=0, sticky="w", padx=0, pady=(0, 4))
        self.tl_prog_lbl.grid_remove()

        # Action row
        row_act = ctk.CTkFrame(manual_container, fg_color="transparent")
        row_act.grid(row=7, column=0, sticky="ew", padx=0, pady=(8, 0))

        _, self.tl_dot, self.tl_lbl = ui.create_status_badge(row_act, "Ready")
        self.tl_lbl.master.pack(side="left")

        self.btn_tl = ui.create_primary_button(row_act, "Process & Update Report", self.start_process_time_leave, width=170)
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

        # ── Card 1: Keka HRMS API Integration (REST API) ──
        keka_api_card = ui.create_card(cards_grid)
        keka_api_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        keka_api_card.grid_columnconfigure(0, weight=1)

        keka_hdr = ctk.CTkFrame(keka_api_card, fg_color="transparent")
        keka_hdr.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            keka_hdr, text="🏢 Keka HRMS API Integration",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        # REST API Badge
        keka_badge = ctk.CTkLabel(
            keka_hdr, text="REST API (OAUTH)",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_ACCENT, fg_color=ui.COLOR_NAV_ACTIVE,
            corner_radius=4, padx=6, pady=2
        )
        keka_badge.pack(side="right")

        ctk.CTkLabel(
            keka_api_card,
            text="Primary HRMS data connector. Uses OAuth 2.0 Client Credentials or direct Bearer token to pull Employee Master (509 employees) and OD/WFH requests.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left", wraplength=480
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Fields container
        keka_fields = ctk.CTkFrame(keka_api_card, fg_color="transparent")
        keka_fields.pack(fill="x", padx=16, pady=(0, 6))

        # Subdomain
        ctk.CTkLabel(
            keka_fields, text="Company Subdomain (.keka.com):",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        ).pack(fill="x", pady=(2, 2))
        self.entry_keka_subdomain = ctk.CTkEntry(
            keka_fields, textvariable=self.keka_subdomain_var,
            placeholder_text="e.g. moshpit", height=32,
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

        # Status & Action Buttons for API
        keka_api_footer = ctk.CTkFrame(keka_api_card, fg_color="transparent")
        keka_api_footer.pack(fill="x", padx=16, pady=(4, 14))

        keka_status_row = ctk.CTkFrame(keka_api_footer, fg_color="transparent")
        keka_status_row.pack(fill="x", pady=(0, 8))
        _, self.settings_keka_dot, self.settings_keka_lbl = ui.create_status_badge(keka_status_row, "Not connected", pack_side="left")

        keka_btn_row = ctk.CTkFrame(keka_api_footer, fg_color="transparent")
        keka_btn_row.pack(fill="x")

        ui.create_secondary_button(
            keka_btn_row, "Save Settings",
            lambda: self.save_connectors_credentials("keka_api"),
            width=115, height=32, icon="save"
        ).pack(side="left", padx=(0, 8))

        self.settings_btn_connect_keka = ui.create_primary_button(
            keka_btn_row, "Connect & Test API", self.connect_keka_now, width=155, height=32, icon="refresh"
        )
        self.settings_btn_connect_keka.pack(side="left")

        # ── Card 2: Keka Web Portal Login (Attendance Automation) ──
        portal_card = ui.create_card(cards_grid)
        portal_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        portal_card.grid_columnconfigure(0, weight=1)

        portal_hdr = ctk.CTkFrame(portal_card, fg_color="transparent")
        portal_hdr.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            portal_hdr, text="🌐 Keka Web Portal Automation",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        portal_badge = ctk.CTkLabel(
            portal_hdr, text="ATTENDANCE SYNC",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color="#A78BFA", fg_color="#2E1065",
            corner_radius=4, padx=6, pady=2
        )
        portal_badge.pack(side="right")

        ctk.CTkLabel(
            portal_card,
            text="Automated browser login to download the official Attendance Report with daily status codes (A, P, WO, etc.). Automatically handles Keka visual captcha.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left", wraplength=480
        ).pack(fill="x", padx=16, pady=(0, 10))

        portal_fields = ctk.CTkFrame(portal_card, fg_color="transparent")
        portal_fields.pack(fill="x", padx=16, pady=(0, 6))

        # Portal Email
        ctk.CTkLabel(
            portal_fields, text="Portal Login Email:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        ).pack(fill="x", pady=(2, 2))
        self.entry_keka_login_email = ctk.CTkEntry(
            portal_fields, textvariable=self.keka_login_email_var,
            placeholder_text="e.g. employee@company.com", height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.entry_keka_login_email.pack(fill="x", pady=(0, 8))

        # Portal Password
        ctk.CTkLabel(
            portal_fields, text="Portal Login Password:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        ).pack(fill="x", pady=(2, 2))
        self.entry_keka_login_password = ctk.CTkEntry(
            portal_fields, textvariable=self.keka_login_password_var,
            placeholder_text="Enter Keka web portal password...", show="*", height=32,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, corner_radius=6, text_color=ui.COLOR_TEXT
        )
        self.entry_keka_login_password.pack(fill="x", pady=(0, 10))

        # Portal Info / Notes Box
        portal_info_box = ctk.CTkFrame(portal_fields, fg_color=ui.COLOR_CARD, corner_radius=6, border_width=1, border_color=ui.COLOR_BORDER)
        portal_info_box.pack(fill="x", pady=(4, 12))
        ctk.CTkLabel(
            portal_info_box,
            text="🔐 SSO & 2FA Bypass Information:\n"
                 " • Single Sign-On (SSO): Click 'Authorize in Browser' to log in via Microsoft 365 or Google Workspace in 1 click.\n"
                 " • 2FA Bypass: Authorize once with 'Remember this browser' checked. Session cookies are permanently saved in your Chrome profile, completely bypassing 2FA on future data pulls!\n"
                 " • In-App 2FA: During automated sync, the app prompts for the 6-digit OTP sent to your email.\n"
                 " • Captchas are solved automatically via offline neural OCR in ~50ms.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_DIM, justify="left", anchor="w"
        ).pack(fill="x", padx=10, pady=8)

        # Status & Action Buttons for Portal
        portal_footer = ctk.CTkFrame(portal_card, fg_color="transparent")
        portal_footer.pack(fill="x", padx=16, pady=(4, 14))

        portal_status_row = ctk.CTkFrame(portal_footer, fg_color="transparent")
        portal_status_row.pack(fill="x", pady=(0, 8))
        _, self.settings_portal_dot, self.settings_portal_lbl = ui.create_status_badge(portal_status_row, "Not connected", pack_side="left")

        portal_btn_row = ctk.CTkFrame(portal_footer, fg_color="transparent")
        portal_btn_row.pack(fill="x")

        ui.create_secondary_button(
            portal_btn_row, "Save",
            lambda: self.save_connectors_credentials("keka_portal"),
            width=80, height=32, icon="save"
        ).pack(side="left", padx=(0, 6))

        self.settings_btn_auth_portal = ui.create_secondary_button(
            portal_btn_row, "Authorize Browser", self.authorize_keka_portal_in_browser, width=145, height=32, icon="eye"
        )
        self.settings_btn_auth_portal.pack(side="left", padx=(0, 6))

        self.settings_btn_test_portal = ui.create_primary_button(
            portal_btn_row, "Test Login", self.connect_keka_portal_now, width=115, height=32, icon="refresh"
        )
        self.settings_btn_test_portal.pack(side="left")

        # ── Card 3: Slack Workspace Connector (Fallback) ──
        slack_card = ui.create_card(cards_grid)
        slack_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=0)
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

        slack_status_row = ctk.CTkFrame(slack_footer, fg_color="transparent")
        slack_status_row.pack(fill="x", pady=(0, 8))
        _, self.settings_slack_dot, self.settings_slack_lbl = ui.create_status_badge(slack_status_row, "Checking...", pack_side="left")

        slack_btn_row = ctk.CTkFrame(slack_footer, fg_color="transparent")
        slack_btn_row.pack(fill="x")

        ui.create_secondary_button(
            slack_btn_row, "Save API",
            lambda: self.save_connectors_credentials("slack"),
            width=100, height=32, icon="save"
        ).pack(side="left", padx=(0, 8))

        self.settings_btn_connect_slack = ui.create_primary_button(
            slack_btn_row, "Connect & Test", self.connect_slack_now, width=135, height=32, icon="refresh"
        )
        self.settings_btn_connect_slack.pack(side="left")

        # ── Card 4: Architecture & Workflow Guide ──
        guide_card = ui.create_card(cards_grid)
        guide_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=0)
        guide_card.grid_columnconfigure(0, weight=1)

        guide_hdr = ctk.CTkFrame(guide_card, fg_color="transparent")
        guide_hdr.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            guide_hdr, text="📊 Integration Architecture Guide",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(side="left")

        guide_badge = ctk.CTkLabel(
            guide_hdr, text="DATA FLOW",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, fg_color=ui.COLOR_INPUT_BG,
            corner_radius=4, padx=6, pady=2
        )
        guide_badge.pack(side="right")

        ctk.CTkLabel(
            guide_card,
            text="Understanding how Keka API, Portal Automation, and Slack collaborate across the application:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC, anchor="w", justify="left"
        ).pack(fill="x", padx=16, pady=(0, 8))

        guide_content = ctk.CTkFrame(guide_card, fg_color=ui.COLOR_CARD, corner_radius=6, border_width=1, border_color=ui.COLOR_BORDER)
        guide_content.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        guide_text = (
            "1. 🏢 Keka HRMS API (Instant & Automated):\n"
            "   • Downloads full Employee Master directory (509 records) → Field #1\n"
            "   • Downloads On Duty (OD) and Work From Home (WFH) requests → Field #3\n"
            "   • Primary high-resolution photo source for employee ID cards\n\n"
            "2. 🌐 Keka Portal Automation (Web Extraction):\n"
            "   • Automates login to export the evaluated Attendance Report → Field #2\n"
            "   • Offline AI OCR solves Keka visual captchas in real-time\n"
            "   • If 2FA OTP is active, manually select Field #2 and click Process\n\n"
            "3. 💬 Slack Workspace API (Secondary Fallback):\n"
            "   • Queries Slack email lookup for users without uploaded Keka avatars\n"
            "   • Automatically discards default avatars to maintain ID card quality"
        )
        ctk.CTkLabel(
            guide_content, text=guide_text,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT, justify="left", anchor="w"
        ).pack(fill="both", expand=True, padx=12, pady=10)

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

    # ---------------------------------------------------------
    # Workforce Intelligence Auto-Sync from Time & Leave Master
    # ---------------------------------------------------------
    def get_latest_time_leave_output(self) -> Optional[str]:
        """Find the most recent Time & Leave Master generated Excel output."""
        if self.last_time_leave_output_path and os.path.exists(self.last_time_leave_output_path):
            p = Path(self.last_time_leave_output_path)
            if not p.name.startswith("~$") and p.stat().st_size > 1000:
                return self.last_time_leave_output_path

        search_dirs = [Path("."), Path("output"), Path("local_data")]
        try:
            dl = Path.home() / "Downloads"
            if dl.exists():
                search_dirs.append(dl)
        except Exception:
            pass

        candidates = []
        for d in search_dirs:
            if d.exists() and d.is_dir():
                try:
                    for f in d.glob("*.xlsx"):
                        # Strictly ignore Excel lock/owner files and hidden files
                        if f.name.startswith("~$") or f.name.startswith("."):
                            continue
                        fn_lower = f.name.lower()
                        if ("daily" in fn_lower and "performance" in fn_lower) or ("time" in fn_lower and "leave" in fn_lower):
                            try:
                                st = f.stat()
                                if st.st_size > 1000:
                                    # Give higher priority weight to unified master outputs
                                    weight = 2 if "time_and_leave_master" in fn_lower else 1
                                    candidates.append((st.st_mtime * weight, st.st_mtime, str(f.resolve())))
                            except Exception:
                                pass
                except Exception:
                    pass
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][2]
        return None


    def open_workforce_sync_dialog(self):
        """
        Open a modern modal dialog for Multi-Month Historical Synchronization & Archive Management.
        Bypasses Keka's 1-month API restriction by partitioning multi-month syncs into sequential
        calendar-month requests, saving each into local_data/historical_archive, and assembling
        unified multi-month time series for analysis.
        """
        from workforce_intelligence.historical_sync import historical_sync_manager

        top = ctk.CTkToplevel(self)
        top.title("Workforce Data Sync Center & Historical Archive")
        top.geometry("740x590")
        top.resizable(False, False)
        top.configure(fg_color=ui.COLOR_BG)
        top.transient(self)
        top.grab_set()

        # Center dialog
        top.update_idletasks()
        try:
            x = self.winfo_rootx() + (self.winfo_width() - 740) // 2
            y = self.winfo_rooty() + (self.winfo_height() - 590) // 2
            top.geometry(f"+{max(30, x)}+{max(30, y)}")
        except Exception:
            pass

        # Container Card
        card = ui.create_card(top)
        card.pack(fill="both", expand=True, padx=14, pady=14)
        card.grid_columnconfigure(0, weight=1)

        # Header
        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(10, 6))

        hdr_left = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_left.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            hdr_left, text="⚡ Workforce Data Sync Center & Historical Archive",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(anchor="w")

        ctk.CTkLabel(
            hdr_left, text="Sync historical months from Keka (last 3M), import older exported reports, and manage local archive.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(anchor="w", pady=(2, 0))

        def _do_import_file(target_m_key=None):
            from tkinter import filedialog
            target_disp = historical_sync_manager.get_month_display_name(target_m_key) if target_m_key else ""
            fn = filedialog.askopenfilename(
                title=f"Select Keka Performance / Attendance File{' for ' + target_disp if target_disp else ''}",
                filetypes=[
                    ("Excel & CSV Files", "*.xlsx;*.xls;*.csv;*.parquet"),
                    ("Excel Workbook (*.xlsx)", "*.xlsx"),
                    ("CSV File (*.csv)", "*.csv"),
                    ("All Files", "*.*"),
                ]
            )
            if not fn:
                return

            res = historical_sync_manager.import_attendance_file(fn, target_month_key=target_m_key)
            if res["success"]:
                _refresh_list()
                m_names = [historical_sync_manager.get_month_display_name(k) for k in res["imported_months"]]
                dlg_status_lbl.configure(
                    text=f"✓ Imported {len(res['imported_months'])} month(s): {', '.join(m_names)} ({res['total_records']:,} rows) into archive!",
                    text_color="#10B981"
                )
                messagebox.showinfo(
                    "Import Successful",
                    f"Successfully imported {len(res['imported_months'])} month(s) into your local archive:\n\n"
                    f"• Month(s): {', '.join(m_names)}\n"
                    f"• Total Records: {res['total_records']:,}\n\n"
                    "These months are now saved in your archive and ready for workforce analysis."
                )
            else:
                messagebox.showerror("Import Failed", f"Could not import file:\n\n{res.get('error')}")

        ui.create_secondary_button(
            hdr, "📂 Import File...", lambda: _do_import_file(),
            width=135, height=28, icon="folder"
        ).pack(side="right", padx=(6, 0), pady=4)

        # Presets Bar
        presets_bar = ctk.CTkFrame(card, fg_color=ui.COLOR_INPUT_BG, corner_radius=6)
        presets_bar.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(
            presets_bar, text="Quick Select:",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_DIM
        ).pack(side="left", padx=(10, 6), pady=6)

        months_data = historical_sync_manager.get_available_months_grid(past_n_months=12)
        month_vars: Dict[str, ctk.BooleanVar] = {}

        def _select_preset(n_months: int):
            for i, m_info in enumerate(months_data):
                m_key = m_info["month_key"]
                if m_key in month_vars:
                    month_vars[m_key].set(i < n_months)

        def _select_api_eligible():
            for m_info in months_data:
                m_key = m_info["month_key"]
                if m_key in month_vars:
                    month_vars[m_key].set(m_info.get("is_api_eligible", False))

        def _select_all_synced():
            for m_info in months_data:
                m_key = m_info["month_key"]
                if m_key in month_vars:
                    month_vars[m_key].set(m_info["is_synced"])

        def _select_all():
            for m_info in months_data:
                m_key = m_info["month_key"]
                if m_key in month_vars:
                    month_vars[m_key].set(True)

        ui.create_secondary_button(presets_bar, "Current Month", lambda: _select_preset(1), width=90, height=24).pack(side="left", padx=2, pady=6)
        ui.create_secondary_button(presets_bar, "Trailing 3M (API)", _select_api_eligible, width=110, height=24).pack(side="left", padx=2, pady=6)
        ui.create_secondary_button(presets_bar, "All Synced", _select_all_synced, width=80, height=24).pack(side="left", padx=2, pady=6)
        ui.create_secondary_button(presets_bar, "Select All", _select_all, width=75, height=24).pack(side="left", padx=2, pady=6)

        # Historical Months Archive List (Scrollable)
        list_container = ctk.CTkFrame(card, fg_color="transparent")
        list_container.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        # List Header
        list_hdr = ctk.CTkFrame(list_container, fg_color="#1E293B", corner_radius=4, height=24)
        list_hdr.pack(fill="x", pady=(0, 2))
        list_hdr.grid_columnconfigure(0, weight=3, minsize=140)
        list_hdr.grid_columnconfigure(1, weight=3, minsize=160)
        list_hdr.grid_columnconfigure(2, weight=2, minsize=130)
        list_hdr.grid_columnconfigure(3, weight=2, minsize=110)

        ctk.CTkLabel(list_hdr, text="Month / Period", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9, weight="bold"), text_color=ui.COLOR_TEXT_DIM, anchor="w").grid(row=0, column=0, sticky="nsew", padx=8, pady=2)
        ctk.CTkLabel(list_hdr, text="Archive Status & Volume", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9, weight="bold"), text_color=ui.COLOR_TEXT_DIM, anchor="w").grid(row=0, column=1, sticky="nsew", padx=4, pady=2)
        ctk.CTkLabel(list_hdr, text="Last Synced", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9, weight="bold"), text_color=ui.COLOR_TEXT_DIM, anchor="w").grid(row=0, column=2, sticky="nsew", padx=4, pady=2)
        ctk.CTkLabel(list_hdr, text="Action", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9, weight="bold"), text_color=ui.COLOR_TEXT_DIM, anchor="center").grid(row=0, column=3, sticky="nsew", padx=4, pady=2)

        scroll_list = ctk.CTkScrollableFrame(list_container, fg_color="transparent", height=180)
        scroll_list.pack(fill="both", expand=True)
        scroll_list.grid_columnconfigure(0, weight=1)

        def _refresh_list():
            for child in scroll_list.winfo_children():
                child.destroy()

            current_grid = historical_sync_manager.get_available_months_grid(past_n_months=12)
            for r_idx, m_info in enumerate(current_grid):
                m_key = m_info["month_key"]
                if m_key not in month_vars:
                    # Default: select trailing 3 months
                    month_vars[m_key] = ctk.BooleanVar(value=(r_idx < 3))

                row_box = ctk.CTkFrame(scroll_list, fg_color="#131B2E" if r_idx % 2 == 0 else "#0F172A", corner_radius=4, height=30)
                row_box.pack(fill="x", pady=1)
                row_box.grid_columnconfigure(0, weight=3, minsize=140)
                row_box.grid_columnconfigure(1, weight=3, minsize=160)
                row_box.grid_columnconfigure(2, weight=2, minsize=130)
                row_box.grid_columnconfigure(3, weight=2, minsize=110)

                # Col 0: Checkbox + Month
                chk_box = ctk.CTkFrame(row_box, fg_color="transparent")
                chk_box.grid(row=0, column=0, sticky="nsew", padx=6, pady=2)
                chk = ctk.CTkCheckBox(
                    chk_box, text=m_info["display_name"], variable=month_vars[m_key],
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
                    text_color=ui.COLOR_TEXT, checkbox_width=16, checkbox_height=16,
                    border_width=1, corner_radius=3, fg_color=ui.COLOR_ACCENT
                )
                chk.pack(side="left", padx=2)

                # Col 1: Status & Records
                if m_info["is_synced"]:
                    src_tag = " (File)" if m_info.get("source") == "FILE_IMPORT" else ""
                    st_text = f"✓ {m_info['record_count']:,} rows ({m_info['headcount']} emps){src_tag}"
                    st_col = "#10B981"
                elif m_info.get("is_api_eligible"):
                    st_text = "○ API Ready (Last 3M)"
                    st_col = ui.COLOR_TEXT_SEC
                else:
                    st_text = "○ Import Needed (>3M)"
                    st_col = "#F59E0B"

                ctk.CTkLabel(
                    row_box, text=st_text,
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold" if m_info["is_synced"] else "normal"),
                    text_color=st_col, anchor="w"
                ).grid(row=0, column=1, sticky="nsew", padx=4, pady=2)

                # Col 2: Last Synced
                ctk.CTkLabel(
                    row_box, text=m_info["last_synced"],
                    font=ctk.CTkFont(family=ui.FONT_FAMILY, size=9),
                    text_color=ui.COLOR_TEXT_SEC, anchor="w"
                ).grid(row=0, column=2, sticky="nsew", padx=4, pady=2)

                # Col 3: Action Buttons (Re-sync / Import & Delete)
                act_box = ctk.CTkFrame(row_box, fg_color="transparent")
                act_box.grid(row=0, column=3, sticky="nsew", padx=4, pady=2)

                def _make_resync(mk=m_key):
                    return lambda: _do_sync_months([mk])

                def _make_import(mk=m_key):
                    return lambda: _do_import_file(target_m_key=mk)

                def _make_delete(mk=m_key):
                    def _del():
                        historical_sync_manager.delete_month(mk)
                        _refresh_list()
                    return _del

                if m_info.get("is_api_eligible"):
                    ui.create_secondary_button(act_box, "🔄 Re-sync" if m_info["is_synced"] else "⚡ Sync", _make_resync(), width=68, height=22).pack(side="left", padx=2)
                else:
                    ui.create_secondary_button(act_box, "📂 Re-import" if m_info["is_synced"] else "📂 Import", _make_import(), width=68, height=22).pack(side="left", padx=2)

                if m_info["is_synced"]:
                    ui.create_secondary_button(act_box, "✕", _make_delete(), width=22, height=22).pack(side="left", padx=2)

        _refresh_list()

        # Live Progress & Status
        status_box = ctk.CTkFrame(card, fg_color=ui.COLOR_INPUT_BG, corner_radius=6)
        status_box.pack(fill="x", padx=14, pady=(4, 8))

        dlg_status_lbl = ctk.CTkLabel(
            status_box, text="⚡ Ready. Select target months to sync or load archived history.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
            text_color=ui.COLOR_TEXT_SEC, anchor="w"
        )
        dlg_status_lbl.pack(fill="x", padx=10, pady=(6, 2))

        dlg_prog = ctk.CTkProgressBar(
            status_box, height=5, corner_radius=3,
            progress_color=ui.COLOR_ACCENT, fg_color=ui.COLOR_CARD
        )
        dlg_prog.set(0.0)
        dlg_prog.pack(fill="x", padx=10, pady=(0, 6))
        dlg_prog.pack_forget()

        # Action Buttons Row
        actions_frame = ctk.CTkFrame(card, fg_color="transparent")
        actions_frame.pack(fill="x", padx=14, pady=(2, 6))

        def _get_selected_month_keys() -> List[str]:
            return [mk for mk, v in month_vars.items() if v.get()]

        def _do_sync_months(target_month_keys: Optional[List[str]] = None):
            selected = target_month_keys or _get_selected_month_keys()
            if not selected:
                messagebox.showwarning("No Months Selected", "Please select at least one month to synchronize.")
                return

            btn_sync.configure(state="disabled")
            btn_load.configure(state="disabled")
            dlg_prog.pack(fill="x", padx=10, pady=(0, 6))
            dlg_prog.start()

            def _batch_prog(idx, total, m_name, pct, msg):
                disp_pct = int(((idx - 1 + pct) / total) * 100)
                top.after(0, lambda: dlg_status_lbl.configure(
                    text=f"[{idx}/{total}] {m_name}: {msg} ({disp_pct}%)",
                    text_color=ui.COLOR_ACCENT
                ))

            def _worker():
                try:
                    subdomain = id_card.clean_keka_subdomain(self.keka_subdomain_var.get() or os.getenv("KEKA_SUBDOMAIN", "moshpit"))
                    client_id = (self.keka_client_id_var.get() or os.getenv("KEKA_CLIENT_ID", "")).strip()
                    client_secret = (self.keka_client_secret_var.get() or os.getenv("KEKA_CLIENT_SECRET", "")).strip()
                    api_key = (self.keka_api_key_var.get() or os.getenv("KEKA_API_KEY", "")).strip()
                    keka_email = (self.keka_login_email_var.get() or os.getenv("KEKA_LOGIN_EMAIL", "")).strip()
                    keka_password = (self.keka_login_password_var.get() or os.getenv("KEKA_LOGIN_PASSWORD", "")).strip()

                    from keka_data_fetcher import KekaDataFetcher
                    fetcher = KekaDataFetcher(
                        subdomain=subdomain,
                        api_key=api_key,
                        client_id=client_id,
                        client_secret=client_secret,
                        keka_email=keka_email,
                        keka_password=keka_password,
                    )

                    res = historical_sync_manager.sync_multiple_months_keka(
                        month_keys=selected,
                        keka_fetcher=fetcher,
                        batch_progress_callback=_batch_prog
                    )

                    def _on_finish():
                        btn_sync.configure(state="normal")
                        btn_load.configure(state="normal")
                        dlg_prog.stop()
                        dlg_prog.pack_forget()
                        _refresh_list()

                        if res["errors"]:
                            err_str = "\n".join(res["errors"])
                            messagebox.showwarning("Sync Completed with Notices", f"Synced {res['total_synced']} of {res['total_requested']} months.\n\nNotices:\n{err_str}")
                        else:
                            dlg_status_lbl.configure(
                                text=f"✓ Successfully synced {res['total_synced']} months ({res['total_records']:,} total records)!",
                                text_color="#10B981"
                            )

                    top.after(0, _on_finish)
                except Exception as e:
                    err_msg = str(e)
                    def _on_err():
                        btn_sync.configure(state="normal")
                        btn_load.configure(state="normal")
                        dlg_prog.stop()
                        dlg_prog.pack_forget()
                        messagebox.showerror("Sync Error", f"Historical sync encountered an error:\n\n{err_msg}")
                    top.after(0, _on_err)

            threading.Thread(target=_worker, daemon=True).start()

        def _do_load_archive():
            selected = _get_selected_month_keys()
            top.destroy()
            self.load_workforce_from_historical_archive(month_keys=selected, show_feedback=True)

        btn_sync = ui.create_primary_button(
            actions_frame, "⚡ Sync Selected Months", lambda: _do_sync_months(),
            width=190, height=34, icon="refresh"
        )
        btn_sync.pack(side="left", padx=(0, 6))

        btn_load = ui.create_primary_button(
            actions_frame, "📊 Load Archive into Dashboard", _do_load_archive,
            width=220, height=34, icon="sync"
        )
        btn_load.pack(side="left", padx=(0, 6))

        ui.create_secondary_button(
            actions_frame, "Close", top.destroy,
            width=70, height=34
        ).pack(side="right")

    def load_workforce_from_historical_archive(self, month_keys: Optional[List[str]] = None, show_feedback: bool = True):
        """
        Load multi-month historical time series directly from local archive into active snapshot.
        Eliminates workbook I/O overhead while providing full multi-month analytics.
        """
        from workforce_intelligence.historical_sync import historical_sync_manager
        df_unified, summary = historical_sync_manager.load_unified_history(month_keys=month_keys)

        if df_unified.empty:
            if show_feedback:
                messagebox.showinfo(
                    "No Archived History Found",
                    "No synced historical months were found in your local archive.\n\n"
                    "Please click '⚡ Sync Time & Leave' to pull historical months from Keka first."
                )
            return False

        self.is_ts_loading = True
        if hasattr(self, "btn_ts_load"):
            self.btn_ts_load.configure(state="disabled")
        if hasattr(self, "ts_prog"):
            self.ts_prog.grid()
            self.ts_prog.start()
        if hasattr(self, "ts_dot") and hasattr(self, "ts_lbl"):
            ui.update_status(self.ts_dot, self.ts_lbl, f"Activating {summary['months_count']} historical months ({summary['total_records']:,} rows)...", "processing")

        self._latest_ts_job_id += 1
        job_id = self._latest_ts_job_id

        def _worker():
            try:
                # Prepare dataset directly from unified DataFrame
                snapshot = snapshot_service.prepare_dataset(df_unified)
                def _on_success():
                    self._ts_load_success(snapshot, f"Historical Archive ({summary['months_count']} Months)", job_id)
                    if show_feedback:
                        messagebox.showinfo(
                            "Historical Archive Loaded",
                            f"Successfully activated Workforce Intelligence Historical Archive!\n\n"
                            f"• Total Months: {summary['months_count']} ({', '.join(summary['months'])})\n"
                            f"• Total Records: {snapshot.row_count:,}\n"
                            f"• Active Headcount: {snapshot.metadata.get('employee_count', 0):,}\n"
                            f"• Date Span: {snapshot.metadata.get('min_date', 'N/A')} to {snapshot.metadata.get('max_date', 'N/A')}\n\n"
                            f"Executive Overview, 3-Month Moving Averages, Trajectories, Heatmaps, and Driver Attributions are now live."
                        )
                self.after(0, _on_success)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda m=err_msg: self._ts_load_error(m, job_id))

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def sync_workforce_from_time_leave(self, file_path: Optional[str] = None, show_feedback: bool = True):
        """
        Automatically sync Workforce Intelligence directly with the Time & Leave Master output.
        Eliminates manual file browsing and ingestion overhead.
        """
        target_path = file_path or self.get_latest_time_leave_output()
        if not target_path or not os.path.exists(target_path):
            if show_feedback:
                messagebox.showinfo(
                    "No Time & Leave Master File Found",
                    "No recent Time & Leave Master output file was found.\n\n"
                    "Please run 'Time and Leave Master' in the Transform menu first, or upload a dataset manually in the Upload section."
                )
            return False

        self.last_time_leave_output_path = str(target_path)
        self.ts_file_path.set(str(target_path))

        self.is_ts_loading = True
        if hasattr(self, "btn_ts_load"):
            self.btn_ts_load.configure(state="disabled")
        if hasattr(self, "ts_prog"):
            self.ts_prog.grid()
            self.ts_prog.start()
        if hasattr(self, "ts_dot") and hasattr(self, "ts_lbl"):
            ui.update_status(self.ts_dot, self.ts_lbl, f"Syncing from Time & Leave Master ({Path(target_path).name})...", "processing")

        self._latest_ts_job_id += 1
        job_id = self._latest_ts_job_id

        def _worker():
            try:
                snapshot = snapshot_service.prepare_dataset(target_path)
                def _on_success():
                    self._ts_load_success(snapshot, target_path, job_id)
                    if show_feedback:
                        messagebox.showinfo(
                            "Workforce Intelligence Synced",
                            f"Successfully synced with Time & Leave Master output!\n\n"
                            f"• File: {Path(target_path).name}\n"
                            f"• Records: {snapshot.row_count:,}\n"
                            f"• Employees: {snapshot.metadata.get('employee_count', 0):,}\n"
                            f"• Date Range: {snapshot.metadata.get('min_date', 'N/A')} to {snapshot.metadata.get('max_date', 'N/A')}\n\n"
                            f"All KPI metrics, attendance composition, and breakdowns are now live."
                        )
                self.after(0, _on_success)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda m=err_msg: self._ts_load_error(m, job_id))

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def _build_workforce_intelligence_frame(self):
        from workforce_intelligence.dashboard_shell import WorkforceDashboardView
        self.workforce_dashboard_view = WorkforceDashboardView(self.main_content, app=self)
        self.frames["workforce_intelligence"] = self.workforce_dashboard_view
        self.frames["analyse_time_series"] = self.workforce_dashboard_view
        self.frames["analyse_dashboard"] = self.workforce_dashboard_view

    # ---------------------------------------------------------
    # Time Series Analysis (Consolidated into Workforce Intelligence)
    # ---------------------------------------------------------
    def _build_time_series_frame(self):
        """Unified into Workforce Intelligence; aliased for backwards compatibility."""
        if hasattr(self, "workforce_dashboard_view"):
            self.frames["analyse_time_series"] = self.workforce_dashboard_view
            self.frames["analyse_dashboard"] = self.workforce_dashboard_view

    # ---------------------------------------------------------
    # Analyse Upload
    # ---------------------------------------------------------
    def _build_analyse_upload_frame(self):
        f = ctk.CTkScrollableFrame(self.main_content, fg_color="transparent")
        self.frames["analyse_upload"] = f
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        hdr = ui.create_page_header(
            f, "Upload Dataset",
            "Upload Daily Performance report or attendance logs (.xlsx, .xls, .csv) for Workforce Intelligence."
        )
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        actions = ctk.CTkFrame(hdr, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        ui.create_secondary_button(actions, "← Workforce Intelligence", lambda: self.select_frame_by_name("workforce_intelligence"), 180).pack(side="left")

        # Fast Sync with Time & Leave Master Card
        sync_card = ui.create_card(f)
        sync_card.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        sync_card.grid_columnconfigure(0, weight=1)

        sync_inner = ctk.CTkFrame(sync_card, fg_color="transparent")
        sync_inner.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        sync_inner.grid_columnconfigure(0, weight=1)

        s_left = ctk.CTkFrame(sync_inner, fg_color="transparent")
        s_left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            s_left, text="⚡ Auto-Sync from Time & Leave Master",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).pack(anchor="w")
        ctk.CTkLabel(
            s_left, text="Directly synchronize with the latest Daily Performance output file without manual re-upload.",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC
        ).pack(anchor="w", pady=(2, 0))

        ui.create_primary_button(
            sync_inner, "⚡ Sync Latest Output",
            lambda: self.sync_workforce_from_time_leave(show_feedback=True),
            width=180, height=32, icon="refresh"
        ).grid(row=0, column=1, sticky="e", padx=(10, 0))

        # Upload Card
        card = ui.create_card(f)
        card.grid(row=2, column=0, sticky="nsew", pady=(0, 12))

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
        res_card.grid(row=3, column=0, sticky="nsew")
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
            res_top, "🚀 Open Workforce Intelligence →",
            lambda: self.select_frame_by_name("workforce_intelligence"), width=240
        )
        self.btn_ts_open_tsa.pack(side="right")
        self.btn_ts_open_tsa.configure(state="disabled")

        self.ts_upload_summary_text = ctk.CTkTextbox(
            res_card, height=140, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, text_color=ui.COLOR_TEXT, corner_radius=6
        )
        self.ts_upload_summary_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.ts_upload_summary_text.insert("0.0", "Select an attendance or performance dataset above and click 'Load & Ingest Dataset'.\nOnce loaded, all metrics and breakdowns will be instantly populated in Workforce Intelligence.")
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
                f"Status: Ready for Workforce Intelligence! Click 'Open Workforce Intelligence →' above."
            )
            self.ts_upload_summary_text.insert("0.0", summary_info)
            self.ts_upload_summary_text.configure(state="disabled")

        # Update Time Series banner
        if hasattr(self, "ts_banner_lbl"):
            self.ts_banner_lbl.configure(
                text=f"📊 Active Dataset: {p_name}  •  {total_rows:,} records  •  {total_emps:,} employees",
                text_color=ui.COLOR_SUCCESS
            )
        if hasattr(self, "btn_ts_go_upload"):
            self.btn_ts_go_upload.configure(text="📂 Change Dataset")

        # Populate filters if legacy controls exist
        if hasattr(self, "ts_bu_combo"):
            self.ts_bu_combo.configure(values=["All Business Units"] + bus)
            self.ts_bu_var.set("All Business Units")

        if hasattr(self, "ts_dept_combo"):
            self.ts_dept_combo.configure(values=["All Departments"] + depts)
            self.ts_dept_var.set("All Departments")

        if hasattr(self, "ts_month_combo"):
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
        if hasattr(self, "ts_level_var"):
            self.ts_level_var.set(choice)
        self._refresh_ts_table(reload_data=True)

    def _reset_ts_filters(self):
        if hasattr(self, "ts_bu_var"):
            self.ts_bu_var.set("All Business Units")
        if hasattr(self, "ts_dept_var"):
            self.ts_dept_var.set("All Departments")
        if hasattr(self, "ts_month_var"):
            self.ts_month_var.set("All Months")
        if hasattr(self, "ts_search_var"):
            self.ts_search_var.set("")
        self._refresh_ts_dashboard()

    def _refresh_ts_dashboard(self):
        if not snapshot_service.has_active_snapshot():
            return
        if not hasattr(self, "lbl_kpi_leave_val"):
            return

        bu = self.ts_bu_var.get() if hasattr(self, "ts_bu_var") else None
        dept = self.ts_dept_var.get() if hasattr(self, "ts_dept_var") else None
        month = self.ts_month_var.get() if hasattr(self, "ts_month_var") else None

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
        if not hasattr(self, "ts_tree"):
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

    def _update_portal_badge(self, msg: str, status_type: str):
        """Updates Keka Portal status badge in Settings."""
        for dot, lbl in [
            (getattr(self, "settings_portal_dot", None), getattr(self, "settings_portal_lbl", None)),
        ]:
            if dot and lbl:
                try:
                    ui.update_status(dot, lbl, msg, status_type)
                except Exception:
                    pass

    def save_connectors_credentials(self, which="all"):
        """
        Saves current entered credentials to .env file permanently.
        Supports saving all credentials or granularly per integration (keka_api, keka_portal, slack).
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

        if which in ("all", "keka", "keka_api"):
            sub = id_card.clean_keka_subdomain(self.keka_subdomain_var.get())
            if hasattr(self.keka_subdomain_var, "set"):
                self.keka_subdomain_var.set(sub)
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

        if which in ("all", "keka", "keka_portal"):
            login_email = self.keka_login_email_var.get().strip()
            login_pwd = self.keka_login_password_var.get().strip()
            if login_email:
                id_card.save_env_variable("KEKA_LOGIN_EMAIL", login_email)
                saved_items.append("KEKA_LOGIN_EMAIL")
            if login_pwd:
                id_card.save_env_variable("KEKA_LOGIN_PASSWORD", login_pwd)
                saved_items.append("KEKA_LOGIN_PASSWORD")

        item_str = ", ".join(saved_items) if saved_items else "No credentials specified"
        log_msg = f"[SETTINGS] ✓ Saved to .env ({which}): {item_str}\n"
        self._append_connector_log(log_msg)

        title = "Credentials Saved"
        if which == "keka_api":
            title = "Keka API Credentials Saved"
        elif which == "keka_portal":
            title = "Keka Portal Credentials Saved"
        elif which == "slack":
            title = "Slack Credentials Saved"

        messagebox.showinfo(
            title,
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
        subdomain = id_card.clean_keka_subdomain(self.keka_subdomain_var.get())
        if hasattr(self.keka_subdomain_var, "set"):
            self.keka_subdomain_var.set(subdomain)
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
                                btn.configure(text="Connect & Test API", state="normal")
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

    def connect_keka_portal_now(self):
        """Validates Keka Web Portal login credentials and captcha solving in background."""
        email = self.keka_login_email_var.get().strip()
        pwd = self.keka_login_password_var.get().strip()
        sub = id_card.clean_keka_subdomain(self.keka_subdomain_var.get().strip() or os.getenv("KEKA_SUBDOMAIN", "moshpit"))
        if hasattr(self.keka_subdomain_var, "set"):
            self.keka_subdomain_var.set(sub)

        if not email or not pwd:
            messagebox.showwarning(
                "Portal Credentials Missing",
                "Please enter your Keka Portal Login Email and Password before testing."
            )
            return

        for btn in [getattr(self, "settings_btn_test_portal", None)]:
            if btn:
                try:
                    btn.configure(text="Testing...", state="disabled")
                except Exception:
                    pass
        self._update_portal_badge("Testing portal...", "processing")
        self._append_connector_log(f"\n[PORTAL] Testing Keka Web Portal login for {email} ({sub}.keka.com)...\n")

        def _worker():
            is_ok, msg, details = id_card.check_keka_portal_status(
                email=email, password=pwd, subdomain=sub, headless=True
            )

            def _finish():
                try:
                    for btn in [getattr(self, "settings_btn_test_portal", None)]:
                        if btn:
                            try:
                                btn.configure(text="Test Portal Login", state="normal")
                            except Exception:
                                pass

                    status = details.get("status", "")
                    if is_ok and status == "2fa_required":
                        self._update_portal_badge("2FA Active (Needs Auth)", "warning")
                        self._append_connector_log(f"[PORTAL] ⚠️ {msg}\n")
                        launch_now = messagebox.askyesno(
                            "Keka 2FA Active: Authorize Now?",
                            f"✅ Credentials and Captcha verified successfully!\n\n"
                            f"ℹ️ Keka 2FA (Two-Factor Authentication) is active on this account.\n\n"
                            f"Would you like to open the browser now to complete 2FA or Single Sign-On (SSO) and save your session?\n\n"
                            f"• Click 'Yes' to launch Chrome, log in, and check 'Remember this browser'.\n"
                            f"• Once completed, 2FA will be completely bypassed for future automated syncs!"
                        )
                        if launch_now:
                            self.authorize_keka_portal_in_browser()
                    elif is_ok:
                        self._update_portal_badge("Session Active (Remembered)", "success")
                        self._append_connector_log(f"[PORTAL] ✓ Keka portal login success: {msg}\n")
                        messagebox.showinfo(
                            "Keka Portal Connected",
                            f"✅ Keka web portal login succeeded!\n\n{msg}"
                        )
                    else:
                        self._update_portal_badge("Login Failed", "error")
                        self._append_connector_log(f"[PORTAL] ✕ Keka portal login failed: {msg}\n")
                        messagebox.showerror(
                            "Keka Portal Login Failed",
                            f"Failed to log into Keka web portal:\n\n{msg}\n\n"
                            "Please check your email, password, and organization subdomain."
                        )
                except Exception:
                    pass

            try:
                self.after(0, _finish)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def authorize_keka_portal_in_browser(self):
        """Launches an interactive Chrome window to authenticate via SSO or 2FA and persist the session."""
        email = self.keka_login_email_var.get().strip()
        pwd = self.keka_login_password_var.get().strip()
        sub = id_card.clean_keka_subdomain(self.keka_subdomain_var.get().strip() or os.getenv("KEKA_SUBDOMAIN", "moshpit"))
        if hasattr(self.keka_subdomain_var, "set"):
            self.keka_subdomain_var.set(sub)

        for btn in [getattr(self, "settings_btn_auth_portal", None), getattr(self, "settings_btn_test_portal", None)]:
            if btn:
                try:
                    btn.configure(state="disabled")
                except Exception:
                    pass

        self._update_portal_badge("Waiting for browser...", "processing")
        self._append_connector_log(
            f"\n[PORTAL] Opening interactive Chrome window for SSO / 2FA authorization ({sub}.keka.com)...\n"
            f"[PORTAL] 1. Single Sign-On: Click 'Office 365' or 'Google' in the browser to sign in.\n"
            f"[PORTAL] 2. Two-Factor Auth: Enter password + OTP, and ensure 'Remember this browser' is checked.\n"
            f"[PORTAL] The application will automatically detect your active session and save cookies permanently.\n"
        )

        def _worker():
            def _on_update(msg):
                try:
                    self.after(0, lambda: self._append_connector_log(f"[PORTAL] {msg}\n"))
                except Exception:
                    pass

            is_ok, msg, details = id_card.authorize_keka_portal_in_browser(
                subdomain=sub,
                email=email,
                password=pwd,
                timeout=180,
                on_status_update=_on_update
            )

            def _finish():
                try:
                    for btn in [getattr(self, "settings_btn_auth_portal", None), getattr(self, "settings_btn_test_portal", None)]:
                        if btn:
                            try:
                                btn.configure(state="normal")
                            except Exception:
                                pass

                    if is_ok:
                        self._update_portal_badge("Session Active (Remembered)", "success")
                        self._append_connector_log(f"[PORTAL] ✓ {msg}\n")
                        messagebox.showinfo(
                            "Keka Session Saved",
                            f"✅ Keka Session Successfully Authorized!\n\n"
                            f"Your authenticated session cookies have been saved to your local Chrome profile.\n\n"
                            f"Two-Factor Authentication (2FA) and Single Sign-On (SSO) are now remembered. "
                            f"All future Absent Management syncs will run automatically in the background without prompting for 2FA!"
                        )
                    else:
                        self._update_portal_badge("Auth Incomplete", "warning")
                        self._append_connector_log(f"[PORTAL] ⚠️ {msg}\n")
                        messagebox.showwarning(
                            "Browser Authorization Incomplete",
                            f"Browser session was not completed:\n\n{msg}\n\n"
                            "You can click 'Authorize in Browser 🌐' anytime to try again."
                        )
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

    def refresh_keka_portal_status(self):
        """Checks Keka Portal connection in background."""
        self.connect_keka_portal_now()

    def _refresh_all_connectors(self):
        """Refreshes Slack, Keka API, and Keka Portal connections."""
        self.connect_slack_now()
        self.connect_keka_now()
        self.connect_keka_portal_now()


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

    def pull_keka_absent_data(self):
        """Pulls Employee Master and OD/WFH reports from Keka API in background thread."""
        from_str = self.absent_from_date_var.get().strip()
        to_str = self.absent_to_date_var.get().strip()

        # Convert DD-MM-YYYY to YYYY-MM-DD for Keka API
        def parse_to_iso(dt_str):
            try:
                for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        return datetime.strptime(dt_str, fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        continue
            except Exception:
                pass
            return dt_str

        from_iso = parse_to_iso(from_str)
        to_iso = parse_to_iso(to_str)

        subdomain = id_card.clean_keka_subdomain(self.keka_subdomain_var.get() or os.getenv("KEKA_SUBDOMAIN", "moshpit"))
        client_id = (self.keka_client_id_var.get() or os.getenv("KEKA_CLIENT_ID", "")).strip()
        client_secret = (self.keka_client_secret_var.get() or os.getenv("KEKA_CLIENT_SECRET", "")).strip()
        api_key = (self.keka_api_key_var.get() or os.getenv("KEKA_API_KEY", "")).strip()
        keka_email = (self.keka_login_email_var.get() or os.getenv("KEKA_LOGIN_EMAIL", "")).strip()
        keka_password = (self.keka_login_password_var.get() or os.getenv("KEKA_LOGIN_PASSWORD", "")).strip()

        if not api_key and not (client_id and client_secret):
            messagebox.showerror(
                "Keka Credentials Missing",
                "Keka API credentials are not configured.\n\n"
                "Please configure Client ID, Client Secret & API Key in the\n"
                "'Connectors & Settings' tab or in your .env file."
            )
            return

        include_attendance = self.absent_include_portal_var.get()

        self.btn_pull_keka.configure(state="disabled")
        ui.update_status(self.absent_keka_dot, self.absent_keka_lbl, "Connecting to Keka API...", "processing")

        def update_progress(pct, step, detail=""):
            def _ui():
                try:
                    if hasattr(self, "absent_progress_bar"):
                        self.absent_progress_bar.set(max(0.0, min(1.0, pct)))
                    if hasattr(self, "absent_progress_pct_lbl"):
                        self.absent_progress_pct_lbl.configure(text=f"{int(pct * 100)}%")
                    if hasattr(self, "absent_progress_step_lbl"):
                        self.absent_progress_step_lbl.configure(text=step)
                    if hasattr(self, "absent_progress_detail_lbl") and detail:
                        self.absent_progress_detail_lbl.configure(text=detail)
                except Exception:
                    pass
            self.after(0, _ui)

        def _worker():
            try:
                update_progress(0.05, "Connecting to Keka API...", "Validating OAuth Bearer credentials...")
                import concurrent.futures
                from keka_data_fetcher import KekaDataFetcher

                fetcher = KekaDataFetcher(
                    subdomain=subdomain,
                    api_key=api_key,
                    client_id=client_id,
                    client_secret=client_secret,
                    keka_email=keka_email,
                    keka_password=keka_password,
                )

                exports_dir = Path.cwd() / "local_data" / "keka_exports"
                exports_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                update_progress(0.15, "Fast Multi-Threaded Syncing...", "Pulling Employee Master and OD/WFH in parallel...")

                # ── Fast Parallel Fetching for Employee Master & OD/WFH ──
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    future_emp = executor.submit(
                        fetcher.fetch_employee_master,
                        active_only=True,
                        progress_callback=lambda p, t, msg: update_progress(0.15 + (p / max(1, t)) * 0.25, "[1/3] Employee Master", msg)
                    )
                    future_wfh = executor.submit(
                        fetcher.fetch_od_wfh_requests,
                        from_date=from_iso,
                        to_date=to_iso,
                        progress_callback=lambda msg: update_progress(0.45, "[2/3] OD/WFH Requests", msg)
                    )

                    emp_df, emp_err = future_emp.result()
                    wfh_df, wfh_err = future_wfh.result()

                if emp_err and emp_df.empty:
                    raise RuntimeError(f"Employee Master pull failed: {emp_err}")

                emp_path = exports_dir / f"Employee_Master_{timestamp}.xlsx"
                fetcher._save_styled_excel(emp_df, emp_path)
                update_progress(0.48, "[1/3] Employee Master Ready", f"Saved {len(emp_df)} employees to {emp_path.name}")

                # 2. Process OD/WFH Results
                wfh_path = None
                wfh_scope_missing = False
                if wfh_err and wfh_df.empty:
                    if "403" in wfh_err or "privilege" in wfh_err.lower() or "scope" in wfh_err.lower():
                        wfh_scope_missing = True
                        wfh_path = exports_dir / f"OD_WFH_Requests_Template_{timestamp}.xlsx"
                        fetcher._save_styled_excel(wfh_df, wfh_path)
                    else:
                        raise RuntimeError(f"OD/WFH pull failed: {wfh_err}")
                else:
                    wfh_path = exports_dir / f"OD_WFH_Requests_{timestamp}.xlsx"
                    fetcher._save_styled_excel(wfh_df, wfh_path)
                update_progress(0.60, "[2/3] OD/WFH Requests Ready", f"Saved {len(wfh_df)} records to {wfh_path.name}")

                # 3. Attendance Sync (Daily Performance Report via API)
                att_path = None
                att_msg = ""
                if include_attendance:
                    update_progress(0.65, "[3/3] Attendance API Sync", "Pulling attendance & leave records via Keka API...")
                    try:
                        def _portal_prog(pct, msg):
                            update_progress(pct, "[3/3] Daily Performance Report", msg)

                        att_df, att_err = fetcher.fetch_attendance_report(
                            from_date=from_iso,
                            to_date=to_iso,
                            emp_df=emp_df,
                            wfh_df=wfh_df,
                            use_api=True,
                            progress_callback=_portal_prog
                        )
                        if att_df is not None and not att_df.empty:
                            att_path = exports_dir / f"Daily_Performance_Report_{timestamp}.xlsx"
                            fetcher._save_styled_excel(att_df, att_path)
                            att_msg = f"\n• Daily Performance Report: {len(att_df)} records (auto-generated via Keka API ⚡)"
                            update_progress(0.98, "[3/3] Daily Performance Report Ready", f"Saved {len(att_df)} attendance records")
                        elif att_err:
                            att_msg = f"\n⚠️ Attendance Sync note: {att_err}"
                            update_progress(0.95, "[3/3] Attendance Sync Skipped", att_err[:80])
                    except Exception as pe:
                        att_msg = f"\n⚠️ Attendance Sync failed: {pe}"
                        update_progress(0.95, "[3/3] Attendance Sync Error", str(pe)[:80])

                update_progress(1.0, "Pull Completed Successfully! ⚡", f"Auto-filled source fields in Absent Management")

                # Update UI on main thread
                def _success():
                    self.absent_emp_file.set(str(emp_path))
                    if wfh_path:
                        self.absent_wfh_file.set(str(wfh_path))
                    if att_path:
                        self.absent_att_file.set(str(att_path))

                    self.btn_pull_keka.configure(state="normal")

                    if wfh_scope_missing:
                        ui.update_status(
                            self.absent_keka_dot,
                            self.absent_keka_lbl,
                            f"✓ Pulled {len(emp_df)} employees | OD/WFH scope missing (HTTP 403)",
                            "warning"
                        )
                        messagebox.showwarning(
                            "Keka Pull Partial Success",
                            f"✅ Employee Master pulled successfully ({len(emp_df)} employees)!\n"
                            f"Saved to: {emp_path.name} → Loaded into Field #1.\n\n"
                            f"⚠️ OD/WFH Scope Not Enabled (HTTP 403):\n"
                            f"Your Keka API key is active, but lacks permission for Remote Work (WFH) and On Duty (OD).\n\n"
                            f"To enable automatic OD/WFH pull:\n"
                            f"1. In Keka Admin Portal, go to Settings > API & Webhooks > API Keys\n"
                            f"2. Edit your API key and check 'Remote Work' and 'On Duty' permissions.\n\n"
                            f"For now, an empty OD/WFH template was created in Field #3, or you can manually browse your OD/WFH report in Field #3!"
                        )
                    else:
                        status_text = f"✓ Pulled {len(emp_df)} employees & {len(wfh_df)} OD/WFH records"
                        if att_path:
                            status_text += " + Attendance"
                        ui.update_status(self.absent_keka_dot, self.absent_keka_lbl, status_text, "success")

                        next_step = (
                            "Both files have been auto-filled into fields #1 and #3!\n"
                            "Now select the Attendance Report (Field #2) and click 'Process Data'."
                            if not att_path
                            else "All 3 files have been auto-filled! You can click 'Process Data' directly."
                        )
                        messagebox.showinfo(
                            "Keka Pull Successful",
                            f"Successfully pulled reports from Keka:\n\n"
                            f"• Employee Master: {len(emp_df)} employees\n"
                            f"  Saved to: {emp_path.name}\n\n"
                            f"• OD/WFH Requests: {len(wfh_df)} records ({from_str} to {to_str})\n"
                            f"  Saved to: {wfh_path.name}"
                            f"{att_msg}\n\n"
                            f"{next_step}"
                        )

                self.after(0, _success)

            except Exception as e:
                def _fail(err_msg):
                    self.btn_pull_keka.configure(state="normal")
                    ui.update_status(self.absent_keka_dot, self.absent_keka_lbl, "Pull failed", "error")
                    messagebox.showerror("Keka Pull Failed", str(err_msg))

                self.after(0, lambda: _fail(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

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

    def pull_keka_time_leave_data(self):
        """Pulls unified Employee Master, OD/WFH, and Attendance logs directly from Keka API in background thread."""
        from_str = self.tl_from_date_var.get().strip()
        to_str = self.tl_to_date_var.get().strip()

        # Convert DD-MM-YYYY to YYYY-MM-DD for Keka API
        def parse_to_iso(dt_str):
            try:
                for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        return datetime.strptime(dt_str, fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        continue
            except Exception:
                pass
            return dt_str

        from_iso = parse_to_iso(from_str)
        to_iso = parse_to_iso(to_str)

        subdomain = id_card.clean_keka_subdomain(self.keka_subdomain_var.get() or os.getenv("KEKA_SUBDOMAIN", "moshpit"))
        client_id = (self.keka_client_id_var.get() or os.getenv("KEKA_CLIENT_ID", "")).strip()
        client_secret = (self.keka_client_secret_var.get() or os.getenv("KEKA_CLIENT_SECRET", "")).strip()
        api_key = (self.keka_api_key_var.get() or os.getenv("KEKA_API_KEY", "")).strip()
        keka_email = (self.keka_login_email_var.get() or os.getenv("KEKA_LOGIN_EMAIL", "")).strip()
        keka_password = (self.keka_login_password_var.get() or os.getenv("KEKA_LOGIN_PASSWORD", "")).strip()

        if not api_key and not (client_id and client_secret):
            messagebox.showerror(
                "Keka Credentials Missing",
                "Keka API credentials are not configured.\n\n"
                "Please configure Client ID, Client Secret & API Key in the\n"
                "'Connectors & Settings' tab or in your .env file."
            )
            return

        out_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"Time_and_Leave_Master_Unified_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        if not out_path:
            return

        self.btn_pull_keka_tl.configure(state="disabled")
        ui.update_status(self.tl_keka_dot, self.tl_keka_lbl, "Connecting to Keka API...", "processing")

        def update_progress(pct, step, detail=""):
            def _ui():
                try:
                    if hasattr(self, "tl_keka_progress_bar"):
                        self.tl_keka_progress_bar.set(max(0.0, min(1.0, pct)))
                    if hasattr(self, "tl_keka_progress_pct_lbl"):
                        self.tl_keka_progress_pct_lbl.configure(text=f"{int(pct * 100)}%")
                    if hasattr(self, "tl_keka_progress_step_lbl"):
                        self.tl_keka_progress_step_lbl.configure(text=step)
                    if hasattr(self, "tl_keka_progress_detail_lbl") and detail:
                        self.tl_keka_progress_detail_lbl.configure(text=detail)
                except Exception:
                    pass
            self.after(0, _ui)

        def _worker():
            try:
                update_progress(0.05, "Connecting to Keka API...", "Validating OAuth credentials...")
                from keka_data_fetcher import KekaDataFetcher

                fetcher = KekaDataFetcher(
                    subdomain=subdomain,
                    api_key=api_key,
                    client_id=client_id,
                    client_secret=client_secret,
                    keka_email=keka_email,
                    keka_password=keka_password,
                )

                res = fetcher.fetch_unified_time_leave_reports(
                    from_date=from_iso,
                    to_date=to_iso,
                    output_file_path=out_path,
                    progress_callback=update_progress
                )

                update_progress(1.0, "Pull Completed Successfully! ⚡", f"Unified Master saved to {Path(out_path).name}")

                def _success():
                    self.btn_pull_keka_tl.configure(state="normal")
                    ui.update_status(self.tl_keka_dot, self.tl_keka_lbl, "Sync Successful", "success")

                    msg = (
                        f"✅ Unified Time and Leave Master report generated successfully!\n\n"
                        f"• Saved To: {out_path}\n"
                        f"• Total Attendance Records: {res.get('total_attendance_rows', 0):,}\n"
                        f"• Absent Mailer Records: {res.get('absent_mailer_rows', 0):,}\n"
                        f"• Total Employees: {res.get('total_employees', 0):,}\n\n"
                        f"Sheets included in Workbook:\n"
                        f"  1. Daily Performance (Reconciled with Applied By, Applied On, Approved By, Approved On)\n"
                        f"  2. Absent Mailer (Enriched with Last Working Day & Reporting Manager)\n"
                    )
                    messagebox.showinfo("Unified Report Ready", msg)

                self.after(0, _success)

            except Exception as e:
                def _fail(err_msg):
                    self.btn_pull_keka_tl.configure(state="normal")
                    ui.update_status(self.tl_keka_dot, self.tl_keka_lbl, "Sync failed", "error")
                    messagebox.showerror("Keka Sync Failed", str(err_msg))

                self.after(0, lambda: _fail(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

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
                employee_master_files=self.tl_emp_master_files,
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

        # Auto-sync with Workforce Intelligence
        self.last_time_leave_output_path = str(out_path)
        try:
            self.sync_workforce_from_time_leave(out_path, show_feedback=False)
        except Exception:
            pass

        msg = (
            f"Daily Performance Report updated successfully!\n\n"
            f"• Total Rows: {stats['total_rows']:,}\n"
            f"• Matched Leave records: {stats['matched_leave_count']:,}\n"
            f"• Matched WFH records: {stats['matched_wfh_count']:,}\n"
            f"• ⚡ Workforce Intelligence automatically synced!\n"
        )
        if stats.get('absent_mailer_rows', 0) > 0:
            msg += f"• Absent Mailer records generated: {stats['absent_mailer_rows']:,}\n"
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
