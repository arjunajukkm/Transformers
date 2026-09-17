"""
tests/test_time_series_analysis.py
──────────────────────────────────
Unit tests for time_series_analysis module.
"""

from datetime import date, datetime
from pathlib import Path
import pandas as pd
import pytest

import time_series_analysis as tsa


def test_time_parsing_and_formatting():
    assert tsa.parse_time_to_minutes("09:30") == 570
    assert tsa.parse_time_to_minutes("09:30:00") == 570
    assert tsa.parse_time_to_minutes("09:30 AM") == 570
    assert tsa.parse_time_to_minutes("09:30 PM") == 1290
    assert tsa.parse_time_to_minutes("NA") is None
    assert tsa.parse_time_to_minutes(None) is None

    assert tsa.minutes_to_time_str(570, use_12hr=True) == "09:30 AM"
    assert tsa.minutes_to_time_str(1290, use_12hr=True) == "09:30 PM"
    assert tsa.minutes_to_time_str(None) == "-"

    assert tsa.hours_to_duration_str(8.5) == "8h 30m"
    assert tsa.hours_to_duration_str(None) == "-"


def test_date_parsing():
    assert tsa.parse_date_value("2026-09-01") == date(2026, 9, 1)
    assert tsa.parse_date_value("01-09-2026") == date(2026, 9, 1)
    assert tsa.parse_date_value("NA") is None
    assert tsa.parse_date_value(None) is None


@pytest.fixture
def sample_dataset(tmp_path):
    rows = [
        # Emp 1: Present, valid swipes
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-01",
            "Month": "Sep 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "In Time": "09:00",
            "Out Time": "18:00",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        # Emp 1: Missing Swipes
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-02",
            "Month": "Sep 2026",
            "Attendance Type": "Missing Swipes",
            "Status": "P(MS)",
            "In Time": "10:00",
            "Out Time": "18:30",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        # Emp 1: Leave applied 2 days late by Employee, approved by Manager in 1 day
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-03",
            "Month": "Sep 2026",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "In Time": "NA",
            "Out Time": "NA",
            "Applied By": "Employee",
            "Applied On": "2026-09-01",  # 2 days in advance (Sep 3 - Sep 1 = 2)
            "Approved By": "Manager",
            "Approved On": "2026-09-02", # 1 day to approve
        },
        # Emp 2: Regularized attendance
        {
            "Employee Number": "E002",
            "Employee Name": "Charlie",
            "Business Unit": "Sales",
            "Department": "Direct Sales",
            "Reporting Manager": "David RM",
            "Date": "2026-09-01",
            "Month": "Sep 2026",
            "Attendance Type": "Regularized",
            "Status": "AR",
            "In Time": "09:30",
            "Out Time": "18:30",
            "Applied By": "Employee",
            "Applied On": "2026-09-01",
            "Approved By": "Manager",
            "Approved On": "2026-09-02",
        },
        # Emp 2: WFH 4 days to test >3 days exception
        *[
            {
                "Employee Number": "E002",
                "Employee Name": "Charlie",
                "Business Unit": "Sales",
                "Department": "Direct Sales",
                "Reporting Manager": "David RM",
                "Date": f"2026-09-0{d}",
                "Month": "Sep 2026",
                "Attendance Type": "Work From Home",
                "Status": "WFH",
                "In Time": "NA",
                "Out Time": "NA",
                "Applied By": "Employee",
                "Applied On": f"2026-09-0{d}",
                "Approved By": "Manager",
                "Approved On": f"2026-09-0{d}",
            }
            for d in range(2, 6) # 4 days
        ]
    ]
    df = pd.DataFrame(rows)
    p = tmp_path / "test_perf.xlsx"
    df.to_excel(p, index=False)
    return p


def test_metrics_calculation(sample_dataset):
    df = tsa.load_time_series_dataset(sample_dataset)
    assert len(df) == 8

    metrics = tsa.compute_time_series_metrics(df)
    assert metrics["total_records"] == 8
    assert metrics["unique_employees"] == 2

    # Leave compliance
    assert metrics["total_leaves_applied"] == 1
    assert metrics["applied_by_emp_cnt"] == 1
    assert metrics["applied_by_emp_pct"] == 100.0
    assert metrics["avg_leave_apply_days"] == 2.0  # Sep 5 - Sep 3 = 2 days

    # Approval compliance
    # 1 leave (1 day to approve) + 4 WFH (0 days) = total 5 requests, avg = 1/5 = 0.2
    assert metrics["total_approvals"] == 5
    assert metrics["appr_mgr_cnt"] == 5
    assert metrics["appr_mgr_pct"] == 100.0

    # Attendance Exception (Regularized)
    assert metrics["regularized_days"] == 1

    # WFH Exception (4 days availed, 4 - 3 = 1 excess day)
    assert metrics["total_wfh_days"] == 4
    assert metrics["wfh_excess_days"] == 1
    assert metrics["wfh_violating_emp_count"] == 1
    assert metrics["wfh_exception_rate_pct"] == 25.0

    # Average Swipes & Working Hours (Alice: 9h and 8.5h -> avg 8.75h)
    assert metrics["avg_in_time"] == "09:30 AM"
    assert metrics["avg_out_time"] == "06:15 PM"
    assert metrics["avg_working_hours"] == "8h 45m"


def test_level_breakdown(sample_dataset):
    df = tsa.load_time_series_dataset(sample_dataset)

    bu_breakdown = tsa.compute_level_breakdown(df, "Business Unit")
    assert len(bu_breakdown) == 2
    bu_names = {b["Entity Name"] for b in bu_breakdown}
    assert "Engineering" in bu_names
    assert "Sales" in bu_names

    emp_breakdown = tsa.compute_level_breakdown(df, "Employee")
    assert len(emp_breakdown) == 2


def test_filters(sample_dataset):
    df = tsa.load_time_series_dataset(sample_dataset)

    # Filter by BU
    eng_metrics = tsa.compute_time_series_metrics(df, business_unit="Engineering")
    assert eng_metrics["total_records"] == 3
    assert eng_metrics["unique_employees"] == 1
    assert eng_metrics["total_wfh_days"] == 0

    sales_metrics = tsa.compute_time_series_metrics(df, business_unit="Sales")
    assert sales_metrics["total_records"] == 5
    assert sales_metrics["unique_employees"] == 1
    assert sales_metrics["total_wfh_days"] == 4


def test_excel_export(sample_dataset, tmp_path):
    df = tsa.load_time_series_dataset(sample_dataset)
    out_file = tmp_path / "time_series_report.xlsx"
    res_path = tsa.export_time_series_report(df, out_file)
    assert res_path.exists()

    # Verify sheets in exported workbook
    xl = pd.ExcelFile(res_path)
    assert "KPI Summary" in xl.sheet_names
    assert "Business Unit" in xl.sheet_names
    assert "Department" in xl.sheet_names
    assert "Reporting Manager" in xl.sheet_names
    assert "Employee Breakdown" in xl.sheet_names
