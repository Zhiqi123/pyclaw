"""
容错机制模块 - 断路器、重试策略、降级执行器

提供系统级的容错能力，确保服务稳定性。
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ============== 断路器 (Circuit Breaker) ==============

class CircuitState(Enum):
    """断路器状态"""
    CLOSED = "closed"      # 正常状态，请求正常通过
    OPEN = "open"          # 熔断状态，快速失败
    HALF_OPEN = "half_open"  # 半开状态，允许探测请求


@dataclass
class CircuitBreakerConfig:
    """断路器配置"""
    failure_threshold: int = 5       # 连续失败次数触发熔断
    success_threshold: int = 2       # 连续成功次数恢复
    timeout: float = 60.0            # 熔断冷却时间(秒)
    half_open_requests: int = 3      # 半开状态允许的探测请求数


class CircuitBreaker:
    """
    断路器

    实现断路器模式，防止级联故障。

    使用示例:
        breaker = CircuitBreaker(name="claude")

        try:
            result = breaker.call(lambda: api_call())
        except CircuitOpenError:
            # 服务熔断中
            pass
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        """当前状态"""
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    def call(self, operation: Callable[[], T]) -> T:
        """
        通过断路器执行操作

        Args:
            operation: 要执行的操作

        Returns:
            操作结果

        Raises:
            CircuitOpenError: 断路器打开时
        """
        self._check_state()

        if self._state == CircuitState.OPEN:
            raise CircuitOpenError(f"断路器 {self.name} 已熔断")

        try:
            result = operation()
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    async def call_async(self, operation: Callable[[], T]) -> T:
        """异步版本"""
        self._check_state()

        if self._state == CircuitState.OPEN:
            raise CircuitOpenError(f"断路器 {self.name} 已熔断")

        try:
            if asyncio.iscoroutinefunction(operation):
                result = await operation()
            else:
                result = operation()
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _check_state(self) -> None:
        """检查并更新状态"""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time is None:
                return

            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.config.timeout:
                self._transition_to(CircuitState.HALF_OPEN)
                self._half_open_calls = 0
                self._success_count = 0

    def _on_success(self) -> None:
        """成功回调"""
        self._failure_count = 0

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

    def _on_failure(self) -> None:
        """失败回调"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
        elif self._failure_count >= self.config.failure_threshold:
            self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """状态转换"""
        old_state = self._state
        self._state = new_state
        logger.info(f"断路器 {self.name}: {old_state.value} -> {new_state.value}")

    def reset(self) -> None:
        """重置断路器"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        logger.info(f"断路器 {self.name} 已重置")

    def force_open(self) -> None:
        """强制打开断路器"""
        self._transition_to(CircuitState.OPEN)
        self._last_failure_time = time.time()


class CircuitOpenError(Exception):
    """断路器打开异常"""
    pass


# ============== 重试策略 (Retry Strategy) ==============

class RetryStrategy(Enum):
    """重试策略类型"""
    FIXED = "fixed"                          # 固定间隔
    EXPONENTIAL = "exponential"              # 指数退避
    EXPONENTIAL_JITTER = "exponential_jitter"  # 指数退避+抖动


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3                    # 最大重试次数
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_JITTER
    base_delay: float = 1.0                  # 基础延迟(秒)
    max_delay: float = 30.0                  # 最大延迟(秒)
    jitter_factor: float = 0.5              # 抖动因子 (0-1)
    retryable_exceptions: tuple = (Exception,)  # 可重试的异常类型
    respect_retry_after: bool = True         # 是否遵循 Retry-After 头


# 不可重试的异常
NON_RETRYABLE_EXCEPTIONS = (
    KeyboardInterrupt,
    SystemExit,
    MemoryError,
)


def is_retryable(error: Exception, config: RetryConfig) -> bool:
    """判断异常是否可重试"""
    if isinstance(error, NON_RETRYABLE_EXCEPTIONS):
        return False

    # 检查 HTTP 状态码
    status_code = getattr(error, 'status_code', None)
    if status_code:
        # 4xx 客户端错误通常不可重试 (除了 429)
        if 400 <= status_code < 500 and status_code != 429:
            return False

    return isinstance(error, config.retryable_exceptions)


def calculate_delay(attempt: int, config: RetryConfig, error: Optional[Exception] = None) -> float:
    """计算重试延迟"""
    # 优先使用服务端指定的延迟
    if config.respect_retry_after and error:
        retry_after = getattr(error, 'retry_after', None)
        if retry_after:
            return float(retry_after)

    if config.strategy == RetryStrategy.FIXED:
        delay = config.base_delay

    elif config.strategy == RetryStrategy.EXPONENTIAL:
        delay = config.base_delay * (2 ** (attempt - 1))

    else:  # EXPONENTIAL_JITTER
        delay = config.base_delay * (2 ** (attempt - 1))
        jitter = random.uniform(1 - config.jitter_factor, 1 + config.jitter_factor)
        delay = delay * jitter

    return min(delay, config.max_delay)


def retry(config: Optional[RetryConfig] = None):
    """
    重试装饰器

    使用示例:
        @retry(RetryConfig(max_attempts=3))
        def api_call():
            ...
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e

                    if not is_retryable(e, config):
                        logger.debug(f"不可重试错误: {e}")
                        raise

                    if attempt == config.max_attempts:
                        logger.warning(f"重试次数耗尽: {attempt}/{config.max_attempts}")
                        break

                    delay = calculate_delay(attempt, config, e)
                    logger.info(f"重试 {attempt}/{config.max_attempts}, 等待 {delay:.2f}s")
                    time.sleep(delay)

            raise RetryExhaustedError(f"重试 {config.max_attempts} 次后仍失败", last_error)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    if asyncio.iscoroutinefunction(func):
                        return await func(*args, **kwargs)
                    else:
                        return func(*args, **kwargs)
                except Exception as e:
                    last_error = e

                    if not is_retryable(e, config):
                        raise

                    if attempt == config.max_attempts:
                        break

                    delay = calculate_delay(attempt, config, e)
                    logger.info(f"异步重试 {attempt}/{config.max_attempts}, 等待 {delay:.2f}s")
                    await asyncio.sleep(delay)

            raise RetryExhaustedError(f"重试 {config.max_attempts} 次后仍失败", last_error)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def retry_with_backoff(
    operation: Callable[[], T],
    config: Optional[RetryConfig] = None
) -> T:
    """
    带退避的重试执行

    Args:
        operation: 要执行的操作
        config: 重试配置

    Returns:
        操作结果
    """
    if config is None:
        config = RetryConfig()

    last_error = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return operation()
        except Exception as e:
            last_error = e

            if not is_retryable(e, config):
                raise

            if attempt == config.max_attempts:
                break

            delay = calculate_delay(attempt, config, e)
            logger.info(f"重试 {attempt}/{config.max_attempts}, 等待 {delay:.2f}s")
            time.sleep(delay)

    raise RetryExhaustedError(f"重试 {config.max_attempts} 次后仍失败", last_error)


async def retry_with_backoff_async(
    operation: Callable[[], T],
    config: Optional[RetryConfig] = None
) -> T:
    """异步版本的重试执行"""
    if config is None:
        config = RetryConfig()

    last_error = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            if asyncio.iscoroutinefunction(operation):
                return await operation()
            else:
                return operation()
        except Exception as e:
            last_error = e

            if not is_retryable(e, config):
                raise

            if attempt == config.max_attempts:
                break

            delay = calculate_delay(attempt, config, e)
            await asyncio.sleep(delay)

    raise RetryExhaustedError(f"重试 {config.max_attempts} 次后仍失败", last_error)


class RetryExhaustedError(Exception):
    """重试耗尽异常"""
    def __init__(self, message: str, last_error: Optional[Exception] = None):
        super().__init__(message)
        self.last_error = last_error


# ============== 降级执行器 (Fallback Executor) ==============

@dataclass
class FallbackResult:
    """降级执行结果"""
    result: Any
    provider: str
    degraded: bool = False
    errors: List[tuple] = field(default_factory=list)


@dataclass
class FallbackConfig:
    """降级配置"""
    enable_cache: bool = True
    cache_ttl: int = 3600  # 缓存有效期(秒)
    static_response: str = "服务暂时不可用，请稍后再试。"


class FallbackExecutor:
    """
    降级执行器

    实现多层降级策略，确保服务可用性。

    使用示例:
        executor = FallbackExecutor()
        executor.add_provider("claude", claude_provider)
        executor.add_provider("deepseek", deepseek_provider)

        result = executor.execute(request)
    """

    def __init__(self, config: Optional[FallbackConfig] = None):
        self.config = config or FallbackConfig()
        self._providers: Dict[str, Any] = {}
        self._provider_order: List[str] = []
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._cache: Dict[str, tuple] = {}  # key -> (result, timestamp)

    def add_provider(
        self,
        name: str,
        provider: Any,
        circuit_config: Optional[CircuitBreakerConfig] = None
    ) -> None:
        """添加提供商"""
        self._providers[name] = provider
        if name not in self._provider_order:
            self._provider_order.append(name)
        self._circuit_breakers[name] = CircuitBreaker(name, circuit_config)

    def set_provider_order(self, order: List[str]) -> None:
        """设置提供商优先级顺序"""
        self._provider_order = [p for p in order if p in self._providers]

    def execute(
        self,
        operation: Callable[[Any], T],
        cache_key: Optional[str] = None,
        retry_config: Optional[RetryConfig] = None
    ) -> FallbackResult:
        """
        执行操作（带降级）

        Args:
            operation: 操作函数，接收 provider 作为参数
            cache_key: 缓存键
            retry_config: 重试配置

        Returns:
            FallbackResult
        """
        errors = []

        for i, provider_name in enumerate(self._provider_order):
            provider = self._providers[provider_name]
            breaker = self._circuit_breakers[provider_name]

            # 跳过已熔断的服务
            if breaker.is_open:
                logger.debug(f"跳过熔断服务: {provider_name}")
                continue

            try:
                # 通过断路器执行
                if retry_config:
                    result = breaker.call(
                        lambda: retry_with_backoff(
                            lambda: operation(provider),
                            retry_config
                        )
                    )
                else:
                    result = breaker.call(lambda: operation(provider))

                # 成功，缓存结果
                if self.config.enable_cache and cache_key:
                    self._cache[cache_key] = (result, time.time())

                return FallbackResult(
                    result=result,
                    provider=provider_name,
                    degraded=(i > 0),
                    errors=errors
                )

            except CircuitOpenError:
                errors.append((provider_name, "circuit_open"))
                continue

            except Exception as e:
                errors.append((provider_name, str(e)))
                logger.warning(f"服务失败: {provider_name}, 错误: {e}")
                continue

        # 所有服务失败，尝试缓存
        if self.config.enable_cache and cache_key and cache_key in self._cache:
            cached_result, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self.config.cache_ttl:
                logger.info("使用缓存响应")
                return FallbackResult(
                    result=cached_result,
                    provider="cache",
                    degraded=True,
                    errors=errors
                )

        # 返回静态响应
        logger.warning("所有服务不可用，返回静态响应")
        return FallbackResult(
            result=self.config.static_response,
            provider="static",
            degraded=True,
            errors=errors
        )

    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """获取指定服务的断路器"""
        return self._circuit_breakers.get(name)

    def reset_all_breakers(self) -> None:
        """重置所有断路器"""
        for breaker in self._circuit_breakers.values():
            breaker.reset()


# ============== 健康检查 ==============

class HealthStatus(Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    component: str
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0
    details: Dict[str, Any] = field(default_factory=dict)


class HealthChecker:
    """
    健康检查器

    定期检查各组件健康状态。
    """

    def __init__(self, check_interval: float = 30.0):
        self.check_interval = check_interval
        self._checks: Dict[str, Callable[[], HealthCheckResult]] = {}
        self._results: Dict[str, HealthCheckResult] = {}
        self._running = False

    def register(self, name: str, check_func: Callable[[], HealthCheckResult]) -> None:
        """注册健康检查"""
        self._checks[name] = check_func

    def check(self, name: str) -> HealthCheckResult:
        """执行单个检查"""
        if name not in self._checks:
            return HealthCheckResult(
                component=name,
                status=HealthStatus.UNKNOWN,
                message="检查未注册"
            )

        start_time = time.time()
        try:
            result = self._checks[name]()
            result.latency_ms = (time.time() - start_time) * 1000
            self._results[name] = result
            return result
        except Exception as e:
            result = HealthCheckResult(
                component=name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            self._results[name] = result
            return result

    def check_all(self) -> Dict[str, HealthCheckResult]:
        """执行所有检查"""
        for name in self._checks:
            self.check(name)
        return self._results.copy()

    def get_overall_status(self) -> HealthStatus:
        """获取整体健康状态"""
        if not self._results:
            return HealthStatus.UNKNOWN

        statuses = [r.status for r in self._results.values()]

        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.UNKNOWN

    def get_result(self, name: str) -> Optional[HealthCheckResult]:
        """获取指定组件的检查结果"""
        return self._results.get(name)
