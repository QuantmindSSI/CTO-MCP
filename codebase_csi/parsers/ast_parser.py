"""
AST Parser - Multi-Language Abstract Syntax Tree Parser

Uses tree-sitter for accurate AST parsing across 10+ languages.
Falls back to Python's built-in ast module or regex when tree-sitter unavailable.

Features:
- Unified API for all supported languages
- Accurate complexity calculation
- Function/class extraction
- Variable scope tracking
- Error-tolerant parsing (partial results on syntax errors)

Architecture:
    ┌─────────────────────────────────────────────────┐
    │              ASTParser                          │
    ├─────────────────────────────────────────────────┤
    │  parse_file() / parse_code()                    │
    │       │                                         │
    │       ├── tree-sitter available? ──→ TreeSitter│
    │       │                                         │
    │       ├── Python file? ──→ Built-in ast        │
    │       │                                         │
    │       └── Fallback ──→ Regex-based parsing     │
    └─────────────────────────────────────────────────┘
"""

import re
import ast as python_ast
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Union, Set
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class ParserBackend(Enum):
    """Parser backend used for analysis."""
    TREE_SITTER = "tree_sitter"
    PYTHON_AST = "python_ast"
    REGEX = "regex"


@dataclass
class FunctionInfo:
    """Information about a function/method."""
    name: str
    line_start: int
    line_end: int
    parameters: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    docstring: Optional[str] = None
    complexity: int = 1
    is_async: bool = False
    is_method: bool = False
    decorators: List[str] = field(default_factory=list)
    nested_functions: List['FunctionInfo'] = field(default_factory=list)


@dataclass
class ClassInfo:
    """Information about a class."""
    name: str
    line_start: int
    line_end: int
    base_classes: List[str] = field(default_factory=list)
    methods: List[FunctionInfo] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    is_dataclass: bool = False


@dataclass
class ImportInfo:
    """Information about an import statement."""
    module: str
    names: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    line_number: int = 0
    is_from_import: bool = False


@dataclass
class VariableInfo:
    """Information about a variable."""
    name: str
    line_number: int
    type_annotation: Optional[str] = None
    scope: str = "module"  # module, class, function, local
    is_constant: bool = False


@dataclass
class ParseResult:
    """Complete parse result for a file."""
    # Metadata
    file_path: Optional[str] = None
    language: str = "unknown"
    backend: ParserBackend = ParserBackend.REGEX
    parse_success: bool = True
    parse_errors: List[str] = field(default_factory=list)
    
    # Extracted information
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    variables: List[VariableInfo] = field(default_factory=list)
    
    # Metrics
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    complexity: int = 0
    max_nesting_depth: int = 0
    
    # Raw data
    raw_tree: Optional[Any] = None  # tree-sitter tree or Python AST


# ═══════════════════════════════════════════════════════════════════════════════
# LANGUAGE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

LANGUAGE_EXTENSIONS: Dict[str, str] = {
    '.py': 'python',
    '.pyw': 'python',
    '.pyi': 'python',
    '.js': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.java': 'java',
    '.go': 'go',
    '.rs': 'rust',
    '.rb': 'ruby',
    '.php': 'php',
    '.c': 'c',
    '.h': 'c',
    '.cpp': 'cpp',
    '.cxx': 'cpp',
    '.cc': 'cpp',
    '.hpp': 'cpp',
    '.hxx': 'cpp',
    '.cs': 'csharp',
    '.swift': 'swift',
    '.kt': 'kotlin',
    '.kts': 'kotlin',
    '.scala': 'scala',
    '.lua': 'lua',
    '.sh': 'bash',
    '.bash': 'bash',
    '.zsh': 'bash',
}

# Tree-sitter grammar package names
TREE_SITTER_GRAMMARS: Dict[str, str] = {
    'python': 'tree_sitter_python',
    'javascript': 'tree_sitter_javascript',
    'typescript': 'tree_sitter_typescript',
    'java': 'tree_sitter_java',
    'go': 'tree_sitter_go',
    'rust': 'tree_sitter_rust',
    'ruby': 'tree_sitter_ruby',
    'php': 'tree_sitter_php',
    'c': 'tree_sitter_c',
    'cpp': 'tree_sitter_cpp',
}


# ═══════════════════════════════════════════════════════════════════════════════
# TREE-SITTER INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════

class TreeSitterParser:
    """Tree-sitter based parser for multi-language support."""
    
    _parsers: Dict[str, Any] = {}
    _available: Optional[bool] = None
    _available_languages: Set[str] = set()
    
    @classmethod
    def is_available(cls) -> bool:
        """Check if tree-sitter is available."""
        if cls._available is None:
            try:
                from tree_sitter import Parser
                cls._available = True
            except ImportError:
                cls._available = False
                logger.debug("tree-sitter not installed, using fallback parsers")
        return cls._available
    
    @classmethod
    def get_available_languages(cls) -> Set[str]:
        """Get set of languages with available grammars."""
        if not cls.is_available():
            return set()
        
        if not cls._available_languages:
            for lang, package in TREE_SITTER_GRAMMARS.items():
                try:
                    __import__(package)
                    cls._available_languages.add(lang)
                except ImportError:
                    pass
        
        return cls._available_languages
    
    @classmethod
    def get_parser(cls, language: str) -> Optional[Any]:
        """Get or create a parser for the given language."""
        if not cls.is_available():
            return None
        
        if language not in TREE_SITTER_GRAMMARS:
            return None
        
        if language not in cls._parsers:
            try:
                from tree_sitter import Language, Parser
                grammar_module = __import__(TREE_SITTER_GRAMMARS[language])
                
                # Handle typescript which has separate tsx/typescript
                if language == 'typescript':
                    lang = grammar_module.language_typescript()
                else:
                    lang = grammar_module.language()
                
                # Grammar wheels (>=0.22) expose language() as a PyCapsule that
                # must be wrapped in tree_sitter.Language before it can be
                # handed to Parser. Older grammars returned a Language already.
                if not isinstance(lang, Language):
                    lang = Language(lang)
                
                parser = Parser(lang)
                cls._parsers[language] = parser
            except Exception as e:
                # A missing or ABI-incompatible grammar must degrade to the
                # fallback parsers, never abort the scan. Cache the failure so
                # each language pays the import cost once.
                logger.debug(f"Could not load tree-sitter grammar for {language}: {e}")
                cls._parsers[language] = None
                return None
        
        return cls._parsers.get(language)
    
    @classmethod
    def parse(cls, code: str, language: str) -> Optional[Any]:
        """Parse code and return tree-sitter tree."""
        parser = cls.get_parser(language)
        if parser is None:
            return None
        
        try:
            tree = parser.parse(code.encode('utf-8'))
            return tree
        except Exception as e:
            logger.debug(f"Tree-sitter parse error for {language}: {e}")
            return None


# ═══════════════════════════════════════════════════════════════════════════════
# PYTHON AST PARSER (Built-in)
# ═══════════════════════════════════════════════════════════════════════════════

class PythonASTParser:
    """Python-specific parser using built-in ast module."""
    
    @staticmethod
    def parse(code: str) -> ParseResult:
        """Parse Python code using built-in ast module."""
        result = ParseResult(
            language='python',
            backend=ParserBackend.PYTHON_AST
        )
        
        lines = code.split('\n')
        result.total_lines = len(lines)
        
        try:
            tree = python_ast.parse(code)
            result.raw_tree = tree
            result.parse_success = True
            
            # Extract information
            result.functions = PythonASTParser._extract_functions(tree)
            result.classes = PythonASTParser._extract_classes(tree)
            result.imports = PythonASTParser._extract_imports(tree)
            result.variables = PythonASTParser._extract_variables(tree)
            
            # Calculate metrics
            result.complexity = PythonASTParser._calculate_complexity(tree)
            result.max_nesting_depth = PythonASTParser._calculate_max_nesting(tree)
            
            # Line counts
            result.code_lines, result.comment_lines, result.blank_lines = \
                PythonASTParser._count_lines(code)
            
        except SyntaxError as e:
            result.parse_success = False
            result.parse_errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
            # Fall back to regex for partial results
            result = RegexParser.parse(code, 'python')
            result.parse_errors.append(f"Fell back to regex due to syntax error")
        
        return result
    
    @staticmethod
    def _extract_functions(tree: python_ast.AST) -> List[FunctionInfo]:
        """Extract function information from AST."""
        functions = []
        
        for node in python_ast.walk(tree):
            if isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
                func = FunctionInfo(
                    name=node.name,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    is_async=isinstance(node, python_ast.AsyncFunctionDef),
                    parameters=[arg.arg for arg in node.args.args],
                    decorators=[
                        PythonASTParser._decorator_name(d) for d in node.decorator_list
                    ],
                    complexity=PythonASTParser._calculate_function_complexity(node),
                )
                
                # Extract return type annotation
                if node.returns:
                    func.return_type = python_ast.unparse(node.returns)
                
                # Extract docstring
                if (node.body and isinstance(node.body[0], python_ast.Expr) and
                    isinstance(node.body[0].value, python_ast.Constant) and
                    isinstance(node.body[0].value.value, str)):
                    func.docstring = node.body[0].value.value
                
                functions.append(func)
        
        return functions
    
    @staticmethod
    def _decorator_name(decorator: python_ast.expr) -> str:
        """Get decorator name as string."""
        if isinstance(decorator, python_ast.Name):
            return decorator.id
        elif isinstance(decorator, python_ast.Attribute):
            return python_ast.unparse(decorator)
        elif isinstance(decorator, python_ast.Call):
            return PythonASTParser._decorator_name(decorator.func)
        return python_ast.unparse(decorator)
    
    @staticmethod
    def _extract_classes(tree: python_ast.AST) -> List[ClassInfo]:
        """Extract class information from AST."""
        classes = []
        
        for node in python_ast.walk(tree):
            if isinstance(node, python_ast.ClassDef):
                cls = ClassInfo(
                    name=node.name,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    base_classes=[python_ast.unparse(base) for base in node.bases],
                    decorators=[
                        PythonASTParser._decorator_name(d) for d in node.decorator_list
                    ],
                    is_dataclass=any(
                        'dataclass' in PythonASTParser._decorator_name(d)
                        for d in node.decorator_list
                    ),
                )
                
                # Extract methods
                for item in node.body:
                    if isinstance(item, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
                        method = FunctionInfo(
                            name=item.name,
                            line_start=item.lineno,
                            line_end=item.end_lineno or item.lineno,
                            is_async=isinstance(item, python_ast.AsyncFunctionDef),
                            is_method=True,
                            parameters=[arg.arg for arg in item.args.args],
                            complexity=PythonASTParser._calculate_function_complexity(item),
                        )
                        cls.methods.append(method)
                
                # Extract docstring
                if (node.body and isinstance(node.body[0], python_ast.Expr) and
                    isinstance(node.body[0].value, python_ast.Constant) and
                    isinstance(node.body[0].value.value, str)):
                    cls.docstring = node.body[0].value.value
                
                classes.append(cls)
        
        return classes
    
    @staticmethod
    def _extract_imports(tree: python_ast.AST) -> List[ImportInfo]:
        """Extract import information from AST."""
        imports = []
        
        for node in python_ast.walk(tree):
            if isinstance(node, python_ast.Import):
                for alias in node.names:
                    imports.append(ImportInfo(
                        module=alias.name,
                        alias=alias.asname,
                        line_number=node.lineno,
                        is_from_import=False,
                    ))
            elif isinstance(node, python_ast.ImportFrom):
                imports.append(ImportInfo(
                    module=node.module or '',
                    names=[alias.name for alias in node.names],
                    line_number=node.lineno,
                    is_from_import=True,
                ))
        
        return imports
    
    @staticmethod
    def _extract_variables(tree: python_ast.AST) -> List[VariableInfo]:
        """Extract module-level variables from AST."""
        variables = []
        
        # Only get top-level assignments
        if isinstance(tree, python_ast.Module):
            for node in tree.body:
                if isinstance(node, python_ast.Assign):
                    for target in node.targets:
                        if isinstance(target, python_ast.Name):
                            variables.append(VariableInfo(
                                name=target.id,
                                line_number=node.lineno,
                                is_constant=target.id.isupper(),
                                scope='module',
                            ))
                elif isinstance(node, python_ast.AnnAssign):
                    if isinstance(node.target, python_ast.Name):
                        variables.append(VariableInfo(
                            name=node.target.id,
                            line_number=node.lineno,
                            type_annotation=python_ast.unparse(node.annotation),
                            is_constant=node.target.id.isupper(),
                            scope='module',
                        ))
        
        return variables
    
    @staticmethod
    def _calculate_complexity(tree: python_ast.AST) -> int:
        """Calculate cyclomatic complexity for entire module."""
        complexity = 1  # Base complexity
        
        for node in python_ast.walk(tree):
            # Decision points that increase complexity
            if isinstance(node, (python_ast.If, python_ast.While, python_ast.For,
                                 python_ast.AsyncFor, python_ast.ExceptHandler,
                                 python_ast.With, python_ast.AsyncWith)):
                complexity += 1
            elif isinstance(node, python_ast.BoolOp):
                # and/or add complexity
                complexity += len(node.values) - 1
            elif isinstance(node, python_ast.comprehension):
                # List/dict/set comprehensions
                complexity += 1
                if node.ifs:
                    complexity += len(node.ifs)
            elif isinstance(node, python_ast.Assert):
                complexity += 1
            elif isinstance(node, python_ast.Raise):
                complexity += 1
            elif isinstance(node, (python_ast.Match,)):
                # Match statement (Python 3.10+)
                complexity += 1
        
        return complexity
    
    @staticmethod
    def _calculate_function_complexity(func_node: python_ast.AST) -> int:
        """Calculate complexity for a single function."""
        complexity = 1
        
        for node in python_ast.walk(func_node):
            if isinstance(node, (python_ast.If, python_ast.While, python_ast.For,
                                 python_ast.AsyncFor, python_ast.ExceptHandler)):
                complexity += 1
            elif isinstance(node, python_ast.BoolOp):
                complexity += len(node.values) - 1
            elif isinstance(node, python_ast.comprehension):
                complexity += 1
        
        return complexity
    
    @staticmethod
    def _calculate_max_nesting(tree: python_ast.AST, depth: int = 0) -> int:
        """Calculate maximum nesting depth."""
        max_depth = depth
        
        for node in python_ast.iter_child_nodes(tree):
            if isinstance(node, (python_ast.If, python_ast.While, python_ast.For,
                                 python_ast.AsyncFor, python_ast.With, python_ast.AsyncWith,
                                 python_ast.Try, python_ast.FunctionDef, 
                                 python_ast.AsyncFunctionDef, python_ast.ClassDef)):
                child_depth = PythonASTParser._calculate_max_nesting(node, depth + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = PythonASTParser._calculate_max_nesting(node, depth)
                max_depth = max(max_depth, child_depth)
        
        return max_depth
    
    @staticmethod
    def _count_lines(code: str) -> Tuple[int, int, int]:
        """Count code, comment, and blank lines."""
        code_lines = 0
        comment_lines = 0
        blank_lines = 0
        in_multiline_string = False
        multiline_char = None
        
        for line in code.split('\n'):
            stripped = line.strip()
            
            if not stripped:
                blank_lines += 1
                continue
            
            # Handle multiline strings (docstrings/comments)
            if in_multiline_string:
                comment_lines += 1
                if multiline_char in stripped:
                    in_multiline_string = False
                continue
            
            # Check for multiline string start
            if '"""' in stripped or "'''" in stripped:
                multiline_char = '"""' if '"""' in stripped else "'''"
                # Check if it closes on same line
                count = stripped.count(multiline_char)
                if count == 1:
                    in_multiline_string = True
                comment_lines += 1
                continue
            
            # Single-line comment
            if stripped.startswith('#'):
                comment_lines += 1
            else:
                code_lines += 1
        
        return code_lines, comment_lines, blank_lines


# ═══════════════════════════════════════════════════════════════════════════════
# REGEX FALLBACK PARSER
# ═══════════════════════════════════════════════════════════════════════════════

class RegexParser:
    """Regex-based parser for when AST parsing is unavailable."""
    
    # Language-specific patterns
    PATTERNS: Dict[str, Dict[str, str]] = {
        'python': {
            'function': r'^\s*(?:async\s+)?def\s+(\w+)\s*\(',
            'class': r'^\s*class\s+(\w+)',
            'import': r'^\s*(?:from\s+(\S+)\s+)?import\s+(.+)',
            'comment': r'#.*$',
            'multiline_comment_start': r'"""|\'\'\' ',
        },
        'javascript': {
            'function': r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|(\w+)\s*:\s*(?:async\s+)?function)',
            'class': r'class\s+(\w+)',
            'import': r'import\s+.*from\s+["\']([^"\']+)["\']|require\(["\']([^"\']+)["\']\)',
            'comment': r'//.*$',
            'multiline_comment_start': r'/\*',
            'multiline_comment_end': r'\*/',
        },
        'typescript': {
            'function': r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*(?::\s*\S+\s*)?=\s*(?:async\s*)?\([^)]*\)\s*=>|(\w+)\s*\([^)]*\)\s*(?::\s*\S+\s*)?{)',
            'class': r'class\s+(\w+)',
            'interface': r'interface\s+(\w+)',
            'type': r'type\s+(\w+)\s*=',
            'import': r'import\s+.*from\s+["\']([^"\']+)["\']',
            'comment': r'//.*$',
            'multiline_comment_start': r'/\*',
            'multiline_comment_end': r'\*/',
        },
        'java': {
            'function': r'(?:public|private|protected)?\s*(?:static\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+(?:\s*,\s*\w+)*)?\s*{',
            'class': r'(?:public\s+)?(?:abstract\s+)?(?:final\s+)?class\s+(\w+)',
            'interface': r'(?:public\s+)?interface\s+(\w+)',
            'import': r'import\s+(?:static\s+)?([^;]+);',
            'comment': r'//.*$',
            'multiline_comment_start': r'/\*',
            'multiline_comment_end': r'\*/',
        },
        'go': {
            'function': r'func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(',
            'struct': r'type\s+(\w+)\s+struct',
            'interface': r'type\s+(\w+)\s+interface',
            'import': r'import\s+(?:\(\s*)?["\']([^"\']+)["\']',
            'comment': r'//.*$',
            'multiline_comment_start': r'/\*',
            'multiline_comment_end': r'\*/',
        },
        'rust': {
            'function': r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)',
            'struct': r'(?:pub\s+)?struct\s+(\w+)',
            'enum': r'(?:pub\s+)?enum\s+(\w+)',
            'trait': r'(?:pub\s+)?trait\s+(\w+)',
            'impl': r'impl(?:<[^>]+>)?\s+(?:(\w+)\s+for\s+)?(\w+)',
            'import': r'use\s+([^;]+);',
            'comment': r'//.*$',
            'multiline_comment_start': r'/\*',
            'multiline_comment_end': r'\*/',
        },
        'ruby': {
            'function': r'def\s+(\w+[?!]?)',
            'class': r'class\s+(\w+)',
            'module': r'module\s+(\w+)',
            'import': r'require\s+["\']([^"\']+)["\']|require_relative\s+["\']([^"\']+)["\']',
            'comment': r'#.*$',
            'multiline_comment_start': r'^=begin',
            'multiline_comment_end': r'^=end',
        },
        'php': {
            'function': r'(?:public|private|protected)?\s*(?:static\s+)?function\s+(\w+)',
            'class': r'(?:abstract\s+)?class\s+(\w+)',
            'interface': r'interface\s+(\w+)',
            'trait': r'trait\s+(\w+)',
            'import': r'use\s+([^;]+);|require(?:_once)?\s*\(?["\']([^"\']+)["\']\)?',
            'comment': r'(?://|#).*$',
            'multiline_comment_start': r'/\*',
            'multiline_comment_end': r'\*/',
        },
        'c': {
            'function': r'(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*{',
            'struct': r'(?:typedef\s+)?struct\s+(\w+)',
            'include': r'#include\s*[<"]([^>"]+)[>"]',
            'comment': r'//.*$',
            'multiline_comment_start': r'/\*',
            'multiline_comment_end': r'\*/',
        },
        'cpp': {
            'function': r'(?:\w+(?:::\w+)?(?:<[^>]+>)?\s+)+(\w+)\s*\([^)]*\)\s*(?:const\s*)?(?:override\s*)?(?:final\s*)?{',
            'class': r'class\s+(\w+)',
            'struct': r'struct\s+(\w+)',
            'namespace': r'namespace\s+(\w+)',
            'include': r'#include\s*[<"]([^>"]+)[>"]',
            'comment': r'//.*$',
            'multiline_comment_start': r'/\*',
            'multiline_comment_end': r'\*/',
        },
    }
    
    # Complexity-increasing keywords by language
    COMPLEXITY_KEYWORDS: Dict[str, List[str]] = {
        'python': ['if', 'elif', 'else', 'for', 'while', 'try', 'except', 'with', 'and', 'or'],
        'javascript': ['if', 'else', 'for', 'while', 'do', 'switch', 'case', 'try', 'catch', '&&', '||', '\\?'],
        'typescript': ['if', 'else', 'for', 'while', 'do', 'switch', 'case', 'try', 'catch', '&&', '||', '\\?'],
        'java': ['if', 'else', 'for', 'while', 'do', 'switch', 'case', 'try', 'catch', '&&', '||', '\\?'],
        'go': ['if', 'else', 'for', 'switch', 'case', 'select', '&&', '||'],
        'rust': ['if', 'else', 'for', 'while', 'loop', 'match', '&&', '||', '\\?'],
        'ruby': ['if', 'elsif', 'else', 'unless', 'case', 'when', 'while', 'until', 'for', 'and', 'or'],
        'php': ['if', 'elseif', 'else', 'for', 'foreach', 'while', 'do', 'switch', 'case', 'try', 'catch', '&&', '||', '\\?'],
        'c': ['if', 'else', 'for', 'while', 'do', 'switch', 'case', '&&', '||', '\\?'],
        'cpp': ['if', 'else', 'for', 'while', 'do', 'switch', 'case', 'try', 'catch', '&&', '||', '\\?'],
    }
    
    @classmethod
    def parse(cls, code: str, language: str) -> ParseResult:
        """Parse code using regex patterns."""
        result = ParseResult(
            language=language,
            backend=ParserBackend.REGEX,
            parse_success=True,
        )
        
        lines = code.split('\n')
        result.total_lines = len(lines)
        
        patterns = cls.PATTERNS.get(language, cls.PATTERNS.get('python', {}))
        
        # Extract functions
        if 'function' in patterns:
            result.functions = cls._extract_functions(code, patterns['function'], language)
        
        # Extract classes
        if 'class' in patterns:
            result.classes = cls._extract_classes(code, patterns['class'])
        
        # Extract imports
        import_pattern = patterns.get('import') or patterns.get('include')
        if import_pattern:
            result.imports = cls._extract_imports(code, import_pattern)
        
        # Calculate metrics
        result.complexity = cls._calculate_complexity(code, language)
        result.code_lines, result.comment_lines, result.blank_lines = \
            cls._count_lines(code, patterns)
        
        return result
    
    @classmethod
    def _extract_functions(cls, code: str, pattern: str, language: str) -> List[FunctionInfo]:
        """Extract functions using regex."""
        functions = []
        
        for i, line in enumerate(code.split('\n'), 1):
            match = re.search(pattern, line, re.MULTILINE)
            if match:
                # Get first non-None group
                name = next((g for g in match.groups() if g), 'unknown')
                functions.append(FunctionInfo(
                    name=name,
                    line_start=i,
                    line_end=i,  # Can't determine end with regex alone
                    is_async='async' in line.lower(),
                ))
        
        return functions
    
    @classmethod
    def _extract_classes(cls, code: str, pattern: str) -> List[ClassInfo]:
        """Extract classes using regex."""
        classes = []
        
        for i, line in enumerate(code.split('\n'), 1):
            match = re.search(pattern, line)
            if match:
                name = match.group(1)
                classes.append(ClassInfo(
                    name=name,
                    line_start=i,
                    line_end=i,
                ))
        
        return classes
    
    @classmethod
    def _extract_imports(cls, code: str, pattern: str) -> List[ImportInfo]:
        """Extract imports using regex."""
        imports = []
        
        for i, line in enumerate(code.split('\n'), 1):
            match = re.search(pattern, line)
            if match:
                # Get first non-None group
                module = next((g for g in match.groups() if g), '')
                imports.append(ImportInfo(
                    module=module,
                    line_number=i,
                ))
        
        return imports
    
    @classmethod
    def _calculate_complexity(cls, code: str, language: str) -> int:
        """Calculate cyclomatic complexity using keyword counting."""
        complexity = 1
        keywords = cls.COMPLEXITY_KEYWORDS.get(language, cls.COMPLEXITY_KEYWORDS['python'])
        
        for keyword in keywords:
            # Use word boundaries for keywords, direct match for operators
            if keyword.startswith('\\') or keyword in ['&&', '||', '?']:
                pattern = re.escape(keyword.replace('\\', ''))
            else:
                pattern = r'\b' + keyword + r'\b'
            
            complexity += len(re.findall(pattern, code))
        
        return complexity
    
    @classmethod
    def _count_lines(cls, code: str, patterns: Dict[str, str]) -> Tuple[int, int, int]:
        """Count code, comment, and blank lines."""
        code_lines = 0
        comment_lines = 0
        blank_lines = 0
        in_multiline = False
        
        comment_pattern = patterns.get('comment', '#.*$')
        ml_start = patterns.get('multiline_comment_start')
        ml_end = patterns.get('multiline_comment_end')
        
        for line in code.split('\n'):
            stripped = line.strip()
            
            if not stripped:
                blank_lines += 1
                continue
            
            # Handle multiline comments
            if in_multiline:
                comment_lines += 1
                if ml_end and re.search(ml_end, stripped):
                    in_multiline = False
                continue
            
            if ml_start and re.search(ml_start, stripped):
                comment_lines += 1
                # Check if it closes on same line
                if not (ml_end and re.search(ml_end, stripped.split(ml_start.replace('\\', ''), 1)[-1])):
                    in_multiline = True
                continue
            
            # Single-line comment
            if re.match(comment_pattern, stripped):
                comment_lines += 1
            else:
                code_lines += 1
        
        return code_lines, comment_lines, blank_lines


# ═══════════════════════════════════════════════════════════════════════════════
# TREE-SITTER AST EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════

class TreeSitterExtractor:
    """Extract information from tree-sitter AST."""
    
    @classmethod
    def extract(cls, tree: Any, code: str, language: str) -> ParseResult:
        """Extract information from tree-sitter tree."""
        result = ParseResult(
            language=language,
            backend=ParserBackend.TREE_SITTER,
            parse_success=True,
            raw_tree=tree,
        )
        
        lines = code.split('\n')
        result.total_lines = len(lines)
        
        root = tree.root_node
        
        # Check for parse errors
        if root.has_error:
            result.parse_errors.append("Tree-sitter detected syntax errors (partial parse)")
        
        # Extract based on language
        result.functions = cls._extract_functions(root, code, language)
        result.classes = cls._extract_classes(root, code, language)
        result.imports = cls._extract_imports(root, code, language)
        result.complexity = cls._calculate_complexity(root, language)
        result.max_nesting_depth = cls._calculate_max_nesting(root)
        
        # Use regex for line counts (tree-sitter doesn't track comments well)
        result.code_lines, result.comment_lines, result.blank_lines = \
            RegexParser._count_lines(code, RegexParser.PATTERNS.get(language, {}))
        
        return result
    
    @classmethod
    def _extract_functions(cls, root: Any, code: str, language: str) -> List[FunctionInfo]:
        """Extract functions from tree-sitter tree."""
        functions = []
        
        # Node types that represent functions in different languages
        function_types = {
            'python': ['function_definition'],
            'javascript': ['function_declaration', 'arrow_function', 'method_definition'],
            'typescript': ['function_declaration', 'arrow_function', 'method_definition'],
            'java': ['method_declaration', 'constructor_declaration'],
            'go': ['function_declaration', 'method_declaration'],
            'rust': ['function_item'],
            'ruby': ['method', 'singleton_method'],
            'php': ['function_definition', 'method_declaration'],
            'c': ['function_definition'],
            'cpp': ['function_definition'],
        }
        
        target_types = function_types.get(language, ['function_definition'])
        
        def traverse(node):
            if node.type in target_types:
                # Find name node
                name = 'anonymous'
                for child in node.children:
                    if child.type in ['identifier', 'name', 'property_identifier']:
                        name = code[child.start_byte:child.end_byte]
                        break
                
                functions.append(FunctionInfo(
                    name=name,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    is_async='async' in node.type or any(
                        c.type == 'async' for c in node.children
                    ),
                ))
            
            for child in node.children:
                traverse(child)
        
        traverse(root)
        return functions
    
    @classmethod
    def _extract_classes(cls, root: Any, code: str, language: str) -> List[ClassInfo]:
        """Extract classes from tree-sitter tree."""
        classes = []
        
        class_types = {
            'python': ['class_definition'],
            'javascript': ['class_declaration'],
            'typescript': ['class_declaration', 'interface_declaration'],
            'java': ['class_declaration', 'interface_declaration'],
            'go': ['type_declaration'],  # For struct definitions
            'rust': ['struct_item', 'impl_item'],
            'ruby': ['class', 'module'],
            'php': ['class_declaration', 'interface_declaration'],
            'cpp': ['class_specifier', 'struct_specifier'],
        }
        
        target_types = class_types.get(language, ['class_definition'])
        
        def traverse(node):
            if node.type in target_types:
                name = 'unknown'
                for child in node.children:
                    if child.type in ['identifier', 'name', 'type_identifier']:
                        name = code[child.start_byte:child.end_byte]
                        break
                
                classes.append(ClassInfo(
                    name=name,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
            
            for child in node.children:
                traverse(child)
        
        traverse(root)
        return classes
    
    @classmethod
    def _extract_imports(cls, root: Any, code: str, language: str) -> List[ImportInfo]:
        """Extract imports from tree-sitter tree."""
        imports = []
        
        import_types = {
            'python': ['import_statement', 'import_from_statement'],
            'javascript': ['import_statement', 'call_expression'],  # call_expression for require()
            'typescript': ['import_statement'],
            'java': ['import_declaration'],
            'go': ['import_declaration', 'import_spec'],
            'rust': ['use_declaration'],
            'ruby': ['call'],  # require/require_relative
            'php': ['use_declaration', 'include_expression', 'require_expression'],
            'c': ['preproc_include'],
            'cpp': ['preproc_include'],
        }
        
        target_types = import_types.get(language, ['import_statement'])
        
        def traverse(node):
            if node.type in target_types:
                # Get the full import text
                import_text = code[node.start_byte:node.end_byte]
                imports.append(ImportInfo(
                    module=import_text.strip(),
                    line_number=node.start_point[0] + 1,
                ))
            
            for child in node.children:
                traverse(child)
        
        traverse(root)
        return imports
    
    @classmethod
    def _calculate_complexity(cls, root: Any, language: str) -> int:
        """Calculate complexity from tree-sitter tree."""
        complexity = 1
        
        # Node types that increase complexity
        complexity_nodes = {
            'python': ['if_statement', 'while_statement', 'for_statement', 
                       'except_clause', 'with_statement', 'boolean_operator',
                       'conditional_expression', 'list_comprehension'],
            'javascript': ['if_statement', 'while_statement', 'for_statement',
                           'for_in_statement', 'switch_statement', 'catch_clause',
                           'ternary_expression', 'binary_expression'],
            'typescript': ['if_statement', 'while_statement', 'for_statement',
                           'for_in_statement', 'switch_statement', 'catch_clause',
                           'ternary_expression', 'binary_expression'],
            'java': ['if_statement', 'while_statement', 'for_statement',
                     'enhanced_for_statement', 'switch_statement', 'catch_clause',
                     'ternary_expression', 'binary_expression'],
            'go': ['if_statement', 'for_statement', 'switch_statement',
                   'select_statement', 'binary_expression'],
            'rust': ['if_expression', 'while_expression', 'for_expression',
                     'loop_expression', 'match_expression', 'binary_expression'],
        }
        
        target_nodes = set(complexity_nodes.get(language, complexity_nodes['python']))
        
        def traverse(node):
            nonlocal complexity
            if node.type in target_nodes:
                complexity += 1
                # For boolean operators, count additional operands
                if node.type in ['boolean_operator', 'binary_expression']:
                    if any(c.type in ['&&', '||', 'and', 'or'] 
                           for c in node.children):
                        complexity += 1
            
            for child in node.children:
                traverse(child)
        
        traverse(root)
        return complexity
    
    @classmethod
    def _calculate_max_nesting(cls, root: Any, depth: int = 0) -> int:
        """Calculate maximum nesting depth."""
        max_depth = depth
        
        nesting_types = {
            'if_statement', 'while_statement', 'for_statement', 'for_in_statement',
            'function_definition', 'function_declaration', 'method_definition',
            'class_definition', 'class_declaration', 'try_statement', 'with_statement',
            'if_expression', 'match_expression', 'loop_expression',
        }
        
        for child in root.children:
            if child.type in nesting_types:
                child_depth = cls._calculate_max_nesting(child, depth + 1)
            else:
                child_depth = cls._calculate_max_nesting(child, depth)
            max_depth = max(max_depth, child_depth)
        
        return max_depth


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN AST PARSER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class ASTParser:
    """
    Unified AST Parser for multiple languages.
    
    Uses the best available parser:
    1. tree-sitter (if installed and grammar available)
    2. Python ast module (for Python files)
    3. Regex fallback (for any language)
    
    Usage:
        parser = ASTParser()
        result = parser.parse_file("path/to/file.py")
        # or
        result = parser.parse_code("def hello(): pass", "python")
    """
    
    def __init__(self, prefer_tree_sitter: bool = True):
        """
        Initialize parser.
        
        Args:
            prefer_tree_sitter: Use tree-sitter when available (default: True)
        """
        self.prefer_tree_sitter = prefer_tree_sitter
    
    def parse_file(self, file_path: Union[str, Path]) -> ParseResult:
        """
        Parse a file and extract AST information.
        
        Args:
            file_path: Path to the file to parse
        
        Returns:
            ParseResult with extracted information
        """
        path = Path(file_path)
        
        if not path.exists():
            return ParseResult(
                file_path=str(path),
                parse_success=False,
                parse_errors=[f"File not found: {path}"]
            )
        
        # Detect language
        language = self._detect_language(path)
        
        try:
            code = path.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            return ParseResult(
                file_path=str(path),
                language=language,
                parse_success=False,
                parse_errors=[f"Could not read file: {e}"]
            )
        
        result = self.parse_code(code, language)
        result.file_path = str(path)
        return result
    
    def parse_code(self, code: str, language: str) -> ParseResult:
        """
        Parse code string and extract AST information.
        
        Args:
            code: Source code to parse
            language: Programming language ('python', 'javascript', etc.)
        
        Returns:
            ParseResult with extracted information
        """
        # Try tree-sitter first
        if self.prefer_tree_sitter and TreeSitterParser.is_available():
            tree = TreeSitterParser.parse(code, language)
            if tree is not None:
                return TreeSitterExtractor.extract(tree, code, language)
        
        # Use built-in ast for Python
        if language == 'python':
            return PythonASTParser.parse(code)
        
        # Fall back to regex
        return RegexParser.parse(code, language)
    
    def _detect_language(self, path: Path) -> str:
        """Detect language from file extension."""
        return LANGUAGE_EXTENSIONS.get(path.suffix.lower(), 'unknown')


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

_default_parser: Optional[ASTParser] = None


def get_default_parser() -> ASTParser:
    """Get or create default parser instance."""
    global _default_parser
    if _default_parser is None:
        _default_parser = ASTParser()
    return _default_parser


def parse_file(file_path: Union[str, Path]) -> ParseResult:
    """
    Parse a file and extract AST information.
    
    Convenience function using default parser.
    
    Args:
        file_path: Path to the file to parse
    
    Returns:
        ParseResult with extracted information
    """
    return get_default_parser().parse_file(file_path)


def parse_code(code: str, language: str) -> ParseResult:
    """
    Parse code string and extract AST information.
    
    Convenience function using default parser.
    
    Args:
        code: Source code to parse
        language: Programming language
    
    Returns:
        ParseResult with extracted information
    """
    return get_default_parser().parse_code(code, language)


def get_supported_languages() -> List[str]:
    """Get list of all supported languages."""
    return list(LANGUAGE_EXTENSIONS.values())


def is_language_supported(language: str) -> bool:
    """Check if a language is supported."""
    return language in set(LANGUAGE_EXTENSIONS.values())


def get_tree_sitter_languages() -> Set[str]:
    """Get languages with tree-sitter support available."""
    return TreeSitterParser.get_available_languages()
