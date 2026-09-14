"""
workforce.py
────────────
Workforce Intelligence API endpoints: file upload, summary metrics, and filter retrieval.
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
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


@router.post("/workforce/upload")
async def upload_dataset(file: UploadFile = File(...)):
    """
    Upload and ingest an Excel or CSV workforce dataset.
    Processes data non-destructively through the analytical engine,
    caches the analysis session in memory, and immediately removes the temporary file.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing.")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Expected an Excel (.xlsx, .xls) or CSV (.csv) file.",
        )

    # Write temporarily for pandas reader
    temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        with os.fdopen(temp_fd, "wb") as f:
            f.write(content)

        # Process through workforce_intelligence engine
        summary = SESSION.load_dataset(temp_path, filename=file.filename)
        return summary

    except MissingRequiredColumnsError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Dataset is missing required canonical columns: {', '.join(e.missing_columns)}",
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to process file '{file.filename}': {str(e)}",
        )
    finally:
        # Guarantee no persistent storage of raw customer files
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
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
