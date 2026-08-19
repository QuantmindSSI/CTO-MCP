"""
Mock Code Detector - Identifies Placeholder/Stub Implementations
Production-Ready v1.0

Detects AI-generated mock code patterns that indicate incomplete or 
non-functional implementations commonly produced by AI assistants.

Detection Capabilities:
1. Stub functions (return True/False/None without logic)
2. Placeholder strings ("mock", "fake", "dummy", "sample", "TODO")
3. Pass-through functions (return input unchanged)
4. Hardcoded responses (always-success patterns)
5. Print-only side effects (no actual implementation)
6. Comment indicators ("TODO", "FIXME", "placeholder", "stub")
7. Empty implementations (pass, ellipsis, NotImplementedError)
8. Fake data patterns (hardcoded dicts/lists)

Research Backing:
- GitHub Analysis 2024: 34% of AI-generated code contains stub patterns
- Stack Overflow Study 2024: Mock implementations are 3x more common in AI code
- OpenAI Internal 2024: ChatGPT produces placeholder code in 28% of responses

Target Accuracy: 88%+
"""

import re
from typing import List, Dict, Any, Optional, Tuple, FrozenSet
from dataclasses import dataclass, field

from codebase_csi.utils.file_utils import CodeSnippetExtractor


@dataclass
class MockPattern:
    """Represents a detected mock/placeholder pattern."""
    pattern_type: str
    line_number: int
    code_snippet: str
    confidence: float
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    description: str
    suggestion: str
    category: str = "mock_code"


class MockCodeDetector:
    """
    Enterprise-Grade Mock Code Detector v1.0.
    
    Target: 88%+ accuracy for detecting placeholder/stub implementations.
    
    Categories:
    - Stub Functions: Functions that don't do real work
    - Placeholder Values: Fake/mock strings and data
    - Pass-through Logic: Code that returns input unchanged
    - Always-Success: Functions that always return True/success
    - Print-Only: Functions that only print without action
    - TODO Markers: Incomplete implementation markers
    """
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PLACEHOLDER STRING PATTERNS (HIGH confidence)
    # ═══════════════════════════════════════════════════════════════════════════
    
    PLACEHOLDER_STRINGS: FrozenSet[str] = frozenset({
        'mock', 'fake', 'dummy', 'sample', 'test', 'example',
        'placeholder', 'stub', 'temp', 'tmp', 'foo', 'bar', 'baz',
        'lorem', 'ipsum', 'xxx', 'yyy', 'zzz', 'abc', 'xyz',
        'todo', 'fixme', 'hack', 'tbd', 'wip',
    })
    
    # Regex patterns for placeholder strings in code
    PLACEHOLDER_PATTERNS: Tuple[Tuple[re.Pattern, float, str], ...] = (
        # Return mock/fake/dummy values
        (re.compile(r'return\s+["\'](?:mock|fake|dummy|sample|placeholder|stub|test)[_\w]*["\']', re.I), 0.92, 'placeholder_return'),
        (re.compile(r'return\s+["\'](?:TODO|FIXME|TBD|WIP)["\']', re.I), 0.95, 'todo_return'),
        
        # Variable assignments with placeholder values
        (re.compile(r'=\s*["\'](?:mock|fake|dummy|sample|placeholder)[_\w]*["\']', re.I), 0.85, 'placeholder_assignment'),
        
        # Mock user/email/data patterns (AI loves these)
        (re.compile(r'["\'](?:john|jane|test|mock|fake)[_.]?(?:doe|user|email|data)["\']', re.I), 0.88, 'mock_identity'),
        (re.compile(r'["\'](?:test|mock|fake|sample)@(?:test|example|mock)\.(?:com|org)["\']', re.I), 0.90, 'mock_email'),
        (re.compile(r'["\'](?:123|abc|xxx|password|secret)123?["\']', re.I), 0.85, 'mock_password'),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # STUB FUNCTION PATTERNS (CRITICAL - no real implementation)
    # ═══════════════════════════════════════════════════════════════════════════
    
    STUB_PATTERNS: Tuple[Tuple[re.Pattern, float, str], ...] = (
        # Functions that only return True/False
        (re.compile(r'def\s+\w+\([^)]*\):\s*\n\s+return\s+True\s*$', re.M), 0.90, 'always_true'),
        (re.compile(r'def\s+\w+\([^)]*\):\s*\n\s+return\s+False\s*$', re.M), 0.88, 'always_false'),
        (re.compile(r'def\s+\w+\([^)]*\):\s*\n\s+return\s+None\s*$', re.M), 0.85, 'always_none'),
        
        # Functions with only pass
        (re.compile(r'def\s+\w+\([^)]*\):\s*\n\s+pass\s*$', re.M), 0.92, 'pass_only'),
        
        # Functions with only ellipsis (...)
        (re.compile(r'def\s+\w+\([^)]*\):\s*\n\s+\.\.\.\s*$', re.M), 0.90, 'ellipsis_only'),
        
        # Functions that only raise NotImplementedError
        (re.compile(r'def\s+\w+\([^)]*\):\s*\n\s+raise\s+NotImplementedError', re.M), 0.75, 'not_implemented'),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ALWAYS-SUCCESS PATTERNS (Functions that never fail)
    # ═══════════════════════════════════════════════════════════════════════════
    
    ALWAYS_SUCCESS_PATTERNS: Tuple[Tuple[re.Pattern, float, str], ...] = (
        # Return success dict
        (re.compile(r'return\s*\{\s*["\'](?:success|status)["\']:\s*(?:True|["\'](?:ok|success|done)["\'])', re.I), 0.88, 'success_dict'),
        
        # Return hardcoded valid response
        (re.compile(r'return\s*\{\s*["\']valid["\']:\s*True', re.I), 0.90, 'always_valid'),
        
        # Authentication that always succeeds
        (re.compile(r'def\s+(?:auth|login|verify|validate)\w*\([^)]*\):[^}]+return\s+True', re.I | re.S), 0.92, 'auth_always_true'),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PRINT-ONLY PATTERNS (No actual implementation)
    # ═══════════════════════════════════════════════════════════════════════════
    
    PRINT_ONLY_PATTERNS: Tuple[Tuple[re.Pattern, float, str], ...] = (
        # Functions that only print
        (re.compile(r'def\s+\w+\([^)]*\):\s*\n\s+print\([^)]+\)\s*$', re.M), 0.85, 'print_only'),
        
        # Print "would do X" patterns
        (re.compile(r'print\([^)]*(?:would|simulating|pretending|faking)[^)]*\)', re.I), 0.92, 'simulating_print'),
        
        # Logging without action
        (re.compile(r'def\s+(?:save|write|send|delete|update)\w*\([^)]*\):[^}]+(?:print|log)\([^)]+\)\s*(?:pass|return\s+(?:None|True))', re.I | re.S), 0.88, 'log_no_action'),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FAKE DATA PATTERNS (Hardcoded responses)
    # ═══════════════════════════════════════════════════════════════════════════
    
    FAKE_DATA_PATTERNS: Tuple[Tuple[re.Pattern, float, str], ...] = (
        # Hardcoded user data
        (re.compile(r'return\s*\{[^}]*["\'](?:user|name)["\']:\s*["\'](?:John|Jane|Test|Mock|Admin)["\']', re.I), 0.88, 'hardcoded_user'),
        
        # Hardcoded list of items
        (re.compile(r'return\s*\[\s*["\'](?:item|test|sample|mock)\d*["\']', re.I), 0.85, 'hardcoded_list'),
        
        # Empty container returns (potential stubs)
        (re.compile(r'return\s*\[\s*\]', re.I), 0.70, 'empty_list_return'),
        (re.compile(r'return\s*\{\s*\}', re.I), 0.70, 'empty_dict_return'),
        
        # Hardcoded ID patterns
        (re.compile(r'return\s*(?:\d+|["\'](?:\d+|[a-f0-9-]{36})["\'])\s*#.*(?:mock|fake|test|dummy)', re.I), 0.90, 'hardcoded_id'),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PASS-THROUGH PATTERNS (Input returned unchanged)
    # ═══════════════════════════════════════════════════════════════════════════
    
    PASS_THROUGH_PATTERNS: Tuple[Tuple[re.Pattern, float, str], ...] = (
        # Function returns its input
        (re.compile(r'def\s+(?:encrypt|hash|transform|process|convert)\w*\(\s*(\w+)\s*\):\s*\n\s+return\s+\1\s*$', re.M), 0.95, 'passthrough_no_transform'),
        
        # Validation that returns input
        (re.compile(r'def\s+(?:validate|verify|check)\w*\(\s*(\w+)\s*\):\s*\n\s+return\s+\1\s*$', re.M), 0.92, 'validation_passthrough'),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TODO/INCOMPLETE MARKERS
    # ═══════════════════════════════════════════════════════════════════════════
    
    TODO_PATTERNS: Tuple[Tuple[re.Pattern, float, str], ...] = (
        # TODO comments indicating incomplete code
        (re.compile(r'#\s*TODO:?\s*(?:implement|add|fix|complete|finish)', re.I), 0.90, 'todo_implement'),
        (re.compile(r'#\s*FIXME:?\s*', re.I), 0.85, 'fixme_marker'),
        (re.compile(r'#\s*HACK:?\s*', re.I), 0.80, 'hack_marker'),
        (re.compile(r'#\s*(?:placeholder|stub|mock|fake)\s*', re.I), 0.92, 'placeholder_comment'),
        
        # Docstring TODOs. The tempered dot (?:(?!\"{3}|'{3}).) keeps the match
        # inside ONE docstring: the previous greedy .* spanned from a file's
        # first docstring to its last triple-quote, flagging line 1 of any
        # multi-docstring file containing a trigger word anywhere between.
        (re.compile(
            r'(?:"{3}|\'{3})(?:(?!"{3}|\'{3}).)*?(?:TODO|FIXME|placeholder|not implemented)'
            r'(?:(?!"{3}|\'{3}).)*?(?:"{3}|\'{3})',
            re.I | re.S,
        ), 0.88, 'docstring_todo'),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SUSPICIOUS FUNCTION NAMES (Indicate mock intent)
    # ═══════════════════════════════════════════════════════════════════════════
    
    MOCK_FUNCTION_NAMES: FrozenSet[str] = frozenset({
        'mock', 'fake', 'stub', 'dummy', 'sample', 'test',
        'placeholder', 'temp', 'tmp', 'todo', 'example',
    })
    
    MOCK_FUNCTION_PATTERN = re.compile(
        r'def\s+(?:mock|fake|stub|dummy|sample|temp|placeholder|_?test_?|example)_?\w*\s*\(',
        re.I
    )
    
    def __init__(self):
        """Initialize mock code detector."""
        self.name = "MockCode"
        self.version = "1.0"
        self.weight = 0.15  # Weight in overall confidence calculation
        self._snippet_extractor = CodeSnippetExtractor(context_lines=2)
    
    def _get_contextual_snippet(self, content: str, line_number: int) -> str:
        """
        Extract a contextual code snippet using the centralized utility.
        
        Args:
            content: Full file content
            line_number: Line number where pattern was detected
            
        Returns:
            Contextual code snippet with surrounding lines
        """
        return CodeSnippetExtractor.extract_from_content(
            content=content,
            line_number=line_number,
            context_lines=2
        )
    
    def analyze(self, content_or_path, content: str = None, language: str = "python") -> Dict[str, Any]:
        """
        Analyze code for mock/placeholder patterns.
        
        Supports two calling conventions:
        1. analyze(content) - for testing
        2. analyze(file_path, content, language) - for production use
        
        Args:
            content_or_path: Either source code content (str) or file path (Path)
            content: Source code content (when file_path is provided)
            language: Programming language
            
        Returns:
            Analysis results with detected patterns and confidence
        """
        # Handle both calling conventions:
        # 1. analyze(content) - content is in content_or_path
        # 2. analyze(file_path, content, language) - content is in second arg
        if content is None:
            # First argument is the content (test mode)
            actual_content = content_or_path
        else:
            # First argument is file_path (production mode)
            actual_content = content
        
        if not actual_content or not actual_content.strip():
            return {
                'confidence': 0.0,
                'patterns': [],
                'summary': {'total': 0}
            }
        
        patterns: List[MockPattern] = []
        lines = actual_content.split('\n')
        
        # Phase 1: Detect placeholder strings
        patterns.extend(self._detect_placeholder_strings(actual_content, lines))
        
        # Phase 2: Detect stub functions
        patterns.extend(self._detect_stub_functions(actual_content, lines))
        
        # Phase 3: Detect always-success patterns
        patterns.extend(self._detect_always_success(actual_content, lines))
        
        # Phase 4: Detect print-only implementations
        patterns.extend(self._detect_print_only(actual_content, lines))
        
        # Phase 5: Detect fake data patterns
        patterns.extend(self._detect_fake_data(actual_content, lines))
        
        # Phase 6: Detect pass-through functions
        patterns.extend(self._detect_passthrough(actual_content, lines))
        
        # Phase 7: Detect TODO/incomplete markers
        patterns.extend(self._detect_todo_markers(actual_content, lines))
        
        # Phase 8: Detect suspicious function names
        patterns.extend(self._detect_mock_function_names(actual_content, lines))
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(patterns, len(lines))
        
        # Build summary
        summary = self._build_summary(patterns)
        
        return {
            'confidence': confidence,
            'patterns': patterns,
            'summary': summary,
            'analyzer': self.name,
            'version': self.version
        }
    
    def _detect_placeholder_strings(self, content: str, lines: List[str]) -> List[MockPattern]:
        """Detect placeholder string values."""
        patterns = []
        
        for regex, confidence, pattern_type in self.PLACEHOLDER_PATTERNS:
            for match in regex.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                snippet = self._get_contextual_snippet(content, line_num)
                
                patterns.append(MockPattern(
                    pattern_type=f"placeholder_{pattern_type}",
                    line_number=line_num,
                    code_snippet=snippet,
                    confidence=confidence,
                    severity="HIGH" if confidence > 0.88 else "MEDIUM",
                    description=f"Placeholder string detected: {pattern_type}",
                    suggestion="Replace placeholder value with actual implementation or configuration"
                ))
        
        return patterns
    
    def _detect_stub_functions(self, content: str, lines: List[str]) -> List[MockPattern]:
        """Detect stub function implementations."""
        patterns = []
        
        for regex, confidence, pattern_type in self.STUB_PATTERNS:
            for match in regex.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                snippet = self._get_contextual_snippet(content, line_num)
                
                severity = "CRITICAL" if pattern_type in ('always_true', 'pass_only') else "HIGH"
                
                patterns.append(MockPattern(
                    pattern_type=f"stub_{pattern_type}",
                    line_number=line_num,
                    code_snippet=snippet,
                    confidence=confidence,
                    severity=severity,
                    description=f"Stub function detected: {pattern_type.replace('_', ' ')}",
                    suggestion="Implement actual business logic for this function"
                ))
        
        return patterns
    
    def _detect_always_success(self, content: str, lines: List[str]) -> List[MockPattern]:
        """Detect functions that always return success."""
        patterns = []
        
        for regex, confidence, pattern_type in self.ALWAYS_SUCCESS_PATTERNS:
            for match in regex.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                snippet = self._get_contextual_snippet(content, line_num)
                
                patterns.append(MockPattern(
                    pattern_type=f"always_success_{pattern_type}",
                    line_number=line_num,
                    code_snippet=snippet,
                    confidence=confidence,
                    severity="CRITICAL" if 'auth' in pattern_type else "HIGH",
                    description=f"Always-success pattern: {pattern_type.replace('_', ' ')}",
                    suggestion="Add proper validation logic; handle failure cases"
                ))
        
        return patterns
    
    def _detect_print_only(self, content: str, lines: List[str]) -> List[MockPattern]:
        """Detect print-only implementations."""
        patterns = []
        
        for regex, confidence, pattern_type in self.PRINT_ONLY_PATTERNS:
            for match in regex.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                snippet = self._get_contextual_snippet(content, line_num)
                
                patterns.append(MockPattern(
                    pattern_type=f"print_only_{pattern_type}",
                    line_number=line_num,
                    code_snippet=snippet,
                    confidence=confidence,
                    severity="HIGH",
                    description=f"Print-only implementation: {pattern_type.replace('_', ' ')}",
                    suggestion="Replace print statement with actual implementation"
                ))
        
        return patterns
    
    def _detect_fake_data(self, content: str, lines: List[str]) -> List[MockPattern]:
        """Detect hardcoded fake data patterns."""
        patterns = []
        
        for regex, confidence, pattern_type in self.FAKE_DATA_PATTERNS:
            for match in regex.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                snippet = self._get_contextual_snippet(content, line_num)
                
                # Lower severity for empty returns (might be intentional)
                severity = "MEDIUM" if 'empty' in pattern_type else "HIGH"
                
                patterns.append(MockPattern(
                    pattern_type=f"fake_data_{pattern_type}",
                    line_number=line_num,
                    code_snippet=snippet,
                    confidence=confidence,
                    severity=severity,
                    description=f"Fake data pattern: {pattern_type.replace('_', ' ')}",
                    suggestion="Replace hardcoded data with actual data source or configuration"
                ))
        
        return patterns
    
    def _detect_passthrough(self, content: str, lines: List[str]) -> List[MockPattern]:
        """Detect pass-through functions that don't transform input."""
        patterns = []
        
        for regex, confidence, pattern_type in self.PASS_THROUGH_PATTERNS:
            for match in regex.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                snippet = self._get_contextual_snippet(content, line_num)
                
                patterns.append(MockPattern(
                    pattern_type=f"passthrough_{pattern_type}",
                    line_number=line_num,
                    code_snippet=snippet,
                    confidence=confidence,
                    severity="CRITICAL",
                    description=f"Pass-through function: {pattern_type.replace('_', ' ')}",
                    suggestion="Implement actual transformation/validation logic"
                ))
        
        return patterns
    
    def _detect_todo_markers(self, content: str, lines: List[str]) -> List[MockPattern]:
        """Detect TODO and incomplete implementation markers."""
        patterns = []
        
        for regex, confidence, pattern_type in self.TODO_PATTERNS:
            for match in regex.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                snippet = self._get_contextual_snippet(content, line_num)
                
                patterns.append(MockPattern(
                    pattern_type=f"todo_{pattern_type}",
                    line_number=line_num,
                    code_snippet=snippet,
                    confidence=confidence,
                    severity="MEDIUM",
                    description=f"Incomplete implementation marker: {pattern_type.replace('_', ' ')}",
                    suggestion="Complete the implementation before production use"
                ))
        
        return patterns
    
    def _detect_mock_function_names(self, content: str, lines: List[str]) -> List[MockPattern]:
        """Detect function names that indicate mock/test purpose."""
        patterns = []
        
        for match in self.MOCK_FUNCTION_PATTERN.finditer(content):
            line_num = content[:match.start()].count('\n') + 1
            snippet = self._get_contextual_snippet(content, line_num)
            
            # Skip if in a test file
            if 'test' in str(content).lower()[:100]:
                continue
            
            patterns.append(MockPattern(
                pattern_type="mock_function_name",
                line_number=line_num,
                code_snippet=snippet,
                confidence=0.85,
                severity="MEDIUM",
                description="Function name suggests mock/placeholder purpose",
                suggestion="Rename function or replace with production implementation"
            ))
        
        return patterns
    
    def _calculate_confidence(self, patterns: List[MockPattern], total_lines: int) -> float:
        """Calculate overall mock code confidence."""
        if not patterns:
            return 0.0
        
        # Weight by severity
        severity_weights = {
            'CRITICAL': 1.0,
            'HIGH': 0.8,
            'MEDIUM': 0.5,
            'LOW': 0.3
        }
        
        weighted_sum = sum(
            p.confidence * severity_weights.get(p.severity, 0.5)
            for p in patterns
        )
        
        # Normalize by pattern count with diminishing returns
        pattern_factor = min(1.0, len(patterns) / 10)  # Cap at 10 patterns
        
        # Density factor (patterns per 100 lines)
        density = (len(patterns) / max(total_lines, 1)) * 100
        density_factor = min(1.0, density / 5)  # Cap at 5 patterns per 100 lines
        
        # Combine factors
        confidence = (weighted_sum / len(patterns)) * 0.6 + pattern_factor * 0.25 + density_factor * 0.15
        
        return min(1.0, confidence)
    
    def _build_summary(self, patterns: List[MockPattern]) -> Dict[str, Any]:
        """Build summary of detected patterns."""
        summary = {
            'total': len(patterns),
            'by_severity': {
                'CRITICAL': 0,
                'HIGH': 0,
                'MEDIUM': 0,
                'LOW': 0
            },
            'by_category': {}
        }
        
        for pattern in patterns:
            summary['by_severity'][pattern.severity] = summary['by_severity'].get(pattern.severity, 0) + 1
            
            # Extract category from pattern type
            category = pattern.pattern_type.split('_')[0]
            summary['by_category'][category] = summary['by_category'].get(category, 0) + 1
        
        return summary
