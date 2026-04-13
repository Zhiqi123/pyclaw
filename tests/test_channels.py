"""
阶段5 通道接入层测试
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from pyclaw.channels import (
    BaseChannel, ChannelType, ChannelStatus,
    IncomingMessage, OutgoingMessage,
    ChannelManager, IMessageChannel, WeChatChannel,
    DmPolicy, DmPolicyConfig
)


class TestIncomingMessage:
    """IncomingMessage 测试"""

    def test_create_message(self):
        """测试创建消息"""
        msg = IncomingMessage(
            id="msg_001",
            channel_type=ChannelType.IMESSAGE,
            channel_id="chat_001",
            sender_id="user_001",
            sender_name="张三",
            content="你好"
        )

        assert msg.id == "msg_001"
        assert msg.channel_type == ChannelType.IMESSAGE
        assert msg.sender_name == "张三"
        assert msg.content == "你好"

    def test_default_values(self):
        """测试默认值"""
        msg = IncomingMessage(
            id="msg_001",
            channel_type=ChannelType.CLI,
            channel_id="cli",
            sender_id="user"
        )

        assert msg.sender_name == ""
        assert msg.content == ""
        assert msg.reply_to is None
        assert msg.attachments == []
        assert msg.metadata == {}


class TestOutgoingMessage:
    """OutgoingMessage 测试"""

    def test_create_message(self):
        """测试创建消息"""
        msg = OutgoingMessage(
            channel_type=ChannelType.WECHAT,
            channel_id="chat_001",
            content="回复内容"
        )

        assert msg.channel_type == ChannelType.WECHAT
        assert msg.channel_id == "chat_001"
        assert msg.content == "回复内容"


class MockChannel(BaseChannel):
    """测试用的 Mock 通道"""

    def __init__(self):
        # 使用 OPEN 策略，允许所有消息通过
        dm_config = DmPolicyConfig(policy=DmPolicy.OPEN)
        super().__init__(ChannelType.CLI, dm_config=dm_config)
        self._connected = False
        self._listening = False
        self._sent_messages = []

    def connect(self) -> bool:
        self._connected = True
        self._set_status(ChannelStatus.CONNECTED)
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._set_status(ChannelStatus.DISCONNECTED)

    def send(self, message: OutgoingMessage) -> bool:
        if not self._connected:
            return False
        self._sent_messages.append(message)
        return True

    def start_listening(self) -> None:
        self._listening = True

    def stop_listening(self) -> None:
        self._listening = False

    def simulate_message(self, content: str, sender_id: str = "test_user"):
        """模拟接收消息"""
        msg = IncomingMessage(
            id=f"msg_{len(self._sent_messages)}",
            channel_type=self._channel_type,
            channel_id="test_channel",
            sender_id=sender_id,
            content=content
        )
        self._emit_message(msg)


class TestBaseChannel:
    """BaseChannel 测试"""

    def test_channel_type(self):
        """测试通道类型"""
        channel = MockChannel()
        assert channel.channel_type == ChannelType.CLI

    def test_initial_status(self):
        """测试初始状态"""
        channel = MockChannel()
        assert channel.status == ChannelStatus.DISCONNECTED
        assert not channel.is_connected

    def test_connect(self):
        """测试连接"""
        channel = MockChannel()
        assert channel.connect()
        assert channel.is_connected
        assert channel.status == ChannelStatus.CONNECTED

    def test_disconnect(self):
        """测试断开连接"""
        channel = MockChannel()
        channel.connect()
        channel.disconnect()
        assert not channel.is_connected
        assert channel.status == ChannelStatus.DISCONNECTED

    def test_send_message(self):
        """测试发送消息"""
        channel = MockChannel()
        channel.connect()

        msg = OutgoingMessage(
            channel_type=ChannelType.CLI,
            channel_id="test",
            content="测试消息"
        )
        assert channel.send(msg)
        assert len(channel._sent_messages) == 1

    def test_send_without_connect(self):
        """测试未连接时发送"""
        channel = MockChannel()
        msg = OutgoingMessage(
            channel_type=ChannelType.CLI,
            channel_id="test",
            content="测试消息"
        )
        assert not channel.send(msg)

    def test_send_text(self):
        """测试发送文本便捷方法"""
        channel = MockChannel()
        channel.connect()

        assert channel.send_text("channel_001", "你好")
        assert channel._sent_messages[0].content == "你好"

    def test_message_callback(self):
        """测试消息回调"""
        channel = MockChannel()
        received = []

        def on_message(msg):
            received.append(msg)

        channel.set_on_message(on_message)
        channel.connect()
        channel.simulate_message("测试消息")

        assert len(received) == 1
        assert received[0].content == "测试消息"


class TestChannelManager:
    """ChannelManager 测试"""

    def test_register_channel(self):
        """测试注册通道"""
        manager = ChannelManager()
        channel = MockChannel()

        manager.register(channel)
        assert manager.get(ChannelType.CLI) is not None

    def test_unregister_channel(self):
        """测试注销通道"""
        manager = ChannelManager()
        channel = MockChannel()

        manager.register(channel)
        assert manager.unregister(ChannelType.CLI)
        assert manager.get(ChannelType.CLI) is None

    def test_connect_all(self):
        """测试连接所有通道"""
        manager = ChannelManager()
        channel1 = MockChannel()
        channel2 = MockChannel()
        channel2._channel_type = ChannelType.API

        manager.register(channel1)
        manager.register(channel2)

        results = manager.connect_all()
        assert results[ChannelType.CLI] is True
        assert results[ChannelType.API] is True

    def test_disconnect_all(self):
        """测试断开所有通道"""
        manager = ChannelManager()
        channel = MockChannel()

        manager.register(channel)
        manager.connect_all()
        manager.disconnect_all()

        assert not channel.is_connected

    def test_start_stop_all(self):
        """测试启动/停止所有通道"""
        manager = ChannelManager()
        channel = MockChannel()

        manager.register(channel)
        manager.connect_all()
        manager.start_all()

        assert channel._listening

        manager.stop_all()
        assert not channel._listening

    def test_send_message(self):
        """测试通过管理器发送消息"""
        manager = ChannelManager()
        channel = MockChannel()

        manager.register(channel)
        manager.connect_all()

        assert manager.send(ChannelType.CLI, "channel_001", "测试消息")
        assert len(channel._sent_messages) == 1

    def test_send_to_nonexistent_channel(self):
        """测试发送到不存在的通道"""
        manager = ChannelManager()
        assert not manager.send(ChannelType.IMESSAGE, "channel_001", "测试")

    def test_reply(self):
        """测试回复消息"""
        manager = ChannelManager()
        channel = MockChannel()

        manager.register(channel)
        manager.connect_all()

        incoming = IncomingMessage(
            id="msg_001",
            channel_type=ChannelType.CLI,
            channel_id="channel_001",
            sender_id="user_001",
            content="原消息"
        )

        assert manager.reply(incoming, "回复内容")
        assert channel._sent_messages[0].content == "回复内容"
        assert channel._sent_messages[0].reply_to == "msg_001"

    def test_unified_message_callback(self):
        """测试统一消息回调"""
        manager = ChannelManager()
        channel = MockChannel()
        received = []

        def on_message(msg):
            received.append(msg)

        manager.register(channel)
        manager.set_on_message(on_message)
        manager.connect_all()

        channel.simulate_message("测试消息")

        assert len(received) == 1
        assert received[0].content == "测试消息"

    def test_get_status(self):
        """测试获取状态"""
        manager = ChannelManager()
        channel = MockChannel()

        manager.register(channel)
        status = manager.get_status()

        assert status[ChannelType.CLI] == ChannelStatus.DISCONNECTED

        manager.connect_all()
        status = manager.get_status()
        assert status[ChannelType.CLI] == ChannelStatus.CONNECTED

    def test_list_channels(self):
        """测试列出通道"""
        manager = ChannelManager()
        channel1 = MockChannel()
        channel2 = MockChannel()
        channel2._channel_type = ChannelType.API

        manager.register(channel1)
        manager.register(channel2)

        channels = manager.list_channels()
        assert ChannelType.CLI in channels
        assert ChannelType.API in channels

    def test_connected_channels(self):
        """测试获取已连接通道"""
        manager = ChannelManager()
        channel1 = MockChannel()
        channel2 = MockChannel()
        channel2._channel_type = ChannelType.API

        manager.register(channel1)
        manager.register(channel2)

        # 只连接一个
        manager.connect(ChannelType.CLI)

        connected = manager.connected_channels
        assert ChannelType.CLI in connected
        assert ChannelType.API not in connected


class TestIMessageChannel:
    """IMessageChannel 测试"""

    def test_channel_type(self):
        """测试通道类型"""
        channel = IMessageChannel()
        assert channel.channel_type == ChannelType.IMESSAGE

    def test_config(self):
        """测试配置"""
        channel = IMessageChannel(config={
            "poll_interval": 5.0,
            "allowed_senders": ["+1234567890"]
        })
        assert channel._poll_interval == 5.0
        assert "+1234567890" in channel._allowed_senders

    @patch('platform.system')
    def test_connect_non_macos(self, mock_system):
        """测试非 macOS 环境连接"""
        mock_system.return_value = "Linux"
        channel = IMessageChannel()
        assert not channel.connect()
        assert channel.status == ChannelStatus.ERROR


class TestWeChatChannel:
    """WeChatChannel 测试"""

    def test_channel_type(self):
        """测试通道类型"""
        channel = WeChatChannel()
        assert channel.channel_type == ChannelType.WECHAT

    def test_config(self):
        """测试配置"""
        channel = WeChatChannel(config={
            "hot_reload": False,
            "allowed_users": ["user1", "user2"]
        })
        assert channel._hot_reload is False
        assert "user1" in channel._allowed_users

    def test_connect_without_itchat(self):
        """测试未安装 itchat 时连接"""
        with patch.dict('sys.modules', {'itchat': None}):
            channel = WeChatChannel()
            # 由于 import 会失败，这里模拟
            channel._itchat = None
            # connect 会尝试 import，失败后返回 False


class TestChannelType:
    """ChannelType 枚举测试"""

    def test_values(self):
        """测试枚举值"""
        assert ChannelType.IMESSAGE.value == "imessage"
        assert ChannelType.WECHAT.value == "wechat"
        assert ChannelType.TELEGRAM.value == "telegram"
        assert ChannelType.CLI.value == "cli"
        assert ChannelType.API.value == "api"


class TestChannelStatus:
    """ChannelStatus 枚举测试"""

    def test_values(self):
        """测试枚举值"""
        assert ChannelStatus.DISCONNECTED.value == "disconnected"
        assert ChannelStatus.CONNECTING.value == "connecting"
        assert ChannelStatus.CONNECTED.value == "connected"
        assert ChannelStatus.ERROR.value == "error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
