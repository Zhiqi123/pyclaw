"""
内置工具集 - macOS 远程控制工具

提供通过 iMessage 远程控制 Mac 的核心工具。
"""

import base64
import logging
import os
import platform
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .tools import Tool, ToolParameter, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


# ============================================================================
# Shell 命令执行
# ============================================================================

def shell_exec(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
    env: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    执行 Shell 命令

    Args:
        command: 要执行的命令
        timeout: 超时时间（秒）
        working_dir: 工作目录
        env: 额外的环境变量

    Returns:
        包含 stdout, stderr, return_code 的字典
    """
    try:
        # 准备环境变量
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
            env=run_env
        )

        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "return_code": result.returncode,
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"命令超时（{timeout}秒）",
            "return_code": -1,
            "success": False
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
            "success": False
        }


# ============================================================================
# AppleScript 执行
# ============================================================================

def applescript_exec(script: str, timeout: int = 30) -> Dict[str, Any]:
    """
    执行 AppleScript 脚本

    Args:
        script: AppleScript 代码
        timeout: 超时时间（秒）

    Returns:
        执行结果
    """
    if platform.system() != "Darwin":
        return {
            "output": "",
            "error": "AppleScript 仅支持 macOS",
            "success": False
        }

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return {
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.returncode != 0 else "",
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "output": "",
            "error": f"脚本超时（{timeout}秒）",
            "success": False
        }
    except Exception as e:
        return {
            "output": "",
            "error": str(e),
            "success": False
        }


# ============================================================================
# 截屏工具
# ============================================================================

def screenshot(
    output_path: Optional[str] = None,
    region: Optional[str] = None,
    format: str = "png",
    include_cursor: bool = False,
    delay: int = 0
) -> Dict[str, Any]:
    """
    截取屏幕截图

    Args:
        output_path: 输出路径（默认保存到桌面）
        region: 区域 "x,y,width,height" 或 "window" 捕获窗口
        format: 图像格式 (png, jpg, pdf)
        include_cursor: 是否包含鼠标指针
        delay: 延迟秒数

    Returns:
        截图文件路径和 base64 编码
    """
    if platform.system() != "Darwin":
        return {"error": "截屏功能仅支持 macOS", "success": False}

    # 默认输出路径
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.expanduser(f"~/Desktop/screenshot_{timestamp}.{format}")
    else:
        output_path = os.path.expanduser(output_path)

    # 构建命令
    cmd = ["screencapture"]

    if delay > 0:
        cmd.extend(["-T", str(delay)])

    if include_cursor:
        cmd.append("-C")

    if region == "window":
        cmd.append("-w")  # 交互式窗口选择
    elif region:
        # 解析区域 "x,y,width,height"
        try:
            x, y, w, h = map(int, region.split(","))
            cmd.extend(["-R", f"{x},{y},{w},{h}"])
        except ValueError:
            return {"error": "区域格式错误，应为 'x,y,width,height'", "success": False}

    # 格式
    if format in ("jpg", "jpeg"):
        cmd.extend(["-t", "jpg"])
    elif format == "pdf":
        cmd.extend(["-t", "pdf"])

    cmd.append(output_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return {
                "error": result.stderr or "截屏失败",
                "success": False
            }

        # 读取文件并编码
        response = {
            "path": output_path,
            "success": True
        }

        # 如果文件较小，返回 base64
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            if file_size < 1024 * 1024:  # 小于 1MB
                with open(output_path, "rb") as f:
                    response["base64"] = base64.b64encode(f.read()).decode()
                response["size"] = file_size

        return response

    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 剪贴板操作
# ============================================================================

def clipboard_get() -> Dict[str, Any]:
    """获取剪贴板内容"""
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    try:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return {
            "content": result.stdout,
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def clipboard_set(content: str) -> Dict[str, Any]:
    """设置剪贴板内容"""
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    try:
        process = subprocess.Popen(
            ["pbcopy"],
            stdin=subprocess.PIPE,
            text=True
        )
        process.communicate(input=content, timeout=5)
        return {
            "message": "已复制到剪贴板",
            "length": len(content),
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 系统通知
# ============================================================================

def notify(
    title: str,
    message: str,
    subtitle: Optional[str] = None,
    sound: Optional[str] = None
) -> Dict[str, Any]:
    """
    发送系统通知

    Args:
        title: 通知标题
        message: 通知内容
        subtitle: 副标题
        sound: 声音名称 (default, Basso, Blow, Bottle, Frog, Funk, Glass, Hero, Morse, Ping, Pop, Purr, Sosumi, Submarine, Tink)
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    # 转义引号
    title = title.replace('"', '\\"')
    message = message.replace('"', '\\"')

    script = f'display notification "{message}" with title "{title}"'

    if subtitle:
        subtitle = subtitle.replace('"', '\\"')
        script = f'display notification "{message}" with title "{title}" subtitle "{subtitle}"'

    if sound:
        script += f' sound name "{sound}"'

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10
        )
        return {
            "message": "通知已发送",
            "success": result.returncode == 0
        }
    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 打开应用/URL
# ============================================================================

def open_app(app_name: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    打开应用程序

    Args:
        app_name: 应用名称或路径（如 "Safari", "Visual Studio Code", "/Applications/Slack.app"）
        args: 传递给应用的参数
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    cmd = ["open", "-a", app_name]
    if args:
        cmd.append("--args")
        cmd.extend(args)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return {"message": f"已打开 {app_name}", "success": True}
        else:
            return {"error": result.stderr or f"无法打开 {app_name}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def open_url(url: str, browser: Optional[str] = None) -> Dict[str, Any]:
    """
    打开 URL

    Args:
        url: 要打开的 URL
        browser: 指定浏览器（如 "Safari", "Google Chrome"）
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    cmd = ["open"]
    if browser:
        cmd.extend(["-a", browser])
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return {"message": f"已打开 {url}", "success": True}
        else:
            return {"error": result.stderr or f"无法打开 {url}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 系统信息
# ============================================================================

def get_system_info() -> Dict[str, Any]:
    """获取系统信息"""
    info = {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "timestamp": datetime.now().isoformat()
    }

    if platform.system() == "Darwin":
        # macOS 特有信息
        try:
            # 获取 macOS 版本
            result = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True, text=True, timeout=5
            )
            info["macos_version"] = result.stdout.strip()

            # 获取硬件信息
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5
            )
            info["cpu"] = result.stdout.strip()

            # 获取内存
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5
            )
            mem_bytes = int(result.stdout.strip())
            info["memory_gb"] = round(mem_bytes / (1024**3), 1)

            # 获取磁盘使用
            result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                info["disk"] = {
                    "total": parts[1],
                    "used": parts[2],
                    "available": parts[3],
                    "percent_used": parts[4]
                }

            # 获取电池状态
            result = subprocess.run(
                ["pmset", "-g", "batt"],
                capture_output=True, text=True, timeout=5
            )
            info["battery_raw"] = result.stdout.strip()

        except Exception as e:
            info["error"] = str(e)

    return info


def get_running_apps() -> Dict[str, Any]:
    """获取正在运行的应用列表"""
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    script = '''
    tell application "System Events"
        set appList to name of every process whose background only is false
        return appList
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            apps = [app.strip() for app in result.stdout.split(",")]
            return {
                "apps": apps,
                "count": len(apps),
                "success": True
            }
        else:
            return {"error": result.stderr, "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 文件操作
# ============================================================================

def list_files(
    path: str = ".",
    pattern: Optional[str] = None,
    recursive: bool = False,
    include_hidden: bool = False
) -> Dict[str, Any]:
    """
    列出目录中的文件

    Args:
        path: 目录路径
        pattern: 文件名模式（如 "*.txt"）
        recursive: 是否递归
        include_hidden: 是否包含隐藏文件
    """
    try:
        path = os.path.expanduser(path)
        p = Path(path)

        if not p.exists():
            return {"error": f"路径不存在: {path}", "success": False}

        if not p.is_dir():
            return {"error": f"不是目录: {path}", "success": False}

        # 获取文件列表
        if recursive:
            if pattern:
                files = list(p.rglob(pattern))
            else:
                files = list(p.rglob("*"))
        else:
            if pattern:
                files = list(p.glob(pattern))
            else:
                files = list(p.iterdir())

        # 过滤隐藏文件
        if not include_hidden:
            files = [f for f in files if not f.name.startswith(".")]

        # 构建结果
        result = []
        for f in files[:100]:  # 限制返回数量
            try:
                stat = f.stat()
                result.append({
                    "name": f.name,
                    "path": str(f),
                    "is_dir": f.is_dir(),
                    "size": stat.st_size if f.is_file() else None,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except (PermissionError, OSError):
                continue

        return {
            "files": result,
            "count": len(result),
            "total": len(files),
            "path": str(p.absolute()),
            "success": True
        }

    except Exception as e:
        return {"error": str(e), "success": False}


def read_file(path: str, max_size: int = 102400, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    读取文件内容

    Args:
        path: 文件路径
        max_size: 最大读取字节数（默认 100KB）
        encoding: 文件编码
    """
    try:
        path = os.path.expanduser(path)

        if not os.path.exists(path):
            return {"error": f"文件不存在: {path}", "success": False}

        if not os.path.isfile(path):
            return {"error": f"不是文件: {path}", "success": False}

        file_size = os.path.getsize(path)

        with open(path, "r", encoding=encoding) as f:
            content = f.read(max_size)

        return {
            "content": content,
            "size": file_size,
            "truncated": file_size > max_size,
            "path": path,
            "success": True
        }

    except UnicodeDecodeError:
        return {"error": f"无法用 {encoding} 解码文件", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def write_file(path: str, content: str, append: bool = False) -> Dict[str, Any]:
    """
    写入文件

    Args:
        path: 文件路径
        content: 文件内容
        append: 是否追加模式
    """
    try:
        path = os.path.expanduser(path)
        mode = "a" if append else "w"

        # 确保目录存在
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        with open(path, mode, encoding="utf-8") as f:
            f.write(content)

        return {
            "message": f"已{'追加' if append else '写入'} {path}",
            "size": len(content),
            "path": path,
            "success": True
        }

    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 音量和亮度控制
# ============================================================================

def set_volume(level: int, mute: Optional[bool] = None) -> Dict[str, Any]:
    """
    设置系统音量

    Args:
        level: 音量级别 0-100
        mute: 是否静音
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    try:
        if mute is not None:
            mute_cmd = "with output muted" if mute else "without output muted"
            script = f'set volume {mute_cmd}'
            subprocess.run(["osascript", "-e", script], timeout=5)

        if 0 <= level <= 100:
            # AppleScript 音量范围是 0-7
            volume = int(level * 7 / 100)
            script = f'set volume output volume {level}'
            subprocess.run(["osascript", "-e", script], timeout=5)

        # 获取当前状态
        result = subprocess.run(
            ["osascript", "-e", "output volume of (get volume settings)"],
            capture_output=True, text=True, timeout=5
        )
        current = result.stdout.strip()

        return {
            "volume": current,
            "message": f"音量已设置为 {level}%",
            "success": True
        }

    except Exception as e:
        return {"error": str(e), "success": False}


def get_volume() -> Dict[str, Any]:
    """获取当前音量"""
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    try:
        result = subprocess.run(
            ["osascript", "-e", "get volume settings"],
            capture_output=True, text=True, timeout=5
        )
        return {
            "raw": result.stdout.strip(),
            "success": True
        }
    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 电源管理
# ============================================================================

def power_action(action: str) -> Dict[str, Any]:
    """
    电源操作

    Args:
        action: 操作类型
            - sleep: 睡眠
            - lock: 锁屏
            - screensaver: 启动屏幕保护
            - caffeinate: 阻止睡眠（返回进程 ID）
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    actions = {
        "sleep": "pmset sleepnow",
        "lock": "osascript -e 'tell application \"System Events\" to keystroke \"q\" using {command down, control down}'",
        "screensaver": "open -a ScreenSaverEngine",
        "display_sleep": "pmset displaysleepnow"
    }

    if action == "caffeinate":
        # 启动 caffeinate 阻止睡眠
        try:
            process = subprocess.Popen(
                ["caffeinate", "-d", "-i"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return {
                "message": "已阻止系统睡眠",
                "pid": process.pid,
                "stop_command": f"kill {process.pid}",
                "success": True
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    if action not in actions:
        return {
            "error": f"未知操作: {action}",
            "available_actions": list(actions.keys()) + ["caffeinate"],
            "success": False
        }

    try:
        subprocess.run(actions[action], shell=True, timeout=10)
        return {"message": f"已执行 {action}", "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 注册内置工具到 ToolRegistry
# ============================================================================

def register_builtin_tools(registry: ToolRegistry) -> None:
    """将所有内置工具注册到 ToolRegistry"""

    # Shell 执行
    registry.add(Tool(
        name="shell_exec",
        description="执行 Shell 命令并返回结果。可用于运行任何终端命令。",
        parameters=[
            ToolParameter("command", "string", "要执行的 Shell 命令", required=True),
            ToolParameter("timeout", "number", "超时时间（秒），默认 30", default=30),
            ToolParameter("working_dir", "string", "工作目录"),
        ],
        handler=shell_exec,
        category="system"
    ))

    # AppleScript 执行
    registry.add(Tool(
        name="applescript_exec",
        description="执行 AppleScript 脚本，用于 macOS GUI 自动化。",
        parameters=[
            ToolParameter("script", "string", "AppleScript 代码", required=True),
            ToolParameter("timeout", "number", "超时时间（秒），默认 30", default=30),
        ],
        handler=applescript_exec,
        category="system"
    ))

    # 截屏
    registry.add(Tool(
        name="screenshot",
        description="截取屏幕截图，保存到指定路径或桌面。",
        parameters=[
            ToolParameter("output_path", "string", "输出路径（默认桌面）"),
            ToolParameter("region", "string", "区域 'x,y,width,height' 或 'window'"),
            ToolParameter("format", "string", "图像格式", enum=["png", "jpg", "pdf"]),
            ToolParameter("delay", "number", "延迟秒数"),
        ],
        handler=screenshot,
        category="media"
    ))

    # 剪贴板
    registry.add(Tool(
        name="clipboard_get",
        description="获取剪贴板中的文本内容。",
        parameters=[],
        handler=clipboard_get,
        category="system"
    ))

    registry.add(Tool(
        name="clipboard_set",
        description="设置剪贴板内容。",
        parameters=[
            ToolParameter("content", "string", "要复制的内容", required=True),
        ],
        handler=clipboard_set,
        category="system"
    ))

    # 通知
    registry.add(Tool(
        name="notify",
        description="发送 macOS 系统通知。",
        parameters=[
            ToolParameter("title", "string", "通知标题", required=True),
            ToolParameter("message", "string", "通知内容", required=True),
            ToolParameter("subtitle", "string", "副标题"),
            ToolParameter("sound", "string", "提示音", enum=[
                "default", "Basso", "Blow", "Bottle", "Frog",
                "Funk", "Glass", "Hero", "Morse", "Ping",
                "Pop", "Purr", "Sosumi", "Submarine", "Tink"
            ]),
        ],
        handler=notify,
        category="system"
    ))

    # 打开应用
    registry.add(Tool(
        name="open_app",
        description="打开 macOS 应用程序。",
        parameters=[
            ToolParameter("app_name", "string", "应用名称，如 'Safari', 'Visual Studio Code'", required=True),
            ToolParameter("args", "array", "传递给应用的参数"),
        ],
        handler=open_app,
        category="system"
    ))

    # 打开 URL
    registry.add(Tool(
        name="open_url",
        description="在浏览器中打开 URL。",
        parameters=[
            ToolParameter("url", "string", "要打开的 URL", required=True),
            ToolParameter("browser", "string", "指定浏览器，如 'Safari', 'Google Chrome'"),
        ],
        handler=open_url,
        category="system"
    ))

    # 系统信息
    registry.add(Tool(
        name="get_system_info",
        description="获取系统信息，包括 macOS 版本、CPU、内存、磁盘等。",
        parameters=[],
        handler=get_system_info,
        category="system"
    ))

    # 运行中的应用
    registry.add(Tool(
        name="get_running_apps",
        description="获取当前正在运行的应用程序列表。",
        parameters=[],
        handler=get_running_apps,
        category="system"
    ))

    # 文件列表
    registry.add(Tool(
        name="list_files",
        description="列出目录中的文件和文件夹。",
        parameters=[
            ToolParameter("path", "string", "目录路径，默认当前目录", required=True),
            ToolParameter("pattern", "string", "文件名模式，如 '*.txt'"),
            ToolParameter("recursive", "boolean", "是否递归搜索"),
            ToolParameter("include_hidden", "boolean", "是否包含隐藏文件"),
        ],
        handler=list_files,
        category="file"
    ))

    # 读取文件
    registry.add(Tool(
        name="read_file",
        description="读取文件内容。",
        parameters=[
            ToolParameter("path", "string", "文件路径", required=True),
            ToolParameter("max_size", "number", "最大读取字节数，默认 100KB"),
            ToolParameter("encoding", "string", "文件编码，默认 utf-8"),
        ],
        handler=read_file,
        category="file"
    ))

    # 写入文件
    registry.add(Tool(
        name="write_file",
        description="写入内容到文件。",
        parameters=[
            ToolParameter("path", "string", "文件路径", required=True),
            ToolParameter("content", "string", "文件内容", required=True),
            ToolParameter("append", "boolean", "是否追加模式，默认覆盖"),
        ],
        handler=write_file,
        category="file"
    ))

    # 音量控制
    registry.add(Tool(
        name="set_volume",
        description="设置系统音量。",
        parameters=[
            ToolParameter("level", "number", "音量级别 0-100", required=True),
            ToolParameter("mute", "boolean", "是否静音"),
        ],
        handler=set_volume,
        category="system"
    ))

    registry.add(Tool(
        name="get_volume",
        description="获取当前系统音量。",
        parameters=[],
        handler=get_volume,
        category="system"
    ))

    # 电源管理
    registry.add(Tool(
        name="power_action",
        description="执行电源相关操作：sleep（睡眠）、lock（锁屏）、screensaver（屏保）、display_sleep（关闭显示器）、caffeinate（阻止睡眠）。",
        parameters=[
            ToolParameter("action", "string", "操作类型", required=True, enum=[
                "sleep", "lock", "screensaver", "display_sleep", "caffeinate"
            ]),
        ],
        handler=power_action,
        category="system"
    ))

    logger.info(f"已注册 {len(registry.list_tools())} 个内置工具")


# ============================================================================
# 窗口操作工具
# ============================================================================

def get_windows(app_name: Optional[str] = None) -> Dict[str, Any]:
    """
    获取窗口列表

    Args:
        app_name: 应用名称，None 则获取所有窗口
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    if app_name:
        script = f'''
        tell application "System Events"
            tell process "{app_name}"
                set windowList to {{}}
                repeat with w in windows
                    set windowInfo to {{name:(name of w), position:(position of w), size:(size of w)}}
                    set end of windowList to windowInfo
                end repeat
                return windowList
            end tell
        end tell
        '''
    else:
        script = '''
        tell application "System Events"
            set windowList to {}
            repeat with p in (every process whose background only is false)
                set appName to name of p
                repeat with w in windows of p
                    try
                        set windowInfo to {app:appName, name:(name of w)}
                        set end of windowList to windowInfo
                    end try
                end repeat
            end repeat
            return windowList
        end tell
        '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            # 解析 AppleScript 返回的列表
            raw = result.stdout.strip()
            return {
                "windows": raw,
                "success": True
            }
        else:
            return {"error": result.stderr, "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def window_action(
    app_name: str,
    action: str,
    window_index: int = 1
) -> Dict[str, Any]:
    """
    窗口操作

    Args:
        app_name: 应用名称
        action: 操作类型 (minimize, maximize, close, focus, fullscreen)
        window_index: 窗口索引（从1开始）
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    actions = {
        "minimize": f'''
            tell application "System Events"
                tell process "{app_name}"
                    set value of attribute "AXMinimized" of window {window_index} to true
                end tell
            end tell
        ''',
        "maximize": f'''
            tell application "System Events"
                tell process "{app_name}"
                    set value of attribute "AXFullScreen" of window {window_index} to false
                    click (first button of window {window_index} whose subrole is "AXZoomButton")
                end tell
            end tell
        ''',
        "close": f'''
            tell application "{app_name}"
                close window {window_index}
            end tell
        ''',
        "focus": f'''
            tell application "{app_name}"
                activate
                set index of window {window_index} to 1
            end tell
        ''',
        "fullscreen": f'''
            tell application "System Events"
                tell process "{app_name}"
                    set value of attribute "AXFullScreen" of window {window_index} to true
                end tell
            end tell
        ''',
        "restore": f'''
            tell application "System Events"
                tell process "{app_name}"
                    set value of attribute "AXMinimized" of window {window_index} to false
                end tell
            end tell
        '''
    }

    if action not in actions:
        return {
            "error": f"未知操作: {action}",
            "available_actions": list(actions.keys()),
            "success": False
        }

    try:
        result = subprocess.run(
            ["osascript", "-e", actions[action]],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            return {"message": f"已对 {app_name} 窗口执行 {action}", "success": True}
        else:
            return {"error": result.stderr or "操作失败", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def move_window(
    app_name: str,
    x: int,
    y: int,
    window_index: int = 1
) -> Dict[str, Any]:
    """
    移动窗口位置

    Args:
        app_name: 应用名称
        x: X 坐标
        y: Y 坐标
        window_index: 窗口索引
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    script = f'''
    tell application "System Events"
        tell process "{app_name}"
            set position of window {window_index} to {{{x}, {y}}}
        end tell
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return {"message": f"窗口已移动到 ({x}, {y})", "success": True}
        else:
            return {"error": result.stderr, "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def resize_window(
    app_name: str,
    width: int,
    height: int,
    window_index: int = 1
) -> Dict[str, Any]:
    """
    调整窗口大小

    Args:
        app_name: 应用名称
        width: 宽度
        height: 高度
        window_index: 窗口索引
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    script = f'''
    tell application "System Events"
        tell process "{app_name}"
            set size of window {window_index} to {{{width}, {height}}}
        end tell
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return {"message": f"窗口大小已调整为 {width}x{height}", "success": True}
        else:
            return {"error": result.stderr, "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def screenshot_window(
    app_name: str,
    output_path: Optional[str] = None,
    window_index: int = 1
) -> Dict[str, Any]:
    """
    截取特定应用窗口

    Args:
        app_name: 应用名称
        output_path: 输出路径
        window_index: 窗口索引
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    # 先聚焦窗口
    focus_script = f'''
    tell application "{app_name}"
        activate
    end tell
    delay 0.5
    '''

    try:
        subprocess.run(["osascript", "-e", focus_script], timeout=5)

        # 获取窗口 ID
        get_window_id = f'''
        tell application "System Events"
            tell process "{app_name}"
                return id of window {window_index}
            end tell
        end tell
        '''

        # 使用 screencapture -l 截取特定窗口
        # 首先尝试获取窗口列表
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.expanduser(f"~/Desktop/{app_name}_{timestamp}.png")
        else:
            output_path = os.path.expanduser(output_path)

        # 使用交互式窗口选择（-w）自动选择当前激活的窗口
        # 或使用 -l <windowid> 截取特定窗口
        result = subprocess.run(
            ["screencapture", "-o", "-x", output_path],  # -o 不包含阴影, -x 静音
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0 and os.path.exists(output_path):
            response = {
                "path": output_path,
                "app": app_name,
                "success": True
            }

            # 如果文件较小，返回 base64
            file_size = os.path.getsize(output_path)
            if file_size < 2 * 1024 * 1024:  # 小于 2MB
                with open(output_path, "rb") as f:
                    response["base64"] = base64.b64encode(f.read()).decode()
                response["size"] = file_size

            return response
        else:
            return {"error": "截图失败", "success": False}

    except Exception as e:
        return {"error": str(e), "success": False}


def ocr_text(image_path: str) -> Dict[str, Any]:
    """
    OCR 识别图片中的文字（使用 macOS Vision framework）

    Args:
        image_path: 图片路径
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    image_path = os.path.expanduser(image_path)

    if not os.path.exists(image_path):
        return {"error": f"文件不存在: {image_path}", "success": False}

    # 使用 macOS 内置的 shortcuts 命令或 Python Vision
    # 方法1: 使用 swift 脚本调用 Vision framework
    swift_code = '''
    import Vision
    import Foundation
    import AppKit

    let imagePath = CommandLine.arguments[1]
    guard let image = NSImage(contentsOfFile: imagePath),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("ERROR: Cannot load image")
        exit(1)
    }

    let request = VNRecognizeTextRequest { request, error in
        guard let observations = request.results as? [VNRecognizedTextObservation] else {
            print("ERROR: No text found")
            return
        }

        for observation in observations {
            if let topCandidate = observation.topCandidates(1).first {
                print(topCandidate.string)
            }
        }
    }

    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    try? handler.perform([request])
    '''

    # 保存 swift 脚本
    swift_file = tempfile.NamedTemporaryFile(mode='w', suffix='.swift', delete=False)
    swift_file.write(swift_code)
    swift_file.close()

    try:
        # 编译并运行
        result = subprocess.run(
            ["swift", swift_file.name, image_path],
            capture_output=True, text=True, timeout=30
        )

        os.unlink(swift_file.name)

        if result.returncode == 0:
            text = result.stdout.strip()
            return {
                "text": text,
                "lines": text.split('\n') if text else [],
                "success": True
            }
        else:
            # 如果 swift 方式失败，尝试使用 shortcuts（macOS 12+）
            return _ocr_with_shortcuts(image_path)

    except subprocess.TimeoutExpired:
        os.unlink(swift_file.name)
        return {"error": "OCR 超时", "success": False}
    except Exception as e:
        try:
            os.unlink(swift_file.name)
        except:
            pass
        return {"error": str(e), "success": False}


def _ocr_with_shortcuts(image_path: str) -> Dict[str, Any]:
    """使用 macOS Shortcuts 进行 OCR（备选方案）"""
    try:
        # 使用 screencapture + 剪贴板方式
        # 先复制图片到剪贴板，然后用 pdftotext 等工具
        # 这是一个简化的实现

        # 使用 tesseract 如果可用
        result = subprocess.run(
            ["which", "tesseract"],
            capture_output=True, text=True
        )

        if result.returncode == 0:
            result = subprocess.run(
                ["tesseract", image_path, "stdout", "-l", "chi_sim+eng"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return {
                    "text": result.stdout.strip(),
                    "method": "tesseract",
                    "success": True
                }

        return {
            "error": "OCR 不可用，请安装 tesseract: brew install tesseract tesseract-lang",
            "success": False
        }
    except Exception as e:
        return {"error": str(e), "success": False}


def click_at(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
    """
    在指定位置点击鼠标

    Args:
        x: X 坐标
        y: Y 坐标
        button: 鼠标按钮 (left, right)
        clicks: 点击次数
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    # 使用 cliclick 工具（需要安装：brew install cliclick）
    try:
        result = subprocess.run(["which", "cliclick"], capture_output=True)
        if result.returncode != 0:
            # 尝试使用 AppleScript
            click_type = "click" if button == "left" else "right click"
            script = f'''
            tell application "System Events"
                {click_type} at {{{x}, {y}}}
            end tell
            '''
            # AppleScript 不直接支持坐标点击，使用 Python 的替代方案
            return {
                "error": "需要安装 cliclick: brew install cliclick",
                "success": False
            }

        cmd = ["cliclick"]
        if button == "right":
            cmd.append("rc:" + f"{x},{y}")
        else:
            if clicks == 2:
                cmd.append("dc:" + f"{x},{y}")  # double click
            else:
                cmd.append("c:" + f"{x},{y}")  # single click

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            return {"message": f"已在 ({x}, {y}) 点击", "success": True}
        else:
            return {"error": result.stderr, "success": False}

    except Exception as e:
        return {"error": str(e), "success": False}


def type_text(text: str, delay: float = 0.05) -> Dict[str, Any]:
    """
    模拟键盘输入文字

    Args:
        text: 要输入的文字
        delay: 按键间隔（秒）
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    # 转义特殊字符
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')

    script = f'''
    tell application "System Events"
        keystroke "{escaped}"
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode == 0:
            return {"message": f"已输入 {len(text)} 个字符", "success": True}
        else:
            return {"error": result.stderr, "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def press_key(key: str, modifiers: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    模拟按键

    Args:
        key: 按键名称 (return, tab, escape, space, delete, up, down, left, right, f1-f12)
        modifiers: 修饰键列表 (command, control, option, shift)
    """
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    key_codes = {
        "return": 36, "tab": 48, "escape": 53, "space": 49,
        "delete": 51, "backspace": 51,
        "up": 126, "down": 125, "left": 123, "right": 124,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118,
        "f5": 96, "f6": 97, "f7": 98, "f8": 100,
        "f9": 101, "f10": 109, "f11": 103, "f12": 111,
        "home": 115, "end": 119, "pageup": 116, "pagedown": 121
    }

    modifier_map = {
        "command": "command down",
        "control": "control down",
        "option": "option down",
        "shift": "shift down"
    }

    if key.lower() in key_codes:
        key_code = key_codes[key.lower()]
        modifier_str = ""
        if modifiers:
            mods = [modifier_map.get(m.lower(), "") for m in modifiers if m.lower() in modifier_map]
            if mods:
                modifier_str = " using {" + ", ".join(mods) + "}"

        script = f'''
        tell application "System Events"
            key code {key_code}{modifier_str}
        end tell
        '''
    else:
        # 单个字符
        modifier_str = ""
        if modifiers:
            mods = [modifier_map.get(m.lower(), "") for m in modifiers if m.lower() in modifier_map]
            if mods:
                modifier_str = " using {" + ", ".join(mods) + "}"

        script = f'''
        tell application "System Events"
            keystroke "{key}"{modifier_str}
        end tell
        '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )

        if result.returncode == 0:
            mod_desc = f" + {', '.join(modifiers)}" if modifiers else ""
            return {"message": f"已按下 {key}{mod_desc}", "success": True}
        else:
            return {"error": result.stderr, "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def get_screen_size() -> Dict[str, Any]:
    """获取屏幕尺寸"""
    if platform.system() != "Darwin":
        return {"error": "仅支持 macOS", "success": False}

    script = '''
    tell application "Finder"
        get bounds of window of desktop
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )

        if result.returncode == 0:
            # 返回格式: "0, 0, 1920, 1080"
            bounds = result.stdout.strip().split(", ")
            if len(bounds) == 4:
                return {
                    "width": int(bounds[2]),
                    "height": int(bounds[3]),
                    "success": True
                }

        # 备选方案
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=10
        )

        import re
        match = re.search(r'Resolution: (\d+) x (\d+)', result.stdout)
        if match:
            return {
                "width": int(match.group(1)),
                "height": int(match.group(2)),
                "success": True
            }

        return {"error": "无法获取屏幕尺寸", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


# ============================================================================
# 便捷函数：创建包含内置工具的 Registry
# ============================================================================

def create_builtin_registry() -> ToolRegistry:
    """创建包含所有内置工具的 ToolRegistry"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    register_window_tools(registry)  # 注册窗口操作工具

    # 注册浏览器工具（如果 Playwright 可用）
    try:
        from .browser_tools import register_browser_tools
        register_browser_tools(registry)
    except ImportError:
        logger.info("浏览器工具模块未加载")

    return registry


def register_window_tools(registry: ToolRegistry) -> None:
    """注册窗口操作和 GUI 自动化工具"""

    # 获取窗口列表
    registry.add(Tool(
        name="get_windows",
        description="获取窗口列表。可以获取所有应用的窗口，或指定应用的窗口。",
        parameters=[
            ToolParameter("app_name", "string", "应用名称，不指定则获取所有窗口"),
        ],
        handler=get_windows,
        category="window"
    ))

    # 窗口操作
    registry.add(Tool(
        name="window_action",
        description="窗口操作：最小化、最大化、关闭、聚焦、全屏、恢复窗口。",
        parameters=[
            ToolParameter("app_name", "string", "应用名称", required=True),
            ToolParameter("action", "string", "操作类型", required=True, enum=[
                "minimize", "maximize", "close", "focus", "fullscreen", "restore"
            ]),
            ToolParameter("window_index", "number", "窗口索引（从1开始），默认1"),
        ],
        handler=window_action,
        category="window"
    ))

    # 移动窗口
    registry.add(Tool(
        name="move_window",
        description="移动窗口到指定位置。",
        parameters=[
            ToolParameter("app_name", "string", "应用名称", required=True),
            ToolParameter("x", "number", "X 坐标", required=True),
            ToolParameter("y", "number", "Y 坐标", required=True),
            ToolParameter("window_index", "number", "窗口索引，默认1"),
        ],
        handler=move_window,
        category="window"
    ))

    # 调整窗口大小
    registry.add(Tool(
        name="resize_window",
        description="调整窗口大小。",
        parameters=[
            ToolParameter("app_name", "string", "应用名称", required=True),
            ToolParameter("width", "number", "宽度", required=True),
            ToolParameter("height", "number", "高度", required=True),
            ToolParameter("window_index", "number", "窗口索引，默认1"),
        ],
        handler=resize_window,
        category="window"
    ))

    # 截取窗口
    registry.add(Tool(
        name="screenshot_window",
        description="截取指定应用的窗口截图。",
        parameters=[
            ToolParameter("app_name", "string", "应用名称", required=True),
            ToolParameter("output_path", "string", "输出路径（默认桌面）"),
            ToolParameter("window_index", "number", "窗口索引，默认1"),
        ],
        handler=screenshot_window,
        category="window"
    ))

    # OCR 文字识别
    registry.add(Tool(
        name="ocr_text",
        description="OCR 识别图片中的文字。支持中英文。需要先截图，然后对截图进行 OCR。",
        parameters=[
            ToolParameter("image_path", "string", "图片文件路径", required=True),
        ],
        handler=ocr_text,
        category="vision"
    ))

    # 鼠标点击
    registry.add(Tool(
        name="click_at",
        description="在指定屏幕坐标点击鼠标。需要先安装 cliclick: brew install cliclick",
        parameters=[
            ToolParameter("x", "number", "X 坐标", required=True),
            ToolParameter("y", "number", "Y 坐标", required=True),
            ToolParameter("button", "string", "鼠标按钮", enum=["left", "right"]),
            ToolParameter("clicks", "number", "点击次数（1或2）"),
        ],
        handler=click_at,
        category="input"
    ))

    # 键盘输入
    registry.add(Tool(
        name="type_text",
        description="模拟键盘输入文字。用于在当前焦点位置输入文本。",
        parameters=[
            ToolParameter("text", "string", "要输入的文字", required=True),
        ],
        handler=type_text,
        category="input"
    ))

    # 按键
    registry.add(Tool(
        name="press_key",
        description="模拟按键。支持功能键、方向键和修饰键组合（如 Cmd+C）。",
        parameters=[
            ToolParameter("key", "string", "按键名称（return/tab/escape/space/delete/up/down/left/right/f1-f12）或单个字符", required=True),
            ToolParameter("modifiers", "array", "修饰键列表（command/control/option/shift）"),
        ],
        handler=press_key,
        category="input"
    ))

    # 获取屏幕尺寸
    registry.add(Tool(
        name="get_screen_size",
        description="获取屏幕分辨率。",
        parameters=[],
        handler=get_screen_size,
        category="system"
    ))

    logger.info(f"已注册窗口操作工具，当前共 {len(registry.list_tools())} 个工具")