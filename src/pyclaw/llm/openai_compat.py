"""
OpenAI 兼容 Provider

支持 DeepSeek、通义千问、豆包等使用 OpenAI 兼容 API 的模型。
"""

import json
import logging
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

from .base import BaseProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI, AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class OpenAICompatProvider(BaseProvider):
    """
    OpenAI 兼容 Provider

    支持所有使用 OpenAI 兼容 API 的模型提供商。
    """

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 60,
        provider_name: str = "openai_compat"
    ):
        super().__init__(api_key, api_base, model, max_tokens, temperature, timeout)
        self._provider_name = provider_name

        if not HAS_OPENAI:
            raise ImportError("openai 库未安装，请运行: pip install openai")

        self._client = OpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=timeout
        )
        self._async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=timeout
        )

    @property
    def name(self) -> str:
        return self._provider_name

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> LLMResponse:
        """同步聊天"""
        try:
            params = {
                "model": kwargs.get("model", self.model),
                "messages": messages,
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "temperature": kwargs.get("temperature", self.temperature),
            }

            if tools:
                params["tools"] = tools
                params["tool_choice"] = kwargs.get("tool_choice", "auto")

            response = self._client.chat.completions.create(**params)
            return self._parse_response(response)

        except Exception as e:
            logger.error(f"{self.name} API 调用失败: {e}")
            raise

    async def chat_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> LLMResponse:
        """异步聊天"""
        try:
            params = {
                "model": kwargs.get("model", self.model),
                "messages": messages,
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "temperature": kwargs.get("temperature", self.temperature),
            }

            if tools:
                params["tools"] = tools
                params["tool_choice"] = kwargs.get("tool_choice", "auto")

            response = await self._async_client.chat.completions.create(**params)
            return self._parse_response(response)

        except Exception as e:
            logger.error(f"{self.name} API 异步调用失败: {e}")
            raise

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Generator[str, None, LLMResponse]:
        """流式聊天"""
        params = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": True,
        }

        if tools:
            params["tools"] = tools
            params["tool_choice"] = kwargs.get("tool_choice", "auto")

        content_parts = []
        tool_calls_data = {}  # id -> {name, arguments}
        finish_reason = "stop"

        response = self._client.chat.completions.create(**params)

        for chunk in response:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # 处理内容
            if delta.content:
                content_parts.append(delta.content)
                yield delta.content

            # 处理工具调用
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    tc_id = tc.id or list(tool_calls_data.keys())[-1] if tool_calls_data else "0"
                    if tc.id:
                        tool_calls_data[tc.id] = {
                            "name": tc.function.name if tc.function else "",
                            "arguments": ""
                        }
                    if tc.function and tc.function.arguments:
                        if tc_id in tool_calls_data:
                            tool_calls_data[tc_id]["arguments"] += tc.function.arguments

            # 处理结束原因
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        # 构建工具调用列表
        tool_calls = [
            ToolCall(id=tc_id, name=data["name"], arguments=data["arguments"])
            for tc_id, data in tool_calls_data.items()
        ]

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else finish_reason,
            usage={}
        )

    async def stream_chat_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> AsyncGenerator[str, LLMResponse]:
        """异步流式聊天"""
        params = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": True,
        }

        if tools:
            params["tools"] = tools
            params["tool_choice"] = kwargs.get("tool_choice", "auto")

        content_parts = []
        tool_calls_data = {}

        response = await self._async_client.chat.completions.create(**params)

        async for chunk in response:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if delta.content:
                content_parts.append(delta.content)
                yield delta.content

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.id:
                        tool_calls_data[tc.id] = {
                            "name": tc.function.name if tc.function else "",
                            "arguments": ""
                        }
                    if tc.function and tc.function.arguments:
                        tc_id = tc.id or list(tool_calls_data.keys())[-1]
                        if tc_id in tool_calls_data:
                            tool_calls_data[tc_id]["arguments"] += tc.function.arguments

        tool_calls = [
            ToolCall(id=tc_id, name=data["name"], arguments=data["arguments"])
            for tc_id, data in tool_calls_data.items()
        ]

    def _parse_response(self, response) -> LLMResponse:
        """解析 OpenAI 格式响应"""
        choice = response.choices[0]
        message = choice.message

        content = message.content or ""
        tool_calls = []

        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments
                ))

        finish_reason = choice.finish_reason or "stop"
        if tool_calls:
            finish_reason = "tool_calls"

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            raw_response=response
        )


class DeepSeekProvider(OpenAICompatProvider):
    """DeepSeek Provider"""

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 60
    ):
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            provider_name="deepseek"
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "supports_tools": True,
            "supports_vision": False,
            "supports_streaming": True,
            "max_context_length": 128000
        }


class QwenProvider(OpenAICompatProvider):
    """通义千问 Provider"""

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen-plus",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 60
    ):
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            provider_name="qwen"
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "supports_tools": True,
            "supports_vision": "vl" in self.model.lower(),
            "supports_streaming": True,
            "max_context_length": 1000000 if "max" in self.model.lower() else 131072
        }


class DoubaoProvider(OpenAICompatProvider):
    """豆包 Provider"""

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://ark.cn-beijing.volces.com/api/v3",
        model: str = "doubao-pro-32k",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 60
    ):
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            provider_name="doubao"
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "supports_tools": True,
            "supports_vision": "vision" in self.model.lower(),
            "supports_streaming": True,
            "max_context_length": 256000
        }
