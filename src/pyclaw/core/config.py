"""
配置系统 - 多层配置合并

支持: 默认配置 → 用户配置 → 环境变量
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar, Type
from dataclasses import dataclass, field, asdict
from copy import deepcopy
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================
# 配置数据类
# ============================================================

@dataclass
class LLMProviderConfig:
    """单个 LLM 提供商配置"""
    enabled: bool = False
    api_key: str = ""
    api_base: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 60


@dataclass
class LLMConfig:
    """LLM 配置"""
    default_provider: str = "deepseek"
    claude: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(
        api_base="https://api.anthropic.com",
        model="claude-sonnet-4-20250514"
    ))
    deepseek: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(
        enabled=True,
        api_base="https://api.deepseek.com",
        model="deepseek-chat"
    ))
    qwen: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus"
    ))
    doubao: LLMProviderConfig = field(default_factory=lambda: LLMProviderConfig(
        api_base="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-pro-32k"
    ))

    # 任务路由配置
    task_routing: Dict[str, str] = field(default_factory=lambda: {
        "complex_reasoning": "claude",
        "code_generation": "deepseek",
        "chinese_chat": "qwen",
        "default": "deepseek"
    })


@dataclass
class MemoryConfig:
    """记忆系统配置"""
    db_path: str = "~/.pyclaw/data/pyclaw.db"
    max_context_tokens: int = 8000
    max_history_messages: int = 50
    enable_summarization: bool = False
    # 数据保留配置
    retention_days: int = 30  # 详细记录保留天数
    auto_cleanup: bool = True  # 是否自动清理过期数据
    cleanup_on_startup: bool = True  # 启动时是否执行清理


@dataclass
class IMessageConfig:
    """iMessage 通道配置"""
    enabled: bool = False
    db_path: str = "~/Library/Messages/chat.db"
    poll_interval: float = 2.0
    allowed_senders: list = field(default_factory=list)
    my_ids: list = field(default_factory=list)  # 自己的 ID（电话号码/Apple ID），用于过滤自己发给自己的消息


@dataclass
class WeChatConfig:
    """微信通道配置"""
    enabled: bool = False
    watch_dir: str = "~/.pyclaw/wechat"
    poll_interval: float = 1.0
    auto_login: bool = False


@dataclass
class ChannelConfig:
    """通道配置"""
    imessage: IMessageConfig = field(default_factory=IMessageConfig)
    wechat: WeChatConfig = field(default_factory=WeChatConfig)


@dataclass
class HeartbeatConfig:
    """心跳调度配置"""
    enabled: bool = False
    active_hours_start: int = 8   # 活跃时间开始 (小时)
    active_hours_end: int = 22    # 活跃时间结束 (小时)
    tasks: list = field(default_factory=list)


@dataclass
class LogConfig:
    """日志配置"""
    level: str = "INFO"
    file_path: str = "~/.pyclaw/logs/pyclaw.log"
    max_size_mb: int = 10
    backup_count: int = 5
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class PyClawConfig:
    """PyClaw 主配置"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    channels: ChannelConfig = field(default_factory=ChannelConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    log: LogConfig = field(default_factory=LogConfig)

    # 技能目录
    skills_dir: str = "~/.pyclaw/skills"

    # 系统提示词
    system_prompt: str = """你是 PyClaw，一个智能个人助手。
你可以帮助用户完成各种任务，包括回答问题、执行操作、管理日程等。
请用简洁、友好的方式回复用户。"""


# ============================================================
# 配置管理器
# ============================================================

class Config:
    """
    配置管理器

    支持多层配置合并：默认配置 → 用户配置文件 → 环境变量

    使用示例:
        config = Config()
        config.load()

        # 访问配置
        print(config.llm.default_provider)
        print(config.memory.db_path)
    """

    _instance: Optional["Config"] = None
    DEFAULT_CONFIG_DIR = Path.home() / ".pyclaw"
    CONFIG_FILE_NAME = "config.yaml"

    def __new__(cls) -> "Config":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._config: PyClawConfig = PyClawConfig()
        self._config_path: Optional[Path] = None
        self._initialized = True

    @property
    def llm(self) -> LLMConfig:
        return self._config.llm

    @property
    def memory(self) -> MemoryConfig:
        return self._config.memory

    @property
    def channels(self) -> ChannelConfig:
        return self._config.channels

    @property
    def heartbeat(self) -> HeartbeatConfig:
        return self._config.heartbeat

    @property
    def log(self) -> LogConfig:
        return self._config.log

    @property
    def skills_dir(self) -> str:
        return self._expand_path(self._config.skills_dir)

    @property
    def system_prompt(self) -> str:
        return self._config.system_prompt

    def load(self, config_path: Optional[str] = None) -> "Config":
        """
        加载配置

        Args:
            config_path: 配置文件路径，None 则使用默认路径
        """
        # 1. 从默认配置开始
        self._config = PyClawConfig()

        # 2. 确定配置文件路径
        if config_path:
            self._config_path = Path(config_path).expanduser()
        else:
            self._config_path = self.DEFAULT_CONFIG_DIR / self.CONFIG_FILE_NAME

        # 3. 加载用户配置文件
        if self._config_path.exists():
            self._load_from_file(self._config_path)
            logger.info(f"已加载配置文件: {self._config_path}")
        else:
            logger.info("使用默认配置")

        # 4. 应用环境变量覆盖
        self._apply_env_overrides()

        # 5. 确保必要目录存在
        self._ensure_directories()

        return self

    def _load_from_file(self, path: Path) -> None:
        """从 YAML 文件加载配置"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._merge_config(data)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")

    def _merge_config(self, data: Dict[str, Any]) -> None:
        """合并配置数据"""
        if "llm" in data:
            self._merge_llm_config(data["llm"])
        # 支持 providers 作为 llm 的别名（兼容 config.example.yaml 格式）
        if "providers" in data:
            self._merge_providers_config(data["providers"])
        if "memory" in data:
            self._merge_dataclass(self._config.memory, data["memory"])
        if "channels" in data:
            self._merge_channels_config(data["channels"])
        if "heartbeat" in data or "scheduler" in data:
            self._merge_dataclass(self._config.heartbeat, data.get("heartbeat") or data.get("scheduler", {}))
        if "log" in data or "logging" in data:
            self._merge_dataclass(self._config.log, data.get("log") or data.get("logging", {}))
        if "skills_dir" in data:
            self._config.skills_dir = data["skills_dir"]
        if "system_prompt" in data:
            self._config.system_prompt = data["system_prompt"]

    def _merge_llm_config(self, data: Dict[str, Any]) -> None:
        """合并 LLM 配置"""
        if "default_provider" in data:
            self._config.llm.default_provider = data["default_provider"]
        if "task_routing" in data:
            self._config.llm.task_routing.update(data["task_routing"])

        # 合并各提供商配置
        for provider in ["claude", "deepseek", "qwen", "doubao"]:
            if provider in data:
                provider_config = getattr(self._config.llm, provider)
                self._merge_dataclass(provider_config, data[provider])
                # 如果有 api_key，自动启用
                if data[provider].get("api_key"):
                    provider_config.enabled = True

    def _merge_providers_config(self, data: Dict[str, Any]) -> None:
        """合并 providers 配置（兼容 config.example.yaml 格式）"""
        for provider in ["claude", "deepseek", "qwen", "doubao"]:
            if provider in data:
                provider_config = getattr(self._config.llm, provider)
                self._merge_dataclass(provider_config, data[provider])
                # 如果有 api_key，自动启用
                if data[provider].get("api_key"):
                    provider_config.enabled = True

    def _merge_channels_config(self, data: Dict[str, Any]) -> None:
        """合并 channels 配置"""
        if "imessage" in data:
            self._merge_dataclass(self._config.channels.imessage, data["imessage"])
        if "wechat" in data:
            self._merge_dataclass(self._config.channels.wechat, data["wechat"])

    def _merge_dataclass(self, obj: Any, data: Dict[str, Any]) -> None:
        """合并数据到 dataclass 对象"""
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)

    def _apply_env_overrides(self) -> None:
        """应用环境变量覆盖"""
        env_mappings = {
            # API Keys
            "PYCLAW_CLAUDE_API_KEY": ("llm", "claude", "api_key"),
            "PYCLAW_DEEPSEEK_API_KEY": ("llm", "deepseek", "api_key"),
            "PYCLAW_QWEN_API_KEY": ("llm", "qwen", "api_key"),
            "PYCLAW_DOUBAO_API_KEY": ("llm", "doubao", "api_key"),
            "ANTHROPIC_API_KEY": ("llm", "claude", "api_key"),
            "DEEPSEEK_API_KEY": ("llm", "deepseek", "api_key"),

            # 其他配置
            "PYCLAW_DEFAULT_PROVIDER": ("llm", "default_provider"),
            "PYCLAW_LOG_LEVEL": ("log", "level"),
        }

        for env_var, path in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                self._set_nested_value(path, value)
                logger.debug(f"环境变量覆盖: {env_var}")

    def _set_nested_value(self, path: tuple, value: Any) -> None:
        """设置嵌套属性值"""
        obj = self._config
        for key in path[:-1]:
            obj = getattr(obj, key)
        setattr(obj, path[-1], value)

    def _ensure_directories(self) -> None:
        """确保必要目录存在"""
        dirs = [
            self.DEFAULT_CONFIG_DIR,
            self.DEFAULT_CONFIG_DIR / "data",
            self.DEFAULT_CONFIG_DIR / "logs",
            self.DEFAULT_CONFIG_DIR / "skills",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def _expand_path(self, path: str) -> str:
        """展开路径中的 ~ 符号"""
        return str(Path(path).expanduser())

    def save(self, path: Optional[str] = None) -> None:
        """保存配置到文件"""
        save_path = Path(path).expanduser() if path else self._config_path
        if not save_path:
            save_path = self.DEFAULT_CONFIG_DIR / self.CONFIG_FILE_NAME

        save_path.parent.mkdir(parents=True, exist_ok=True)

        # 转换为字典
        data = self._config_to_dict()

        with open(save_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"配置已保存: {save_path}")

    def _config_to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典"""
        return {
            "llm": {
                "default_provider": self._config.llm.default_provider,
                "task_routing": self._config.llm.task_routing,
                "claude": asdict(self._config.llm.claude),
                "deepseek": asdict(self._config.llm.deepseek),
                "qwen": asdict(self._config.llm.qwen),
                "doubao": asdict(self._config.llm.doubao),
            },
            "memory": asdict(self._config.memory),
            "channels": asdict(self._config.channels),
            "heartbeat": asdict(self._config.heartbeat),
            "log": asdict(self._config.log),
            "skills_dir": self._config.skills_dir,
            "system_prompt": self._config.system_prompt,
        }

    def get_provider_config(self, provider: str) -> Optional[LLMProviderConfig]:
        """获取指定提供商的配置"""
        return getattr(self._config.llm, provider, None)

    def get_enabled_providers(self) -> list:
        """获取所有启用的提供商"""
        providers = []
        for name in ["claude", "deepseek", "qwen", "doubao"]:
            config = getattr(self._config.llm, name)
            if config.enabled and config.api_key:
                providers.append(name)
        return providers

    @classmethod
    def reset(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None
