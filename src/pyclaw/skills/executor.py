"""
技能执行器 - 执行匹配的技能

包含依赖管理和安全检查功能。
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

from .models import Skill, SkillMatch
from .registry import SkillRegistry
from .dependency import (
    DependencyManager,
    DependencyStatus,
    RiskLevel,
    get_dependency_manager,
)
from ..core.logger import LoggerMixin

logger = logging.getLogger(__name__)


class SkillState(Enum):
    """技能运行状态"""
    IDLE = "idle"                   # 空闲
    CHECKING_DEPS = "checking_deps"  # 检查依赖中
    WAITING_CONFIRM = "waiting_confirm"  # 等待用户确认
    INSTALLING = "installing"        # 安装依赖中
    RUNNING = "running"              # 运行中
    COMPLETED = "completed"          # 已完成
    FAILED = "failed"                # 失败


@dataclass
class SkillExecutionResult:
    """技能执行结果"""
    success: bool
    skill_name: str
    system_prompt: str = ""
    user_prompt: str = ""
    model_preference: Optional[str] = None
    tools: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class SkillExecutor(LoggerMixin):
    """
    技能执行器

    负责：
    - 匹配用户输入到合适的技能
    - 准备技能执行所需的提示词和配置
    - 支持技能链式调用

    使用示例:
        executor = SkillExecutor(registry)
        result = executor.execute("查询北京天气", context={"user_id": "123"})
        if result.success:
            # 使用 result.system_prompt 和 result.user_prompt 调用 LLM
            pass
    """

    def __init__(
        self,
        registry: SkillRegistry,
        default_system_prompt: str = ""
    ):
        """
        初始化执行器

        Args:
            registry: 技能注册表
            default_system_prompt: 默认系统提示词（无技能匹配时使用）
        """
        self._registry = registry
        self._default_system_prompt = default_system_prompt

        # 前置/后置处理器
        self._pre_processors: List[Callable] = []
        self._post_processors: List[Callable] = []

    def execute(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
        force_skill: Optional[str] = None
    ) -> SkillExecutionResult:
        """
        执行技能

        Args:
            user_input: 用户输入
            context: 上下文信息（可用于模板渲染）
            force_skill: 强制使用指定技能

        Returns:
            执行结果
        """
        context = context or {}

        # 前置处理
        processed_input = self._run_pre_processors(user_input, context)

        # 获取技能
        skill = None
        match = None

        if force_skill:
            skill = self._registry.get(force_skill)
            if not skill:
                return SkillExecutionResult(
                    success=False,
                    skill_name=force_skill,
                    error=f"技能 '{force_skill}' 不存在"
                )
        else:
            # 匹配技能
            matches = self._registry.match(processed_input, limit=1)
            if matches:
                match = matches[0]
                skill = match.skill

        # 无匹配技能，使用默认配置
        if not skill:
            return SkillExecutionResult(
                success=True,
                skill_name="",
                system_prompt=self._default_system_prompt,
                user_prompt=processed_input,
                metadata={"matched": False}
            )

        # 准备提示词
        try:
            system_prompt = skill.system_prompt or self._default_system_prompt
            user_prompt = skill.render_user_prompt(processed_input, **context)

            result = SkillExecutionResult(
                success=True,
                skill_name=skill.name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_preference=skill.model_preference,
                tools=skill.tools,
                metadata={
                    "matched": True,
                    "skill_version": skill.version,
                    "trigger_pattern": match.trigger.pattern if match else None,
                    "match_score": match.score if match else 1.0
                }
            )

            # 后置处理
            result = self._run_post_processors(result, context)

            self.logger.debug(f"执行技能: {skill.name}, 匹配分数: {match.score if match else 1.0}")
            return result

        except Exception as e:
            self.logger.error(f"技能执行失败 [{skill.name}]: {e}")
            return SkillExecutionResult(
                success=False,
                skill_name=skill.name,
                error=str(e)
            )

    def match_skill(self, user_input: str) -> Optional[SkillMatch]:
        """
        仅匹配技能，不执行

        Args:
            user_input: 用户输入

        Returns:
            匹配结果，无匹配返回 None
        """
        matches = self._registry.match(user_input, limit=1)
        return matches[0] if matches else None

    def get_all_matches(self, user_input: str, limit: int = 5) -> List[SkillMatch]:
        """
        获取所有匹配的技能

        Args:
            user_input: 用户输入
            limit: 最大返回数量

        Returns:
            匹配结果列表
        """
        return self._registry.match(user_input, limit=limit)

    def add_pre_processor(self, processor: Callable[[str, Dict], str]) -> None:
        """
        添加前置处理器

        处理器签名: (user_input: str, context: dict) -> str

        Args:
            processor: 处理器函数
        """
        self._pre_processors.append(processor)

    def add_post_processor(
        self,
        processor: Callable[[SkillExecutionResult, Dict], SkillExecutionResult]
    ) -> None:
        """
        添加后置处理器

        处理器签名: (result: SkillExecutionResult, context: dict) -> SkillExecutionResult

        Args:
            processor: 处理器函数
        """
        self._post_processors.append(processor)

    def _run_pre_processors(self, user_input: str, context: Dict) -> str:
        """运行前置处理器"""
        result = user_input
        for processor in self._pre_processors:
            try:
                result = processor(result, context)
            except Exception as e:
                self.logger.warning(f"前置处理器执行失败: {e}")
        return result

    def _run_post_processors(
        self,
        result: SkillExecutionResult,
        context: Dict
    ) -> SkillExecutionResult:
        """运行后置处理器"""
        for processor in self._post_processors:
            try:
                result = processor(result, context)
            except Exception as e:
                self.logger.warning(f"后置处理器执行失败: {e}")
        return result

    @property
    def registry(self) -> SkillRegistry:
        """获取技能注册表"""
        return self._registry

    @property
    def default_system_prompt(self) -> str:
        """获取默认系统提示词"""
        return self._default_system_prompt

    @default_system_prompt.setter
    def default_system_prompt(self, value: str) -> None:
        """设置默认系统提示词"""
        self._default_system_prompt = value


class SafeSkillExecutor(SkillExecutor):
    """
    安全技能执行器

    在 SkillExecutor 基础上增加：
    - 依赖检查
    - 安装确认
    - 风险评估
    - 状态跟踪

    使用示例:
        executor = SafeSkillExecutor(registry)

        # 设置确认回调
        executor.set_confirm_callback(lambda msg: input(msg + " (y/n): ").lower() == 'y')

        # 执行时自动检查依赖
        result = executor.execute_safe("github pr list")
    """

    def __init__(
        self,
        registry: SkillRegistry,
        default_system_prompt: str = "",
        auto_install: bool = False,
        max_risk_level: RiskLevel = RiskLevel.MEDIUM
    ):
        """
        初始化安全执行器

        Args:
            registry: 技能注册表
            default_system_prompt: 默认系统提示词
            auto_install: 是否自动安装依赖（不推荐）
            max_risk_level: 允许的最大风险等级
        """
        super().__init__(registry, default_system_prompt)

        self._dep_manager = get_dependency_manager()
        self._auto_install = auto_install
        self._max_risk_level = max_risk_level
        self._confirm_callback: Optional[Callable[[str], bool]] = None

        # 状态跟踪
        self._current_skill: Optional[str] = None
        self._current_state = SkillState.IDLE

    def set_confirm_callback(self, callback: Callable[[str], bool]) -> None:
        """
        设置确认回调

        Args:
            callback: 确认回调函数，接收提示信息，返回 True 表示确认
        """
        self._confirm_callback = callback
        self._dep_manager.set_confirm_callback(callback)

    def check_dependencies(self, skill_name: str) -> Dict[str, Any]:
        """
        检查技能依赖

        Args:
            skill_name: 技能名称

        Returns:
            依赖信息字典
        """
        self._current_state = SkillState.CHECKING_DEPS
        info = self._dep_manager.get_skill_info(skill_name)

        if not info:
            return {
                "skill_name": skill_name,
                "has_dependencies": False,
                "all_installed": True,
                "dependencies": []
            }

        return info

    def execute_safe(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
        force_skill: Optional[str] = None,
        skip_dep_check: bool = False
    ) -> SkillExecutionResult:
        """
        安全执行技能

        流程:
        1. 匹配技能
        2. 检查依赖
        3. 如有缺失依赖，请求确认安装
        4. 安装依赖
        5. 执行技能

        Args:
            user_input: 用户输入
            context: 上下文
            force_skill: 强制技能
            skip_dep_check: 跳过依赖检查

        Returns:
            执行结果
        """
        context = context or {}

        # 1. 匹配技能
        skill = None
        match = None

        if force_skill:
            skill = self._registry.get(force_skill)
            if not skill:
                return SkillExecutionResult(
                    success=False,
                    skill_name=force_skill,
                    error=f"技能 '{force_skill}' 不存在"
                )
        else:
            matches = self._registry.match(user_input, limit=1)
            if matches:
                match = matches[0]
                skill = match.skill

        # 无匹配，走默认流程
        if not skill:
            return self.execute(user_input, context, force_skill)

        self._current_skill = skill.name

        # 2. 检查依赖
        if not skip_dep_check:
            dep_info = self.check_dependencies(skill.name)

            if dep_info.get("has_dependencies", False):
                # 检查风险等级
                skill_risk = RiskLevel[dep_info.get("risk_level", "low").upper()]
                if self._compare_risk(skill_risk, self._max_risk_level) > 0:
                    self._current_state = SkillState.FAILED
                    return SkillExecutionResult(
                        success=False,
                        skill_name=skill.name,
                        error=f"技能风险等级 ({skill_risk.value}) 超过允许的最大等级 ({self._max_risk_level.value})",
                        metadata={"risk_level": skill_risk.value}
                    )

                # 检查是否有缺失依赖
                if not dep_info.get("all_installed", True):
                    self._current_state = SkillState.WAITING_CONFIRM

                    # 需要安装
                    if not self._auto_install:
                        # 请求确认
                        if self._confirm_callback:
                            prompt = self._dep_manager.format_install_prompt(skill.name)
                            if not self._confirm_callback(prompt):
                                self._current_state = SkillState.FAILED
                                return SkillExecutionResult(
                                    success=False,
                                    skill_name=skill.name,
                                    error="用户取消依赖安装",
                                    metadata={"cancelled_by_user": True}
                                )

                    # 3. 安装依赖
                    self._current_state = SkillState.INSTALLING
                    install_result = self._dep_manager.install_skill_dependencies(
                        skill.name,
                        confirm=False  # 已经确认过
                    )

                    if not install_result["success"]:
                        self._current_state = SkillState.FAILED
                        return SkillExecutionResult(
                            success=False,
                            skill_name=skill.name,
                            error=f"依赖安装失败: {install_result.get('failed', [])}",
                            metadata={"install_result": install_result}
                        )

        # 4. 执行技能
        self._current_state = SkillState.RUNNING
        result = self.execute(user_input, context, force_skill)

        self._current_state = SkillState.COMPLETED if result.success else SkillState.FAILED
        return result

    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "state": self._current_state.value,
            "current_skill": self._current_skill
        }

    def _compare_risk(self, a: RiskLevel, b: RiskLevel) -> int:
        """比较风险等级，返回 -1/0/1"""
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        return (order.index(a) > order.index(b)) - (order.index(a) < order.index(b))

    def list_available_skills(self) -> List[Dict[str, Any]]:
        """
        列出所有可用技能及其依赖状态

        Returns:
            技能信息列表
        """
        skills = self._registry.list_skills(enabled_only=True)
        result = []

        for skill in skills:
            dep_info = self._dep_manager.get_skill_info(skill.name)

            result.append({
                "name": skill.name,
                "description": skill.description,
                "triggers": [t.pattern for t in skill.triggers[:3]],  # 前3个触发词
                "dependencies_ready": dep_info.get("all_installed", True) if dep_info else True,
                "risk_level": dep_info.get("risk_level", "low") if dep_info else "low"
            })

        return result
