"""
workforce_intelligence
──────────────────────
Workforce Intelligence Data Foundation package.
Provides ingestion, schema validation, data normalization, and quality reporting
for employee attendance, leave, and WFH records.
"""

from workforce_intelligence.ingestion import load_workforce_data
from workforce_intelligence.quality import DataQualityReport, QualityFinding
from workforce_intelligence.metrics import (
    build_employee_day_facts,
    calculate_compliance_breakdown,
    calculate_core_metrics,
)
from workforce_intelligence.policy import evaluate_policy
from workforce_intelligence.policy_config import PolicyConfig
from workforce_intelligence.requests import LeaveRequest, build_leave_requests
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

from workforce_intelligence.trends import (
    TREND_METRICS,
    TrendMetricDefinition,
    calculate_time_series_trends,
    get_trend_metric_catalogue,
)
from workforce_intelligence.patterns import (
    PATTERN_DEFINITIONS,
    PatternCategory,
    PatternContext,
    PatternEvidenceItem,
    PatternPersistence,
    PatternResult,
    PatternSeverity,
    PatternStatus,
    PatternStrength,
    PatternSummary,
    detect_patterns,
)

__all__ = [
    "load_workforce_data",
    "evaluate_policy",
    "build_leave_requests",
    "build_employee_day_facts",
    "calculate_core_metrics",
    "calculate_compliance_breakdown",
    "calculate_time_series_trends",
    "get_trend_metric_catalogue",
    "detect_patterns",
    "PatternContext",
    "PatternResult",
    "PatternSummary",
    "PatternEvidenceItem",
    "PATTERN_DEFINITIONS",
    "PatternCategory",
    "PatternSeverity",
    "PatternStrength",
    "PatternPersistence",
    "PatternStatus",
    "TREND_METRICS",
    "TrendMetricDefinition",
    "PolicyConfig",
    "LeaveRequest",
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
