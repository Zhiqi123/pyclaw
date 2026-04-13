"""
通道基类 - 定义消息通道接口
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum
from datetime import datetime

from ..core.logger import LoggerMixin
from ..core.event_bus import EventBus, EventType
from .security import (
    ChannelCapability, ChannelCapabilityInfo,
    DmPolicy, DmPolicyConfig, DmSecurityManager
)

logger = logging.getLogger(__name__)


class ChannelType(Enum):
    """通道类型"""
    IMESSAGE = "imessage"
    WECHAT = "wechat"
    TELEGRAM = "telegram"
    CLI = "cli"
    API = "api"


class ChannelStatus(Enum):
    """通道状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class IncomingMessage:
    """接收到的消息"""
    id: str                          # 消息 ID
    channel_type: ChannelType        # 通道类型
    channel_id: str                  # 通道 ID（如聊天 ID）
    sender_id: str                   # 发送者 ID
    sender_name: str = ""            # 发送者名称
    content: str = ""                # 消息内容
    timestamp: datetime = field(default_factory=datetime.now)
    reply_to: Optional[str] = None   # 回复的消息 ID
    attachments: List[Dict] = field(default_factory=list)  # 附件
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """发送的消息"""
    channel_type: ChannelType
    channel_id: str
    content: str
    reply_to: Optional[str] = None
    attachments: List[Dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseChannel(ABC, LoggerMixin):
    """
    通道基类

    定义消息通道的标准接口，所有通道适配器需要继承此类。

    使用示例:
        class MyChannel(BaseChannel):
            def connect(self): ...
            def disconnect(self): ...
            def send(self, message): ...
            def start_listening(self): ...

            @property
            def capabilities(self) -> ChannelCapabilityInfo:
                return ChannelCapabilityInfo(
                    capabilities=ChannelCapability.TEXT | ChannelCapability.IMAGE
                )
    """

    def __init__(
        self,
        channel_type: ChannelType,
        config: Optional[Dict] = None,
        dm_config: Optional[DmPolicyConfig] = None
    ):
        """
        初始化通道

        Args:
            channel_type: 通道类型
            config: 通道配置
            dm_config: DM 安全策略配置
        """
        self._channel_type = channel_type
        self._config = config or {}
        self._status = ChannelStatus.DISCONNECTED
        self._event_bus = EventBus()

        # 消息处理回调
        self._on_message: Optional[Callable[[IncomingMessage], None]] = None

        # DM 安全管理器
        self._security_manager = DmSecurityManager(dm_config)

    @property
    def channel_type(self) -> ChannelType:
        """通道类型"""
        return self._channel_type

    @property
    def status(self) -> ChannelStatus:
        """通道状态"""
        return self._status

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._status == ChannelStatus.CONNECTED

    @property
    def security_manager(self) -> DmSecurityManager:
        """获取安全管理器"""
        return self._security_manager

    @property
    def capabilities(self) -> ChannelCapabilityInfo:
        """
        获取通道能力信息

        子类应重写此属性以声明支持的能力。
        默认仅支持文本消息。
        """
        return ChannelCapabilityInfo(capabilities=ChannelCapability.TEXT)

    def supports(self, capability: ChannelCapability) -> bool:
        """检查是否支持指定能力"""
        return self.capabilities.supports(capability)

    def set_on_message(self, callback: Callable[[IncomingMessage], None]) -> None:
        """
        设置消息接收回调

        Args:
            callback: 回调函数，接收 IncomingMessage 参数
        """
        self._on_message = callback

    def _emit_message(self, message: IncomingMessage) -> None:
        """
        触发消息事件

        Args:
            message: 接收到的消息
        """
        # 安全检查：访问权限
        if not self._security_manager.check_access(message.sender_id, self._channel_type.value):
            self.logger.debug(f"用户 {message.sender_id} 无访问权限，消息被拒绝")
            print(f"[安全检查] 用户 {message.sender_id} 无访问权限，消息被拒绝")
            return

        # 安全检查：速率限制
        if not self._security_manager.check_rate_limit(message.sender_id, self._channel_type.value):
            self.logger.warning(f"用户 {message.sender_id} 触发速率限制")
            print(f"[安全检查] 用户 {message.sender_id} 触发速率限制")
            return

        print(f"[安全检查] 通过，调用回调处理消息")
        if self._on_message:
            try:
                self._on_message(message)
            except Exception as e:
                self.logger.error(f"消息回调执行失败: {e}")
                print(f"[回调错误] {e}")
                import traceback
                traceback.print_exc()

        # 发布事件
        self._event_bus.publish(
            EventType.MESSAGE_RECEIVED,
            data={
                "channel_type": self._channel_type.value,
                "channel_id": message.channel_id,
                "sender_id": message.sender_id,
                "content": message.content
            },
            source=f"Channel:{self._channel_type.value}"
        )

    def _emit_message_bypass_security(self, message: IncomingMessage) -> None:
        """
        触发消息事件（绕过安全检查）

        用于配对消息等特殊场景。

        Args:
            message: 接收到的消息
        """
        if self._on_message:
            try:
                self._on_message(message)
            except Exception as e:
                self.logger.error(f"消息回调执行失败: {e}")

        self._event_bus.publish(
            EventType.MESSAGE_RECEIVED,
            data={
                "channel_type": self._channel_type.value,
                "channel_id": message.channel_id,
                "sender_id": message.sender_id,
                "content": message.content
            },
            source=f"Channel:{self._channel_type.value}"
        )

    def _set_status(self, status: ChannelStatus) -> None:
        """更新状态"""
        old_status = self._status
        self._status = status

        if old_status != status:
            self.logger.info(f"通道状态变更: {old_status.value} -> {status.value}")

    @abstractmethod
    def connect(self) -> bool:
        """
        连接通道

        Returns:
            是否连接成功
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    def send(self, message: OutgoingMessage) -> bool:
        """
        发送消息

        Args:
            message: 要发送的消息

        Returns:
            是否发送成功
        """
        pass

    @abstractmethod
    def start_listening(self) -> None:
        """开始监听消息"""
        pass

    @abstractmethod
    def stop_listening(self) -> None:
        """停止监听消息"""
        pass

    def send_text(self, channel_id: str, content: str, reply_to: Optional[str] = None) -> bool:
        """
        发送文本消息的便捷方法

        Args:
            channel_id: 通道 ID
            content: 消息内容
            reply_to: 回复的消息 ID

        Returns:
            是否发送成功
        """
        message = OutgoingMessage(
            channel_type=self._channel_type,
            channel_id=channel_id,
            content=content,
            reply_to=reply_to
        )
        return self.send(message)
