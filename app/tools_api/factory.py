from __future__ import annotations
import os
from functools import lru_cache

from .facade import ToolsFacade
from .local_adapters.local_tools_adapter import LocalToolsAdapter

try:
    # 预留：若未来提供 MCP 适配器，可在此导入并切换
    from .mcp_adapters.mcp_tools_adapter import McpToolsAdapter  # type: ignore
except Exception:  # pragma: no cover - MCP 非必需
    McpToolsAdapter = None  # type: ignore


@lru_cache(maxsize=1)
def resolve_tool_facade() -> ToolsFacade:
    """
    工具工厂：根据配置选择实现。
    - 默认返回本地实现（LocalToolsAdapter）。
    - 当 TOOL_IMPL=mcp 且 MCP 适配器可用时，返回 MCP 实现。
    """
    impl = os.getenv("TOOL_IMPL", "local").lower()

    if impl == "mcp" and McpToolsAdapter is not None:
        return McpToolsAdapter()  # type: ignore

    return LocalToolsAdapter()
