"""
ingestion
─────────
Transformers 2.0 Ingestion & Pre-processing Package.
Exposes ingestion workflows for KRA Management, OKR Upload, Absenteeism, and Attendance Summaries.
"""

from generate_upload import (
    generate_upload_file,
    generate_okr_upload_file,
    normalize_okr_weightage,
)
from absent_management import process_absent_management
from attendance_summary import process_attendance_summary

__all__ = [
    "generate_upload_file",
    "generate_okr_upload_file",
    "normalize_okr_weightage",
    "process_absent_management",
    "process_attendance_summary",
]
