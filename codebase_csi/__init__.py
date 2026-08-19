"""
AI Code Detector - Production-Ready AI-Generated Code Detection System

A comprehensive tool for detecting, analyzing, and remediating AI-generated code patterns
across multiple programming languages.

Features:
- 5-phase detection methodology
- Enterprise-grade quality gates
- Automated remediation
- CI/CD integration
- Compliance reporting
- Vertical-specific solutions (Healthcare, Finance, Government, etc.)
"""

__version__ = "1.0.0"
__author__ = "AI Code Detector Team"
__license__ = "MIT"

from codebase_csi.core.detector import AICodeDetector
from codebase_csi.core.models import (
    ConfidenceLevel,
    FileAnalysis,
    DetectionResult,
    ProjectAnalysis
)

__all__ = [
    "AICodeDetector",
    "ConfidenceLevel",
    "FileAnalysis",
    "DetectionResult",
    "ProjectAnalysis",
    "__version__"
]
