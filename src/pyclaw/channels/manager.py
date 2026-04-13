"""
通道管理器 - 统一管理多个通道
"""

import logging
from typing import Callable, Dict, List, Optional
from datetime import datetime

from .base import (
    BaseChannel, ChannelType, ChannelStatus,
    IncomingMessage, OutgoingMessage
)
from ..core.logger import LoggerMixin
from ..core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)


class ChannelManager(LoggerMixin):
    """
    通道管理器

    统一管理多个消息通道，提供：
    - 通道注册/注销
    - 统一的消息路由
    - 通道状态监控

    使用示例:
        manager = ChannelManager()
        manager.register(imessage_channel)
        manager.register(wechat_channel)
        manager.set_on_message(handle_all_messages)
        manager.connect_all()
        manager.start_all()
    """

    def __init__(self):
        """初始化管理器"""
        self._channels: Dict[ChannelType, BaseChannel] = {}
        self._on_message: Optional[Callable[[IncomingMessage], None]] = None
        self._event_bus = EventBus()

    def register(self, channel: BaseChannel) -> None:
        """
        注册通道

        Args:
            channel: 通道实例
        """
        channel_type = channel.channel_type

        if channel_type in self._channels:
            self.logger.warning(f"通道 {channel_type.value} 已存在，将被替换")

        # 设置消息回调
        channel.set_on_message(self._route_message)

        self._channels[channel_type] = channel
        self.logger.info(f"注册通道: {channel_type.value}")

    def unregister(self, channel_type: ChannelType) -> bool:
        """
        注销通道

        Args:
            channel_type: 通道类型

        Returns:
            是否注销成功
        """
        if channel_type not in self._channels:
            return False

        channel = self._channels.pop(channel_type)
        channel.disconnect()
        self.logger.info(f"注销通道: {channel_type.value}")
        return True

    def get(self, channel_type: ChannelType) -> Optional[BaseChannel]:
        """获取通道"""
        return self._channels.get(channel_type)

    def set_on_message(self, callback: Callable[[IncomingMessage], None]) -> None:
        """
        设置统一的消息回调

        Args:
            callback: 回调函数
        """
        self._on_message = callback

    def _route_message(self, message: IncomingMessage) -> None:
        """路由消息到统一回调"""
        if self._on_message:
            try:
                self._on_message(message)
            except Exception as e:
                self.logger.error(f"消息路由失败: {e}")

    def connect(self, channel_type: ChannelType) -> bool:
        """
        连接指定通道

        Args:
            channel_type: 通道类型

        Returns:
            是否连接成功
        """
        channel = self._channels.get(channel_type)
        if not channel:
            self.logger.error(f"通道不存在: {channel_type.value}")
            return False

        return channel.connect()

    def connect_all(self) -> Dict[ChannelType, bool]:
        """
        连接所有通道

        Returns:
            各通道连接结果
        """
        results = {}
        for channel_type, channel in self._channels.items():
            results[channel_type] = channel.connect()
        return results

    def disconnect(self, channel_type: ChannelType) -> None:
        """断开指定通道"""
        channel = self._channels.get(channel_type)
        if channel:
            channel.disconnect()

    def disconnect_all(self) -> None:
        """断开所有通道"""
        for channel in self._channels.values():
            channel.disconnect()

    def start(self, channel_type: ChannelType) -> None:
        """开始监听指定通道"""
        channel = self._channels.get(channel_type)
        if channel and channel.is_connected:
            channel.start_listening()

    def start_all(self) -> None:
        """开始监听所有已连接的通道"""
        for channel in self._channels.values():
            if channel.is_connected:
                channel.start_listening()

    def stop(self, channel_type: ChannelType) -> None:
        """停止监听指定通道"""
        channel = self._channels.get(channel_type)
        if channel:
            channel.stop_listening()

    def stop_all(self) -> None:
        """停止监听所有通道"""
        for channel in self._channels.values():
            channel.stop_listening()

    def send(
        self,
        channel_type: ChannelType,
        channel_id: str,
        content: str,
        reply_to: Optional[str] = None
    ) -> bool:
        """
        通过指定通道发送消息

        Args:
            channel_type: 通道类型
            channel_id: 通道 ID
            content: 消息内容
            reply_to: 回复的消息 ID

        Returns:
            是否发送成功
        """
        channel = self._channels.get(channel_type)
        if not channel:
            self.logger.error(f"通道不存在: {channel_type.value}")
            return False

        if not channel.is_connected:
            self.logger.error(f"通道未连接: {channel_type.value}")
            return False

        return channel.send_text(channel_id, content, reply_to)

    def reply(self, message: IncomingMessage, content: str) -> bool:
        """
        回复消息

        Args:
            message: 原消息
            content: 回复内容

        Returns:
            是否发送成功
        """
        return self.send(
            channel_type=message.channel_type,
            channel_id=message.channel_id,
            content=content,
            reply_to=message.id
        )

    def get_status(self) -> Dict[ChannelType, ChannelStatus]:
        """获取所有通道状态"""
        return {
            channel_type: channel.status
            for channel_type, channel in self._channels.items()
        }

    def list_channels(self) -> List[ChannelType]:
        """列出所有注册的通道"""
        return list(self._channels.keys())

    @property
    def connected_channels(self) -> List[ChannelType]:
        """获取已连接的通道列表"""
        return [
            channel_type
            for channel_type, channel in self._channels.items()
            if channel.is_connected
        ]
