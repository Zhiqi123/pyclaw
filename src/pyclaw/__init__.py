"""
PyClaw - 轻量级个人 AI 助手系统

一个模块化、可扩展的 AI 助手框架，支持多模型、多通道。

使用示例:
    from pyclaw import PyClaw

    # 创建实例
    claw = PyClaw()

    # 处理消息
    response = claw.chat("你好")
    print(response.content)
"""

__version__ = "0.2.2"
__author__ = "PyClaw Team"

# 核心模块
from .core import EventBus, EventType, Event, Config, setup_logger, get_logger

# 记忆模块
from .memory import Database, MemoryManager, Message, Conversation, MessageRole

# LLM 模块
from .llm import (
    LLMRouter, LLMResponse, ToolCall,
    BaseProvider, ClaudeProvider,
    DeepSeekProvider, QwenProvider, DoubaoProvider
)

# Agent 模块
from .agent import AgentCore, AgentResponse, ToolRegistry, Tool, ToolResult

# 技能模块
from .skills import (
    SkillLoader, SkillRegistry, SkillExecutor,
    Skill, SkillTrigger, SkillMatch
)

# 通道模块
from .channels import (
    ChannelManager, BaseChannel,
    IMessageChannel, WeChatChannel,
    ChannelType, ChannelStatus,
    IncomingMessage, OutgoingMessage
)

# 调度模块
from .scheduler import HeartbeatScheduler, ScheduledTask, TaskResult, TaskStatus

__all__ = [
    # 版本
    "__version__",

    # 核心
    "EventBus", "EventType", "Event",
    "Config",
    "setup_logger", "get_logger",

    # 记忆
    "Database", "MemoryManager",
    "Message", "Conversation", "MessageRole",

    # LLM
    "LLMRouter", "LLMResponse", "ToolCall",
    "BaseProvider", "ClaudeProvider",
    "DeepSeekProvider", "QwenProvider", "DoubaoProvider",

    # Agent
    "AgentCore", "AgentResponse",
    "ToolRegistry", "Tool", "ToolResult",

    # 技能
    "SkillLoader", "SkillRegistry", "SkillExecutor",
    "Skill", "SkillTrigger", "SkillMatch",

    # 通道
    "ChannelManager", "BaseChannel",
    "IMessageChannel", "WeChatChannel",
    "ChannelType", "ChannelStatus",
    "IncomingMessage", "OutgoingMessage",

    # 调度
    "HeartbeatScheduler", "ScheduledTask", "TaskResult", "TaskStatus",

    # 主类
    "PyClaw",
]


class PyClaw:
    """
    PyClaw 主类

    整合所有模块，提供统一的接口。

    使用示例:
        claw = PyClaw()
        claw.register_tool("get_time", "获取时间")(lambda: "12:00")
        response = claw.chat("现在几点？")
    """

    def __init__(self, config_path: str = None):
        """
        初始化 PyClaw

        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        self.config = Config()
        if config_path:
            self.config.load(config_path)
        else:
            self.config.load()

        # 初始化日志
        setup_logger(
            level=self.config.log_level,
            log_file=self.config.log_file
        )

        # 初始化数据库
        self.db = Database(self.config.database_path)
        self.db.initialize()

        # 初始化记忆管理器
        self.memory = MemoryManager(self.db, self.config)

        # 初始化工具注册表
        self.tools = ToolRegistry()

        # 初始化 LLM 路由器
        self.llm = LLMRouter(self.config)

        # 初始化 Agent
        self.agent = AgentCore(self.llm, self.memory, self.tools, self.config)

        # 初始化技能系统
        self.skill_loader = SkillLoader()
        self.skill_registry = SkillRegistry(self.skill_loader)
        self.skill_executor = SkillExecutor(
            self.skill_registry,
            default_system_prompt=self.config.system_prompt
        )

        # 初始化通道管理器
        self.channels = ChannelManager()

        # 初始化调度器
        self.scheduler = HeartbeatScheduler()

        # 事件总线
        self.event_bus = EventBus()

    def chat(
        self,
        message: str,
        conversation_id: int = None,
        channel: str = "cli",
        channel_id: str = ""
    ) -> AgentResponse:
        """
        处理聊天消息

        Args:
            message: 用户消息
            conversation_id: 对话 ID
            channel: 通道类型
            channel_id: 通道 ID（如发送者电话号码），用于实现上下文记忆

        Returns:
            Agent 响应
        """
        # 尝试匹配技能
        skill_result = self.skill_executor.execute(message)

        if skill_result.success and skill_result.skill_name:
            # 使用技能的提示词
            self.agent.system_prompt = skill_result.system_prompt
            message = skill_result.user_prompt

        return self.agent.process(
            message,
            conversation_id=conversation_id,
            channel=channel,
            channel_id=channel_id
        )

    async def chat_async(
        self,
        message: str,
        conversation_id: int = None,
        channel: str = "cli",
        channel_id: str = ""
    ) -> AgentResponse:
        """异步处理聊天消息"""
        skill_result = self.skill_executor.execute(message)

        if skill_result.success and skill_result.skill_name:
            self.agent.system_prompt = skill_result.system_prompt
            message = skill_result.user_prompt

        return await self.agent.process_async(
            message,
            conversation_id=conversation_id,
            channel=channel,
            channel_id=channel_id
        )

    def register_tool(self, name: str, description: str, parameters: list = None):
        """
        注册工具的装饰器

        使用示例:
            @claw.register_tool("get_time", "获取当前时间")
            def get_time():
                return datetime.now().isoformat()
        """
        return self.tools.register(name, description, parameters)

    def load_skills(self, directory: str) -> int:
        """
        从目录加载技能

        Args:
            directory: 技能目录

        Returns:
            加载的技能数量
        """
        return self.skill_registry.load_directory(directory)

    def add_channel(self, channel: BaseChannel) -> None:
        """添加通道"""
        self.channels.register(channel)

    def start(self) -> None:
        """启动所有服务"""
        self.channels.connect_all()
        self.channels.start_all()
        self.scheduler.start()

    def stop(self) -> None:
        """停止所有服务"""
        self.scheduler.stop()
        self.channels.stop_all()
        self.channels.disconnect_all()
