"""
工作区文件管理 - Markdown 文件存储层

管理 SOUL.md, USER.md, MEMORY.md 等工作区文件。
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, date
import logging

from ..core.logger import LoggerMixin

logger = logging.getLogger(__name__)


# 工作区文件定义
WORKSPACE_FILES = {
    "AGENTS.md": "Agent 操作指令和行为规范",
    "SOUL.md": "人格、语气、边界定义",
    "USER.md": "用户身份信息",
    "IDENTITY.md": "Agent 名称、主题、emoji、头像",
    "TOOLS.md": "本地工具使用说明",
    "HEARTBEAT.md": "心跳检查清单",
    "BOOT.md": "启动检查清单",
    "BOOTSTRAP.md": "首次运行仪式",
    "MEMORY.md": "策划的长期记忆",
}


class WorkspaceManager(LoggerMixin):
    """
    工作区文件管理器

    管理 ~/.pyclaw/workspace/ 目录下的 Markdown 文件。

    使用示例:
        workspace = WorkspaceManager()

        # 读取文件
        soul = workspace.read("SOUL.md")

        # 写入文件
        workspace.write("USER.md", "# 用户信息\\n...")

        # 获取所有工作区内容
        context = workspace.get_workspace_context()
    """

    def __init__(self, workspace_dir: Optional[str] = None):
        """
        初始化工作区管理器

        Args:
            workspace_dir: 工作区目录，默认 ~/.pyclaw/workspace
        """
        if workspace_dir:
            self.workspace_dir = Path(workspace_dir).expanduser()
        else:
            self.workspace_dir = Path.home() / ".pyclaw" / "workspace"

        self.memory_dir = self.workspace_dir / "memory"

    def initialize(self) -> None:
        """初始化工作区目录结构"""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 创建默认文件（如果不存在）
        self._create_default_files()

        self.logger.info(f"工作区初始化完成: {self.workspace_dir}")

    def _create_default_files(self) -> None:
        """创建默认工作区文件"""
        defaults = {
            "SOUL.md": self._default_soul(),
            "USER.md": self._default_user(),
            "IDENTITY.md": self._default_identity(),
            "MEMORY.md": self._default_memory(),
        }

        for filename, content in defaults.items():
            filepath = self.workspace_dir / filename
            if not filepath.exists():
                filepath.write_text(content, encoding="utf-8")
                self.logger.debug(f"创建默认文件: {filename}")

    def _default_soul(self) -> str:
        return """# 人格定义

## 基本特质
- 友好、耐心、专业
- 偏好简洁直接的沟通方式
- 尊重用户隐私

## 语气风格
- 使用中文交流
- 避免过度使用表情符号
- 技术讨论时保持专业

## 边界
- 不讨论政治敏感话题
- 不提供医疗/法律建议
- 遇到不确定的问题会坦诚说明
"""

    def _default_user(self) -> str:
        return """# 用户信息

## 基本信息
- 姓名: [待填写]
- 时区: Asia/Shanghai

## 偏好
- 编程语言: [待填写]
- 工作时间: 09:00-22:00

## 备注
- [在此添加关于用户的备注]
"""

    def _default_identity(self) -> str:
        return """# Agent 身份

## 基本信息
- 名称: PyClaw
- 主题: 个人 AI 助手
- Emoji: 🐾

## 描述
PyClaw 是一个轻量级的个人 AI 助手，帮助用户完成日常任务。
"""

    def _default_memory(self) -> str:
        return """# 长期记忆

## 重要事项
- [在此记录重要的长期记忆]

## 用户偏好
- [在此记录用户的偏好设置]

## 待办事项
- [在此记录长期待办事项]
"""

    # ============================================================
    # 文件读写
    # ============================================================

    def read(self, filename: str) -> Optional[str]:
        """
        读取工作区文件

        Args:
            filename: 文件名（如 SOUL.md）

        Returns:
            文件内容，不存在返回 None
        """
        filepath = self.workspace_dir / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def write(self, filename: str, content: str) -> None:
        """
        写入工作区文件

        Args:
            filename: 文件名
            content: 文件内容
        """
        filepath = self.workspace_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        self.logger.debug(f"写入文件: {filename}")

    def append(self, filename: str, content: str) -> None:
        """追加内容到文件"""
        filepath = self.workspace_dir / filename
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(content)

    def exists(self, filename: str) -> bool:
        """检查文件是否存在"""
        return (self.workspace_dir / filename).exists()

    def list_files(self) -> List[str]:
        """列出所有工作区文件"""
        if not self.workspace_dir.exists():
            return []
        return [f.name for f in self.workspace_dir.glob("*.md")]

    def delete(self, filename: str) -> bool:
        """删除文件"""
        filepath = self.workspace_dir / filename
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    # ============================================================
    # 每日记忆
    # ============================================================

    def get_daily_memory_path(self, dt: Optional[date] = None) -> Path:
        """获取每日记忆文件路径"""
        dt = dt or date.today()
        return self.memory_dir / f"{dt.isoformat()}.md"

    def read_daily_memory(self, dt: Optional[date] = None) -> Optional[str]:
        """读取每日记忆"""
        path = self.get_daily_memory_path(dt)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def write_daily_memory(self, content: str, dt: Optional[date] = None) -> None:
        """写入每日记忆"""
        path = self.get_daily_memory_path(dt)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def append_daily_memory(self, content: str, dt: Optional[date] = None) -> None:
        """追加每日记忆"""
        path = self.get_daily_memory_path(dt)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 如果文件不存在，创建带日期标题的文件
        if not path.exists():
            dt = dt or date.today()
            header = f"# {dt.isoformat()} 记忆日志\n\n"
            path.write_text(header, encoding="utf-8")

        with open(path, "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%H:%M")
            f.write(f"\n## {timestamp}\n{content}\n")

    def list_daily_memories(self, limit: int = 30) -> List[str]:
        """列出最近的每日记忆文件"""
        if not self.memory_dir.exists():
            return []

        files = sorted(self.memory_dir.glob("*.md"), reverse=True)
        return [f.stem for f in files[:limit]]

    # ============================================================
    # 上下文构建
    # ============================================================

    def get_workspace_context(
        self,
        include_files: Optional[List[str]] = None,
        include_daily_memory: bool = False,
        daily_memory_days: int = 3
    ) -> str:
        """
        获取工作区上下文

        将工作区文件内容组合为上下文字符串。

        Args:
            include_files: 要包含的文件列表，None 则包含所有核心文件
            include_daily_memory: 是否包含每日记忆
            daily_memory_days: 包含最近几天的记忆

        Returns:
            组合后的上下文字符串
        """
        if include_files is None:
            include_files = ["SOUL.md", "USER.md", "IDENTITY.md", "MEMORY.md"]

        parts = []

        for filename in include_files:
            content = self.read(filename)
            if content:
                parts.append(f"<!-- {filename} -->\n{content}")

        # 包含每日记忆
        if include_daily_memory:
            memories = self.list_daily_memories(limit=daily_memory_days)
            for date_str in memories:
                dt = date.fromisoformat(date_str)
                content = self.read_daily_memory(dt)
                if content:
                    parts.append(f"<!-- memory/{date_str}.md -->\n{content}")

        return "\n\n---\n\n".join(parts)

    def get_boot_checklist(self) -> Optional[str]:
        """获取启动检查清单"""
        return self.read("BOOT.md")

    def get_heartbeat_checklist(self) -> Optional[str]:
        """获取心跳检查清单"""
        return self.read("HEARTBEAT.md")

    def get_bootstrap(self) -> Optional[str]:
        """获取首次运行仪式"""
        return self.read("BOOTSTRAP.md")

    def is_first_run(self) -> bool:
        """检查是否首次运行"""
        marker = self.workspace_dir / ".initialized"
        return not marker.exists()

    def mark_initialized(self) -> None:
        """标记已初始化"""
        marker = self.workspace_dir / ".initialized"
        marker.touch()

    # ============================================================
    # 便捷属性
    # ============================================================

    @property
    def soul(self) -> Optional[str]:
        """获取 SOUL.md 内容"""
        return self.read("SOUL.md")

    @property
    def user(self) -> Optional[str]:
        """获取 USER.md 内容"""
        return self.read("USER.md")

    @property
    def identity(self) -> Optional[str]:
        """获取 IDENTITY.md 内容"""
        return self.read("IDENTITY.md")

    @property
    def memory(self) -> Optional[str]:
        """获取 MEMORY.md 内容"""
        return self.read("MEMORY.md")

    @property
    def tools(self) -> Optional[str]:
        """获取 TOOLS.md 内容"""
        return self.read("TOOLS.md")

    @property
    def agents(self) -> Optional[str]:
        """获取 AGENTS.md 内容"""
        return self.read("AGENTS.md")
