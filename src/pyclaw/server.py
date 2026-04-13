"""
PyClaw Server - 后台服务模块

提供后台运行、通道监听、进程管理功能。
"""

import os
import sys
import signal
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Callable
from datetime import datetime
from dataclasses import dataclass, field

from .core.config import Config
from .core.logger import setup_logger, get_logger
from .channels import ChannelManager, ChannelType, IMessageChannel, WeChatChannel
from .agent import AgentCore
from .llm import LLMRouter
from .memory import MemoryManager

logger = get_logger(__name__)


@dataclass
class ServerConfig:
    """服务器配置"""
    pid_file: str = "~/.pyclaw/pyclaw.pid"
    log_file: str = "~/.pyclaw/logs/server.log"
    channels: List[str] = field(default_factory=lambda: ["imessage"])
    auto_restart: bool = True
    max_restart_attempts: int = 5
    restart_delay: float = 5.0


class PyClawServer:
    """
    PyClaw 后台服务

    管理通道监听、消息处理、进程生命周期。

    使用示例:
        server = PyClawServer(config)
        await server.start()
    """

    def __init__(
        self,
        config: Config,
        server_config: Optional[ServerConfig] = None
    ):
        self.config = config
        self.server_config = server_config or ServerConfig()
        self._running = False
        self._shutdown_event: Optional[asyncio.Event] = None
        self._tasks: List[asyncio.Task] = []
        self._channel_manager: Optional[ChannelManager] = None
        self._agent: Optional[AgentCore] = None
        self._start_time: Optional[datetime] = None
        self._message_count = 0
        self._restart_count = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # 主事件循环引用

    @property
    def pid_file(self) -> Path:
        return Path(self.server_config.pid_file).expanduser()

    @property
    def log_file(self) -> Path:
        return Path(self.server_config.log_file).expanduser()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uptime(self) -> Optional[float]:
        if self._start_time:
            return (datetime.now() - self._start_time).total_seconds()
        return None

    def _write_pid(self) -> None:
        """写入 PID 文件"""
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(os.getpid()))
        logger.info(f"PID 文件已写入: {self.pid_file}")

    def _remove_pid(self) -> None:
        """删除 PID 文件"""
        if self.pid_file.exists():
            self.pid_file.unlink()
            logger.info("PID 文件已删除")

    @classmethod
    def read_pid(cls, pid_file: str = "~/.pyclaw/pyclaw.pid") -> Optional[int]:
        """读取 PID 文件"""
        path = Path(pid_file).expanduser()
        if path.exists():
            try:
                return int(path.read_text().strip())
            except (ValueError, IOError):
                return None
        return None

    @classmethod
    def is_process_running(cls, pid: int) -> bool:
        """检查进程是否运行"""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @classmethod
    def get_server_status(cls, pid_file: str = "~/.pyclaw/pyclaw.pid") -> dict:
        """获取服务器状态"""
        pid = cls.read_pid(pid_file)
        if pid is None:
            return {"status": "stopped", "pid": None}

        if cls.is_process_running(pid):
            return {"status": "running", "pid": pid}
        else:
            # PID 文件存在但进程不存在，清理
            Path(pid_file).expanduser().unlink(missing_ok=True)
            return {"status": "stopped", "pid": None, "stale_pid": pid}

    def _setup_signal_handlers(self) -> None:
        """设置信号处理"""
        loop = asyncio.get_event_loop()

        def handle_signal(sig: signal.Signals) -> None:
            logger.info(f"收到信号 {sig.name}，正在关闭...")
            if self._shutdown_event:
                self._shutdown_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    async def _init_components(self) -> None:
        """初始化组件"""
        logger.info("初始化组件...")
        print("[初始化] 正在初始化组件...")

        # 初始化 LLM Router
        llm_router = LLMRouter(self.config)
        print("[初始化] LLM Router 已创建")

        # 初始化 Memory Manager（需要先创建 Database）
        from .memory import Database
        db_path = self.config.memory.db_path
        database = Database(db_path)
        database.initialize()  # 创建表结构
        memory = MemoryManager(database, self.config)
        print(f"[初始化] Memory Manager 已创建，数据库: {db_path}")

        # 初始化工具注册表并注册内置工具
        from .agent.builtin_tools import create_builtin_registry
        tool_registry = create_builtin_registry()
        print(f"[初始化] 已注册 {len(tool_registry.list_tools())} 个内置工具")

        # 初始化 Agent
        self._agent = AgentCore(llm_router, memory, tool_registry=tool_registry, config=self.config)
        print("[初始化] Agent 已创建")

        # 初始化通道管理器
        self._channel_manager = ChannelManager()

        # 注册启用的通道
        if self.config.channels.imessage.enabled:
            from .channels.security import DmPolicyConfig, DmPolicy

            # 创建安全配置，将 allowed_senders 添加到白名单
            allowed_senders = self.config.channels.imessage.allowed_senders or []
            dm_config = DmPolicyConfig(
                policy=DmPolicy.ALLOWLIST,
                allowlist=set(allowed_senders)
            )

            imessage_config = {
                "poll_interval": self.config.channels.imessage.poll_interval,
                "allowed_senders": allowed_senders,
                "db_path": self.config.channels.imessage.db_path,
                "my_ids": self.config.channels.imessage.my_ids
            }
            imessage_channel = IMessageChannel(imessage_config, dm_config=dm_config)
            self._channel_manager.register(imessage_channel)
            logger.info(f"已注册 iMessage 通道，白名单: {allowed_senders}")

        if self.config.channels.wechat.enabled:
            wechat_config = {
                "auto_login": self.config.channels.wechat.auto_login
            }
            wechat_channel = WeChatChannel(wechat_config)
            self._channel_manager.register(wechat_channel)
            logger.info("已注册 WeChat 通道")

        # 注册消息处理器（同步包装器调用异步处理）
        self._channel_manager.set_on_message(self._sync_handle_message)

        logger.info("组件初始化完成")

    def _sync_handle_message(self, message: "IncomingMessage") -> None:
        """同步消息处理包装器"""
        # 使用 run_coroutine_threadsafe 在主事件循环中调度异步任务
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._handle_message(message),
                self._loop
            )
            # 等待完成（可设置超时）
            future.result(timeout=300)  # 5分钟超时
        except Exception as e:
            print(f"[错误] 调度异步任务失败: {e}")
            import traceback
            traceback.print_exc()

    async def _handle_message(self, message: "IncomingMessage") -> None:
        """处理收到的消息"""
        from .channels import IncomingMessage
        try:
            self._message_count += 1
            sender = message.sender_id
            content = message.content
            channel_type = message.channel_type
            channel_id = message.channel_id
            attachments = message.attachments  # 获取附件

            # 日志显示附件信息
            attachment_info = f" [附件: {len(attachments)}张图片]" if attachments else ""
            logger.info(f"收到消息 [{channel_type.value}] {sender}: {content[:50] if content else ''}...{attachment_info}")
            print(f"[收到消息] {sender}: {content[:50] if content else ''}...{attachment_info}")

            if self._agent:
                # 调用 Agent 处理
                # 使用 sender_id 作为 channel_id，确保同一发送者的对话保持上下文
                print(f"[处理中] 正在处理...")
                agent_response = self._agent.process(
                    content,
                    channel=channel_type.value,
                    channel_id=sender,  # 使用 sender_id 作为对话标识，实现上下文记忆
                    attachments=attachments  # 传递附件给 Agent
                )
                response_text = agent_response.content if agent_response else ""

                # 获取模型名称用于显示
                provider_name = agent_response.provider_used.capitalize() if agent_response.provider_used else "Agent"
                print(f"[{provider_name}] {response_text[:100] if response_text else '无回复'}...")

                # 发送回复
                if self._channel_manager and response_text:
                    success = self._channel_manager.send(
                        channel_type=channel_type,
                        channel_id=sender,  # 回复给发送者
                        content=response_text
                    )
                    if success:
                        logger.info(f"已回复 {sender}")
                        print(f"[已发送] 回复已发送给 {sender}")
                    else:
                        logger.error(f"发送回复失败")
                        print(f"[错误] 发送回复失败")

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            print(f"[错误] 处理消息失败: {e}")
            import traceback
            traceback.print_exc()

    async def _run_channel_listeners(self) -> None:
        """运行通道监听"""
        if not self._channel_manager:
            return

        registered_channels = self._channel_manager.list_channels()

        if not registered_channels:
            logger.warning("没有注册的通道，服务将空转")
            # 保持运行但不监听
            while not self._shutdown_event.is_set():
                await asyncio.sleep(1)
            return

        logger.info(f"启动通道监听: {[c.value for c in registered_channels]}")

        # 连接所有通道
        connect_results = self._channel_manager.connect_all()
        for channel_type, success in connect_results.items():
            if success:
                logger.info(f"通道 {channel_type.value} 连接成功")
            else:
                logger.error(f"通道 {channel_type.value} 连接失败")

        # 启动监听
        self._channel_manager.start_all()

        # 保持运行
        while not self._shutdown_event.is_set():
            await asyncio.sleep(1)

    async def start(self, daemonize: bool = False) -> None:
        """
        启动服务器

        Args:
            daemonize: 是否以守护进程模式运行
        """
        # 检查是否已运行
        status = self.get_server_status(str(self.pid_file))
        if status["status"] == "running":
            logger.error(f"服务已在运行 (PID: {status['pid']})")
            raise RuntimeError(f"Server already running with PID {status['pid']}")

        if daemonize:
            self._daemonize()

        self._running = True
        self._start_time = datetime.now()
        self._shutdown_event = asyncio.Event()
        self._loop = asyncio.get_event_loop()  # 保存主事件循环引用

        # 写入 PID
        self._write_pid()

        # 设置信号处理
        self._setup_signal_handlers()

        # 设置日志（确保控制台输出）
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        setup_logger(
            level="INFO",
            log_file=str(self.log_file),
            console_output=True
        )

        print("=" * 50)
        print("PyClaw Server 启动")
        print(f"PID: {os.getpid()}")
        print(f"日志文件: {self.log_file}")
        print("按 Ctrl+C 停止服务")
        print("=" * 50)

        logger.info("PyClaw Server 启动")
        logger.info(f"PID: {os.getpid()}")
        logger.info(f"配置: {self.config._config_path}")

        try:
            # 初始化组件
            await self._init_components()

            # 运行通道监听
            await self._run_channel_listeners()

        except Exception as e:
            logger.error(f"服务器错误: {e}")
            raise
        finally:
            await self.stop()

    def _daemonize(self) -> None:
        """转为守护进程"""
        # 第一次 fork
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError as e:
            logger.error(f"Fork #1 失败: {e}")
            sys.exit(1)

        # 脱离终端
        os.chdir("/")
        os.setsid()
        os.umask(0)

        # 第二次 fork
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError as e:
            logger.error(f"Fork #2 失败: {e}")
            sys.exit(1)

        # 重定向标准流
        sys.stdout.flush()
        sys.stderr.flush()

        with open("/dev/null", "r") as devnull:
            os.dup2(devnull.fileno(), sys.stdin.fileno())

        log_path = self.log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, "a") as log:
            os.dup2(log.fileno(), sys.stdout.fileno())
            os.dup2(log.fileno(), sys.stderr.fileno())

    async def stop(self) -> None:
        """停止服务器"""
        logger.info("正在停止服务器...")
        self._running = False

        # 取消所有任务
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # 停止通道监听
        if self._channel_manager:
            self._channel_manager.stop_all()
            self._channel_manager.disconnect_all()

        # 删除 PID 文件
        self._remove_pid()

        uptime = self.uptime or 0
        logger.info(f"服务器已停止 (运行时间: {uptime:.0f}秒, 处理消息: {self._message_count})")

    @classmethod
    def stop_by_pid(cls, pid_file: str = "~/.pyclaw/pyclaw.pid") -> bool:
        """
        通过 PID 文件停止服务器

        Returns:
            是否成功停止
        """
        pid = cls.read_pid(pid_file)
        if pid is None:
            return False

        if not cls.is_process_running(pid):
            # 清理过期 PID 文件
            Path(pid_file).expanduser().unlink(missing_ok=True)
            return False

        try:
            os.kill(pid, signal.SIGTERM)
            # 等待进程退出
            import time
            for _ in range(10):
                time.sleep(0.5)
                if not cls.is_process_running(pid):
                    return True
            # 强制终止
            os.kill(pid, signal.SIGKILL)
            return True
        except OSError:
            return False

    def get_stats(self) -> dict:
        """获取运行统计"""
        return {
            "running": self._running,
            "pid": os.getpid() if self._running else None,
            "uptime": self.uptime,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "message_count": self._message_count,
            "restart_count": self._restart_count,
        }


async def run_server(
    config: Config,
    daemonize: bool = False,
    server_config: Optional[ServerConfig] = None
) -> None:
    """
    运行服务器的便捷函数

    Args:
        config: PyClaw 配置
        daemonize: 是否守护进程模式
        server_config: 服务器配置
    """
    server = PyClawServer(config, server_config)
    await server.start(daemonize=daemonize)
