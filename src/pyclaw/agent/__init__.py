"""
PyClaw Agent 模块 - 核心智能层
"""

from .tools import ToolRegistry, Tool, ToolParameter, ToolResult
from .agent import AgentCore, AgentResponse
from .builtin_tools import (
    register_builtin_tools,
    create_builtin_registry,
    # 独立工具函数（可单独使用）
    shell_exec,
    applescript_exec,
    screenshot,
    clipboard_get,
    clipboard_set,
    notify,
    open_app,
    open_url,
    get_system_info,
    get_running_apps,
    list_files,
    read_file,
    write_file,
    set_volume,
    get_volume,
    power_action,
)
from .tool_guard import (
    ToolGuard,
    SafeToolRegistry,
    IntentParser,
    DangerousPatternDetector,
    OperationIntent,
    OperationType,
    RiskLevel,
    ConfirmationRequest,
    get_tool_guard,
    analyze_command_risk,
)

__all__ = [
    # 核心类
    "ToolRegistry",
    "Tool",
    "ToolParameter",
    "ToolResult",
    "AgentCore",
    "AgentResponse",
    # 内置工具注册
    "register_builtin_tools",
    "create_builtin_registry",
    # 独立工具函数
    "shell_exec",
    "applescript_exec",
    "screenshot",
    "clipboard_get",
    "clipboard_set",
    "notify",
    "open_app",
    "open_url",
    "get_system_info",
    "get_running_apps",
    "list_files",
    "read_file",
    "write_file",
    "set_volume",
    "get_volume",
    "power_action",
    # 安全守卫
    "ToolGuard",
    "SafeToolRegistry",
    "IntentParser",
    "DangerousPatternDetector",
    "OperationIntent",
    "OperationType",
    "RiskLevel",
    "ConfirmationRequest",
    "get_tool_guard",
    "analyze_command_risk",
]
