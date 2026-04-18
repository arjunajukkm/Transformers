import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import pandas as pd
    import customtkinter as ctk
    from openpyxl import load_workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
except ImportError:
    raise SystemExit("Missing dependency. Run: pip install customtkinter pandas openpyxl")


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "KRA Transformer Pro"
WINDOW_SIZE = "1180x760"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(980, 620)

        self.selected_input_file = ctk.StringVar(value="")
        self.is_processing = False

        self._setup_window()
        self._build_layout()
        self.select_frame_by_name("transform")

    def _setup_window(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

    def _build_layout(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=240, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(5, weight=1)

        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="KRA Tools",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
        )
        self.logo_label.grid(row=0, column=0, padx=24, pady=(28, 24))

        self.nav_transform = ctk.CTkButton(
            self.sidebar_frame,
            text="Transform KRA Files",
            height=44,
            corner_radius=10,
            border_spacing=10,
            anchor="w",
            fg_color="transparent",
            hover_color=("gray75", "gray25"),
            text_color=("gray10", "gray90"),
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self.select_frame_by_name("transform"),
        )
        self.nav_transform.grid(row=1, column=0, sticky="ew", padx=16, pady=(4, 8))

        self.nav_generate = ctk.CTkButton(
            self.sidebar_frame,
            text="Generate Upload Files",
            height=44,
            corner_radius=10,
            border_spacing=10,
            anchor="w",
            fg_color="transparent",
            hover_color=("gray75", "gray25"),
            text_color=("gray10", "gray90"),
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self.select_frame_by_name("generate"),
        )
        self.nav_generate.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))

        self.appearance_mode_menu = ctk.CTkOptionMenu(
            self.sidebar_frame,
            values=["Dark", "Light", "System"],
            command=self.change_appearance_mode_event,
            height=38,
        )
        self.appearance_mode_menu.set("Dark")
        self.appearance_mode_menu.grid(row=6, column=0, padx=20, pady=20, sticky="s")

        self.main_content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.main_content.grid(row=0, column=1, sticky="nsew", padx=24, pady=24)
        self.main_content.grid_rowconfigure(0, weight=1)
        self.main_content.grid_columnconfigure(0, weight=1)

        self._build_transform_frame()
        self._build_generate_frame()

    def _build_transform_frame(self):
        self.frame_transform = ctk.CTkFrame(self.main_content, fg_color="transparent", corner_radius=0)
        self.frame_transform.grid_columnconfigure(0, weight=1)

        self.transform_title = ctk.CTkLabel(
            self.frame_transform,
            text="Transform KRA Files",
            font=ctk.CTkFont(size=30, weight="bold"),
        )
        self.transform_title.grid(row=0, column=0, sticky="w", pady=(0, 18))

        self.transform_card = ctk.CTkFrame(self.frame_transform, corner_radius=18)
        self.transform_card.grid(row=1, column=0, sticky="nsew")
        self.transform_card.grid_columnconfigure(0, weight=1)

        self.file_row = ctk.CTkFrame(self.transform_card, fg_color="transparent")
        self.file_row.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 18))
        self.file_row.grid_columnconfigure(0, weight=1)

        self.file_entry = ctk.CTkEntry(
            self.file_row,
            textvariable=self.selected_input_file,
            placeholder_text="Select Excel file",
            height=48,
            font=ctk.CTkFont(size=14),
        )
        self.file_entry.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        self.btn_browse = ctk.CTkButton(
            self.file_row,
            text="Upload",
            width=130,
            height=48,
            corner_radius=12,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.select_input_file,
        )
        self.btn_browse.grid(row=0, column=1)

        self.progress = ctk.CTkProgressBar(
            self.transform_card,
            mode="indeterminate",
            height=10,
            corner_radius=999,
        )
        self.progress.grid(row=1, column=0, sticky="ew", padx=28, pady=(4, 16))
        self.progress.grid_remove()

        self.action_row = ctk.CTkFrame(self.transform_card, fg_color="transparent")
        self.action_row.grid(row=2, column=0, sticky="w", padx=28, pady=(0, 18))

        self.btn_transform = ctk.CTkButton(
            self.action_row,
            text="Transform",
            width=140,
            height=44,
            corner_radius=12,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.start_transform,
        )
        self.btn_transform.pack(side="left", padx=(0, 12))

        self.btn_cancel = ctk.CTkButton(
            self.action_row,
            text="Cancel",
            width=120,
            height=44,
            corner_radius=12,
            fg_color="transparent",
            border_width=1,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.cancel_transform,
        )
        self.btn_cancel.pack(side="left")

        self.status_frame = ctk.CTkFrame(self.transform_card, fg_color="transparent")
        self.status_frame.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 26))
        self.status_frame.grid_columnconfigure(1, weight=1)

        self.status_dot = ctk.CTkLabel(
            self.status_frame,
            text="●",
            text_color="#22c55e",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.status_dot.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="Ready",
            text_color="gray70",
            font=ctk.CTkFont(size=13),
        )
        self.status_label.grid(row=0, column=1, sticky="w")

    def _build_generate_frame(self):
        self.frame_generate = ctk.CTkFrame(self.main_content, fg_color="transparent", corner_radius=0)
        self.frame_generate.grid_columnconfigure(0, weight=1)

        self.generate_title = ctk.CTkLabel(
            self.frame_generate,
            text="Generate Upload Files",
            font=ctk.CTkFont(size=30, weight="bold"),
        )
        self.generate_title.grid(row=0, column=0, sticky="w", pady=(0, 18))

        self.generate_card = ctk.CTkFrame(self.frame_generate, corner_radius=18)
        self.generate_card.grid(row=1, column=0, sticky="nsew")

        self.generate_placeholder = ctk.CTkLabel(
            self.generate_card,
            text="Coming soon",
            text_color="gray70",
            font=ctk.CTkFont(size=15),
        )
        self.generate_placeholder.pack(anchor="w", padx=28, pady=28)

    def select_frame_by_name(self, name: str):
        self.nav_transform.configure(
            fg_color=("gray75", "gray25") if name == "transform" else "transparent"
        )
        self.nav_generate.configure(
            fg_color=("gray75", "gray25") if name == "generate" else "transparent"
        )

        if name == "transform":
            self.frame_generate.grid_forget()
            self.frame_transform.grid(row=0, column=0, sticky="nsew")
        else:
            self.frame_transform.grid_forget()
            self.frame_generate.grid(row=0, column=0, sticky="nsew")

    def change_appearance_mode_event(self, new_mode: str):
        ctk.set_appearance_mode(new_mode)

    def set_status(self, text: str, color: str = "gray70"):
        self.status_label.configure(text=text, text_color=color)

        dot_color = "#22c55e"
        if color == "#2563eb":
            dot_color = "#2563eb"
        elif color == "#ef4444":
            dot_color = "#ef4444"
        elif color == "#f59e0b":
            dot_color = "#f59e0b"

        self.status_dot.configure(text_color=dot_color)
        self.update_idletasks()

    def select_input_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Excel File",
            filetypes=[("Excel files", "*.xlsx *.xls")],
        )
        if file_path:
            self.selected_input_file.set(file_path)
            self.set_status("File selected", "gray70")

    def cancel_transform(self):
        if self.is_processing:
            messagebox.showwarning("In Progress", "Please wait until the current transformation finishes.")
            return

        self.selected_input_file.set("")
        self.set_status("Cancelled", "#f59e0b")

    def start_transform(self):
        if self.is_processing:
            return

        if not self.selected_input_file.get().strip():
            messagebox.showerror("Missing File", "Please select an Excel file first.")
            self.set_status("No file selected", "#ef4444")
            return

        self.is_processing = True
        self.btn_transform.configure(state="disabled")
        self.btn_browse.configure(state="disabled")
        self.progress.grid()
        self.progress.start()
        self.set_status("Transforming...", "#2563eb")

        thread = threading.Thread(target=self._run_transform_job, daemon=True)
        thread.start()

    def _run_transform_job(self):
        try:
            input_path = Path(self.selected_input_file.get())
            output_path = self._build_output_path(input_path)

            transformed_sheets = {}

            with pd.ExcelFile(input_path) as excel_file:
                for sheet_name in excel_file.sheet_names:
                    df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)

                    transformed_df = self.transform_kra_dataframe(df)
                    if transformed_df is not None and not transformed_df.empty:
                        transformed_sheets[sheet_name] = transformed_df

            if not transformed_sheets:
                raise ValueError("No valid non-empty sheets found to transform.")

            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                for sheet_name, transformed_df in transformed_sheets.items():
                    safe_name = str(sheet_name)[:31] if sheet_name else "Sheet1"
                    export_df = transformed_df[["KRA", "KPI", "Weightage", "KPI %", "KRA %"]]
                    export_df.to_excel(writer, sheet_name=safe_name, index=False)

            self.apply_excel_formatting(output_path)
            self.after(0, lambda: self._transform_success(output_path, len(transformed_sheets)))

        except Exception as exc:
            error_text = f"{exc}\n\n{traceback.format_exc()}"
            self.after(0, lambda: self._transform_error(error_text))

    def _build_output_path(self, input_path: Path) -> Path:
        downloads = Path.home() / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return downloads / f"{input_path.stem}_Transformed_{timestamp}.xlsx"

    def _transform_success(self, output_path: Path, sheet_count: int):
        self._reset_ui_state()
        self.set_status(f"Success • {sheet_count} sheet(s) transformed", "#22c55e")
        messagebox.showinfo(
            "Done",
            f"File transformed successfully.\n\nSaved to:\n{output_path}"
        )

    def _transform_error(self, error_text: str):
        self._reset_ui_state()
        self.set_status("Transformation failed", "#ef4444")
        messagebox.showerror("Error", error_text)

    def _reset_ui_state(self):
        self.is_processing = False
        self.progress.stop()
        self.progress.grid_remove()
        self.btn_transform.configure(state="normal")
        self.btn_browse.configure(state="normal")

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
        header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        white_fill = PatternFill(fill_type="solid", start_color="FFFFFF", end_color="FFFFFF")
        blue_fill = PatternFill(fill_type="solid", start_color="DCE6F1", end_color="DCE6F1")
        yellow_fill = PatternFill(fill_type="solid", start_color="FFF2CC", end_color="FFF2CC")

        left_alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        center_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        thin_side = Side(style="thin", color="BFBFBF")
        thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

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