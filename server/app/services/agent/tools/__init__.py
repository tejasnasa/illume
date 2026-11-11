"""The tool registry and the tools registered on it.

Importing this package registers every tool, so ``REGISTRY`` is complete once it
has been imported.
"""

from app.services.agent.tools import (  # noqa: F401  (each module registers its tools on import)
    finish,
    graph,
    info,
    navigate,
    read_file,
    search,
)
from app.services.agent.tools.context import (
    NodeEvent,
    RepoSnapshot,
    SharedBudget,
    ToolContext,
)
from app.services.agent.tools.registry import (
    REGISTRY,
    Tool,
    ToolInput,
    ToolRegistry,
    ToolResult,
    function_tools,
    strict_schema,
)

__all__ = [
    "REGISTRY",
    "NodeEvent",
    "RepoSnapshot",
    "SharedBudget",
    "Tool",
    "ToolContext",
    "ToolInput",
    "ToolRegistry",
    "ToolResult",
    "function_tools",
    "strict_schema",
]
