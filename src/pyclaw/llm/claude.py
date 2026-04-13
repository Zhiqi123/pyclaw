"""
Claude Provider - Anthropic API 封装
"""

import logging
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

from .base import BaseProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


class ClaudeProvider(BaseProvider):
    """
    Claude Provider

    使用 Anthropic 官方 SDK 调用 Claude 模型。
    """

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://api.anthropic.com",
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout: int = 60
    ):
        super().__init__(api_key, api_base, model, max_tokens, temperature, timeout)

        if not HAS_ANTHROPIC:
            raise ImportError("anthropic 库未安装，请运行: pip install anthropic")

        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=api_base if api_base != "https://api.anthropic.com" else None,
            timeout=timeout
        )
        self._async_client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=api_base if api_base != "https://api.anthropic.com" else None,
            timeout=timeout
        )

    @property
    def name(self) -> str:
        return "claude"

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> LLMResponse:
        """同步聊天"""
        # 分离系统消息
        system_prompt, chat_messages = self._prepare_messages(messages)

        # 转换工具格式
        anthropic_tools = self._convert_tools(tools) if tools else None

        try:
            params = {
                "model": kwargs.get("model", self.model),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "temperature": kwargs.get("temperature", self.temperature),
                "messages": chat_messages,
            }

            if system_prompt:
                params["system"] = system_prompt

            if anthropic_tools:
                params["tools"] = anthropic_tools

            response = self._client.messages.create(**params)
            return self._parse_response(response)

        except Exception as e:
            logger.error(f"Claude API 调用失败: {e}")
            raise

    async def chat_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> LLMResponse:
        """异步聊天"""
        system_prompt, chat_messages = self._prepare_messages(messages)
        anthropic_tools = self._convert_tools(tools) if tools else None

        try:
            params = {
                "model": kwargs.get("model", self.model),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "temperature": kwargs.get("temperature", self.temperature),
                "messages": chat_messages,
            }

            if system_prompt:
                params["system"] = system_prompt

            if anthropic_tools:
                params["tools"] = anthropic_tools

            response = await self._async_client.messages.create(**params)
            return self._parse_response(response)

        except Exception as e:
            logger.error(f"Claude API 异步调用失败: {e}")
            raise

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Generator[str, None, LLMResponse]:
        """流式聊天"""
        system_prompt, chat_messages = self._prepare_messages(messages)
        anthropic_tools = self._convert_tools(tools) if tools else None

        params = {
            "model": kwargs.get("model", self.model),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "messages": chat_messages,
        }

        if system_prompt:
            params["system"] = system_prompt

        if anthropic_tools:
            params["tools"] = anthropic_tools

        content_parts = []
        tool_calls = []
        usage = {}

        with self._client.messages.stream(**params) as stream:
            for event in stream:
                if hasattr(event, 'type'):
                    if event.type == 'content_block_delta':
                        if hasattr(event.delta, 'text'):
                            content_parts.append(event.delta.text)
                            yield event.delta.text
                    elif event.type == 'message_delta':
                        if hasattr(event, 'usage'):
                            usage = {
                                "prompt_tokens": getattr(event.usage, 'input_tokens', 0),
                                "completion_tokens": getattr(event.usage, 'output_tokens', 0)
                            }

            # 获取最终消息
            final_message = stream.get_final_message()
            if final_message:
                tool_calls = self._extract_tool_calls(final_message)

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage
        )

    def _prepare_messages(self, messages: List[Dict]) -> tuple:
        """
        准备消息，分离系统消息

        Returns:
            (system_prompt, chat_messages)
        """
        system_prompt = ""
        chat_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content
            elif role == "tool":
                # Claude 使用 tool_result 格式
                chat_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content
                    }]
                })
            elif role == "assistant" and msg.get("tool_calls"):
                # 助手的工具调用
                content_blocks = []
                if content:
                    content_blocks.append({"type": "text", "text": content})

                for tc in msg["tool_calls"]:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": self._parse_json_safe(tc["function"]["arguments"])
                    })

                chat_messages.append({
                    "role": "assistant",
                    "content": content_blocks
                })
            else:
                chat_messages.append({
                    "role": role,
                    "content": content
                })

        # Claude API 要求 messages 不能为空
        if not chat_messages:
            raise ValueError("消息列表为空，无法调用 Claude API")

        return system_prompt, chat_messages

    def _convert_tools(self, tools: List[Dict]) -> List[Dict]:
        """转换工具格式为 Anthropic 格式"""
        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}})
                })
        return anthropic_tools

    def _parse_response(self, response) -> LLMResponse:
        """解析 Anthropic 响应"""
        content = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                import json
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=json.dumps(block.input) if isinstance(block.input, dict) else str(block.input)
                ))

        finish_reason = "tool_calls" if tool_calls else response.stop_reason or "stop"

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens
            },
            raw_response=response
        )

    def _extract_tool_calls(self, message) -> List[ToolCall]:
        """从消息中提取工具调用"""
        import json
        tool_calls = []
        for block in message.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=json.dumps(block.input) if isinstance(block.input, dict) else str(block.input)
                ))
        return tool_calls

    def _parse_json_safe(self, s: str) -> dict:
        """安全解析 JSON"""
        import json
        try:
            return json.loads(s)
        except Exception:
            return {}

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "supports_tools": True,
            "supports_vision": True,
            "supports_streaming": True,
            "max_context_length": 200000
        }
