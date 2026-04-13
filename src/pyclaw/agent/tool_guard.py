"""
工具安全守卫 - 意图确认和敏感操作保护

解决的问题：
1. 确保正确理解用户意图
2. 敏感操作二次确认
3. 操作预览和撤销
4. 危险命令拦截
"""

import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class OperationType(Enum):
    """操作类型"""
    READ = "read"           # 读取（安全）
    WRITE = "write"         # 写入
    DELETE = "delete"       # 删除（危险）
    MOVE = "move"           # 移动
    EXECUTE = "execute"     # 执行命令
    SYSTEM = "system"       # 系统操作
    NETWORK = "network"     # 网络操作


class RiskLevel(Enum):
    """风险等级"""
    SAFE = "safe"           # 安全，无需确认
    LOW = "low"             # 低风险，记录日志
    MEDIUM = "medium"       # 中风险，需确认
    HIGH = "high"           # 高风险，需二次确认
    CRITICAL = "critical"   # 极高风险，默认拒绝


@dataclass
class OperationIntent:
    """操作意图"""
    tool_name: str                      # 工具名称
    operation_type: OperationType       # 操作类型
    risk_level: RiskLevel              # 风险等级
    target: str                         # 操作目标
    description: str                    # 人类可读描述
    parameters: Dict[str, Any] = field(default_factory=dict)
    reversible: bool = False           # 是否可撤销
    preview: Optional[str] = None      # 操作预览


@dataclass
class ConfirmationRequest:
    """确认请求"""
    intent: OperationIntent
    message: str                        # 确认消息
    options: List[str] = field(default_factory=lambda: ["确认", "取消"])
    timeout: int = 60                   # 超时秒数
    require_exact_match: bool = False   # 是否要求精确匹配（用于高危操作）


@dataclass
class OperationRecord:
    """操作记录（用于审计和撤销）"""
    id: str
    intent: OperationIntent
    timestamp: datetime
    confirmed_by: Optional[str] = None
    result: Optional[Dict] = None
    backup_path: Optional[str] = None   # 备份路径（用于撤销）


class DangerousPatternDetector:
    """危险模式检测器"""

    # 危险的 shell 命令模式
    DANGEROUS_COMMANDS = {
        # 删除相关
        r"rm\s+-rf?\s+[~/]": (RiskLevel.CRITICAL, "递归删除根目录或主目录"),
        r"rm\s+-rf?\s+/": (RiskLevel.CRITICAL, "删除系统目录"),
        r"rm\s+-rf?\s+\*": (RiskLevel.HIGH, "删除所有文件"),
        r"rm\s+": (RiskLevel.MEDIUM, "删除文件"),

        # 系统修改
        r"sudo\s+": (RiskLevel.HIGH, "以管理员权限执行"),
        r"chmod\s+777": (RiskLevel.HIGH, "设置危险权限"),
        r"chown\s+": (RiskLevel.MEDIUM, "修改文件所有者"),

        # 磁盘操作
        r"dd\s+if=": (RiskLevel.CRITICAL, "磁盘写入操作"),
        r"mkfs": (RiskLevel.CRITICAL, "格式化磁盘"),
        r"fdisk": (RiskLevel.CRITICAL, "分区操作"),

        # 网络危险
        r"curl.*\|\s*sh": (RiskLevel.CRITICAL, "从网络执行脚本"),
        r"wget.*\|\s*sh": (RiskLevel.CRITICAL, "从网络执行脚本"),
        r"curl.*\|\s*bash": (RiskLevel.CRITICAL, "从网络执行脚本"),

        # 系统控制
        r"shutdown": (RiskLevel.HIGH, "关机"),
        r"reboot": (RiskLevel.HIGH, "重启"),
        r"halt": (RiskLevel.HIGH, "停止系统"),

        # 数据库
        r"DROP\s+DATABASE": (RiskLevel.CRITICAL, "删除数据库"),
        r"DROP\s+TABLE": (RiskLevel.HIGH, "删除数据表"),
        r"DELETE\s+FROM\s+\w+\s*;": (RiskLevel.HIGH, "删除所有记录"),
        r"TRUNCATE": (RiskLevel.HIGH, "清空表"),

        # Git 危险操作
        r"git\s+push\s+.*--force": (RiskLevel.HIGH, "强制推送"),
        r"git\s+reset\s+--hard": (RiskLevel.MEDIUM, "硬重置"),
        r"git\s+clean\s+-fd": (RiskLevel.MEDIUM, "清理未跟踪文件"),
    }

    # 敏感路径
    SENSITIVE_PATHS = {
        "/": RiskLevel.CRITICAL,
        "/System": RiskLevel.CRITICAL,
        "/Library": RiskLevel.CRITICAL,
        "/Applications": RiskLevel.HIGH,
        "/Users": RiskLevel.HIGH,
        "~": RiskLevel.MEDIUM,
        "~/Documents": RiskLevel.MEDIUM,
        "~/Desktop": RiskLevel.MEDIUM,
        "~/Downloads": RiskLevel.LOW,
    }

    # 敏感文件模式
    SENSITIVE_FILES = [
        (r"\.env$", RiskLevel.HIGH, "环境变量文件"),
        (r"\.ssh/", RiskLevel.CRITICAL, "SSH 密钥目录"),
        (r"\.aws/", RiskLevel.CRITICAL, "AWS 配置"),
        (r"\.kube/", RiskLevel.HIGH, "Kubernetes 配置"),
        (r"id_rsa", RiskLevel.CRITICAL, "SSH 私钥"),
        (r"\.pem$", RiskLevel.HIGH, "证书文件"),
        (r"password", RiskLevel.HIGH, "密码相关文件"),
        (r"secret", RiskLevel.HIGH, "密钥相关文件"),
        (r"credentials", RiskLevel.HIGH, "凭证文件"),
    ]

    @classmethod
    def detect_command_risk(cls, command: str) -> Tuple[RiskLevel, str]:
        """
        检测命令风险

        Returns:
            (风险等级, 风险描述)
        """
        command_lower = command.lower()

        for pattern, (level, desc) in cls.DANGEROUS_COMMANDS.items():
            if re.search(pattern, command, re.IGNORECASE):
                return level, desc

        return RiskLevel.LOW, ""

    @classmethod
    def detect_path_risk(cls, path: str) -> Tuple[RiskLevel, str]:
        """检测路径风险"""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)

        # 检查敏感路径
        for sensitive_path, level in cls.SENSITIVE_PATHS.items():
            expanded = os.path.expanduser(sensitive_path)
            if abs_path == expanded or abs_path.startswith(expanded + "/"):
                # 如果是子目录，降低一级风险
                if abs_path != expanded and level != RiskLevel.CRITICAL:
                    level = RiskLevel(list(RiskLevel)[max(0, list(RiskLevel).index(level) - 1)].value)
                return level, f"敏感路径: {sensitive_path}"

        # 检查敏感文件模式
        for pattern, level, desc in cls.SENSITIVE_FILES:
            if re.search(pattern, path, re.IGNORECASE):
                return level, desc

        return RiskLevel.SAFE, ""


class IntentParser:
    """意图解析器 - 从工具调用中提取操作意图"""

    # 工具到操作类型的映射
    TOOL_OPERATIONS = {
        # 系统工具
        "shell_exec": OperationType.EXECUTE,
        "applescript_exec": OperationType.EXECUTE,
        "power_action": OperationType.SYSTEM,

        # 文件操作
        "read_file": OperationType.READ,
        "write_file": OperationType.WRITE,
        "list_files": OperationType.READ,

        # 系统信息（安全）
        "get_system_info": OperationType.READ,
        "get_running_apps": OperationType.READ,
        "get_volume": OperationType.READ,
        "clipboard_get": OperationType.READ,

        # 系统修改
        "clipboard_set": OperationType.WRITE,
        "set_volume": OperationType.SYSTEM,
        "notify": OperationType.SYSTEM,
        "open_app": OperationType.EXECUTE,
        "open_url": OperationType.NETWORK,
        "screenshot": OperationType.READ,
    }

    @classmethod
    def parse(cls, tool_name: str, arguments: Dict[str, Any]) -> OperationIntent:
        """
        解析工具调用为操作意图

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            操作意图
        """
        op_type = cls.TOOL_OPERATIONS.get(tool_name, OperationType.EXECUTE)
        risk_level = RiskLevel.LOW
        target = ""
        description = ""
        reversible = False
        preview = None

        # 根据工具类型解析
        if tool_name == "shell_exec":
            command = arguments.get("command", "")
            target = command
            risk_level, risk_desc = DangerousPatternDetector.detect_command_risk(command)
            description = f"执行命令: {command[:50]}{'...' if len(command) > 50 else ''}"
            if risk_desc:
                description += f" ({risk_desc})"

            # 检测是否为删除/移动操作
            if re.search(r"\brm\b", command):
                op_type = OperationType.DELETE
                reversible = False
            elif re.search(r"\bmv\b", command):
                op_type = OperationType.MOVE
                reversible = True

        elif tool_name == "write_file":
            path = arguments.get("path", "")
            content = arguments.get("content", "")
            target = path
            path_risk, path_desc = DangerousPatternDetector.detect_path_risk(path)
            risk_level = path_risk
            description = f"写入文件: {path}"
            preview = f"内容预览 ({len(content)} 字符):\n{content[:200]}{'...' if len(content) > 200 else ''}"
            reversible = True  # 可以通过备份恢复

        elif tool_name == "applescript_exec":
            script = arguments.get("script", "")
            target = script[:100]
            description = f"执行 AppleScript: {script[:50]}..."
            # AppleScript 可能涉及 GUI 操作，默认中等风险
            risk_level = RiskLevel.MEDIUM

        elif tool_name == "power_action":
            action = arguments.get("action", "")
            target = action
            description = f"电源操作: {action}"
            if action in ("sleep", "lock", "screensaver"):
                risk_level = RiskLevel.MEDIUM
            else:
                risk_level = RiskLevel.HIGH

        elif tool_name == "open_url":
            url = arguments.get("url", "")
            target = url
            description = f"打开 URL: {url}"
            risk_level = RiskLevel.LOW

        elif tool_name == "open_app":
            app = arguments.get("app_name", "")
            target = app
            description = f"打开应用: {app}"
            risk_level = RiskLevel.LOW

        else:
            # 默认处理
            target = str(arguments)[:100]
            description = f"调用工具: {tool_name}"

        return OperationIntent(
            tool_name=tool_name,
            operation_type=op_type,
            risk_level=risk_level,
            target=target,
            description=description,
            parameters=arguments,
            reversible=reversible,
            preview=preview
        )


class ToolGuard:
    """
    工具安全守卫

    提供：
    - 意图确认
    - 敏感操作保护
    - 操作审计
    - 备份和撤销

    使用示例:
        guard = ToolGuard()

        # 设置确认回调
        guard.set_confirm_callback(my_confirm_func)

        # 检查操作
        intent = guard.analyze("shell_exec", {"command": "rm -rf /tmp/test"})

        if guard.requires_confirmation(intent):
            request = guard.create_confirmation_request(intent)
            if not guard.confirm(request):
                return "操作已取消"

        # 执行操作（带备份）
        result = guard.execute_with_protection(tool_func, intent)
    """

    def __init__(
        self,
        backup_dir: Optional[str] = None,
        max_risk_level: RiskLevel = RiskLevel.HIGH,
        always_confirm_types: Optional[Set[OperationType]] = None
    ):
        """
        初始化守卫

        Args:
            backup_dir: 备份目录
            max_risk_level: 允许的最大风险等级
            always_confirm_types: 始终需要确认的操作类型
        """
        self._backup_dir = backup_dir or os.path.expanduser("~/.pyclaw/backups")
        self._max_risk_level = max_risk_level
        self._always_confirm = always_confirm_types or {
            OperationType.DELETE,
            OperationType.MOVE,
        }

        self._confirm_callback: Optional[Callable[[str], bool]] = None
        self._operation_history: List[OperationRecord] = []
        self._pending_confirmations: Dict[str, ConfirmationRequest] = {}

        # 确保备份目录存在
        os.makedirs(self._backup_dir, exist_ok=True)

    def set_confirm_callback(self, callback: Callable[[str], bool]) -> None:
        """设置确认回调"""
        self._confirm_callback = callback

    def analyze(self, tool_name: str, arguments: Dict[str, Any]) -> OperationIntent:
        """分析工具调用，返回操作意图"""
        return IntentParser.parse(tool_name, arguments)

    def requires_confirmation(self, intent: OperationIntent) -> bool:
        """判断是否需要确认"""
        # 始终需要确认的操作类型
        if intent.operation_type in self._always_confirm:
            return True

        # 根据风险等级判断
        risk_order = list(RiskLevel)
        if risk_order.index(intent.risk_level) >= risk_order.index(RiskLevel.MEDIUM):
            return True

        return False

    def is_allowed(self, intent: OperationIntent) -> Tuple[bool, str]:
        """判断操作是否被允许"""
        risk_order = list(RiskLevel)
        if risk_order.index(intent.risk_level) > risk_order.index(self._max_risk_level):
            return False, f"操作风险等级 ({intent.risk_level.value}) 超过允许的最大等级 ({self._max_risk_level.value})"
        return True, ""

    def create_confirmation_request(self, intent: OperationIntent) -> ConfirmationRequest:
        """创建确认请求"""
        lines = [
            "⚠️ 操作确认请求",
            "",
            f"操作: {intent.description}",
            f"类型: {intent.operation_type.value}",
            f"风险等级: {intent.risk_level.value.upper()}",
            f"目标: {intent.target[:100]}",
        ]

        if intent.preview:
            lines.extend(["", "预览:", intent.preview])

        if not intent.reversible:
            lines.extend(["", "⚠️ 此操作不可撤销！"])

        lines.extend(["", "请回复 '确认' 或 '取消'"])

        # 高危操作需要输入特定确认词
        require_exact = intent.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        if require_exact:
            confirm_code = hashlib.md5(intent.target.encode()).hexdigest()[:4].upper()
            lines.append(f"高危操作，请输入确认码: {confirm_code}")

        request = ConfirmationRequest(
            intent=intent,
            message="\n".join(lines),
            options=["确认", "取消"],
            require_exact_match=require_exact
        )

        # 保存待确认请求
        request_id = hashlib.md5(
            f"{intent.tool_name}:{intent.target}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:8]
        self._pending_confirmations[request_id] = request

        return request

    def confirm(self, request: ConfirmationRequest) -> bool:
        """执行确认"""
        if not self._confirm_callback:
            logger.warning("未设置确认回调，默认拒绝")
            return False

        try:
            response = self._confirm_callback(request.message)
            return response
        except Exception as e:
            logger.error(f"确认回调失败: {e}")
            return False

    def backup_file(self, path: str) -> Optional[str]:
        """
        备份文件

        Returns:
            备份路径，失败返回 None
        """
        try:
            path = os.path.expanduser(path)
            if not os.path.exists(path):
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.basename(path)
            backup_path = os.path.join(
                self._backup_dir,
                f"{filename}.{timestamp}.backup"
            )

            if os.path.isdir(path):
                shutil.copytree(path, backup_path)
            else:
                shutil.copy2(path, backup_path)

            logger.info(f"已备份: {path} -> {backup_path}")
            return backup_path

        except Exception as e:
            logger.error(f"备份失败: {e}")
            return None

    def execute_with_protection(
        self,
        tool_func: Callable,
        intent: OperationIntent,
        confirmed: bool = False
    ) -> Dict[str, Any]:
        """
        带保护执行工具

        Args:
            tool_func: 工具函数
            intent: 操作意图
            confirmed: 是否已确认

        Returns:
            执行结果
        """
        # 检查是否允许
        allowed, reason = self.is_allowed(intent)
        if not allowed:
            return {
                "success": False,
                "error": reason,
                "blocked": True
            }

        # 检查是否需要确认
        if not confirmed and self.requires_confirmation(intent):
            return {
                "success": False,
                "error": "操作需要用户确认",
                "requires_confirmation": True,
                "intent": {
                    "description": intent.description,
                    "risk_level": intent.risk_level.value,
                    "operation_type": intent.operation_type.value
                }
            }

        # 备份（如果适用）
        backup_path = None
        if intent.operation_type in (OperationType.DELETE, OperationType.MOVE, OperationType.WRITE):
            target_path = self._extract_path(intent)
            if target_path:
                backup_path = self.backup_file(target_path)

        # 记录操作
        record = OperationRecord(
            id=hashlib.md5(f"{datetime.now().isoformat()}".encode()).hexdigest()[:8],
            intent=intent,
            timestamp=datetime.now(),
            confirmed_by="user" if confirmed else None,
            backup_path=backup_path
        )

        # 执行
        try:
            result = tool_func(**intent.parameters)
            record.result = result if isinstance(result, dict) else {"output": result}
            self._operation_history.append(record)

            return {
                "success": True,
                "result": result,
                "operation_id": record.id,
                "backup_path": backup_path
            }

        except Exception as e:
            logger.error(f"工具执行失败: {e}")
            record.result = {"error": str(e)}
            self._operation_history.append(record)

            return {
                "success": False,
                "error": str(e),
                "operation_id": record.id,
                "backup_path": backup_path
            }

    def _extract_path(self, intent: OperationIntent) -> Optional[str]:
        """从意图中提取文件路径"""
        params = intent.parameters

        # 直接路径参数
        if "path" in params:
            return params["path"]

        # 从命令中提取
        if intent.tool_name == "shell_exec":
            command = params.get("command", "")
            # 简单提取最后一个参数作为路径
            parts = command.split()
            if len(parts) >= 2:
                last = parts[-1]
                if last.startswith("/") or last.startswith("~") or last.startswith("."):
                    return last

        return None

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取操作历史"""
        return [
            {
                "id": r.id,
                "description": r.intent.description,
                "timestamp": r.timestamp.isoformat(),
                "risk_level": r.intent.risk_level.value,
                "has_backup": r.backup_path is not None
            }
            for r in self._operation_history[-limit:]
        ]

    def undo(self, operation_id: str) -> Dict[str, Any]:
        """
        撤销操作

        Args:
            operation_id: 操作 ID

        Returns:
            撤销结果
        """
        # 查找操作记录
        record = next(
            (r for r in self._operation_history if r.id == operation_id),
            None
        )

        if not record:
            return {"success": False, "error": f"操作 {operation_id} 不存在"}

        if not record.backup_path:
            return {"success": False, "error": "此操作没有备份，无法撤销"}

        if not os.path.exists(record.backup_path):
            return {"success": False, "error": "备份文件不存在"}

        # 恢复备份
        try:
            target_path = self._extract_path(record.intent)
            if not target_path:
                return {"success": False, "error": "无法确定目标路径"}

            target_path = os.path.expanduser(target_path)

            if os.path.isdir(record.backup_path):
                if os.path.exists(target_path):
                    shutil.rmtree(target_path)
                shutil.copytree(record.backup_path, target_path)
            else:
                shutil.copy2(record.backup_path, target_path)

            return {
                "success": True,
                "message": f"已恢复: {target_path}",
                "from_backup": record.backup_path
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# 集成到工具系统的包装器
# ============================================================================

class SafeToolRegistry:
    """
    安全工具注册表包装器

    包装 ToolRegistry，自动添加安全检查。
    """

    def __init__(self, registry, guard: Optional[ToolGuard] = None):
        """
        Args:
            registry: 原始 ToolRegistry
            guard: 工具守卫（可选，默认创建新实例）
        """
        self._registry = registry
        self._guard = guard or ToolGuard()

    def set_confirm_callback(self, callback: Callable[[str], bool]) -> None:
        """设置确认回调"""
        self._guard.set_confirm_callback(callback)

    def execute(
        self,
        name: str,
        arguments: Dict[str, Any],
        skip_confirmation: bool = False
    ) -> Dict[str, Any]:
        """
        安全执行工具

        Args:
            name: 工具名称
            arguments: 参数
            skip_confirmation: 跳过确认（用于已确认的操作）

        Returns:
            执行结果
        """
        # 分析意图
        intent = self._guard.analyze(name, arguments)

        # 检查是否允许
        allowed, reason = self._guard.is_allowed(intent)
        if not allowed:
            return {
                "success": False,
                "error": reason,
                "blocked": True
            }

        # 检查是否需要确认
        if not skip_confirmation and self._guard.requires_confirmation(intent):
            request = self._guard.create_confirmation_request(intent)

            if not self._guard.confirm(request):
                return {
                    "success": False,
                    "error": "用户取消操作",
                    "cancelled": True
                }

        # 获取工具
        tool = self._registry.get(name)
        if not tool or not tool.handler:
            return {
                "success": False,
                "error": f"工具不存在或无处理函数: {name}"
            }

        # 执行
        return self._guard.execute_with_protection(
            tool.handler,
            intent,
            confirmed=True
        )

    def analyze_intent(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        仅分析意图，不执行

        用于在执行前向用户展示将要进行的操作。
        """
        intent = self._guard.analyze(name, arguments)

        return {
            "tool": name,
            "operation_type": intent.operation_type.value,
            "risk_level": intent.risk_level.value,
            "description": intent.description,
            "target": intent.target,
            "reversible": intent.reversible,
            "preview": intent.preview,
            "requires_confirmation": self._guard.requires_confirmation(intent),
        }

    @property
    def guard(self) -> ToolGuard:
        return self._guard

    @property
    def registry(self):
        return self._registry


# ============================================================================
# 便捷函数
# ============================================================================

_global_guard: Optional[ToolGuard] = None


def get_tool_guard() -> ToolGuard:
    """获取全局工具守卫"""
    global _global_guard
    if _global_guard is None:
        _global_guard = ToolGuard()
    return _global_guard


def analyze_command_risk(command: str) -> Dict[str, Any]:
    """
    分析命令风险

    便捷函数，用于快速检查命令是否危险。
    """
    level, desc = DangerousPatternDetector.detect_command_risk(command)
    return {
        "command": command,
        "risk_level": level.value,
        "risk_description": desc,
        "requires_confirmation": level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL),
        "blocked": level == RiskLevel.CRITICAL
    }
