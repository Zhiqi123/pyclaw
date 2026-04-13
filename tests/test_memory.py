"""
阶段1 数据存储层测试
"""

import pytest
import tempfile
from pathlib import Path

from pyclaw.memory import Database, MemoryManager, Conversation, Message, MessageRole
from pyclaw.core import EventBus, Config


class TestDatabase:
    """Database 测试"""

    def setup_method(self):
        """每个测试创建临时数据库"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.db = Database(str(self.db_path))
        self.db.initialize()

    def test_initialize(self):
        """测试数据库初始化"""
        assert self.db_path.exists()

    def test_create_conversation(self):
        """测试创建对话"""
        conv_id = self.db.create_conversation(
            channel="imessage",
            channel_id="+1234567890",
            title="测试对话"
        )
        assert conv_id > 0

        conv = self.db.get_conversation(conv_id)
        assert conv is not None
        assert conv["channel"] == "imessage"
        assert conv["title"] == "测试对话"

    def test_add_message(self):
        """测试添加消息"""
        conv_id = self.db.create_conversation()
        msg_id = self.db.add_message(
            conversation_id=conv_id,
            role="user",
            content="你好"
        )
        assert msg_id > 0

        messages = self.db.get_messages(conv_id)
        assert len(messages) == 1
        assert messages[0]["content"] == "你好"

    def test_get_recent_messages(self):
        """测试获取最近消息"""
        conv_id = self.db.create_conversation()

        # 添加多条消息
        for i in range(10):
            self.db.add_message(conv_id, "user", f"消息 {i}")

        # 获取最近 5 条（按 ID 倒序取最新的5条，然后正序返回）
        messages = self.db.get_recent_messages(conv_id, limit=5)
        assert len(messages) == 5
        # 验证返回的是最后插入的5条消息，按正序排列
        assert messages[0]["content"] == "消息 5"  # 最早的
        assert messages[4]["content"] == "消息 9"  # 最新的

    def test_conversation_by_channel(self):
        """测试按通道获取对话"""
        self.db.create_conversation(channel="imessage", channel_id="user1")
        self.db.create_conversation(channel="imessage", channel_id="user2")

        conv = self.db.get_conversation_by_channel("imessage", "user1")
        assert conv is not None
        assert conv["channel_id"] == "user1"

    def test_delete_conversation(self):
        """测试删除对话（级联删除消息）"""
        conv_id = self.db.create_conversation()
        self.db.add_message(conv_id, "user", "测试消息")

        self.db.delete_conversation(conv_id)

        assert self.db.get_conversation(conv_id) is None
        assert len(self.db.get_messages(conv_id)) == 0

    def test_facts(self):
        """测试事实存储"""
        fact_id = self.db.add_fact(
            content="用户喜欢咖啡",
            category="preference"
        )
        assert fact_id > 0

        facts = self.db.search_facts(category="preference")
        assert len(facts) == 1
        assert facts[0]["content"] == "用户喜欢咖啡"


class TestMemoryManager:
    """MemoryManager 测试"""

    def setup_method(self):
        """每个测试创建临时数据库和管理器"""
        EventBus.reset()
        Config.reset()

        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.db = Database(str(self.db_path))
        self.db.initialize()

        self.config = Config()
        self.config.load()
        self.memory = MemoryManager(self.db, self.config)

    def test_create_conversation(self):
        """测试创建对话"""
        conv = self.memory.create_conversation(
            channel="cli",
            title="测试"
        )
        assert conv.id is not None
        assert conv.channel == "cli"

    def test_get_or_create_conversation(self):
        """测试获取或创建对话"""
        # 第一次创建
        conv1 = self.memory.get_or_create_conversation("imessage", "user1")
        # 第二次获取
        conv2 = self.memory.get_or_create_conversation("imessage", "user1")

        assert conv1.id == conv2.id

    def test_add_messages(self):
        """测试添加消息"""
        conv = self.memory.create_conversation()

        msg1 = self.memory.add_user_message(conv.id, "你好")
        msg2 = self.memory.add_assistant_message(conv.id, "你好！有什么可以帮你的？")

        assert msg1.role == MessageRole.USER
        assert msg2.role == MessageRole.ASSISTANT

        messages = self.memory.get_messages(conv.id)
        assert len(messages) == 2

    def test_get_context(self):
        """测试获取上下文"""
        conv = self.memory.create_conversation()

        self.memory.add_user_message(conv.id, "你好")
        self.memory.add_assistant_message(conv.id, "你好！")
        self.memory.add_user_message(conv.id, "今天天气怎么样？")

        context = self.memory.get_context(conv.id)

        assert len(context) == 3
        assert context[0]["role"] == "user"
        assert context[1]["role"] == "assistant"
        assert context[2]["role"] == "user"

    def test_context_token_limit(self):
        """测试上下文 token 限制"""
        conv = self.memory.create_conversation()

        # 添加很多消息
        for i in range(100):
            self.memory.add_user_message(conv.id, f"这是第 {i} 条很长的测试消息，用于测试 token 限制功能。" * 10)

        # 获取有限制的上下文
        context = self.memory.get_context(conv.id, max_tokens=1000)

        # 应该被截断
        assert len(context) < 100

    def test_tool_message(self):
        """测试工具消息"""
        conv = self.memory.create_conversation()

        # 助手发起工具调用
        self.memory.add_assistant_message(
            conv.id,
            "",
            tool_calls=[{
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "北京"}'}
            }]
        )

        # 工具响应
        self.memory.add_tool_message(
            conv.id,
            content='{"temperature": 25, "weather": "晴"}',
            tool_call_id="call_123",
            name="get_weather"
        )

        messages = self.memory.get_messages(conv.id)
        assert len(messages) == 2
        assert messages[1].role == MessageRole.TOOL
        assert messages[1].tool_call_id == "call_123"

    def test_count_tokens(self):
        """测试 token 计数"""
        # 简单测试
        count = self.memory.count_tokens("Hello, world!")
        assert count > 0

        # 中文
        count_cn = self.memory.count_tokens("你好，世界！")
        assert count_cn > 0


class TestMessage:
    """Message 模型测试"""

    def test_to_dict(self):
        """测试转换为字典"""
        msg = Message(
            role=MessageRole.USER,
            content="你好"
        )
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "你好"

    def test_from_dict(self):
        """测试从字典创建"""
        d = {"role": "assistant", "content": "你好！"}
        msg = Message.from_dict(d)
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "你好！"

    def test_tool_call_message(self):
        """测试工具调用消息"""
        msg = Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "test"}}]
        )
        d = msg.to_dict()
        assert "tool_calls" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
