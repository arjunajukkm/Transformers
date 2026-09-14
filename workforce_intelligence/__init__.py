"""
workforce_intelligence
──────────────────────
Workforce Intelligence Data Foundation package.
Provides ingestion, schema validation, data normalization, and quality reporting
for employee attendance, leave, and WFH records.
"""

from workforce_intelligence.ingestion import load_workforce_data
from workforce_intelligence.quality import DataQualityReport, QualityFinding
from workforce_intelligence.schema import (
    CANONICAL_COLUMNS,
    CORE_COLUMNS,
    DQ_FLAGS,
    EMPLOYEE_DIMENSIONS,
    EVENT_DIMENSIONS,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
)
from workforce_intelligence.validation import (
    MissingRequiredColumnsError,
    ValidationError,
)

__all__ = [
    "load_workforce_data",
    "DataQualityReport",
    "QualityFinding",
    "CANONICAL_COLUMNS",
    "CORE_COLUMNS",
    "REQUIRED_COLUMNS",
    "OPTIONAL_COLUMNS",
    "EMPLOYEE_DIMENSIONS",
    "EVENT_DIMENSIONS",
    "DQ_FLAGS",
    "MissingRequiredColumnsError",
    "ValidationError",
]
