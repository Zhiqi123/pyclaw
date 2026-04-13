"""
LLM Provider 基类

定义统一的 LLM 接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional
from enum import Enum


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: str  # JSON 字符串

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments
            }
        }


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # stop, tool_calls, length, error
    usage: Dict[str, int] = field(default_factory=dict)  # prompt_tokens, completion_tokens
    raw_response: Any = None  # 原始响应对象
    provider: str = ""  # 使用的 provider 名称

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class BaseProvider(ABC):
    """
    LLM Provider 基类

    所有模型提供商都需要实现这个接口。
    """

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 60
    ):
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    @property
    @abstractmethod
    def name(self) -> str:
        """提供商名称"""
        pass

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> LLMResponse:
        """
        同步聊天

        Args:
            messages: 消息列表
            tools: 可用工具列表
            **kwargs: 其他参数

        Returns:
            LLMResponse
        """
        pass

    @abstractmethod
    async def chat_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> LLMResponse:
        """异步聊天"""
        pass

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Generator[str, None, LLMResponse]:
        """
        流式聊天（同步）

        Yields:
            内容片段

        Returns:
            最终的 LLMResponse
        """
        # 默认实现：不支持流式，直接返回完整响应
        response = self.chat(messages, tools, **kwargs)
        yield response.content
        return response

    async def stream_chat_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> AsyncGenerator[str, LLMResponse]:
        """流式聊天（异步）"""
        response = await self.chat_async(messages, tools, **kwargs)
        yield response.content

    def get_capabilities(self) -> Dict[str, Any]:
        """
        获取提供商能力

        Returns:
            能力字典，包含：
            - supports_tools: 是否支持工具调用
            - supports_vision: 是否支持视觉
            - supports_streaming: 是否支持流式
            - max_context_length: 最大上下文长度
        """
        return {
            "supports_tools": True,
            "supports_vision": False,
            "supports_streaming": True,
            "max_context_length": 8192
        }

    def validate_config(self) -> bool:
        """验证配置是否有效"""
        return bool(self.api_key and self.model)
