"""
事件总线 - PyClaw 核心通信机制

实现各模块间的松耦合通信，支持同步和异步事件处理。
"""

import asyncio
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """事件类型枚举"""
    # 消息相关
    MESSAGE_RECEIVED = auto()    # 收到用户消息
    MESSAGE_SENT = auto()        # 发送响应消息
    MESSAGE_SAVED = auto()       # 消息已保存

    # 工具/技能相关
    TOOL_EXECUTED = auto()       # 工具执行完成
    SKILL_LOADED = auto()        # 技能加载完成
    SKILL_MATCHED = auto()       # 技能匹配成功

    # 记忆相关
    MEMORY_UPDATED = auto()      # 记忆存储更新
    CONTEXT_LOADED = auto()      # 上下文加载完成

    # 会话相关
    SESSION_STARTED = auto()     # 会话开始
    SESSION_ENDED = auto()       # 会话结束

    # 调度相关
    HEARTBEAT_TRIGGERED = auto() # 心跳触发
    TASK_SCHEDULED = auto()      # 任务已调度
    TASK_COMPLETED = auto()      # 任务完成
    TASK_FAILED = auto()         # 任务失败

    # 系统相关
    ERROR_OCCURRED = auto()      # 错误发生
    CONFIG_UPDATED = auto()      # 配置更新
    SYSTEM_STARTUP = auto()      # 系统启动
    SYSTEM_SHUTDOWN = auto()     # 系统关闭


@dataclass
class Event:
    """事件数据类"""
    type: EventType
    data: Any = None
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


# 回调函数类型
SyncCallback = Callable[[Event], None]
AsyncCallback = Callable[[Event], Any]  # 返回 Coroutine
Callback = Union[SyncCallback, AsyncCallback]


class EventBus:
    """
    事件总线

    实现发布/订阅模式，支持同步和异步事件处理。

    使用示例:
        bus = EventBus()

        # 订阅事件
        def on_message(event: Event):
            print(f"收到消息: {event.data}")

        bus.subscribe(EventType.MESSAGE_RECEIVED, on_message)

        # 发布事件
        bus.publish(EventType.MESSAGE_RECEIVED, data="Hello")
    """

    _instance: Optional["EventBus"] = None

    def __new__(cls) -> "EventBus":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._subscribers: Dict[EventType, List[Callback]] = {}
        self._async_subscribers: Dict[EventType, List[AsyncCallback]] = {}
        self._event_history: List[Event] = []
        self._max_history = 1000
        self._initialized = True
        logger.debug("EventBus 初始化完成")

    def subscribe(
        self,
        event_type: EventType,
        callback: Callback,
        is_async: bool = False
    ) -> None:
        """
        订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数
            is_async: 是否为异步回调
        """
        if is_async:
            if event_type not in self._async_subscribers:
                self._async_subscribers[event_type] = []
            self._async_subscribers[event_type].append(callback)
        else:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)

        logger.debug(f"订阅事件: {event_type.name}, async={is_async}")

    def unsubscribe(
        self,
        event_type: EventType,
        callback: Callback,
        is_async: bool = False
    ) -> bool:
        """
        取消订阅

        Returns:
            是否成功取消
        """
        subscribers = self._async_subscribers if is_async else self._subscribers
        if event_type in subscribers and callback in subscribers[event_type]:
            subscribers[event_type].remove(callback)
            logger.debug(f"取消订阅: {event_type.name}")
            return True
        return False

    def publish(
        self,
        event_type: EventType,
        data: Any = None,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Event:
        """
        发布事件（同步）

        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件来源
            metadata: 元数据

        Returns:
            创建的事件对象
        """
        event = Event(
            type=event_type,
            data=data,
            source=source,
            metadata=metadata or {}
        )

        # 记录历史
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

        # 通知同步订阅者
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"事件处理错误 [{event_type.name}]: {e}")
                    self._publish_error(e, event)

        logger.debug(f"发布事件: {event_type.name}, data={data}")
        return event

    async def publish_async(
        self,
        event_type: EventType,
        data: Any = None,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Event:
        """
        发布事件（异步）

        同时通知同步和异步订阅者
        """
        # 先同步发布
        event = self.publish(event_type, data, source, metadata)

        # 再通知异步订阅者
        if event_type in self._async_subscribers:
            tasks = []
            for callback in self._async_subscribers[event_type]:
                tasks.append(asyncio.create_task(self._safe_async_call(callback, event)))
            if tasks:
                await asyncio.gather(*tasks)

        return event

    async def _safe_async_call(self, callback: AsyncCallback, event: Event) -> None:
        """安全调用异步回调"""
        try:
            await callback(event)
        except Exception as e:
            logger.error(f"异步事件处理错误 [{event.type.name}]: {e}")
            self._publish_error(e, event)

    def _publish_error(self, error: Exception, source_event: Optional[Event] = None) -> None:
        """发布错误事件"""
        if source_event and source_event.type == EventType.ERROR_OCCURRED:
            return  # 避免无限循环

        error_data = {
            "error": str(error),
            "error_type": type(error).__name__,
            "source_event": source_event.type.name if source_event else None
        }

        # 直接通知，不递归
        if EventType.ERROR_OCCURRED in self._subscribers:
            error_event = Event(
                type=EventType.ERROR_OCCURRED,
                data=error_data,
                source="EventBus"
            )
            for callback in self._subscribers[EventType.ERROR_OCCURRED]:
                try:
                    callback(error_event)
                except Exception:
                    pass  # 忽略错误处理中的错误

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100
    ) -> List[Event]:
        """
        获取事件历史

        Args:
            event_type: 筛选特定类型，None 表示全部
            limit: 返回数量限制
        """
        if event_type:
            events = [e for e in self._event_history if e.type == event_type]
        else:
            events = self._event_history
        return events[-limit:]

    def clear_history(self) -> None:
        """清空事件历史"""
        self._event_history.clear()
        logger.debug("事件历史已清空")

    @classmethod
    def reset(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None
