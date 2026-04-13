"""
通道安全模块 - DM 安全策略和访问控制

提供多层次的消息访问控制机制，保护系统安全。
"""

import logging
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, Flag, auto
from typing import Any, Callable, Dict, List, Optional, Set
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ============== 通道能力声明 (Channel Capabilities) ==============

class ChannelCapability(Flag):
    """
    通道能力标志

    使用位标志表示通道支持的功能。

    使用示例:
        caps = ChannelCapability.TEXT | ChannelCapability.IMAGE
        if ChannelCapability.TEXT in caps:
            print("支持文本")
    """
    NONE = 0
    TEXT = auto()           # 文本消息
    IMAGE = auto()          # 图片消息
    AUDIO = auto()          # 音频消息
    VIDEO = auto()          # 视频消息
    FILE = auto()           # 文件传输
    REACTION = auto()       # 表情回应
    REPLY = auto()          # 消息回复
    EDIT = auto()           # 消息编辑
    DELETE = auto()         # 消息删除
    TYPING = auto()         # 输入状态
    READ_RECEIPT = auto()   # 已读回执
    MENTION = auto()        # @提及
    RICH_TEXT = auto()      # 富文本/Markdown
    STICKER = auto()        # 贴纸
    LOCATION = auto()       # 位置分享

    # 常用组合
    BASIC = TEXT
    STANDARD = TEXT | IMAGE | FILE | REPLY
    FULL = TEXT | IMAGE | AUDIO | VIDEO | FILE | REACTION | REPLY | EDIT | DELETE


@dataclass
class ChannelCapabilityInfo:
    """通道能力详细信息"""
    capabilities: ChannelCapability
    max_text_length: int = 4096          # 最大文本长度
    max_file_size: int = 10 * 1024 * 1024  # 最大文件大小 (10MB)
    supported_image_types: List[str] = field(default_factory=lambda: ["jpg", "png", "gif"])
    supported_audio_types: List[str] = field(default_factory=lambda: ["mp3", "wav", "m4a"])
    supported_video_types: List[str] = field(default_factory=lambda: ["mp4", "mov"])
    rate_limit: int = 30                  # 每分钟消息数限制
    extra: Dict[str, Any] = field(default_factory=dict)

    def supports(self, capability: ChannelCapability) -> bool:
        """检查是否支持指定能力"""
        return capability in self.capabilities

    def supports_all(self, capabilities: ChannelCapability) -> bool:
        """检查是否支持所有指定能力"""
        return (self.capabilities & capabilities) == capabilities

    def supports_any(self, capabilities: ChannelCapability) -> bool:
        """检查是否支持任一指定能力"""
        return bool(self.capabilities & capabilities)


# ============== DM 安全策略 (DM Policy) ==============

class DmPolicy(Enum):
    """
    DM 安全策略

    控制谁可以与系统进行私信交互。

    - DISABLED: 完全禁用 DM 功能
    - PAIRING: 需要配对码验证
    - ALLOWLIST: 仅允许白名单用户
    - OPEN: 开放给所有人（不推荐）
    """
    DISABLED = "disabled"      # 禁用 DM
    PAIRING = "pairing"        # 配对模式
    ALLOWLIST = "allowlist"    # 白名单模式
    OPEN = "open"              # 开放模式


@dataclass
class PairingSession:
    """配对会话"""
    code: str                           # 配对码
    user_id: str                        # 用户 ID
    channel_type: str                   # 通道类型
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    verified: bool = False
    attempts: int = 0                   # 尝试次数

    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(minutes=5)

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        return datetime.now() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """是否有效（未过期且未超过尝试次数）"""
        return not self.is_expired and self.attempts < 5


@dataclass
class DmPolicyConfig:
    """DM 策略配置"""
    policy: DmPolicy = DmPolicy.ALLOWLIST
    allowlist: Set[str] = field(default_factory=set)      # 白名单用户 ID
    blocklist: Set[str] = field(default_factory=set)      # 黑名单用户 ID
    pairing_code_length: int = 6                          # 配对码长度
    pairing_expiry_minutes: int = 5                       # 配对码有效期
    max_pairing_attempts: int = 5                         # 最大配对尝试次数
    rate_limit_per_minute: int = 10                       # 每分钟消息限制
    require_verification: bool = False                    # 是否需要额外验证


class DmSecurityManager:
    """
    DM 安全管理器

    管理 DM 访问控制、配对验证和速率限制。

    使用示例:
        manager = DmSecurityManager(DmPolicyConfig(policy=DmPolicy.PAIRING))

        # 生成配对码
        code = manager.generate_pairing_code("user123", "imessage")

        # 验证配对
        if manager.verify_pairing("user123", "imessage", "123456"):
            print("配对成功")

        # 检查访问权限
        if manager.check_access("user123", "imessage"):
            print("允许访问")
    """

    def __init__(self, config: Optional[DmPolicyConfig] = None):
        self.config = config or DmPolicyConfig()
        self._pairing_sessions: Dict[str, PairingSession] = {}
        self._verified_users: Dict[str, datetime] = {}  # user_key -> verified_time
        self._rate_limits: Dict[str, List[float]] = {}  # user_key -> timestamps
        self._on_pairing_success: Optional[Callable[[str, str], None]] = None

    def _user_key(self, user_id: str, channel_type: str) -> str:
        """生成用户唯一键"""
        return f"{channel_type}:{user_id}"

    def check_access(self, user_id: str, channel_type: str) -> bool:
        """
        检查用户是否有访问权限

        Args:
            user_id: 用户 ID
            channel_type: 通道类型

        Returns:
            是否允许访问
        """
        user_key = self._user_key(user_id, channel_type)

        # 检查黑名单
        if user_id in self.config.blocklist:
            logger.debug(f"用户 {user_id} 在黑名单中")
            return False

        # 根据策略检查
        if self.config.policy == DmPolicy.DISABLED:
            return False

        elif self.config.policy == DmPolicy.OPEN:
            return True

        elif self.config.policy == DmPolicy.ALLOWLIST:
            return user_id in self.config.allowlist

        elif self.config.policy == DmPolicy.PAIRING:
            # 检查是否已验证
            if user_key in self._verified_users:
                return True
            # 检查白名单（预授权用户）
            if user_id in self.config.allowlist:
                return True
            return False

        return False

    def check_rate_limit(self, user_id: str, channel_type: str) -> bool:
        """
        检查速率限制

        Args:
            user_id: 用户 ID
            channel_type: 通道类型

        Returns:
            是否在限制内（True 表示允许）
        """
        user_key = self._user_key(user_id, channel_type)
        now = time.time()
        window_start = now - 60  # 1 分钟窗口

        # 获取或创建时间戳列表
        if user_key not in self._rate_limits:
            self._rate_limits[user_key] = []

        # 清理过期记录
        self._rate_limits[user_key] = [
            ts for ts in self._rate_limits[user_key] if ts > window_start
        ]

        # 检查是否超限
        if len(self._rate_limits[user_key]) >= self.config.rate_limit_per_minute:
            logger.warning(f"用户 {user_id} 触发速率限制")
            return False

        # 记录本次请求
        self._rate_limits[user_key].append(now)
        return True

    def generate_pairing_code(self, user_id: str, channel_type: str) -> str:
        """
        生成配对码

        Args:
            user_id: 用户 ID
            channel_type: 通道类型

        Returns:
            配对码
        """
        import random
        import string

        # 生成随机配对码
        code = ''.join(
            random.choices(string.digits, k=self.config.pairing_code_length)
        )

        user_key = self._user_key(user_id, channel_type)

        # 创建配对会话
        session = PairingSession(
            code=code,
            user_id=user_id,
            channel_type=channel_type,
            expires_at=datetime.now() + timedelta(minutes=self.config.pairing_expiry_minutes)
        )
        self._pairing_sessions[user_key] = session

        logger.info(f"为用户 {user_id} 生成配对码（有效期 {self.config.pairing_expiry_minutes} 分钟）")
        return code

    def verify_pairing(self, user_id: str, channel_type: str, code: str) -> bool:
        """
        验证配对码

        Args:
            user_id: 用户 ID
            channel_type: 通道类型
            code: 配对码

        Returns:
            是否验证成功
        """
        user_key = self._user_key(user_id, channel_type)

        session = self._pairing_sessions.get(user_key)
        if not session:
            logger.debug(f"用户 {user_id} 无配对会话")
            return False

        # 增加尝试次数
        session.attempts += 1

        # 检查有效性
        if not session.is_valid:
            logger.warning(f"用户 {user_id} 配对会话无效（过期或超过尝试次数）")
            del self._pairing_sessions[user_key]
            return False

        # 验证配对码
        if session.code != code:
            logger.debug(f"用户 {user_id} 配对码错误（尝试 {session.attempts}/{self.config.max_pairing_attempts}）")
            return False

        # 验证成功
        session.verified = True
        self._verified_users[user_key] = datetime.now()
        del self._pairing_sessions[user_key]

        logger.info(f"用户 {user_id} 配对成功")

        # 触发回调
        if self._on_pairing_success:
            try:
                self._on_pairing_success(user_id, channel_type)
            except Exception as e:
                logger.error(f"配对成功回调执行失败: {e}")

        return True

    def revoke_access(self, user_id: str, channel_type: str) -> None:
        """
        撤销用户访问权限

        Args:
            user_id: 用户 ID
            channel_type: 通道类型
        """
        user_key = self._user_key(user_id, channel_type)

        if user_key in self._verified_users:
            del self._verified_users[user_key]
            logger.info(f"已撤销用户 {user_id} 的访问权限")

        if user_key in self._pairing_sessions:
            del self._pairing_sessions[user_key]

    def add_to_allowlist(self, user_id: str) -> None:
        """添加用户到白名单"""
        self.config.allowlist.add(user_id)
        logger.info(f"用户 {user_id} 已添加到白名单")

    def remove_from_allowlist(self, user_id: str) -> None:
        """从白名单移除用户"""
        self.config.allowlist.discard(user_id)
        logger.info(f"用户 {user_id} 已从白名单移除")

    def add_to_blocklist(self, user_id: str) -> None:
        """添加用户到黑名单"""
        self.config.blocklist.add(user_id)
        # 同时撤销所有通道的访问权限
        keys_to_remove = [k for k in self._verified_users if k.endswith(f":{user_id}")]
        for key in keys_to_remove:
            del self._verified_users[key]
        logger.info(f"用户 {user_id} 已添加到黑名单")

    def remove_from_blocklist(self, user_id: str) -> None:
        """从黑名单移除用户"""
        self.config.blocklist.discard(user_id)
        logger.info(f"用户 {user_id} 已从黑名单移除")

    def set_policy(self, policy: DmPolicy) -> None:
        """设置 DM 策略"""
        old_policy = self.config.policy
        self.config.policy = policy
        logger.info(f"DM 策略变更: {old_policy.value} -> {policy.value}")

    def set_on_pairing_success(self, callback: Callable[[str, str], None]) -> None:
        """设置配对成功回调"""
        self._on_pairing_success = callback

    def get_pending_pairings(self) -> List[PairingSession]:
        """获取待处理的配对会话"""
        return [
            session for session in self._pairing_sessions.values()
            if session.is_valid and not session.verified
        ]

    def get_verified_users(self) -> Dict[str, datetime]:
        """获取已验证用户列表"""
        return self._verified_users.copy()

    def cleanup_expired(self) -> int:
        """
        清理过期的配对会话

        Returns:
            清理的会话数量
        """
        expired_keys = [
            key for key, session in self._pairing_sessions.items()
            if session.is_expired
        ]
        for key in expired_keys:
            del self._pairing_sessions[key]

        if expired_keys:
            logger.debug(f"清理了 {len(expired_keys)} 个过期配对会话")

        return len(expired_keys)

    def get_status(self) -> Dict[str, Any]:
        """获取安全管理器状态"""
        return {
            "policy": self.config.policy.value,
            "allowlist_count": len(self.config.allowlist),
            "blocklist_count": len(self.config.blocklist),
            "verified_users_count": len(self._verified_users),
            "pending_pairings_count": len(self._pairing_sessions),
            "rate_limit_per_minute": self.config.rate_limit_per_minute
        }


# ============== 消息过滤器 ==============

class MessageFilter:
    """
    消息过滤器

    对消息进行安全过滤和预处理。
    """

    def __init__(self):
        self._filters: List[Callable[[str], str]] = []
        self._validators: List[Callable[[str], bool]] = []

    def add_filter(self, filter_func: Callable[[str], str]) -> None:
        """添加过滤函数"""
        self._filters.append(filter_func)

    def add_validator(self, validator_func: Callable[[str], bool]) -> None:
        """添加验证函数"""
        self._validators.append(validator_func)

    def filter(self, content: str) -> str:
        """
        过滤消息内容

        Args:
            content: 原始内容

        Returns:
            过滤后的内容
        """
        result = content
        for filter_func in self._filters:
            try:
                result = filter_func(result)
            except Exception as e:
                logger.error(f"消息过滤失败: {e}")
        return result

    def validate(self, content: str) -> bool:
        """
        验证消息内容

        Args:
            content: 消息内容

        Returns:
            是否通过验证
        """
        for validator_func in self._validators:
            try:
                if not validator_func(content):
                    return False
            except Exception as e:
                logger.error(f"消息验证失败: {e}")
                return False
        return True


# ============== 预置过滤器 ==============

def create_length_filter(max_length: int) -> Callable[[str], str]:
    """创建长度限制过滤器"""
    def filter_func(content: str) -> str:
        if len(content) > max_length:
            return content[:max_length] + "..."
        return content
    return filter_func


def create_length_validator(max_length: int) -> Callable[[str], bool]:
    """创建长度验证器"""
    def validator_func(content: str) -> bool:
        return len(content) <= max_length
    return validator_func


def create_keyword_filter(keywords: List[str], replacement: str = "***") -> Callable[[str], str]:
    """创建关键词过滤器"""
    def filter_func(content: str) -> str:
        result = content
        for keyword in keywords:
            result = result.replace(keyword, replacement)
        return result
    return filter_func


def create_empty_validator() -> Callable[[str], bool]:
    """创建非空验证器"""
    def validator_func(content: str) -> bool:
        return bool(content and content.strip())
    return validator_func
