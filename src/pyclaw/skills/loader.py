"""
技能加载器 - 解析 SKILL.md 文件

SKILL.md 格式示例:
```
---
name: weather
description: 获取天气信息
version: 1.0.0
triggers:
  - pattern: "天气"
    type: contains
  - pattern: "weather"
    type: contains
model: qwen
tags:
  - utility
  - weather
---

# 系统提示词

你是一个天气查询助手，帮助用户获取天气信息。

# 用户提示词模板

用户想要查询天气: {user_input}

请提供准确的天气信息。
```
"""

import re
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from functools import lru_cache

from .models import Skill, SkillTrigger, TriggerType
from ..core.logger import LoggerMixin

logger = logging.getLogger(__name__)


class SkillLoader(LoggerMixin):
    """
    技能加载器

    解析 SKILL.md 文件，支持 LRU 缓存。

    使用示例:
        loader = SkillLoader()
        skill = loader.load("/path/to/SKILL.md")
    """

    # Front-matter 分隔符
    FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)

    # 内容区块标题
    SYSTEM_PROMPT_HEADERS = ["# 系统提示词", "# System Prompt", "## System"]
    USER_PROMPT_HEADERS = ["# 用户提示词模板", "# User Prompt", "## User"]

    def __init__(self, cache_size: int = 100):
        """
        初始化加载器

        Args:
            cache_size: LRU 缓存大小
        """
        self._cache_size = cache_size
        # 使用装饰器的缓存
        self._load_cached = lru_cache(maxsize=cache_size)(self._load_impl)

    def load(self, path: str, use_cache: bool = True) -> Optional[Skill]:
        """
        加载技能文件

        Args:
            path: SKILL.md 文件路径
            use_cache: 是否使用缓存

        Returns:
            Skill 对象，加载失败返回 None
        """
        path = str(Path(path).resolve())

        if use_cache:
            # 检查文件修改时间
            try:
                mtime = Path(path).stat().st_mtime
                return self._load_cached(path, mtime)
            except FileNotFoundError:
                self.logger.error(f"技能文件不存在: {path}")
                return None
        else:
            return self._load_impl(path, 0)

    def _load_impl(self, path: str, mtime: float) -> Optional[Skill]:
        """实际加载实现"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            return self.parse(content, source_path=path)

        except Exception as e:
            self.logger.error(f"加载技能文件失败 [{path}]: {e}")
            return None

    def parse(self, content: str, source_path: Optional[str] = None) -> Optional[Skill]:
        """
        解析 SKILL.md 内容

        Args:
            content: 文件内容
            source_path: 源文件路径

        Returns:
            Skill 对象
        """
        # 1. 提取 front-matter
        frontmatter, body = self._extract_frontmatter(content)
        if not frontmatter:
            self.logger.warning("技能文件缺少 front-matter")
            return None

        # 2. 解析 YAML
        try:
            meta = yaml.safe_load(frontmatter)
            if not isinstance(meta, dict):
                self.logger.error("front-matter 格式错误")
                return None
        except yaml.YAMLError as e:
            self.logger.error(f"YAML 解析错误: {e}")
            return None

        # 3. 提取必要字段
        name = meta.get("name")
        if not name:
            self.logger.error("技能缺少 name 字段")
            return None

        # 4. 解析触发器
        triggers = self._parse_triggers(meta.get("triggers", []))

        # 5. 提取提示词
        system_prompt = self._extract_section(body, self.SYSTEM_PROMPT_HEADERS)
        user_prompt = self._extract_section(body, self.USER_PROMPT_HEADERS)

        # 如果没有明确的区块，使用整个 body 作为系统提示词
        if not system_prompt and body.strip():
            system_prompt = body.strip()

        # 6. 构建 Skill 对象
        skill = Skill(
            name=name,
            description=meta.get("description", ""),
            version=meta.get("version", "1.0.0"),
            author=meta.get("author", ""),
            triggers=triggers,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt,
            tools=meta.get("tools", []),
            model_preference=meta.get("model"),
            max_tokens=meta.get("max_tokens"),
            temperature=meta.get("temperature"),
            tags=meta.get("tags", []),
            enabled=meta.get("enabled", True),
            source_path=source_path,
            loaded_at=datetime.now()
        )

        self.logger.debug(f"解析技能: {name}, 触发器数: {len(triggers)}")
        return skill

    def _extract_frontmatter(self, content: str) -> tuple:
        """
        提取 front-matter 和正文

        Returns:
            (frontmatter, body)
        """
        match = self.FRONTMATTER_PATTERN.match(content)
        if match:
            frontmatter = match.group(1)
            body = content[match.end():]
            return frontmatter, body
        return None, content

    def _parse_triggers(self, triggers_data: List) -> List[SkillTrigger]:
        """解析触发器配置"""
        triggers = []

        for item in triggers_data:
            if isinstance(item, str):
                # 简单字符串格式
                triggers.append(SkillTrigger(pattern=item))
            elif isinstance(item, dict):
                # 完整配置格式
                pattern = item.get("pattern", "")
                if not pattern:
                    continue

                trigger_type = TriggerType.EXACT
                type_str = item.get("type", "exact").lower()
                if type_str == "prefix":
                    trigger_type = TriggerType.PREFIX
                elif type_str == "contains":
                    trigger_type = TriggerType.CONTAINS
                elif type_str == "regex":
                    trigger_type = TriggerType.REGEX

                triggers.append(SkillTrigger(
                    pattern=pattern,
                    type=trigger_type,
                    case_sensitive=item.get("case_sensitive", False)
                ))

        return triggers

    def _extract_section(self, body: str, headers: List[str]) -> str:
        """
        从正文中提取指定区块

        Args:
            body: 正文内容
            headers: 可能的标题列表

        Returns:
            区块内容
        """
        lines = body.split("\n")
        in_section = False
        section_lines = []
        section_level = 0

        for line in lines:
            # 检查是否是目标区块的开始
            if not in_section:
                for header in headers:
                    if line.strip().startswith(header):
                        in_section = True
                        section_level = len(header) - len(header.lstrip("#"))
                        break
                continue

            # 检查是否遇到同级或更高级的标题（区块结束）
            if line.strip().startswith("#"):
                current_level = len(line) - len(line.lstrip("#"))
                if current_level <= section_level:
                    break

            section_lines.append(line)

        return "\n".join(section_lines).strip()

    def clear_cache(self) -> None:
        """清空缓存"""
        self._load_cached.cache_clear()
