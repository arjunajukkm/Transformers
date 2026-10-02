"""
tests/test_unified_time_leave.py
─────────────────────────────────
Comprehensive test suite validating the Unified Time & Leave Master Engine:
1. Applied By and Approved By role attribution (Admin vs Manager vs Employee)
2. Reporting Manager extraction and enrichment from Employee Master
3. Deduplication of 'LWD' and 'Last Working Day'
4. Multi-sheet workbook output (Daily Performance + Absent Mailer)
5. Custom Excel styling (Header #00FF99, Calibri font, no cell borders, dd-mmm-yy date formatting)
6. Keka API unified workbook generator
"""

from datetime import date, datetime
from pathlib import Path
import tempfile
import openpyxl
import pandas as pd
import pytest

from time_leave_master import (
    compute_applied_by,
    compute_approved_by,
    format_date_str,
    reconcile_time_and_leave,
)
from keka_data_fetcher import KekaDataFetcher
import absent_management


def test_applied_by_admin_vs_employee():
    """Admin users (Arjun S, E Janani Sri) applying for self -> Employee, applying for others -> Admin."""
    # Self-application by admin
    assert compute_applied_by("Arjun S", "Arjun S") == "Employee"
    assert compute_applied_by("E Janani Sri", "E Janani Sri") == "Employee"
    assert compute_applied_by("Janani Sri E", "Janani Sri E") == "Employee"

    # Admin applying on behalf of another employee
    assert compute_applied_by("Arjun S", "Rahul Sharma") == "Admin"
    assert compute_applied_by("E Janani Sri", "Priya Verma") == "Admin"
    assert compute_applied_by("arjun s", "Kavita Rao") == "Admin"

    # Regular employee applying for self
    assert compute_applied_by("Rahul Sharma", "Rahul Sharma") == "Employee"
    # Regular employee / manager applying for another -> Admin / Proxy
    assert compute_applied_by("Manager Bob", "Rahul Sharma") == "Admin"
    # Empty requester defaults to Employee
    assert compute_applied_by("", "Rahul Sharma") == "Employee"


def test_approved_by_manager_vs_admin():
    """
    Approved By logic:
    - If action taken by matches employee's Reporting Manager -> Manager
    - Else if action taken by is Admin (Arjun S or E Janani Sri) -> Admin
    - Else -> Manager (never Employee)
    """
    # When approver is Reporting Manager (even if approver happens to be Arjun S who is their actual RM)
    assert compute_approved_by("Arjun S", reporting_manager="Arjun S") == "Manager"
    assert compute_approved_by("arjun s", reporting_manager="Arjun S") == "Manager"

    # When approver is Admin and NOT their RM
    assert compute_approved_by("Arjun S", reporting_manager="Priya Nair") == "Admin"
    assert compute_approved_by("E Janani Sri", reporting_manager="Priya Nair") == "Admin"
    assert compute_approved_by("Janani Sri E", reporting_manager="Priya Nair") == "Admin"

    # When approver is their Reporting Manager (regular name)
    assert compute_approved_by("Priya Nair", reporting_manager="Priya Nair") == "Manager"

    # When approver is another supervisor/fallback (never Employee)
    assert compute_approved_by("Vikram Singh", reporting_manager="Priya Nair") == "Manager"
    assert compute_approved_by("", reporting_manager="Priya Nair") == "Manager"


def test_date_formatting_dd_mmm_yy():
    """Verify dd-mmm-yy date formatting across multiple input types."""
    assert format_date_str("2026-09-09") == "09-Sep-26"
    assert format_date_str("2026-01-15") == "15-Jan-26"
    assert format_date_str("15-01-2026") == "15-Jan-26"
    assert format_date_str("") == ""
    assert format_date_str(None) == ""


def test_unified_reconcile_with_employee_master_and_absent_mailer():
    """
    Test reconcile_time_and_leave when employee master is provided:
    1. Populates Reporting Manager and Last Working Day
    2. Removes duplicate LWD column
    3. Produces both 'Daily Performance' and 'Absent Mailer' sheets
    4. Applies correct Admin/Manager role labels
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Performance file with missing Reporting Manager & duplicate LWD
        perf_df = pd.DataFrame([
            {
                "Employee Number": "EMP101",
                "Employee Name": "Alice Green",
                "Date": "2026-09-01",
                "Attendance Type": "Leave",
                "Attendance Status": "A",
                "Quantity": 1.0,
                "Reporting Manager": "",
                "LWD": "2026-09-30",
                "Last Working Day": "2026-09-30",
                "Location": "",
            },
            {
                "Employee Number": "EMP102",
                "Employee Name": "Bob White",
                "Date": "2026-09-01",
                "Attendance Type": "Present",
                "Attendance Status": "P",
                "Quantity": 0.0,
                "Reporting Manager": "",
                "LWD": "",
                "Last Working Day": "",
                "Location": "",
            }
        ])
        perf_file = tmp_path / "perf.xlsx"
        perf_df.to_excel(perf_file, index=False)

        # 2. Leave file with Admin approver
        leave_df = pd.DataFrame([
            {
                "Employee Number": "EMP101",
                "Employee Name": "Alice Green",
                "From Date": "2026-09-01",
                "To Date": "2026-09-01",
                "Total Duration": 1.0,
                "Requester": "Arjun S",
                "Requested On": "2026-08-30",
                "Last Action Taken by": "Arjun S",
                "Action Taken On": "2026-08-31",
                "Leave Type": "Casual Leave",
                "Status": "Approved",
            }
        ])
        leave_file = tmp_path / "leaves.xlsx"
        leave_df.to_excel(leave_file, index=False)

        # 3. Employee Master file providing Reporting Manager & Last Working Day
        master_df = pd.DataFrame([
            {
                "Employee Number": "EMP101",
                "Employee Name": "Alice Green",
                "Work Email": "alice@company.com",
                "Reporting Manager": "Carlos Ray",
                "Reporting Manager Email": "carlos@company.com",
                "Location": "Bangalore",
                "Last Working Day": "2026-09-30",
            },
            {
                "Employee Number": "EMP102",
                "Employee Name": "Bob White",
                "Work Email": "bob@company.com",
                "Reporting Manager": "Carlos Ray",
                "Reporting Manager Email": "carlos@company.com",
                "Location": "Mumbai",
                "Last Working Day": "",
            }
        ])
        master_file = tmp_path / "master.xlsx"
        master_df.to_excel(master_file, index=False)

        out_file = tmp_path / "Unified_Report.xlsx"

        stats = reconcile_time_and_leave(
            perf_files=[str(perf_file)],
            leave_active_files=[str(leave_file)],
            employee_master_files=[str(master_file)],
            output_path=str(out_file)
        )

        assert stats["total_rows"] == 2
        assert stats["matched_leave_count"] == 1
        assert stats["absent_mailer_rows"] >= 1

        # Inspect generated workbook with openpyxl
        wb = openpyxl.load_workbook(out_file)
        assert "Daily Performance" in wb.sheetnames
        assert "Absent Mailer" in wb.sheetnames

        # 1. Verify Daily Performance sheet
        ws_perf = wb["Daily Performance"]
        headers_perf = [cell.value for cell in ws_perf[1]]

        # Ensure duplicate 'LWD' is removed and 'Last Working Day' is preserved
        assert "LWD" not in headers_perf
        assert "Last Working Day" in headers_perf
        assert "Reporting Manager" in headers_perf
        assert "Applied By" in headers_perf
        assert "Approved By" in headers_perf

        # Verify row 2 data (Alice Green - leave reconciled)
        row2 = {headers_perf[i]: ws_perf.cell(row=2, column=i+1).value for i in range(len(headers_perf))}
        assert row2["Employee Number"] == "EMP101"
        assert row2["Reporting Manager"] == "Carlos Ray"
        assert row2["Location"] == "Bangalore"

        # Verify date cell is real date object with dd-mmm-yy number format
        lwd_val = row2["Last Working Day"]
        assert isinstance(lwd_val, (date, datetime))
        assert (lwd_val.year, lwd_val.month, lwd_val.day) == (2026, 9, 30)
        lwd_col_idx = headers_perf.index("Last Working Day") + 1
        assert ws_perf.cell(row=2, column=lwd_col_idx).number_format == "dd-mmm-yy"

        # Requester was Arjun S for Alice Green -> Admin
        assert row2["Applied By"] == "Admin"
        # Approver was Arjun S and RM is Carlos Ray -> Admin
        assert row2["Approved By"] == "Admin"

        # Verify styling on Daily Performance
        # Header: #00FF99 fill, bold
        h_cell = ws_perf.cell(row=1, column=1)
        assert h_cell.font.bold is True
        assert h_cell.fill.fill_type == "solid"
        assert "00FF99" in (h_cell.fill.start_color.rgb or "").upper()

        # Body: no border
        b_cell = ws_perf.cell(row=2, column=1)
        assert b_cell.border.left is None or b_cell.border.left.style is None
        assert b_cell.border.top is None or b_cell.border.top.style is None

        # 2. Verify Absent Mailer sheet
        ws_mailer = wb["Absent Mailer"]
        headers_mailer = [cell.value for cell in ws_mailer[1]]
        assert "LWD" not in headers_mailer
        assert "Last Working Day" in headers_mailer
        assert "Reporting Manager" in headers_mailer
        assert "Employee Mail ID" in headers_mailer
        assert "RM Mail ID" in headers_mailer

        # Verify mailer row contains Alice Green
        mailer_row = {headers_mailer[i]: ws_mailer.cell(row=2, column=i+1).value for i in range(len(headers_mailer))}
        assert mailer_row["Employee Number"] == "EMP101"
        assert mailer_row["Employee Mail ID"] == "alice@company.com"
        assert mailer_row["Reporting Manager"] == "Carlos Ray"
        assert mailer_row["RM Mail ID"] == "carlos@company.com"


def test_keka_fetcher_save_unified_workbook():
    """Verify KekaDataFetcher._save_unified_workbook saves both sheets with clean headers, styles & date formats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = Path(tmpdir) / "keka_unified.xlsx"

        df_perf = pd.DataFrame([{
            "Employee Number": "EMP201",
            "Employee Name": "David Miller",
            "Date": "01-Sep-26",
            "Status": "A",
            "Quantity": 1.0,
            "Reporting Manager": "Sarah Connor",
            "Last Working Day": "25-Aug-26",
            "Applied By": "Employee",
            "Approved By": "Manager",
        }])

        df_mailer = pd.DataFrame([{
            "Employee Number": "EMP201",
            "Employee Name": "David Miller",
            "Date": "01-Sep-26",
            "Status": "A",
            "Quantity": 1.0,
            "Employee Mail ID": "david@company.com",
            "Reporting Manager": "Sarah Connor",
            "RM Mail ID": "sarah@company.com",
            "Location": "Delhi",
            "Month": "Sep-2026",
            "Last Working Day": "25-Aug-26",
        }])

        fetcher = KekaDataFetcher(subdomain="test")
        fetcher._save_unified_workbook(df_perf, df_mailer, str(out_file))

        wb = openpyxl.load_workbook(out_file)
        assert "Daily Performance" in wb.sheetnames
        assert "Absent Mailer" in wb.sheetnames

        for sname in ["Daily Performance", "Absent Mailer"]:
            ws = wb[sname]
            headers = [cell.value for cell in ws[1]]
            assert "LWD" not in headers
            assert "Last Working Day" in headers

            # Check header fill and font
            assert ws.cell(row=1, column=1).font.bold is True
            assert "00FF99" in (ws.cell(row=1, column=1).fill.start_color.rgb or "").upper()

            # Check date cell formatting
            date_col_idx = headers.index("Date") + 1
            date_cell = ws.cell(row=2, column=date_col_idx)
            assert isinstance(date_cell.value, (date, datetime))
            assert date_cell.number_format == "dd-mmm-yy"


def test_pending_status_has_no_approved_data():
    """Verify that if Approval Status is Pending, Approved By and Approved On are strictly 'NA'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        perf_df = pd.DataFrame([{
            "Employee Number": "EMP501",
            "Employee Name": "Pending User",
            "Date": "2026-09-02",
            "Attendance Type": "Leave",
            "Attendance Status": "A",
            "Quantity": 1.0,
            "Approval Status": "Pending",
            "Approved By": "Some Old Name",
            "Approved On": "2026-09-01",
        }])
        perf_file = tmp_path / "perf.xlsx"
        perf_df.to_excel(perf_file, index=False)

        leave_df = pd.DataFrame([{
            "Employee Number": "EMP501",
            "Employee Name": "Pending User",
            "From Date": "2026-09-02",
            "To Date": "2026-09-02",
            "Total Duration": 1.0,
            "Status": "Pending",
            "Requester": "Pending User",
            "Requested On": "2026-09-01",
            "Last Action Taken by": "Manager Bob",
            "Action Taken On": "2026-09-01",
            "Leave Type": "Casual Leave",
        }])
        leave_file = tmp_path / "leaves.xlsx"
        leave_df.to_excel(leave_file, index=False)

        out_file = tmp_path / "reconciled_pending.xlsx"
        reconcile_time_and_leave(
            perf_files=[str(perf_file)],
            leave_active_files=[str(leave_file)],
            output_path=str(out_file)
        )

        wb = openpyxl.load_workbook(out_file)
        ws = wb["Daily Performance"]
        headers = [c.value for c in ws[1]]
        row = {headers[i]: ws.cell(row=2, column=i+1).value for i in range(len(headers))}

        assert row["Approval Status"] == "Pending"
        assert row["Approved By"] == "NA"
        assert row["Approved On"] == "NA"


def test_quantity_rules_half_day_and_max_one():
    """Verify that quantity is strictly 0.5 for half day and max 1.0 per date entry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        perf_df = pd.DataFrame([
            {
                "Employee Number": "EMP601",
                "Employee Name": "HalfDay User",
                "Date": "2026-09-03",
                "Attendance Type": "Leave",
                "Attendance Status": "A",
                "Quantity": 0.5,
            },
            {
                "Employee Number": "EMP602",
                "Employee Name": "MultiDay User",
                "Date": "2026-09-03",
                "Attendance Type": "Leave",
                "Attendance Status": "A",
                "Quantity": 3.0,  # Erroneous duration > 1 on single date
            }
        ])
        perf_file = tmp_path / "perf.xlsx"
        perf_df.to_excel(perf_file, index=False)

        leave_df = pd.DataFrame([
            {
                "Employee Number": "EMP601",
                "Employee Name": "HalfDay User",
                "From Date": "2026-09-03",
                "To Date": "2026-09-03",
                "Total Duration": 0.5,
                "Status": "Approved",
                "Leave Type": "Half Day Casual Leave",
            },
            {
                "Employee Number": "EMP602",
                "Employee Name": "MultiDay User",
                "From Date": "2026-09-03",
                "To Date": "2026-09-05",
                "Total Duration": 3.0,
                "Status": "Approved",
                "Leave Type": "Sick Leave",
            }
        ])
        leave_file = tmp_path / "leaves.xlsx"
        leave_df.to_excel(leave_file, index=False)

        out_file = tmp_path / "reconciled_qty.xlsx"
        reconcile_time_and_leave(
            perf_files=[str(perf_file)],
            leave_active_files=[str(leave_file)],
            output_path=str(out_file)
        )

        wb = openpyxl.load_workbook(out_file)
        ws_perf = wb["Daily Performance"]
        headers_perf = [c.value for c in ws_perf[1]]

        r1 = {headers_perf[i]: ws_perf.cell(row=2, column=i+1).value for i in range(len(headers_perf))}
        r2 = {headers_perf[i]: ws_perf.cell(row=3, column=i+1).value for i in range(len(headers_perf))}

        assert r1["Quantity"] == 0.5
        assert r2["Quantity"] == 1.0  # Capped at 1.0 because entries are single date records

        # Verify Absent Mailer quantities are strictly 0.5 or 1.0
        ws_mailer = wb["Absent Mailer"]
        headers_mailer = [c.value for c in ws_mailer[1]]
        for r_idx in range(2, ws_mailer.max_row + 1):
            m_row = {headers_mailer[i]: ws_mailer.cell(row=r_idx, column=i+1).value for i in range(len(headers_mailer))}
            assert m_row["Quantity"] in (0.5, 1.0)


def test_absent_management_deduplication():
    """Verify absent_management.process_absent_management produces Last Working Day and no LWD."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Master file
        emp_df = pd.DataFrame([{
            "Employee Number": "EMP301",
            "Employee Name": "Elena Rostova",
            "Email": "elena@company.com",
            "Reporting Manager Name": "Alex Smith",
            "Reporting Manager Email": "alex@company.com",
            "Location": "Bangalore",
            "Last Working Date": "2026-08-20",
        }])
        emp_file = tmp_path / "emp_master.xlsx"
        emp_df.to_excel(emp_file, index=False)

        # 2. Attendance file with both LWD and Last Working Day
        att_df = pd.DataFrame([{
            "Employee Number": "EMP301",
            "Date": "2026-09-01",
            "Attendance Status": "A",
            "Quantity": 1.0,
            "LWD": "20-Aug-26",
            "Last Working Day": "20-Aug-26",
        }])
        att_file = tmp_path / "att.xlsx"
        att_df.to_excel(att_file, index=False)

        # 3. Empty OD/WFH file
        wfh_df = pd.DataFrame([{
            "Employee Number": "EMP301",
            "Request Type": "WFH",
            "From Date": "2026-09-05",
            "To Date": "2026-09-05",
            "Status": "Approved",
        }])
        wfh_file = tmp_path / "wfh.xlsx"
        wfh_df.to_excel(wfh_file, index=False)

        out_file = tmp_path / "Absent_Report.xlsx"
        absent_management.process_absent_management(
            str(emp_file), str(att_file), str(wfh_file), str(out_file)
        )

        wb = openpyxl.load_workbook(out_file)
        for sname in wb.sheetnames:
            ws = wb[sname]
            headers = [cell.value for cell in ws[1]]
            assert "LWD" not in headers, f"Sheet '{sname}' unexpectedly contained duplicate 'LWD' header"
            assert "Last Working Day" in headers, f"Sheet '{sname}' was missing 'Last Working Day' header"


def test_app_absent_tab_removed_and_one_card():
    """Verify that Absent Management is removed from navigation items and Time & Leave Master has one card."""
    app_file = Path(__file__).resolve().parent.parent / "app.py"
    content = app_file.read_text(encoding="utf-8")

    # 1. Verify "absent" is not in transform_sub_items or flyout items
    assert '("absent", "Absent Management"' not in content, "Absent Management should not be in navigation items"

    # 2. Verify "absent" is not in dashboard cards
    dash_start = content.find("def _build_dashboard_frame(self):")
    dash_end = content.find("def _build_transform_frame(self):")
    dash_code = content[dash_start:dash_end]
    assert 'select_frame_by_name("absent")' not in dash_code, "Absent Management should not be a card on Dashboard"

    # 3. Verify _build_time_leave_frame has exactly ONE card
    tl_start = content.find("def _build_time_leave_frame(self):")
    tl_end = content.find("def _build_id_card_frame(self):")
    tl_code = content[tl_start:tl_end]

    card_count = tl_code.count("ui.create_card(")
    assert card_count == 1, f"Expected exactly 1 card in Time and Leave Master, found {card_count}"


def test_post_lwd_attendance_is_strictly_excluded():
    """Verify that if employee LWD is in July or August, attendance in September is completely dropped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        perf_df = pd.DataFrame([
            {
                "Employee Number": "EMP_INACTIVE",
                "Employee Name": "Ex Employee",
                "Date": "2026-09-02",
                "Attendance Type": "Absent",
                "Status": "A",
                "Quantity": 1.0,
                "Last Working Day": "2026-08-15",
            },
            {
                "Employee Number": "EMP_ACTIVE",
                "Employee Name": "Current Employee",
                "Date": "2026-09-02",
                "Attendance Type": "Present",
                "Status": "P",
                "Quantity": 1.0,
                "Last Working Day": "",
            }
        ])
        perf_file = tmp_path / "perf.xlsx"
        perf_df.to_excel(perf_file, index=False)
        out_file = tmp_path / "unified.xlsx"

        stats = reconcile_time_and_leave(
            perf_files=[str(perf_file)],
            output_path=str(out_file)
        )

        assert stats["total_rows"] == 1
        wb = openpyxl.load_workbook(out_file)
        ws = wb["Daily Performance"]
        headers = [c.value for c in ws[1]]
        emp_idx = headers.index("Employee Number") + 1
        emp_ids = [ws.cell(row=r, column=emp_idx).value for r in range(2, ws.max_row + 1)]
        assert "EMP_INACTIVE" not in emp_ids
        assert "EMP_ACTIVE" in emp_ids


def test_half_day_colon_split_into_two_rows_with_half_quantity():
    """Verify that composite half-day entries (CL/SL:A) split into two rows with 0.5 quantity each."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        perf_df = pd.DataFrame([
            {
                "Employee Number": "EMP701",
                "Employee Name": "Half User",
                "Date": "2026-09-05",
                "Attendance Type": "Leave",
                "Status": "CL/SL:A",
                "Quantity": 1.0,
            }
        ])
        perf_file = tmp_path / "perf.xlsx"
        perf_df.to_excel(perf_file, index=False)
        out_file = tmp_path / "split_report.xlsx"

        stats = reconcile_time_and_leave(
            perf_files=[str(perf_file)],
            output_path=str(out_file)
        )

        assert stats["total_rows"] == 2
        wb = openpyxl.load_workbook(out_file)
        ws = wb["Daily Performance"]
        headers = [c.value for c in ws[1]]
        st_idx = headers.index("Status") + 1
        q_idx = headers.index("Quantity") + 1

        rows = []
        for r in range(2, ws.max_row + 1):
            rows.append({
                "Status": ws.cell(row=r, column=st_idx).value,
                "Quantity": ws.cell(row=r, column=q_idx).value,
            })

        assert len(rows) == 2
        assert rows[0]["Quantity"] == 0.5
        assert rows[1]["Quantity"] == 0.5
        statuses = [r["Status"] for r in rows]
        assert "CL/SL" in statuses
        assert "A" in statuses


def test_leave_status_reflects_actual_leave_type_code():
    """Verify that Status column shows actual leave abbreviation (e.g. SL, EL, GL) not CLSL."""
    from time_leave_master import get_leave_status_code
    assert get_leave_status_code("Sick Leave") == "SL"
    assert get_leave_status_code("Casual Leave") == "CL"
    assert get_leave_status_code("Earned Leave") == "EL"
    assert get_leave_status_code("Privilege Leave") == "PL"
    assert get_leave_status_code("Garden Leave") == "GL"
    assert get_leave_status_code("Comp Off") == "CO"
    assert get_leave_status_code("Wedding Leave") == "WL"


def test_admin_applied_leave_detection_rules():
    """Verify Garden Leave and instant approvals are correctly tagged as Admin."""
    # Garden Leave is always Admin
    assert compute_applied_by("John Doe", "John Doe", leave_name="Garden Leave") == "Admin"
    # Instant approval (same minute timestamp) is Admin
    assert compute_applied_by(
        "John Doe", "John Doe",
        leave_name="Casual Leave",
        requested_on="2026-09-01 10:00:00",
        action_taken_on="2026-09-01 10:00:00"
    ) == "Admin"
    # Normal employee self-application
    assert compute_applied_by(
        "John Doe", "John Doe",
        leave_name="Casual Leave",
        requested_on="2026-09-01 10:00:00",
        action_taken_on="2026-09-02 14:00:00"
    ) == "Employee"


def test_approved_by_always_has_approved_on_date():
    """Verify that if Approval Status is Approved, Approved On date is populated, never missing or NA."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        perf_df = pd.DataFrame([{
            "Employee Number": "EMP801",
            "Employee Name": "Test Employee",
            "Date": "2026-09-10",
            "Attendance Type": "Leave",
            "Status": "Leave",
            "Quantity": 1.0,
        }])
        perf_file = tmp_path / "perf.xlsx"
        perf_df.to_excel(perf_file, index=False)

        leave_df = pd.DataFrame([{
            "Employee Number": "EMP801",
            "Employee Name": "Test Employee",
            "From Date": "2026-09-10",
            "To Date": "2026-09-10",
            "Total Duration": 1.0,
            "Requester": "Test Employee",
            "Requested On": "2026-09-09",
            "Last Action Taken by": "Manager Sarah",
            "Action Taken On": "",  # Missing approval date in raw input
            "Leave Type": "Sick Leave",
            "Status": "Approved",
        }])
        leave_file = tmp_path / "leaves.xlsx"
        leave_df.to_excel(leave_file, index=False)

        out_file = tmp_path / "approved_date_test.xlsx"
        reconcile_time_and_leave(
            perf_files=[str(perf_file)],
            leave_active_files=[str(leave_file)],
            output_path=str(out_file)
        )

        wb = openpyxl.load_workbook(out_file)
        ws = wb["Daily Performance"]
        headers = [c.value for c in ws[1]]
        row = {headers[i]: ws.cell(row=2, column=i+1).value for i in range(len(headers))}

        assert row["Approval Status"] == "Approved"
        assert row["Approved By"] == "Manager"
        # Approved On must be populated with fallback (from Requested On or Date), NEVER "NA" or None
        assert row["Approved On"] is not None
        assert str(row["Approved On"]).strip().upper() not in ("NA", "NONE", "")

