"""
iMessage 通道适配器

通过 AppleScript 与 macOS Messages 应用交互。
"""

import base64
import logging
import mimetypes
import subprocess
import tempfile
import time
import threading
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .base import (
    BaseChannel, ChannelType, ChannelStatus,
    IncomingMessage, OutgoingMessage
)

# Claude API 支持的图片类型
CLAUDE_SUPPORTED_TYPES = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
# 需要转换的图片类型（HEIC -> JPEG）
CONVERTIBLE_TYPES = {'.heic', '.heif'}
# 所有支持的图片类型
SUPPORTED_IMAGE_TYPES = CLAUDE_SUPPORTED_TYPES | CONVERTIBLE_TYPES
# Claude API 图片大小限制（5MB）
MAX_IMAGE_SIZE = 5 * 1024 * 1024

logger = logging.getLogger(__name__)


class IMessageChannel(BaseChannel):
    """
    iMessage 通道

    通过 AppleScript 发送消息，通过读取 chat.db 接收消息。

    注意：需要授予终端/Python 完全磁盘访问权限才能读取 chat.db。

    使用示例:
        channel = IMessageChannel()
        channel.set_on_message(handle_message)
        channel.connect()
        channel.start_listening()
    """

    # Messages 数据库路径
    CHAT_DB_PATH = Path.home() / "Library/Messages/chat.db"

    # 轮询间隔（秒）
    DEFAULT_POLL_INTERVAL = 2.0

    def __init__(self, config: Optional[Dict] = None, dm_config=None):
        """
        初始化 iMessage 通道

        Args:
            config: 配置项
                - poll_interval: 轮询间隔（秒）
                - allowed_senders: 允许的发送者列表（为空则允许所有）
                - my_ids: 自己的 ID 列表（电话号码/Apple ID），用于过滤自己发给自己的消息
            dm_config: DM 安全策略配置
        """
        super().__init__(ChannelType.IMESSAGE, config, dm_config)

        self._poll_interval = self._config.get("poll_interval", self.DEFAULT_POLL_INTERVAL)
        self._allowed_senders = set(self._config.get("allowed_senders", []))
        self._my_ids = set(self._config.get("my_ids", []))

        self._listening = False
        self._listen_thread: Optional[threading.Thread] = None
        self._last_message_id: Optional[int] = None

        # 记录最近发送的消息内容，用于防止循环回复
        self._recent_sent_contents: List[str] = []
        self._max_recent_sent = 10  # 最多记录10条

    def connect(self) -> bool:
        """连接通道（检查环境）"""
        self._set_status(ChannelStatus.CONNECTING)

        # 检查是否在 macOS 上
        import platform
        if platform.system() != "Darwin":
            self.logger.error("iMessage 通道仅支持 macOS")
            self._set_status(ChannelStatus.ERROR)
            return False

        # 检查数据库是否可访问
        if not self._check_db_access():
            self.logger.error("无法访问 Messages 数据库，请授予完全磁盘访问权限")
            self._set_status(ChannelStatus.ERROR)
            return False

        # 获取最新消息 ID
        self._last_message_id = self._get_latest_message_id()

        self._set_status(ChannelStatus.CONNECTED)
        self.logger.info("iMessage 通道已连接")
        return True

    def disconnect(self) -> None:
        """断开连接"""
        self.stop_listening()
        self._set_status(ChannelStatus.DISCONNECTED)
        self.logger.info("iMessage 通道已断开")

    def send(self, message: OutgoingMessage) -> bool:
        """
        发送消息

        Args:
            message: 要发送的消息

        Returns:
            是否发送成功
        """
        if not self.is_connected:
            self.logger.error("通道未连接")
            return False

        success = self._send_via_applescript(message.channel_id, message.content)

        # 记录发送的内容，用于防止循环回复
        if success:
            self._recent_sent_contents.append(message.content)
            # 保持列表长度
            if len(self._recent_sent_contents) > self._max_recent_sent:
                self._recent_sent_contents.pop(0)

        return success

    def start_listening(self) -> None:
        """开始监听消息"""
        if self._listening:
            return

        self._listening = True
        self._listen_thread = threading.Thread(target=self._poll_messages, daemon=True)
        self._listen_thread.start()
        self.logger.info("开始监听 iMessage 消息")

    def stop_listening(self) -> None:
        """停止监听消息"""
        self._listening = False
        if self._listen_thread:
            self._listen_thread.join(timeout=5)
            self._listen_thread = None
        self.logger.info("停止监听 iMessage 消息")

    def _check_db_access(self) -> bool:
        """检查数据库访问权限"""
        try:
            if not self.CHAT_DB_PATH.exists():
                return False

            conn = sqlite3.connect(f"file:{self.CHAT_DB_PATH}?mode=ro", uri=True)
            conn.execute("SELECT 1 FROM message LIMIT 1")
            conn.close()
            return True
        except Exception as e:
            self.logger.debug(f"数据库访问检查失败: {e}")
            return False

    def _get_latest_message_id(self) -> Optional[int]:
        """获取最新消息 ID"""
        try:
            conn = sqlite3.connect(f"file:{self.CHAT_DB_PATH}?mode=ro", uri=True)
            cursor = conn.execute("SELECT MAX(ROWID) FROM message")
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            self.logger.error(f"获取最新消息 ID 失败: {e}")
            return None

    def _poll_messages(self) -> None:
        """轮询新消息"""
        print(f"[iMessage] 开始轮询，当前 last_message_id: {self._last_message_id}")
        print(f"[iMessage] 配置 - allowed_senders: {self._allowed_senders}, my_ids: {self._my_ids}")
        while self._listening:
            try:
                new_messages = self._fetch_new_messages()
                if new_messages:
                    print(f"[iMessage] 发现 {len(new_messages)} 条新消息")
                for msg in new_messages:
                    print(f"[iMessage] 处理消息: {msg.sender_id} -> {msg.content[:30] if msg.content else ''}")
                    self._emit_message(msg)
            except Exception as e:
                self.logger.error(f"轮询消息失败: {e}")
                print(f"[iMessage] 轮询错误: {e}")
                import traceback
                traceback.print_exc()

            time.sleep(self._poll_interval)

    def _fetch_new_messages(self) -> List[IncomingMessage]:
        """获取新消息"""
        messages = []

        try:
            conn = sqlite3.connect(f"file:{self.CHAT_DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            # 先查询所有新消息（包括自己发的），用于调试
            debug_query = """
                SELECT
                    m.ROWID as id,
                    m.text,
                    m.is_from_me,
                    h.id as sender_id
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ?
                ORDER BY m.ROWID ASC
                LIMIT 10
            """
            debug_cursor = conn.execute(debug_query, (self._last_message_id or 0,))
            debug_rows = debug_cursor.fetchall()
            if debug_rows:
                print(f"[iMessage] 数据库中新消息（ROWID > {self._last_message_id}）:")
                for r in debug_rows:
                    print(f"  ID={r['id']}, is_from_me={r['is_from_me']}, sender={r['sender_id']}, text={r['text'][:30] if r['text'] else 'None'}...")

            # 查询新消息
            query = """
                SELECT
                    m.ROWID as id,
                    m.text,
                    m.date,
                    m.is_from_me,
                    h.id as sender_id,
                    c.chat_identifier
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                LEFT JOIN chat c ON cmj.chat_id = c.ROWID
                WHERE m.ROWID > ?
                    AND m.is_from_me = 0
                    AND m.text IS NOT NULL
                ORDER BY m.ROWID ASC
            """

            cursor = conn.execute(query, (self._last_message_id or 0,))
            rows = cursor.fetchall()

            if rows:
                print(f"[iMessage] 查询到 {len(rows)} 条来自他人的消息")

            for row in rows:
                sender_id = row["sender_id"] or ""
                message_content = row["text"] or ""

                # 过滤自己发给自己的消息
                if self._my_ids and sender_id in self._my_ids:
                    print(f"[iMessage] 跳过消息（发送者在my_ids中）: sender={sender_id}")
                    self._last_message_id = row["id"]
                    continue

                # 检查发送者白名单
                if self._allowed_senders and sender_id not in self._allowed_senders:
                    print(f"[iMessage] 跳过消息（发送者不在白名单中）: sender={sender_id}")
                    self._last_message_id = row["id"]
                    continue

                # 过滤最近发送的消息（防止循环回复）
                if message_content in self._recent_sent_contents:
                    print(f"[iMessage] 跳过自己发送的消息: {message_content[:30]}...")
                    self._last_message_id = row["id"]
                    continue

                # 转换时间戳（macOS 使用 2001-01-01 作为纪元）
                mac_epoch = datetime(2001, 1, 1)
                timestamp = mac_epoch
                if row["date"]:
                    # date 是纳秒级时间戳
                    seconds = row["date"] / 1_000_000_000
                    timestamp = datetime.fromtimestamp(mac_epoch.timestamp() + seconds)

                # 获取附件
                message_id = row["id"]
                attachments = self._get_message_attachments(message_id)

                msg = IncomingMessage(
                    id=str(row["id"]),
                    channel_type=ChannelType.IMESSAGE,
                    channel_id=row["chat_identifier"] or sender_id,
                    sender_id=sender_id,
                    content=message_content,
                    timestamp=timestamp,
                    attachments=attachments
                )
                messages.append(msg)

                # 更新最新消息 ID
                self._last_message_id = row["id"]

            conn.close()

        except Exception as e:
            self.logger.error(f"获取新消息失败: {e}")

        return messages

    def _get_message_attachments(self, message_id: int) -> List[Dict]:
        """
        获取消息的附件

        Args:
            message_id: 消息 ROWID

        Returns:
            附件列表，每个附件包含 type, media_type, data (base64)
        """
        attachments = []

        try:
            conn = sqlite3.connect(f"file:{self.CHAT_DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            # 查询附件
            query = """
                SELECT
                    a.ROWID,
                    a.filename,
                    a.mime_type,
                    a.transfer_name,
                    a.uti
                FROM attachment a
                INNER JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
                WHERE maj.message_id = ?
            """

            cursor = conn.execute(query, (message_id,))
            rows = cursor.fetchall()

            for row in rows:
                filename = row["filename"]
                mime_type = row["mime_type"]
                transfer_name = row["transfer_name"]
                uti = row["uti"]

                # 处理文件路径（macOS 使用 ~ 表示 home 目录）
                if filename:
                    filepath = Path(filename.replace("~", str(Path.home())))

                    # 检查文件是否存在且是支持的图片类型
                    if filepath.exists():
                        suffix = filepath.suffix.lower()

                        if suffix in SUPPORTED_IMAGE_TYPES:
                            attachment = self._read_image_attachment(filepath, mime_type)
                            if attachment:
                                print(f"[iMessage] 读取图片附件: {transfer_name or filepath.name}")
                                attachments.append(attachment)
                        else:
                            print(f"[iMessage] 跳过非图片附件: {transfer_name or filepath.name} ({suffix})")
                    else:
                        print(f"[iMessage] 附件文件不存在: {filepath}")

            conn.close()

        except Exception as e:
            self.logger.error(f"获取附件失败: {e}")
            print(f"[iMessage] 获取附件错误: {e}")
            import traceback
            traceback.print_exc()

        return attachments

    def _read_image_attachment(self, filepath: Path, mime_type: Optional[str] = None) -> Optional[Dict]:
        """
        读取图片附件并转换为 base64

        Args:
            filepath: 文件路径
            mime_type: MIME 类型

        Returns:
            附件字典，包含 type, media_type, data
        """
        try:
            suffix = filepath.suffix.lower()

            # HEIC/HEIF 需要转换为 JPEG（Claude API 不支持 HEIC）
            if suffix in CONVERTIBLE_TYPES:
                print(f"[iMessage] 转换 HEIC 图片为 JPEG...")
                converted_data, converted_mime = self._convert_heic_to_jpeg(filepath)
                if converted_data:
                    return {
                        "type": "image",
                        "media_type": converted_mime,
                        "data": converted_data,
                        "filename": filepath.stem + ".jpg"
                    }
                else:
                    print(f"[iMessage] HEIC 转换失败，跳过此图片")
                    return None

            # 其他格式直接读取
            if not mime_type:
                mime_type, _ = mimetypes.guess_type(str(filepath))

            if not mime_type:
                mime_type = 'image/jpeg'  # 默认使用 jpeg

            # 确保 mime_type 是 Claude 支持的格式
            if mime_type not in {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}:
                mime_type = 'image/jpeg'

            # 读取文件内容
            with open(filepath, 'rb') as f:
                data = f.read()

            # 检查大小，如果超过限制则压缩
            if len(data) > MAX_IMAGE_SIZE:
                print(f"[iMessage] 图片过大 ({len(data)//1024//1024}MB)，正在压缩...")
                data, mime_type = self._compress_image(filepath, data)
                if data is None:
                    print(f"[iMessage] 图片压缩失败，跳过")
                    return None

            # 转换为 base64
            base64_data = base64.b64encode(data).decode('utf-8')

            return {
                "type": "image",
                "media_type": mime_type,
                "data": base64_data,
                "filename": filepath.name
            }

        except Exception as e:
            self.logger.error(f"读取图片失败 {filepath}: {e}")
            print(f"[iMessage] 读取图片错误: {e}")
            return None

    def _compress_image(self, filepath: Path, data: bytes) -> tuple:
        """
        使用 sips 压缩图片

        Args:
            filepath: 原始文件路径
            data: 原始数据

        Returns:
            (compressed_data, mime_type) 元组，失败返回 (None, None)
        """
        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp_path = tmp.name

            # 计算目标尺寸（按比例缩小到 5MB 以下）
            # 假设压缩后大小与像素数成正比
            ratio = (MAX_IMAGE_SIZE / len(data)) ** 0.5
            max_dimension = int(4096 * ratio)  # 最大边长
            max_dimension = max(800, min(max_dimension, 2048))  # 限制在 800-2048 之间

            # 使用 sips 调整大小并转为 JPEG
            result = subprocess.run(
                ['sips', '-s', 'format', 'jpeg',
                 '-s', 'formatOptions', '80',  # JPEG 质量 80%
                 '-Z', str(max_dimension),  # 最大边长
                 str(filepath), '--out', tmp_path],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                self.logger.error(f"sips 压缩失败: {result.stderr}")
                return (None, None)

            # 读取压缩后的文件
            with open(tmp_path, 'rb') as f:
                compressed_data = f.read()

            # 删除临时文件
            Path(tmp_path).unlink(missing_ok=True)

            print(f"[iMessage] 压缩完成: {len(data)//1024}KB -> {len(compressed_data)//1024}KB")

            return (compressed_data, 'image/jpeg')

        except Exception as e:
            self.logger.error(f"图片压缩失败: {e}")
            return (None, None)

    def _convert_heic_to_jpeg(self, filepath: Path) -> tuple:
        """
        使用 macOS sips 命令将 HEIC 转换为 JPEG（同时压缩）

        Args:
            filepath: HEIC 文件路径

        Returns:
            (base64_data, mime_type) 元组，失败返回 (None, None)
        """
        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp_path = tmp.name

            # 使用 sips 转换并压缩（macOS 自带工具）
            # -Z 2048 限制最大边长为 2048 像素
            # formatOptions 80 设置 JPEG 质量为 80%
            result = subprocess.run(
                ['sips', '-s', 'format', 'jpeg',
                 '-s', 'formatOptions', '80',
                 '-Z', '2048',
                 str(filepath), '--out', tmp_path],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                self.logger.error(f"sips 转换失败: {result.stderr}")
                return (None, None)

            # 读取转换后的文件
            with open(tmp_path, 'rb') as f:
                data = f.read()

            # 删除临时文件
            Path(tmp_path).unlink(missing_ok=True)

            # 如果仍然太大，进一步压缩
            if len(data) > MAX_IMAGE_SIZE:
                print(f"[iMessage] 转换后仍过大 ({len(data)//1024}KB)，进一步压缩...")
                # 使用更小的尺寸
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp2:
                    tmp_path2 = tmp2.name

                result = subprocess.run(
                    ['sips', '-s', 'format', 'jpeg',
                     '-s', 'formatOptions', '70',
                     '-Z', '1200',
                     str(filepath), '--out', tmp_path2],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    with open(tmp_path2, 'rb') as f:
                        data = f.read()
                Path(tmp_path2).unlink(missing_ok=True)

            print(f"[iMessage] HEIC 转换完成: {len(data)//1024}KB")

            # 转换为 base64
            base64_data = base64.b64encode(data).decode('utf-8')

            return (base64_data, 'image/jpeg')

        except subprocess.TimeoutExpired:
            self.logger.error("HEIC 转换超时")
            return (None, None)
        except Exception as e:
            self.logger.error(f"HEIC 转换失败: {e}")
            return (None, None)

    def _send_via_applescript(self, recipient: str, content: str) -> bool:
        """
        通过 AppleScript 发送消息

        Args:
            recipient: 接收者（电话号码或 Apple ID）
            content: 消息内容

        Returns:
            是否发送成功
        """
        # 转义特殊字符
        escaped_content = content.replace('\\', '\\\\').replace('"', '\\"')

        script = f'''
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant "{recipient}" of targetService
            send "{escaped_content}" to targetBuddy
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                self.logger.error(f"AppleScript 执行失败: {result.stderr}")
                return False

            self.logger.debug(f"消息已发送至 {recipient}")
            return True

        except subprocess.TimeoutExpired:
            self.logger.error("AppleScript 执行超时")
            return False
        except Exception as e:
            self.logger.error(f"发送消息失败: {e}")
            return False

    def get_recent_chats(self, limit: int = 10) -> List[Dict]:
        """
        获取最近的聊天

        Args:
            limit: 返回数量

        Returns:
            聊天列表
        """
        chats = []

        try:
            conn = sqlite3.connect(f"file:{self.CHAT_DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            query = """
                SELECT
                    c.chat_identifier,
                    c.display_name,
                    MAX(m.date) as last_message_date
                FROM chat c
                LEFT JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
                LEFT JOIN message m ON cmj.message_id = m.ROWID
                GROUP BY c.ROWID
                ORDER BY last_message_date DESC
                LIMIT ?
            """

            cursor = conn.execute(query, (limit,))
            for row in cursor.fetchall():
                chats.append({
                    "chat_id": row["chat_identifier"],
                    "display_name": row["display_name"] or row["chat_identifier"]
                })

            conn.close()

        except Exception as e:
            self.logger.error(f"获取聊天列表失败: {e}")

        return chats
