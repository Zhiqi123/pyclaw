"""
工具注册表 - 管理可用工具

定义工具格式和注册机制。
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from enum import Enum

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str  # string, number, boolean, array, object
    description: str = ""
    required: bool = False
    enum: Optional[List[str]] = None
    default: Any = None


@dataclass
class Tool:
    """
    工具定义

    使用示例:
        tool = Tool(
            name="get_weather",
            description="获取指定城市的天气",
            parameters=[
                ToolParameter("city", "string", "城市名称", required=True)
            ],
            handler=get_weather_func
        )
    """
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)
    handler: Optional[Callable] = None
    category: str = "general"
    enabled: bool = True

    def to_openai_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI 工具格式"""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {"type": param.type, "description": param.description}
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    output: Any
    error: Optional[str] = None

    def to_string(self) -> str:
        """转换为字符串（用于返回给 LLM）"""
        if self.success:
            if isinstance(self.output, (dict, list)):
                return json.dumps(self.output, ensure_ascii=False, indent=2)
            return str(self.output)
        else:
            return f"错误: {self.error}"


class ToolRegistry:
    """
    工具注册表

    管理所有可用工具的注册、查询和执行。

    使用示例:
        registry = ToolRegistry()

        # 注册工具
        @registry.register("get_time", "获取当前时间")
        def get_time():
            return datetime.now().isoformat()

        # 或手动注册
        registry.add(tool)

        # 执行工具
        result = registry.execute("get_time", {})
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._categories: Dict[str, List[str]] = {}  # category -> tool names

    def add(self, tool: Tool) -> None:
        """添加工具"""
        self._tools[tool.name] = tool

        # 更新分类索引
        if tool.category not in self._categories:
            self._categories[tool.category] = []
        if tool.name not in self._categories[tool.category]:
            self._categories[tool.category].append(tool.name)

        logger.debug(f"注册工具: {tool.name}")

    def register(
        self,
        name: str,
        description: str,
        parameters: Optional[List[ToolParameter]] = None,
        category: str = "general"
    ) -> Callable:
        """
        装饰器方式注册工具

        使用示例:
            @registry.register("add", "加法运算", [
                ToolParameter("a", "number", "第一个数", required=True),
                ToolParameter("b", "number", "第二个数", required=True)
            ])
            def add(a: float, b: float) -> float:
                return a + b
        """
        def decorator(func: Callable) -> Callable:
            tool = Tool(
                name=name,
                description=description,
                parameters=parameters or [],
                handler=func,
                category=category
            )
            self.add(tool)
            return func
        return decorator

    def get(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self._tools.get(name)

    def remove(self, name: str) -> bool:
        """移除工具"""
        if name in self._tools:
            tool = self._tools.pop(name)
            if tool.category in self._categories:
                self._categories[tool.category].remove(name)
            return True
        return False

    def list_tools(self, category: Optional[str] = None, enabled_only: bool = True) -> List[Tool]:
        """列出工具"""
        if category:
            names = self._categories.get(category, [])
            tools = [self._tools[n] for n in names if n in self._tools]
        else:
            tools = list(self._tools.values())

        if enabled_only:
            tools = [t for t in tools if t.enabled]

        return tools

    def get_schemas(self, category: Optional[str] = None) -> List[Dict]:
        """获取工具的 OpenAI Schema 列表"""
        tools = self.list_tools(category=category, enabled_only=True)
        return [t.to_openai_schema() for t in tools]

    def execute(self, name: str, arguments: Union[str, Dict]) -> ToolResult:
        """
        执行工具

        Args:
            name: 工具名称
            arguments: 参数（JSON 字符串或字典）

        Returns:
            ToolResult
        """
        tool = self.get(name)
        if not tool:
            return ToolResult(success=False, output=None, error=f"工具不存在: {name}")

        if not tool.enabled:
            return ToolResult(success=False, output=None, error=f"工具已禁用: {name}")

        if not tool.handler:
            return ToolResult(success=False, output=None, error=f"工具无处理函数: {name}")

        # 解析参数
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError as e:
                return ToolResult(success=False, output=None, error=f"参数解析失败: {e}")
        else:
            args = arguments

        # 执行
        try:
            result = tool.handler(**args)
            return ToolResult(success=True, output=result)
        except Exception as e:
            logger.error(f"工具执行失败 [{name}]: {e}")
            return ToolResult(success=False, output=None, error=str(e))

    async def execute_async(self, name: str, arguments: Union[str, Dict]) -> ToolResult:
        """异步执行工具"""
        import asyncio

        tool = self.get(name)
        if not tool:
            return ToolResult(success=False, output=None, error=f"工具不存在: {name}")

        if not tool.enabled:
            return ToolResult(success=False, output=None, error=f"工具已禁用: {name}")

        if not tool.handler:
            return ToolResult(success=False, output=None, error=f"工具无处理函数: {name}")

        # 解析参数
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError as e:
                return ToolResult(success=False, output=None, error=f"参数解析失败: {e}")
        else:
            args = arguments

        # 执行
        try:
            if asyncio.iscoroutinefunction(tool.handler):
                result = await tool.handler(**args)
            else:
                result = tool.handler(**args)
            return ToolResult(success=True, output=result)
        except Exception as e:
            logger.error(f"工具异步执行失败 [{name}]: {e}")
            return ToolResult(success=False, output=None, error=str(e))

    def enable(self, name: str) -> bool:
        """启用工具"""
        tool = self.get(name)
        if tool:
            tool.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """禁用工具"""
        tool = self.get(name)
        if tool:
            tool.enabled = False
            return True
        return False

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        return list(self._categories.keys())
