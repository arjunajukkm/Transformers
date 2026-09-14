"""
workforce.py
────────────
Workforce Intelligence API endpoints: file upload, summary metrics,
filter retrieval, and monthly time-series trend intelligence.
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from workforce_app.backend.services.analysis_service import SESSION
from workforce_intelligence.validation import MissingRequiredColumnsError, ValidationError

router = APIRouter()


class FilterRequest(BaseModel):
    business_unit: Optional[str] = None
    department: Optional[str] = None
    sub_department: Optional[str] = None
    location: Optional[str] = None
    reporting_manager: Optional[str] = None


class TrendFilterRequest(BaseModel):
    metric: str = "attendance_exception_rate"
    business_unit: Optional[str] = None
    department: Optional[str] = None
    sub_department: Optional[str] = None
    location: Optional[str] = None
    reporting_manager: Optional[str] = None
    employee_number: Optional[str] = None


@router.post("/workforce/upload")
async def upload_dataset(
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
):
    """
    Upload and ingest one or multiple Excel (.xlsx, .xls) or CSV (.csv) workforce reports.
    Processes data non-destructively through the analytical engine,
    preserves source file traceability and origin, detects cross-file exact duplicates,
    caches the analysis session in memory, and immediately removes temporary files.
    """
    uploaded_files: List[UploadFile] = []
    if files:
        uploaded_files.extend(files)
    if file:
        uploaded_files.append(file)

    if not uploaded_files:
        raise HTTPException(status_code=400, detail="No file(s) provided in upload request.")

    temp_paths: List[str] = []
    filenames: List[str] = []

    try:
        for uf in uploaded_files:
            if not uf.filename:
                raise HTTPException(status_code=400, detail="Uploaded file missing filename.")

            ext = Path(uf.filename).suffix.lower()
            if ext not in (".xlsx", ".xls", ".csv"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file format '{ext}' for file '{uf.filename}'. Expected .xlsx, .xls, or .csv",
                )

            temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
            temp_paths.append(temp_path)
            filenames.append(uf.filename)

            content = await uf.read()
            if len(content) == 0:
                raise HTTPException(status_code=400, detail=f"Uploaded file '{uf.filename}' is empty.")

            with os.fdopen(temp_fd, "wb") as f:
                f.write(content)

        # Multi-file or single-file combined display name
        if len(filenames) == 1:
            combined_display_name = filenames[0]
            input_paths: Union[str, List[str]] = temp_paths[0]
        else:
            combined_display_name = f"{len(filenames)} files ({', '.join(filenames[:3])}{'...' if len(filenames) > 3 else ''})"
            input_paths = temp_paths

        # Process through workforce_intelligence engine
        summary = SESSION.load_dataset(input_paths, filename=combined_display_name, file_names=filenames)
        return summary

    except HTTPException:
        raise
    except MissingRequiredColumnsError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Dataset is missing required canonical columns: {', '.join(e.missing_columns)}",
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        target_name = filenames[-1] if filenames else "uploaded file"
        raise HTTPException(
            status_code=400,
            detail=f"Unable to process '{target_name}': {str(e)}",
        )
    finally:
        # Guarantee no persistent storage of raw customer files on disk
        for tp in temp_paths:
            try:
                if os.path.exists(tp):
                    os.unlink(tp)
            except OSError:
                pass


@router.get("/workforce/summary")
def get_summary(
    business_unit: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    sub_department: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    reporting_manager: Optional[str] = Query(None),
):
    """
    Return leadership summary metrics and insights for the active session.
    Dynamically recalculates all KPIs when filters are applied.
    """
    filters = {}
    if business_unit:
        filters["business_unit"] = business_unit
    if department:
        filters["department"] = department
    if sub_department:
        filters["sub_department"] = sub_department
    if location:
        filters["location"] = location
    if reporting_manager:
        filters["reporting_manager"] = reporting_manager

    return SESSION.get_summary(filters=filters if filters else None)


@router.post("/workforce/summary")
def post_summary(filter_req: FilterRequest):
    """Filter summary endpoint accepting JSON payload."""
    filters = filter_req.dict(exclude_none=True)
    return SESSION.get_summary(filters=filters if filters else None)


@router.get("/workforce/filters")
def get_filters():
    """Return available categorical filter values for active dataset."""
    return SESSION.get_available_filters()


@router.get("/workforce/trends")
def get_trends(
    metric: str = Query("attendance_exception_rate"),
    business_unit: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    sub_department: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    reporting_manager: Optional[str] = Query(None),
    employee_number: Optional[str] = Query(None),
):
    """
    Return monthly time-series trend intelligence for a specific metric.
    Dynamically recalculates points, MoM changes, streak, and direction
    from the filtered population.
    """
    filters = {}
    if business_unit:
        filters["business_unit"] = business_unit
    if department:
        filters["department"] = department
    if sub_department:
        filters["sub_department"] = sub_department
    if location:
        filters["location"] = location
    if reporting_manager:
        filters["reporting_manager"] = reporting_manager
    if employee_number:
        filters["employee_number"] = employee_number

    try:
        return SESSION.get_trends(metric=metric, filters=filters if filters else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/workforce/trends")
def post_trends(trend_req: TrendFilterRequest):
    """POST endpoint for trends with filter payload."""
    filters = trend_req.dict(exclude={"metric"}, exclude_none=True)
    try:
        return SESSION.get_trends(metric=trend_req.metric, filters=filters if filters else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workforce/trends/metrics")
def get_trend_metrics():
    """Return the centralized trend metric catalogue grouped by category."""
    return SESSION.get_trend_metrics()


class PatternFilterRequest(BaseModel):
    category: Optional[str] = None
    pattern_type: Optional[str] = None
    entity_type: Optional[str] = None
    strength: Optional[str] = None
    status: Optional[str] = None
    business_unit: Optional[str] = None
    department: Optional[str] = None
    sub_department: Optional[str] = None
    location: Optional[str] = None
    reporting_manager: Optional[str] = None
    employee_number: Optional[str] = None


@router.get("/workforce/patterns")
def get_patterns(
    category: Optional[str] = Query(None),
    pattern_type: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    strength: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    business_unit: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    sub_department: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    reporting_manager: Optional[str] = Query(None),
    employee_number: Optional[str] = Query(None),
):
    """
    Return detected behavioral and process patterns for the active session.
    Dynamically re-evaluates patterns when population or attribute filters are applied.
    """
    dim_filters = {}
    if business_unit:
        dim_filters["business_unit"] = business_unit
    if department:
        dim_filters["department"] = department
    if sub_department:
        dim_filters["sub_department"] = sub_department
    if location:
        dim_filters["location"] = location
    if reporting_manager:
        dim_filters["reporting_manager"] = reporting_manager
    if employee_number:
        dim_filters["employee_number"] = employee_number

    return SESSION.get_patterns(
        filters=dim_filters if dim_filters else None,
        category=category,
        pattern_type=pattern_type,
        entity_type=entity_type,
        strength=strength,
        status=status,
        employee_number=employee_number,
        reporting_manager=reporting_manager,
    )


@router.post("/workforce/patterns")
def post_patterns(filter_req: PatternFilterRequest):
    """Filter patterns endpoint accepting JSON payload."""
    data = filter_req.dict(exclude_none=True)
    dim_keys = {"business_unit", "department", "sub_department", "location", "reporting_manager", "employee_number"}
    dim_filters = {k: v for k, v in data.items() if k in dim_keys}

    return SESSION.get_patterns(
        filters=dim_filters if dim_filters else None,
        category=data.get("category"),
        pattern_type=data.get("pattern_type"),
        entity_type=data.get("entity_type"),
        strength=data.get("strength"),
        status=data.get("status"),
        employee_number=data.get("employee_number"),
        reporting_manager=data.get("reporting_manager"),
    )


@router.get("/workforce/patterns/catalogue")
def get_pattern_catalogue():
    """Return central pattern definitions catalogue grouped by category."""
    return SESSION.get_pattern_catalogue()


@router.get("/workforce/patterns/{pattern_id}")
def get_pattern_detail(pattern_id: str):
    """Return detailed evidence and timeline records for a specific pattern ID."""
    res = SESSION.get_pattern_by_id(pattern_id)
    if res is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found.")
    return res

