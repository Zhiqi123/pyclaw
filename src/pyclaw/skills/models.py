"""
技能数据模型
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime


class TriggerType(Enum):
    """触发器类型"""
    EXACT = "exact"      # 精确匹配
    PREFIX = "prefix"    # 前缀匹配
    CONTAINS = "contains"  # 包含匹配
    REGEX = "regex"      # 正则匹配


@dataclass
class SkillTrigger:
    """技能触发器"""
    pattern: str
    type: TriggerType = TriggerType.EXACT
    case_sensitive: bool = False

    def matches(self, text: str) -> bool:
        """检查文本是否匹配触发器"""
        import re

        check_text = text if self.case_sensitive else text.lower()
        check_pattern = self.pattern if self.case_sensitive else self.pattern.lower()

        if self.type == TriggerType.EXACT:
            return check_text == check_pattern
        elif self.type == TriggerType.PREFIX:
            return check_text.startswith(check_pattern)
        elif self.type == TriggerType.CONTAINS:
            return check_pattern in check_text
        elif self.type == TriggerType.REGEX:
            try:
                flags = 0 if self.case_sensitive else re.IGNORECASE
                return bool(re.search(self.pattern, text, flags))
            except re.error:
                return False

        return False


@dataclass
class Skill:
    """
    技能定义

    技能通过 SKILL.md 文件定义，包含：
    - 元数据（名称、描述、触发器等）
    - 提示词模板
    - 可选的工具定义
    """
    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""

    # 触发器列表
    triggers: List[SkillTrigger] = field(default_factory=list)

    # 提示词
    system_prompt: str = ""
    user_prompt_template: str = ""

    # 工具定义（可选）
    tools: List[Dict[str, Any]] = field(default_factory=list)

    # 配置
    model_preference: Optional[str] = None  # 首选模型
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None

    # 元数据
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    source_path: Optional[str] = None
    loaded_at: Optional[datetime] = None

    def matches(self, text: str) -> bool:
        """检查文本是否匹配任一触发器"""
        return any(trigger.matches(text) for trigger in self.triggers)

    def get_matching_trigger(self, text: str) -> Optional[SkillTrigger]:
        """获取匹配的触发器"""
        for trigger in self.triggers:
            if trigger.matches(text):
                return trigger
        return None

    def render_user_prompt(self, user_input: str, **kwargs) -> str:
        """渲染用户提示词模板"""
        if not self.user_prompt_template:
            return user_input

        try:
            return self.user_prompt_template.format(
                user_input=user_input,
                **kwargs
            )
        except KeyError:
            return self.user_prompt_template.replace("{user_input}", user_input)


@dataclass
class SkillMatch:
    """技能匹配结果"""
    skill: Skill
    trigger: SkillTrigger
    score: float = 1.0  # 匹配分数（用于排序）
    extracted_args: Dict[str, str] = field(default_factory=dict)
