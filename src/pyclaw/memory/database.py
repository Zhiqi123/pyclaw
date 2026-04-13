"""
数据库管理 - SQLite 存储层

管理数据库连接、表结构初始化和迁移。
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import contextmanager
import logging

import aiosqlite

from ..core.logger import LoggerMixin

logger = logging.getLogger(__name__)


# 数据库版本，用于迁移
DB_VERSION = 2

# 表结构定义
SCHEMA = """
-- 对话表
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL DEFAULT 'cli',
    channel_id TEXT DEFAULT '',
    title TEXT DEFAULT '',
    summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT DEFAULT '{}'
);

-- 消息表
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls TEXT,
    tool_call_id TEXT,
    name TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- 摘要表
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    message_start INTEGER DEFAULT 0,
    message_end INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- 事实表
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    source_conversation_id INTEGER,
    category TEXT DEFAULT '',
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (source_conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

-- 系统操作日志表
CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL DEFAULT 'INFO',
    category TEXT NOT NULL DEFAULT 'system',
    action TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT DEFAULT '{}',
    source TEXT DEFAULT '',
    conversation_id INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

-- 版本表
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_conversations_channel ON conversations(channel, channel_id);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_system_logs_category ON system_logs(category);
CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level);
"""


class Database(LoggerMixin):
    """
    数据库管理器

    提供同步和异步两种访问方式。

    使用示例:
        db = Database("~/.pyclaw/data/pyclaw.db")
        db.initialize()

        # 同步操作
        with db.connection() as conn:
            conn.execute("SELECT * FROM conversations")

        # 异步操作
        async with db.async_connection() as conn:
            await conn.execute("SELECT * FROM messages")
    """

    def __init__(self, db_path: str):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path).expanduser()
        self._sync_conn: Optional[sqlite3.Connection] = None

    def initialize(self) -> None:
        """初始化数据库（创建表结构）"""
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self.connection() as conn:
            # 执行 schema
            conn.executescript(SCHEMA)

            # 检查并更新版本
            cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = cursor.fetchone()

            if row is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (DB_VERSION,))
            elif row[0] < DB_VERSION:
                self._migrate(conn, row[0], DB_VERSION)
                conn.execute("UPDATE schema_version SET version = ?", (DB_VERSION,))

            conn.commit()

        self.logger.info(f"数据库初始化完成: {self.db_path}")

    def _migrate(self, conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
        """执行数据库迁移"""
        self.logger.info(f"数据库迁移: v{from_version} -> v{to_version}")

        # v1 -> v2: 添加 system_logs 表
        if from_version < 2:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL DEFAULT 'INFO',
                    category TEXT NOT NULL DEFAULT 'system',
                    action TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT DEFAULT '{}',
                    source TEXT DEFAULT '',
                    conversation_id INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_category ON system_logs(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level)")
            self.logger.info("迁移完成: 添加 system_logs 表")

    @contextmanager
    def connection(self):
        """
        获取同步数据库连接（上下文管理器）

        Yields:
            sqlite3.Connection
        """
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            yield conn
        finally:
            conn.close()

    async def async_connection(self) -> aiosqlite.Connection:
        """
        获取异步数据库连接

        Returns:
            aiosqlite.Connection
        """
        conn = await aiosqlite.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ============================================================
    # 对话操作
    # ============================================================

    def create_conversation(
        self,
        channel: str = "cli",
        channel_id: str = "",
        title: str = "",
        metadata: Optional[Dict] = None
    ) -> int:
        """创建新对话，返回对话 ID"""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversations (channel, channel_id, title, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (channel, channel_id, title, json.dumps(metadata or {}))
            )
            conn.commit()
            return cursor.lastrowid

    def get_conversation(self, conversation_id: int) -> Optional[Dict]:
        """获取对话信息"""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_conversation_by_channel(self, channel: str, channel_id: str) -> Optional[Dict]:
        """根据通道信息获取对话"""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM conversations
                WHERE channel = ? AND channel_id = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (channel, channel_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_conversation(
        self,
        conversation_id: int,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> None:
        """更新对话信息"""
        updates = ["updated_at = CURRENT_TIMESTAMP"]
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if summary is not None:
            updates.append("summary = ?")
            params.append(summary)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))

        params.append(conversation_id)

        with self.connection() as conn:
            conn.execute(
                f"UPDATE conversations SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()

    def list_conversations(
        self,
        channel: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """列出对话"""
        with self.connection() as conn:
            if channel:
                cursor = conn.execute(
                    """
                    SELECT * FROM conversations
                    WHERE channel = ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (channel, limit, offset)
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM conversations
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset)
                )
            return [dict(row) for row in cursor.fetchall()]

    def delete_conversation(self, conversation_id: int) -> None:
        """删除对话（级联删除消息）"""
        with self.connection() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            conn.commit()

    # ============================================================
    # 消息操作
    # ============================================================

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> int:
        """添加消息，返回消息 ID"""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages
                (conversation_id, role, content, tool_calls, tool_call_id, name, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content,
                    json.dumps(tool_calls) if tool_calls else None,
                    tool_call_id,
                    name,
                    json.dumps(metadata or {})
                )
            )
            # 更新对话的 updated_at
            conn.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,)
            )
            conn.commit()
            return cursor.lastrowid

    def get_messages(
        self,
        conversation_id: int,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict]:
        """获取对话的消息列表"""
        with self.connection() as conn:
            if limit:
                cursor = conn.execute(
                    """
                    SELECT * FROM messages
                    WHERE conversation_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ? OFFSET ?
                    """,
                    (conversation_id, limit, offset)
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM messages
                    WHERE conversation_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (conversation_id,)
                )

            messages = []
            for row in cursor.fetchall():
                msg = dict(row)
                # 解析 JSON 字段
                if msg.get("tool_calls"):
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                if msg.get("metadata"):
                    msg["metadata"] = json.loads(msg["metadata"])
                messages.append(msg)

            return messages

    def get_recent_messages(
        self,
        conversation_id: int,
        limit: int = 50
    ) -> List[Dict]:
        """获取最近的消息（按 ID 倒序取，然后正序返回）"""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM messages
                    WHERE conversation_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (conversation_id, limit)
            )

            messages = []
            for row in cursor.fetchall():
                msg = dict(row)
                if msg.get("tool_calls"):
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                if msg.get("metadata"):
                    msg["metadata"] = json.loads(msg["metadata"])
                messages.append(msg)

            return messages

    def count_messages(self, conversation_id: int) -> int:
        """统计对话消息数量"""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,)
            )
            return cursor.fetchone()[0]

    # ============================================================
    # 事实操作
    # ============================================================

    def add_fact(
        self,
        content: str,
        category: str = "",
        source_conversation_id: Optional[int] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict] = None
    ) -> int:
        """添加事实"""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO facts
                (content, category, source_conversation_id, confidence, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (content, category, source_conversation_id, confidence, json.dumps(metadata or {}))
            )
            conn.commit()
            return cursor.lastrowid

    def search_facts(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """搜索事实"""
        with self.connection() as conn:
            conditions = []
            params = []

            if query:
                conditions.append("content LIKE ?")
                params.append(f"%{query}%")
            if category:
                conditions.append("category = ?")
                params.append(category)

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            params.append(limit)

            cursor = conn.execute(
                f"""
                SELECT * FROM facts
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params
            )

            facts = []
            for row in cursor.fetchall():
                fact = dict(row)
                if fact.get("metadata"):
                    fact["metadata"] = json.loads(fact["metadata"])
                facts.append(fact)

            return facts

    def get_fact(self, fact_id: int) -> Optional[Dict]:
        """获取单个事实"""
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,))
            row = cursor.fetchone()
            if row:
                fact = dict(row)
                if fact.get("metadata"):
                    fact["metadata"] = json.loads(fact["metadata"])
                return fact
            return None

    def update_fact(
        self,
        fact_id: int,
        content: Optional[str] = None,
        category: Optional[str] = None,
        confidence: Optional[float] = None
    ) -> None:
        """更新事实"""
        updates = []
        params = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if confidence is not None:
            updates.append("confidence = ?")
            params.append(confidence)

        if not updates:
            return

        params.append(fact_id)

        with self.connection() as conn:
            conn.execute(
                f"UPDATE facts SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()

    def delete_fact(self, fact_id: int) -> None:
        """删除事实"""
        with self.connection() as conn:
            conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            conn.commit()

    def list_facts(self, category: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """列出所有事实"""
        with self.connection() as conn:
            if category:
                cursor = conn.execute(
                    "SELECT * FROM facts WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                    (category, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM facts ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )

            facts = []
            for row in cursor.fetchall():
                fact = dict(row)
                if fact.get("metadata"):
                    fact["metadata"] = json.loads(fact["metadata"])
                facts.append(fact)
            return facts

    # ============================================================
    # 摘要操作
    # ============================================================

    def add_summary(
        self,
        conversation_id: int,
        content: str,
        message_start: int = 0,
        message_end: int = 0
    ) -> int:
        """添加对话摘要"""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO summaries (conversation_id, content, message_start, message_end)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, content, message_start, message_end)
            )
            # 同时更新对话的 summary 字段
            conn.execute(
                "UPDATE conversations SET summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (content, conversation_id)
            )
            conn.commit()
            return cursor.lastrowid

    def get_summaries(self, conversation_id: int) -> List[Dict]:
        """获取对话的所有摘要"""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM summaries
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                """,
                (conversation_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_summary(self, conversation_id: int) -> Optional[Dict]:
        """获取对话的最新摘要"""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM summaries
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (conversation_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_summaries(self, conversation_id: int) -> None:
        """删除对话的所有摘要"""
        with self.connection() as conn:
            conn.execute("DELETE FROM summaries WHERE conversation_id = ?", (conversation_id,))
            conn.commit()

    # ============================================================
    # 系统日志操作
    # ============================================================

    def add_system_log(
        self,
        action: str,
        message: str,
        level: str = "INFO",
        category: str = "system",
        details: Optional[Dict] = None,
        source: str = "",
        conversation_id: Optional[int] = None
    ) -> int:
        """
        添加系统操作日志

        Args:
            action: 操作类型（如 tool_call, llm_request, channel_send 等）
            message: 日志消息
            level: 日志级别（DEBUG, INFO, WARNING, ERROR）
            category: 日志分类（system, agent, llm, channel, skill, scheduler）
            details: 详细信息（JSON 格式）
            source: 日志来源模块
            conversation_id: 关联的对话 ID

        Returns:
            日志记录 ID
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO system_logs
                (level, category, action, message, details, source, conversation_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (level, category, action, message, json.dumps(details or {}), source, conversation_id)
            )
            conn.commit()
            return cursor.lastrowid

    def get_system_logs(
        self,
        category: Optional[str] = None,
        level: Optional[str] = None,
        conversation_id: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """
        查询系统日志

        Args:
            category: 按分类筛选
            level: 按级别筛选
            conversation_id: 按对话筛选
            start_time: 开始时间（ISO 格式）
            end_time: 结束时间（ISO 格式）
            limit: 返回数量限制
            offset: 偏移量
        """
        with self.connection() as conn:
            conditions = []
            params = []

            if category:
                conditions.append("category = ?")
                params.append(category)
            if level:
                conditions.append("level = ?")
                params.append(level)
            if conversation_id:
                conditions.append("conversation_id = ?")
                params.append(conversation_id)
            if start_time:
                conditions.append("timestamp >= ?")
                params.append(start_time)
            if end_time:
                conditions.append("timestamp <= ?")
                params.append(end_time)

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            params.extend([limit, offset])

            cursor = conn.execute(
                f"""
                SELECT * FROM system_logs
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                params
            )

            logs = []
            for row in cursor.fetchall():
                log = dict(row)
                if log.get("details"):
                    log["details"] = json.loads(log["details"])
                logs.append(log)

            return logs

    def count_system_logs(
        self,
        category: Optional[str] = None,
        level: Optional[str] = None
    ) -> int:
        """统计系统日志数量"""
        with self.connection() as conn:
            conditions = []
            params = []

            if category:
                conditions.append("category = ?")
                params.append(category)
            if level:
                conditions.append("level = ?")
                params.append(level)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            cursor = conn.execute(
                f"SELECT COUNT(*) FROM system_logs WHERE {where_clause}",
                params
            )
            return cursor.fetchone()[0]

    # ============================================================
    # 数据清理操作
    # ============================================================

    def cleanup_old_messages(self, retention_days: int = 30) -> Dict[str, int]:
        """
        清理超过保留期限的消息

        保留最近 N 天的详细消息，删除更早的消息（但保留对话和摘要）。

        Args:
            retention_days: 保留天数

        Returns:
            清理统计信息
        """
        with self.connection() as conn:
            # 计算截止时间
            cursor = conn.execute(
                """
                SELECT datetime('now', ? || ' days') as cutoff
                """,
                (f"-{retention_days}",)
            )
            cutoff = cursor.fetchone()[0]

            # 统计要删除的消息数量
            cursor = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE timestamp < ?",
                (cutoff,)
            )
            messages_to_delete = cursor.fetchone()[0]

            # 删除旧消息
            conn.execute(
                "DELETE FROM messages WHERE timestamp < ?",
                (cutoff,)
            )

            # 清理旧系统日志
            cursor = conn.execute(
                "SELECT COUNT(*) FROM system_logs WHERE timestamp < ?",
                (cutoff,)
            )
            logs_to_delete = cursor.fetchone()[0]

            conn.execute(
                "DELETE FROM system_logs WHERE timestamp < ?",
                (cutoff,)
            )

            conn.commit()

            result = {
                "messages_deleted": messages_to_delete,
                "logs_deleted": logs_to_delete,
                "cutoff_date": cutoff
            }

            self.logger.info(f"数据清理完成: 删除 {messages_to_delete} 条消息, {logs_to_delete} 条日志")
            return result

    def cleanup_empty_conversations(self) -> int:
        """
        清理没有消息的空对话

        Returns:
            删除的对话数量
        """
        with self.connection() as conn:
            # 找出没有消息的对话
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM conversations c
                WHERE NOT EXISTS (
                    SELECT 1 FROM messages m WHERE m.conversation_id = c.id
                )
                """
            )
            count = cursor.fetchone()[0]

            # 删除空对话
            conn.execute(
                """
                DELETE FROM conversations
                WHERE id NOT IN (
                    SELECT DISTINCT conversation_id FROM messages
                )
                """
            )
            conn.commit()

            self.logger.info(f"清理空对话: 删除 {count} 个")
            return count

    def get_database_stats(self) -> Dict[str, any]:
        """
        获取数据库统计信息

        Returns:
            统计信息字典
        """
        with self.connection() as conn:
            stats = {}

            # 各表记录数
            tables = ["conversations", "messages", "summaries", "facts", "system_logs"]
            for table in tables:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f"{table}_count"] = cursor.fetchone()[0]

            # 数据库文件大小
            stats["db_size_mb"] = round(self.db_path.stat().st_size / (1024 * 1024), 2)

            # 最早和最新消息时间
            cursor = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM messages")
            row = cursor.fetchone()
            stats["oldest_message"] = row[0]
            stats["newest_message"] = row[1]

            # 最早和最新日志时间
            cursor = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM system_logs")
            row = cursor.fetchone()
            stats["oldest_log"] = row[0]
            stats["newest_log"] = row[1]

            return stats

    def vacuum(self) -> None:
        """压缩数据库文件，回收空间"""
        with self.connection() as conn:
            conn.execute("VACUUM")
            self.logger.info("数据库压缩完成")
