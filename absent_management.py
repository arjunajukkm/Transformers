import pandas as pd
from pathlib import Path
from datetime import datetime

def process_absent_management(emp_master_path, attendance_path, od_wfh_path, output_path):
    # Read files
    df_emp = pd.read_excel(emp_master_path)
    df_att = pd.read_excel(attendance_path)
    df_wfh = pd.read_excel(od_wfh_path)

    # Normalize Employee Numbers to avoid float/string matching issues
    def clean_emp_num(df):
        if 'Employee Number' in df.columns:
            df['Employee Number'] = df['Employee Number'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            
    clean_emp_num(df_emp)
    clean_emp_num(df_att)
    clean_emp_num(df_wfh)

    # 1. Working Sheet Generation
    # Remove columns
    cols_to_remove = [
        "Sub Department", "Cost Center", "Shift", "Shift Start", "In Time", 
        "Late By", "Shift End", "Out Time", "Early By", "Effective Hours", 
        "Total Hours", "Break Duration", "Over Time", "Total Short Hours(Effective)", 
        "Total Short Hours(Gross)"
    ]
    df_working = df_att.drop(columns=[c for c in cols_to_remove if c in df_att.columns])

    # Convert dates for comparison
    if 'Date' not in df_working.columns:
        df_working['Date'] = ""
    df_working['Date_parsed'] = pd.to_datetime(df_working['Date'], dayfirst=True, errors='coerce')
    
    if 'From Date' not in df_wfh.columns:
        df_wfh['From Date'] = ""
    if 'To Date' not in df_wfh.columns:
        df_wfh['To Date'] = ""
    if 'Request Status' not in df_wfh.columns:
        df_wfh['Request Status'] = ""
        
    df_wfh['From Date_parsed'] = pd.to_datetime(df_wfh['From Date'], dayfirst=True, errors='coerce')
    df_wfh['To Date_parsed'] = pd.to_datetime(df_wfh['To Date'], dayfirst=True, errors='coerce')
    
    # 2. Add WFH Applied
    df_wfh_pending = df_wfh[df_wfh['Request Status'].astype(str).str.strip().str.lower() == 'pending']
    
    def check_wfh(row):
        emp_num = row.get('Employee Number')
        att_date = row.get('Date_parsed')
        if pd.isna(att_date) or pd.isna(emp_num):
            return "No"
            
        # Get pending wfh for this employee
        emp_wfh = df_wfh_pending[df_wfh_pending['Employee Number'] == emp_num]
        for _, w_row in emp_wfh.iterrows():
            if pd.notna(w_row['From Date_parsed']) and pd.notna(w_row['To Date_parsed']):
                if w_row['From Date_parsed'] <= att_date <= w_row['To Date_parsed']:
                    return "Yes"
        return "No"

    df_working['WFH Applied'] = df_working.apply(check_wfh, axis=1)

    # 3. Add Attendance Availability
    if 'Status' not in df_working.columns:
        df_working['Status'] = ""
        
    def check_availability(row):
        if row.get('WFH Applied') == "Yes":
            return "Yes"
            
        status = row.get('Status')
        if pd.isna(status):
            return "Yes"
        s = str(status).strip()
        if s == "A" or ":A" in s or "A:" in s:
            return "No"
        return "Yes"
        
    df_working['Attendance Availability'] = df_working.apply(check_availability, axis=1)

    # 4. Add Quantity
    def get_quantity(row):
        if row.get('WFH Applied') == "Yes":
            return 0.0
            
        if row['Attendance Availability'] == "No":
            s = str(row['Status']).strip()
            if s == "A":
                return 1.0
            elif ":" in s:
                return 0.5
        return 0.0

    df_working['Quantity'] = df_working.apply(get_quantity, axis=1)

    # Clean up temp date column
    df_working = df_working.drop(columns=['Date_parsed'])

    # B. Sheet: 'Mailer' Generation
    df_mailer = df_working.copy()

    # Map from Emp Master using Employee Number
    if 'Employee Number' not in df_emp.columns:
        df_emp['Employee Number'] = ""
        
    df_emp_unique = df_emp.drop_duplicates(subset=['Employee Number'])
    
    email_map = dict(zip(df_emp_unique['Employee Number'], df_emp_unique.get('Work Email', [])))
    rm_map = dict(zip(df_emp_unique['Employee Number'], df_emp_unique.get('Reporting Manager', [])))
    rm_email_map = dict(zip(df_emp_unique['Employee Number'], df_emp_unique.get('Reporting Manager Email', [])))
    lwd_map = dict(zip(df_emp_unique['Employee Number'], df_emp_unique.get('Last Working Day', [])))
    location_map = dict(zip(df_emp_unique['Employee Number'], df_emp_unique.get('Location', [])))

    df_mailer['Employee Mail ID'] = df_mailer.get('Employee Number', pd.Series()).map(email_map)
    df_mailer['Reporting Manager'] = df_mailer.get('Employee Number', pd.Series()).map(rm_map)
    df_mailer['RM Mail ID'] = df_mailer.get('Employee Number', pd.Series()).map(rm_email_map)
    df_mailer['LWD'] = df_mailer.get('Employee Number', pd.Series()).map(lwd_map)
    df_mailer['Location'] = df_mailer.get('Employee Number', pd.Series()).map(location_map)

    # Month Column
    def get_first_day_of_month(date_val):
        try:
            if pd.isna(date_val):
                return ""
            d = pd.to_datetime(date_val, dayfirst=True)
            first_day = d.replace(day=1)
            return first_day.strftime("%d-%m-%Y")
        except:
            return ""

    df_mailer['Month'] = df_mailer['Date'].apply(get_first_day_of_month)

    # Keep only required columns in Mailer
    mailer_cols = [
        "Employee Number", "Employee Name", "Date", "Status", "Quantity", 
        "Employee Mail ID", "Reporting Manager", "RM Mail ID", "Location", 
        "Month", "LWD"
    ]
    # Ensure they exist
    for col in mailer_cols:
        if col not in df_mailer.columns:
            df_mailer[col] = ""
            
    df_mailer = df_mailer[mailer_cols]

    # Write output
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_working.to_excel(writer, sheet_name="Working", index=False)
        df_mailer.to_excel(writer, sheet_name="Mailer", index=False)
        
        from openpyxl.styles import Font, Border
        font_header = Font(name='Calibri', size=11, bold=True)
        font_body = Font(name='Calibri', size=10)
        no_border = Border()
        
        for sheetname in writer.sheets:
            ws = writer.sheets[sheetname]
            for row in ws.iter_rows():
                for cell in row:
                    cell.border = no_border
                    if cell.row == 1:
                        cell.font = font_header
                    else:
                        cell.font = font_body
