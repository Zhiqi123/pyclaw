"""
WeChat Mac 客户端通道适配器

通过 AppleScript 和 UI 自动化与 Mac 微信客户端交互。
不依赖网页版，适用于无法登录网页版的账号。
"""

import logging
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional
from datetime import datetime

from .base import (
    BaseChannel, ChannelType, ChannelStatus,
    IncomingMessage, OutgoingMessage
)
from .security import ChannelCapability, ChannelCapabilityInfo, DmPolicyConfig

logger = logging.getLogger(__name__)


class WeChatMacChannel(BaseChannel):
    """
    Mac 微信客户端通道

    通过 AppleScript 和 UI 自动化控制 Mac 微信客户端。

    特点：
    - 不依赖网页版，无账号限制
    - 需要微信客户端保持打开状态
    - 通过剪贴板传递消息
    - 支持监听文件传输助手消息

    使用示例:
        channel = WeChatMacChannel()
        channel.set_on_message(handle_message)
        channel.connect()
        channel.start_listening()  # 开始监听文件传输助手
        channel.send_to_filehelper("Hello!")

    监听模式要求：
    - 微信窗口需要打开并显示文件传输助手对话
    - 需要授予终端"辅助功能"权限
    """

    # 微信 App 名称（AppleScript 用）
    WECHAT_APP = "WeChat"  # 英文名称用于 System Events
    WECHAT_APP_CN = "微信"  # 中文名称用于 activate
    WECHAT_BUNDLE_ID = "com.tencent.xinWeChat"

    def __init__(self, config: Optional[Dict] = None, dm_config: Optional[DmPolicyConfig] = None):
        """
        初始化 Mac 微信通道

        Args:
            config: 配置项
                - search_delay: 搜索等待时间（秒）
                - send_delay: 发送后等待时间（秒）
                - poll_interval: 消息轮询间隔（秒）
                - watch_contact: 要监听的联系人（默认 "文件传输助手"）
            dm_config: DM 安全策略配置
        """
        super().__init__(ChannelType.WECHAT, config, dm_config)

        self._search_delay = self._config.get("search_delay", 0.5)
        self._send_delay = self._config.get("send_delay", 0.3)
        self._poll_interval = self._config.get("poll_interval", 2.0)
        self._watch_contact = self._config.get("watch_contact", "文件传输助手")

        # 记录最近发送的消息，用于防止循环
        self._recent_sent_contents: List[str] = []
        self._max_recent_sent = 10

        # 消息监听
        self._listening = False
        self._listen_thread: Optional[threading.Thread] = None

        # 已处理的消息（用于去重）
        self._seen_messages: List[str] = []
        self._max_seen = 50

    def connect(self) -> bool:
        """连接通道（检查微信是否运行）"""
        self._set_status(ChannelStatus.CONNECTING)

        # 检查是否在 macOS 上
        import platform
        if platform.system() != "Darwin":
            self.logger.error("WeChatMacChannel 仅支持 macOS")
            self._set_status(ChannelStatus.ERROR)
            return False

        # 检查微信是否运行
        if not self._is_wechat_running():
            self.logger.error("微信客户端未运行，请先打开微信")
            self._set_status(ChannelStatus.ERROR)
            return False

        self._set_status(ChannelStatus.CONNECTED)
        self.logger.info("Mac 微信通道已连接")
        return True

    def disconnect(self) -> None:
        """断开连接"""
        self.stop_listening()
        self._set_status(ChannelStatus.DISCONNECTED)
        self.logger.info("Mac 微信通道已断开")

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

        # 发送文本
        if message.content:
            success = self._send_text_to_contact(message.channel_id, message.content)
            if success:
                self._recent_sent_contents.append(message.content)
                if len(self._recent_sent_contents) > self._max_recent_sent:
                    self._recent_sent_contents.pop(0)
            return success

        # 发送附件
        if message.attachments:
            for att in message.attachments:
                file_path = att.get("path")
                if file_path:
                    self._send_file_to_contact(message.channel_id, file_path)

        return True

    def start_listening(self) -> None:
        """
        开始监听消息

        注意：需要先打开微信并进入要监听的对话（如文件传输助手）
        """
        if self._listening:
            return

        # 先确保进入监听的对话
        self.logger.info(f"准备监听 [{self._watch_contact}] 的消息...")
        print(f"[WeChatMac] 请确保微信已打开并显示「{self._watch_contact}」对话")

        self._listening = True
        self._listen_thread = threading.Thread(target=self._poll_messages, daemon=True)
        self._listen_thread.start()
        self.logger.info(f"开始监听 [{self._watch_contact}]")

    def stop_listening(self) -> None:
        """停止监听"""
        self._listening = False
        if self._listen_thread:
            self._listen_thread.join(timeout=5)
            self._listen_thread = None
        self.logger.info("停止监听微信通知")

    # ==================== 核心功能实现 ====================

    def _is_wechat_running(self) -> bool:
        """检查微信是否正在运行"""
        script = f'''
        tell application "System Events"
            return (name of processes) contains "{self.WECHAT_APP}"
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10
            )
            return "true" in result.stdout.lower()
        except Exception as e:
            self.logger.error(f"检查微信状态失败: {e}")
            return False

    def _activate_wechat(self) -> bool:
        """激活微信窗口"""
        # 使用 bundle id 激活，更可靠
        script = f'''
        tell application id "{self.WECHAT_BUNDLE_ID}"
            activate
        end tell
        delay 0.3
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"激活微信失败: {e}")
            return False

    def _search_contact(self, contact: str) -> bool:
        """
        搜索联系人

        Args:
            contact: 联系人名称（如 "文件传输助手"）

        Returns:
            是否成功
        """
        # 使用 Cmd+F 打开搜索，输入联系人名称，回车选中
        script = f'''
        tell application "System Events"
            tell process "{self.WECHAT_APP}"
                -- 按 Cmd+F 打开搜索
                keystroke "f" using command down
                delay 0.3

                -- 清空搜索框并输入联系人
                keystroke "a" using command down
                delay 0.1
                keystroke "{contact}"
                delay {self._search_delay}

                -- 按回车选中第一个结果
                keystroke return
                delay 0.3
            end tell
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=15
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"搜索联系人失败: {e}")
            return False

    def _send_text_via_clipboard(self, text: str) -> bool:
        """
        通过剪贴板发送文本

        Args:
            text: 要发送的文本

        Returns:
            是否成功
        """
        # 先将文本复制到剪贴板
        try:
            process = subprocess.Popen(
                ["pbcopy"],
                stdin=subprocess.PIPE,
                text=True
            )
            process.communicate(input=text)
        except Exception as e:
            self.logger.error(f"复制到剪贴板失败: {e}")
            return False

        # 粘贴并发送
        script = f'''
        tell application "System Events"
            tell process "{self.WECHAT_APP}"
                -- 粘贴
                keystroke "v" using command down
                delay 0.2

                -- 发送
                keystroke return
                delay {self._send_delay}
            end tell
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"发送文本失败: {e}")
            return False

    def _send_text_to_contact(self, contact: str, text: str) -> bool:
        """
        发送文本给指定联系人

        Args:
            contact: 联系人名称
            text: 消息内容

        Returns:
            是否成功
        """
        if not self._activate_wechat():
            return False

        if not self._search_contact(contact):
            return False

        if not self._send_text_via_clipboard(text):
            return False

        self.logger.info(f"已发送消息到 {contact}")
        return True

    def _send_file_to_contact(self, contact: str, file_path: str) -> bool:
        """
        发送文件给指定联系人

        Args:
            contact: 联系人名称
            file_path: 文件路径

        Returns:
            是否成功
        """
        if not Path(file_path).exists():
            self.logger.error(f"文件不存在: {file_path}")
            return False

        if not self._activate_wechat():
            return False

        if not self._search_contact(contact):
            return False

        # 将文件路径复制到剪贴板（作为文件引用）
        script = f'''
        set theFile to POSIX file "{file_path}"
        set the clipboard to theFile

        tell application "System Events"
            tell process "{self.WECHAT_APP}"
                -- 粘贴文件
                keystroke "v" using command down
                delay 0.5

                -- 发送
                keystroke return
                delay 0.5
            end tell
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                self.logger.info(f"已发送文件到 {contact}: {file_path}")
                return True
            else:
                self.logger.error(f"发送文件失败: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"发送文件失败: {e}")
            return False

    def _poll_messages(self) -> None:
        """轮询读取微信对话中的新消息"""
        print(f"[WeChatMac] 开始轮询消息，间隔 {self._poll_interval}s")

        while self._listening:
            try:
                # 读取当前对话的最新消息
                messages = self._read_latest_messages()

                for msg_content in messages:
                    # 跳过空消息
                    if not msg_content or not msg_content.strip():
                        continue

                    # 跳过已处理的消息
                    if msg_content in self._seen_messages:
                        continue

                    # 跳过自己发送的消息
                    if msg_content in self._recent_sent_contents:
                        continue

                    # 记录已处理
                    self._seen_messages.append(msg_content)
                    if len(self._seen_messages) > self._max_seen:
                        self._seen_messages.pop(0)

                    # 构建消息对象
                    incoming = IncomingMessage(
                        id=str(int(time.time() * 1000)),
                        channel_type=ChannelType.WECHAT,
                        channel_id=self._watch_contact,
                        sender_id="self",
                        sender_name=self._watch_contact,
                        content=msg_content,
                        timestamp=datetime.now(),
                        metadata={"source": "wechat_mac"}
                    )

                    print(f"[WeChatMac] 收到消息: {msg_content[:50]}...")
                    self._emit_message(incoming)

            except Exception as e:
                self.logger.error(f"读取消息失败: {e}")

            time.sleep(self._poll_interval)

    def _read_latest_messages(self, count: int = 5) -> List[str]:
        """
        读取微信对话窗口中的最新消息

        Args:
            count: 读取最近几条消息

        Returns:
            消息内容列表
        """
        # 使用 AppleScript 通过 Accessibility API 读取消息
        # 微信的消息列表是 scroll area 中的 static text 元素
        script = f'''
        tell application "System Events"
            tell process "{self.WECHAT_APP}"
                try
                    -- 获取主窗口
                    set mainWindow to window 1

                    -- 尝试获取消息列表区域的文本
                    -- 微信的 UI 结构：window > split group > scroll area > table/outline > text
                    set allTexts to {{}}

                    -- 遍历所有 static text 元素
                    set textElements to every static text of mainWindow
                    repeat with t in textElements
                        try
                            set textValue to value of t
                            if textValue is not missing value and textValue is not "" then
                                set end of allTexts to textValue
                            end if
                        end try
                    end repeat

                    -- 返回最后几条
                    if (count of allTexts) > {count} then
                        return items -{count} thru -1 of allTexts
                    else
                        return allTexts
                    end if
                on error
                    return {{}}
                end try
            end tell
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0 and result.stdout.strip():
                # AppleScript 返回的列表格式是: "item1, item2, item3"
                raw_output = result.stdout.strip()
                if raw_output:
                    # 解析返回的消息
                    messages = [m.strip() for m in raw_output.split(", ") if m.strip()]
                    return messages

        except subprocess.TimeoutExpired:
            self.logger.warning("读取消息超时")
        except Exception as e:
            self.logger.error(f"读取消息失败: {e}")

        return []

    def _read_clipboard_content(self) -> str:
        """读取剪贴板内容"""
        try:
            result = subprocess.run(["pbpaste"], capture_output=True, text=True)
            return result.stdout
        except Exception:
            return ""

    def open_filehelper(self) -> bool:
        """
        打开文件传输助手对话

        Returns:
            是否成功
        """
        if not self._activate_wechat():
            return False

        return self._search_contact("文件传输助手")

    # ==================== 文件传输助手便捷方法 ====================

    def send_to_filehelper(self, content: str) -> bool:
        """
        发送文本到文件传输助手

        Args:
            content: 消息内容

        Returns:
            是否成功
        """
        return self._send_text_to_contact("文件传输助手", content)

    def send_image_to_filehelper(self, file_path: str) -> bool:
        """
        发送图片到文件传输助手

        Args:
            file_path: 图片路径

        Returns:
            是否成功
        """
        return self._send_file_to_contact("文件传输助手", file_path)

    def send_file_to_filehelper(self, file_path: str) -> bool:
        """
        发送文件到文件传输助手

        Args:
            file_path: 文件路径

        Returns:
            是否成功
        """
        return self._send_file_to_contact("文件传输助手", file_path)

    # ==================== 发送给好友 ====================

    def send_to_friend(self, name: str, content: str) -> bool:
        """
        发送文本给好友

        Args:
            name: 好友昵称或备注名
            content: 消息内容

        Returns:
            是否成功
        """
        return self._send_text_to_contact(name, content)

    def send_image(self, name: str, file_path: str) -> bool:
        """
        发送图片给好友

        Args:
            name: 好友昵称或备注名
            file_path: 图片路径

        Returns:
            是否成功
        """
        return self._send_file_to_contact(name, file_path)

    def send_file(self, name: str, file_path: str) -> bool:
        """
        发送文件给好友

        Args:
            name: 好友昵称或备注名
            file_path: 文件路径

        Returns:
            是否成功
        """
        return self._send_file_to_contact(name, file_path)

    # ==================== 通道能力 ====================

    @property
    def capabilities(self) -> ChannelCapabilityInfo:
        """通道能力"""
        return ChannelCapabilityInfo(
            capabilities=(
                ChannelCapability.TEXT |
                ChannelCapability.IMAGE |
                ChannelCapability.FILE
            ),
            max_text_length=10000,
            supported_image_types=["jpg", "jpeg", "png", "gif", "webp"]
        )
