"""
workforce_intelligence
──────────────────────
Workforce Intelligence Data Foundation package.
Provides ingestion, schema validation, data normalization, and quality reporting
for employee attendance, leave, and WFH records.
"""

from workforce_intelligence.ingestion import load_workforce_data
from workforce_intelligence.quality import DataQualityReport
from workforce_intelligence.schema import (
    CANONICAL_COLUMNS,
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
    "CANONICAL_COLUMNS",
    "REQUIRED_COLUMNS",
    "OPTIONAL_COLUMNS",
    "EMPLOYEE_DIMENSIONS",
    "EVENT_DIMENSIONS",
    "MissingRequiredColumnsError",
    "ValidationError",
]
