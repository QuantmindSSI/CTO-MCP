"""
Antipattern Analyzer - Enterprise-Grade Antipattern Detection
Production-Ready v1.0

Detection Capabilities:
1. Bleeding Edge (Organizational Antipattern)
   - Premature adoption of cutting-edge technologies
   - Unstable dependencies (alpha, beta, rc versions)
   - Experimental APIs and features
   - Frequent version pinning issues

2. Gold Plating (Software Design Antipattern)
   - Over-engineering and unnecessary complexity
   - Unused features and dead code paths
   - Excessive abstraction layers
   - Premature optimization patterns

3. Magic Numbers (Programming Antipattern)
   - Unexplained constants in code
   - Note: Basic detection in PatternAnalyzer, enhanced here

Research-backed patterns from:
- Martin Fowler's Refactoring Patterns
- SourceMaking Antipattern Catalog
- IEEE Software Engineering Best Practices

Target Accuracy: 85%+
"""

import re
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional, FrozenSet
from dataclasses import dataclass, field
from collections import Counter


@dataclass(frozen=True)
class AntipatternMatch:
    """Represents a detected antipattern (immutable for hashability)."""
    antipattern_type: str
    line_number: int
    severity: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    confidence: float  # 0.0 - 1.0
    context: str
    suggestion: str
    category: str  # 'organizational', 'design', 'programming'
    subcategory: str = ""  # More specific classification


class AntipatternAnalyzer:
    """
    Enterprise-Grade Antipattern Analyzer v1.0.
    
    Target: 85%+ accuracy for antipattern detection.
    
    Detects:
    - Bleeding Edge: Premature technology adoption
    - Gold Plating: Over-engineering and unnecessary features
    - Magic Numbers: Enhanced detection (complements PatternAnalyzer)
    """
    
    # ═══════════════════════════════════════════════════════════════════════════
    # BLEEDING EDGE DETECTION - Organizational Antipattern
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Unstable version patterns in dependency files
    UNSTABLE_VERSION_PATTERNS: Tuple[Tuple[str, str, float], ...] = (
        # Alpha/Beta/RC versions - works with ==, :, or space separators
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?(alpha|alfa)[\d.-]*', 'alpha_version', 0.92),
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?beta[\d.-]*', 'beta_version', 0.88),
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?rc[\d.-]*', 'release_candidate', 0.85),
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?dev[\d.-]*', 'dev_version', 0.90),
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?preview[\d.-]*', 'preview_version', 0.88),
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?canary[\d.-]*', 'canary_version', 0.90),
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?nightly[\d.-]*', 'nightly_version', 0.92),
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?unstable[\d.-]*', 'unstable_version', 0.95),
        (r'[\w-]+[=]{1,2}[\d.]*[-.]?experimental[\d.-]*', 'experimental_version', 0.90),
        (r'[\w-]+[=]{1,2}0\.0\.\d+', 'zero_zero_version', 0.80),
        # JSON format for package.json ("package": "version")
        (r'"[\w-]+"\s*:\s*"[\d.]*[-.]?(alpha|alfa)[\d.-]*"', 'alpha_version', 0.92),
        (r'"[\w-]+"\s*:\s*"[\d.]*[-.]?beta[\d.-]*"', 'beta_version', 0.88),
        (r'"[\w-]+"\s*:\s*"[\d.]*[-.]?rc[\d.-]*"', 'release_candidate', 0.85),
        (r'"[\w-]+"\s*:\s*"[\d.]*[-.]?nightly[\d.-]*"', 'nightly_version', 0.92),
        (r'"[\w-]+"\s*:\s*"[\d.]*[-.]?unstable[\d.-]*"', 'unstable_version', 0.95),
    )
    
    # Bleeding edge framework/library patterns
    BLEEDING_EDGE_IMPORTS: FrozenSet[str] = frozenset({
        # Experimental Python features
        '__future__',
        # Known experimental/unstable packages
        'typing_extensions',  # Often for cutting-edge typing features
    })
    
    # Experimental API patterns in code
    EXPERIMENTAL_API_PATTERNS: Tuple[Tuple[str, str, float], ...] = (
        # Python experimental
        (r'@experimental', 'experimental_decorator', 0.90),
        (r'@beta', 'beta_decorator', 0.88),
        (r'@unstable', 'unstable_decorator', 0.92),
        (r'@deprecated.*replacement', 'using_deprecated_api', 0.75),
        (r'#\s*TODO:?\s*remove\s+when\s+stable', 'todo_remove_unstable', 0.85),
        (r'#\s*HACK:?\s*workaround', 'hack_workaround', 0.80),
        (r'#\s*FIXME:?\s*unstable', 'fixme_unstable', 0.88),
        
        # JavaScript/TypeScript experimental
        (r'@experimental', 'experimental_decorator_js', 0.90),
        (r"['\"]use\s+experimental['\"]", 'use_experimental', 0.92),
        (r'__experimental__', 'dunder_experimental', 0.90),
        
        # Feature flags suggesting instability
        (r'ENABLE_EXPERIMENTAL', 'experimental_flag', 0.85),
        (r'USE_BETA_', 'beta_flag', 0.85),
        (r'FEATURE_FLAG_.*UNSTABLE', 'unstable_feature_flag', 0.88),
    )
    
    # Dependency files to check
    DEPENDENCY_FILES: FrozenSet[str] = frozenset({
        'requirements.txt', 'requirements-dev.txt', 'requirements-test.txt',
        'setup.py', 'setup.cfg', 'pyproject.toml',
        'package.json', 'package-lock.json',
        'Pipfile', 'Pipfile.lock',
        'Cargo.toml', 'go.mod', 'pom.xml', 'build.gradle',
        'Gemfile', 'composer.json',
    })
    
    # ═══════════════════════════════════════════════════════════════════════════
    # GOLD PLATING DETECTION - Software Design Antipattern
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Over-engineering indicators
    OVER_ENGINEERING_PATTERNS: Tuple[Tuple[str, str, float], ...] = (
        # Abstract factory for single implementation
        (r'class\s+Abstract\w*Factory\b(?!.*(Concrete|Impl|Default)\w*Factory)', 
         'single_factory', 0.75),
        
        # Builder pattern for simple objects (< 5 fields typically)
        (r'class\s+\w*Builder\b.*\n(?:.*\n){0,10}.*def\s+build\s*\(', 
         'simple_object_builder', 0.70),
        
        # Strategy pattern with single strategy
        (r'class\s+\w*Strategy\b.*\n(?:(?!class\s+\w*Strategy).*\n){0,50}(?!class\s+\w*Strategy)', 
         'single_strategy', 0.72),
        
        # Excessive interface definitions
        (r'class\s+I[A-Z]\w*\s*\(\s*(?:ABC|Protocol|Interface)\s*\)', 
         'interface_definition', 0.60),
        
        # Deep inheritance (more than 3 levels)
        (r'class\s+\w+\s*\(\s*\w+\s*\)\s*:.*#.*extends.*extends', 
         'deep_inheritance', 0.78),
        
        # Visitor pattern (often over-engineered)
        (r'class\s+\w*Visitor\b.*def\s+visit_\w+', 'visitor_pattern', 0.65),
        
        # Adapter wrapping simple functionality
        (r'class\s+\w*Adapter\b.*\n(?:.*\n){0,15}.*def\s+\w+\s*\(self[,\)]', 
         'simple_adapter', 0.68),
    )
    
    # Unused/Dead code patterns
    DEAD_CODE_PATTERNS: Tuple[Tuple[str, str, float], ...] = (
        # Functions that only pass
        (r'def\s+\w+\s*\([^)]*\)\s*:\s*(?:\n\s*["\'].*["\'])?\s*\n\s+pass\s*$', 
         'pass_only_function', 0.85),
        
        # Empty except blocks
        (r'except\s*(?:\w+\s*)?:\s*\n\s*pass\s*$', 'empty_except', 0.80),
        
        # Commented out code blocks
        (r'#\s*(?:def|class|if|for|while|try)\s+\w+', 'commented_code', 0.75),
        
        # TODO/FIXME suggesting unused code
        (r'#\s*TODO:?\s*(?:remove|delete|cleanup)\s+(?:unused|dead)', 
         'todo_remove_unused', 0.82),
        
        # Functions with NotImplementedError only
        (r'def\s+\w+\s*\([^)]*\)\s*:\s*\n\s*raise\s+NotImplementedError', 
         'not_implemented', 0.70),
    )
    
    # Premature optimization patterns
    PREMATURE_OPTIMIZATION_PATTERNS: Tuple[Tuple[str, str, float], ...] = (
        # Manual caching without profiling evidence
        (r'_cache\s*=\s*\{\}', 'manual_cache', 0.65),
        (r'@lru_cache\s*\(\s*maxsize\s*=\s*(?:None|\d{4,})\)', 
         'unbounded_cache', 0.72),
        
        # Micro-optimizations
        (r'#.*(?:optimization|optimize|performance|faster|speed)', 
         'optimization_comment', 0.60),
        (r'\bslots\b\s*=', 'slots_usage', 0.55),  # May be premature
        
        # Complex comprehensions (nested > 2 levels)
        (r'\[.*\[.*\[.*for.*for.*for', 'nested_comprehension', 0.78),
        
        # Bit manipulation for simple operations
        (r'<<\s*\d+|>>\s*\d+|&\s*0x|^\s*0x|\|\s*0x', 'bit_manipulation', 0.55),
    )
    
    # Excessive abstraction patterns
    EXCESSIVE_ABSTRACTION_PATTERNS: Tuple[Tuple[str, str, float], ...] = (
        # Too many design pattern keywords in one file
        (r'(?:Factory|Builder|Strategy|Observer|Visitor|Adapter|Decorator|Proxy|Facade)', 
         'design_pattern_keyword', 0.50),  # Count these, threshold on quantity
        
        # Wrapper classes that just delegate
        (r'def\s+(\w+)\s*\(self,\s*\*args,\s*\*\*kwargs\)\s*:\s*\n\s*return\s+self\.\w+\.\1\s*\(\*args', 
         'pass_through_delegation', 0.75),
        
        # Classes with only one method
        (r'class\s+\w+\s*(?:\([^)]*\))?\s*:\s*\n(?:\s*["\'].*["\'].*\n)?(?:\s*\n)*\s*def\s+\w+.*(?:\n(?!\s*def).*)*$', 
         'single_method_class', 0.70),
        
        # Excessive use of ABC/Protocol
        (r'from\s+abc\s+import\s+(?:ABC|abstractmethod)', 'abc_import', 0.40),
        (r'from\s+typing\s+import\s+Protocol', 'protocol_import', 0.40),
    )
    
    # Feature flag overload
    FEATURE_FLAG_PATTERNS: Tuple[Tuple[str, str, float], ...] = (
        (r'if\s+(?:ENABLE_|DISABLE_|USE_|FEATURE_|FLAG_)\w+', 'feature_flag_check', 0.50),
        (r'(?:ENABLE_|DISABLE_|USE_|FEATURE_|FLAG_)\w+\s*=\s*(?:True|False|true|false)', 
         'feature_flag_definition', 0.50),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAGIC NUMBERS ENHANCEMENT - Programming Antipattern
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Domain-specific magic numbers (harder to detect)
    DOMAIN_MAGIC_PATTERNS: Tuple[Tuple[str, str, float], ...] = (
        # HTTP status codes used directly
        (r'==\s*(?:200|201|204|301|302|400|401|403|404|500|502|503)\b', 
         'http_status_magic', 0.75),
        
        # Port numbers used directly
        (r'(?:port|PORT)\s*[=:]\s*(?:80|443|8080|8443|3000|5000|8000|9000)\b', 
         'port_magic', 0.70),
        
        # Timeout values
        (r'timeout\s*[=:]\s*\d{2,}', 'timeout_magic', 0.72),
        
        # Retry counts
        (r'(?:retry|retries|max_retries)\s*[=:]\s*\d+', 'retry_magic', 0.68),
        
        # Buffer sizes without constants
        (r'buffer\s*[=:]\s*\d{3,}', 'buffer_size_magic', 0.75),
        
        # Sleep/delay values
        (r'(?:sleep|delay|wait)\s*\(\s*\d+(?:\.\d+)?\s*\)', 'sleep_magic', 0.72),
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # INITIALIZATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def __init__(self):
        """Initialize with compiled patterns."""
        # Compile bleeding edge patterns
        self._unstable_version_patterns = [
            (re.compile(pattern, re.IGNORECASE | re.MULTILINE), name, conf)
            for pattern, name, conf in self.UNSTABLE_VERSION_PATTERNS
        ]
        self._experimental_api_patterns = [
            (re.compile(pattern, re.IGNORECASE | re.MULTILINE), name, conf)
            for pattern, name, conf in self.EXPERIMENTAL_API_PATTERNS
        ]
        
        # Compile gold plating patterns
        self._over_engineering_patterns = [
            (re.compile(pattern, re.MULTILINE | re.DOTALL), name, conf)
            for pattern, name, conf in self.OVER_ENGINEERING_PATTERNS
        ]
        self._dead_code_patterns = [
            (re.compile(pattern, re.MULTILINE), name, conf)
            for pattern, name, conf in self.DEAD_CODE_PATTERNS
        ]
        self._premature_opt_patterns = [
            (re.compile(pattern, re.IGNORECASE | re.MULTILINE), name, conf)
            for pattern, name, conf in self.PREMATURE_OPTIMIZATION_PATTERNS
        ]
        self._excessive_abstraction_patterns = [
            (re.compile(pattern, re.MULTILINE | re.DOTALL), name, conf)
            for pattern, name, conf in self.EXCESSIVE_ABSTRACTION_PATTERNS
        ]
        self._feature_flag_patterns = [
            (re.compile(pattern, re.IGNORECASE), name, conf)
            for pattern, name, conf in self.FEATURE_FLAG_PATTERNS
        ]
        
        # Compile magic number patterns
        self._domain_magic_patterns = [
            (re.compile(pattern, re.IGNORECASE), name, conf)
            for pattern, name, conf in self.DOMAIN_MAGIC_PATTERNS
        ]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN ANALYSIS ENTRY POINT
    # ═══════════════════════════════════════════════════════════════════════════
    
    def analyze(self, file_path: Path, content: str, language: str) -> Dict:
        """
        Analyze code for antipatterns.
        
        Args:
            file_path: Path to the file being analyzed
            content: File content
            language: Programming language
            
        Returns:
            Dict with confidence score, antipatterns, and summary
        """
        lines = content.split('\n')
        matches: List[AntipatternMatch] = []
        
        # Determine if this is a dependency file
        is_dependency_file = file_path.name in self.DEPENDENCY_FILES
        
        # Phase 1: Bleeding Edge Detection
        if is_dependency_file:
            matches.extend(self._detect_bleeding_edge_dependencies(content, lines, file_path))
        else:
            matches.extend(self._detect_bleeding_edge_code(content, lines, language))
        
        # Phase 2: Gold Plating Detection
        matches.extend(self._detect_gold_plating(content, lines, language))
        
        # Phase 3: Enhanced Magic Number Detection
        matches.extend(self._detect_domain_magic_numbers(content, lines, language))
        
        # Calculate confidence
        confidence = self._calculate_confidence(matches, len(lines))
        
        # Generate summary
        summary = self._generate_summary(matches, confidence)
        
        return {
            'confidence': confidence,
            'antipatterns': matches,
            'patterns': [self._match_to_pattern(m) for m in matches],
            'summary': summary,
            'antipattern_counts': self._count_antipatterns(matches),
            'severity_distribution': self._severity_distribution(matches),
            'category_distribution': self._category_distribution(matches),
            'analyzer_version': '1.0',
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # BLEEDING EDGE DETECTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _detect_bleeding_edge_dependencies(
        self, content: str, lines: List[str], file_path: Path
    ) -> List[AntipatternMatch]:
        """Detect bleeding edge patterns in dependency files."""
        matches: List[AntipatternMatch] = []
        
        for line_num, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith('#') or line.strip().startswith('//'):
                continue
            
            for pattern, pattern_name, confidence in self._unstable_version_patterns:
                if pattern.search(line):
                    severity = self._get_bleeding_edge_severity(pattern_name)
                    matches.append(AntipatternMatch(
                        antipattern_type='bleeding_edge',
                        line_number=line_num,
                        severity=severity,
                        confidence=confidence,
                        context=line.strip()[:100],
                        suggestion=self._get_bleeding_edge_suggestion(pattern_name),
                        category='organizational',
                        subcategory=pattern_name
                    ))
                    break  # Only one match per line
        
        return matches
    
    def _detect_bleeding_edge_code(
        self, content: str, lines: List[str], language: str
    ) -> List[AntipatternMatch]:
        """Detect bleeding edge patterns in source code."""
        matches: List[AntipatternMatch] = []
        
        for line_num, line in enumerate(lines, 1):
            for pattern, pattern_name, confidence in self._experimental_api_patterns:
                match = pattern.search(line)
                if match:
                    severity = self._get_bleeding_edge_severity(pattern_name)
                    matches.append(AntipatternMatch(
                        antipattern_type='bleeding_edge',
                        line_number=line_num,
                        severity=severity,
                        confidence=confidence,
                        context=line.strip()[:100],
                        suggestion=self._get_bleeding_edge_suggestion(pattern_name),
                        category='organizational',
                        subcategory=pattern_name
                    ))
                    break
        
        return matches
    
    def _get_bleeding_edge_severity(self, pattern_name: str) -> str:
        """Get severity for bleeding edge pattern."""
        critical_patterns = {'unstable_version', 'nightly_version', 'experimental_version'}
        high_patterns = {'alpha_version', 'dev_version', 'canary_version', 
                        'experimental_decorator', 'dunder_experimental'}
        
        if pattern_name in critical_patterns:
            return 'CRITICAL'
        elif pattern_name in high_patterns:
            return 'HIGH'
        else:
            return 'MEDIUM'
    
    def _get_bleeding_edge_suggestion(self, pattern_name: str) -> str:
        """Get suggestion for bleeding edge pattern."""
        suggestions = {
            'alpha_version': "Alpha versions are unstable. Wait for stable release or pin to last stable version.",
            'beta_version': "Beta versions may have bugs. Consider waiting for stable release.",
            'release_candidate': "RC versions are near-stable but may still have issues. Monitor for stable release.",
            'dev_version': "Dev versions are for development only. Use stable version in production.",
            'preview_version': "Preview versions are for evaluation. Not recommended for production.",
            'canary_version': "Canary versions have latest changes but may be unstable.",
            'nightly_version': "Nightly builds are experimental. Use stable version instead.",
            'unstable_version': "Explicitly unstable. Do not use in production.",
            'experimental_version': "Experimental features may change or be removed.",
            'zero_zero_version': "0.0.x versions indicate very early development stage.",
            'early_version': "0.x versions may have breaking changes. Pin version carefully.",
            'experimental_decorator': "Experimental APIs may change without notice.",
            'beta_decorator': "Beta APIs are not yet stable.",
            'unstable_decorator': "Unstable APIs should not be used in production.",
            'using_deprecated_api': "Replace deprecated API with recommended alternative.",
            'hack_workaround': "Document workaround and track upstream fix.",
            'fixme_unstable': "Track and fix stability issues.",
            'experimental_flag': "Feature flags for experimental features indicate risk.",
            'beta_flag': "Beta feature flags should be monitored.",
            'unstable_feature_flag': "Unstable feature flags should be disabled in production.",
        }
        return suggestions.get(pattern_name, "Review and consider stable alternatives.")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # GOLD PLATING DETECTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _detect_gold_plating(
        self, content: str, lines: List[str], language: str
    ) -> List[AntipatternMatch]:
        """Detect gold plating patterns."""
        matches: List[AntipatternMatch] = []
        
        # 1. Over-engineering patterns
        matches.extend(self._detect_over_engineering(content, lines, language))
        
        # 2. Dead code patterns
        matches.extend(self._detect_dead_code(content, lines, language))
        
        # 3. Premature optimization
        matches.extend(self._detect_premature_optimization(content, lines, language))
        
        # 4. Excessive abstraction
        matches.extend(self._detect_excessive_abstraction(content, lines, language))
        
        # 5. Feature flag overload
        matches.extend(self._detect_feature_flag_overload(content, lines))
        
        return matches
    
    def _detect_over_engineering(
        self, content: str, lines: List[str], language: str
    ) -> List[AntipatternMatch]:
        """Detect over-engineering patterns."""
        matches: List[AntipatternMatch] = []
        
        for pattern, pattern_name, confidence in self._over_engineering_patterns:
            for match in pattern.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                context = content[match.start():match.end()][:100]
                
                matches.append(AntipatternMatch(
                    antipattern_type='gold_plating',
                    line_number=line_num,
                    severity='MEDIUM',
                    confidence=confidence,
                    context=context.replace('\n', ' ').strip(),
                    suggestion=self._get_gold_plating_suggestion(pattern_name),
                    category='design',
                    subcategory=pattern_name
                ))
        
        return matches
    
    def _detect_dead_code(
        self, content: str, lines: List[str], language: str
    ) -> List[AntipatternMatch]:
        """Detect dead/unused code patterns."""
        matches: List[AntipatternMatch] = []
        
        for pattern, pattern_name, confidence in self._dead_code_patterns:
            for match in pattern.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                context = match.group(0)[:100]
                
                matches.append(AntipatternMatch(
                    antipattern_type='gold_plating',
                    line_number=line_num,
                    severity='LOW' if pattern_name == 'commented_code' else 'MEDIUM',
                    confidence=confidence,
                    context=context.replace('\n', ' ').strip(),
                    suggestion=self._get_gold_plating_suggestion(pattern_name),
                    category='design',
                    subcategory=pattern_name
                ))
        
        return matches
    
    def _detect_premature_optimization(
        self, content: str, lines: List[str], language: str
    ) -> List[AntipatternMatch]:
        """Detect premature optimization patterns."""
        matches: List[AntipatternMatch] = []
        
        for pattern, pattern_name, confidence in self._premature_opt_patterns:
            for match in pattern.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                context = match.group(0)[:100]
                
                # Lower severity for these - they might be legitimate
                severity = 'LOW' if pattern_name in ('slots_usage', 'bit_manipulation', 'optimization_comment') else 'MEDIUM'
                
                matches.append(AntipatternMatch(
                    antipattern_type='gold_plating',
                    line_number=line_num,
                    severity=severity,
                    confidence=confidence,
                    context=context.replace('\n', ' ').strip(),
                    suggestion=self._get_gold_plating_suggestion(pattern_name),
                    category='design',
                    subcategory=pattern_name
                ))
        
        return matches
    
    def _detect_excessive_abstraction(
        self, content: str, lines: List[str], language: str
    ) -> List[AntipatternMatch]:
        """Detect excessive abstraction patterns."""
        matches: List[AntipatternMatch] = []
        
        # Count design pattern keywords
        design_pattern_count = 0
        for pattern, pattern_name, _ in self._excessive_abstraction_patterns:
            count = len(pattern.findall(content))
            if pattern_name == 'design_pattern_keyword':
                design_pattern_count = count
            elif count > 0:
                for match in pattern.finditer(content):
                    line_num = content[:match.start()].count('\n') + 1
                    context = match.group(0)[:100]
                    
                    matches.append(AntipatternMatch(
                        antipattern_type='gold_plating',
                        line_number=line_num,
                        severity='MEDIUM',
                        confidence=self._excessive_abstraction_patterns[
                            [p[1] for p in self.EXCESSIVE_ABSTRACTION_PATTERNS].index(pattern_name)
                        ][2],
                        context=context.replace('\n', ' ').strip(),
                        suggestion=self._get_gold_plating_suggestion(pattern_name),
                        category='design',
                        subcategory=pattern_name
                    ))
        
        # Flag if too many design patterns in one file
        if design_pattern_count > 5:
            matches.append(AntipatternMatch(
                antipattern_type='gold_plating',
                line_number=1,
                severity='HIGH',
                confidence=min(0.85, 0.5 + design_pattern_count * 0.05),
                context=f"File uses {design_pattern_count} design pattern keywords",
                suggestion="Consider if all these patterns are necessary. Simplify where possible.",
                category='design',
                subcategory='pattern_overload'
            ))
        
        return matches
    
    def _detect_feature_flag_overload(
        self, content: str, lines: List[str]
    ) -> List[AntipatternMatch]:
        """Detect excessive feature flags."""
        matches: List[AntipatternMatch] = []
        
        flag_definitions = 0
        flag_checks = 0
        
        for pattern, pattern_name, _ in self._feature_flag_patterns:
            count = len(pattern.findall(content))
            if pattern_name == 'feature_flag_definition':
                flag_definitions = count
            else:
                flag_checks = count
        
        total_flags = flag_definitions + flag_checks
        
        if total_flags > 10:
            severity = 'HIGH' if total_flags > 20 else 'MEDIUM'
            matches.append(AntipatternMatch(
                antipattern_type='gold_plating',
                line_number=1,
                severity=severity,
                confidence=min(0.82, 0.5 + total_flags * 0.02),
                context=f"File has {flag_definitions} flag definitions and {flag_checks} flag checks",
                suggestion="Consider consolidating feature flags. Too many flags increase complexity.",
                category='design',
                subcategory='feature_flag_overload'
            ))
        
        return matches
    
    def _get_gold_plating_suggestion(self, pattern_name: str) -> str:
        """Get suggestion for gold plating pattern."""
        suggestions = {
            'single_factory': "Abstract Factory without multiple implementations is over-engineering. Use simple factory method.",
            'simple_object_builder': "Builder pattern for simple objects adds unnecessary complexity. Use constructor or factory.",
            'single_strategy': "Strategy pattern with single strategy is premature abstraction. Use direct implementation.",
            'interface_definition': "Interface without multiple implementations may be premature. YAGNI principle.",
            'deep_inheritance': "Prefer composition over deep inheritance. Flatter hierarchies are easier to maintain.",
            'visitor_pattern': "Visitor pattern is complex. Ensure the complexity is justified.",
            'simple_adapter': "Simple adapter that just delegates may be unnecessary indirection.",
            'pass_only_function': "Empty function suggests incomplete implementation or dead code. Remove or implement.",
            'empty_except': "Empty except block hides errors. Log or handle the exception.",
            'commented_code': "Commented code should be removed. Use version control for history.",
            'todo_remove_unused': "Remove unused code rather than leaving it commented.",
            'not_implemented': "NotImplementedError suggests incomplete design. Implement or remove.",
            'manual_cache': "Manual caching is error-prone. Use @lru_cache or dedicated caching library.",
            'unbounded_cache': "Unbounded cache can cause memory issues. Set appropriate maxsize.",
            'optimization_comment': "Premature optimization is the root of all evil. Profile first.",
            'slots_usage': "__slots__ is micro-optimization. Use only after profiling shows benefit.",
            'nested_comprehension': "Deeply nested comprehensions are hard to read. Use explicit loops.",
            'bit_manipulation': "Bit manipulation for non-performance-critical code reduces readability.",
            'pass_through_delegation': "Pass-through delegation adds indirection without value.",
            'single_method_class': "Class with single method should probably be a function.",
            'abc_import': "ABC/abstractmethod is powerful but can lead to over-abstraction.",
            'protocol_import': "Protocol is useful for structural typing but can be overused.",
            'pattern_overload': "Too many design patterns in one file suggests over-engineering.",
            'feature_flag_overload': "Too many feature flags increase code complexity and maintenance burden.",
        }
        return suggestions.get(pattern_name, "Review for potential simplification.")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ENHANCED MAGIC NUMBER DETECTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _detect_domain_magic_numbers(
        self, content: str, lines: List[str], language: str
    ) -> List[AntipatternMatch]:
        """Detect domain-specific magic numbers."""
        matches: List[AntipatternMatch] = []
        
        for line_num, line in enumerate(lines, 1):
            # Skip comments
            if self._is_comment_line(line.strip(), language):
                continue
            
            for pattern, pattern_name, confidence in self._domain_magic_patterns:
                match = pattern.search(line)
                if match:
                    matches.append(AntipatternMatch(
                        antipattern_type='magic_numbers',
                        line_number=line_num,
                        severity='MEDIUM',
                        confidence=confidence,
                        context=line.strip()[:100],
                        suggestion=self._get_magic_number_suggestion(pattern_name),
                        category='programming',
                        subcategory=pattern_name
                    ))
                    break
        
        return matches
    
    def _get_magic_number_suggestion(self, pattern_name: str) -> str:
        """Get suggestion for magic number pattern."""
        suggestions = {
            'http_status_magic': "Use HTTP status constants (e.g., status.HTTP_200_OK or HTTPStatus.OK).",
            'port_magic': "Extract port numbers to configuration or named constants.",
            'timeout_magic': "Extract timeout values to named constants (e.g., DEFAULT_TIMEOUT_SECONDS).",
            'retry_magic': "Extract retry counts to named constants (e.g., MAX_RETRY_ATTEMPTS).",
            'buffer_size_magic': "Extract buffer sizes to named constants (e.g., DEFAULT_BUFFER_SIZE).",
            'sleep_magic': "Extract delay values to named constants (e.g., POLLING_INTERVAL_SECONDS).",
        }
        return suggestions.get(pattern_name, "Extract magic number to named constant.")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _is_comment_line(self, line: str, language: str) -> bool:
        """Check if line is a comment."""
        stripped = line.strip()
        if language in ('python', 'ruby', 'perl', 'shell', 'bash'):
            return stripped.startswith('#')
        elif language in ('javascript', 'typescript', 'java', 'c', 'cpp', 'csharp', 'go', 'rust'):
            return stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*')
        return stripped.startswith('#') or stripped.startswith('//')
    
    def _calculate_confidence(
        self, matches: List[AntipatternMatch], total_lines: int
    ) -> float:
        """Calculate overall confidence score."""
        if not matches:
            return 0.0
        
        severity_weights = {'CRITICAL': 1.0, 'HIGH': 0.75, 'MEDIUM': 0.5, 'LOW': 0.25}
        
        total_weight = sum(
            severity_weights.get(m.severity, 0.5) * m.confidence
            for m in matches
        )
        
        # Normalize by code size
        size_factor = max(1, total_lines / 100)
        normalized = total_weight / size_factor
        
        # Cap at 0.92 for antipattern analysis
        return min(0.92, normalized)
    
    def _generate_summary(
        self, matches: List[AntipatternMatch], confidence: float
    ) -> Dict:
        """Generate analysis summary."""
        return {
            'total_antipatterns': len(matches),
            'confidence': confidence,
            'risk_level': self._get_risk_level(confidence),
            'antipattern_distribution': self._count_antipatterns(matches),
            'category_distribution': self._category_distribution(matches),
            'severity_distribution': self._severity_distribution(matches),
            'top_issues': self._get_top_issues(matches),
            'recommendations': self._get_recommendations(matches),
        }
    
    def _count_antipatterns(self, matches: List[AntipatternMatch]) -> Dict[str, int]:
        """Count antipattern occurrences by type."""
        return dict(Counter(m.antipattern_type for m in matches))
    
    def _category_distribution(self, matches: List[AntipatternMatch]) -> Dict[str, int]:
        """Get distribution by category."""
        return dict(Counter(m.category for m in matches))
    
    def _severity_distribution(self, matches: List[AntipatternMatch]) -> Dict[str, int]:
        """Get severity distribution."""
        return dict(Counter(m.severity for m in matches))
    
    def _get_top_issues(self, matches: List[AntipatternMatch], limit: int = 5) -> List[Dict]:
        """Get top issues sorted by severity and confidence."""
        severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        sorted_matches = sorted(
            matches,
            key=lambda m: (severity_order.get(m.severity, 4), -m.confidence)
        )
        return [
            {
                'type': m.antipattern_type,
                'subcategory': m.subcategory,
                'line': m.line_number,
                'severity': m.severity,
                'confidence': m.confidence,
                'context': m.context[:50],
            }
            for m in sorted_matches[:limit]
        ]
    
    def _get_recommendations(self, matches: List[AntipatternMatch]) -> List[str]:
        """Generate recommendations based on detected antipatterns."""
        recommendations = []
        
        antipattern_counts = self._count_antipatterns(matches)
        
        if antipattern_counts.get('bleeding_edge', 0) > 0:
            recommendations.append(
                "Consider stabilizing dependencies. Bleeding edge technologies "
                "increase maintenance burden and production risk."
            )
        
        if antipattern_counts.get('gold_plating', 0) > 3:
            recommendations.append(
                "Signs of over-engineering detected. Apply YAGNI (You Aren't Gonna Need It) "
                "principle and simplify where possible."
            )
        
        if antipattern_counts.get('magic_numbers', 0) > 2:
            recommendations.append(
                "Multiple magic numbers detected. Extract to named constants "
                "for better maintainability."
            )
        
        if not recommendations:
            recommendations.append("Code follows good practices. Continue monitoring.")
        
        return recommendations
    
    def _get_risk_level(self, confidence: float) -> str:
        """Determine risk level from confidence."""
        if confidence >= 0.75:
            return 'CRITICAL'
        elif confidence >= 0.55:
            return 'HIGH'
        elif confidence >= 0.35:
            return 'MEDIUM'
        elif confidence >= 0.15:
            return 'LOW'
        return 'MINIMAL'
    
    def _match_to_pattern(self, match: AntipatternMatch) -> Dict:
        """Convert match to pattern dict for compatibility."""
        return {
            'type': match.antipattern_type,
            'subcategory': match.subcategory,
            'line': match.line_number,
            'severity': match.severity,
            'confidence': match.confidence,
            'context': match.context,
            'suggestion': match.suggestion,
            'category': match.category,
        }
