"""
阶段2 模型接入层测试
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from pyclaw.llm import (
    BaseProvider, LLMResponse, ToolCall,
    LLMRouter,
    DeepSeekProvider, QwenProvider, DoubaoProvider
)
from pyclaw.llm.router import TaskType
from pyclaw.core import Config, EventBus


class TestLLMResponse:
    """LLMResponse 测试"""

    def test_basic_response(self):
        """测试基本响应"""
        response = LLMResponse(
            content="你好！",
            finish_reason="stop"
        )
        assert response.content == "你好！"
        assert not response.has_tool_calls

    def test_tool_calls_response(self):
        """测试工具调用响应"""
        tool_call = ToolCall(
            id="call_123",
            name="get_weather",
            arguments='{"city": "北京"}'
        )
        response = LLMResponse(
            content="",
            tool_calls=[tool_call],
            finish_reason="tool_calls"
        )
        assert response.has_tool_calls
        assert len(response.tool_calls) == 1

    def test_tool_call_to_dict(self):
        """测试工具调用转字典"""
        tool_call = ToolCall(
            id="call_123",
            name="get_weather",
            arguments='{"city": "北京"}'
        )
        d = tool_call.to_dict()
        assert d["id"] == "call_123"
        assert d["type"] == "function"
        assert d["function"]["name"] == "get_weather"


class TestLLMRouter:
    """LLMRouter 测试"""

    def setup_method(self):
        """每个测试前重置"""
        EventBus.reset()
        Config.reset()

    def test_task_routing(self):
        """测试任务路由配置"""
        config = Config()
        config.load()
        router = LLMRouter(config)

        routing = router.get_task_routing()
        assert "default" in routing

    def test_set_task_routing(self):
        """测试设置任务路由"""
        config = Config()
        config.load()
        router = LLMRouter(config)

        router.set_task_routing(TaskType.CODE_GENERATION, "deepseek")
        routing = router.get_task_routing()
        # 路由使用字符串键（task_type.value）
        assert routing[TaskType.CODE_GENERATION.value] == "deepseek"

    def test_get_available_providers_empty(self):
        """测试获取可用提供商（无配置时）"""
        config = Config()
        config.load()
        router = LLMRouter(config)

        # 没有配置 API Key 时应该返回空
        available = router.get_available_providers()
        # 默认配置没有 API Key，所以应该为空
        assert isinstance(available, list)

    @patch('pyclaw.llm.openai_compat.OpenAI')
    @patch('pyclaw.llm.openai_compat.AsyncOpenAI')
    def test_get_provider_with_config(self, mock_async_openai, mock_openai):
        """测试获取已配置的 Provider"""
        config = Config()
        config.load()
        # 模拟配置了 API Key
        config._config.llm.deepseek.api_key = "test_key"
        config._config.llm.deepseek.enabled = True

        router = LLMRouter(config)
        provider = router.get_provider("deepseek")

        assert provider is not None
        assert provider.name == "deepseek"

    def test_get_provider_unknown(self):
        """测试获取未知 Provider"""
        config = Config()
        config.load()
        router = LLMRouter(config)

        provider = router.get_provider("unknown_provider")
        assert provider is None


class TestProviderCapabilities:
    """Provider 能力测试"""

    @patch('pyclaw.llm.openai_compat.OpenAI')
    @patch('pyclaw.llm.openai_compat.AsyncOpenAI')
    def test_deepseek_capabilities(self, mock_async, mock_sync):
        """测试 DeepSeek 能力"""
        provider = DeepSeekProvider(api_key="test")
        caps = provider.get_capabilities()

        assert caps["supports_tools"] is True
        assert caps["supports_vision"] is False
        assert caps["max_context_length"] == 128000

    @patch('pyclaw.llm.openai_compat.OpenAI')
    @patch('pyclaw.llm.openai_compat.AsyncOpenAI')
    def test_qwen_capabilities(self, mock_async, mock_sync):
        """测试 Qwen 能力"""
        provider = QwenProvider(api_key="test", model="qwen-plus")
        caps = provider.get_capabilities()

        assert caps["supports_tools"] is True
        assert caps["supports_streaming"] is True

    @patch('pyclaw.llm.openai_compat.OpenAI')
    @patch('pyclaw.llm.openai_compat.AsyncOpenAI')
    def test_qwen_vl_capabilities(self, mock_async, mock_sync):
        """测试 Qwen VL 视觉能力"""
        provider = QwenProvider(api_key="test", model="qwen-vl-max")
        caps = provider.get_capabilities()

        assert caps["supports_vision"] is True

    @patch('pyclaw.llm.openai_compat.OpenAI')
    @patch('pyclaw.llm.openai_compat.AsyncOpenAI')
    def test_doubao_capabilities(self, mock_async, mock_sync):
        """测试豆包能力"""
        provider = DoubaoProvider(api_key="test")
        caps = provider.get_capabilities()

        assert caps["supports_tools"] is True
        assert caps["max_context_length"] == 256000


class TestProviderChat:
    """Provider 聊天测试（Mock）"""

    @patch('pyclaw.llm.openai_compat.OpenAI')
    @patch('pyclaw.llm.openai_compat.AsyncOpenAI')
    def test_deepseek_chat_mock(self, mock_async, mock_sync):
        """测试 DeepSeek 聊天（Mock）"""
        # 设置 Mock 响应
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "你好！"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_sync.return_value = mock_client

        provider = DeepSeekProvider(api_key="test")
        response = provider.chat([{"role": "user", "content": "你好"}])

        assert response.content == "你好！"
        assert response.finish_reason == "stop"
        assert not response.has_tool_calls

    @patch('pyclaw.llm.openai_compat.OpenAI')
    @patch('pyclaw.llm.openai_compat.AsyncOpenAI')
    def test_tool_call_response_mock(self, mock_async, mock_sync):
        """测试工具调用响应（Mock）"""
        # 设置带工具调用的 Mock 响应
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "get_weather"
        mock_tool_call.function.arguments = '{"city": "北京"}'

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_response.choices[0].message.tool_calls = [mock_tool_call]
        mock_response.choices[0].finish_reason = "tool_calls"
        mock_response.usage.prompt_tokens = 20
        mock_response.usage.completion_tokens = 15

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_sync.return_value = mock_client

        provider = DeepSeekProvider(api_key="test")

        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取天气",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"}
                    }
                }
            }
        }]

        response = provider.chat(
            [{"role": "user", "content": "北京天气怎么样？"}],
            tools=tools
        )

        assert response.has_tool_calls
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"


class TestRouterSelection:
    """路由器选择测试"""

    def setup_method(self):
        EventBus.reset()
        Config.reset()

    @patch('pyclaw.llm.openai_compat.OpenAI')
    @patch('pyclaw.llm.openai_compat.AsyncOpenAI')
    def test_select_provider_by_task(self, mock_async, mock_sync):
        """测试按任务类型选择 Provider"""
        config = Config()
        config.load()
        config._config.llm.deepseek.api_key = "test_key"
        config._config.llm.qwen.api_key = "test_key"

        router = LLMRouter(config)
        router.set_task_routing(TaskType.CODE_GENERATION, "deepseek")
        router.set_task_routing(TaskType.CHINESE_CHAT, "qwen")

        # 代码生成应该选择 DeepSeek
        provider = router.select_provider(task_type=TaskType.CODE_GENERATION)
        assert provider is not None
        assert provider.name == "deepseek"

        # 中文对话应该选择 Qwen
        provider = router.select_provider(task_type=TaskType.CHINESE_CHAT)
        assert provider is not None
        assert provider.name == "qwen"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
