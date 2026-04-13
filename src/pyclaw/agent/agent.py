"""
Agent Core - 智能核心

实现感知→思考→行动的主循环。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

from .tools import ToolRegistry, ToolResult
from ..llm import LLMRouter, LLMResponse
from ..llm.router import TaskType
from ..memory import MemoryManager, MessageRole
from ..core.config import Config
from ..core.event_bus import EventBus, EventType
from ..core.logger import LoggerMixin

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Agent 响应"""
    content: str
    conversation_id: int
    tool_calls_made: int = 0
    total_tokens: int = 0
    provider_used: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentCore(LoggerMixin):
    """
    智能核心

    实现 Agent 的主循环：感知 → 思考 → 行动 → 工具调用循环

    使用示例:
        agent = AgentCore(llm_router, memory_manager, tool_registry)

        # 处理用户消息
        response = agent.process("你好", conversation_id=1)

        # 或异步处理
        response = await agent.process_async("今天天气怎么样？", conversation_id=1)
    """

    MAX_TOOL_ITERATIONS = 10  # 最大工具调用轮数

    def __init__(
        self,
        llm_router: LLMRouter,
        memory: MemoryManager,
        tool_registry: Optional[ToolRegistry] = None,
        config: Optional[Config] = None
    ):
        """
        初始化 Agent

        Args:
            llm_router: LLM 路由器
            memory: 记忆管理器
            tool_registry: 工具注册表
            config: 配置
        """
        self.llm = llm_router
        self.memory = memory
        self.tools = tool_registry or ToolRegistry()
        self.config = config or Config()
        self.event_bus = EventBus()

        # 系统提示词
        self._system_prompt = self.config.system_prompt

        # 回调钩子
        self._on_tool_call: Optional[Callable] = None
        self._on_thinking: Optional[Callable] = None

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str):
        self._system_prompt = value

    def set_on_tool_call(self, callback: Callable[[str, Dict, ToolResult], None]) -> None:
        """设置工具调用回调"""
        self._on_tool_call = callback

    def set_on_thinking(self, callback: Callable[[str], None]) -> None:
        """设置思考过程回调"""
        self._on_thinking = callback

    def process(
        self,
        user_input: str,
        conversation_id: Optional[int] = None,
        channel: str = "cli",
        channel_id: str = "",
        task_type: str = TaskType.DEFAULT,
        attachments: Optional[List[Dict]] = None,
        **kwargs
    ) -> AgentResponse:
        """
        处理用户输入（同步）

        Args:
            user_input: 用户输入
            conversation_id: 对话 ID，None 则根据 channel+channel_id 获取或创建
            channel: 通道类型
            channel_id: 通道 ID（如发送者电话号码/Apple ID）
            task_type: 任务类型
            attachments: 附件列表（图片等）
            **kwargs: 其他参数

        Returns:
            AgentResponse
        """
        # 1. 感知：获取或创建对话
        if conversation_id is None:
            if channel_id:
                # 根据 channel + channel_id 获取或创建对话（实现上下文记忆）
                conv = self.memory.get_or_create_conversation(
                    channel=channel,
                    channel_id=channel_id
                )
            else:
                # 没有 channel_id，创建临时对话
                conv = self.memory.create_conversation(channel=channel, channel_id=channel_id)
            conversation_id = conv.id
        else:
            conv = self.memory.get_conversation(conversation_id)
            if not conv:
                conv = self.memory.create_conversation(channel=channel, channel_id=channel_id)
                conversation_id = conv.id

        # 2. 保存用户消息（包含附件）
        self.memory.add_user_message(conversation_id, user_input, attachments=attachments)

        # 发布事件
        self.event_bus.publish(
            EventType.MESSAGE_RECEIVED,
            data={"content": user_input, "conversation_id": conversation_id},
            source="AgentCore"
        )

        # 3. 思考：构建上下文并调用 LLM
        response = self._think_and_act(
            conversation_id=conversation_id,
            task_type=task_type,
            current_attachments=attachments,  # 传递当前消息的附件
            **kwargs
        )

        return response

    async def process_async(
        self,
        user_input: str,
        conversation_id: Optional[int] = None,
        channel: str = "cli",
        channel_id: str = "",
        task_type: str = TaskType.DEFAULT,
        **kwargs
    ) -> AgentResponse:
        """异步处理用户输入"""
        # 1. 感知：获取或创建对话
        if conversation_id is None:
            if channel_id:
                conv = self.memory.get_or_create_conversation(
                    channel=channel,
                    channel_id=channel_id
                )
            else:
                conv = self.memory.create_conversation(channel=channel, channel_id=channel_id)
            conversation_id = conv.id

        # 2. 保存用户消息
        self.memory.add_user_message(conversation_id, user_input)

        self.event_bus.publish(
            EventType.MESSAGE_RECEIVED,
            data={"content": user_input, "conversation_id": conversation_id},
            source="AgentCore"
        )

        # 3. 思考与行动
        response = await self._think_and_act_async(
            conversation_id=conversation_id,
            task_type=task_type,
            **kwargs
        )

        return response

    def _think_and_act(
        self,
        conversation_id: int,
        task_type: str = TaskType.DEFAULT,
        current_attachments: Optional[List[Dict]] = None,
        **kwargs
    ) -> AgentResponse:
        """
        思考与行动循环（同步）

        实现工具调用循环，直到 LLM 返回最终响应。

        Args:
            conversation_id: 对话 ID
            task_type: 任务类型
            current_attachments: 当前消息的附件（图片等）
            **kwargs: 其他参数
        """
        tool_calls_made = 0
        total_tokens = 0
        provider_used = ""
        is_first_iteration = True  # 用于判断是否是第一次迭代（需要附加图片）

        for iteration in range(self.MAX_TOOL_ITERATIONS):
            # 构建消息
            messages = self._build_messages(conversation_id)

            # 在第一次迭代时，将附件添加到最后一条用户消息
            if is_first_iteration and current_attachments:
                messages = self._inject_attachments(messages, current_attachments)
                is_first_iteration = False

            # 获取可用工具
            tools = self.tools.get_schemas() if self.tools.list_tools() else None

            # 调用 LLM
            try:
                llm_response = self.llm.chat(
                    messages=messages,
                    tools=tools,
                    task_type=task_type,
                    **kwargs
                )
            except Exception as e:
                self.logger.error(f"LLM 调用失败: {e}")
                error_msg = f"抱歉，处理请求时出错: {e}"
                self.memory.add_assistant_message(conversation_id, error_msg)
                return AgentResponse(
                    content=error_msg,
                    conversation_id=conversation_id,
                    tool_calls_made=tool_calls_made
                )

            # 更新统计
            total_tokens += llm_response.usage.get("prompt_tokens", 0)
            total_tokens += llm_response.usage.get("completion_tokens", 0)
            provider_used = llm_response.provider  # 记录使用的 provider

            # 检查是否有工具调用
            if llm_response.has_tool_calls:
                # 保存助手消息（带工具调用）
                self.memory.add_assistant_message(
                    conversation_id,
                    llm_response.content,
                    tool_calls=[tc.to_dict() for tc in llm_response.tool_calls]
                )

                # 执行工具调用
                for tool_call in llm_response.tool_calls:
                    tool_calls_made += 1

                    if self._on_thinking:
                        self._on_thinking(f"调用工具: {tool_call.name}")

                    result = self.tools.execute(tool_call.name, tool_call.arguments)

                    # 回调
                    if self._on_tool_call:
                        self._on_tool_call(tool_call.name, tool_call.arguments, result)

                    # 保存工具结果
                    self.memory.add_tool_message(
                        conversation_id,
                        result.to_string(),
                        tool_call_id=tool_call.id,
                        name=tool_call.name
                    )

                    # 发布事件
                    self.event_bus.publish(
                        EventType.TOOL_EXECUTED,
                        data={
                            "tool": tool_call.name,
                            "success": result.success,
                            "conversation_id": conversation_id
                        },
                        source="AgentCore"
                    )

                # 继续循环，让 LLM 处理工具结果
                continue

            else:
                # 没有工具调用，返回最终响应
                final_content = llm_response.content

                # 保存助手消息
                self.memory.add_assistant_message(conversation_id, final_content)

                # 发布事件
                self.event_bus.publish(
                    EventType.MESSAGE_SENT,
                    data={"content": final_content, "conversation_id": conversation_id},
                    source="AgentCore"
                )

                return AgentResponse(
                    content=final_content,
                    conversation_id=conversation_id,
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    provider_used=provider_used
                )

        # 达到最大迭代次数
        error_msg = "抱歉，处理过程过于复杂，请简化您的请求。"
        self.memory.add_assistant_message(conversation_id, error_msg)
        return AgentResponse(
            content=error_msg,
            conversation_id=conversation_id,
            tool_calls_made=tool_calls_made,
            total_tokens=total_tokens
        )

    async def _think_and_act_async(
        self,
        conversation_id: int,
        task_type: str = TaskType.DEFAULT,
        **kwargs
    ) -> AgentResponse:
        """思考与行动循环（异步）"""
        tool_calls_made = 0
        total_tokens = 0

        for iteration in range(self.MAX_TOOL_ITERATIONS):
            messages = self._build_messages(conversation_id)
            tools = self.tools.get_schemas() if self.tools.list_tools() else None

            try:
                llm_response = await self.llm.chat_async(
                    messages=messages,
                    tools=tools,
                    task_type=task_type,
                    **kwargs
                )
            except Exception as e:
                self.logger.error(f"LLM 异步调用失败: {e}")
                error_msg = f"抱歉，处理请求时出错: {e}"
                self.memory.add_assistant_message(conversation_id, error_msg)
                return AgentResponse(
                    content=error_msg,
                    conversation_id=conversation_id,
                    tool_calls_made=tool_calls_made
                )

            total_tokens += llm_response.usage.get("prompt_tokens", 0)
            total_tokens += llm_response.usage.get("completion_tokens", 0)

            if llm_response.has_tool_calls:
                self.memory.add_assistant_message(
                    conversation_id,
                    llm_response.content,
                    tool_calls=[tc.to_dict() for tc in llm_response.tool_calls]
                )

                for tool_call in llm_response.tool_calls:
                    tool_calls_made += 1

                    result = await self.tools.execute_async(tool_call.name, tool_call.arguments)

                    if self._on_tool_call:
                        self._on_tool_call(tool_call.name, tool_call.arguments, result)

                    self.memory.add_tool_message(
                        conversation_id,
                        result.to_string(),
                        tool_call_id=tool_call.id,
                        name=tool_call.name
                    )

                    self.event_bus.publish(
                        EventType.TOOL_EXECUTED,
                        data={
                            "tool": tool_call.name,
                            "success": result.success,
                            "conversation_id": conversation_id
                        },
                        source="AgentCore"
                    )

                continue

            else:
                final_content = llm_response.content
                self.memory.add_assistant_message(conversation_id, final_content)

                self.event_bus.publish(
                    EventType.MESSAGE_SENT,
                    data={"content": final_content, "conversation_id": conversation_id},
                    source="AgentCore"
                )

                return AgentResponse(
                    content=final_content,
                    conversation_id=conversation_id,
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens
                )

        error_msg = "抱歉，处理过程过于复杂，请简化您的请求。"
        self.memory.add_assistant_message(conversation_id, error_msg)
        return AgentResponse(
            content=error_msg,
            conversation_id=conversation_id,
            tool_calls_made=tool_calls_made,
            total_tokens=total_tokens
        )

    def _build_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        """构建发送给 LLM 的消息列表"""
        messages = []

        # 系统提示词
        if self._system_prompt:
            messages.append({
                "role": "system",
                "content": self._system_prompt
            })

        # 历史上下文
        context = self.memory.get_context(conversation_id)
        messages.extend(context)

        return messages

    def _inject_attachments(
        self,
        messages: List[Dict[str, Any]],
        attachments: List[Dict]
    ) -> List[Dict[str, Any]]:
        """
        将附件注入到最后一条用户消息

        Args:
            messages: 消息列表
            attachments: 附件列表

        Returns:
            更新后的消息列表
        """
        if not messages or not attachments:
            return messages

        # 找到最后一条用户消息
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                original_content = messages[i].get("content", "")

                # 构建多模态内容
                content_parts = []

                # 添加图片
                for attachment in attachments:
                    if attachment.get("type") == "image":
                        content_parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": attachment.get("media_type", "image/jpeg"),
                                "data": attachment.get("data", "")
                            }
                        })

                # 添加文本
                if isinstance(original_content, str) and original_content:
                    content_parts.append({
                        "type": "text",
                        "text": original_content
                    })
                elif isinstance(original_content, list):
                    # 已经是多模态格式，合并
                    content_parts.extend(original_content)

                messages[i]["content"] = content_parts
                self.logger.debug(f"已将 {len(attachments)} 个附件注入到用户消息")
                break

        return messages

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Optional[List] = None,
        category: str = "general"
    ) -> Callable:
        """
        装饰器方式注册工具

        使用示例:
            @agent.register_tool("get_time", "获取当前时间")
            def get_time():
                return datetime.now().isoformat()
        """
        return self.tools.register(name, description, parameters, category)
