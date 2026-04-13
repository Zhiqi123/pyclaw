"""
WeChat 通道适配器

通过 itchat 库与微信交互（需要扫码登录）。
"""

import base64
import logging
import mimetypes
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .base import (
    BaseChannel, ChannelType, ChannelStatus,
    IncomingMessage, OutgoingMessage
)
from .security import ChannelCapability, ChannelCapabilityInfo, DmPolicyConfig

# Claude API 支持的图片类型
CLAUDE_SUPPORTED_TYPES = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
# Claude API 图片大小限制（5MB）
MAX_IMAGE_SIZE = 5 * 1024 * 1024

logger = logging.getLogger(__name__)


class WeChatChannel(BaseChannel):
    """
    微信通道

    通过 itchat 库实现微信消息收发。

    注意：
    - 需要安装 itchat: pip install itchat-uos
    - 首次使用需要扫码登录
    - 微信网页版可能被限制

    使用示例:
        channel = WeChatChannel()
        channel.set_on_message(handle_message)
        channel.connect()  # 会弹出二维码
        channel.start_listening()
    """

    def __init__(self, config: Optional[Dict] = None, dm_config: Optional[DmPolicyConfig] = None):
        """
        初始化微信通道

        Args:
            config: 配置项
                - hot_reload: 是否启用热重载（保持登录状态）
                - qr_callback: 二维码回调函数
                - allowed_users: 允许的用户列表
                - download_dir: 文件下载目录（默认使用临时目录）
            dm_config: DM 安全策略配置
        """
        super().__init__(ChannelType.WECHAT, config, dm_config)

        self._hot_reload = self._config.get("hot_reload", True)
        self._qr_callback = self._config.get("qr_callback")
        self._allowed_users = set(self._config.get("allowed_users", []))
        self._download_dir = Path(self._config.get("download_dir", tempfile.gettempdir()))

        self._itchat = None
        self._listening = False
        self._listen_thread: Optional[threading.Thread] = None

        # 用户信息缓存
        self._user_cache: Dict[str, Dict] = {}

        # 记录最近发送的消息内容，用于防止循环回复
        self._recent_sent_contents: List[str] = []
        self._max_recent_sent = 10  # 最多记录10条

        # 文件传输助手用户名
        self._filehelper = "filehelper"

    def connect(self) -> bool:
        """连接微信（扫码登录）"""
        self._set_status(ChannelStatus.CONNECTING)

        try:
            import itchat
            self._itchat = itchat
        except ImportError:
            self.logger.error("请安装 itchat: pip install itchat-uos")
            self._set_status(ChannelStatus.ERROR)
            return False

        try:
            # 登录
            self._itchat.auto_login(
                hotReload=self._hot_reload,
                qrCallback=self._qr_callback,
                enableCmdQR=2 if not self._qr_callback else False
            )

            self._set_status(ChannelStatus.CONNECTED)
            self.logger.info("微信通道已连接")
            return True

        except Exception as e:
            self.logger.error(f"微信登录失败: {e}")
            self._set_status(ChannelStatus.ERROR)
            return False

    def disconnect(self) -> None:
        """断开连接"""
        self.stop_listening()

        if self._itchat:
            try:
                self._itchat.logout()
            except Exception:
                pass

        self._set_status(ChannelStatus.DISCONNECTED)
        self.logger.info("微信通道已断开")

    def send(self, message: OutgoingMessage) -> bool:
        """
        发送消息

        Args:
            message: 要发送的消息（支持文本和附件）

        Returns:
            是否发送成功
        """
        if not self.is_connected or not self._itchat:
            self.logger.error("通道未连接")
            return False

        try:
            success = True

            # 发送附件
            if message.attachments:
                for attachment in message.attachments:
                    att_type = attachment.get("type", "")
                    if att_type == "image":
                        # 图片附件
                        file_path = attachment.get("path")
                        if file_path:
                            if not self._send_image(message.channel_id, file_path):
                                success = False
                    elif att_type == "file":
                        # 文件附件
                        file_path = attachment.get("path")
                        if file_path:
                            if not self._send_file(message.channel_id, file_path):
                                success = False

            # 发送文本内容
            if message.content:
                result = self._itchat.send(message.content, toUserName=message.channel_id)

                if result.get("BaseResponse", {}).get("Ret") == 0:
                    self.logger.debug(f"消息已发送至 {message.channel_id}")
                    # 记录发送的内容，用于防止循环回复
                    self._recent_sent_contents.append(message.content)
                    if len(self._recent_sent_contents) > self._max_recent_sent:
                        self._recent_sent_contents.pop(0)
                else:
                    self.logger.error(f"发送失败: {result}")
                    success = False

            return success

        except Exception as e:
            self.logger.error(f"发送消息失败: {e}")
            return False

    def start_listening(self) -> None:
        """开始监听消息"""
        if self._listening or not self._itchat:
            return

        # 注册文本消息处理器
        @self._itchat.msg_register([self._itchat.content.TEXT])
        def handle_text(msg):
            self._handle_message(msg, msg_type="text")

        @self._itchat.msg_register([self._itchat.content.TEXT], isGroupChat=True)
        def handle_group_text(msg):
            self._handle_message(msg, is_group=True, msg_type="text")

        # 注册图片消息处理器
        @self._itchat.msg_register([self._itchat.content.PICTURE])
        def handle_picture(msg):
            self._handle_message(msg, msg_type="picture")

        @self._itchat.msg_register([self._itchat.content.PICTURE], isGroupChat=True)
        def handle_group_picture(msg):
            self._handle_message(msg, is_group=True, msg_type="picture")

        # 注册文件/附件消息处理器
        @self._itchat.msg_register([self._itchat.content.ATTACHMENT])
        def handle_attachment(msg):
            self._handle_message(msg, msg_type="attachment")

        @self._itchat.msg_register([self._itchat.content.ATTACHMENT], isGroupChat=True)
        def handle_group_attachment(msg):
            self._handle_message(msg, is_group=True, msg_type="attachment")

        # 注册视频消息处理器
        @self._itchat.msg_register([self._itchat.content.VIDEO])
        def handle_video(msg):
            self._handle_message(msg, msg_type="video")

        # 注册录音消息处理器
        @self._itchat.msg_register([self._itchat.content.RECORDING])
        def handle_recording(msg):
            self._handle_message(msg, msg_type="recording")

        # ===== 文件传输助手特殊处理 =====
        # 监听自己发送的消息（用于接收手机发到文件传输助手的内容）
        @self._itchat.msg_register([self._itchat.content.TEXT], isFriendChat=True, isMpChat=False)
        def handle_self_text(msg):
            if msg.get("ToUserName") == self._filehelper:
                self._handle_filehelper_message(msg, msg_type="text")

        @self._itchat.msg_register([self._itchat.content.PICTURE], isFriendChat=True, isMpChat=False)
        def handle_self_picture(msg):
            if msg.get("ToUserName") == self._filehelper:
                self._handle_filehelper_message(msg, msg_type="picture")

        @self._itchat.msg_register([self._itchat.content.ATTACHMENT], isFriendChat=True, isMpChat=False)
        def handle_self_attachment(msg):
            if msg.get("ToUserName") == self._filehelper:
                self._handle_filehelper_message(msg, msg_type="attachment")

        self._listening = True
        self._listen_thread = threading.Thread(
            target=self._itchat.run,
            kwargs={"blockThread": False},
            daemon=True
        )
        self._listen_thread.start()
        self.logger.info("开始监听微信消息")

    def stop_listening(self) -> None:
        """停止监听消息"""
        self._listening = False
        if self._listen_thread:
            self._listen_thread = None
        self.logger.info("停止监听微信消息")

    def _handle_message(self, msg: Dict, is_group: bool = False, msg_type: str = "text") -> None:
        """处理接收到的消息"""
        try:
            sender_id = msg.get("FromUserName", "")
            actual_sender = msg.get("ActualUserName", sender_id) if is_group else sender_id

            # 检查用户白名单
            if self._allowed_users:
                sender_info = self._get_user_info(actual_sender)
                nick_name = sender_info.get("NickName", "")
                if actual_sender not in self._allowed_users and nick_name not in self._allowed_users:
                    return

            # 获取消息内容
            message_content = msg.get("Text", "")

            # 防止循环回复
            if msg_type == "text" and message_content in self._recent_sent_contents:
                self.logger.debug(f"跳过自己发送的消息: {message_content[:30]}...")
                return

            # 处理附件
            attachments = []
            if msg_type in ("picture", "video", "attachment", "recording"):
                attachment = self._download_attachment(msg, msg_type)
                if attachment:
                    attachments.append(attachment)
                    # 对于图片/文件消息，如果没有文本，生成描述
                    if not message_content:
                        type_names = {
                            "picture": "[图片]",
                            "video": "[视频]",
                            "attachment": "[文件]",
                            "recording": "[语音]"
                        }
                        message_content = type_names.get(msg_type, "[附件]")

            # 构建消息对象
            incoming = IncomingMessage(
                id=msg.get("MsgId", ""),
                channel_type=ChannelType.WECHAT,
                channel_id=sender_id,
                sender_id=actual_sender,
                sender_name=self._get_display_name(actual_sender),
                content=message_content,
                timestamp=datetime.now(),
                attachments=attachments,
                metadata={
                    "is_group": is_group,
                    "msg_type": msg_type,
                    "raw": msg
                }
            )

            self._emit_message(incoming)

        except Exception as e:
            self.logger.error(f"处理消息失败: {e}")

    def _handle_filehelper_message(self, msg: Dict, msg_type: str = "text") -> None:
        """
        处理发送到文件传输助手的消息（手机端发送）

        Args:
            msg: itchat 消息对象
            msg_type: 消息类型
        """
        try:
            # 获取消息内容
            message_content = msg.get("Text", "")

            # 跳过 PyClaw 自己发送的消息
            if message_content in self._recent_sent_contents:
                return

            # 处理附件
            attachments = []
            if msg_type in ("picture", "attachment"):
                attachment = self._download_attachment(msg, msg_type)
                if attachment:
                    attachments.append(attachment)
                    if not message_content:
                        type_names = {"picture": "[图片]", "attachment": "[文件]"}
                        message_content = type_names.get(msg_type, "[附件]")

            # 构建消息对象
            incoming = IncomingMessage(
                id=msg.get("MsgId", ""),
                channel_type=ChannelType.WECHAT,
                channel_id=self._filehelper,
                sender_id="self",  # 标记为自己发送
                sender_name="文件传输助手",
                content=message_content,
                timestamp=datetime.now(),
                attachments=attachments,
                metadata={
                    "is_from_filehelper": True,
                    "msg_type": msg_type,
                    "raw": msg
                }
            )

            self._emit_message(incoming)
            self.logger.info(f"[文件传输助手] 收到: {message_content[:50]}...")

        except Exception as e:
            self.logger.error(f"处理文件传输助手消息失败: {e}")

    def _download_attachment(self, msg: Dict, msg_type: str) -> Optional[Dict]:
        """
        下载消息附件

        Args:
            msg: itchat 消息对象
            msg_type: 消息类型 (picture/video/attachment/recording)

        Returns:
            附件字典，包含 type, media_type, data (base64), filename
        """
        try:
            # 生成文件名
            file_name = msg.get("FileName", "")
            if not file_name:
                ext_map = {
                    "picture": ".jpg",
                    "video": ".mp4",
                    "recording": ".mp3",
                    "attachment": ""
                }
                file_name = f"{msg.get('MsgId', 'file')}{ext_map.get(msg_type, '')}"

            # 下载文件到临时目录
            file_path = self._download_dir / file_name
            msg.download(str(file_path))

            if not file_path.exists():
                self.logger.error(f"附件下载失败: {file_name}")
                return None

            # 读取文件内容
            with open(file_path, 'rb') as f:
                data = f.read()

            # 检查文件大小
            file_size = len(data)

            # 获取 MIME 类型
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if not mime_type:
                mime_type = "application/octet-stream"

            # 对于图片类型，检查是否需要压缩
            if msg_type == "picture":
                suffix = file_path.suffix.lower()

                # 检查是否是支持的图片类型
                if suffix not in CLAUDE_SUPPORTED_TYPES:
                    self.logger.warning(f"不支持的图片格式: {suffix}")
                    # 仍然返回，但标记为文件类型
                    return {
                        "type": "file",
                        "media_type": mime_type,
                        "data": base64.b64encode(data).decode('utf-8'),
                        "filename": file_name,
                        "path": str(file_path),
                        "size": file_size
                    }

                # 如果图片过大，压缩
                if file_size > MAX_IMAGE_SIZE:
                    self.logger.info(f"图片过大 ({file_size // 1024}KB)，正在压缩...")
                    data, mime_type = self._compress_image(file_path, data)
                    if data is None:
                        self.logger.error("图片压缩失败")
                        return None

                return {
                    "type": "image",
                    "media_type": mime_type,
                    "data": base64.b64encode(data).decode('utf-8'),
                    "filename": file_name,
                    "path": str(file_path),
                    "size": len(data)
                }

            # 其他类型作为文件返回
            return {
                "type": "file",
                "media_type": mime_type,
                "data": base64.b64encode(data).decode('utf-8'),
                "filename": file_name,
                "path": str(file_path),
                "size": file_size
            }

        except Exception as e:
            self.logger.error(f"下载附件失败: {e}")
            return None

    def _compress_image(self, filepath: Path, data: bytes) -> tuple:
        """
        压缩图片（使用 PIL 如果可用，否则跳过）

        Args:
            filepath: 文件路径
            data: 原始数据

        Returns:
            (compressed_data, mime_type) 元组
        """
        try:
            from PIL import Image
            import io

            # 打开图片
            img = Image.open(io.BytesIO(data))

            # 计算目标尺寸
            ratio = (MAX_IMAGE_SIZE / len(data)) ** 0.5
            max_dimension = int(max(img.size) * ratio)
            max_dimension = max(800, min(max_dimension, 2048))

            # 调整大小
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            # 保存为 JPEG
            output = io.BytesIO()
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            img.save(output, format='JPEG', quality=80, optimize=True)
            compressed_data = output.getvalue()

            self.logger.info(f"压缩完成: {len(data) // 1024}KB -> {len(compressed_data) // 1024}KB")
            return (compressed_data, 'image/jpeg')

        except ImportError:
            self.logger.warning("PIL 未安装，无法压缩图片")
            return (data, 'image/jpeg')
        except Exception as e:
            self.logger.error(f"图片压缩失败: {e}")
            return (data, 'image/jpeg')

    def _get_user_info(self, user_name: str) -> Dict:
        """获取用户信息（带缓存）"""
        if user_name in self._user_cache:
            return self._user_cache[user_name]

        if not self._itchat:
            return {}

        try:
            # 尝试从好友列表获取
            friends = self._itchat.get_friends(update=False)
            for friend in friends:
                if friend.get("UserName") == user_name:
                    self._user_cache[user_name] = friend
                    return friend

            # 尝试搜索
            info = self._itchat.search_friends(userName=user_name)
            if info:
                self._user_cache[user_name] = info
                return info

        except Exception:
            pass

        return {}

    def _get_display_name(self, user_name: str) -> str:
        """获取显示名称"""
        info = self._get_user_info(user_name)
        return info.get("RemarkName") or info.get("NickName") or user_name

    def get_friends(self) -> List[Dict]:
        """
        获取好友列表

        Returns:
            好友列表
        """
        if not self._itchat:
            return []

        try:
            friends = self._itchat.get_friends(update=True)
            return [
                {
                    "user_name": f.get("UserName"),
                    "nick_name": f.get("NickName"),
                    "remark_name": f.get("RemarkName")
                }
                for f in friends
            ]
        except Exception as e:
            self.logger.error(f"获取好友列表失败: {e}")
            return []

    def get_chatrooms(self) -> List[Dict]:
        """
        获取群聊列表

        Returns:
            群聊列表
        """
        if not self._itchat:
            return []

        try:
            chatrooms = self._itchat.get_chatrooms(update=True)
            return [
                {
                    "user_name": c.get("UserName"),
                    "nick_name": c.get("NickName"),
                    "member_count": c.get("MemberCount", 0)
                }
                for c in chatrooms
            ]
        except Exception as e:
            self.logger.error(f"获取群聊列表失败: {e}")
            return []

    def send_to_friend(self, nick_name: str, content: str) -> bool:
        """
        通过昵称发送消息给好友

        Args:
            nick_name: 好友昵称或备注名
            content: 消息内容

        Returns:
            是否发送成功
        """
        if not self._itchat:
            return False

        try:
            # 先搜索好友
            friends = self._itchat.search_friends(name=nick_name)
            if not friends:
                friends = self._itchat.search_friends(remarkName=nick_name)

            if not friends:
                self.logger.error(f"未找到好友: {nick_name}")
                return False

            user_name = friends[0].get("UserName")
            return self.send_text(user_name, content)

        except Exception as e:
            self.logger.error(f"发送消息失败: {e}")
            return False

    def _send_image(self, to_user: str, file_path: str) -> bool:
        """
        发送图片

        Args:
            to_user: 接收者用户名
            file_path: 图片文件路径

        Returns:
            是否发送成功
        """
        if not self._itchat:
            return False

        try:
            result = self._itchat.send_image(file_path, toUserName=to_user)
            if result.get("BaseResponse", {}).get("Ret") == 0:
                self.logger.debug(f"图片已发送至 {to_user}")
                return True
            else:
                self.logger.error(f"发送图片失败: {result}")
                return False
        except Exception as e:
            self.logger.error(f"发送图片失败: {e}")
            return False

    def _send_file(self, to_user: str, file_path: str) -> bool:
        """
        发送文件

        Args:
            to_user: 接收者用户名
            file_path: 文件路径

        Returns:
            是否发送成功
        """
        if not self._itchat:
            return False

        try:
            result = self._itchat.send_file(file_path, toUserName=to_user)
            if result.get("BaseResponse", {}).get("Ret") == 0:
                self.logger.debug(f"文件已发送至 {to_user}")
                return True
            else:
                self.logger.error(f"发送文件失败: {result}")
                return False
        except Exception as e:
            self.logger.error(f"发送文件失败: {e}")
            return False

    def send_image(self, to_user: str, file_path: str) -> bool:
        """
        发送图片（公开方法）

        Args:
            to_user: 接收者用户名（可以是 UserName 或昵称）
            file_path: 图片文件路径

        Returns:
            是否发送成功
        """
        if not self.is_connected:
            self.logger.error("通道未连接")
            return False

        # 如果不是 UserName 格式，尝试搜索好友
        if not to_user.startswith("@"):
            friends = self._itchat.search_friends(name=to_user)
            if not friends:
                friends = self._itchat.search_friends(remarkName=to_user)
            if friends:
                to_user = friends[0].get("UserName")
            else:
                self.logger.error(f"未找到用户: {to_user}")
                return False

        return self._send_image(to_user, file_path)

    def send_file(self, to_user: str, file_path: str) -> bool:
        """
        发送文件（公开方法）

        Args:
            to_user: 接收者用户名（可以是 UserName 或昵称）
            file_path: 文件路径

        Returns:
            是否发送成功
        """
        if not self.is_connected:
            self.logger.error("通道未连接")
            return False

        # 如果不是 UserName 格式，尝试搜索好友
        if not to_user.startswith("@"):
            friends = self._itchat.search_friends(name=to_user)
            if not friends:
                friends = self._itchat.search_friends(remarkName=to_user)
            if friends:
                to_user = friends[0].get("UserName")
            else:
                self.logger.error(f"未找到用户: {to_user}")
                return False

        return self._send_file(to_user, file_path)

    # ==================== 文件传输助手功能 ====================

    def send_to_filehelper(self, content: str) -> bool:
        """
        发送文本消息到文件传输助手

        Args:
            content: 消息内容

        Returns:
            是否发送成功
        """
        return self.send_text(self._filehelper, content)

    def send_image_to_filehelper(self, file_path: str) -> bool:
        """
        发送图片到文件传输助手

        Args:
            file_path: 图片文件路径

        Returns:
            是否发送成功
        """
        return self._send_image(self._filehelper, file_path)

    def send_file_to_filehelper(self, file_path: str) -> bool:
        """
        发送文件到文件传输助手

        Args:
            file_path: 文件路径

        Returns:
            是否发送成功
        """
        return self._send_file(self._filehelper, file_path)

    # ==================== 通道能力声明 ====================

    @property
    def capabilities(self) -> ChannelCapabilityInfo:
        """
        获取通道能力信息

        微信通道支持：文本、图片、文件、视频、语音
        """
        return ChannelCapabilityInfo(
            capabilities=(
                ChannelCapability.TEXT |
                ChannelCapability.IMAGE |
                ChannelCapability.FILE |
                ChannelCapability.VIDEO |
                ChannelCapability.AUDIO
            ),
            max_text_length=10000,
            max_file_size=MAX_IMAGE_SIZE,
            supported_image_types=list(CLAUDE_SUPPORTED_TYPES)
        )
