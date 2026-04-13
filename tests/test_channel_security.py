"""
通道安全模块测试 - DM 安全策略和通道能力
"""

import pytest
import time
from datetime import datetime, timedelta

from pyclaw.channels.security import (
    ChannelCapability, ChannelCapabilityInfo,
    DmPolicy, DmPolicyConfig, DmSecurityManager,
    PairingSession, MessageFilter,
    create_length_filter, create_length_validator,
    create_keyword_filter, create_empty_validator
)


class TestChannelCapability:
    """通道能力测试"""

    def test_basic_capabilities(self):
        """测试基本能力"""
        caps = ChannelCapability.TEXT | ChannelCapability.IMAGE

        assert ChannelCapability.TEXT in caps
        assert ChannelCapability.IMAGE in caps
        assert ChannelCapability.AUDIO not in caps

    def test_capability_combinations(self):
        """测试能力组合"""
        assert ChannelCapability.BASIC == ChannelCapability.TEXT
        assert ChannelCapability.TEXT in ChannelCapability.STANDARD
        assert ChannelCapability.IMAGE in ChannelCapability.STANDARD

    def test_full_capabilities(self):
        """测试完整能力"""
        full = ChannelCapability.FULL

        assert ChannelCapability.TEXT in full
        assert ChannelCapability.IMAGE in full
        assert ChannelCapability.AUDIO in full
        assert ChannelCapability.VIDEO in full


class TestChannelCapabilityInfo:
    """通道能力信息测试"""

    def test_create_info(self):
        """测试创建能力信息"""
        info = ChannelCapabilityInfo(
            capabilities=ChannelCapability.TEXT | ChannelCapability.IMAGE,
            max_text_length=2000
        )

        assert info.max_text_length == 2000
        assert info.supports(ChannelCapability.TEXT)
        assert info.supports(ChannelCapability.IMAGE)

    def test_supports_all(self):
        """测试支持所有能力"""
        info = ChannelCapabilityInfo(
            capabilities=ChannelCapability.TEXT | ChannelCapability.IMAGE | ChannelCapability.FILE
        )

        assert info.supports_all(ChannelCapability.TEXT | ChannelCapability.IMAGE)
        assert not info.supports_all(ChannelCapability.TEXT | ChannelCapability.AUDIO)

    def test_supports_any(self):
        """测试支持任一能力"""
        info = ChannelCapabilityInfo(
            capabilities=ChannelCapability.TEXT
        )

        assert info.supports_any(ChannelCapability.TEXT | ChannelCapability.IMAGE)
        assert not info.supports_any(ChannelCapability.AUDIO | ChannelCapability.VIDEO)

    def test_default_values(self):
        """测试默认值"""
        info = ChannelCapabilityInfo(capabilities=ChannelCapability.TEXT)

        assert info.max_text_length == 4096
        assert info.max_file_size == 10 * 1024 * 1024
        assert "jpg" in info.supported_image_types
        assert info.rate_limit == 30


class TestDmPolicy:
    """DM 策略枚举测试"""

    def test_values(self):
        """测试枚举值"""
        assert DmPolicy.DISABLED.value == "disabled"
        assert DmPolicy.PAIRING.value == "pairing"
        assert DmPolicy.ALLOWLIST.value == "allowlist"
        assert DmPolicy.OPEN.value == "open"


class TestPairingSession:
    """配对会话测试"""

    def test_create_session(self):
        """测试创建会话"""
        session = PairingSession(
            code="123456",
            user_id="user1",
            channel_type="imessage"
        )

        assert session.code == "123456"
        assert session.user_id == "user1"
        assert not session.verified
        assert session.attempts == 0

    def test_expiry(self):
        """测试过期"""
        session = PairingSession(
            code="123456",
            user_id="user1",
            channel_type="imessage",
            expires_at=datetime.now() - timedelta(minutes=1)
        )

        assert session.is_expired
        assert not session.is_valid

    def test_max_attempts(self):
        """测试最大尝试次数"""
        session = PairingSession(
            code="123456",
            user_id="user1",
            channel_type="imessage"
        )

        session.attempts = 5
        assert not session.is_valid


class TestDmSecurityManager:
    """DM 安全管理器测试"""

    def test_disabled_policy(self):
        """测试禁用策略"""
        config = DmPolicyConfig(policy=DmPolicy.DISABLED)
        manager = DmSecurityManager(config)

        assert not manager.check_access("user1", "imessage")

    def test_open_policy(self):
        """测试开放策略"""
        config = DmPolicyConfig(policy=DmPolicy.OPEN)
        manager = DmSecurityManager(config)

        assert manager.check_access("user1", "imessage")
        assert manager.check_access("user2", "wechat")

    def test_allowlist_policy(self):
        """测试白名单策略"""
        config = DmPolicyConfig(
            policy=DmPolicy.ALLOWLIST,
            allowlist={"user1", "user2"}
        )
        manager = DmSecurityManager(config)

        assert manager.check_access("user1", "imessage")
        assert manager.check_access("user2", "imessage")
        assert not manager.check_access("user3", "imessage")

    def test_blocklist(self):
        """测试黑名单"""
        config = DmPolicyConfig(
            policy=DmPolicy.OPEN,
            blocklist={"blocked_user"}
        )
        manager = DmSecurityManager(config)

        assert manager.check_access("normal_user", "imessage")
        assert not manager.check_access("blocked_user", "imessage")

    def test_pairing_flow(self):
        """测试配对流程"""
        config = DmPolicyConfig(policy=DmPolicy.PAIRING)
        manager = DmSecurityManager(config)

        # 未配对用户无权限
        assert not manager.check_access("user1", "imessage")

        # 生成配对码
        code = manager.generate_pairing_code("user1", "imessage")
        assert len(code) == 6

        # 验证配对码
        assert manager.verify_pairing("user1", "imessage", code)

        # 配对后有权限
        assert manager.check_access("user1", "imessage")

    def test_pairing_wrong_code(self):
        """测试错误配对码"""
        config = DmPolicyConfig(policy=DmPolicy.PAIRING)
        manager = DmSecurityManager(config)

        manager.generate_pairing_code("user1", "imessage")

        assert not manager.verify_pairing("user1", "imessage", "000000")

    def test_pairing_no_session(self):
        """测试无配对会话"""
        config = DmPolicyConfig(policy=DmPolicy.PAIRING)
        manager = DmSecurityManager(config)

        assert not manager.verify_pairing("user1", "imessage", "123456")

    def test_rate_limit(self):
        """测试速率限制"""
        config = DmPolicyConfig(
            policy=DmPolicy.OPEN,
            rate_limit_per_minute=3
        )
        manager = DmSecurityManager(config)

        # 前 3 次应该通过
        assert manager.check_rate_limit("user1", "imessage")
        assert manager.check_rate_limit("user1", "imessage")
        assert manager.check_rate_limit("user1", "imessage")

        # 第 4 次应该被限制
        assert not manager.check_rate_limit("user1", "imessage")

    def test_add_to_allowlist(self):
        """测试添加到白名单"""
        config = DmPolicyConfig(policy=DmPolicy.ALLOWLIST)
        manager = DmSecurityManager(config)

        assert not manager.check_access("user1", "imessage")

        manager.add_to_allowlist("user1")
        assert manager.check_access("user1", "imessage")

    def test_remove_from_allowlist(self):
        """测试从白名单移除"""
        config = DmPolicyConfig(
            policy=DmPolicy.ALLOWLIST,
            allowlist={"user1"}
        )
        manager = DmSecurityManager(config)

        assert manager.check_access("user1", "imessage")

        manager.remove_from_allowlist("user1")
        assert not manager.check_access("user1", "imessage")

    def test_add_to_blocklist(self):
        """测试添加到黑名单"""
        config = DmPolicyConfig(policy=DmPolicy.OPEN)
        manager = DmSecurityManager(config)

        assert manager.check_access("user1", "imessage")

        manager.add_to_blocklist("user1")
        assert not manager.check_access("user1", "imessage")

    def test_revoke_access(self):
        """测试撤销访问权限"""
        config = DmPolicyConfig(policy=DmPolicy.PAIRING)
        manager = DmSecurityManager(config)

        # 配对
        code = manager.generate_pairing_code("user1", "imessage")
        manager.verify_pairing("user1", "imessage", code)
        assert manager.check_access("user1", "imessage")

        # 撤销
        manager.revoke_access("user1", "imessage")
        assert not manager.check_access("user1", "imessage")

    def test_set_policy(self):
        """测试设置策略"""
        config = DmPolicyConfig(policy=DmPolicy.DISABLED)
        manager = DmSecurityManager(config)

        assert not manager.check_access("user1", "imessage")

        manager.set_policy(DmPolicy.OPEN)
        assert manager.check_access("user1", "imessage")

    def test_get_status(self):
        """测试获取状态"""
        config = DmPolicyConfig(
            policy=DmPolicy.ALLOWLIST,
            allowlist={"user1", "user2"},
            blocklist={"blocked"}
        )
        manager = DmSecurityManager(config)

        status = manager.get_status()

        assert status["policy"] == "allowlist"
        assert status["allowlist_count"] == 2
        assert status["blocklist_count"] == 1

    def test_cleanup_expired(self):
        """测试清理过期会话"""
        config = DmPolicyConfig(
            policy=DmPolicy.PAIRING,
            pairing_expiry_minutes=0  # 立即过期
        )
        manager = DmSecurityManager(config)

        manager.generate_pairing_code("user1", "imessage")

        # 等待过期
        time.sleep(0.1)

        cleaned = manager.cleanup_expired()
        assert cleaned == 1

    def test_pairing_callback(self):
        """测试配对成功回调"""
        config = DmPolicyConfig(policy=DmPolicy.PAIRING)
        manager = DmSecurityManager(config)

        callback_called = []

        def on_success(user_id, channel_type):
            callback_called.append((user_id, channel_type))

        manager.set_on_pairing_success(on_success)

        code = manager.generate_pairing_code("user1", "imessage")
        manager.verify_pairing("user1", "imessage", code)

        assert len(callback_called) == 1
        assert callback_called[0] == ("user1", "imessage")


class TestMessageFilter:
    """消息过滤器测试"""

    def test_add_filter(self):
        """测试添加过滤器"""
        filter = MessageFilter()
        filter.add_filter(lambda s: s.upper())

        result = filter.filter("hello")
        assert result == "HELLO"

    def test_multiple_filters(self):
        """测试多个过滤器"""
        filter = MessageFilter()
        filter.add_filter(lambda s: s.strip())
        filter.add_filter(lambda s: s.upper())

        result = filter.filter("  hello  ")
        assert result == "HELLO"

    def test_add_validator(self):
        """测试添加验证器"""
        filter = MessageFilter()
        filter.add_validator(lambda s: len(s) > 0)

        assert filter.validate("hello")
        assert not filter.validate("")

    def test_multiple_validators(self):
        """测试多个验证器"""
        filter = MessageFilter()
        filter.add_validator(lambda s: len(s) > 0)
        filter.add_validator(lambda s: len(s) < 100)

        assert filter.validate("hello")
        assert not filter.validate("")
        assert not filter.validate("x" * 200)


class TestPresetFilters:
    """预置过滤器测试"""

    def test_length_filter(self):
        """测试长度过滤器"""
        filter_func = create_length_filter(10)

        assert filter_func("hello") == "hello"
        assert filter_func("hello world!") == "hello worl..."

    def test_length_validator(self):
        """测试长度验证器"""
        validator = create_length_validator(10)

        assert validator("hello")
        assert not validator("hello world!")

    def test_keyword_filter(self):
        """测试关键词过滤器"""
        filter_func = create_keyword_filter(["敏感词", "bad"])

        assert filter_func("这是敏感词测试") == "这是***测试"
        assert filter_func("this is bad") == "this is ***"

    def test_empty_validator(self):
        """测试非空验证器"""
        validator = create_empty_validator()

        assert validator("hello")
        assert not validator("")
        assert not validator("   ")
