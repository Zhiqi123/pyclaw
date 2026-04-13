"""
容错机制模块测试 - 断路器、重试策略、降级执行器
"""

import pytest
import time
from unittest.mock import Mock, MagicMock

from pyclaw.core.resilience import (
    CircuitBreaker, CircuitBreakerConfig, CircuitState, CircuitOpenError,
    RetryConfig, RetryStrategy, RetryExhaustedError,
    retry, retry_with_backoff,
    FallbackExecutor, FallbackResult, FallbackConfig,
    HealthChecker, HealthCheckResult, HealthStatus,
    is_retryable, calculate_delay
)


class TestCircuitBreaker:
    """断路器测试"""

    def test_initial_state(self):
        """测试初始状态"""
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open

    def test_success_keeps_closed(self):
        """测试成功调用保持关闭状态"""
        breaker = CircuitBreaker("test")
        result = breaker.call(lambda: "success")
        assert result == "success"
        assert breaker.is_closed

    def test_failure_threshold(self):
        """测试失败阈值触发熔断"""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        def failing_op():
            raise Exception("fail")

        # 连续失败 3 次
        for _ in range(3):
            with pytest.raises(Exception):
                breaker.call(failing_op)

        # 应该已熔断
        assert breaker.is_open

    def test_circuit_open_error(self):
        """测试熔断后抛出 CircuitOpenError"""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config)

        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)

        # 熔断后调用应抛出 CircuitOpenError
        with pytest.raises(CircuitOpenError):
            breaker.call(lambda: "test")

    def test_half_open_after_timeout(self):
        """测试超时后进入半开状态"""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=0.1)
        breaker = CircuitBreaker("test", config)

        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)

        assert breaker.is_open

        # 等待超时
        time.sleep(0.15)

        # 下次调用前检查状态会转为半开
        breaker._check_state()
        assert breaker.state == CircuitState.HALF_OPEN

    def test_recovery_from_half_open(self):
        """测试从半开状态恢复"""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=2,
            timeout=0.1
        )
        breaker = CircuitBreaker("test", config)

        # 触发熔断
        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)

        time.sleep(0.15)

        # 连续成功 2 次应恢复
        breaker.call(lambda: "ok")
        breaker.call(lambda: "ok")

        assert breaker.is_closed

    def test_reset(self):
        """测试重置断路器"""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker("test", config)

        with pytest.raises(Exception):
            breaker.call(lambda: 1/0)

        assert breaker.is_open

        breaker.reset()
        assert breaker.is_closed

    def test_force_open(self):
        """测试强制打开断路器"""
        breaker = CircuitBreaker("test")
        breaker.force_open()
        assert breaker.is_open


class TestRetryStrategy:
    """重试策略测试"""

    def test_retry_config_defaults(self):
        """测试默认配置"""
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.strategy == RetryStrategy.EXPONENTIAL_JITTER
        assert config.base_delay == 1.0

    def test_is_retryable(self):
        """测试可重试判断"""
        config = RetryConfig()

        # 普通异常可重试
        assert is_retryable(Exception("test"), config)

        # KeyboardInterrupt 不可重试
        assert not is_retryable(KeyboardInterrupt(), config)

    def test_calculate_delay_fixed(self):
        """测试固定延迟计算"""
        config = RetryConfig(strategy=RetryStrategy.FIXED, base_delay=2.0)
        assert calculate_delay(1, config) == 2.0
        assert calculate_delay(2, config) == 2.0
        assert calculate_delay(3, config) == 2.0

    def test_calculate_delay_exponential(self):
        """测试指数退避延迟计算"""
        config = RetryConfig(strategy=RetryStrategy.EXPONENTIAL, base_delay=1.0)
        assert calculate_delay(1, config) == 1.0
        assert calculate_delay(2, config) == 2.0
        assert calculate_delay(3, config) == 4.0

    def test_calculate_delay_max_limit(self):
        """测试最大延迟限制"""
        config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL,
            base_delay=1.0,
            max_delay=5.0
        )
        # 第 10 次重试理论上是 512 秒，但应被限制为 5 秒
        assert calculate_delay(10, config) == 5.0

    def test_retry_with_backoff_success(self):
        """测试重试成功"""
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("fail")
            return "success"

        config = RetryConfig(max_attempts=3, base_delay=0.01)
        result = retry_with_backoff(operation, config)

        assert result == "success"
        assert call_count == 3

    def test_retry_exhausted(self):
        """测试重试耗尽"""
        def always_fail():
            raise Exception("always fail")

        config = RetryConfig(max_attempts=2, base_delay=0.01)

        with pytest.raises(RetryExhaustedError) as exc_info:
            retry_with_backoff(always_fail, config)

        assert "重试 2 次后仍失败" in str(exc_info.value)

    def test_retry_decorator(self):
        """测试重试装饰器"""
        call_count = 0

        @retry(RetryConfig(max_attempts=3, base_delay=0.01))
        def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("fail")
            return "ok"

        result = flaky_function()
        assert result == "ok"
        assert call_count == 2


class TestFallbackExecutor:
    """降级执行器测试"""

    def test_execute_primary_success(self):
        """测试主服务成功"""
        executor = FallbackExecutor()
        executor.add_provider("primary", "provider1")
        executor.add_provider("backup", "provider2")

        result = executor.execute(lambda p: f"result from {p}")

        assert result.result == "result from provider1"
        assert result.provider == "primary"
        assert not result.degraded

    def test_fallback_on_failure(self):
        """测试故障转移"""
        executor = FallbackExecutor()
        executor.add_provider("primary", "provider1")
        executor.add_provider("backup", "provider2")

        call_count = 0

        def operation(provider):
            nonlocal call_count
            call_count += 1
            if provider == "provider1":
                raise Exception("primary failed")
            return f"result from {provider}"

        result = executor.execute(operation)

        assert result.result == "result from provider2"
        assert result.provider == "backup"
        assert result.degraded
        assert len(result.errors) == 1

    def test_all_providers_fail(self):
        """测试所有服务失败返回静态响应"""
        config = FallbackConfig(static_response="服务不可用")
        executor = FallbackExecutor(config)
        executor.add_provider("p1", "provider1")
        executor.add_provider("p2", "provider2")

        def always_fail(provider):
            raise Exception("fail")

        result = executor.execute(always_fail)

        assert result.result == "服务不可用"
        assert result.provider == "static"
        assert result.degraded
        assert len(result.errors) == 2

    def test_provider_order(self):
        """测试提供商优先级顺序"""
        executor = FallbackExecutor()
        executor.add_provider("low", "provider_low")
        executor.add_provider("high", "provider_high")
        executor.set_provider_order(["high", "low"])

        result = executor.execute(lambda p: p)

        assert result.result == "provider_high"

    def test_circuit_breaker_integration(self):
        """测试断路器集成"""
        executor = FallbackExecutor()
        config = CircuitBreakerConfig(failure_threshold=1)
        executor.add_provider("p1", "provider1", config)
        executor.add_provider("p2", "provider2", config)

        # 让 p1 失败并熔断
        def fail_p1(provider):
            if provider == "provider1":
                raise Exception("fail")
            return "ok"

        executor.execute(fail_p1)

        # p1 应该被熔断，直接使用 p2
        breaker = executor.get_circuit_breaker("p1")
        assert breaker.is_open

    def test_reset_all_breakers(self):
        """测试重置所有断路器"""
        executor = FallbackExecutor()
        config = CircuitBreakerConfig(failure_threshold=1)
        executor.add_provider("p1", "provider1", config)

        # 触发熔断
        try:
            executor.execute(lambda p: 1/0)
        except:
            pass

        executor.reset_all_breakers()
        breaker = executor.get_circuit_breaker("p1")
        assert breaker.is_closed


class TestHealthChecker:
    """健康检查器测试"""

    def test_register_check(self):
        """测试注册检查"""
        checker = HealthChecker()

        def check_db():
            return HealthCheckResult(
                component="database",
                status=HealthStatus.HEALTHY
            )

        checker.register("database", check_db)
        result = checker.check("database")

        assert result.component == "database"
        assert result.status == HealthStatus.HEALTHY

    def test_check_unknown(self):
        """测试检查未注册的组件"""
        checker = HealthChecker()
        result = checker.check("unknown")

        assert result.status == HealthStatus.UNKNOWN
        assert "未注册" in result.message

    def test_check_with_exception(self):
        """测试检查时发生异常"""
        checker = HealthChecker()

        def failing_check():
            raise Exception("check failed")

        checker.register("failing", failing_check)
        result = checker.check("failing")

        assert result.status == HealthStatus.UNHEALTHY
        assert "check failed" in result.message

    def test_check_all(self):
        """测试检查所有组件"""
        checker = HealthChecker()

        checker.register("db", lambda: HealthCheckResult("db", HealthStatus.HEALTHY))
        checker.register("cache", lambda: HealthCheckResult("cache", HealthStatus.DEGRADED))

        results = checker.check_all()

        assert len(results) == 2
        assert results["db"].status == HealthStatus.HEALTHY
        assert results["cache"].status == HealthStatus.DEGRADED

    def test_overall_status_healthy(self):
        """测试整体状态 - 健康"""
        checker = HealthChecker()
        checker.register("a", lambda: HealthCheckResult("a", HealthStatus.HEALTHY))
        checker.register("b", lambda: HealthCheckResult("b", HealthStatus.HEALTHY))
        checker.check_all()

        assert checker.get_overall_status() == HealthStatus.HEALTHY

    def test_overall_status_degraded(self):
        """测试整体状态 - 降级"""
        checker = HealthChecker()
        checker.register("a", lambda: HealthCheckResult("a", HealthStatus.HEALTHY))
        checker.register("b", lambda: HealthCheckResult("b", HealthStatus.DEGRADED))
        checker.check_all()

        assert checker.get_overall_status() == HealthStatus.DEGRADED

    def test_overall_status_unhealthy(self):
        """测试整体状态 - 不健康"""
        checker = HealthChecker()
        checker.register("a", lambda: HealthCheckResult("a", HealthStatus.HEALTHY))
        checker.register("b", lambda: HealthCheckResult("b", HealthStatus.UNHEALTHY))
        checker.check_all()

        assert checker.get_overall_status() == HealthStatus.UNHEALTHY

    def test_latency_measurement(self):
        """测试延迟测量"""
        checker = HealthChecker()

        def slow_check():
            time.sleep(0.05)
            return HealthCheckResult("slow", HealthStatus.HEALTHY)

        checker.register("slow", slow_check)
        result = checker.check("slow")

        assert result.latency_ms >= 50
