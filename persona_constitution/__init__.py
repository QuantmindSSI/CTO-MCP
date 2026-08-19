"""persona-constitution: an MCP server serving the Agentic Engineering Persona.

Exposes the constitution loader, the markdown section extractors, the
Zero-Framework-Tolerance code scanner (CodebaseCSI-backed), the diff-aware PR
review engine, and the JSON-RPC dispatch layer so they can be imported and
tested directly, independent of the stdio transport.
"""

from .review.engine import review_patch
from .scanner import (
    PROSE_RULES,
    scan_code,
)
from .server import (
    DEPRECATED_SECTION_ALIASES,
    KA_TITLES,
    PROTOCOL_VERSION,
    SECTION_MAP,
    SERVER_INFO,
    TOOLS,
    VERIFICATION_GATES,
    dispatch,
    find_section,
    find_subsection,
    load_constitution,
    resolve_constitution_path,
    serve,
    split_headings,
)

__version__ = "3.2.0"

__all__ = [
    "DEPRECATED_SECTION_ALIASES",
    "KA_TITLES",
    "PROSE_RULES",
    "PROTOCOL_VERSION",
    "SECTION_MAP",
    "SERVER_INFO",
    "TOOLS",
    "VERIFICATION_GATES",
    "__version__",
    "dispatch",
    "find_section",
    "find_subsection",
    "load_constitution",
    "resolve_constitution_path",
    "review_patch",
    "scan_code",
    "serve",
    "split_headings",
]
