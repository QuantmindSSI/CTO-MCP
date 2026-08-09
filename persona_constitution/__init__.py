"""persona-constitution: an MCP server serving the Agentic Engineering Persona.

Exposes the constitution loader, the markdown section extractors, the
Zero-Framework-Tolerance code scanner (CodebaseCSI-backed), and the JSON-RPC dispatch layer so they
can be imported and tested directly, independent of the stdio transport.
"""

from .scanner import (  # noqa: F401 - re-exported as the package's public API.
    PROSE_RULES,
    scan_code,
)
from .server import (  # noqa: F401 - re-exported as the package's public API.
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

__version__ = "3.0.0"

__all__ = [
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
    "scan_code",
    "serve",
    "split_headings",
]
