"""
test_time_leave_master.py
─────────────────────────
Comprehensive test suite for the Time and Leave Master engine.
Validates multi-month file combination, date splitting / expansion,
role computation (Applied By & Approved By), half-day matching,
and quantity validation constraints.
"""

from datetime import date
from pathlib import Path
import tempfile
import pandas as pd
import pytest

from time_leave_master import (
    compute_applied_by,
    compute_approved_by,
    expand_application_records,
    load_and_combine_files,
    parse_date,
    reconcile_time_and_leave,
)


def test_compute_applied_by():
    # If requester matches Employee Name -> Employee, else Admin
    assert compute_applied_by("John Doe", "John Doe") == "Employee"
    assert compute_applied_by("  john doe  ", "JOHN DOE") == "Employee"
    assert compute_applied_by("Jane Smith", "John Doe") == "Admin"
    assert compute_applied_by("HR Admin", "John Doe") == "Admin"
    assert compute_applied_by("", "John Doe") == "Employee"


def test_compute_approved_by():
    # If action taken by is 'Arjun S' or 'E Janani Sri' -> Admin, else Manager (Approved By should never be Employee)
    assert compute_approved_by("Arjun S") == "Admin"
    assert compute_approved_by("arjun s") == "Admin"
    assert compute_approved_by("E Janani Sri") == "Admin"
    assert compute_approved_by("e janani sri") == "Admin"
    assert compute_approved_by("Janani Sri E") == "Admin"
    assert compute_approved_by("Reporting Manager") == "Manager"
    assert compute_approved_by("Priya Sharma") == "Manager"
    assert compute_approved_by("") == "Manager"


def test_expand_application_records():
    # Test multi-day leave expansion
    df = pd.DataFrame([{
        "Employee Number": "EMP001",
        "Employee Name": "Alice Smith",
        "From Date": "2026-09-01",
        "To Date": "2026-09-03",
        "Total Duration": 3,
        "Requester": "Alice Smith",
        "Requested On": "2026-08-28",
        "Last Action Taken by": "Arjun S",
        "Action Taken On": "2026-08-29",
        "Leave Type": "Casual Leave",
    }])

    expanded = expand_application_records(df, app_type="leave")
    assert len(expanded) == 3
    dates = [rec["date"] for rec in expanded]
    assert dates == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    for rec in expanded:
        assert rec["emp_num"] == "EMP001"
        assert rec["applied_by"] == "Employee"
        assert rec["applied_on"] == "28-Aug-26"
        assert rec["approved_by"] == "Admin"
        assert rec["approved_on"] == "29-Aug-26"


def test_expand_half_day_application():
    df = pd.DataFrame([{
        "Employee Number": "EMP002",
        "Employee Name": "Bob Jones",
        "From Date": "2026-09-05",
        "To Date": "2026-09-05",
        "Total Duration": 0.5,
        "Requested By": "Bob Jones",
        "Applied On": "2026-09-04",
        "Action Taken By": "Manager David",
        "Approved On": "2026-09-04",
        "Leave Name": "Sick Leave",
    }])

    expanded = expand_application_records(df, app_type="leave")
    assert len(expanded) == 1
    assert expanded[0]["date"] == date(2026, 9, 5)
    assert expanded[0]["duration"] == 0.5
    assert expanded[0]["applied_by"] == "Employee"
    assert expanded[0]["approved_by"] == "Manager"


def test_load_and_combine_files():
    with tempfile.TemporaryDirectory() as tmp_dir:
        f1 = Path(tmp_dir) / "month1.xlsx"
        f2 = Path(tmp_dir) / "month2.xlsx"

        df1 = pd.DataFrame([{"Employee Number": "E1", "Date": "2026-08-01"}])
        df2 = pd.DataFrame([{"Employee Number": "E1", "Date": "2026-09-01"}])

        df1.to_excel(f1, index=False)
        df2.to_excel(f2, index=False)

        combined = load_and_combine_files([f1, f2])
        assert len(combined) == 2


def test_reconciliation_end_to_end():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        perf_file = tmp_p / "daily_perf.xlsx"
        leave_active_file = tmp_p / "leave_active.xlsx"
        leave_inactive_file = tmp_p / "leave_inactive.xlsx"
        wfh_file = tmp_p / "wfh.xlsx"
        out_file = tmp_p / "output.xlsx"

        # Daily Performance Report:
        # Row 0: Full day leave (Alice on 2026-09-02)
        # Row 1 & 2: Two half-day entries on the same day (Bob on 2026-09-04, 0.5 CL and 0.5 SL)
        # Row 3: Full day WFH (Charlie on 2026-09-05)
        # Row 4: Present day (David on 2026-09-05, no application)
        df_perf = pd.DataFrame([
            {
                "Employee Number": "E001",
                "Employee Name": "Alice Smith",
                "Date": "2026-09-02",
                "Status": "CL",
                "Attendance Type": "Leave",
                "Leave Name": "Casual Leave",
                "Quantity": 1.0,
                "Applied By": "",
                "Applied On": "",
                "Approved By": "",
                "Approved On": "",
            },
            {
                "Employee Number": "E002",
                "Employee Name": "Bob Jones",
                "Date": "2026-09-04",
                "Status": "CL",
                "Attendance Type": "Leave",
                "Leave Name": "Casual Leave",
                "Quantity": 0.5,
                "Applied By": "",
                "Applied On": "",
                "Approved By": "",
                "Approved On": "",
            },
            {
                "Employee Number": "E002",
                "Employee Name": "Bob Jones",
                "Date": "2026-09-04",
                "Status": "SL",
                "Attendance Type": "Leave",
                "Leave Name": "Sick Leave",
                "Quantity": 0.5,
                "Applied By": "",
                "Applied On": "",
                "Approved By": "",
                "Approved On": "",
            },
            {
                "Employee Number": "E003",
                "Employee Name": "Charlie Brown",
                "Date": "2026-09-05",
                "Status": "WFH",
                "Attendance Type": "Work From Home",
                "Leave Name": "-",
                "Quantity": 1.0,
                "Applied By": "",
                "Applied On": "",
                "Approved By": "",
                "Approved On": "",
            },
            {
                "Employee Number": "E004",
                "Employee Name": "David Miller",
                "Date": "2026-09-05",
                "Status": "P",
                "Attendance Type": "Present",
                "Leave Name": "-",
                "Quantity": 1.0,
                "Applied By": "",
                "Applied On": "",
                "Approved By": "",
                "Approved On": "",
            }
        ])
        df_perf.to_excel(perf_file, index=False)

        # Leave Active: Alice multi-day application (09-01 to 09-03)
        df_leave_act = pd.DataFrame([{
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "From Date": "2026-09-01",
            "To Date": "2026-09-03",
            "Total Duration": 3,
            "Requested By": "HR Ops",  # Admin applied
            "Applied On": "2026-08-30",
            "Last Action Taken by": "Arjun S",  # Admin approved
            "Approved On": "2026-08-31",
            "Leave Type": "Casual Leave",
        }])
        df_leave_act.to_excel(leave_active_file, index=False)

        # Leave Inactive: Bob two half days (one in inactive, one in active)
        df_leave_inact = pd.DataFrame([{
            "Employee Number": "E002",
            "Employee Name": "Bob Jones",
            "From Date": "2026-09-04",
            "To Date": "2026-09-04",
            "Total Duration": 0.5,
            "Requested By": "Bob Jones",  # Employee applied
            "Applied On": "2026-09-03",
            "Last Action Taken by": "Manager Peter",  # Employee approved
            "Approved On": "2026-09-04",
            "Leave Type": "Casual Leave",
        }, {
            "Employee Number": "E002",
            "Employee Name": "Bob Jones",
            "From Date": "2026-09-04",
            "To Date": "2026-09-04",
            "Total Duration": 0.5,
            "Requested By": "Bob Jones",
            "Applied On": "2026-09-04",
            "Last Action Taken by": "E Janani Sri",  # Admin approved
            "Approved On": "2026-09-04",
            "Leave Type": "Sick Leave",
        }])
        df_leave_inact.to_excel(leave_inactive_file, index=False)

        # WFH: Charlie WFH application
        df_wfh = pd.DataFrame([{
            "Employee Number": "E003",
            "Employee Name": "Charlie Brown",
            "From Date": "2026-09-05",
            "To Date": "2026-09-05",
            "Total Duration": 1,
            "Requested By": "Charlie Brown",
            "Applied On": "2026-09-04",
            "Last Action Taken by": "Arjun S",
            "Approved On": "2026-09-05",
        }])
        df_wfh.to_excel(wfh_file, index=False)

        # Run reconciliation
        stats = reconcile_time_and_leave(
            perf_files=[perf_file],
            leave_active_files=[leave_active_file],
            leave_inactive_files=[leave_inactive_file],
            wfh_files=[wfh_file],
            output_path=out_file
        )

        assert stats["total_rows"] == 5
        assert stats["matched_leave_count"] == 3
        assert stats["matched_wfh_count"] == 1
        assert stats["quantity_violation_count"] == 0

        # Verify output dataframe content (keep_default_na=False to read NA as string)
        res = pd.read_excel(out_file, keep_default_na=False)
        # Alice (E001):
        alice_row = res[res["Employee Number"] == "E001"].iloc[0]
        assert alice_row["Date"] == "02-Sep-26"
        assert alice_row["Applied By"] == "Admin"
        assert alice_row["Applied On"] == "30-Aug-26"
        assert alice_row["Approved By"] == "Admin"
        assert alice_row["Approved On"] == "31-Aug-26"

        # Bob (E002): 2 half days
        bob_rows = res[res["Employee Number"] == "E002"]
        assert len(bob_rows) == 2
        bob_cl = bob_rows[bob_rows["Leave Name"] == "Casual Leave"].iloc[0]
        assert bob_cl["Applied By"] == "Employee"
        assert bob_cl["Approved By"] == "Manager"

        bob_sl = bob_rows[bob_rows["Leave Name"] == "Sick Leave"].iloc[0]
        assert bob_sl["Applied By"] == "Employee"
        assert bob_sl["Approved By"] == "Admin"

        # Charlie (E003): WFH
        charlie_row = res[res["Employee Number"] == "E003"].iloc[0]
        assert charlie_row["Applied By"] == "Employee"
        assert charlie_row["Approved By"] == "Admin"

        # David (E004): Unchanged / not matched -> defaults to NA
        david_row = res[res["Employee Number"] == "E004"].iloc[0]
        assert david_row["Applied By"] == "NA"


def test_quantity_violation_detected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        perf_file = tmp_p / "daily_perf_viol.xlsx"
        out_file = tmp_p / "output.xlsx"

        # Employee with two rows having quantity 1.0 each on the same day -> total 2.0 > 1.0
        df_perf = pd.DataFrame([
            {
                "Employee Number": "E999",
                "Employee Name": "Violator",
                "Date": "2026-09-10",
                "Status": "CL",
                "Quantity": 1.0,
            },
            {
                "Employee Number": "E999",
                "Employee Name": "Violator",
                "Date": "2026-09-10",
                "Status": "WFH",
                "Quantity": 1.0,
            }
        ])
        df_perf.to_excel(perf_file, index=False)

        stats = reconcile_time_and_leave(
            perf_files=[perf_file],
            leave_active_files=[],
            leave_inactive_files=[],
            wfh_files=[],
            output_path=out_file
        )

        assert stats["quantity_violation_count"] == 1
        assert stats["quantity_violations"][0]["employee"] == "E999"
        assert stats["quantity_violations"][0]["total_quantity"] == 2.0


def test_attendance_type_filtering():
    """
    Verify that WFH applications are ONLY merged if Attendance Type is 'Work From Home',
    and Leave applications are ONLY merged if Attendance Type is 'Leave'.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        perf_file = tmp_p / "daily_perf_filter.xlsx"
        leave_file = tmp_p / "leave_app.xlsx"
        wfh_file = tmp_p / "wfh_app.xlsx"
        out_file = tmp_p / "output_filter.xlsx"

        df_perf = pd.DataFrame([
            {
                "Employee Number": "E100",
                "Employee Name": "User One",
                "Date": "2026-09-01",
                "Attendance Type": "Present",  # Not Leave
                "Status": "P",
            },
            {
                "Employee Number": "E100",
                "Employee Name": "User One",
                "Date": "2026-09-02",
                "Attendance Type": "Absent",  # Not Work From Home
                "Status": "A",
            },
            {
                "Employee Number": "E100",
                "Employee Name": "User One",
                "Date": "2026-09-03",
                "Attendance Type": "Leave",  # Valid Leave
                "Status": "CL",
            },
            {
                "Employee Number": "E100",
                "Employee Name": "User One",
                "Date": "2026-09-04",
                "Attendance Type": "Work From Home",  # Valid WFH
                "Status": "WFH",
            },
        ])
        df_perf.to_excel(perf_file, index=False)

        # Leave application covering 2026-09-01 (when user was 'Present') and 2026-09-03 (when user was 'Leave')
        df_leave = pd.DataFrame([{
            "Employee Number": "E100",
            "Employee Name": "User One",
            "From Date": "2026-09-01",
            "To Date": "2026-09-03",
            "Total Duration": 3,
            "Requested By": "User One",
            "Applied On": "2026-08-30",
            "Action Taken By": "Arjun S",
            "Approved On": "2026-08-31",
        }])
        df_leave.to_excel(leave_file, index=False)

        # WFH application covering 2026-09-02 (when user was 'Absent') and 2026-09-04 (when user was 'Work From Home')
        df_wfh = pd.DataFrame([{
            "Employee Number": "E100",
            "Employee Name": "User One",
            "From Date": "2026-09-02",
            "To Date": "2026-09-04",
            "Total Duration": 3,
            "Requested By": "User One",
            "Applied On": "2026-09-01",
            "Action Taken By": "E Janani Sri",
            "Approved On": "2026-09-02",
        }])
        df_wfh.to_excel(wfh_file, index=False)

        stats = reconcile_time_and_leave(
            perf_files=[perf_file],
            leave_active_files=[leave_file],
            leave_inactive_files=[],
            wfh_files=[wfh_file],
            output_path=out_file
        )

        assert stats["matched_leave_count"] == 1
        assert stats["matched_wfh_count"] == 1

        res = pd.read_excel(out_file, keep_default_na=False)

        # Row 0: Present on 2026-09-01 -> should NOT be merged, defaults to NA
        row_0 = res[res["Date"] == "01-Sep-26"].iloc[0]
        assert row_0["Applied By"] == "NA"

        # Row 1: Absent on 2026-09-02 -> should NOT be merged, defaults to NA
        row_1 = res[res["Date"] == "02-Sep-26"].iloc[0]
        assert row_1["Applied By"] == "NA"

        # Row 2: Leave on 2026-09-03 -> SHOULD be merged
        row_2 = res[res["Date"] == "03-Sep-26"].iloc[0]
        assert row_2["Applied By"] == "Employee"
        assert row_2["Approved By"] == "Admin"

        # Row 3: Work From Home on 2026-09-04 -> SHOULD be merged
        row_3 = res[res["Date"] == "04-Sep-26"].iloc[0]
        assert row_3["Applied By"] == "Employee"
        assert row_3["Approved By"] == "Admin"


def test_status_matching_and_excel_formatting():
    """
    Verify that WFH Request Status and Leave Status are matched into the output,
    and the output Excel has Calibri 11 format, 1st row bold filled with #00FF99, and no borders.
    """
    import openpyxl

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        perf_file = tmp_p / "perf_status.xlsx"
        leave_file = tmp_p / "leave_status.xlsx"
        wfh_file = tmp_p / "wfh_status.xlsx"
        out_file = tmp_p / "out_styled.xlsx"

        df_perf = pd.DataFrame([
            {
                "Employee Number": "E501",
                "Employee Name": "Sara Lee",
                "Date": "2026-09-10",
                "Attendance Type": "Leave",
                "Status": "CL",
                "Approval Status": "",
            },
            {
                "Employee Number": "E502",
                "Employee Name": "Tom Hardy",
                "Date": "2026-09-11",
                "Attendance Type": "Work From Home",
                "Status": "WFH",
                "Approval Status": "",
            },
        ])
        df_perf.to_excel(perf_file, index=False)

        df_leave = pd.DataFrame([{
            "Employee Number": "E501",
            "Employee Name": "Sara Lee",
            "From Date": "2026-09-10",
            "To Date": "2026-09-10",
            "Total Duration": 1,
            "Requested By": "Sara Lee",
            "Status": "Approved",  # Leave Status
            "Action Taken By": "Arjun S",
        }])
        df_leave.to_excel(leave_file, index=False)

        df_wfh = pd.DataFrame([{
            "Employee Number": "E502",
            "Employee Name": "Tom Hardy",
            "From Date": "2026-09-11",
            "To Date": "2026-09-11",
            "Total Duration": 1,
            "Requested By": "Tom Hardy",
            "Request Status": "Pending",  # WFH Request Status
            "Action Taken By": "E Janani Sri",
        }])
        df_wfh.to_excel(wfh_file, index=False)

        stats = reconcile_time_and_leave(
            perf_files=[perf_file],
            leave_active_files=[leave_file],
            leave_inactive_files=[],
            wfh_files=[wfh_file],
            output_path=out_file
        )

        assert stats["matched_leave_count"] == 1
        assert stats["matched_wfh_count"] == 1

        # Check matched statuses in output DataFrame
        res = pd.read_excel(out_file)
        sara_row = res[res["Employee Number"] == "E501"].iloc[0]
        assert sara_row["Approval Status"] == "Approved"

        tom_row = res[res["Employee Number"] == "E502"].iloc[0]
        assert tom_row["Approval Status"] == "Pending"

        # Check Excel formatting via openpyxl
        wb = openpyxl.load_workbook(out_file)
        ws = wb.active

        # Check Header (Row 1)
        for cell in ws[1]:
            assert cell.font.name == "Calibri"
            assert cell.font.size == 10
            assert cell.font.bold is True
            # Fill color check: 00FF99
            assert cell.fill.start_color.rgb == "0000FF99" or cell.fill.start_color.rgb == "00FF99"
            assert cell.border.left is None or cell.border.left.style is None
            assert cell.border.right is None or cell.border.right.style is None
            assert cell.border.top is None or cell.border.top.style is None
            assert cell.border.bottom is None or cell.border.bottom.style is None

        # Check Data rows (Row 2, Row 3)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                assert cell.font.name == "Calibri"
                assert cell.font.size == 10
                assert cell.font.bold is False or cell.font.bold is None
                assert cell.border.left is None or cell.border.left.style is None
                assert cell.border.right is None or cell.border.right.style is None
                assert cell.border.top is None or cell.border.top.style is None
                assert cell.border.bottom is None or cell.border.bottom.style is None


def test_realtime_progress_callback():
    """
    Verify that progress_callback receives monotonically increasing progress updates
    with informative status messages across files, application expansion, and row reconciliation.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        perf_file = tmp_p / "perf.xlsx"
        leave_file = tmp_p / "leave.xlsx"
        out_file = tmp_p / "out.xlsx"

        # Generate 20 rows of performance data
        rows = []
        for i in range(20):
            rows.append({
                "Employee Number": f"E{i:03d}",
                "Employee Name": f"Employee {i}",
                "Date": f"2026-09-{(i % 10) + 1:02d}",
                "Attendance Type": "Leave" if i % 2 == 0 else "Present",
                "Status": "CL" if i % 2 == 0 else "P",
                "Quantity": 1.0,
            })
        pd.DataFrame(rows).to_excel(perf_file, index=False)

        # Generate leave application
        pd.DataFrame([{
            "Employee Number": "E000",
            "Employee Name": "Employee 0",
            "From Date": "2026-09-01",
            "To Date": "2026-09-01",
            "Total Duration": 1,
            "Requested By": "Employee 0",
            "Status": "Approved",
            "Action Taken By": "Arjun S",
        }]).to_excel(leave_file, index=False)

        progress_updates = []

        def on_progress(ratio: float, msg: str):
            progress_updates.append((ratio, msg))

        stats = reconcile_time_and_leave(
            perf_files=[perf_file],
            leave_active_files=[leave_file],
            leave_inactive_files=[],
            wfh_files=[],
            output_path=out_file,
            progress_callback=on_progress,
        )

        assert stats["total_rows"] == 20
        assert len(progress_updates) >= 5

        # Verify progress starts low and reaches 1.0
        assert progress_updates[0][0] <= 0.05
        assert progress_updates[-1][0] == 1.0

        # Verify progress ratios are non-decreasing
        ratios = [u[0] for u in progress_updates]
        for idx in range(1, len(ratios)):
            assert ratios[idx] >= ratios[idx - 1]

        # Verify row volume reconciliation messages occurred
        reconcile_msgs = [u[1] for u in progress_updates if "Reconciling" in u[1]]
        assert len(reconcile_msgs) > 0


def test_na_preservation_in_output():
    """
    Verify that literal 'NA' in input files is preserved in the output sheet
    and not converted to NaN or blank cells.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir)
        perf_file = tmp_p / "perf_with_na.xlsx"
        out_file = tmp_p / "output_preserved_na.xlsx"

        df_perf = pd.DataFrame([
            {
                "Employee Number": "EMP_NA_01",
                "Employee Name": "Alice",
                "Date": "2026-09-01",
                "Attendance Type": "NA",
                "Status": "NA",
                "Remarks": "NA",
                "Quantity": 1.0,
            },
            {
                "Employee Number": "EMP_NA_02",
                "Employee Name": "Bob",
                "Date": "2026-09-02",
                "Attendance Type": "Present",
                "Status": "P",
                "Remarks": "Good",
                "Quantity": 1.0,
            }
        ])
        df_perf.to_excel(perf_file, index=False)

        stats = reconcile_time_and_leave(
            perf_files=[perf_file],
            leave_active_files=[],
            leave_inactive_files=[],
            wfh_files=[],
            output_path=out_file
        )

        assert stats["total_rows"] == 2

        # Read back output with keep_default_na=False to check literal content
        res = pd.read_excel(out_file, keep_default_na=False)
        row0 = res[res["Employee Number"] == "EMP_NA_01"].iloc[0]
        assert row0["Attendance Type"] == "NA"
        assert row0["Status"] == "NA"
        assert row0["Remarks"] == "NA"




