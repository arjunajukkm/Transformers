import re
from datetime import datetime, date
from pathlib import Path
import pandas as pd


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

    # Helper: date formatter to DD-MMM-YY
    def format_date_dd_mmm_yy(val):
        if pd.isna(val) or val is None:
            return ""
        if isinstance(val, (datetime, date, pd.Timestamp)):
            return val.strftime("%d-%b-%y")
        s = str(val).strip()
        if not s or s.lower() in ("nan", "nat", "none", "na", "-", "#n/a"):
            return ""
        if re.match(r'^\d{2}-[A-Za-z]{3}-\d{2}$', s):
            return s
        try:
            if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', s):
                dt = pd.to_datetime(s, errors='coerce')
            else:
                dt = pd.to_datetime(s, dayfirst=True, errors='coerce')
            if pd.notna(dt):
                return dt.strftime("%d-%b-%y")
        except Exception:
            pass
        return s

    def get_first_day_of_month(date_val):
        try:
            if pd.isna(date_val) or date_val is None:
                return ""
            if isinstance(date_val, (datetime, date, pd.Timestamp)):
                return date_val.replace(day=1).strftime("%d-%b-%y")
            s = str(date_val).strip()
            if not s or s.lower() in ("nan", "nat", "none", "na", "-", "#n/a"):
                return ""
            if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', s):
                d = pd.to_datetime(s, errors='coerce')
            else:
                d = pd.to_datetime(s, dayfirst=True, errors='coerce')
            if pd.notna(d):
                first_day = d.replace(day=1)
                return first_day.strftime("%d-%b-%y")
            return ""
        except Exception:
            return ""

    # Robust column alias matching for Employee Master
    def find_emp_col(df, candidates):
        col_lookup = {str(c).strip().lower(): c for c in df.columns}
        for cand in candidates:
            if cand in col_lookup:
                return col_lookup[cand]
        for c in df.columns:
            clean = re.sub(r'[^a-z0-9]', '', str(c).lower())
            for cand in candidates:
                if clean == re.sub(r'[^a-z0-9]', '', cand):
                    return c
        return None

    emp_id_col = find_emp_col(df_emp, ["employee number", "employee id", "emp no", "emp id", "employee code", "emp code", "empid", "empno"]) or "Employee Number"
    email_col = find_emp_col(df_emp, ["work email", "email", "official email", "email id", "mail id", "employee mail id"])
    rm_col = find_emp_col(df_emp, ["reporting manager", "manager", "reporting manager name", "manager name", "rm"])
    rm_email_col = find_emp_col(df_emp, ["reporting manager email", "manager email", "rm email", "rm mail id", "reporting manager mail id"])
    lwd_col = find_emp_col(df_emp, ["last working day", "lwd", "last working date", "last day", "exit date", "relieving date", "resignation date", "lastworkingday"])
    loc_col = find_emp_col(df_emp, ["location", "work location", "branch", "city"])

    if emp_id_col in df_emp.columns:
        df_emp_unique = df_emp.drop_duplicates(subset=[emp_id_col])
    else:
        df_emp_unique = df_emp

    email_map = dict(zip(df_emp_unique[emp_id_col], df_emp_unique[email_col])) if email_col else {}
    rm_map = dict(zip(df_emp_unique[emp_id_col], df_emp_unique[rm_col])) if rm_col else {}
    rm_email_map = dict(zip(df_emp_unique[emp_id_col], df_emp_unique[rm_email_col])) if rm_email_col else {}
    lwd_map = dict(zip(df_emp_unique[emp_id_col], df_emp_unique[lwd_col])) if lwd_col else {}
    location_map = dict(zip(df_emp_unique[emp_id_col], df_emp_unique[loc_col])) if loc_col else {}

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

    # Filter out attendance records where Date > Last Working Day (LWD)
    def is_after_lwd(row):
        emp_num = row.get('Employee Number')
        att_d = row.get('Date_parsed')
        if pd.isna(att_d) or pd.isna(emp_num):
            return False
        lwd_val = row.get('Last Working Day') or row.get('LWD') or lwd_map.get(emp_num)
        if pd.isna(lwd_val) or not str(lwd_val).strip() or str(lwd_val).strip().lower() in ("nan", "nat", "none", "na", "-", "#n/a"):
            return False
        try:
            lwd_str = str(lwd_val).strip()
            if len(lwd_str) >= 10 and lwd_str[4] == '-' and lwd_str[7] == '-':
                lwd_parsed = pd.to_datetime(lwd_str[:10], format='%Y-%m-%d', errors='coerce')
            else:
                lwd_parsed = pd.to_datetime(lwd_val, dayfirst=True, errors='coerce')
            if pd.notna(lwd_parsed) and att_d.date() > lwd_parsed.date():
                return True
        except Exception:
            pass
        return False

    valid_lwd_mask = ~df_working.apply(is_after_lwd, axis=1)
    df_working = df_working[valid_lwd_mask].copy()

    # Parse WFH dates & filter cancelled/rejected
    if 'From Date' not in df_wfh.columns:
        df_wfh['From Date'] = ""
    if 'To Date' not in df_wfh.columns:
        df_wfh['To Date'] = ""
    if 'Request Status' not in df_wfh.columns:
        df_wfh['Request Status'] = ""
        
    df_wfh['From Date_parsed'] = pd.to_datetime(df_wfh['From Date'], dayfirst=True, errors='coerce')
    df_wfh['To Date_parsed'] = pd.to_datetime(df_wfh['To Date'], dayfirst=True, errors='coerce')
    
    # Filter out any cancelled, rejected, revoked, or withdrawn applications
    if 'Request Status' in df_wfh.columns:
        invalid_mask = df_wfh['Request Status'].astype(str).str.strip().str.lower().apply(
            lambda s: any(k in s for k in ['cancel', 'reject', 'revok', 'withdraw']) or s in ['2', '3', '4', '5']
        )
        df_wfh = df_wfh[~invalid_mask].copy()

    df_wfh_pending = df_wfh[df_wfh['Request Status'].astype(str).str.strip().str.lower().isin(['pending', 'approved'])]

    # Function to check WFH request for an employee on a date
    def find_wfh_info(emp_num, att_date):
        if pd.isna(att_date) or pd.isna(emp_num):
            return None
        emp_wfh = df_wfh_pending[df_wfh_pending['Employee Number'] == emp_num]
        for _, w_row in emp_wfh.iterrows():
            if pd.notna(w_row['From Date_parsed']) and pd.notna(w_row['To Date_parsed']):
                if w_row['From Date_parsed'] <= att_date <= w_row['To Date_parsed']:
                    dur = float(w_row.get('Duration', 1.0) or 1.0)
                    sess = str(w_row.get('Session', '')).lower()
                    type_str = str(w_row.get('Request Type', '')).lower()
                    is_half = (dur <= 0.5) or ('half' in sess) or ('half' in type_str)
                    return {"is_half": is_half}
        return None

    # Process all rows, splitting composite half-day entries (e.g., 'CL/SL:A') or half-day WFH into two line items
    expanded_working_rows = []
    for _, row in df_working.iterrows():
        emp_num = row.get('Employee Number')
        att_date = row.get('Date_parsed')
        status = str(row.get('Status') or '').strip()
        orig_qty = row.get('Quantity')
        try:
            parsed_orig_qty = float(orig_qty) if pd.notna(orig_qty) else 1.0
        except (ValueError, TypeError):
            parsed_orig_qty = 1.0

        # Case 1: Composite colon status (e.g. 'CL/SL:A', 'A:CL/SL', 'WFH:A', 'P:A')
        if ":" in status:
            parts = [p.strip() for p in status.split(":", 1)]
            p1, p2 = parts[0], parts[1]

            # Line item 1
            r1 = row.to_dict()
            r1['Status'] = p1
            r1['Quantity'] = 0.5
            if p1 == "A":
                r1['WFH Applied'] = "No"
                r1['Attendance Availability'] = "No"
            elif p1 == "WFH":
                r1['WFH Applied'] = "Yes"
                r1['Attendance Availability'] = "Yes"
            else:
                r1['WFH Applied'] = "No"
                r1['Attendance Availability'] = "Yes"

            # Line item 2
            r2 = row.to_dict()
            r2['Status'] = p2
            r2['Quantity'] = 0.5
            if p2 == "A":
                r2['WFH Applied'] = "No"
                r2['Attendance Availability'] = "No"
            elif p2 == "WFH":
                r2['WFH Applied'] = "Yes"
                r2['Attendance Availability'] = "Yes"
            else:
                r2['WFH Applied'] = "No"
                r2['Attendance Availability'] = "Yes"

            expanded_working_rows.extend([r1, r2])

        else:
            # Case 2: Single status
            wfh_info = find_wfh_info(emp_num, att_date)
            if wfh_info:
                if wfh_info["is_half"]:
                    # Split into two line items of 0.5 each
                    # 1. WFH line item
                    r1 = row.to_dict()
                    r1['Status'] = "WFH"
                    r1['Quantity'] = 0.5
                    r1['WFH Applied'] = "Yes"
                    r1['Attendance Availability'] = "Yes"

                    # 2. Other half line item
                    r2 = row.to_dict()
                    if status == "A":
                        r2['Status'] = "A"
                        r2['Quantity'] = 0.5
                        r2['WFH Applied'] = "No"
                        r2['Attendance Availability'] = "No"
                    else:
                        r2['Status'] = status if status not in ("", "nan") else "P"
                        r2['Quantity'] = 0.5
                        r2['WFH Applied'] = "No"
                        r2['Attendance Availability'] = "Yes"

                    expanded_working_rows.extend([r1, r2])
                else:
                    # Full day WFH
                    r = row.to_dict()
                    r['Status'] = "WFH" if status in ("A", "") else status
                    r['Quantity'] = 1.0  # All days tagged against 0.5 or 1, no quantity 0!
                    r['WFH Applied'] = "Yes"
                    r['Attendance Availability'] = "Yes"
                    expanded_working_rows.append(r)
            else:
                r = row.to_dict()
                r['WFH Applied'] = "No"
                if status == "A":
                    r['Attendance Availability'] = "No"
                else:
                    r['Attendance Availability'] = "Yes"

                # Quantity: 0.5 if half day (or if originally tagged as 0.5), else 1.0 (never 0.0)
                if 0 < parsed_orig_qty <= 0.5 or "half" in status.lower():
                    r['Quantity'] = 0.5
                else:
                    r['Quantity'] = 1.0

                expanded_working_rows.append(r)

    if expanded_working_rows:
        df_working = pd.DataFrame(expanded_working_rows)
    else:
        df_working = pd.DataFrame(columns=list(df_working.columns) + ['WFH Applied', 'Attendance Availability', 'Quantity'])

    # Clean up temp date column
    if 'Date_parsed' in df_working.columns:
        df_working = df_working.drop(columns=['Date_parsed'])

    # Map Last Working Day & format dates in Working sheet (deduplicate LWD vs Last Working Day)
    lwd_series = df_working['Employee Number'].map(lwd_map).apply(format_date_dd_mmm_yy) if (lwd_map and 'Employee Number' in df_working.columns) else pd.Series([""] * len(df_working))
    if 'Last Working Day' in df_working.columns:
        df_working['Last Working Day'] = df_working['Last Working Day'].replace("", pd.NA).fillna(lwd_series).apply(format_date_dd_mmm_yy).fillna("")
        if 'LWD' in df_working.columns:
            df_working = df_working.drop(columns=['LWD'])
    elif 'LWD' in df_working.columns:
        df_working['Last Working Day'] = df_working['LWD'].replace("", pd.NA).fillna(lwd_series).apply(format_date_dd_mmm_yy).fillna("")
        df_working = df_working.drop(columns=['LWD'])
    else:
        df_working['Last Working Day'] = lwd_series

    if 'Date' in df_working.columns:
        df_working['Date'] = df_working['Date'].apply(format_date_dd_mmm_yy)

    # B. Sheet: 'Mailer' Generation
    df_mailer = df_working.copy()

    if not df_mailer.empty and 'Employee Number' in df_mailer.columns:
        df_mailer['Employee Mail ID'] = df_mailer['Employee Number'].map(email_map).fillna("")
        df_mailer['Reporting Manager'] = df_mailer['Employee Number'].map(rm_map).fillna("")
        df_mailer['RM Mail ID'] = df_mailer['Employee Number'].map(rm_email_map).fillna("")
        df_mailer['Location'] = df_mailer['Employee Number'].map(location_map).fillna("")
        df_mailer['Last Working Day'] = df_mailer['Employee Number'].map(lwd_map).apply(format_date_dd_mmm_yy) if lwd_map else ""
    else:
        df_mailer['Employee Mail ID'] = ""
        df_mailer['Reporting Manager'] = ""
        df_mailer['RM Mail ID'] = ""
        df_mailer['Location'] = ""
        df_mailer['Last Working Day'] = ""

    if 'Date' in df_mailer.columns:
        df_mailer['Month'] = df_mailer['Date'].apply(get_first_day_of_month)
        df_mailer['Date'] = df_mailer['Date'].apply(format_date_dd_mmm_yy)
    else:
        df_mailer['Month'] = ""

    # Keep only required columns in Mailer (standardizing on 'Last Working Day')
    mailer_cols = [
        "Employee Number", "Employee Name", "Date", "Status", "Quantity", 
        "Employee Mail ID", "Reporting Manager", "RM Mail ID", "Location", 
        "Month", "Last Working Day"
    ]
    for col in mailer_cols:
        if col not in df_mailer.columns:
            df_mailer[col] = ""
            
    df_mailer = df_mailer[mailer_cols]

    # Write output with styled Excel: Calibri 11 bold header with #00FF99 fill and no borders
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_working.to_excel(writer, sheet_name="Working", index=False)
        df_mailer.to_excel(writer, sheet_name="Mailer", index=False)
        
        from openpyxl.styles import Font, PatternFill, Border
        font_header = Font(name='Calibri', size=11, bold=True)
        font_body = Font(name='Calibri', size=10)
        fill_header = PatternFill(start_color="00FF99", end_color="00FF99", fill_type="solid")
        no_border = Border()
        
        for sheetname in writer.sheets:
            ws = writer.sheets[sheetname]
            for row in ws.iter_rows():
                for cell in row:
                    cell.border = no_border
                    if cell.row == 1:
                        cell.font = font_header
                        cell.fill = fill_header
                    else:
                        cell.font = font_body
