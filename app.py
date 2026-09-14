import threading
import traceback
import sys
import os
import ctypes
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import pandas as pd
import customtkinter as ctk
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side



import ui_components as ui

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
        self.absent_emp_file = ctk.StringVar()
        self.absent_att_file = ctk.StringVar()
        self.absent_wfh_file = ctk.StringVar()
        self.att_summary_file = ctk.StringVar()
        self.analyse_upload_file = ctk.StringVar()
        
        # State flags
        self.is_processing = False
        self.is_generating = False
        self.is_analysing = False
        
        # Navigation state
        self.transform_menu_expanded = True
        self.analyse_menu_expanded = True
        self.menu_expanded = True
        self.nav_parent_btn = None
        self.nav_chevron = None
        self.analyse_parent_btn = None
        self.analyse_chevron = None
        self.sub_nav_btns = {}

        self._setup_window()
        self._build_layout()
        self.select_frame_by_name("dashboard")

    def _setup_window(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.configure(fg_color=ui.COLOR_BG)

    def _build_layout(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=ui.COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(10, weight=1)

        # Logo
        lbl_logo = ctk.CTkLabel(
            self.sidebar, text="Transformers",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=26, weight="bold"),
            text_color=ui.COLOR_ACCENT
        )
        lbl_logo.grid(row=0, column=0, padx=24, pady=(32, 32), sticky="w")
        
        sep = ctk.CTkFrame(self.sidebar, height=1, fg_color=ui.COLOR_SIDEBAR_SEP)
        sep.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))

        # ── Collapsible Transform Navigation Group ──────────────
        self.nav_parent_frame, self.nav_parent_btn, self.nav_chevron = ui.create_collapsible_nav_item(
            self.sidebar,
            text="Transform",
            icon=ui.ICON_HOME,
            on_select=lambda: self._on_transform_parent_clicked(),
            on_toggle=lambda: self.toggle_transform_menu(),
            row=2,
        )

        # Sub-menu container for child modules
        self.sub_menu_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sub_menu_frame.grid(row=3, column=0, sticky="ew")
        self.sub_menu_frame.grid_columnconfigure(0, weight=1)

        # Sub-items: KRA Management, Absent Management, Attendance Summary
        transform_sub_items = [
            ("transform", "KRA Management", ui.ICON_KRA),
            ("absent", "Absent Management", ui.ICON_ABSENT),
            ("att_summary", "Attendance Summary", ui.ICON_ATTENDANCE),
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

        # ── Collapsible Analyse Navigation Group ──────────────
        self.analyse_parent_frame, self.analyse_parent_btn, self.analyse_chevron = ui.create_collapsible_nav_item(
            self.sidebar,
            text="Analyse",
            icon=ui.ICON_ANALYSE,
            on_select=lambda: self._on_analyse_parent_clicked(),
            on_toggle=lambda: self.toggle_analyse_menu(),
            row=4,
        )

        # Sub-menu container for Analyse child modules
        self.analyse_sub_menu_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.analyse_sub_menu_frame.grid(row=5, column=0, sticky="ew")
        self.analyse_sub_menu_frame.grid_columnconfigure(0, weight=1)

        # Sub-items: Dashboard, Upload
        analyse_sub_items = [
            ("analyse_dashboard", "Dashboard", ui.ICON_DASHBOARD),
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

        # Main Content
        self.main_content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.main_content.grid(row=0, column=1, sticky="nsew", padx=40, pady=40)
        self.main_content.grid_rowconfigure(0, weight=1)
        self.main_content.grid_columnconfigure(0, weight=1)

        # Build Frames
        self.frames = {}
        self._build_dashboard_frame()
        self._build_transform_frame()
        self._build_generate_frame()
        self._build_absent_frame()
        self._build_att_summary_frame()
        self._build_analyse_dashboard_frame()
        self._build_analyse_upload_frame()

    def _on_transform_parent_clicked(self):
        """When the Transform header is clicked, ensure menu is open and show overview."""
        if not self.transform_menu_expanded:
            self.toggle_transform_menu(force_state=True)
        self.select_frame_by_name("dashboard")

    def toggle_transform_menu(self, force_state=None):
        """Toggle the collapsible Transform sub-menu between expanded and collapsed states."""
        if force_state is not None:
            self.transform_menu_expanded = force_state
        else:
            self.transform_menu_expanded = not self.transform_menu_expanded
        self.menu_expanded = self.transform_menu_expanded

        if self.transform_menu_expanded:
            self.sub_menu_frame.grid(row=3, column=0, sticky="ew")
            self.nav_chevron.configure(text="▾")
        else:
            self.sub_menu_frame.grid_remove()
            self.nav_chevron.configure(text="▸")

    def _on_analyse_parent_clicked(self):
        """When the Analyse header is clicked, ensure menu is open and show Analyse Dashboard."""
        if not self.analyse_menu_expanded:
            self.toggle_analyse_menu(force_state=True)
        self.select_frame_by_name("analyse_dashboard")

    def toggle_analyse_menu(self, force_state=None):
        """Toggle the collapsible Analyse sub-menu between expanded and collapsed states."""
        if force_state is not None:
            self.analyse_menu_expanded = force_state
        else:
            self.analyse_menu_expanded = not self.analyse_menu_expanded

        if self.analyse_menu_expanded:
            self.analyse_sub_menu_frame.grid(row=5, column=0, sticky="ew")
            self.analyse_chevron.configure(text="▾")
        else:
            self.analyse_sub_menu_frame.grid_remove()
            self.analyse_chevron.configure(text="▸")

    def select_frame_by_name(self, name: str):
        is_transform_parent = (name == "dashboard")
        is_analyse_parent = False

        transform_children = ("dashboard", "transform", "generate", "absent", "att_summary")
        analyse_children = ("analyse_dashboard", "analyse_upload")

        # Auto-expand menu if navigating to a child module
        if name in transform_children and not self.transform_menu_expanded:
            self.toggle_transform_menu(force_state=True)
        elif name in analyse_children and not self.analyse_menu_expanded:
            self.toggle_analyse_menu(force_state=True)

        # Update Parent button highlight
        ui.set_nav_active(self.nav_parent_btn, is_transform_parent)
        ui.set_nav_active(self.analyse_parent_btn, is_analyse_parent)

        # Update Sub-nav buttons highlight
        for n, btn in self.sub_nav_btns.items():
            is_active = (n == name) or (name == "generate" and n == "transform")
            ui.set_sub_nav_active(btn, is_active)

        # Hide all frames
        for f in self.frames.values():
            f.grid_forget()

        # Show selected
        if name in self.frames:
            self.frames[name].grid(row=0, column=0, sticky="nsew")

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

        ctk.CTkLabel(card, text="Upload Transformed File", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"), text_color=ui.COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        ui.create_upload_row(card, self.selected_gen_input_file, "Select transformed Excel...", "Browse", 1)

        ctk.CTkLabel(card, text="Employee Mapping Format:\nEMP ID, Name, Designation (Sheet Name)", font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"), text_color=ui.COLOR_TEXT, justify="left").grid(row=2, column=0, sticky="w", padx=16, pady=(12, 8))
        self.gen_mapping_text = ctk.CTkTextbox(card, height=80, font=ctk.CTkFont(family="Consolas", size=12), fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER, border_width=1, text_color=ui.COLOR_TEXT)
        self.gen_mapping_text.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        self.gen_mapping_text.insert("0.0", 'EMP001, John Doe, Manager\nEMP002, Jane Smith, Manager')

        self.gen_prog = ctk.CTkProgressBar(card, mode="indeterminate", height=4, corner_radius=2, fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT)
        self.gen_prog.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.gen_prog.set(0)
        self.gen_prog.grid_remove()

        row5 = ctk.CTkFrame(card, fg_color="transparent")
        row5.grid(row=5, column=0, sticky="ew", padx=16, pady=(12, 16))
        
        _, self.gen_dot, self.gen_lbl = ui.create_status_badge(row5, "Ready")
        self.gen_lbl.master.pack(side="left")

        self.btn_gen = ui.create_primary_button(row5, "Generate File", self.start_generate)
        self.btn_gen.pack(side="right")

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
    # Analyse Dashboard
    # ---------------------------------------------------------
    def _build_analyse_dashboard_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["analyse_dashboard"] = f
        f.grid_columnconfigure((0, 1), weight=1)

        hdr = ui.create_page_header(f, "Analyse", "Quick access to analytics and dataset processing modules.")
        hdr.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 30))

        ui.create_dashboard_card(
            f, ui.ICON_UPLOAD, "Upload Dataset for Analysis",
            "Upload raw spreadsheets or logs to calculate distributions, null values, and summary metrics.",
            "Active", lambda: self.select_frame_by_name("analyse_upload"), 1, 0
        )

    # ---------------------------------------------------------
    # Analyse Upload
    # ---------------------------------------------------------
    def _build_analyse_upload_frame(self):
        f = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.frames["analyse_upload"] = f
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        hdr = ui.create_page_header(f, "Analyse Upload", "Upload Excel or CSV files to generate instant statistical reports and summaries.")
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        actions = ctk.CTkFrame(hdr, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        ui.create_secondary_button(actions, "← Back to Dashboard", lambda: self.select_frame_by_name("analyse_dashboard"), 160).pack()

        # Upload Card
        card = ui.create_card(f)
        card.grid(row=1, column=0, sticky="nsew", pady=(0, 12))

        ctk.CTkLabel(
            card, text="1. Select Dataset for Analysis",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 2))

        ctk.CTkLabel(
            card, text="Supported formats: Excel (.xlsx, .xls) and CSV (.csv).",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
            text_color=ui.COLOR_TEXT_SEC
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 8))

        ui.create_upload_row(card, self.analyse_upload_file, "Select file to analyse...", "Browse", 2)

        self.analyse_prog = ctk.CTkProgressBar(
            card, mode="indeterminate", height=4, corner_radius=2,
            fg_color=ui.COLOR_INPUT_BG, progress_color=ui.COLOR_ACCENT
        )
        self.analyse_prog.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.analyse_prog.set(0)
        self.analyse_prog.grid_remove()

        row4 = ctk.CTkFrame(card, fg_color="transparent")
        row4.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 12))

        _, self.analyse_dot, self.analyse_lbl = ui.create_status_badge(row4, "Ready")
        self.analyse_lbl.master.pack(side="left")

        self.btn_analyse = ui.create_primary_button(row4, "Run Analysis", self.start_analyse)
        self.btn_analyse.pack(side="right")

        # Results Card
        res_card = ui.create_card(f)
        res_card.grid(row=2, column=0, sticky="nsew")
        res_card.grid_columnconfigure(0, weight=1)
        res_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            res_card, text="Analysis Report & Preview",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
            text_color=ui.COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        self.analyse_result_text = ctk.CTkTextbox(
            res_card, height=140, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=ui.COLOR_INPUT_BG, border_color=ui.COLOR_BORDER,
            border_width=1, text_color=ui.COLOR_TEXT, corner_radius=6
        )
        self.analyse_result_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.analyse_result_text.insert("0.0", "Select a file and click 'Run Analysis' to view dataset summary, column statistics, and row metrics.")
        self.analyse_result_text.configure(state="disabled")


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
        if not self.selected_gen_input_file.get():
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
