"""
tests/test_keka_data_fetcher.py
───────────────────────────────
Unit and integration tests for keka_data_fetcher.py and its compatibility
with absent_management.py.
"""

import os
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

import keka_data_fetcher as kdf
from keka_data_fetcher import KekaDataFetcher, get_keka_access_token
import absent_management


# ------------------------------------------------------------------------------
# Test 1: Fetcher initialization and subdomain resolution
# ------------------------------------------------------------------------------
def test_keka_data_fetcher_init():
    fetcher = KekaDataFetcher(subdomain="finbox")
    assert fetcher.subdomain == "finbox"
    assert fetcher.base_url == "https://finbox.keka.com/api/v1"

    # URL trimming
    fetcher2 = KekaDataFetcher(subdomain="https://mycompany.keka.com")
    assert fetcher2.subdomain == "mycompany"
    assert fetcher2.base_url == "https://mycompany.keka.com/api/v1"


# ------------------------------------------------------------------------------
# Test 2: OAuth token caching & error handling
# ------------------------------------------------------------------------------
def test_token_auth_missing_creds(monkeypatch):
    monkeypatch.setenv("KEKA_API_KEY", "")
    monkeypatch.setenv("KEKA_CLIENT_ID", "")
    monkeypatch.setenv("KEKA_CLIENT_SECRET", "")
    kdf._KEKA_TOKEN_CACHE["access_token"] = None
    kdf._KEKA_TOKEN_CACHE["expires_at"] = 0

    tok, err = get_keka_access_token(api_key="", client_id="", client_secret="")
    assert tok is None
    assert "missing" in err.lower()


def test_token_auth_direct_token():
    tok, err = get_keka_access_token(api_key="direct_secret_jwt")
    assert err is None
    assert tok == "direct_secret_jwt"


# ------------------------------------------------------------------------------
# Test 3: fetch_employee_master mocking
# ------------------------------------------------------------------------------
def test_fetch_employee_master_columns_and_data(monkeypatch):
    mock_employees = {
        "totalPages": 1,
        "data": [
            {
                "id": "emp_01",
                "employeeNumber": "FB-101",
                "displayName": "Alice Smith",
                "email": "alice@finbox.in",
                "reportingManager": {
                    "id": "emp_02",
                    "displayName": "Bob Manager",
                    "email": "bob@finbox.in"
                },
                "location": {"name": "Bangalore"},
                "lastWorkingDay": "2026-12-31T00:00:00Z",
                "groups": [
                    {"groupType": 1, "title": "Engineering"},        # BU via integer
                    {"groupType": 2, "title": "Backend"},            # Dept via integer
                ]
            },
            {
                "id": "emp_02",
                "employeeNumber": "FB-102",
                "displayName": "Bob Manager",
                "email": "bob@finbox.in",
                "reportingManager": None,
                "location": "Remote",
                "lastWorkingDay": None,
                "groups": [
                    # BU via groupTypeName string (robustness path)
                    {"groupType": 99, "groupTypeName": "Business Unit", "title": "Operations"},
                    {"groupType": 99, "groupTypeName": "Department",    "title": "HR"},
                ]
            }
        ]
    }

    class MockResponse:
        status_code = 200
        def json(self):
            return mock_employees

    def mock_get(url, **kwargs):
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_get)

    fetcher = KekaDataFetcher(subdomain="finbox", api_key="test_token")
    df_emp, err = fetcher.fetch_employee_master()

    assert err is None
    assert len(df_emp) == 2

    # All required columns present — including RM Mail ID alias
    required_cols = [
        "Employee Number", "Employee Name", "Work Email",
        "Reporting Manager", "Reporting Manager Email", "RM Mail ID",
        "Last Working Day", "Location", "Business Unit", "Department"
    ]
    for col in required_cols:
        assert col in df_emp.columns, f"Missing required column: {col}"

    # Alice — groupType integer path
    assert df_emp.loc[0, "Employee Number"] == "FB-101"
    assert df_emp.loc[0, "Work Email"] == "alice@finbox.in"
    assert df_emp.loc[0, "Reporting Manager"] == "Bob Manager"
    assert df_emp.loc[0, "Reporting Manager Email"] == "bob@finbox.in"
    assert df_emp.loc[0, "RM Mail ID"] == "bob@finbox.in"
    assert df_emp.loc[0, "Location"] == "Bangalore"
    assert df_emp.loc[0, "Business Unit"] == "Engineering"
    assert df_emp.loc[0, "Department"] == "Backend"
    assert df_emp.loc[0, "Last Working Day"] == "31-Dec-26"

    # Bob — groupTypeName string path
    assert df_emp.loc[1, "Employee Number"] == "FB-102"
    assert df_emp.loc[1, "Location"] == "Remote"
    assert df_emp.loc[1, "Business Unit"] == "Operations"
    assert df_emp.loc[1, "Department"] == "HR"
    assert df_emp.loc[1, "Last Working Day"] == ""


# ------------------------------------------------------------------------------
# Test 4: fetch_od_wfh_requests mocking
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
def test_fetch_od_wfh_requests_structure(monkeypatch):
    mock_wfh = {
        "totalPages": 1,
        "data": [
            {
                "employeeNumber": "FB-101",
                "employeeName": "Alice Smith",
                "fromDate": "2026-09-10T00:00:00Z",
                "toDate": "2026-09-12T00:00:00Z",
                "status": 1  # Pending
            },
            {
                "employeeNumber": "FB-103",
                "employeeName": "Eve Cancelled",
                "fromDate": "2026-09-10T00:00:00Z",
                "toDate": "2026-09-12T00:00:00Z",
                "status": 4,  # Cancelled -> MUST BE IGNORED
                "cancellationReason": "Attending office instead"
            },
            {
                "employeeNumber": "FB-104",
                "employeeName": "Dan Rejected",
                "fromDate": "2026-09-10T00:00:00Z",
                "toDate": "2026-09-12T00:00:00Z",
                "status": 3  # Rejected -> MUST BE IGNORED
            },
            {
                "employeeNumber": "FB-105",
                "employeeName": "Fred Revoked",
                "fromDate": "2026-09-10T00:00:00Z",
                "toDate": "2026-09-12T00:00:00Z",
                "status": 5  # Revoked -> MUST BE IGNORED
            }
        ]
    }

    mock_od = {
        "totalPages": 1,
        "data": [
            {
                "employeeNumber": "FB-102",
                "employeeName": "Bob Manager",
                "fromDate": "2026-09-15T00:00:00Z",
                "toDate": "2026-09-15T00:00:00Z",
                "status": 2  # Approved
            },
            {
                "employeeNumber": "FB-106",
                "employeeName": "Gina Cancelled OD",
                "fromDate": "2026-09-15T00:00:00Z",
                "toDate": "2026-09-15T00:00:00Z",
                "status": 4  # Cancelled OD -> MUST BE IGNORED
            }
        ]
    }

    def mock_get(url, **kwargs):
        res = MagicMock()
        res.status_code = 200
        if "/time/wfh" in url:
            res.json.return_value = mock_wfh
        elif "/time/od" in url:
            res.json.return_value = mock_od
        else:
            res.json.return_value = {"totalPages": 1, "data": []}
        return res

    monkeypatch.setattr("requests.get", mock_get)

    fetcher = KekaDataFetcher(subdomain="finbox", api_key="test_token")
    df_wfh, err = fetcher.fetch_od_wfh_requests(from_date="2026-09-01", to_date="2026-09-30")

    assert err is None
    # Cancelled (4), Rejected (3), and Revoked (5) records MUST be ignored
    assert len(df_wfh) == 2

    # Check required columns for absent_management.py
    required_cols = ["Employee Number", "From Date", "To Date", "Request Status", "Request Type"]
    for col in required_cols:
        assert col in df_wfh.columns, f"Missing required column: {col}"

    # Status mapping check
    wfh_row = df_wfh[df_wfh["Request Type"] == "WFH"].iloc[0]
    assert wfh_row["Request Status"] == "Pending"
    assert wfh_row["Employee Number"] == "FB-101"

    od_row = df_wfh[df_wfh["Request Type"] == "OD"].iloc[0]
    assert od_row["Request Status"] == "Approved"
    assert od_row["Employee Number"] == "FB-102"

    # Ensure cancelled employees are NOT in df_wfh
    assert "FB-103" not in df_wfh["Employee Number"].values
    assert "FB-104" not in df_wfh["Employee Number"].values
    assert "FB-105" not in df_wfh["Employee Number"].values
    assert "FB-106" not in df_wfh["Employee Number"].values



# ------------------------------------------------------------------------------
# Test 5: End-to-end integration with absent_management.process_absent_management
# ------------------------------------------------------------------------------
def test_absent_management_pipeline_with_fetched_reports(tmp_path, monkeypatch):
    """
    Simulates fetching Employee Master & OD/WFH via API, pairing with a manual
    Attendance report export, and processing through absent_management engine.
    """
    # 1. Create mock employee master Excel with LWD
    emp_data = pd.DataFrame([
        {
            "Employee Number": "1001",
            "Employee Name": "Charlie Brown",
            "Work Email": "charlie@finbox.in",
            "Reporting Manager": "Alice Manager",
            "Reporting Manager Email": "alice@finbox.in",
            "Last Working Day": "2026-10-31",
            "Location": "Delhi"
        }
    ])
    emp_file = tmp_path / "Employee_Master.xlsx"
    emp_data.to_excel(str(emp_file), index=False)

    # 2. Create mock OD/WFH Excel (including a Cancelled request on 06-09-2026)
    wfh_data = pd.DataFrame([
        {
            "Employee Number": "1001",
            "Employee Name": "Charlie Brown",
            "From Date": "05-09-2026",
            "To Date": "05-09-2026",
            "Request Status": "Pending",
            "Request Type": "WFH"
        },
        {
            "Employee Number": "1001",
            "Employee Name": "Charlie Brown",
            "From Date": "06-09-2026",
            "To Date": "06-09-2026",
            "Request Status": "Cancelled",
            "Request Type": "WFH"
        }
    ])
    wfh_file = tmp_path / "OD_WFH_Requests.xlsx"
    wfh_data.to_excel(str(wfh_file), index=False)

    # 3. Create mock Attendance report Excel (with Status codes like in portal export)
    att_data = pd.DataFrame([
        {
            "Employee Number": "1001",
            "Employee Name": "Charlie Brown",
            "Date": "05-09-2026",
            "Status": "A",
            "Shift": "General",
            "In Time": "",
            "Out Time": ""
        },
        {
            "Employee Number": "1001",
            "Employee Name": "Charlie Brown",
            "Date": "06-09-2026",
            "Status": "A",
            "Shift": "General",
            "In Time": "",
            "Out Time": ""
        },
        {
            "Employee Number": "1001",
            "Employee Name": "Charlie Brown",
            "Date": "07-09-2026",
            "Status": "P",
            "Shift": "General",
            "In Time": "09:30",
            "Out Time": "18:30"
        }
    ])
    att_file = tmp_path / "Attendance_Report.xlsx"
    att_data.to_excel(str(att_file), index=False)

    # 4. Run absent_management.process_absent_management
    output_file = tmp_path / "Absent_Output.xlsx"
    absent_management.process_absent_management(
        str(emp_file),
        str(att_file),
        str(wfh_file),
        str(output_file)
    )

    assert output_file.exists()

    # Read and verify sheets
    working_df = pd.read_excel(str(output_file), sheet_name="Working")
    mailer_df = pd.read_excel(str(output_file), sheet_name="Mailer")

    assert len(working_df) == 3
    assert len(mailer_df) == 3

    # On 05-Sep-26, WFH was Pending -> WFH Applied should be 'Yes', Quantity 1.0 (no quantity 0)
    row_05 = working_df[working_df["Date"] == "05-Sep-26"].iloc[0]
    assert row_05["WFH Applied"] == "Yes"
    assert row_05["Quantity"] == 1.0

    # On 06-Sep-26, Status is 'A' without WFH -> Quantity 1.0
    row_06 = working_df[working_df["Date"] == "06-Sep-26"].iloc[0]
    assert row_06["WFH Applied"] == "No"
    assert row_06["Quantity"] == 1.0

    # Last Working Day check on both Working and Mailer (formatted as DD-MMM-YY: 31-Oct-26)
    assert "Last Working Day" in working_df.columns
    assert "Last Working Day" in mailer_df.columns
    assert working_df.loc[0, "Last Working Day"] == "31-Oct-26"
    assert mailer_df.loc[0, "Last Working Day"] == "31-Oct-26"
    # Ensure duplicate 'LWD' column is removed from working sheet
    assert "LWD" not in working_df.columns

    # Mailer sheet checks
    assert "Employee Mail ID" in mailer_df.columns
    assert "RM Mail ID" in mailer_df.columns
    assert mailer_df.loc[0, "Employee Mail ID"] == "charlie@finbox.in"
    assert mailer_df.loc[0, "Reporting Manager"] == "Alice Manager"
    assert mailer_df.loc[0, "Month"] == "01-Sep-26"

    # Verify Header styling: bold font with #00FF99 fill and no borders
    import openpyxl
    wb = openpyxl.load_workbook(str(output_file))
    for sname in ["Working", "Mailer"]:
        ws = wb[sname]
        for cell in ws[1]:
            assert cell.font.bold is True
            assert cell.fill.start_color.rgb in ("0000FF99", "00FF99")


# ------------------------------------------------------------------------------
# Test 6: format_hours_hhmm and format_punch_time helpers
# ------------------------------------------------------------------------------
def test_format_helpers():
    assert kdf.KekaDataFetcher._format_hours_hhmm(4.11) == "04:07"
    assert kdf.KekaDataFetcher._format_hours_hhmm(0.0) == "00:00"
    assert kdf.KekaDataFetcher._format_hours_hhmm(10.5) == "10:30"
    assert kdf.KekaDataFetcher._format_hours_hhmm(None) == "00:00"

    punch = {"timestamp": "2026-09-01T06:37:21Z"}
    assert kdf.KekaDataFetcher._format_punch_time(punch) == "12:07"
    assert kdf.KekaDataFetcher._format_punch_time(None) == ""


# ------------------------------------------------------------------------------
# Test 7: fetch_attendance_records_api with full 24-column synthesis
# ------------------------------------------------------------------------------
def test_fetch_attendance_records_api_mock(monkeypatch):
    mock_att = {
        "totalPages": 1,
        "data": [
            {
                "employeeNumber": "EMP-01",
                "attendanceDate": "2026-09-01T00:00:00Z",
                "dayType": 0,
                "totalGrossHours": 9.0,
                "totalEffectiveHours": 8.5,
                "totalBreakDuration": 0.5,
                "firstInOfTheDay": {"timestamp": "2026-09-01T04:00:00Z"},
                "lastOutOfTheDay": {"timestamp": "2026-09-01T13:00:00Z"}
            },
            {
                "employeeNumber": "EMP-01",
                "attendanceDate": "2026-09-02T00:00:00Z",
                "dayType": 0,
                "totalGrossHours": 0.0,
                "totalEffectiveHours": 0.0,
                "totalBreakDuration": 0.0,
                "firstInOfTheDay": None,
                "lastOutOfTheDay": None
            },
            {
                "employeeNumber": "EMP-01",
                "attendanceDate": "2026-09-06T00:00:00Z",
                "dayType": 2,
                "totalGrossHours": 0.0,
                "totalEffectiveHours": 0.0,
                "totalBreakDuration": 0.0,
                "firstInOfTheDay": None,
                "lastOutOfTheDay": None
            }
        ]
    }

    mock_leaves = {
        "totalPages": 1,
        "data": [
            {
                "employeeNumber": "EMP-01",
                "fromDate": "2026-09-03T00:00:00Z",
                "toDate": "2026-09-03T00:00:00Z",
                "status": 1,
                "selection": [{"leaveTypeName": "Sick Leave", "count": 1.0}]
            }
        ]
    }

    def mock_get(url, **kwargs):
        res = MagicMock()
        res.status_code = 200
        if "/time/attendance" in url:
            res.json.return_value = mock_att
        elif "/time/leaverequests" in url:
            res.json.return_value = mock_leaves
        else:
            res.json.return_value = {"totalPages": 1, "data": []}
        return res

    monkeypatch.setattr("requests.get", mock_get)

    fetcher = KekaDataFetcher(subdomain="finbox", api_key="dummy_token")
    emp_df = pd.DataFrame([{"Employee Number": "EMP-01", "Employee Name": "Alice Tester", "Department": "QA"}])
    df_perf, err = fetcher.fetch_attendance_records_api(
        from_date="2026-09-01",
        to_date="2026-09-06",
        emp_df=emp_df
    )

    assert err is None
    assert len(df_perf) == 3

    # Check that required Daily Performance columns exist
    required_cols = [
        "Employee Number", "Employee Name", "Date", "Status", "Attendance Type",
        "Effective Hours", "Total Hours", "Break Duration", "Quantity"
    ]
    for col in required_cols:
        assert col in df_perf.columns

    # Row 1: Working day with 8.5 hours -> Present, Quantity 1.0 (no quantity 0)
    row1 = df_perf[df_perf["Date"] == "2026-09-01"].iloc[0]
    assert row1["Status"] == "P"
    assert row1["Attendance Type"] == "Present"
    assert row1["Effective Hours"] == "08:30"
    assert row1["Quantity"] == 1.0

    # Row 2: Working day with 0 hours and no punch -> Absent
    row2 = df_perf[df_perf["Date"] == "2026-09-02"].iloc[0]
    assert row2["Status"] == "A"
    assert row2["Attendance Type"] == "Absent"
    assert row2["Quantity"] == 1.0

    # Row 3: dayType 2 -> Week Off, Quantity 1.0 (no quantity 0)
    row3 = df_perf[df_perf["Date"] == "2026-09-06"].iloc[0]
    assert row3["Status"] == "WO"
    assert row3["Attendance Type"] == "Week Off"
    assert row3["Quantity"] == 1.0


# ------------------------------------------------------------------------------
# Test 8: Cancelled WFH/OD/Leaves MUST be ignored in Daily Performance Report
# ------------------------------------------------------------------------------
def test_cancelled_requests_ignored_in_daily_performance(monkeypatch):
    """
    Validates that:
    1. If a leave request is Cancelled (status 3), it does NOT mark the date as CLSL.
    2. If a WFH request is Cancelled, it does NOT mark the date as WFH.
    3. The employee's actual attendance (Absent A, Present P) is preserved.
    """
    mock_att = {
        "totalPages": 1,
        "data": [
            {
                "employeeNumber": "EMP-99",
                "attendanceDate": "2026-09-02T00:00:00Z",
                "dayType": 0,
                "totalGrossHours": 0.0,
                "totalEffectiveHours": 0.0,
                "totalBreakDuration": 0.0,
                "firstInOfTheDay": None,
                "lastOutOfTheDay": None
            },
            {
                "employeeNumber": "EMP-99",
                "attendanceDate": "2026-09-03T00:00:00Z",
                "dayType": 0,
                "totalGrossHours": 8.5,
                "totalEffectiveHours": 8.0,
                "totalBreakDuration": 0.5,
                "firstInOfTheDay": {"timestamp": "2026-09-03T04:00:00Z"},
                "lastOutOfTheDay": {"timestamp": "2026-09-03T12:30:00Z"}
            }
        ]
    }

    mock_leaves = {
        "totalPages": 1,
        "data": [
            {
                "employeeNumber": "EMP-99",
                "fromDate": "2026-09-02T00:00:00Z",
                "toDate": "2026-09-02T00:00:00Z",
                "status": 3,  # Cancelled Leave
                "cancellationReason": "User cancelled",
                "selection": [{"leaveTypeName": "Casual Leave", "count": 1.0}]
            }
        ]
    }

    # Cancelled WFH dataframe
    wfh_df = pd.DataFrame([
        {
            "Employee Number": "EMP-99",
            "Employee Name": "Test Employee",
            "From Date": "02-09-2026",
            "To Date": "03-09-2026",
            "Request Status": "Cancelled",
            "Request Type": "WFH"
        }
    ])

    def mock_get(url, **kwargs):
        res = MagicMock()
        res.status_code = 200
        if "/time/attendance" in url:
            res.json.return_value = mock_att
        elif "/time/leaverequests" in url:
            res.json.return_value = mock_leaves
        else:
            res.json.return_value = {"totalPages": 1, "data": []}
        return res

    monkeypatch.setattr("requests.get", mock_get)

    fetcher = KekaDataFetcher(subdomain="finbox", api_key="dummy_token")
    emp_df = pd.DataFrame([{"Employee Number": "EMP-99", "Employee Name": "Test Employee", "Department": "Eng"}])

    df_perf, err = fetcher.fetch_attendance_records_api(
        from_date="2026-09-02",
        to_date="2026-09-03",
        emp_df=emp_df,
        wfh_df=wfh_df
    )

    assert err is None
    assert len(df_perf) == 2

    # On 2026-09-02: Leave was Cancelled, WFH was Cancelled, 0 punches -> MUST BE ABSENT (A), Quantity 1.0
    row_02 = df_perf[df_perf["Date"] == "2026-09-02"].iloc[0]
    assert row_02["Status"] == "A", f"Expected 'A' but got '{row_02['Status']}'"
    assert row_02["Attendance Type"] == "Absent"
    assert row_02["Quantity"] == 1.0

    # On 2026-09-03: WFH was Cancelled, worked 8.0 hours -> MUST BE PRESENT (P), Quantity 1.0 (no quantity 0)
    row_03 = df_perf[df_perf["Date"] == "2026-09-03"].iloc[0]
    assert row_03["Status"] == "P", f"Expected 'P' but got '{row_03['Status']}'"
    assert row_03["Attendance Type"] == "Present"
    assert row_03["Quantity"] == 1.0

    # Also verify fetch_leave_requests filters out cancelled leaves
    leaves, l_err = fetcher.fetch_leave_requests(from_date="2026-09-01", to_date="2026-09-05")
    assert l_err is None
    assert len(leaves) == 0, "Cancelled leaves should be filtered out by fetch_leave_requests"


def test_fetch_wfh_half_day_split_and_quantity_half(monkeypatch):
    """Verify that half-day WFH requests split into two line items with 0.5 quantity each."""
    mock_att = {
        "totalPages": 1,
        "data": [
            {
                "employeeNumber": "EMP-WFH",
                "attendanceDate": "2026-09-04T00:00:00Z",
                "totalWorkDurationInSeconds": 14400,  # 4 hours
                "originalDayType": 0,
                "firstIn": "2026-09-04T09:00:00Z",
                "lastOut": "2026-09-04T13:00:00Z",
            }
        ]
    }
    wfh_df = pd.DataFrame([
        {
            "Employee Number": "EMP-WFH",
            "From Date": "2026-09-04",
            "To Date": "2026-09-04",
            "Duration": 0.5,
            "Session": "Session 2",
            "Request Status": "Approved",
            "Approval Status": "Approved",
            "Request Type": "WFH",
            "Requested On": "2026-09-01",
            "Action Taken On": "2026-09-02",
        }
    ])

    def mock_get(url, **kwargs):
        res = MagicMock()
        res.status_code = 200
        if "/time/attendance" in url:
            res.json.return_value = mock_att
        else:
            res.json.return_value = {"totalPages": 1, "data": []}
        return res

    monkeypatch.setattr("requests.get", mock_get)

    fetcher = KekaDataFetcher(subdomain="finbox", api_key="dummy_token")
    emp_df = pd.DataFrame([{"Employee Number": "EMP-WFH", "Employee Name": "WFH Worker"}])

    df_perf, err = fetcher.fetch_attendance_records_api(
        from_date="2026-09-04",
        to_date="2026-09-04",
        emp_df=emp_df,
        wfh_df=wfh_df
    )

    assert err is None
    # Must be split into two 0.5 entries (WFH + Present)
    assert len(df_perf) == 2
    for _, row in df_perf.iterrows():
        assert row["Quantity"] == 0.5
        assert row["Quantity"] != 0.0

    types = set(df_perf["Attendance Type"])
    assert "Work From Home" in types
    assert "Present" in types


def test_post_lwd_records_dropped_in_fetch_attendance_records_api(monkeypatch):
    """Verify that attendance dates after Last Working Day are omitted from API fetch results."""
    mock_att = {
        "totalPages": 1,
        "data": [
            {
                "employeeNumber": "EMP-RESIGNED",
                "attendanceDate": "2026-09-05T00:00:00Z",
                "totalWorkDurationInSeconds": 0,
                "originalDayType": 0,
            }
        ]
    }

    def mock_get(url, **kwargs):
        res = MagicMock()
        res.status_code = 200
        if "/time/attendance" in url:
            res.json.return_value = mock_att
        else:
            res.json.return_value = {"totalPages": 1, "data": []}
        return res

    monkeypatch.setattr("requests.get", mock_get)

    fetcher = KekaDataFetcher(subdomain="finbox", api_key="dummy_token")
    # Employee resigned on 2026-08-31
    emp_df = pd.DataFrame([{
        "Employee Number": "EMP-RESIGNED",
        "Employee Name": "Old Worker",
        "Last Working Day": "2026-08-31"
    }])

    df_perf, err = fetcher.fetch_attendance_records_api(
        from_date="2026-09-01",
        to_date="2026-09-10",
        emp_df=emp_df
    )

    assert err is None
    # Attendance for 2026-09-05 must be completely filtered out
    assert len(df_perf) == 0


