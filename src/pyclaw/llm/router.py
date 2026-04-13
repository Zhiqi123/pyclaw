"""
LLM Router - 模型路由器

根据任务类型和配置选择合适的模型提供商，支持断路器、重试和降级。
"""

import logging
from typing import Any, Dict, List, Optional, Type

from .base import BaseProvider, LLMResponse
from .claude import ClaudeProvider
from .openai_compat import DeepSeekProvider, QwenProvider, DoubaoProvider
from .task_detector import TaskDetector, TaskType, detect_task_type
from ..core.config import Config, LLMProviderConfig
from ..core.event_bus import EventBus, EventType
from ..core.logger import LoggerMixin
from ..core.resilience import (
    CircuitBreaker, CircuitBreakerConfig, CircuitOpenError,
    RetryConfig, RetryStrategy, retry_with_backoff, retry_with_backoff_async
)

logger = logging.getLogger(__name__)


# Provider 类映射
PROVIDER_CLASSES: Dict[str, Type[BaseProvider]] = {
    "claude": ClaudeProvider,
    "deepseek": DeepSeekProvider,
    "qwen": QwenProvider,
    "doubao": DoubaoProvider,
}

# 默认降级顺序
DEFAULT_FALLBACK_ORDER = ["deepseek", "qwen", "claude", "doubao"]


class LLMRouter(LoggerMixin):
    """
    LLM 路由器

    根据任务类型自动选择最合适的模型，支持故障转移、断路器和重试。

    使用示例:
        router = LLMRouter(config)

        # 自动选择模型（带任务检测）
        response = router.chat(messages)

        # 指定任务类型
        response = router.chat(messages, task_type=TaskType.CODE_GENERATION)

        # 指定提供商
        response = router.chat(messages, provider="claude")
    """

    def __init__(self, config: Optional[Config] = None):
        """
        初始化路由器

        Args:
            config: 配置实例，None 则使用全局配置
        """
        self.config = config or Config()
        self.event_bus = EventBus()

        # 已初始化的 Provider 缓存
        self._providers: Dict[str, BaseProvider] = {}

        # 断路器
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

        # 任务检测器
        self._task_detector = TaskDetector()

        # 任务路由规则
        self._task_routing = self.config.llm.task_routing.copy()

        # 故障转移顺序
        self._fallback_order = DEFAULT_FALLBACK_ORDER.copy()

        # 重试配置
        self._retry_config = RetryConfig(
            max_attempts=3,
            strategy=RetryStrategy.EXPONENTIAL_JITTER,
            base_delay=1.0,
            max_delay=30.0
        )

        # 是否启用自动任务检测
        self._auto_detect_task = True

    def get_provider(self, name: str) -> Optional[BaseProvider]:
        """
        获取指定的 Provider

        Args:
            name: 提供商名称

        Returns:
            Provider 实例，未配置或不可用返回 None
        """
        # 检查缓存
        if name in self._providers:
            return self._providers[name]

        # 获取配置
        provider_config = self.config.get_provider_config(name)
        if not provider_config or not provider_config.api_key:
            self.logger.debug(f"Provider {name} 未配置或无 API Key")
            return None

        # 创建 Provider
        provider_class = PROVIDER_CLASSES.get(name)
        if not provider_class:
            self.logger.warning(f"未知的 Provider: {name}")
            return None

        try:
            provider = provider_class(
                api_key=provider_config.api_key,
                api_base=provider_config.api_base,
                model=provider_config.model,
                max_tokens=provider_config.max_tokens,
                temperature=provider_config.temperature,
                timeout=provider_config.timeout
            )
            self._providers[name] = provider

            # 创建断路器
            self._circuit_breakers[name] = CircuitBreaker(
                name=name,
                config=CircuitBreakerConfig(
                    failure_threshold=5,
                    success_threshold=2,
                    timeout=60.0
                )
            )

            self.logger.debug(f"初始化 Provider: {name}")
            return provider

        except Exception as e:
            self.logger.error(f"初始化 Provider {name} 失败: {e}")
            return None

    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """获取指定 Provider 的断路器"""
        return self._circuit_breakers.get(name)

    def select_provider(
        self,
        task_type: TaskType = TaskType.DEFAULT,
        require_vision: bool = False,
        require_tools: bool = False
    ) -> Optional[BaseProvider]:
        """
        根据任务类型选择 Provider

        Args:
            task_type: 任务类型
            require_vision: 是否需要视觉能力
            require_tools: 是否需要工具调用

        Returns:
            最合适的 Provider
        """
        # 1. 根据任务类型获取推荐的提供商
        task_key = task_type.value if isinstance(task_type, TaskType) else task_type
        recommended = self._task_routing.get(task_key) or self._task_routing.get(TaskType.DEFAULT.value)
        if not recommended:
            recommended = self.config.llm.default_provider

        # 2. 尝试获取推荐的提供商
        provider = self._get_available_provider(recommended, require_vision, require_tools)

        # 3. 如果推荐的不可用，尝试故障转移
        if not provider:
            for fallback_name in self._fallback_order:
                if fallback_name == recommended:
                    continue
                fallback = self._get_available_provider(fallback_name, require_vision, require_tools)
                if fallback:
                    provider = fallback
                    self.logger.info(f"故障转移: {recommended} -> {fallback_name}")
                    break

        return provider

    def _get_available_provider(
        self,
        name: str,
        require_vision: bool = False,
        require_tools: bool = False
    ) -> Optional[BaseProvider]:
        """获取可用的 Provider（检查断路器和能力）"""
        # 检查断路器状态
        breaker = self._circuit_breakers.get(name)
        if breaker and breaker.is_open:
            self.logger.debug(f"Provider {name} 断路器已打开，跳过")
            return None

        provider = self.get_provider(name)
        if not provider:
            return None

        # 检查能力
        caps = provider.get_capabilities()
        if require_vision and not caps.get("supports_vision"):
            return None
        if require_tools and not caps.get("supports_tools"):
            return None

        return provider

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        task_type: Optional[TaskType] = None,
        provider: Optional[str] = None,
        auto_detect: Optional[bool] = None,
        **kwargs
    ) -> LLMResponse:
        """
        聊天（自动选择模型）

        Args:
            messages: 消息列表
            tools: 可用工具
            task_type: 任务类型，None 则自动检测
            provider: 指定提供商名称，None 则自动选择
            auto_detect: 是否自动检测任务类型
            **kwargs: 传递给 Provider 的其他参数

        Returns:
            LLMResponse
        """
        # 自动检测任务类型
        if task_type is None and provider is None:
            should_detect = auto_detect if auto_detect is not None else self._auto_detect_task
            if should_detect:
                # 从最后一条用户消息检测
                user_message = self._get_last_user_message(messages)
                has_image = self._has_image_content(messages)
                detection = detect_task_type(user_message, has_image)
                task_type = detection.task_type
                self.logger.debug(
                    f"任务检测: {task_type.value}, 置信度: {detection.confidence:.2f}"
                )

        if task_type is None:
            task_type = TaskType.DEFAULT

        # 选择 Provider
        if provider:
            llm = self.get_provider(provider)
            if not llm:
                raise ValueError(f"Provider {provider} 不可用")
            provider_name = provider
        else:
            llm = self.select_provider(
                task_type=task_type,
                require_vision=kwargs.get("require_vision", False),
                require_tools=bool(tools)
            )
            if not llm:
                raise ValueError("没有可用的 LLM Provider")
            provider_name = llm.name

        # 通过断路器和重试执行
        breaker = self._circuit_breakers.get(provider_name)
        errors = []

        try:
            if breaker:
                response = breaker.call(
                    lambda: retry_with_backoff(
                        lambda: llm.chat(messages, tools, **kwargs),
                        self._retry_config
                    )
                )
            else:
                response = retry_with_backoff(
                    lambda: llm.chat(messages, tools, **kwargs),
                    self._retry_config
                )

            # 发布事件
            self.event_bus.publish(
                EventType.TOOL_EXECUTED,
                data={
                    "provider": llm.name,
                    "model": llm.model,
                    "task_type": task_type.value if isinstance(task_type, TaskType) else task_type,
                    "usage": response.usage
                },
                source="LLMRouter"
            )

            # 设置 provider 名称
            response.provider = llm.name

            return response

        except CircuitOpenError:
            errors.append((provider_name, "circuit_open"))
        except Exception as e:
            errors.append((provider_name, str(e)))
            self.logger.error(f"LLM 调用失败 ({provider_name}): {e}")

        # 尝试故障转移（只有自动选择时）
        if not provider:
            for fallback_name in self._fallback_order:
                if fallback_name == provider_name:
                    continue

                fallback = self._get_available_provider(
                    fallback_name,
                    require_vision=kwargs.get("require_vision", False),
                    require_tools=bool(tools)
                )
                if not fallback:
                    continue

                fallback_breaker = self._circuit_breakers.get(fallback_name)

                try:
                    self.logger.info(f"故障转移重试: {fallback_name}")

                    if fallback_breaker:
                        response = fallback_breaker.call(
                            lambda: retry_with_backoff(
                                lambda: fallback.chat(messages, tools, **kwargs),
                                self._retry_config
                            )
                        )
                    else:
                        response = fallback.chat(messages, tools, **kwargs)

                    # 标记为降级响应
                    response.raw_response = response.raw_response or {}
                    if isinstance(response.raw_response, dict):
                        response.raw_response["degraded"] = True
                        response.raw_response["original_provider"] = provider_name

                    # 设置 provider 名称
                    response.provider = fallback.name

                    return response

                except Exception as e:
                    errors.append((fallback_name, str(e)))
                    continue

        # 所有尝试都失败
        error_msg = "; ".join([f"{p}: {e}" for p, e in errors])
        raise RuntimeError(f"所有 Provider 调用失败: {error_msg}")

    async def chat_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        task_type: Optional[TaskType] = None,
        provider: Optional[str] = None,
        auto_detect: Optional[bool] = None,
        **kwargs
    ) -> LLMResponse:
        """异步聊天"""
        # 自动检测任务类型
        if task_type is None and provider is None:
            should_detect = auto_detect if auto_detect is not None else self._auto_detect_task
            if should_detect:
                user_message = self._get_last_user_message(messages)
                has_image = self._has_image_content(messages)
                detection = detect_task_type(user_message, has_image)
                task_type = detection.task_type

        if task_type is None:
            task_type = TaskType.DEFAULT

        if provider:
            llm = self.get_provider(provider)
            if not llm:
                raise ValueError(f"Provider {provider} 不可用")
            provider_name = provider
        else:
            llm = self.select_provider(
                task_type=task_type,
                require_vision=kwargs.get("require_vision", False),
                require_tools=bool(tools)
            )
            if not llm:
                raise ValueError("没有可用的 LLM Provider")
            provider_name = llm.name

        breaker = self._circuit_breakers.get(provider_name)

        try:
            if breaker:
                response = await breaker.call_async(
                    lambda: retry_with_backoff_async(
                        lambda: llm.chat_async(messages, tools, **kwargs),
                        self._retry_config
                    )
                )
            else:
                response = await retry_with_backoff_async(
                    lambda: llm.chat_async(messages, tools, **kwargs),
                    self._retry_config
                )

            self.event_bus.publish(
                EventType.TOOL_EXECUTED,
                data={
                    "provider": llm.name,
                    "model": llm.model,
                    "task_type": task_type.value if isinstance(task_type, TaskType) else task_type,
                    "usage": response.usage
                },
                source="LLMRouter"
            )

            # 设置 provider 名称
            response.provider = llm.name

            return response

        except Exception as e:
            self.logger.error(f"LLM 异步调用失败 ({provider_name}): {e}")
            raise

    def _get_last_user_message(self, messages: List[Dict[str, Any]]) -> str:
        """获取最后一条用户消息"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # 多模态消息
                    texts = [p.get("text", "") for p in content if p.get("type") == "text"]
                    return " ".join(texts)
        return ""

    def _has_image_content(self, messages: List[Dict[str, Any]]) -> bool:
        """检查消息是否包含图片"""
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "image_url" or part.get("type") == "image":
                        return True
        return False

    def get_available_providers(self) -> List[str]:
        """获取所有可用的提供商名称"""
        available = []
        for name in PROVIDER_CLASSES.keys():
            provider_config = self.config.get_provider_config(name)
            if provider_config and provider_config.api_key:
                available.append(name)
        return available

    def set_task_routing(self, task_type: TaskType, provider: str) -> None:
        """设置任务路由规则"""
        key = task_type.value if isinstance(task_type, TaskType) else task_type
        self._task_routing[key] = provider

    def get_task_routing(self) -> Dict[str, str]:
        """获取当前任务路由规则"""
        return self._task_routing.copy()

    def set_fallback_order(self, order: List[str]) -> None:
        """设置故障转移顺序"""
        self._fallback_order = order

    def set_retry_config(self, config: RetryConfig) -> None:
        """设置重试配置"""
        self._retry_config = config

    def set_auto_detect(self, enabled: bool) -> None:
        """设置是否启用自动任务检测"""
        self._auto_detect_task = enabled

    def reset_circuit_breakers(self) -> None:
        """重置所有断路器"""
        for breaker in self._circuit_breakers.values():
            breaker.reset()

    def get_health_status(self) -> Dict[str, Any]:
        """获取路由器健康状态"""
        status = {
            "available_providers": self.get_available_providers(),
            "circuit_breakers": {}
        }

        for name, breaker in self._circuit_breakers.items():
            status["circuit_breakers"][name] = {
                "state": breaker.state.value,
                "is_open": breaker.is_open
            }

        return status
