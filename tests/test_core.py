"""
阶段0 基础设施层测试
"""

import pytest
import asyncio
from pyclaw.core import EventBus, EventType, Config, setup_logger, get_logger
from pyclaw.core.event_bus import Event


class TestEventBus:
    """EventBus 测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        EventBus.reset()

    def test_singleton(self):
        """测试单例模式"""
        bus1 = EventBus()
        bus2 = EventBus()
        assert bus1 is bus2

    def test_subscribe_and_publish(self):
        """测试订阅和发布"""
        bus = EventBus()
        received = []

        def callback(event: Event):
            received.append(event.data)

        bus.subscribe(EventType.MESSAGE_RECEIVED, callback)
        bus.publish(EventType.MESSAGE_RECEIVED, data="Hello")

        assert len(received) == 1
        assert received[0] == "Hello"

    def test_multiple_subscribers(self):
        """测试多个订阅者"""
        bus = EventBus()
        results = []

        def callback1(event: Event):
            results.append(f"cb1:{event.data}")

        def callback2(event: Event):
            results.append(f"cb2:{event.data}")

        bus.subscribe(EventType.MESSAGE_RECEIVED, callback1)
        bus.subscribe(EventType.MESSAGE_RECEIVED, callback2)
        bus.publish(EventType.MESSAGE_RECEIVED, data="test")

        assert len(results) == 2
        assert "cb1:test" in results
        assert "cb2:test" in results

    def test_unsubscribe(self):
        """测试取消订阅"""
        bus = EventBus()
        received = []

        def callback(event: Event):
            received.append(event.data)

        bus.subscribe(EventType.MESSAGE_RECEIVED, callback)
        bus.publish(EventType.MESSAGE_RECEIVED, data="first")

        bus.unsubscribe(EventType.MESSAGE_RECEIVED, callback)
        bus.publish(EventType.MESSAGE_RECEIVED, data="second")

        assert len(received) == 1
        assert received[0] == "first"

    def test_event_history(self):
        """测试事件历史"""
        bus = EventBus()
        bus.publish(EventType.MESSAGE_RECEIVED, data="msg1")
        bus.publish(EventType.MESSAGE_SENT, data="msg2")
        bus.publish(EventType.MESSAGE_RECEIVED, data="msg3")

        # 获取所有历史
        all_history = bus.get_history()
        assert len(all_history) == 3

        # 按类型筛选
        received_history = bus.get_history(EventType.MESSAGE_RECEIVED)
        assert len(received_history) == 2

    @pytest.mark.asyncio
    async def test_async_publish(self):
        """测试异步发布"""
        bus = EventBus()
        results = []

        async def async_callback(event: Event):
            await asyncio.sleep(0.01)
            results.append(f"async:{event.data}")

        def sync_callback(event: Event):
            results.append(f"sync:{event.data}")

        bus.subscribe(EventType.MESSAGE_RECEIVED, sync_callback)
        bus.subscribe(EventType.MESSAGE_RECEIVED, async_callback, is_async=True)

        await bus.publish_async(EventType.MESSAGE_RECEIVED, data="test")

        assert "sync:test" in results
        assert "async:test" in results


class TestConfig:
    """Config 测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        Config.reset()

    def test_singleton(self):
        """测试单例模式"""
        config1 = Config()
        config2 = Config()
        assert config1 is config2

    def test_default_values(self):
        """测试默认值"""
        config = Config()
        config.load()

        assert config.llm.default_provider == "deepseek"
        assert config.memory.max_context_tokens == 8000
        assert config.log.level == "INFO"

    def test_provider_config(self):
        """测试提供商配置"""
        config = Config()
        config.load()

        deepseek = config.get_provider_config("deepseek")
        assert deepseek is not None
        assert deepseek.model == "deepseek-chat"

    def test_expand_path(self):
        """测试路径展开"""
        config = Config()
        config.load()

        skills_dir = config.skills_dir
        assert "~" not in skills_dir


class TestLogger:
    """Logger 测试"""

    def test_setup_logger(self):
        """测试日志设置"""
        logger = setup_logger("test_logger", level="DEBUG", console_output=True)
        assert logger is not None
        assert logger.level == 10  # DEBUG

    def test_get_logger(self):
        """测试获取 logger"""
        setup_logger("pyclaw", level="INFO")
        logger = get_logger("pyclaw.test")
        assert logger is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
