"""
Development Documentation Analyzer
Detects AI-generated planning and development documents that should not be pushed to production.

AI assistants commonly generate these types of documents during development:
- Implementation plans and summaries
- Architecture decision records (informal)
- Quick setup guides (internal)
- Improvement/TODO lists
- API documentation drafts
- Deep dive technical docs

These are valuable locally but typically shouldn't be in production repos.
"""

import re
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass


@dataclass
class DevDocIssue:
    """Represents a development document that may not belong in production."""
    file_path: str
    doc_type: str
    confidence: float
    severity: str  # 'LOW', 'MEDIUM', 'HIGH'
    reason: str
    suggestion: str


class DevDocAnalyzer:
    """
    Analyzes a codebase for development documentation that should remain local.
    
    AI assistants tend to create extensive planning documents during development.
    These are useful locally but often shouldn't be pushed to production repos.
    """
    
    # File name patterns that indicate development docs
    DEV_DOC_FILENAME_PATTERNS = {
        # Implementation/Planning docs
        r'IMPLEMENTATION[-_]?SUMMARY': ('implementation_summary', 'HIGH', 'Implementation summaries are internal planning docs'),
        r'IMPLEMENTATION[-_]?PLAN': ('implementation_plan', 'HIGH', 'Implementation plans are internal planning docs'),
        r'IMPLEMENTATION[-_]?NOTES?': ('implementation_notes', 'HIGH', 'Implementation notes are internal docs'),
        r'ARCHITECTURE\.md$': ('architecture_doc', 'MEDIUM', 'Architecture docs may be internal planning'),
        r'ARCHITECTURE[-_]?DECISION': ('adr_informal', 'MEDIUM', 'Informal ADRs may not follow standard format'),
        
        # Quick/Setup guides (internal)
        r'QUICK[-_]?SETUP': ('quick_setup', 'MEDIUM', 'Quick setup guides are often internal convenience docs'),
        r'QUICK[-_]?START': ('quick_start', 'LOW', 'May be internal or public - review needed'),
        r'DEV[-_]?SETUP': ('dev_setup', 'MEDIUM', 'Dev setup guides are typically internal'),
        r'LOCAL[-_]?SETUP': ('local_setup', 'MEDIUM', 'Local setup guides are internal'),
        
        # Improvement/TODO docs
        r'IMPROVEMENTS?\.md$': ('improvements', 'HIGH', 'Improvement lists are internal planning'),
        r'TODO\.md$': ('todo_doc', 'HIGH', 'TODO documents are internal tracking'),
        r'TASKS?\.md$': ('task_doc', 'HIGH', 'Task documents are internal tracking'),
        r'ROADMAP[-_]?INTERNAL': ('internal_roadmap', 'HIGH', 'Internal roadmaps should stay local'),
        r'BACKLOG\.md$': ('backlog', 'HIGH', 'Backlog documents are internal'),
        
        # Technical deep dives (internal)
        r'DEEP[-_]?DIVE': ('deep_dive', 'MEDIUM', 'Deep dive docs may be internal technical notes'),
        r'TECHNICAL[-_]?NOTES?': ('tech_notes', 'MEDIUM', 'Technical notes are often internal'),
        r'DESIGN[-_]?NOTES?': ('design_notes', 'MEDIUM', 'Design notes are often internal'),
        r'RESEARCH[-_]?NOTES?': ('research_notes', 'MEDIUM', 'Research notes are internal'),
        
        # API docs (drafts)
        r'API[-_]?DOCUMENTATION': ('api_doc', 'LOW', 'May be draft - check if finalized'),
        r'API[-_]?REFERENCE': ('api_ref', 'LOW', 'May be draft - check if finalized'),
        
        # Integration plans
        r'INTEGRATION[-_]?PLAN': ('integration_plan', 'HIGH', 'Integration plans are internal'),
        r'MIGRATION[-_]?PLAN': ('migration_plan', 'HIGH', 'Migration plans are internal'),
        r'UPGRADE[-_]?PLAN': ('upgrade_plan', 'HIGH', 'Upgrade plans are internal'),
        
        # Meeting/Discussion notes
        r'MEETING[-_]?NOTES?': ('meeting_notes', 'HIGH', 'Meeting notes are internal'),
        r'DISCUSSION[-_]?NOTES?': ('discussion_notes', 'HIGH', 'Discussion notes are internal'),
        r'DECISION[-_]?LOG': ('decision_log', 'MEDIUM', 'May be informal decision tracking'),
        
        # Debug/Troubleshooting
        r'DEBUG[-_]?NOTES?': ('debug_notes', 'HIGH', 'Debug notes are internal'),
        r'TROUBLESHOOTING[-_]?NOTES?': ('troubleshoot_notes', 'MEDIUM', 'May be internal or public'),
        
        # Draft indicators
        r'DRAFT[-_]': ('draft_doc', 'HIGH', 'Draft documents should not be in production'),
        r'[-_]DRAFT\.md$': ('draft_doc', 'HIGH', 'Draft documents should not be in production'),
        r'WIP[-_]': ('wip_doc', 'HIGH', 'Work-in-progress docs should not be in production'),
        r'[-_]WIP\.md$': ('wip_doc', 'HIGH', 'Work-in-progress docs should not be in production'),
    }
    
    # Content patterns that indicate development docs
    DEV_DOC_CONTENT_PATTERNS = [
        (r'(?i)^#\s*implementation\s+(plan|summary|notes)', 'implementation_doc', 0.8),
        (r'(?i)this\s+document\s+(outlines|describes)\s+the\s+(implementation|development)', 'planning_doc', 0.7),
        (r'(?i)^#\s*todo\s*$|^##\s*todo\s*$', 'todo_section', 0.6),
        (r'(?i)internal\s+use\s+only', 'internal_doc', 0.9),
        (r'(?i)do\s+not\s+(share|distribute|publish)', 'confidential', 0.9),
        (r'(?i)draft\s+version|work\s+in\s+progress', 'draft_indicator', 0.8),
        (r'(?i)^\s*-\s*\[\s*[x ]?\s*\]', 'task_list', 0.5),  # Markdown checkboxes
        (r'(?i)phase\s+\d+\s*:', 'phased_plan', 0.7),
        (r'(?i)^#+\s*phase\s+\d+', 'phased_plan', 0.7),
        (r'(?i)estimated\s+(time|effort|duration)', 'estimate_doc', 0.6),
        (r'(?i)meeting\s+(notes|minutes|summary)', 'meeting_doc', 0.8),
        (r'(?i)^#+\s*next\s+steps', 'planning_section', 0.6),
        (r'(?i)^#+\s*open\s+questions', 'planning_section', 0.6),
        (r'(?i)^#+\s*blockers?', 'tracking_doc', 0.6),
        (r'(?i)^#+\s*risks?\s*(and|&)\s*mitigations?', 'risk_doc', 0.6),
    ]
    
    # Standard files that SHOULD be in repos (whitelist)
    STANDARD_FILES = {
        'README.md',
        'LICENSE',
        'LICENSE.md',
        'CHANGELOG.md',
        'CONTRIBUTING.md',
        'CODE_OF_CONDUCT.md',
        'SECURITY.md',
        'CODEOWNERS',
        '.gitignore',
        '.gitattributes',
    }
    
    # Standard directories for docs
    STANDARD_DOC_DIRS = {
        'docs/official',
        'docs/api',
        'docs/guides',
        'docs/tutorials',
        '.github',
    }
    
    def __init__(self):
        """Initialize the analyzer."""
        self.issues: List[DevDocIssue] = []
    
    def analyze_file(self, file_path: Path) -> Optional[DevDocIssue]:
        """
        Analyze a single file to determine if it's a dev doc that shouldn't be pushed.
        
        Args:
            file_path: Path to the file to analyze
            
        Returns:
            DevDocIssue if the file appears to be a development doc, None otherwise
        """
        # Skip non-markdown files for now
        if file_path.suffix.lower() not in ['.md', '.markdown', '.txt']:
            return None
        
        filename = file_path.name
        relative_path = str(file_path)
        
        # Check if it's a standard file (whitelist)
        if filename in self.STANDARD_FILES:
            return None
        
        # Check if it's in a standard docs directory
        for std_dir in self.STANDARD_DOC_DIRS:
            if std_dir in relative_path.replace('\\', '/'):
                return None
        
        # Check filename patterns
        for pattern, (doc_type, severity, reason) in self.DEV_DOC_FILENAME_PATTERNS.items():
            if re.search(pattern, filename, re.IGNORECASE):
                return DevDocIssue(
                    file_path=str(file_path),
                    doc_type=doc_type,
                    confidence=0.8 if severity == 'HIGH' else 0.6 if severity == 'MEDIUM' else 0.4,
                    severity=severity,
                    reason=reason,
                    suggestion=f"Consider adding to .gitignore or moving to docs/internal/"
                )
        
        # Check content patterns if file exists and is readable
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            content_confidence = self._analyze_content(content)
            
            if content_confidence > 0.5:
                return DevDocIssue(
                    file_path=str(file_path),
                    doc_type='dev_content',
                    confidence=content_confidence,
                    severity='MEDIUM' if content_confidence > 0.7 else 'LOW',
                    reason='Content patterns suggest this is a development/planning document',
                    suggestion='Review content and consider if this should be in production repo'
                )
        except Exception:
            pass
        
        return None
    
    def _analyze_content(self, content: str) -> float:
        """Analyze content for development doc patterns."""
        if not content:
            return 0.0
        
        max_confidence = 0.0
        pattern_matches = 0
        
        for pattern, doc_type, confidence in self.DEV_DOC_CONTENT_PATTERNS:
            if re.search(pattern, content, re.MULTILINE):
                pattern_matches += 1
                max_confidence = max(max_confidence, confidence)
        
        # Boost confidence if multiple patterns match
        if pattern_matches > 2:
            max_confidence = min(1.0, max_confidence + 0.1)
        if pattern_matches > 4:
            max_confidence = min(1.0, max_confidence + 0.1)
        
        return max_confidence
    
    def analyze_directory(self, directory: Path, recursive: bool = True) -> List[DevDocIssue]:
        """
        Analyze a directory for development documents.
        
        Args:
            directory: Path to the directory to analyze
            recursive: Whether to scan subdirectories
            
        Returns:
            List of DevDocIssue for files that appear to be development docs
        """
        self.issues = []
        
        if recursive:
            files = directory.rglob('*')
        else:
            files = directory.glob('*')
        
        # Skip common non-source directories
        skip_dirs = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache', 'htmlcov', 'dist', 'build'}
        
        for file_path in files:
            # Skip directories in skip list
            if any(skip_dir in file_path.parts for skip_dir in skip_dirs):
                continue
            
            if file_path.is_file():
                issue = self.analyze_file(file_path)
                if issue:
                    self.issues.append(issue)
        
        return self.issues
    
    def generate_gitignore_suggestions(self) -> List[str]:
        """Generate .gitignore entries based on found issues."""
        suggestions = []
        seen_patterns = set()
        
        for issue in self.issues:
            filename = Path(issue.file_path).name
            
            # Generate appropriate gitignore pattern
            if issue.doc_type in ['implementation_summary', 'implementation_plan', 'implementation_notes']:
                pattern = 'IMPLEMENTATION*.md'
            elif issue.doc_type == 'architecture_doc':
                pattern = 'ARCHITECTURE.md'
            elif issue.doc_type in ['quick_setup', 'dev_setup', 'local_setup']:
                pattern = '*SETUP*.md'
            elif issue.doc_type in ['improvements', 'todo_doc', 'task_doc', 'backlog']:
                pattern = f'{filename}'
            elif issue.doc_type == 'deep_dive':
                pattern = '*DEEP_DIVE*.md'
            elif issue.doc_type in ['draft_doc', 'wip_doc']:
                pattern = '*DRAFT*.md\n*WIP*.md'
            else:
                pattern = filename
            
            if pattern not in seen_patterns:
                suggestions.append(pattern)
                seen_patterns.add(pattern)
        
        return suggestions
    
    def get_summary(self) -> Dict:
        """Get a summary of the analysis."""
        return {
            'total_issues': len(self.issues),
            'high_severity': len([i for i in self.issues if i.severity == 'HIGH']),
            'medium_severity': len([i for i in self.issues if i.severity == 'MEDIUM']),
            'low_severity': len([i for i in self.issues if i.severity == 'LOW']),
            'doc_types': dict(Counter(i.doc_type for i in self.issues)),
            'gitignore_suggestions': self.generate_gitignore_suggestions(),
        }


# Import Counter for summary
from collections import Counter


def scan_for_dev_docs(path: str) -> Dict:
    """
    Convenience function to scan a path for development documents.
    
    Args:
        path: Path to file or directory to scan
        
    Returns:
        Dictionary with scan results
    """
    analyzer = DevDocAnalyzer()
    target = Path(path)
    
    if target.is_file():
        issue = analyzer.analyze_file(target)
        if issue:
            analyzer.issues = [issue]
    else:
        analyzer.analyze_directory(target)
    
    return {
        'issues': [
            {
                'file': i.file_path,
                'type': i.doc_type,
                'confidence': i.confidence,
                'severity': i.severity,
                'reason': i.reason,
                'suggestion': i.suggestion,
            }
            for i in analyzer.issues
        ],
        'summary': analyzer.get_summary(),
    }


if __name__ == '__main__':
    import sys
    import json
    
    path = sys.argv[1] if len(sys.argv) > 1 else '.'
    result = scan_for_dev_docs(path)
    
    print(json.dumps(result, indent=2))
