"""
阶段3 核心智能层测试
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from pyclaw.agent import ToolRegistry, Tool, ToolResult, AgentCore
from pyclaw.agent.tools import ToolParameter
from pyclaw.llm import LLMResponse, ToolCall, LLMRouter
from pyclaw.memory import Database, MemoryManager
from pyclaw.core import Config, EventBus


class TestToolRegistry:
    """ToolRegistry 测试"""

    def test_register_tool(self):
        """测试注册工具"""
        registry = ToolRegistry()

        tool = Tool(
            name="test_tool",
            description="测试工具",
            parameters=[
                ToolParameter("arg1", "string", "参数1", required=True)
            ],
            handler=lambda arg1: f"收到: {arg1}"
        )
        registry.add(tool)

        assert registry.get("test_tool") is not None
        assert registry.get("test_tool").name == "test_tool"

    def test_register_decorator(self):
        """测试装饰器注册"""
        registry = ToolRegistry()

        @registry.register("add", "加法", [
            ToolParameter("a", "number", "第一个数", required=True),
            ToolParameter("b", "number", "第二个数", required=True)
        ])
        def add(a: float, b: float) -> float:
            return a + b

        tool = registry.get("add")
        assert tool is not None
        assert tool.handler is not None

    def test_execute_tool(self):
        """测试执行工具"""
        registry = ToolRegistry()

        @registry.register("greet", "打招呼", [
            ToolParameter("name", "string", "名字", required=True)
        ])
        def greet(name: str) -> str:
            return f"你好, {name}!"

        result = registry.execute("greet", {"name": "张三"})
        assert result.success
        assert result.output == "你好, 张三!"

    def test_execute_with_json_string(self):
        """测试 JSON 字符串参数"""
        registry = ToolRegistry()

        @registry.register("echo", "回显")
        def echo(message: str = "default") -> str:
            return message

        result = registry.execute("echo", '{"message": "hello"}')
        assert result.success
        assert result.output == "hello"

    def test_execute_nonexistent_tool(self):
        """测试执行不存在的工具"""
        registry = ToolRegistry()
        result = registry.execute("nonexistent", {})
        assert not result.success
        assert "不存在" in result.error

    def test_tool_schema(self):
        """测试工具 Schema 生成"""
        registry = ToolRegistry()

        tool = Tool(
            name="get_weather",
            description="获取天气",
            parameters=[
                ToolParameter("city", "string", "城市", required=True),
                ToolParameter("unit", "string", "单位", enum=["celsius", "fahrenheit"])
            ],
            handler=lambda city, unit="celsius": {"city": city, "temp": 25}
        )
        registry.add(tool)

        schemas = registry.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "get_weather"
        assert "city" in schemas[0]["function"]["parameters"]["properties"]

    def test_disable_enable_tool(self):
        """测试禁用/启用工具"""
        registry = ToolRegistry()

        @registry.register("test", "测试")
        def test_func():
            return "ok"

        # 禁用
        registry.disable("test")
        result = registry.execute("test", {})
        assert not result.success
        assert "禁用" in result.error

        # 启用
        registry.enable("test")
        result = registry.execute("test", {})
        assert result.success

    def test_list_tools_by_category(self):
        """测试按分类列出工具"""
        registry = ToolRegistry()

        registry.add(Tool(name="tool1", description="工具1", category="cat1", handler=lambda: 1))
        registry.add(Tool(name="tool2", description="工具2", category="cat1", handler=lambda: 2))
        registry.add(Tool(name="tool3", description="工具3", category="cat2", handler=lambda: 3))

        cat1_tools = registry.list_tools(category="cat1")
        assert len(cat1_tools) == 2

        cat2_tools = registry.list_tools(category="cat2")
        assert len(cat2_tools) == 1


class TestToolResult:
    """ToolResult 测试"""

    def test_success_result(self):
        """测试成功结果"""
        result = ToolResult(success=True, output={"key": "value"})
        assert result.success
        s = result.to_string()
        assert "key" in s
        assert "value" in s

    def test_error_result(self):
        """测试错误结果"""
        result = ToolResult(success=False, output=None, error="出错了")
        assert not result.success
        s = result.to_string()
        assert "错误" in s
        assert "出错了" in s


class TestAgentCore:
    """AgentCore 测试"""

    def setup_method(self):
        """每个测试前设置"""
        EventBus.reset()
        Config.reset()

        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.db = Database(str(self.db_path))
        self.db.initialize()

        self.config = Config()
        self.config.load()

        self.memory = MemoryManager(self.db, self.config)
        self.tools = ToolRegistry()

    def _create_mock_router(self, response_content: str, tool_calls: list = None):
        """创建 Mock LLM Router"""
        mock_router = MagicMock(spec=LLMRouter)

        response = LLMResponse(
            content=response_content,
            tool_calls=tool_calls or [],
            finish_reason="tool_calls" if tool_calls else "stop",
            usage={"prompt_tokens": 10, "completion_tokens": 5}
        )
        mock_router.chat.return_value = response
        return mock_router

    def test_simple_conversation(self):
        """测试简单对话"""
        mock_router = self._create_mock_router("你好！有什么可以帮你的？")

        agent = AgentCore(mock_router, self.memory, self.tools, self.config)
        response = agent.process("你好")

        assert response.content == "你好！有什么可以帮你的？"
        assert response.conversation_id is not None
        assert response.tool_calls_made == 0

    def test_conversation_with_tool_call(self):
        """测试带工具调用的对话"""
        # 注册工具
        @self.tools.register("get_time", "获取当前时间")
        def get_time():
            return "2024-01-01 12:00:00"

        # 第一次调用返回工具调用
        tool_call = ToolCall(id="call_1", name="get_time", arguments="{}")
        first_response = LLMResponse(
            content="",
            tool_calls=[tool_call],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 10, "completion_tokens": 5}
        )

        # 第二次调用返回最终响应
        second_response = LLMResponse(
            content="现在是 2024-01-01 12:00:00",
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 20, "completion_tokens": 10}
        )

        mock_router = MagicMock(spec=LLMRouter)
        mock_router.chat.side_effect = [first_response, second_response]

        agent = AgentCore(mock_router, self.memory, self.tools, self.config)
        response = agent.process("现在几点了？")

        assert response.content == "现在是 2024-01-01 12:00:00"
        assert response.tool_calls_made == 1

    def test_tool_call_callback(self):
        """测试工具调用回调"""
        @self.tools.register("echo", "回显")
        def echo(msg: str = ""):
            return msg

        tool_call = ToolCall(id="call_1", name="echo", arguments='{"msg": "test"}')
        first_response = LLMResponse(content="", tool_calls=[tool_call], finish_reason="tool_calls", usage={})
        second_response = LLMResponse(content="Done", tool_calls=[], finish_reason="stop", usage={})

        mock_router = MagicMock(spec=LLMRouter)
        mock_router.chat.side_effect = [first_response, second_response]

        callback_called = []

        def on_tool_call(name, args, result):
            callback_called.append((name, result.success))

        agent = AgentCore(mock_router, self.memory, self.tools, self.config)
        agent.set_on_tool_call(on_tool_call)
        agent.process("测试")

        assert len(callback_called) == 1
        assert callback_called[0][0] == "echo"
        assert callback_called[0][1] is True

    def test_system_prompt(self):
        """测试系统提示词"""
        mock_router = self._create_mock_router("OK")

        agent = AgentCore(mock_router, self.memory, self.tools, self.config)
        agent.system_prompt = "你是一个测试助手"

        assert agent.system_prompt == "你是一个测试助手"

    def test_register_tool_decorator(self):
        """测试通过 Agent 注册工具"""
        mock_router = self._create_mock_router("OK")
        agent = AgentCore(mock_router, self.memory, self.tools, self.config)

        @agent.register_tool("my_tool", "我的工具")
        def my_tool():
            return "result"

        assert agent.tools.get("my_tool") is not None

    def test_max_iterations(self):
        """测试最大迭代次数限制"""
        # 总是返回工具调用，测试是否会停止
        @self.tools.register("infinite", "无限工具")
        def infinite():
            return "again"

        tool_call = ToolCall(id="call_1", name="infinite", arguments="{}")
        response = LLMResponse(content="", tool_calls=[tool_call], finish_reason="tool_calls", usage={})

        mock_router = MagicMock(spec=LLMRouter)
        mock_router.chat.return_value = response

        agent = AgentCore(mock_router, self.memory, self.tools, self.config)
        result = agent.process("测试")

        # 应该在达到最大迭代次数后停止
        assert "复杂" in result.content or mock_router.chat.call_count <= AgentCore.MAX_TOOL_ITERATIONS + 1


class TestAgentCoreAsync:
    """AgentCore 异步测试"""

    def setup_method(self):
        EventBus.reset()
        Config.reset()

        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.db = Database(str(self.db_path))
        self.db.initialize()

        self.config = Config()
        self.config.load()

        self.memory = MemoryManager(self.db, self.config)
        self.tools = ToolRegistry()

    @pytest.mark.asyncio
    async def test_async_process(self):
        """测试异步处理"""
        mock_router = MagicMock(spec=LLMRouter)
        response = LLMResponse(
            content="异步响应",
            tool_calls=[],
            finish_reason="stop",
            usage={}
        )
        # 使用 AsyncMock 返回协程
        mock_router.chat_async = AsyncMock(return_value=response)

        agent = AgentCore(mock_router, self.memory, self.tools, self.config)
        result = await agent.process_async("测试")

        assert result.content == "异步响应"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
