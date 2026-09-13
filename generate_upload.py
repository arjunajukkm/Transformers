import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

def generate_upload_file(input_file, output_file, employees):
    wb = Workbook()
    ws = wb.active
    ws.title = "Objective Key Results"
    
    headers = [
        "Employee Number", "Employee Name", "Objective Title", "Objective Description", 
        "Time Frame", "Objective Type", "Objective Metric Type", "Objective Metric Name", 
        "Target Direction", "Objective Initial Value", "Objective Target Value", 
        "Objective Start Date", "Objective End Date", "Tags", "Include In Review", 
        "Visibility", "Progress Calculation Type", "Objective Weightage", 
        "KeyResult Employee Number", "KeyResult Employee Name", "Key Result Title", 
        "Key Result Description", "Key Result Metric Type", "Key Result Metric Name", 
        "Key Result Target Direction", "Key Result Initial Value", "Key Result Target Value", 
        "Key Result Start Date", "Key Result End Date", "Key Result Tags", "Key Result Weightage"
    ]
    
    ws.merge_cells('A1:AE1')
    title_cell = ws.cell(row=1, column=1, value="Objective Key Results")
    title_cell.font = Font(bold=True, size=13)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 25
    
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(name="Calibri", color="FFFFFF", bold=True, size=11)
    header_alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
    
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment
    ws.row_dimensions[2].height = 35
    
    xl = pd.ExcelFile(input_file)
    all_rows = []
    
    for sheet_name, employee_list in employees.items():
        actual_sheet_name = None
        for name in xl.sheet_names:
            if name.strip() == sheet_name.strip():
                actual_sheet_name = name
                break
                
        if not actual_sheet_name:
            continue
            
        df = pd.read_excel(xl, sheet_name=actual_sheet_name, header=0)
        extracted_data = []
        
        if df.shape[1] == 4:
            df.iloc[:, 0] = df.iloc[:, 0].ffill()
            df.iloc[:, 2] = df.iloc[:, 2].ffill()
            
            for kra, group in df.groupby(df.columns[0], sort=False):
                kra_weight = group.iloc[0, 2]
                kra_pct = kra_weight if pd.notna(kra_weight) else None
                
                weights = pd.to_numeric(group.iloc[:, 3], errors='coerce').fillna(0)
                total_w = weights.sum()
                
                for idx, row in group.iterrows():
                    kpi = row.iloc[1]
                    w = weights.loc[idx]
                    
                    if total_w > 0:
                        kpi_pct = round((w / total_w) * 100, 2)
                    else:
                        kpi_pct = 0.0
                        
                    kpi_pct_val = kpi_pct if pd.notna(kpi_pct) else None
                    extracted_data.append((kra, kpi, kpi_pct_val, kra_pct))
                    
        elif df.shape[1] >= 5:
            for _, row in df.iterrows():
                kra = row.iloc[0]
                kpi = row.iloc[1]
                kpi_pct = row.iloc[3]
                kra_pct = row.iloc[4]
                
                if pd.notna(kra) and pd.notna(kpi):
                    kpi_pct_val = kpi_pct if pd.notna(kpi_pct) else None
                    kra_pct_val = kra_pct if pd.notna(kra_pct) else None
                    extracted_data.append((kra, kpi, kpi_pct_val, kra_pct_val))
        
        for emp_num, emp_name in employee_list:
            for kra, kpi, kpi_pct, kra_pct in extracted_data:
                row_data = [
                    emp_num, emp_name, kra, None, "2025 - 26", "Individual", 
                    "Percentage", None, "Increase From", 0, 100, None, None, 
                    None, "Yes", "Managers", "Average of child KPI", kra_pct, 
                    emp_num, emp_name, kpi, None, "Percentage", None, 
                    "Increase From", 0, 100, None, None, None, kpi_pct
                ]
                all_rows.append((emp_num, row_data))
                
    data_alignment = Alignment(vertical="center", wrap_text=True)
    blue_fill = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    row_font = Font(name="Calibri", size=10)
    
    current_emp = None
    use_blue = False
    
    current_row = 3
    for emp_num, row_data in all_rows:
        if emp_num != current_emp:
            current_emp = emp_num
            use_blue = not use_blue
            
        current_fill = blue_fill if use_blue else white_fill
        
        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.alignment = data_alignment
            cell.fill = current_fill
            cell.font = row_font
            
        ws.row_dimensions[current_row].height = 30
        current_row += 1
        
    ws.freeze_panes = "A3"
    
    col_widths = {
        1: 15, 2: 25, 3: 70, 4: 12, 5: 12, 6: 12, 7: 18, 8: 12, 9: 12, 10: 12, 
        11: 12, 12: 12, 13: 12, 14: 12, 15: 12, 16: 12, 17: 12, 18: 18, 19: 15, 
        20: 25, 21: 70, 22: 12, 23: 18, 24: 12, 25: 12, 26: 12, 27: 12, 28: 12, 
        29: 12, 30: 12, 31: 18
    }
    
    for col_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width
        
    wb.save(output_file)


if __name__ == "__main__":
    input_file = "YOUR_INPUT_FILE.xlsx"
    output_file = "YOUR_OUTPUT_FILE.xlsx"

    employees = {
        "Sheet Name Exactly As In Excel": [
            ("EMP001", "Employee Full Name"),
            ("EMP002", "Another Employee"),
        ],
        "Another Sheet Name": [
            ("EMP003", "Third Employee"),
        ],
    }

    generate_upload_file(input_file, output_file, employees)
