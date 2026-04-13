"""
技能注册表 - 管理已加载的技能
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime

from .models import Skill, SkillMatch, SkillTrigger
from .loader import SkillLoader
from ..core.logger import LoggerMixin

logger = logging.getLogger(__name__)


class SkillRegistry(LoggerMixin):
    """
    技能注册表

    管理所有已加载的技能，支持：
    - 从目录批量加载技能
    - 按名称/标签查询技能
    - 根据用户输入匹配技能

    使用示例:
        registry = SkillRegistry()
        registry.load_directory("/path/to/skills")
        matches = registry.match("查询天气")
    """

    def __init__(self, loader: Optional[SkillLoader] = None):
        """
        初始化注册表

        Args:
            loader: 技能加载器，None 则创建默认加载器
        """
        self._loader = loader or SkillLoader()
        self._skills: Dict[str, Skill] = {}
        self._tags_index: Dict[str, Set[str]] = {}  # tag -> skill names

    def register(self, skill: Skill) -> bool:
        """
        注册技能

        Args:
            skill: 技能对象

        Returns:
            是否注册成功
        """
        if not skill.name:
            self.logger.error("技能缺少名称，无法注册")
            return False

        if skill.name in self._skills:
            self.logger.warning(f"技能 '{skill.name}' 已存在，将被覆盖")

        self._skills[skill.name] = skill

        # 更新标签索引
        for tag in skill.tags:
            if tag not in self._tags_index:
                self._tags_index[tag] = set()
            self._tags_index[tag].add(skill.name)

        self.logger.debug(f"注册技能: {skill.name}")
        return True

    def unregister(self, name: str) -> bool:
        """
        注销技能

        Args:
            name: 技能名称

        Returns:
            是否注销成功
        """
        if name not in self._skills:
            return False

        skill = self._skills.pop(name)

        # 更新标签索引
        for tag in skill.tags:
            if tag in self._tags_index:
                self._tags_index[tag].discard(name)
                if not self._tags_index[tag]:
                    del self._tags_index[tag]

        self.logger.debug(f"注销技能: {name}")
        return True

    def get(self, name: str) -> Optional[Skill]:
        """获取技能"""
        return self._skills.get(name)

    def list_skills(
        self,
        tag: Optional[str] = None,
        enabled_only: bool = True
    ) -> List[Skill]:
        """
        列出技能

        Args:
            tag: 按标签过滤
            enabled_only: 只返回启用的技能

        Returns:
            技能列表
        """
        skills = list(self._skills.values())

        if enabled_only:
            skills = [s for s in skills if s.enabled]

        if tag:
            tag_skills = self._tags_index.get(tag, set())
            skills = [s for s in skills if s.name in tag_skills]

        return skills

    def load_file(self, path: str, use_cache: bool = True) -> Optional[Skill]:
        """
        加载单个技能文件

        Args:
            path: SKILL.md 文件路径
            use_cache: 是否使用缓存

        Returns:
            加载的技能，失败返回 None
        """
        skill = self._loader.load(path, use_cache=use_cache)
        if skill:
            self.register(skill)
        return skill

    def load_directory(
        self,
        directory: str,
        recursive: bool = True,
        use_cache: bool = True
    ) -> int:
        """
        从目录加载技能

        Args:
            directory: 技能目录
            recursive: 是否递归搜索
            use_cache: 是否使用缓存

        Returns:
            成功加载的技能数量
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            self.logger.error(f"目录不存在: {directory}")
            return 0

        # 支持两种格式: SKILL.md 和 *.SKILL.md
        if recursive:
            skill_files = list(dir_path.glob("**/SKILL.md")) + list(dir_path.glob("**/*.SKILL.md"))
        else:
            skill_files = list(dir_path.glob("SKILL.md")) + list(dir_path.glob("*.SKILL.md"))

        loaded = 0
        for skill_file in skill_files:
            skill = self.load_file(str(skill_file), use_cache=use_cache)
            if skill:
                loaded += 1

        self.logger.info(f"从 {directory} 加载了 {loaded} 个技能")
        return loaded

    def match(self, text: str, limit: int = 5) -> List[SkillMatch]:
        """
        匹配技能

        根据用户输入匹配合适的技能。

        Args:
            text: 用户输入
            limit: 最大返回数量

        Returns:
            匹配结果列表，按分数排序
        """
        matches = []

        for skill in self._skills.values():
            if not skill.enabled:
                continue

            trigger = skill.get_matching_trigger(text)
            if trigger:
                # 计算匹配分数
                score = self._calculate_score(text, trigger)
                matches.append(SkillMatch(
                    skill=skill,
                    trigger=trigger,
                    score=score
                ))

        # 按分数排序
        matches.sort(key=lambda m: m.score, reverse=True)

        return matches[:limit]

    def _calculate_score(self, text: str, trigger: SkillTrigger) -> float:
        """
        计算匹配分数

        Args:
            text: 用户输入
            trigger: 匹配的触发器

        Returns:
            分数 (0.0 - 1.0)
        """
        from .models import TriggerType

        # 基础分数
        base_score = 0.5

        # 根据触发器类型调整
        if trigger.type == TriggerType.EXACT:
            base_score = 1.0
        elif trigger.type == TriggerType.PREFIX:
            base_score = 0.9
        elif trigger.type == TriggerType.CONTAINS:
            # 根据匹配长度比例调整
            ratio = len(trigger.pattern) / len(text) if text else 0
            base_score = 0.5 + 0.3 * ratio
        elif trigger.type == TriggerType.REGEX:
            base_score = 0.7

        return min(1.0, base_score)

    def reload(self, name: str) -> bool:
        """
        重新加载技能

        Args:
            name: 技能名称

        Returns:
            是否重新加载成功
        """
        skill = self._skills.get(name)
        if not skill or not skill.source_path:
            return False

        # 清除缓存并重新加载
        self._loader.clear_cache()
        new_skill = self._loader.load(skill.source_path, use_cache=False)

        if new_skill:
            self.register(new_skill)
            return True

        return False

    def reload_all(self) -> int:
        """
        重新加载所有技能

        Returns:
            成功重新加载的数量
        """
        self._loader.clear_cache()
        reloaded = 0

        for name in list(self._skills.keys()):
            if self.reload(name):
                reloaded += 1

        return reloaded

    def enable(self, name: str) -> bool:
        """启用技能"""
        skill = self._skills.get(name)
        if skill:
            skill.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """禁用技能"""
        skill = self._skills.get(name)
        if skill:
            skill.enabled = False
            return True
        return False

    def clear(self) -> None:
        """清空所有技能"""
        self._skills.clear()
        self._tags_index.clear()
        self._loader.clear_cache()

    @property
    def count(self) -> int:
        """技能数量"""
        return len(self._skills)

    def get_tags(self) -> List[str]:
        """获取所有标签"""
        return list(self._tags_index.keys())
