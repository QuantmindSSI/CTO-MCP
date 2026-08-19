"""
Report Generator - JSON Analysis Reports
Production-Ready v1.0

Generates comprehensive JSON reports after codebase analysis.
Designed for machine-readable output and CI/CD integration.

Features:
- Executive summary with risk assessment
- Per-file breakdown with issue details
- Antipattern analysis with recommendations
- Actionable remediation suggestions
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import Counter

from codebase_csi.utils.file_utils import CodeSnippetExtractor


@dataclass
class FileAnalysis:
    """Analysis results for a single file."""
    path: str
    language: str
    lines_of_code: int
    results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    overall_confidence: float = 0.0
    risk_level: str = "MINIMAL"
    top_issues: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CodebaseReport:
    """Complete codebase analysis report."""
    # Metadata
    report_id: str
    generated_at: str
    codebase_path: str
    scan_duration_seconds: float
    
    # Statistics
    total_files: int
    total_lines: int
    languages: Dict[str, int]
    
    # Analysis Results
    overall_confidence: float
    risk_level: str
    analyzer_scores: Dict[str, Dict[str, float]]
    
    # Antipattern Summary
    antipattern_summary: Dict[str, int]
    
    # File Details
    file_analyses: List[FileAnalysis]
    
    # Top Issues
    critical_issues: List[Dict[str, Any]]
    high_issues: List[Dict[str, Any]]
    
    # Recommendations
    recommendations: List[str]


class ReportGenerator:
    """
    Generates comprehensive JSON analysis reports.
    
    Output format:
    - JSON: Machine-readable for CI/CD integration
    """
    
    ANALYZER_WEIGHTS = {
        'Pattern': 0.22,
        'Statistical': 0.18,
        'Security': 0.16,
        'MockCode': 0.15,
        'Emoji': 0.10,
        'Architectural': 0.03,
        'Comment': 0.04,
        'Antipattern': 0.12,
    }
    
    def __init__(self):
        """Initialize report generator with snippet extractor."""
        self._snippet_extractor = CodeSnippetExtractor(context_lines=3, use_cache=True)
    
    def generate_report(
        self,
        scan_results: Dict[str, Any],
        output_path: Optional[Path] = None
    ) -> str:
        """
        Generate a comprehensive JSON report from scan results.
        
        Args:
            scan_results: Results from running all analyzers
            output_path: Optional path to save the report
            
        Returns:
            Report content as JSON string
        """
        # Build report data structure
        report = self._build_report_data(scan_results)
        
        # Generate JSON output
        content = self._generate_json_report(report)
        
        # Save if path provided
        if output_path:
            output_path.write_text(content, encoding='utf-8')
        
        return content
    
    def _build_report_data(self, scan_results: Dict[str, Any]) -> CodebaseReport:
        """Build structured report data from scan results."""
        file_analyses = []
        all_issues = []
        antipattern_counts = Counter()
        analyzer_totals = {name: [] for name in self.ANALYZER_WEIGHTS}
        total_lines = 0
        languages = Counter()
        
        for file_path, file_data in scan_results.get('files', {}).items():
            lang = file_data.get('language', 'unknown')
            loc = file_data.get('lines_of_code', 0)
            total_lines += loc
            languages[lang] += 1
            
            file_results = {}
            file_confidence = 0.0
            file_issues = []
            
            for analyzer_name, result in file_data.get('results', {}).items():
                if 'error' in result:
                    continue
                    
                conf = result.get('confidence', 0)
                issues = result.get('patterns', result.get('anomalies', 
                         result.get('vulnerabilities', result.get('antipatterns', 
                         result.get('issues', [])))))
                
                file_results[analyzer_name] = {
                    'confidence': conf,
                    'issue_count': len(issues) if isinstance(issues, list) else 0,
                }
                
                if analyzer_name in analyzer_totals:
                    analyzer_totals[analyzer_name].append(conf)
                
                # Collect issues with file context
                if isinstance(issues, list):
                    for issue in issues:
                        issue_dict = self._issue_to_dict(issue, file_path, analyzer_name)
                        file_issues.append(issue_dict)
                        all_issues.append(issue_dict)
                        
                        # Count antipatterns
                        if analyzer_name == 'Antipattern':
                            ap_type = getattr(issue, 'antipattern_type', issue_dict.get('type', 'unknown'))
                            antipattern_counts[ap_type] += 1
            
            # Calculate file confidence
            if file_results:
                file_confidence = sum(
                    file_results.get(name, {}).get('confidence', 0) * weight
                    for name, weight in self.ANALYZER_WEIGHTS.items()
                )
            
            file_analyses.append(FileAnalysis(
                path=file_path,
                language=lang,
                lines_of_code=loc,
                results=file_results,
                overall_confidence=file_confidence,
                risk_level=self._get_risk_level(file_confidence),
                top_issues=sorted(file_issues, 
                                 key=lambda x: self._severity_rank(x.get('severity', 'LOW')))[:5]
            ))
        
        # Calculate overall scores
        analyzer_scores = {}
        for name, confs in analyzer_totals.items():
            if confs:
                analyzer_scores[name] = {
                    'average': sum(confs) / len(confs),
                    'min': min(confs),
                    'max': max(confs),
                    'weight': self.ANALYZER_WEIGHTS.get(name, 0),
                }
        
        overall_confidence = sum(
            analyzer_scores.get(name, {}).get('average', 0) * weight
            for name, weight in self.ANALYZER_WEIGHTS.items()
        )
        
        # Sort issues by severity
        severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        sorted_issues = sorted(all_issues, key=lambda x: severity_order.get(x.get('severity', 'LOW'), 4))
        
        critical_issues = [i for i in sorted_issues if i.get('severity') == 'CRITICAL'][:20]
        high_issues = [i for i in sorted_issues if i.get('severity') == 'HIGH'][:20]
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            analyzer_scores, antipattern_counts, critical_issues, high_issues
        )
        
        return CodebaseReport(
            report_id=f"CSI-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            generated_at=datetime.now().isoformat(),
            codebase_path=scan_results.get('codebase_path', 'Unknown'),
            scan_duration_seconds=scan_results.get('duration', 0),
            total_files=len(file_analyses),
            total_lines=total_lines,
            languages=dict(languages),
            overall_confidence=overall_confidence,
            risk_level=self._get_risk_level(overall_confidence),
            analyzer_scores=analyzer_scores,
            antipattern_summary=dict(antipattern_counts),
            file_analyses=file_analyses,
            critical_issues=critical_issues,
            high_issues=high_issues,
            recommendations=recommendations,
        )
    
    def _issue_to_dict(self, issue: Any, file_path: str, analyzer: str) -> Dict[str, Any]:
        """Convert an issue object to a dictionary with code snippet."""
        if hasattr(issue, '__dict__'):
            d = {k: v for k, v in issue.__dict__.items() if not k.startswith('_')}
        elif isinstance(issue, dict):
            d = issue.copy()
        else:
            d = {'value': str(issue)}
        
        d['file'] = file_path
        d['analyzer'] = analyzer
        d.setdefault('severity', 'MEDIUM')
        d.setdefault('type', 'unknown')
        
        # Normalized line number keys (support 'line' or 'line_number')
        line_no = d.get('line_number') or d.get('line') or d.get('lineno') or 0
        d['line_number'] = int(line_no) if isinstance(line_no, (int, str)) and str(line_no).isdigit() else 0

        # Detected pattern/type for remediation guidance
        detected = d.get('pattern') or d.get('type') or d.get('issue_type') or 'unknown'
        d['detected_pattern'] = detected

        # Include code snippet (use existing or extract fresh)
        # Prioritize existing snippet from analyzer, then extract from file
        existing_snippet = d.get('code_snippet', '')
        if not existing_snippet and d['line_number'] > 0:
            d['code_snippet'] = self._snippet_extractor.extract(file_path, d['line_number'])
        else:
            d['code_snippet'] = existing_snippet
        
        d.setdefault('context', '')
        d.setdefault('suggestion', '')
        
        return d
    
    def _get_risk_level(self, confidence: float) -> str:
        """Determine risk level from confidence score."""
        if confidence >= 0.75:
            return 'CRITICAL'
        elif confidence >= 0.55:
            return 'HIGH'
        elif confidence >= 0.35:
            return 'MEDIUM'
        elif confidence >= 0.15:
            return 'LOW'
        return 'MINIMAL'
    
    def _severity_rank(self, severity: str) -> int:
        """Get numeric rank for severity."""
        ranks = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        return ranks.get(severity, 4)
    
    def _generate_recommendations(
        self,
        analyzer_scores: Dict[str, Dict[str, float]],
        antipattern_counts: Counter,
        critical_issues: List[Dict],
        high_issues: List[Dict]
    ) -> List[str]:
        """Generate actionable recommendations."""
        recommendations = []
        
        # Based on analyzer scores
        pattern_avg = analyzer_scores.get('Pattern', {}).get('average', 0)
        if pattern_avg > 0.6:
            recommendations.append(
                "Improve Naming Conventions: High pattern detection suggests generic variable names. "
                "Replace names like 'data', 'temp', 'result' with descriptive alternatives."
            )
        
        security_avg = analyzer_scores.get('Security', {}).get('average', 0)
        if security_avg > 0.3:
            recommendations.append(
                "Address Security Vulnerabilities: Security issues detected. "
                "Review hardcoded secrets, SQL injection risks, and input validation."
            )
        
        comment_avg = analyzer_scores.get('Comment', {}).get('average', 0)
        if comment_avg > 0.6:
            recommendations.append(
                "Refine Documentation Style: Comments appear tutorial-like. "
                "Focus on explaining 'why' rather than 'what'. Remove obvious comments."
            )
        
        statistical_avg = analyzer_scores.get('Statistical', {}).get('average', 0)
        if statistical_avg > 0.5:
            recommendations.append(
                "Reduce Code Complexity: High statistical anomalies detected. "
                "Consider refactoring complex functions and reducing nesting depth."
            )
        
        # Based on antipatterns
        if antipattern_counts.get('gold_plating', 0) > 5:
            recommendations.append(
                "Simplify Architecture: Gold plating detected. "
                "Apply YAGNI principle - remove unnecessary abstractions and over-engineered patterns."
            )
        
        if antipattern_counts.get('bleeding_edge', 0) > 3:
            recommendations.append(
                "Stabilize Dependencies: Bleeding edge patterns detected. "
                "Consider using stable versions of dependencies for production reliability."
            )
        
        if antipattern_counts.get('magic_numbers', 0) > 5:
            recommendations.append(
                "Extract Constants: Magic numbers detected. "
                "Replace hardcoded values with named constants for better maintainability."
            )
        
        # Based on critical issues
        if len(critical_issues) > 0:
            recommendations.insert(0,
                f"URGENT: {len(critical_issues)} critical issues require immediate attention. "
                "Review the critical_issues section."
            )
        
        if not recommendations:
            recommendations.append(
                "Good Code Quality: No major issues detected. "
                "Continue following current best practices."
            )
        
        return recommendations
    
    def _generate_json_report(self, report: CodebaseReport) -> str:
        """Generate JSON report for CI/CD integration."""
        report_dict = {
            'report_id': report.report_id,
            'generated_at': report.generated_at,
            'codebase_path': report.codebase_path,
            'scan_duration_seconds': report.scan_duration_seconds,
            'summary': {
                'total_files': report.total_files,
                'total_lines': report.total_lines,
                'languages': report.languages,
                'overall_confidence': report.overall_confidence,
                'risk_level': report.risk_level,
            },
            'analyzer_scores': report.analyzer_scores,
            'antipattern_summary': report.antipattern_summary,
            'critical_issues': report.critical_issues,
            'high_issues': report.high_issues,
            'recommendations': report.recommendations,
            'files': [
                {
                    'path': fa.path,
                    'language': fa.language,
                    'lines_of_code': fa.lines_of_code,
                    'overall_confidence': fa.overall_confidence,
                    'risk_level': fa.risk_level,
                    'results': fa.results,
                }
                for fa in report.file_analyses
            ],
        }
        
        return json.dumps(report_dict, indent=2, default=str)
