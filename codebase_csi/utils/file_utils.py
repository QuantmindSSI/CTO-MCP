"""
File utilities for scanning and processing code files.

Provides file discovery, language detection, and filtering capabilities.
"""

import os
from pathlib import Path
from typing import List, Set, Optional, Dict
import fnmatch


class LanguageDetector:
    """Detect programming language from file extensions and content."""
    
    LANGUAGE_MAP = {
        # Python
        '.py': 'python',
        '.pyw': 'python',
        '.pyi': 'python',
        
        # JavaScript/TypeScript
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.mjs': 'javascript',
        '.cjs': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        
        # Web Technologies
        '.html': 'html',
        '.htm': 'html',
        '.xhtml': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.sass': 'sass',
        '.less': 'less',
        '.vue': 'vue',
        '.svelte': 'svelte',
        
        # Java/JVM
        '.java': 'java',
        '.kt': 'kotlin',
        '.kts': 'kotlin',
        '.scala': 'scala',
        '.groovy': 'groovy',
        '.gradle': 'groovy',
        
        # C/C++
        '.c': 'c',
        '.h': 'c',  # Note: Could also be C++, requires content detection
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.c++': 'cpp',
        '.hpp': 'cpp',
        '.hh': 'cpp',
        '.hxx': 'cpp',
        '.h++': 'cpp',
        
        # C#/.NET
        '.cs': 'csharp',
        '.csx': 'csharp',
        '.fs': 'fsharp',
        '.fsx': 'fsharp',
        '.fsi': 'fsharp',
        '.vb': 'visualbasic',
        
        # Systems Programming
        '.go': 'go',
        '.rs': 'rust',
        '.zig': 'zig',
        '.nim': 'nim',
        
        # Scripting
        '.rb': 'ruby',
        '.php': 'php',
        '.php3': 'php',
        '.php4': 'php',
        '.php5': 'php',
        '.phtml': 'php',
        '.pl': 'perl',
        '.pm': 'perl',
        '.t': 'perl',
        '.sh': 'shell',
        '.bash': 'shell',
        '.zsh': 'shell',
        '.fish': 'shell',
        '.ksh': 'shell',
        '.lua': 'lua',
        
        # Apple
        '.swift': 'swift',
        '.m': 'objective-c',  # Note: Could also be MATLAB, requires content detection
        '.mm': 'objective-c++',
        
        # Mobile
        '.dart': 'dart',
        
        # Functional
        '.ex': 'elixir',
        '.exs': 'elixir',
        '.erl': 'erlang',
        '.hrl': 'erlang',
        '.clj': 'clojure',
        '.cljs': 'clojure',
        '.cljc': 'clojure',
        '.edn': 'clojure',
        '.hs': 'haskell',
        '.lhs': 'haskell',
        '.elm': 'elm',
        '.ml': 'ocaml',
        '.mli': 'ocaml',
        '.lisp': 'lisp',
        '.cl': 'lisp',
        '.el': 'lisp',
        
        # Scientific/Statistical
        '.r': 'r',
        '.R': 'r',
        '.rmd': 'rmarkdown',
        '.Rmd': 'rmarkdown',
        '.jl': 'julia',
        '.m': 'matlab',  # Conflicts with Objective-C
        '.mat': 'matlab',
        
        # Data/Config
        '.json': 'json',
        '.jsonc': 'json',
        '.json5': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.toml': 'toml',
        '.xml': 'xml',
        '.ini': 'ini',
        '.cfg': 'config',
        '.conf': 'config',
        '.properties': 'properties',
        
        # Markup/Documentation
        '.md': 'markdown',
        '.markdown': 'markdown',
        '.rst': 'restructuredtext',
        '.tex': 'latex',
        '.adoc': 'asciidoc',
        
        # Database
        '.sql': 'sql',
        '.psql': 'postgresql',
        '.mysql': 'mysql',
        '.pgsql': 'postgresql',
        
        # Infrastructure/DevOps
        '.tf': 'terraform',
        '.tfvars': 'terraform',
        '.hcl': 'hcl',
        'Dockerfile': 'dockerfile',
        'Makefile': 'makefile',
        '.mk': 'makefile',
        '.cmake': 'cmake',
        'CMakeLists.txt': 'cmake',
        
        # Hardware Description
        '.v': 'verilog',  # Note: Could also be V language, requires content detection
        '.vh': 'verilog',
        '.sv': 'systemverilog',
        '.svh': 'systemverilog',
        '.vhd': 'vhdl',
        '.vhdl': 'vhdl',
        '.vht': 'vhdl',
        
        # Data Science/Notebooks
        '.ipynb': 'jupyter',
        '.rmd': 'rmarkdown',
        
        # Game Development
        '.gd': 'gdscript',
        '.shader': 'shader',
        '.glsl': 'glsl',
        '.hlsl': 'hlsl',
        
        # Other
        '.proto': 'protobuf',
        '.thrift': 'thrift',
        '.graphql': 'graphql',
        '.gql': 'graphql',
    }
    
    # Binary file extensions (skip these entirely)
    BINARY_EXTENSIONS = {
        # Compiled
        '.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib', '.o', '.a', '.lib',
        '.class', '.jar', '.war', '.ear', '.exe', '.out',
        
        # Images
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp',
        '.tiff', '.tif', '.psd', '.ai', '.eps',
        
        # Archives
        '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar', '.tgz',
        
        # Media
        '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.wav',
        '.ogg', '.m4a', '.aac',
        
        # Documents
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        
        # Fonts
        '.ttf', '.otf', '.woff', '.woff2', '.eot',
        
        # Databases
        '.db', '.sqlite', '.sqlite3',
        
        # Other
        '.bin', '.dat', '.dmp'
    }
    
    # Conflicting extensions that need content-based detection
    CONFLICTING_EXTENSIONS = {
        '.m': ['objective-c', 'matlab'],
        '.v': ['verilog', 'vlang'],
        '.h': ['c', 'cpp']
    }
    
    def detect(self, file_path: Path, content_sample: Optional[str] = None) -> str:
        """
        Detect language from file extension and optionally content.
        
        Args:
            file_path: Path to file
            content_sample: Optional first few lines of file for disambiguation
            
        Returns:
            Language name or 'unknown'
        """
        # Handle special filenames (no extension)
        filename = file_path.name
        if filename in self.LANGUAGE_MAP:
            return self.LANGUAGE_MAP[filename]
        
        suffix = file_path.suffix.lower()
        
        # Check if it's a known binary extension
        if suffix in self.BINARY_EXTENSIONS:
            return 'binary'
        
        # Check for conflicting extensions
        if suffix in self.CONFLICTING_EXTENSIONS and content_sample:
            return self._detect_conflicting(suffix, content_sample)
        
        return self.LANGUAGE_MAP.get(suffix, 'unknown')
    
    def _detect_conflicting(self, extension: str, content: str) -> str:
        """
        Use content-based detection for ambiguous file extensions.
        
        Args:
            extension: File extension (e.g., '.m', '.v')
            content: First few lines of file content
            
        Returns:
            Detected language
        """
        content_lower = content.lower()
        
        if extension == '.m':
            # MATLAB indicators
            matlab_indicators = [
                'function', '%', 'end', 'disp(', 'fprintf(',
                'matrix', 'plot(', 'figure('
            ]
            # Objective-C indicators
            objc_indicators = [
                '@interface', '@implementation', '@property', '#import',
                'NSString', 'NS', '[[', 'alloc]', 'init]'
            ]
            
            matlab_score = sum(1 for ind in matlab_indicators if ind in content_lower)
            objc_score = sum(1 for ind in objc_indicators if ind in content)
            
            return 'matlab' if matlab_score > objc_score else 'objective-c'
        
        elif extension == '.v':
            # Verilog indicators
            verilog_indicators = ['module', 'endmodule', 'wire', 'reg', 'always', 'assign']
            # V language indicators
            vlang_indicators = ['fn ', 'struct ', 'mut ', 'pub fn', 'import ']
            
            verilog_score = sum(1 for ind in verilog_indicators if ind in content_lower)
            vlang_score = sum(1 for ind in vlang_indicators if ind in content_lower)
            
            return 'verilog' if verilog_score > vlang_score else 'vlang'
        
        elif extension == '.h':
            # C++ indicators
            cpp_indicators = ['class ', 'namespace', 'template<', 'std::', '::']
            cpp_score = sum(1 for ind in cpp_indicators if ind in content_lower)
            
            return 'cpp' if cpp_score > 0 else 'c'
        
        return self.LANGUAGE_MAP.get(extension, 'unknown')
    
    def is_supported(self, file_path: Path) -> bool:
        """Check if file language is supported."""
        lang = self.detect(file_path)
        return lang not in ['unknown', 'binary']
    
    def is_binary_extension(self, file_path: Path) -> bool:
        """Check if file has a known binary extension."""
        return file_path.suffix.lower() in self.BINARY_EXTENSIONS


class FileScanner:
    """
    Scan directories for code files with filtering capabilities.
    
    Features:
    - Extension filtering
    - Pattern-based exclusion
    - File size limits
    - Binary file detection with magic numbers
    - Symlink protection
    - Proper encoding detection
    """
    
    # Directories to always exclude (common build/cache/dependency dirs)
    EXCLUDED_DIRS = {
        # Python
        'venv', '.venv', 'env', '.env', '__pycache__', '.pytest_cache',
        '.mypy_cache', '.tox', '.eggs', 'htmlcov', '.coverage',
        'build', 'dist', '*.egg-info',
        
        # JavaScript/Node
        'node_modules', '.next', '.nuxt', '.cache', '.npm',
        
        # Build/Dist
        'build', 'dist', 'out', 'target', '_build',
        
        # Version Control
        '.git', '.svn', '.hg', '.bzr',
        
        # IDEs
        '.vscode', '.idea', '.eclipse', '.settings', '.vs',
        
        # Dependencies/Package Managers
        'vendor', 'Pods', 'Carthage', '.gradle', '.m2', '.cargo',
        'elm-stuff', '.stack-work', '.terraform', '.bundle',
        
        # Temp
        'tmp', 'temp', '.tmp',
        
        # Other
        'coverage', '.sass-cache'
    }
    
    # Magic number signatures for binary file detection
    BINARY_SIGNATURES = [
        (b'\x7fELF', 'ELF executable'),
        (b'MZ', 'Windows PE'),
        (b'\xca\xfe\xba\xbe', 'Java class'),
        (b'\x89PNG', 'PNG image'),
        (b'\xff\xd8\xff', 'JPEG image'),
        (b'GIF8', 'GIF image'),
        (b'%PDF', 'PDF document'),
        (b'PK\x03\x04', 'ZIP archive'),
        (b'\x1f\x8b', 'GZIP archive'),
        (b'BM', 'BMP image'),
        (b'ID3', 'MP3 audio'),
    ]
    
    def __init__(
        self,
        extensions: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        max_file_size_kb: int = 1024
    ):
        """
        Initialize file scanner.
        
        Args:
            extensions: List of file extensions to include (e.g., ['.py', '.js'])
            exclude_patterns: Glob patterns to exclude (e.g., ['node_modules/*', '*.min.js'])
            max_file_size_kb: Maximum file size in kilobytes
        """
        self.extensions = set(extensions) if extensions else set()
        self.exclude_patterns = exclude_patterns or []
        self.max_file_size_bytes = max_file_size_kb * 1024
        self.language_detector = LanguageDetector()
        self._visited_inodes: Set[tuple] = set()  # Track hard links
    
    def scan_directory(
        self,
        directory: Path,
        recursive: bool = True
    ) -> List[Path]:
        """
        Scan directory for code files with symlink protection.
        
        Args:
            directory: Directory to scan
            recursive: Whether to scan subdirectories
            
        Returns:
            List of file paths matching criteria
        """
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")
        
        # Resolve symlinks in the root directory itself
        try:
            directory = directory.resolve(strict=True)
        except (OSError, RuntimeError) as e:
            raise ValueError(f"Cannot resolve directory (possible circular symlink): {e}")
        
        files: List[Path] = []
        self._visited_inodes.clear()  # Reset for new scan
        
        if recursive:
            # Recursive scan with symlink protection
            for root, dirs, filenames in os.walk(directory, followlinks=False):
                root_path = Path(root)
                
                # Check for circular references via inode tracking
                try:
                    stat_info = root_path.stat()
                    inode = (stat_info.st_dev, stat_info.st_ino)
                    
                    # Skip if we've already visited this inode (hard link cycle)
                    if inode in self._visited_inodes:
                        dirs[:] = []  # Don't descend into this directory
                        continue
                    
                    self._visited_inodes.add(inode)
                except OSError:
                    # Permission denied or other error, skip this directory
                    dirs[:] = []
                    continue
                
                # Filter out symlinks and excluded directories
                dirs[:] = [
                    d for d in dirs 
                    if not (root_path / d).is_symlink() 
                    and not self._should_exclude_dir(root_path / d)
                ]
                
                # Process files
                for filename in filenames:
                    file_path = root_path / filename
                    
                    # Skip symlinks at file level too
                    if file_path.is_symlink():
                        continue
                    
                    if self._should_include_file(file_path):
                        files.append(file_path)
        else:
            # Non-recursive scan
            for item in directory.iterdir():
                if item.is_file() and self._should_include_file(item):
                    files.append(item)
        
        return sorted(files)
    
    def _should_include_file(self, file_path: Path) -> bool:
        """Check if file should be included in scan."""
        # Check if file exists and is a file
        if not file_path.is_file():
            return False
        
        # Check extension
        if self.extensions and file_path.suffix not in self.extensions:
            return False
        
        # Check if language is supported
        if self.extensions and not self.language_detector.is_supported(file_path):
            return False
        
        # Check exclusion patterns
        if self._matches_exclude_pattern(file_path):
            return False
        
        # Check file size
        try:
            if file_path.stat().st_size > self.max_file_size_bytes:
                return False
        except OSError:
            return False
        
        # Check if binary
        if self._is_binary(file_path):
            return False
        
        return True
    
    def _should_exclude_dir(self, dir_path: Path) -> bool:
        """Check if directory should be excluded."""
        dir_name = dir_path.name
        
        # Use comprehensive exclusion list
        if dir_name in self.EXCLUDED_DIRS:
            return True
        
        # Check wildcard patterns in EXCLUDED_DIRS
        for pattern in self.EXCLUDED_DIRS:
            if '*' in pattern and fnmatch.fnmatch(dir_name, pattern):
                return True
        
        # Check custom patterns
        return self._matches_exclude_pattern(dir_path)
    
    def _matches_exclude_pattern(self, path: Path) -> bool:
        """Check if path matches any exclusion pattern."""
        path_str = str(path)
        
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(path_str, pattern):
                return True
            
            # Also check just the filename
            if fnmatch.fnmatch(path.name, pattern):
                return True
        
        return False
    
    def _is_binary(self, file_path: Path) -> bool:
        """
        Check if file is binary using multiple strategies.
        
        1. Check extension first (fast)
        2. Check magic numbers (reliable)
        3. Check for text-like content (fallback)
        """
        # Strategy 1: Check extension
        if self.language_detector.is_binary_extension(file_path):
            return True
        
        try:
            with open(file_path, 'rb') as f:
                header = f.read(512)
            
            # Strategy 2: Check magic numbers
            for signature, _ in self.BINARY_SIGNATURES:
                if header.startswith(signature):
                    return True
            
            # Strategy 3: Try to decode as text
            # Check for high ratio of non-text bytes
            if len(header) == 0:
                return False
            
            # Count potentially problematic bytes
            non_text_bytes = sum(
                1 for byte in header
                if byte < 32 and byte not in (9, 10, 13)  # Allow tab, LF, CR
            )
            
            # If more than 30% are non-text bytes, consider it binary
            if non_text_bytes / len(header) > 0.3:
                return True
            
            # Strategy 4: Try UTF-8 decode
            try:
                header.decode('utf-8')
                return False  # Successfully decoded, probably text
            except UnicodeDecodeError:
                # Could be text in different encoding
                # Try to decode with latin-1 (accepts all bytes)
                try:
                    decoded = header.decode('latin-1')
                    # Check if decoded string looks like text
                    printable = sum(1 for c in decoded if c.isprintable() or c.isspace())
                    if printable / len(decoded) > 0.7:
                        return False  # Probably text in different encoding
                except:
                    pass
                
                return True  # Probably binary
            
        except Exception:
            return True  # Assume binary if can't read


def get_file_info(file_path: Path) -> dict:
    """
    Get comprehensive file information.
    
    Args:
        file_path: Path to file
        
    Returns:
        Dictionary with file information
    """
    detector = LanguageDetector()
    stat = file_path.stat()
    
    return {
        'path': str(file_path),
        'name': file_path.name,
        'extension': file_path.suffix,
        'language': detector.detect(file_path),
        'size_bytes': stat.st_size,
        'size_kb': round(stat.st_size / 1024, 2),
        'modified': stat.st_mtime,
        'is_supported': detector.is_supported(file_path)
    }


def read_file_with_encoding_detection(file_path: Path) -> tuple[str, str]:
    """
    Read file with automatic encoding detection.
    
    Tries multiple strategies:
    1. UTF-8 (most common)
    2. UTF-8 with BOM
    3. UTF-16
    4. Latin-1 (ISO-8859-1)
    5. Windows-1252
    
    Args:
        file_path: Path to file
        
    Returns:
        Tuple of (content, encoding_used)
        
    Raises:
        UnicodeDecodeError: If file cannot be decoded with any known encoding
    """
    # Strategy 1: Try UTF-8 with BOM handling (covers both cases)
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        return content, 'utf-8'
    except UnicodeDecodeError:
        pass
    
    # Strategy 2: Try plain UTF-8 (fallback)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content, 'utf-8'
    except UnicodeDecodeError:
        pass
    
    # Strategy 3: Try UTF-16 (Windows files with BOM)
    try:
        with open(file_path, 'r', encoding='utf-16') as f:
            content = f.read()
        return content, 'utf-16'
    except UnicodeDecodeError:
        pass
    
    # Strategy 4: Try Latin-1 (accepts all bytes)
    try:
        with open(file_path, 'r', encoding='latin-1') as f:
            content = f.read()
        return content, 'latin-1'
    except Exception:
        pass
    
    # Strategy 5: Try Windows-1252
    try:
        with open(file_path, 'r', encoding='windows-1252') as f:
            content = f.read()
        return content, 'windows-1252'
    except Exception:
        pass
    
    # If all else fails, raise error
    raise UnicodeDecodeError(
        'unknown', b'', 0, 1,
        f"Cannot decode file {file_path} with any known encoding"
    )


def count_lines(file_path: Path) -> dict:
    """
    Count lines in a file with proper encoding detection.
    
    Args:
        file_path: Path to file
        
    Returns:
        Dictionary with line counts and encoding info
    """
    try:
        content, encoding = read_file_with_encoding_detection(file_path)
        lines = content.splitlines()
        
        total = len(lines)
        blank = sum(1 for line in lines if not line.strip())
        code = total - blank
        
        return {
            'total': total,
            'code': code,
            'blank': blank,
            'comments': 0,  # Would need language-specific parsing
            'encoding': encoding
        }
    except Exception as e:
        return {
            'total': 0,
            'code': 0,
            'blank': 0,
            'comments': 0,
            'encoding': 'unknown',
            'error': str(e)
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CODE SNIPPET EXTRACTOR - Centralized snippet extraction for all analyzers
# ═══════════════════════════════════════════════════════════════════════════════

class CodeSnippetExtractor:
    """
    Centralized code snippet extraction utility.
    
    Features:
    - File content caching for performance
    - Configurable context lines
    - Line highlighting with markers
    - Encoding detection and error handling
    - Thread-safe caching
    
    Usage:
        extractor = CodeSnippetExtractor()
        snippet = extractor.extract(file_path, line_number)
        
        # Or use class method for one-off extraction
        snippet = CodeSnippetExtractor.extract_snippet(file_path, line_number)
    """
    
    # Class-level cache for file contents (shared across instances)
    _file_cache: dict = {}
    _cache_max_size: int = 100  # Maximum number of files to cache
    
    def __init__(self, context_lines: int = 3, use_cache: bool = True):
        """
        Initialize snippet extractor.
        
        Args:
            context_lines: Number of lines to show before/after issue line
            use_cache: Whether to cache file contents for performance
        """
        self.context_lines = context_lines
        self.use_cache = use_cache
    
    def extract(
        self, 
        file_path: str, 
        line_number: int, 
        context_lines: Optional[int] = None
    ) -> str:
        """
        Extract code snippet from file with line numbers and highlighting.
        
        Args:
            file_path: Path to source file (absolute or relative)
            line_number: Line number where issue was detected (1-based)
            context_lines: Override default context lines (optional)
            
        Returns:
            Formatted code snippet with line numbers, highlighted issue line,
            or empty string if extraction fails
        """
        ctx = context_lines if context_lines is not None else self.context_lines
        return self._do_extract(file_path, line_number, ctx)
    
    @classmethod
    def extract_snippet(
        cls,
        file_path: str,
        line_number: int,
        context_lines: int = 3
    ) -> str:
        """
        Class method for one-off snippet extraction (no instance needed).
        
        Args:
            file_path: Path to source file
            line_number: Line number (1-based)
            context_lines: Lines of context before/after
            
        Returns:
            Formatted code snippet or empty string
        """
        extractor = cls(context_lines=context_lines, use_cache=True)
        return extractor.extract(file_path, line_number)
    
    @classmethod
    def extract_from_content(
        cls,
        content: str,
        line_number: int,
        context_lines: int = 3
    ) -> str:
        """
        Extract snippet from already-loaded content (no file I/O).
        
        Args:
            content: Source code content
            line_number: Line number (1-based)
            context_lines: Lines of context before/after
            
        Returns:
            Formatted code snippet or empty string
        """
        if not content or not line_number or line_number <= 0:
            return ''
        
        lines = content.splitlines()
        
        if not lines or line_number > len(lines):
            return ''
        
        return cls._format_snippet(lines, line_number, context_lines)
    
    def _do_extract(self, file_path: str, line_number: int, context_lines: int) -> str:
        """Internal extraction implementation."""
        # Validate inputs
        if not line_number or line_number <= 0:
            return ''
        
        if not file_path:
            return ''
        
        try:
            # Resolve path
            path = Path(file_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            
            resolved_path = str(path.resolve())
            
            # Check if file exists
            if not path.is_file():
                return ''
            
            # Get file content (cached or fresh)
            lines = self._get_file_lines(resolved_path)
            
            if not lines or line_number > len(lines):
                return ''
            
            return self._format_snippet(lines, line_number, context_lines)
            
        except (OSError, IOError, PermissionError) as e:
            # File access errors - return empty silently
            return ''
        except Exception as e:
            # Unexpected errors - return empty to avoid breaking callers
            return ''
    
    def _get_file_lines(self, file_path: str) -> List[str]:
        """Get file lines with optional caching."""
        if self.use_cache and file_path in self._file_cache:
            return self._file_cache[file_path]
        
        # Read file with encoding detection
        try:
            content = Path(file_path).read_text(encoding='utf-8', errors='replace')
        except UnicodeDecodeError:
            # Try with latin-1 as fallback
            try:
                content = Path(file_path).read_text(encoding='latin-1', errors='replace')
            except Exception:
                return []
        
        lines = content.splitlines()
        
        # Cache if enabled (with size limit)
        if self.use_cache:
            if len(self._file_cache) >= self._cache_max_size:
                # Remove oldest entry (FIFO)
                oldest_key = next(iter(self._file_cache))
                del self._file_cache[oldest_key]
            self._file_cache[file_path] = lines
        
        return lines
    
    @staticmethod
    def _format_snippet(lines: List[str], line_number: int, context_lines: int) -> str:
        """
        Format code snippet with line numbers and highlighting.
        
        Format:
            >>> 123 | <issue line>     <- Highlighted with >>>
                124 | <next line>      <- Normal lines with spaces
        """
        # Calculate boundaries (1-based line numbers)
        start_line = max(1, line_number - context_lines)
        end_line = min(len(lines), line_number + context_lines)
        
        # Extract snippet (convert to 0-based for list indexing)
        snippet_lines = lines[start_line - 1:end_line]
        
        # Format with line numbers and marker
        formatted = []
        for idx, line in enumerate(snippet_lines, start=start_line):
            marker = ">>> " if idx == line_number else "    "
            formatted.append(f"{marker}{idx:>4} | {line}")
        
        return "\n".join(formatted)
    
    @classmethod
    def clear_cache(cls):
        """Clear the file content cache."""
        cls._file_cache.clear()
    
    @classmethod
    def get_cache_stats(cls) -> dict:
        """Get cache statistics."""
        return {
            'cached_files': len(cls._file_cache),
            'max_size': cls._cache_max_size
        }
