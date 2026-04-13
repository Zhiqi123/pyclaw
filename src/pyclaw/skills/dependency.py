"""
技能依赖管理器 - 安全的依赖检查与安装

解决的问题：
1. 检测技能所需的第三方工具是否已安装
2. 在安装前向用户展示依赖信息
3. 提供安装确认机制
4. 跟踪依赖安装状态
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class DependencyType(Enum):
    """依赖类型"""
    BINARY = "binary"       # 二进制程序（如 gh, jq）
    BREW = "brew"           # Homebrew 包
    PIP = "pip"             # Python 包
    NPM = "npm"             # Node.js 包
    ENV = "env"             # 环境变量
    PERMISSION = "permission"  # 系统权限


class DependencyStatus(Enum):
    """依赖状态"""
    INSTALLED = "installed"
    MISSING = "missing"
    UNKNOWN = "unknown"


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"             # 只读操作、无需安装
    MEDIUM = "medium"       # 需要安装工具但来源可信
    HIGH = "high"           # 涉及敏感操作或不明来源
    CRITICAL = "critical"   # 系统级权限、网络访问


@dataclass
class Dependency:
    """依赖定义"""
    name: str                           # 依赖名称
    type: DependencyType               # 依赖类型
    check_command: Optional[str] = None  # 检查命令（如 "gh --version"）
    install_command: Optional[str] = None  # 安装命令
    description: str = ""               # 描述
    homepage: Optional[str] = None      # 官方网站
    risk_level: RiskLevel = RiskLevel.MEDIUM
    required: bool = True               # 是否必需

    def __post_init__(self):
        # 自动生成检查命令
        if self.check_command is None:
            if self.type == DependencyType.BINARY:
                self.check_command = f"which {self.name}"
            elif self.type == DependencyType.BREW:
                self.check_command = f"brew list {self.name}"
            elif self.type == DependencyType.PIP:
                self.check_command = f"pip show {self.name}"
            elif self.type == DependencyType.NPM:
                self.check_command = f"npm list -g {self.name}"
            elif self.type == DependencyType.ENV:
                self.check_command = f"echo ${self.name}"

        # 自动生成安装命令
        if self.install_command is None:
            if self.type == DependencyType.BREW:
                self.install_command = f"brew install {self.name}"
            elif self.type == DependencyType.PIP:
                self.install_command = f"pip install {self.name}"
            elif self.type == DependencyType.NPM:
                self.install_command = f"npm install -g {self.name}"


@dataclass
class DependencyCheckResult:
    """依赖检查结果"""
    dependency: Dependency
    status: DependencyStatus
    version: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SkillDependencies:
    """技能依赖配置"""
    skill_name: str
    dependencies: List[Dependency] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False  # 是否需要用户确认
    sandbox_required: bool = False       # 是否需要沙箱

    @property
    def all_installed(self) -> bool:
        """所有必需依赖是否已安装"""
        # 需要先调用 check_all()
        return not any(
            d.required for d in self.dependencies
            if getattr(d, '_status', DependencyStatus.UNKNOWN) == DependencyStatus.MISSING
        )


class DependencyManager:
    """
    依赖管理器

    负责检查、安装和管理技能依赖。

    使用示例:
        manager = DependencyManager()

        # 检查技能依赖
        results = manager.check_skill("github")

        # 查看缺失的依赖
        missing = manager.get_missing("github")

        # 安装缺失的依赖（需要确认）
        manager.install_missing("github", confirm_callback=user_confirm)
    """

    # 已知的可信依赖白名单
    TRUSTED_DEPENDENCIES: Dict[str, Dependency] = {
        # CLI 工具
        "gh": Dependency(
            name="gh",
            type=DependencyType.BREW,
            description="GitHub CLI",
            homepage="https://cli.github.com/",
            risk_level=RiskLevel.MEDIUM
        ),
        "jq": Dependency(
            name="jq",
            type=DependencyType.BREW,
            description="JSON 处理工具",
            homepage="https://stedolan.github.io/jq/",
            risk_level=RiskLevel.LOW
        ),
        "tmux": Dependency(
            name="tmux",
            type=DependencyType.BREW,
            description="终端复用器",
            homepage="https://github.com/tmux/tmux",
            risk_level=RiskLevel.LOW
        ),
        "ffmpeg": Dependency(
            name="ffmpeg",
            type=DependencyType.BREW,
            description="多媒体处理工具",
            homepage="https://ffmpeg.org/",
            risk_level=RiskLevel.LOW
        ),
        "yt-dlp": Dependency(
            name="yt-dlp",
            type=DependencyType.BREW,
            description="视频下载工具",
            homepage="https://github.com/yt-dlp/yt-dlp",
            risk_level=RiskLevel.MEDIUM
        ),
        "whisper": Dependency(
            name="openai-whisper",
            type=DependencyType.PIP,
            check_command="pip show openai-whisper",
            install_command="pip install openai-whisper",
            description="OpenAI 语音识别",
            homepage="https://github.com/openai/whisper",
            risk_level=RiskLevel.MEDIUM
        ),
        # 笔记工具
        "memo": Dependency(
            name="memo",
            type=DependencyType.BREW,
            check_command="which memo",
            install_command="brew install draftedus/tap/memo",
            description="Apple Notes CLI",
            homepage="https://github.com/draftedus/memo",
            risk_level=RiskLevel.MEDIUM
        ),
        "obsidian-cli": Dependency(
            name="obsidian-cli",
            type=DependencyType.NPM,
            check_command="which obsidian-cli",
            description="Obsidian CLI",
            risk_level=RiskLevel.MEDIUM
        ),
    }

    # 技能到依赖的映射
    SKILL_DEPENDENCIES: Dict[str, SkillDependencies] = {
        "github": SkillDependencies(
            skill_name="github",
            dependencies=[
                TRUSTED_DEPENDENCIES["gh"],
                TRUSTED_DEPENDENCIES["jq"],
            ],
            risk_level=RiskLevel.MEDIUM
        ),
        "tmux": SkillDependencies(
            skill_name="tmux",
            dependencies=[
                TRUSTED_DEPENDENCIES["tmux"],
            ],
            risk_level=RiskLevel.LOW
        ),
        "apple-notes": SkillDependencies(
            skill_name="apple-notes",
            dependencies=[
                TRUSTED_DEPENDENCIES["memo"],
            ],
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=True  # 涉及个人数据
        ),
        "openai-whisper": SkillDependencies(
            skill_name="openai-whisper",
            dependencies=[
                TRUSTED_DEPENDENCIES["whisper"],
                TRUSTED_DEPENDENCIES["ffmpeg"],
            ],
            risk_level=RiskLevel.MEDIUM
        ),
        "summarize": SkillDependencies(
            skill_name="summarize",
            dependencies=[
                TRUSTED_DEPENDENCIES["yt-dlp"],
            ],
            risk_level=RiskLevel.MEDIUM
        ),
    }

    def __init__(self):
        self._cache: Dict[str, DependencyCheckResult] = {}
        self._confirm_callback: Optional[Callable[[str], bool]] = None

    def set_confirm_callback(self, callback: Callable[[str], bool]) -> None:
        """设置确认回调函数"""
        self._confirm_callback = callback

    def check_dependency(self, dep: Dependency, use_cache: bool = True) -> DependencyCheckResult:
        """
        检查单个依赖

        Args:
            dep: 依赖定义
            use_cache: 是否使用缓存

        Returns:
            检查结果
        """
        cache_key = f"{dep.type.value}:{dep.name}"

        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        result = DependencyCheckResult(
            dependency=dep,
            status=DependencyStatus.UNKNOWN
        )

        try:
            if dep.type == DependencyType.BINARY:
                # 检查二进制是否存在
                path = shutil.which(dep.name)
                if path:
                    result.status = DependencyStatus.INSTALLED
                    # 尝试获取版本
                    try:
                        version_result = subprocess.run(
                            [dep.name, "--version"],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if version_result.returncode == 0:
                            result.version = version_result.stdout.strip().split("\n")[0]
                    except:
                        pass
                else:
                    result.status = DependencyStatus.MISSING

            elif dep.type == DependencyType.ENV:
                # 检查环境变量
                value = os.environ.get(dep.name)
                if value:
                    result.status = DependencyStatus.INSTALLED
                    result.version = f"(已设置，长度={len(value)})"
                else:
                    result.status = DependencyStatus.MISSING

            elif dep.check_command:
                # 运行检查命令
                check_result = subprocess.run(
                    dep.check_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if check_result.returncode == 0:
                    result.status = DependencyStatus.INSTALLED
                    result.version = check_result.stdout.strip().split("\n")[0][:50]
                else:
                    result.status = DependencyStatus.MISSING

        except subprocess.TimeoutExpired:
            result.status = DependencyStatus.UNKNOWN
            result.error = "检查超时"
        except Exception as e:
            result.status = DependencyStatus.UNKNOWN
            result.error = str(e)

        self._cache[cache_key] = result
        return result

    def check_skill(self, skill_name: str) -> List[DependencyCheckResult]:
        """
        检查技能的所有依赖

        Args:
            skill_name: 技能名称

        Returns:
            所有依赖的检查结果
        """
        skill_deps = self.SKILL_DEPENDENCIES.get(skill_name)
        if not skill_deps:
            return []

        results = []
        for dep in skill_deps.dependencies:
            result = self.check_dependency(dep)
            dep._status = result.status  # 缓存到依赖对象
            results.append(result)

        return results

    def get_missing(self, skill_name: str) -> List[Dependency]:
        """获取缺失的必需依赖"""
        results = self.check_skill(skill_name)
        return [
            r.dependency for r in results
            if r.status == DependencyStatus.MISSING and r.dependency.required
        ]

    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """
        获取技能依赖信息（用于显示给用户）

        Returns:
            包含依赖信息的字典
        """
        skill_deps = self.SKILL_DEPENDENCIES.get(skill_name)
        if not skill_deps:
            return None

        results = self.check_skill(skill_name)

        return {
            "skill_name": skill_name,
            "risk_level": skill_deps.risk_level.value,
            "requires_confirmation": skill_deps.requires_confirmation,
            "dependencies": [
                {
                    "name": r.dependency.name,
                    "type": r.dependency.type.value,
                    "description": r.dependency.description,
                    "homepage": r.dependency.homepage,
                    "status": r.status.value,
                    "version": r.version,
                    "required": r.dependency.required,
                    "install_command": r.dependency.install_command,
                }
                for r in results
            ],
            "all_installed": all(
                r.status == DependencyStatus.INSTALLED
                for r in results if r.dependency.required
            ),
            "missing_count": sum(
                1 for r in results
                if r.status == DependencyStatus.MISSING and r.dependency.required
            )
        }

    def format_install_prompt(self, skill_name: str) -> str:
        """
        格式化安装提示（给用户确认）

        Returns:
            格式化的提示字符串
        """
        info = self.get_skill_info(skill_name)
        if not info:
            return f"技能 '{skill_name}' 没有注册的依赖信息。"

        if info["all_installed"]:
            return f"技能 '{skill_name}' 的所有依赖已安装。"

        lines = [
            f"技能 '{skill_name}' 需要安装以下依赖：",
            f"风险等级: {info['risk_level'].upper()}",
            ""
        ]

        for dep in info["dependencies"]:
            if dep["status"] == "missing" and dep["required"]:
                lines.append(f"  • {dep['name']} - {dep['description']}")
                if dep["homepage"]:
                    lines.append(f"    官网: {dep['homepage']}")
                lines.append(f"    安装命令: {dep['install_command']}")
                lines.append("")

        lines.append("是否继续安装？")
        return "\n".join(lines)

    def install_dependency(
        self,
        dep: Dependency,
        confirm: bool = True
    ) -> Dict[str, Any]:
        """
        安装单个依赖

        Args:
            dep: 依赖定义
            confirm: 是否需要确认

        Returns:
            安装结果
        """
        if not dep.install_command:
            return {
                "success": False,
                "error": f"依赖 '{dep.name}' 没有安装命令"
            }

        # 确认
        if confirm and self._confirm_callback:
            prompt = f"即将执行: {dep.install_command}\n确认安装 {dep.name}？"
            if not self._confirm_callback(prompt):
                return {
                    "success": False,
                    "error": "用户取消安装"
                }

        # 检查依赖是否在白名单
        if dep.name not in self.TRUSTED_DEPENDENCIES:
            return {
                "success": False,
                "error": f"依赖 '{dep.name}' 不在信任列表中，请手动安装"
            }

        try:
            logger.info(f"安装依赖: {dep.install_command}")
            result = subprocess.run(
                dep.install_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300  # 5 分钟超时
            )

            if result.returncode == 0:
                # 清除缓存
                cache_key = f"{dep.type.value}:{dep.name}"
                self._cache.pop(cache_key, None)

                return {
                    "success": True,
                    "message": f"成功安装 {dep.name}",
                    "output": result.stdout
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr or f"安装失败，退出码: {result.returncode}"
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "安装超时"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def install_skill_dependencies(
        self,
        skill_name: str,
        confirm: bool = True
    ) -> Dict[str, Any]:
        """
        安装技能的所有缺失依赖

        Args:
            skill_name: 技能名称
            confirm: 是否需要确认

        Returns:
            安装结果
        """
        missing = self.get_missing(skill_name)

        if not missing:
            return {
                "success": True,
                "message": "所有依赖已安装",
                "installed": []
            }

        # 显示安装提示
        if confirm and self._confirm_callback:
            prompt = self.format_install_prompt(skill_name)
            if not self._confirm_callback(prompt):
                return {
                    "success": False,
                    "error": "用户取消安装",
                    "installed": []
                }

        installed = []
        failed = []

        for dep in missing:
            result = self.install_dependency(dep, confirm=False)  # 已经确认过
            if result["success"]:
                installed.append(dep.name)
            else:
                failed.append({
                    "name": dep.name,
                    "error": result["error"]
                })

        return {
            "success": len(failed) == 0,
            "installed": installed,
            "failed": failed,
            "message": f"安装完成: {len(installed)}/{len(missing)}"
        }

    def clear_cache(self) -> None:
        """清除检查缓存"""
        self._cache.clear()


# ============================================================================
# 便捷函数
# ============================================================================

_manager: Optional[DependencyManager] = None


def get_dependency_manager() -> DependencyManager:
    """获取全局依赖管理器实例"""
    global _manager
    if _manager is None:
        _manager = DependencyManager()
    return _manager


def check_skill_dependencies(skill_name: str) -> Dict[str, Any]:
    """检查技能依赖"""
    return get_dependency_manager().get_skill_info(skill_name)


def ensure_skill_dependencies(
    skill_name: str,
    confirm_callback: Optional[Callable[[str], bool]] = None
) -> Dict[str, Any]:
    """
    确保技能依赖已安装

    Args:
        skill_name: 技能名称
        confirm_callback: 确认回调（返回 True 继续安装）

    Returns:
        检查/安装结果
    """
    manager = get_dependency_manager()

    if confirm_callback:
        manager.set_confirm_callback(confirm_callback)

    info = manager.get_skill_info(skill_name)
    if not info:
        return {
            "success": True,
            "message": f"技能 '{skill_name}' 没有注册的依赖",
            "requires_install": False
        }

    if info["all_installed"]:
        return {
            "success": True,
            "message": "所有依赖已安装",
            "requires_install": False,
            "dependencies": info["dependencies"]
        }

    # 需要安装
    return {
        "success": False,
        "message": manager.format_install_prompt(skill_name),
        "requires_install": True,
        "missing_count": info["missing_count"],
        "dependencies": info["dependencies"]
    }
