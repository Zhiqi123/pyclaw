"""
PyClaw 通道模块
"""

from .base import (
    BaseChannel,
    ChannelType,
    ChannelStatus,
    IncomingMessage,
    OutgoingMessage
)
from .security import (
    ChannelCapability,
    ChannelCapabilityInfo,
    DmPolicy,
    DmPolicyConfig,
    DmSecurityManager,
    PairingSession,
    MessageFilter,
    create_length_filter,
    create_length_validator,
    create_keyword_filter,
    create_empty_validator
)
from .manager import ChannelManager
from .imessage import IMessageChannel
from .wechat import WeChatChannel
from .wechat_mac import WeChatMacChannel

__all__ = [
    # 基类
    "BaseChannel",
    "ChannelType",
    "ChannelStatus",
    "IncomingMessage",
    "OutgoingMessage",
    # 能力声明
    "ChannelCapability",
    "ChannelCapabilityInfo",
    # DM 安全策略
    "DmPolicy",
    "DmPolicyConfig",
    "DmSecurityManager",
    "PairingSession",
    # 消息过滤
    "MessageFilter",
    "create_length_filter",
    "create_length_validator",
    "create_keyword_filter",
    "create_empty_validator",
    # 管理器
    "ChannelManager",
    # 具体实现
    "IMessageChannel",
    "WeChatChannel",
    "WeChatMacChannel"  # Mac 客户端版本（无需网页版）
]
