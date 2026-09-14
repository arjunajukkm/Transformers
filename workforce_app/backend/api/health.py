"""
health.py
─────────
Health check endpoint for Workforce Intelligence backend API.
"""

from fastapi import APIRouter
from workforce_app.backend.services.analysis_service import SESSION

router = APIRouter()


@router.get("/health")
def get_health():
    """Return health status and basic runtime state."""
    return {
        "status": "healthy",
        "service": "workforce-intelligence-api",
        "version": "1.0.0",
        "dataset_loaded": SESSION.is_loaded,
        "filename": SESSION.filename,
    }
