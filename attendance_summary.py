import pandas as pd
from pathlib import Path
from datetime import datetime

def process_attendance_summary(input_path, output_path):
    df = pd.read_excel(input_path)

    # Dictionary mapping
    mapping = {
        "WO": "Week off", "WO(R)": "Week off", "WOW": "Week off",
        "WFH": "Work From Home",
        "CLSL": "Leave", "PL": "Leave", "UL": "Leave", "FL": "Leave", 
        "SPL": "Leave", "ML": "Leave", "PT": "Leave", "BL": "Leave", 
        "CL": "Leave", "HPL": "Leave", "WL": "Leave", "VL": "Leave", 
        "MCL": "Leave", "CML": "Leave", "ADL": "Leave", "ADLM": "Leave", 
        "ADM": "Leave", "GL": "Leave", "L": "Leave", "CO": "Leave",
        "P": "Present", "P(MS)": "Present",
        "H": "Holiday", "WOH": "Holiday",
        "OD": "On Duty",
        "A(R)": "Attendance Regularized",
        "A": "Absent"
    }

    # Ensure required columns exist
    for col in ['Status', 'Employee Number', 'Date', 'Employee Name', 'Job Title', 'Location', 'Reporting Manager']:
        if col not in df.columns:
            df[col] = ""

    # Duplication and Value splitting logic
    # Create a list to hold processed rows
    processed_rows = []
    
    # Iterate through to handle duplicates cleanly
    for idx, row in df.iterrows():
        status = str(row['Status']).strip()
        if ':' in status:
            parts = status.split(':')
            if len(parts) >= 2:
                left = parts[0].strip()
                right = parts[1].strip()
                
                # Left row
                row_left = row.copy()
                row_left['Attendance Category'] = mapping.get(left, "Unknown")
                row_left['Quantity'] = 0.5
                processed_rows.append(row_left)
                
                # Right row
                row_right = row.copy()
                row_right['Attendance Category'] = mapping.get(right, "Unknown")
                row_right['Quantity'] = 0.5
                processed_rows.append(row_right)
        else:
            row_single = row.copy()
            row_single['Attendance Category'] = mapping.get(status, "Unknown")
            row_single['Quantity'] = 1.0
            processed_rows.append(row_single)

    df_processed = pd.DataFrame(processed_rows)

    # Generate EMP Wise Summary
    # Extract unique employee info
    base_info = df_processed[['Employee Number', 'Employee Name', 'Job Title', 'Location', 'Reporting Manager']].drop_duplicates(subset=['Employee Number'])
    
    # Total Days (unique Dates)
    total_days = df_processed.groupby('Employee Number')['Date'].nunique().reset_index()
    total_days.rename(columns={'Date': 'Total Days'}, inplace=True)
    
    # Pivot categories for Quantity sum
    pivot = df_processed.pivot_table(
        index='Employee Number', 
        columns='Attendance Category', 
        values='Quantity', 
        aggfunc='sum', 
        fill_value=0
    ).reset_index()

    # Merge base info with aggregations
    summary = pd.merge(base_info, total_days, on='Employee Number', how='left')
    summary = pd.merge(summary, pivot, on='Employee Number', how='left')
    
    # Ensure all required categories exist in summary even if not present in data
    required_categories = [
        'Present', 'Attendance Regularized', 'Work From Home', 
        'On Duty', 'Leave', 'Holiday', 'Week off', 'Absent'
    ]
    for cat in required_categories:
        if cat not in summary.columns:
            summary[cat] = 0.0

    # Final column ordering
    final_cols = [
        'Employee Number', 'Employee Name', 'Job Title', 'Location', 'Reporting Manager',
        'Total Days', 'Present', 'Attendance Regularized', 'Work From Home',
        'On Duty', 'Leave', 'Holiday', 'Week off', 'Absent'
    ]
    
    # Filter to final cols in case extra unknowns were generated
    summary = summary[[col for col in final_cols if col in summary.columns]]

    # Write to Excel
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_processed.to_excel(writer, sheet_name="Processed Data", index=False)
        summary.to_excel(writer, sheet_name="EMP Wise Summary", index=False)

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
