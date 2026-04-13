"""
记忆管理器 - 上下文和对话管理

负责管理对话上下文、消息存取和 token 限制。
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import logging
from enum import Enum

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

from .database import Database
from .models import Conversation, Message, MessageRole
from ..core.event_bus import EventBus, EventType
from ..core.config import Config
from ..core.logger import LoggerMixin

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogCategory(str, Enum):
    """日志分类"""
    SYSTEM = "system"
    AGENT = "agent"
    LLM = "llm"
    CHANNEL = "channel"
    SKILL = "skill"
    SCHEDULER = "scheduler"
    CLEANUP = "cleanup"


class MemoryManager(LoggerMixin):
    """
    记忆管理器

    管理对话上下文，提供消息存取和 token 限制功能。

    使用示例:
        memory = MemoryManager(db)

        # 创建或获取对话
        conv = memory.get_or_create_conversation("imessage", "+1234567890")

        # 添加消息
        memory.add_message(conv.id, MessageRole.USER, "你好")
        memory.add_message(conv.id, MessageRole.ASSISTANT, "你好！有什么可以帮你的？")

        # 获取上下文
        context = memory.get_context(conv.id)
    """

    def __init__(self, database: Database, config: Optional[Config] = None):
        """
        初始化记忆管理器

        Args:
            database: 数据库实例
            config: 配置实例，None 则使用全局配置
        """
        self.db = database
        self.config = config or Config()
        self.event_bus = EventBus()

        # Token 计数器
        self._tokenizer = None
        if HAS_TIKTOKEN:
            try:
                self._tokenizer = tiktoken.get_encoding("cl100k_base")
            except Exception:
                pass

        # 配置
        self.max_context_tokens = self.config.memory.max_context_tokens
        self.max_history_messages = self.config.memory.max_history_messages
        self.retention_days = self.config.memory.retention_days
        self.auto_cleanup = self.config.memory.auto_cleanup
        self._cleanup_executed = False

    def count_tokens(self, text: str) -> int:
        """
        计算文本的 token 数量

        Args:
            text: 输入文本

        Returns:
            token 数量（无 tiktoken 时返回估算值）
        """
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        # 粗略估算：中文约 2 字符/token，英文约 4 字符/token
        return len(text) // 2

    def count_message_tokens(self, messages: List[Dict]) -> int:
        """计算消息列表的总 token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if content:
                total += self.count_tokens(content)
            # 工具调用也计入
            if msg.get("tool_calls"):
                total += self.count_tokens(str(msg["tool_calls"]))
        return total

    # ============================================================
    # 对话管理
    # ============================================================

    def create_conversation(
        self,
        channel: str = "cli",
        channel_id: str = "",
        title: str = ""
    ) -> Conversation:
        """创建新对话"""
        conv_id = self.db.create_conversation(
            channel=channel,
            channel_id=channel_id,
            title=title
        )

        conv = Conversation(
            id=conv_id,
            channel=channel,
            channel_id=channel_id,
            title=title
        )

        self.event_bus.publish(
            EventType.SESSION_STARTED,
            data={"conversation_id": conv_id, "channel": channel},
            source="MemoryManager"
        )

        self.logger.debug(f"创建对话: {conv_id} ({channel})")
        return conv

    def get_conversation(self, conversation_id: int) -> Optional[Conversation]:
        """获取对话"""
        data = self.db.get_conversation(conversation_id)
        if not data:
            return None

        return Conversation(
            id=data["id"],
            channel=data["channel"],
            channel_id=data["channel_id"],
            title=data["title"],
            summary=data.get("summary"),
            created_at=data["created_at"],
            updated_at=data["updated_at"]
        )

    def get_or_create_conversation(
        self,
        channel: str,
        channel_id: str,
        title: str = ""
    ) -> Conversation:
        """获取或创建对话"""
        data = self.db.get_conversation_by_channel(channel, channel_id)

        if data:
            return Conversation(
                id=data["id"],
                channel=data["channel"],
                channel_id=data["channel_id"],
                title=data["title"],
                summary=data.get("summary"),
                created_at=data["created_at"],
                updated_at=data["updated_at"]
            )

        return self.create_conversation(channel, channel_id, title)

    def list_conversations(
        self,
        channel: Optional[str] = None,
        limit: int = 50
    ) -> List[Conversation]:
        """列出对话"""
        data_list = self.db.list_conversations(channel=channel, limit=limit)
        return [
            Conversation(
                id=d["id"],
                channel=d["channel"],
                channel_id=d["channel_id"],
                title=d["title"],
                summary=d.get("summary"),
                created_at=d["created_at"],
                updated_at=d["updated_at"]
            )
            for d in data_list
        ]

    def delete_conversation(self, conversation_id: int) -> None:
        """删除对话"""
        self.db.delete_conversation(conversation_id)

        self.event_bus.publish(
            EventType.SESSION_ENDED,
            data={"conversation_id": conversation_id},
            source="MemoryManager"
        )

        self.logger.debug(f"删除对话: {conversation_id}")

    # ============================================================
    # 消息管理
    # ============================================================

    def add_message(
        self,
        conversation_id: int,
        role: MessageRole,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Message:
        """添加消息到对话"""
        msg_id = self.db.add_message(
            conversation_id=conversation_id,
            role=role.value,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            name=name,
            metadata=metadata
        )

        message = Message(
            id=msg_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            name=name,
            metadata=metadata or {}
        )

        # 发布事件
        event_type = EventType.MESSAGE_RECEIVED if role == MessageRole.USER else EventType.MESSAGE_SAVED
        self.event_bus.publish(
            event_type,
            data={"message": message, "conversation_id": conversation_id},
            source="MemoryManager"
        )

        return message

    def add_user_message(
        self,
        conversation_id: int,
        content: str,
        attachments: Optional[List[Dict]] = None
    ) -> Message:
        """
        添加用户消息（便捷方法）

        Args:
            conversation_id: 对话 ID
            content: 消息内容
            attachments: 附件列表（图片等）

        Returns:
            Message 对象
        """
        # 将附件信息存储在 metadata 中（数据库不直接存储 base64）
        metadata = {}
        if attachments:
            # 只存储附件元数据（不包含 base64 数据，以节省数据库空间）
            metadata["attachments_count"] = len(attachments)
            metadata["attachments_types"] = [a.get("type") for a in attachments]

        msg = self.add_message(
            conversation_id,
            MessageRole.USER,
            content,
            metadata=metadata if metadata else None
        )

        # 在 Message 对象上附加完整的附件数据（用于当前请求）
        msg.attachments = attachments

        return msg

    def add_assistant_message(
        self,
        conversation_id: int,
        content: str,
        tool_calls: Optional[List[Dict]] = None
    ) -> Message:
        """添加助手消息（便捷方法）"""
        return self.add_message(
            conversation_id,
            MessageRole.ASSISTANT,
            content,
            tool_calls=tool_calls
        )

    def add_tool_message(
        self,
        conversation_id: int,
        content: str,
        tool_call_id: str,
        name: str
    ) -> Message:
        """添加工具响应消息（便捷方法）"""
        return self.add_message(
            conversation_id,
            MessageRole.TOOL,
            content,
            tool_call_id=tool_call_id,
            name=name
        )

    def get_messages(
        self,
        conversation_id: int,
        limit: Optional[int] = None
    ) -> List[Message]:
        """获取对话消息"""
        data_list = self.db.get_messages(conversation_id, limit=limit)
        return [self._dict_to_message(d) for d in data_list]

    def get_recent_messages(
        self,
        conversation_id: int,
        limit: Optional[int] = None
    ) -> List[Message]:
        """获取最近的消息"""
        limit = limit or self.max_history_messages
        data_list = self.db.get_recent_messages(conversation_id, limit=limit)
        return [self._dict_to_message(d) for d in data_list]

    def _dict_to_message(self, data: Dict) -> Message:
        """将字典转换为 Message 对象"""
        return Message(
            id=data["id"],
            conversation_id=data["conversation_id"],
            role=MessageRole(data["role"]),
            content=data["content"],
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
            timestamp=data["timestamp"],
            metadata=data.get("metadata", {})
        )

    # ============================================================
    # 上下文管理
    # ============================================================

    def get_context(
        self,
        conversation_id: int,
        max_tokens: Optional[int] = None,
        max_messages: Optional[int] = None
    ) -> List[Dict]:
        """
        获取对话上下文（用于 LLM 调用）

        自动根据 token 限制截断历史消息。

        Args:
            conversation_id: 对话 ID
            max_tokens: 最大 token 数，None 使用配置值
            max_messages: 最大消息数，None 使用配置值

        Returns:
            消息列表（字典格式，可直接用于 LLM API）
        """
        max_tokens = max_tokens or self.max_context_tokens
        max_messages = max_messages or self.max_history_messages

        # 获取最近消息
        messages = self.get_recent_messages(conversation_id, limit=max_messages)

        # 转换为字典格式
        context = [msg.to_dict() for msg in messages]

        # Token 限制截断
        context = self._truncate_by_tokens(context, max_tokens)

        # 确保工具调用完整性（防止孤立的 tool_result）
        context = self._ensure_tool_call_integrity(context)

        self.event_bus.publish(
            EventType.CONTEXT_LOADED,
            data={
                "conversation_id": conversation_id,
                "message_count": len(context),
                "token_count": self.count_message_tokens(context)
            },
            source="MemoryManager"
        )

        return context

    def _truncate_by_tokens(
        self,
        messages: List[Dict],
        max_tokens: int
    ) -> List[Dict]:
        """
        按 token 限制截断消息

        保留最近的消息，从最早的开始删除。
        确保工具调用的完整性（tool_use 和 tool_result 成对保留）。
        """
        if not messages:
            return messages

        total_tokens = self.count_message_tokens(messages)

        if total_tokens <= max_tokens:
            return messages

        # 从最早的消息开始删除
        result = list(messages)
        while result and self.count_message_tokens(result) > max_tokens:
            result.pop(0)

        # 确保工具调用完整性
        result = self._ensure_tool_call_integrity(result)

        self.logger.debug(
            f"上下文截断: {len(messages)} -> {len(result)} 条消息, "
            f"{total_tokens} -> {self.count_message_tokens(result)} tokens"
        )

        return result

    def _ensure_tool_call_integrity(self, messages: List[Dict]) -> List[Dict]:
        """
        确保工具调用消息的完整性

        Claude API 要求 tool_result 必须有对应的 tool_use。
        如果发现孤立的 tool_result，删除它们。
        """
        if not messages:
            return messages

        # 收集所有 tool_use 的 ID
        tool_use_ids = set()
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tool_use_ids.add(tc.get("id"))

        # 过滤掉没有对应 tool_use 的 tool_result
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                tool_call_id = msg.get("tool_call_id")
                if tool_call_id and tool_call_id not in tool_use_ids:
                    # 跳过孤立的 tool_result
                    self.logger.debug(f"跳过孤立的 tool_result: {tool_call_id}")
                    continue
            result.append(msg)

        return result

    def get_context_with_summary(
        self,
        conversation_id: int,
        max_tokens: Optional[int] = None
    ) -> Tuple[Optional[str], List[Dict]]:
        """
        获取带摘要的上下文

        Returns:
            (摘要, 消息列表)
        """
        conv = self.get_conversation(conversation_id)
        summary = conv.summary if conv else None

        context = self.get_context(conversation_id, max_tokens)

        return summary, context

    # ============================================================
    # 事实管理
    # ============================================================

    def add_fact(
        self,
        content: str,
        category: str = "",
        conversation_id: Optional[int] = None
    ) -> int:
        """添加事实"""
        fact_id = self.db.add_fact(
            content=content,
            category=category,
            source_conversation_id=conversation_id
        )

        self.event_bus.publish(
            EventType.MEMORY_UPDATED,
            data={"fact_id": fact_id, "content": content},
            source="MemoryManager"
        )

        return fact_id

    def search_facts(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """搜索事实"""
        return self.db.search_facts(query=query, category=category, limit=limit)

    def get_all_facts(self, category: Optional[str] = None) -> List[Dict]:
        """获取所有事实"""
        return self.db.list_facts(category=category)

    def delete_fact(self, fact_id: int) -> None:
        """删除事实"""
        self.db.delete_fact(fact_id)

    def update_fact(
        self,
        fact_id: int,
        content: Optional[str] = None,
        category: Optional[str] = None,
        confidence: Optional[float] = None
    ) -> None:
        """更新事实"""
        self.db.update_fact(fact_id, content, category, confidence)

    # ============================================================
    # 摘要管理
    # ============================================================

    def add_summary(
        self,
        conversation_id: int,
        content: str,
        message_start: int = 0,
        message_end: int = 0
    ) -> int:
        """添加对话摘要"""
        summary_id = self.db.add_summary(
            conversation_id=conversation_id,
            content=content,
            message_start=message_start,
            message_end=message_end
        )

        self.event_bus.publish(
            EventType.MEMORY_UPDATED,
            data={"summary_id": summary_id, "conversation_id": conversation_id},
            source="MemoryManager"
        )

        return summary_id

    def get_summary(self, conversation_id: int) -> Optional[str]:
        """获取对话的最新摘要"""
        summary = self.db.get_latest_summary(conversation_id)
        return summary["content"] if summary else None

    def should_compress(self, conversation_id: int, threshold: int = 50) -> bool:
        """
        检查是否需要压缩对话

        Args:
            conversation_id: 对话 ID
            threshold: 消息数量阈值

        Returns:
            是否需要压缩
        """
        count = self.db.count_messages(conversation_id)
        return count > threshold

    async def compress_conversation(
        self,
        conversation_id: int,
        llm_client: Any,
        keep_recent: int = 20
    ) -> Optional[str]:
        """
        压缩对话历史

        将旧消息压缩为摘要，保留最近的消息。

        Args:
            conversation_id: 对话 ID
            llm_client: LLM 客户端（用于生成摘要）
            keep_recent: 保留最近的消息数量

        Returns:
            生成的摘要内容，失败返回 None
        """
        # 获取所有消息
        all_messages = self.get_messages(conversation_id)

        if len(all_messages) <= keep_recent:
            self.logger.debug("消息数量不足，无需压缩")
            return None

        # 分离要压缩的消息和要保留的消息
        messages_to_compress = all_messages[:-keep_recent]
        message_start = messages_to_compress[0].id if messages_to_compress else 0
        message_end = messages_to_compress[-1].id if messages_to_compress else 0

        # 构建压缩提示
        conversation_text = self._format_messages_for_summary(messages_to_compress)

        summary_prompt = f"""请将以下对话历史压缩为简洁的摘要，保留：
1. 关键事实和决定
2. 用户的偏好和习惯
3. 未完成的任务或承诺
4. 重要的上下文信息

对话历史:
{conversation_text}

请生成摘要（不超过500字）:"""

        try:
            # 调用 LLM 生成摘要
            response = await llm_client.chat([
                {"role": "user", "content": summary_prompt}
            ])

            summary_content = response.content if hasattr(response, 'content') else str(response)

            # 保存摘要
            self.add_summary(
                conversation_id=conversation_id,
                content=summary_content,
                message_start=message_start,
                message_end=message_end
            )

            self.logger.info(f"对话 {conversation_id} 已压缩，生成摘要")
            return summary_content

        except Exception as e:
            self.logger.error(f"压缩对话失败: {e}")
            return None

    def _format_messages_for_summary(self, messages: List) -> str:
        """格式化消息用于摘要生成"""
        lines = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    # ============================================================
    # 事实提取
    # ============================================================

    async def extract_facts(
        self,
        conversation_id: int,
        llm_client: Any,
        recent_messages: int = 10
    ) -> List[Dict]:
        """
        从对话中提取事实

        Args:
            conversation_id: 对话 ID
            llm_client: LLM 客户端
            recent_messages: 分析最近的消息数量

        Returns:
            提取的事实列表
        """
        messages = self.get_recent_messages(conversation_id, limit=recent_messages)

        if not messages:
            return []

        conversation_text = self._format_messages_for_summary(messages)

        extract_prompt = f"""从以下对话中提取关于用户的事实信息。
返回 JSON 格式的数组，每个事实包含:
- content: 事实内容
- category: 分类 (preference/info/task/habit)
- confidence: 置信度 0-1

只提取明确的事实，不要推测。如果没有可提取的事实，返回空数组 []。

对话:
{conversation_text}

请返回 JSON 数组:"""

        try:
            response = await llm_client.chat([
                {"role": "user", "content": extract_prompt}
            ])

            content = response.content if hasattr(response, 'content') else str(response)

            # 解析 JSON
            import json
            import re

            # 尝试提取 JSON 数组
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                facts_data = json.loads(json_match.group())
            else:
                facts_data = []

            # 保存提取的事实
            extracted_facts = []
            for fact_data in facts_data:
                if isinstance(fact_data, dict) and fact_data.get("content"):
                    fact_id = self.add_fact(
                        content=fact_data["content"],
                        category=fact_data.get("category", "info"),
                        conversation_id=conversation_id
                    )
                    extracted_facts.append({
                        "id": fact_id,
                        **fact_data
                    })

            self.logger.info(f"从对话 {conversation_id} 提取了 {len(extracted_facts)} 个事实")
            return extracted_facts

        except Exception as e:
            self.logger.error(f"提取事实失败: {e}")
            return []

    # ============================================================
    # 完整上下文构建
    # ============================================================

    def build_full_context(
        self,
        conversation_id: int,
        system_prompt: Optional[str] = None,
        include_facts: bool = True,
        include_summary: bool = True,
        max_tokens: Optional[int] = None
    ) -> List[Dict]:
        """
        构建完整的上下文（包含事实、摘要、历史消息）

        按照架构设计的上下文结构:
        1. 系统提示
        2. 用户事实
        3. 历史摘要
        4. 最近对话历史
        5. 当前消息

        Args:
            conversation_id: 对话 ID
            system_prompt: 系统提示词
            include_facts: 是否包含事实
            include_summary: 是否包含摘要
            max_tokens: 最大 token 数

        Returns:
            完整的消息列表
        """
        context = []
        max_tokens = max_tokens or self.max_context_tokens

        # 1. 系统提示
        system_parts = []
        if system_prompt:
            system_parts.append(system_prompt)

        # 2. 用户事实
        if include_facts:
            facts = self.get_all_facts()
            if facts:
                facts_text = "\n".join([f"- {f['content']}" for f in facts[:10]])
                system_parts.append(f"\n关于用户的已知信息:\n{facts_text}")

        # 3. 历史摘要
        if include_summary:
            summary = self.get_summary(conversation_id)
            if summary:
                system_parts.append(f"\n之前对话的摘要:\n{summary}")

        # 添加系统消息
        if system_parts:
            context.append({
                "role": "system",
                "content": "\n".join(system_parts)
            })

        # 4. 最近对话历史
        messages = self.get_context(conversation_id, max_tokens=max_tokens)
        context.extend(messages)

        return context

    # ============================================================
    # 系统日志管理
    # ============================================================

    def log_system_event(
        self,
        action: str,
        message: str,
        level: LogLevel = LogLevel.INFO,
        category: LogCategory = LogCategory.SYSTEM,
        details: Optional[Dict] = None,
        source: str = "",
        conversation_id: Optional[int] = None
    ) -> int:
        """
        记录系统事件到数据库

        Args:
            action: 操作类型（如 tool_call, llm_request, channel_send）
            message: 日志消息
            level: 日志级别
            category: 日志分类
            details: 详细信息
            source: 来源模块
            conversation_id: 关联的对话 ID

        Returns:
            日志记录 ID
        """
        log_id = self.db.add_system_log(
            action=action,
            message=message,
            level=level.value if isinstance(level, LogLevel) else level,
            category=category.value if isinstance(category, LogCategory) else category,
            details=details,
            source=source,
            conversation_id=conversation_id
        )

        # 同时发布事件
        self.event_bus.publish(
            EventType.MEMORY_UPDATED,
            data={
                "type": "system_log",
                "log_id": log_id,
                "action": action,
                "category": category.value if isinstance(category, LogCategory) else category
            },
            source="MemoryManager"
        )

        return log_id

    def get_system_logs(
        self,
        category: Optional[str] = None,
        level: Optional[str] = None,
        conversation_id: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """获取系统日志"""
        return self.db.get_system_logs(
            category=category,
            level=level,
            conversation_id=conversation_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )

    # ============================================================
    # 数据清理管理
    # ============================================================

    def run_cleanup(self, force: bool = False) -> Optional[Dict[str, int]]:
        """
        执行数据清理

        Args:
            force: 是否强制执行（忽略 auto_cleanup 配置）

        Returns:
            清理统计信息，如果未执行返回 None
        """
        if not force and not self.auto_cleanup:
            self.logger.debug("自动清理已禁用")
            return None

        # 记录清理开始
        self.log_system_event(
            action="cleanup_start",
            message=f"开始数据清理，保留 {self.retention_days} 天数据",
            category=LogCategory.CLEANUP,
            source="MemoryManager"
        )

        try:
            # 清理旧消息和日志
            result = self.db.cleanup_old_messages(self.retention_days)

            # 清理空对话
            empty_count = self.db.cleanup_empty_conversations()
            result["empty_conversations_deleted"] = empty_count

            # 记录清理完成
            self.log_system_event(
                action="cleanup_complete",
                message=f"清理完成: {result['messages_deleted']} 消息, {result['logs_deleted']} 日志, {empty_count} 空对话",
                category=LogCategory.CLEANUP,
                details=result,
                source="MemoryManager"
            )

            self._cleanup_executed = True
            return result

        except Exception as e:
            self.logger.error(f"数据清理失败: {e}")
            self.log_system_event(
                action="cleanup_error",
                message=f"清理失败: {str(e)}",
                level=LogLevel.ERROR,
                category=LogCategory.CLEANUP,
                source="MemoryManager"
            )
            return None

    def run_startup_cleanup(self) -> Optional[Dict[str, int]]:
        """
        启动时执行清理（如果配置启用）

        只会在启动后第一次调用时执行
        """
        if self._cleanup_executed:
            return None

        if not self.config.memory.cleanup_on_startup:
            self._cleanup_executed = True
            return None

        return self.run_cleanup()

    def get_storage_stats(self) -> Dict[str, any]:
        """
        获取存储统计信息

        Returns:
            统计信息字典
        """
        stats = self.db.get_database_stats()

        # 添加配置信息
        stats["retention_days"] = self.retention_days
        stats["auto_cleanup"] = self.auto_cleanup

        return stats

    def vacuum_database(self) -> None:
        """压缩数据库，回收空间"""
        self.log_system_event(
            action="vacuum_start",
            message="开始压缩数据库",
            category=LogCategory.CLEANUP,
            source="MemoryManager"
        )

        self.db.vacuum()

        self.log_system_event(
            action="vacuum_complete",
            message="数据库压缩完成",
            category=LogCategory.CLEANUP,
            source="MemoryManager"
        )
