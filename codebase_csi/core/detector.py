"""
Core Detection Engine - Production Ready

This module implements the main AICodeDetector class that orchestrates
multi-phase analysis of code to detect AI-generated patterns.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
from datetime import datetime
import uuid

from codebase_csi.core.models import (
    FileAnalysis,
    DetectionResult,
    ProjectAnalysis,
    ScanConfiguration,
    ConfidenceLevel,
    DetectionPattern
)
from codebase_csi.utils.logger import get_logger
from codebase_csi.utils.file_utils import FileScanner, LanguageDetector
from codebase_csi.analyzers.emoji_detector import EmojiDetector
from codebase_csi.analyzers.pattern_analyzer import PatternAnalyzer
from codebase_csi.analyzers.statistical_analyzer import StatisticalAnalyzer
from codebase_csi.analyzers.security_analyzer import SecurityAnalyzer
from codebase_csi.analyzers.mock_detector import MockCodeDetector


logger = get_logger(__name__)


class AICodeDetector:
    """
    Production-ready AI code detection engine.
    
    Features:
    - Multi-phase analysis pipeline (5 phases)
    - Pluggable analyzer architecture
    - Configurable thresholds and quality gates
    - Comprehensive logging and error handling
    - Performance optimization with caching
    
    Example:
        >>> from codebase_csi import AICodeDetector
        >>> detector = AICodeDetector()
        >>> result = detector.scan_directory("/path/to/code")
        >>> print(f"Found {result.ai_file_count} AI-generated files")
    """
    
    def __init__(self, config: Optional[ScanConfiguration] = None):
        """
        Initialize the detector with configuration.
        
        Args:
            config: Scan configuration. If None, uses defaults.
        """
        self.config = config or ScanConfiguration()
        self.analyzers: Dict[str, any] = {}
        self.file_scanner = FileScanner(
            extensions=self.config.include_extensions,
            exclude_patterns=self.config.exclude_patterns,
            max_file_size_kb=self.config.max_file_size_kb
        )
        self.language_detector = LanguageDetector()
        
        # Validate configuration
        config_errors = self.config.validate()
        if config_errors:
            raise ValueError(f"Invalid configuration: {', '.join(config_errors)}")
        
        # Register all available analyzers
        self._register_default_analyzers()
        
        logger.info("AICodeDetector initialized", extra={
            "config": {
                "confidence_threshold": self.config.confidence_threshold,
                "quality_gates_enabled": self.config.enable_quality_gates,
                "remediation_enabled": self.config.enable_remediation
            },
            "analyzers": list(self.analyzers.keys())
        })
    
    def _register_default_analyzers(self):
        """Register all default analyzers with proper initialization."""
        # Emoji Detector - 15% weight (strong indicator)
        self.register_analyzer('emoji', EmojiDetector())
        
        # Pattern Analyzer - 25% weight (highest - generic naming, verbose comments)
        self.register_analyzer('pattern', PatternAnalyzer())
        
        # Statistical Analyzer - 20% weight (complexity, diversity, nesting)
        self.register_analyzer('statistical', StatisticalAnalyzer())
        
        # Security Analyzer - 20% weight (vulnerabilities 2-3x higher in AI code)
        self.register_analyzer('security', SecurityAnalyzer())
        
        # Semantic Analyzer - 10% weight (comment quality, AI writing style)
        try:
            from codebase_csi.analyzers.semantic_analyzer import SemanticAnalyzer
            self.register_analyzer('semantic', SemanticAnalyzer())
        except ImportError:
            logger.warning("Semantic analyzer not available")
        
        # Architectural Analyzer - 5% weight (SOLID violations, god classes)
        try:
            from codebase_csi.analyzers.architectural_analyzer import ArchitecturalAnalyzer
            self.register_analyzer('architectural', ArchitecturalAnalyzer())
        except ImportError:
            logger.warning("Architectural analyzer not available")
        
        # Mock Code Detector - 15% weight (placeholder/stub implementations)
        self.register_analyzer('mock', MockCodeDetector())
        
        logger.info(f"Registered {len(self.analyzers)} default analyzers")
    
    def register_analyzer(self, name: str, analyzer):
        """
        Register an analyzer module.
        
        Args:
            name: Analyzer name (e.g., 'pattern', 'statistical')
            analyzer: Analyzer instance with analyze() method
        """
        self.analyzers[name] = analyzer
        logger.debug(f"Registered analyzer: {name}")
    
    def scan_file(self, file_path: Union[str, Path]) -> FileAnalysis:
        """
        Scan a single file for AI-generated patterns.
        
        Args:
            file_path: Path to file to scan
            
        Returns:
            FileAnalysis object with results
        """
        file_path = Path(file_path)
        start_time = datetime.now()
        
        logger.info(f"Scanning file: {file_path}")
        
        # Read file content with proper encoding detection
        try:
            from codebase_csi.utils.file_utils import read_file_with_encoding_detection
            content, encoding = read_file_with_encoding_detection(file_path)
            lines = content.splitlines()
            
            logger.debug(f"Read file with encoding: {encoding}", extra={
                "file": str(file_path),
                "encoding": encoding
            })
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return FileAnalysis(
                file_path=str(file_path),
                language="unknown",
                lines_of_code=0,
                confidence_score=0.0,
                confidence_level=ConfidenceLevel.NONE,
                error=str(e)
            )
        
        # Detect language with content sample for conflict resolution
        content_sample = '\n'.join(lines[:50]) if lines else ''  # First 50 lines
        language = self.language_detector.detect(file_path, content_sample)
        
        # Run analysis phases
        patterns: List[DetectionPattern] = []
        phase_scores = {}
        analysis_phases = {}
        
        for analyzer_name, analyzer in self.analyzers.items():
            try:
                phase_result = analyzer.analyze(file_path, content, language)
                phase_scores[analyzer_name] = phase_result.get('confidence', 0.0)
                analysis_phases[analyzer_name] = phase_result
                
                # Extract patterns from phase result
                if 'patterns' in phase_result:
                    patterns.extend(phase_result['patterns'])
                
                logger.debug(f"{analyzer_name} analysis complete", extra={
                    "file": str(file_path),
                    "confidence": phase_result.get('confidence', 0.0)
                })
            
            except Exception as e:
                logger.error(f"Error in {analyzer_name} analyzer for {file_path}: {e}")
                phase_scores[analyzer_name] = 0.0
        
        # Calculate overall confidence
        overall_confidence = self._calculate_overall_confidence(phase_scores)
        confidence_level = ConfidenceLevel.from_score(overall_confidence)
        
        # Calculate scan duration
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        analysis = FileAnalysis(
            file_path=str(file_path),
            language=language,
            lines_of_code=len(lines),
            confidence_score=overall_confidence,
            confidence_level=confidence_level,
            patterns=patterns,
            analysis_phases=analysis_phases,
            scan_duration_ms=duration_ms
        )
        
        logger.info(f"File scan complete: {file_path}", extra={
            "confidence": overall_confidence,
            "level": confidence_level.value,
            "patterns": len(patterns),
            "duration_ms": duration_ms
        })
        
        return analysis
    
    def scan_directory(
        self,
        directory: Union[str, Path],
        recursive: bool = True
    ) -> DetectionResult:
        """
        Scan all files in a directory.
        
        Args:
            directory: Directory path to scan
            recursive: Whether to scan subdirectories
            
        Returns:
            DetectionResult with all file analyses
        """
        directory = Path(directory)
        scan_id = str(uuid.uuid4())
        start_time = datetime.now()
        
        logger.info(f"Starting directory scan: {directory}", extra={
            "scan_id": scan_id,
            "recursive": recursive
        })
        
        # Discover files
        files = self.file_scanner.scan_directory(directory, recursive=recursive)
        total_files = len(files)
        
        logger.info(f"Found {total_files} files to scan")
        
        # Scan each file
        file_analyses: List[FileAnalysis] = []
        skipped_files = 0
        errors: List[str] = []
        
        for file_path in files:
            try:
                analysis = self.scan_file(file_path)
                
                # Only include if above threshold or has error
                if analysis.confidence_score >= self.config.confidence_threshold or analysis.error:
                    file_analyses.append(analysis)
                    
                if analysis.error:
                    errors.append(f"{file_path}: {analysis.error}")
                    
            except Exception as e:
                logger.error(f"Failed to scan {file_path}: {e}")
                errors.append(f"{file_path}: {str(e)}")
                skipped_files += 1
        
        # Calculate overall project confidence
        if file_analyses:
            overall_confidence = sum(f.confidence_score for f in file_analyses) / len(file_analyses)
        else:
            overall_confidence = 0.0
        
        # Calculate duration
        scan_duration = (datetime.now() - start_time).total_seconds()
        
        result = DetectionResult(
            scan_id=scan_id,
            timestamp=start_time,
            target_path=str(directory),
            total_files=total_files,
            scanned_files=total_files - skipped_files,
            skipped_files=skipped_files,
            file_analyses=file_analyses,
            overall_confidence=overall_confidence,
            scan_duration_seconds=scan_duration,
            configuration=self.config.__dict__,
            errors=errors
        )
        
        logger.info("Directory scan complete", extra={
            "scan_id": scan_id,
            "files_scanned": result.scanned_files,
            "ai_files": result.ai_file_count,
            "duration_seconds": scan_duration
        })
        
        return result
    
    def analyze_project(
        self,
        project_path: Union[str, Path]
    ) -> ProjectAnalysis:
        """
        Perform complete project analysis with quality gates.
        
        Args:
            project_path: Path to project root
            
        Returns:
            ProjectAnalysis with quality gate results
        """
        logger.info(f"Analyzing project: {project_path}")
        
        # Run detection scan
        detection_result = self.scan_directory(project_path)
        
        # Initialize project analysis
        project_analysis = ProjectAnalysis(
            project_path=str(project_path),
            detection_result=detection_result,
            quality_gate_passed=True,
            quality_gate_failures=[]
        )
        
        # Run quality gates if enabled
        if self.config.enable_quality_gates:
            logger.info("Running quality gates")
            self._run_quality_gates(project_analysis)
        
        # Generate remediation suggestions if enabled
        if self.config.enable_remediation:
            logger.info("Generating remediation suggestions")
            self._generate_remediation(project_analysis)
        
        # Generate compliance report if enabled
        if self.config.enable_compliance_report:
            logger.info("Generating compliance report")
            self._generate_compliance_report(project_analysis)
        
        logger.info("Project analysis complete", extra={
            "project": str(project_path),
            "quality_gate": "PASSED" if project_analysis.quality_gate_passed else "FAILED",
            "risk": project_analysis.risk_level
        })
        
        return project_analysis
    
    def _calculate_overall_confidence(self, phase_scores: Dict[str, float]) -> float:
        """
        Calculate weighted overall confidence from phase scores.
        
        Args:
            phase_scores: Dictionary of analyzer_name -> confidence score
            
        Returns:
            Overall confidence score (0.0-1.0)
        """
        # v1.1 weights - 80% total coverage with 4 analyzers
        # Pattern (25%): Generic naming, verbose comments, boolean traps, magic numbers, god functions
        # Statistical (20%): Complexity, token diversity, nesting, duplication, function metrics
        # Security (20%): OWASP Top 10, SQL injection, command injection, XSS, weak crypto
        # Emoji (15%): Strong indicator - professional code doesn't use emojis
        # Future (20%): Reserved for semantic, architectural, metadata analyzers in v1.2+
        weights = {
            'pattern': 0.25,      # v1.1 - Implemented
            'statistical': 0.20,  # v1.1 - Implemented
            'security': 0.20,     # v1.1 - Implemented
            'emoji': 0.15,        # v1.0 - Implemented
            'semantic': 0.10,     # v1.2 - Future
            'architectural': 0.05, # v1.2 - Future
            'metadata': 0.05,     # v1.2 - Future
        }
        
        total_score = 0.0
        total_weight = 0.0
        
        for analyzer_name, score in phase_scores.items():
            weight = weights.get(analyzer_name, 0.05)  # Default 5% for unknown analyzers
            total_score += score * weight
            total_weight += weight
        
        if total_weight > 0:
            # Normalize by actual weight (not theoretical max)
            return min(total_score / total_weight, 1.0)
        return 0.0
    
    def _run_quality_gates(self, analysis: ProjectAnalysis):
        """
        Run quality gate checks.
        
        Args:
            analysis: ProjectAnalysis to check
        """
        result = analysis.detection_result
        failures = []
        
        # Check overall confidence threshold
        if result.overall_confidence > self.config.max_ai_confidence:
            failures.append(
                f"Overall AI confidence ({result.overall_confidence:.2%}) "
                f"exceeds limit ({self.config.max_ai_confidence:.2%})"
            )
        
        # Check AI file percentage
        if result.ai_percentage > self.config.max_ai_file_percentage:
            failures.append(
                f"AI-generated file percentage ({result.ai_percentage:.1f}%) "
                f"exceeds limit ({self.config.max_ai_file_percentage:.1f}%)"
            )
        
        # Check for critical files
        critical_files = [
            f for f in result.file_analyses
            if f.confidence_level in [ConfidenceLevel.VERY_HIGH, ConfidenceLevel.HIGH]
        ]
        
        if critical_files:
            failures.append(
                f"Found {len(critical_files)} files with HIGH/VERY_HIGH confidence"
            )
        
        if failures:
            analysis.quality_gate_passed = False
            analysis.quality_gate_failures = failures
            logger.warning("Quality gates FAILED", extra={"failures": failures})
        else:
            logger.info("Quality gates PASSED")
    
    def _generate_remediation(self, analysis: ProjectAnalysis):
        """
        Generate remediation suggestions.
        
        Args:
            analysis: ProjectAnalysis to generate suggestions for
        """
        suggestions = []
        
        for file_analysis in analysis.detection_result.file_analyses:
            if file_analysis.is_ai_generated:
                suggestions.append({
                    'file': file_analysis.file_path,
                    'confidence': file_analysis.confidence_score,
                    'priority': self._get_priority(file_analysis.confidence_level),
                    'actions': self._get_remediation_actions(file_analysis)
                })
        
        analysis.remediation_suggestions = suggestions
        logger.info(f"Generated {len(suggestions)} remediation suggestions")
    
    def _get_priority(self, level: ConfidenceLevel) -> str:
        """Get priority level for remediation."""
        if level == ConfidenceLevel.VERY_HIGH:
            return "CRITICAL"
        elif level == ConfidenceLevel.HIGH:
            return "HIGH"
        elif level == ConfidenceLevel.MEDIUM:
            return "MEDIUM"
        else:
            return "LOW"
    
    def _get_remediation_actions(self, file_analysis: FileAnalysis) -> List[str]:
        """Get specific remediation actions for a file."""
        actions = []
        
        if file_analysis.confidence_level == ConfidenceLevel.VERY_HIGH:
            actions.extend([
                "Schedule immediate manual review",
                "Consider complete refactoring",
                "Document AI tool usage",
                "Add comprehensive tests"
            ])
        elif file_analysis.confidence_level == ConfidenceLevel.HIGH:
            actions.extend([
                "Manual review required",
                "Add code comments explaining logic",
                "Verify error handling",
                "Check security implications"
            ])
        else:
            actions.extend([
                "Review when time permits",
                "Document any AI assistance used"
            ])
        
        return actions
    
    def _generate_compliance_report(self, analysis: ProjectAnalysis):
        """
        Generate compliance report.
        
        Args:
            analysis: ProjectAnalysis to generate report for
        """
        result = analysis.detection_result
        
        compliance_report = {
            'scan_date': result.timestamp.isoformat(),
            'project': analysis.project_path,
            'summary': result.get_summary(),
            'quality_gate_status': 'PASSED' if analysis.quality_gate_passed else 'FAILED',
            'risk_assessment': {
                'overall_risk': analysis.risk_level,
                'ai_file_count': result.ai_file_count,
                'ai_file_percentage': result.ai_percentage,
                'high_risk_files': len([
                    f for f in result.file_analyses
                    if f.confidence_level in [ConfidenceLevel.VERY_HIGH, ConfidenceLevel.HIGH]
                ])
            },
            'recommendations': analysis.remediation_suggestions[:10]  # Top 10
        }
        
        analysis.compliance_report = compliance_report
        logger.info("Compliance report generated")
