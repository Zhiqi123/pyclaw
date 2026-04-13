"""
PyClaw CLI - 命令行入口

提供命令行界面与 PyClaw 交互。
"""

import sys
import os
import asyncio
import logging
from typing import Optional

try:
    import click
except ImportError:
    print("请安装 click: pip install click")
    sys.exit(1)

from .core.config import Config
from .core.logger import setup_logger, get_logger
from .llm.router import LLMRouter
from .llm.task_detector import TaskType
from .agent import AgentCore
from .memory import MemoryManager
from .channels import ChannelManager, ChannelType


# 版本信息
__version__ = "0.1.0"


def get_config_path() -> str:
    """获取配置文件路径"""
    # 优先使用环境变量
    if os.environ.get("PYCLAW_CONFIG"):
        return os.environ["PYCLAW_CONFIG"]

    # 检查当前目录
    if os.path.exists("pyclaw.yaml"):
        return "pyclaw.yaml"
    if os.path.exists("config.yaml"):
        return "config.yaml"

    # 检查用户目录
    home_config = os.path.expanduser("~/.pyclaw/config.yaml")
    if os.path.exists(home_config):
        return home_config

    return ""


@click.group()
@click.version_option(version=__version__, prog_name="pyclaw")
@click.option("--config", "-c", type=click.Path(), help="配置文件路径")
@click.option("--verbose", "-v", is_flag=True, help="详细输出")
@click.option("--debug", "-d", is_flag=True, help="调试模式")
@click.pass_context
def cli(ctx, config: Optional[str], verbose: bool, debug: bool):
    """
    PyClaw - 轻量级个人 AI 助手系统

    使用示例:

        pyclaw chat "你好"

        pyclaw chat --provider deepseek "解释一下快速排序"

        pyclaw server --port 8080
    """
    ctx.ensure_object(dict)

    # 设置日志级别
    log_level = "DEBUG" if debug else ("INFO" if verbose else "WARNING")
    setup_logger(level=log_level)

    # 加载配置
    config_path = config or get_config_path()
    cfg = Config()

    if config_path and os.path.exists(config_path):
        cfg.load(config_path)
        if verbose:
            click.echo(f"已加载配置: {config_path}")
    else:
        cfg.load()  # 使用默认配置

    ctx.obj["config"] = cfg
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug


@cli.command()
@click.argument("message")
@click.option("--provider", "-p", type=click.Choice(["claude", "deepseek", "qwen", "doubao"]),
              help="指定 LLM 提供商")
@click.option("--task", "-t", type=click.Choice([t.value for t in TaskType]),
              help="指定任务类型")
@click.option("--system", "-s", type=str, help="系统提示词")
@click.option("--stream", is_flag=True, help="流式输出（暂不支持）")
@click.pass_context
def chat(ctx, message: str, provider: Optional[str], task: Optional[str],
         system: Optional[str], stream: bool):
    """
    与 AI 对话

    示例:

        pyclaw chat "你好，请介绍一下自己"

        pyclaw chat -p claude "帮我写一个 Python 快速排序"

        pyclaw chat -t code_generation "实现二分查找"
    """
    config = ctx.obj["config"]
    verbose = ctx.obj["verbose"]

    try:
        router = LLMRouter(config)

        # 检查可用的 Provider
        available = router.get_available_providers()
        if not available:
            click.echo("错误: 没有可用的 LLM Provider，请检查配置文件中的 API Key", err=True)
            click.echo("\n提示: 创建 config.yaml 并配置 API Key，或设置环境变量:", err=True)
            click.echo("  export ANTHROPIC_API_KEY=your_key", err=True)
            click.echo("  export DEEPSEEK_API_KEY=your_key", err=True)
            sys.exit(1)

        if verbose:
            click.echo(f"可用的 Provider: {', '.join(available)}")

        # 构建消息
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})

        # 解析任务类型
        task_type = TaskType(task) if task else None

        # 调用 LLM
        if verbose:
            click.echo(f"正在调用 LLM...")

        response = router.chat(
            messages=messages,
            provider=provider,
            task_type=task_type
        )

        # 输出结果
        click.echo(response.content)

        if verbose:
            click.echo(f"\n---")
            click.echo(f"模型: {response.model}")
            if response.usage:
                click.echo(f"Token 使用: {response.usage}")

    except ValueError as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"调用失败: {e}", err=True)
        if ctx.obj["debug"]:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option("--provider", "-p", type=click.Choice(["claude", "deepseek", "qwen", "doubao"]),
              help="指定 LLM 提供商")
@click.option("--system", "-s", type=str, help="系统提示词")
@click.pass_context
def repl(ctx, provider: Optional[str], system: Optional[str]):
    """
    交互式对话模式 (REPL)

    进入交互式对话，输入 'exit' 或 'quit' 退出。

    示例:

        pyclaw repl

        pyclaw repl -p claude
    """
    config = ctx.obj["config"]
    verbose = ctx.obj["verbose"]

    try:
        router = LLMRouter(config)

        available = router.get_available_providers()
        if not available:
            click.echo("错误: 没有可用的 LLM Provider", err=True)
            sys.exit(1)

        click.echo("PyClaw 交互模式 (输入 'exit' 退出)")
        click.echo(f"可用 Provider: {', '.join(available)}")
        click.echo("-" * 40)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})

        while True:
            try:
                user_input = click.prompt("You", prompt_suffix="> ")
            except click.Abort:
                click.echo("\n再见!")
                break

            if user_input.lower() in ["exit", "quit", "q"]:
                click.echo("再见!")
                break

            if user_input.lower() == "clear":
                messages = messages[:1] if system else []
                click.echo("对话已清空")
                continue

            if not user_input.strip():
                continue

            messages.append({"role": "user", "content": user_input})

            try:
                response = router.chat(messages=messages, provider=provider)
                click.echo(f"AI> {response.content}")
                messages.append({"role": "assistant", "content": response.content})
            except Exception as e:
                click.echo(f"错误: {e}", err=True)
                messages.pop()  # 移除失败的用户消息

    except Exception as e:
        click.echo(f"初始化失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def providers(ctx):
    """
    列出可用的 LLM 提供商

    显示已配置且可用的 LLM Provider 列表。
    """
    config = ctx.obj["config"]

    router = LLMRouter(config)
    available = router.get_available_providers()

    if available:
        click.echo("可用的 LLM Provider:")
        for name in available:
            provider_config = config.get_provider_config(name)
            model = provider_config.model if provider_config else "未知"
            click.echo(f"  - {name}: {model}")
    else:
        click.echo("没有可用的 LLM Provider")
        click.echo("\n请配置 API Key:")
        click.echo("  1. 创建 config.yaml 配置文件")
        click.echo("  2. 或设置环境变量 (ANTHROPIC_API_KEY, DEEPSEEK_API_KEY 等)")


@cli.command()
@click.pass_context
def status(ctx):
    """
    显示系统状态

    显示 PyClaw 的运行状态和健康检查结果。
    """
    config = ctx.obj["config"]

    click.echo("PyClaw 系统状态")
    click.echo("=" * 40)

    # LLM Router 状态
    router = LLMRouter(config)
    health = router.get_health_status()

    click.echo("\nLLM Provider:")
    available = health.get("available_providers", [])
    if available:
        for name in available:
            breaker_info = health.get("circuit_breakers", {}).get(name, {})
            state = breaker_info.get("state", "unknown")
            status_icon = "✓" if state == "closed" else "✗"
            click.echo(f"  {status_icon} {name}: {state}")
    else:
        click.echo("  (无可用 Provider)")

    # 任务路由
    click.echo("\n任务路由:")
    routing = router.get_task_routing()
    for task, provider in list(routing.items())[:5]:
        click.echo(f"  {task}: {provider}")
    if len(routing) > 5:
        click.echo(f"  ... 共 {len(routing)} 条规则")


@cli.command()
@click.option("--output", "-o", type=click.Path(), default="config.yaml",
              help="输出文件路径")
@click.option("--force", "-f", is_flag=True, help="覆盖已存在的文件")
def init(output: str, force: bool):
    """
    初始化配置文件

    生成配置文件模板。

    示例:

        pyclaw init

        pyclaw init -o ~/.pyclaw/config.yaml
    """
    if os.path.exists(output) and not force:
        click.echo(f"文件已存在: {output}")
        click.echo("使用 -f 选项覆盖")
        sys.exit(1)

    config_template = '''# PyClaw 配置文件
# 详细说明请参考文档

# LLM 配置
llm:
  # 默认提供商
  default_provider: deepseek

  # 任务路由规则
  task_routing:
    code_generation: claude
    complex_reasoning: deepseek
    chinese_chat: qwen
    default: deepseek

# Provider 配置
# 支持中转 API: 设置 api_base 为你的中转地址
providers:
  claude:
    api_key: ${ANTHROPIC_API_KEY}
    # api_base: https://your-proxy-api.com/v1  # 中转 API（可选）
    model: claude-sonnet-4-20250514
    max_tokens: 8192
    temperature: 0.7

  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    api_base: https://api.deepseek.com/v1
    model: deepseek-chat
    max_tokens: 4096
    temperature: 0.7

  qwen:
    api_key: ${DASHSCOPE_API_KEY}
    api_base: https://dashscope.aliyuncs.com/compatible-mode/v1
    model: qwen-plus
    max_tokens: 4096
    temperature: 0.7

  doubao:
    api_key: ${DOUBAO_API_KEY}
    api_base: https://ark.cn-beijing.volces.com/api/v3
    model: doubao-pro-32k
    max_tokens: 4096
    temperature: 0.7

# 记忆配置
memory:
  database_path: ~/.pyclaw/memory.db
  max_context_tokens: 8000
  max_history_messages: 50

# 日志配置
logging:
  level: INFO
  file: ~/.pyclaw/pyclaw.log
  max_size: 10485760  # 10MB
  backup_count: 3
'''

    # 确保目录存在
    output_dir = os.path.dirname(output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(output, "w", encoding="utf-8") as f:
        f.write(config_template)

    click.echo(f"配置文件已创建: {output}")
    click.echo("\n请编辑配置文件，设置 API Key 或配置环境变量:")
    click.echo("  export ANTHROPIC_API_KEY=your_key")
    click.echo("  export DEEPSEEK_API_KEY=your_key")


@cli.command()
@click.argument("text")
def detect(text: str):
    """
    检测任务类型

    分析输入文本，识别任务类型。

    示例:

        pyclaw detect "帮我写一个排序算法"

        pyclaw detect "翻译成英文"
    """
    from .llm.task_detector import detect_task_type

    result = detect_task_type(text)

    click.echo(f"任务类型: {result.task_type.value}")
    click.echo(f"置信度: {result.confidence:.2f}")
    click.echo(f"推荐 Provider: {result.suggested_provider}")

    if result.detected_features:
        click.echo(f"检测特征: {', '.join(result.detected_features[:3])}")


# ============================================================
# Server 命令组
# ============================================================

@cli.group()
def server():
    """
    后台服务管理

    管理 PyClaw 后台服务的启动、停止和状态查看。

    示例:

        pyclaw server start

        pyclaw server stop

        pyclaw server status
    """
    pass


@server.command("start")
@click.option("--daemon", "-d", is_flag=True, help="以守护进程模式运行")
@click.option("--foreground", "-f", is_flag=True, help="前台运行（默认）")
@click.pass_context
def server_start(ctx, daemon: bool, foreground: bool):
    """
    启动后台服务

    启动 PyClaw 服务，监听配置的通道（如 iMessage）。

    示例:

        pyclaw server start           # 前台运行

        pyclaw server start -d        # 守护进程模式
    """
    from .server import PyClawServer, run_server

    config = ctx.obj["config"]

    # 检查是否已运行
    status = PyClawServer.get_server_status()
    if status["status"] == "running":
        click.echo(f"服务已在运行 (PID: {status['pid']})")
        click.echo("使用 'pyclaw server stop' 停止服务")
        sys.exit(1)

    if daemon:
        click.echo("正在以守护进程模式启动...")
        click.echo("使用 'pyclaw server status' 查看状态")
        click.echo("使用 'pyclaw server stop' 停止服务")
        click.echo("日志文件: ~/.pyclaw/logs/server.log")

    try:
        asyncio.run(run_server(config, daemonize=daemon))
    except KeyboardInterrupt:
        click.echo("\n服务已停止")
    except Exception as e:
        click.echo(f"启动失败: {e}", err=True)
        sys.exit(1)


@server.command("stop")
@click.option("--force", "-f", is_flag=True, help="强制停止")
def server_stop(force: bool):
    """
    停止后台服务

    停止正在运行的 PyClaw 服务。

    示例:

        pyclaw server stop

        pyclaw server stop -f    # 强制停止
    """
    from .server import PyClawServer

    status = PyClawServer.get_server_status()

    if status["status"] != "running":
        click.echo("服务未运行")
        if status.get("stale_pid"):
            click.echo(f"(已清理过期 PID 文件，原 PID: {status['stale_pid']})")
        return

    pid = status["pid"]
    click.echo(f"正在停止服务 (PID: {pid})...")

    if force:
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
            click.echo("服务已强制停止")
        except OSError as e:
            click.echo(f"停止失败: {e}", err=True)
            sys.exit(1)
    else:
        success = PyClawServer.stop_by_pid()
        if success:
            click.echo("服务已停止")
        else:
            click.echo("停止失败，尝试使用 -f 强制停止", err=True)
            sys.exit(1)


@server.command("status")
@click.option("--json", "-j", "as_json", is_flag=True, help="JSON 格式输出")
def server_status(as_json: bool):
    """
    查看服务状态

    显示 PyClaw 服务的运行状态。

    示例:

        pyclaw server status

        pyclaw server status -j    # JSON 格式
    """
    from .server import PyClawServer
    from pathlib import Path

    status = PyClawServer.get_server_status()

    if as_json:
        import json
        click.echo(json.dumps(status, indent=2))
        return

    click.echo("PyClaw 服务状态")
    click.echo("=" * 40)

    if status["status"] == "running":
        click.echo(f"状态: ✓ 运行中")
        click.echo(f"PID: {status['pid']}")

        # 尝试读取日志获取更多信息
        log_file = Path("~/.pyclaw/logs/server.log").expanduser()
        if log_file.exists():
            click.echo(f"日志: {log_file}")
    else:
        click.echo(f"状态: ✗ 未运行")
        if status.get("stale_pid"):
            click.echo(f"(已清理过期 PID: {status['stale_pid']})")

    click.echo()
    click.echo("命令:")
    click.echo("  启动: pyclaw server start")
    click.echo("  停止: pyclaw server stop")
    click.echo("  日志: tail -f ~/.pyclaw/logs/server.log")


@server.command("logs")
@click.option("--lines", "-n", default=50, help="显示行数")
@click.option("--follow", "-f", is_flag=True, help="持续跟踪")
def server_logs(lines: int, follow: bool):
    """
    查看服务日志

    显示 PyClaw 服务的运行日志。

    示例:

        pyclaw server logs

        pyclaw server logs -n 100

        pyclaw server logs -f    # 持续跟踪
    """
    from pathlib import Path
    import subprocess

    log_file = Path("~/.pyclaw/logs/server.log").expanduser()

    if not log_file.exists():
        click.echo("日志文件不存在")
        click.echo(f"路径: {log_file}")
        return

    if follow:
        # 使用 tail -f 持续跟踪
        try:
            subprocess.run(["tail", "-f", str(log_file)])
        except KeyboardInterrupt:
            pass
    else:
        # 显示最后 N 行
        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), str(log_file)],
                capture_output=True,
                text=True
            )
            click.echo(result.stdout)
        except Exception as e:
            click.echo(f"读取日志失败: {e}", err=True)


@server.command("restart")
@click.pass_context
def server_restart(ctx):
    """
    重启后台服务

    停止并重新启动 PyClaw 服务。

    示例:

        pyclaw server restart
    """
    from .server import PyClawServer, run_server

    config = ctx.obj["config"]

    # 先停止
    status = PyClawServer.get_server_status()
    if status["status"] == "running":
        click.echo(f"正在停止服务 (PID: {status['pid']})...")
        PyClawServer.stop_by_pid()
        click.echo("服务已停止")

    # 再启动
    click.echo("正在启动服务...")
    try:
        asyncio.run(run_server(config, daemonize=False))
    except KeyboardInterrupt:
        click.echo("\n服务已停止")
    except Exception as e:
        click.echo(f"启动失败: {e}", err=True)
        sys.exit(1)


def main():
    """CLI 入口点"""
    cli(obj={})


if __name__ == "__main__":
    main()
