"""
CodebaseCSI Parsers Module - Multi-Language AST Support

Provides unified AST parsing for 10+ programming languages using tree-sitter.
Falls back to regex-based analysis when tree-sitter grammars aren't available.

Supported Languages:
- Python, JavaScript, TypeScript
- Java, Go, Rust, Ruby, PHP
- C, C++

Usage:
    from codebase_csi.parsers import ASTParser, parse_file
    
    # Parse a file
    result = parse_file("app.py")
    
    # Get functions, classes, complexity
    functions = result.functions
    complexity = result.complexity
"""

from .ast_parser import (
    ASTParser,
    ParseResult,
    FunctionInfo,
    ClassInfo,
    parse_file,
    parse_code,
    get_supported_languages,
    is_language_supported,
)

__all__ = [
    'ASTParser',
    'ParseResult',
    'FunctionInfo',
    'ClassInfo',
    'parse_file',
    'parse_code',
    'get_supported_languages',
    'is_language_supported',
]
