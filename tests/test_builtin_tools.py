"""
内置工具测试
"""

import os
import platform
import tempfile
from pathlib import Path

import pytest

from pyclaw.agent import (
    ToolRegistry,
    register_builtin_tools,
    create_builtin_registry,
    shell_exec,
    clipboard_get,
    clipboard_set,
    get_system_info,
    list_files,
    read_file,
    write_file,
)


# ============================================================================
# 测试注册机制
# ============================================================================

class TestBuiltinRegistration:
    """测试内置工具注册"""

    def test_register_builtin_tools(self):
        """测试注册内置工具到 Registry"""
        registry = ToolRegistry()
        register_builtin_tools(registry)

        # 应该有多个工具
        tools = registry.list_tools()
        assert len(tools) >= 15

        # 检查核心工具存在
        assert registry.get("shell_exec") is not None
        assert registry.get("screenshot") is not None
        assert registry.get("notify") is not None

    def test_create_builtin_registry(self):
        """测试创建预置 Registry"""
        registry = create_builtin_registry()

        tools = registry.list_tools()
        assert len(tools) >= 15

    def test_tool_categories(self):
        """测试工具分类"""
        registry = create_builtin_registry()

        categories = registry.get_categories()
        assert "system" in categories
        assert "file" in categories

    def test_tool_schemas(self):
        """测试工具 Schema 生成"""
        registry = create_builtin_registry()

        schemas = registry.get_schemas()
        assert len(schemas) >= 15

        # 检查 schema 格式
        shell_schema = next(
            (s for s in schemas if s["function"]["name"] == "shell_exec"),
            None
        )
        assert shell_schema is not None
        assert shell_schema["type"] == "function"
        assert "parameters" in shell_schema["function"]


# ============================================================================
# 测试 Shell 执行
# ============================================================================

class TestShellExec:
    """测试 Shell 命令执行"""

    def test_basic_command(self):
        """测试基本命令"""
        result = shell_exec("echo hello")
        assert result["success"] is True
        assert result["stdout"] == "hello"
        assert result["return_code"] == 0

    def test_command_with_args(self):
        """测试带参数的命令"""
        result = shell_exec("echo -n test")
        assert result["success"] is True
        assert "test" in result["stdout"]

    def test_command_failure(self):
        """测试命令失败"""
        result = shell_exec("exit 1")
        assert result["success"] is False
        assert result["return_code"] == 1

    def test_command_timeout(self):
        """测试命令超时"""
        result = shell_exec("sleep 5", timeout=1)
        assert result["success"] is False
        assert "超时" in result["stderr"]

    def test_working_directory(self):
        """测试工作目录"""
        result = shell_exec("pwd", working_dir="/tmp")
        assert result["success"] is True
        # macOS 下 /tmp 是 /private/tmp 的软链接
        assert "/tmp" in result["stdout"] or "/private/tmp" in result["stdout"]

    def test_pipe_command(self):
        """测试管道命令"""
        result = shell_exec("echo 'hello world' | wc -w")
        assert result["success"] is True
        assert "2" in result["stdout"]

    def test_through_registry(self):
        """测试通过 Registry 执行"""
        registry = create_builtin_registry()
        result = registry.execute("shell_exec", {"command": "echo test"})
        assert result.success is True
        assert "test" in result.output["stdout"]


# ============================================================================
# 测试文件操作
# ============================================================================

class TestFileOperations:
    """测试文件操作工具"""

    def test_list_files(self):
        """测试列出文件"""
        result = list_files("/tmp")
        assert result["success"] is True
        assert "files" in result
        assert isinstance(result["files"], list)

    def test_list_files_with_pattern(self):
        """测试带模式的文件列表"""
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".txt", dir="/tmp", delete=False) as f:
            temp_path = f.name

        try:
            result = list_files("/tmp", pattern="*.txt")
            assert result["success"] is True
        finally:
            os.unlink(temp_path)

    def test_list_nonexistent_path(self):
        """测试不存在的路径"""
        result = list_files("/nonexistent_path_12345")
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_read_write_file(self):
        """测试读写文件"""
        # 写入
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            temp_path = f.name

        try:
            # 写入文件
            write_result = write_file(temp_path, "测试内容\n第二行")
            assert write_result["success"] is True

            # 读取文件
            read_result = read_file(temp_path)
            assert read_result["success"] is True
            assert "测试内容" in read_result["content"]
            assert "第二行" in read_result["content"]

            # 追加模式
            append_result = write_file(temp_path, "\n第三行", append=True)
            assert append_result["success"] is True

            read_result2 = read_file(temp_path)
            assert "第三行" in read_result2["content"]

        finally:
            os.unlink(temp_path)

    def test_read_nonexistent_file(self):
        """测试读取不存在的文件"""
        result = read_file("/nonexistent_file_12345.txt")
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_read_file_max_size(self):
        """测试读取文件大小限制"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("x" * 1000)
            temp_path = f.name

        try:
            result = read_file(temp_path, max_size=100)
            assert result["success"] is True
            assert result["truncated"] is True
            assert len(result["content"]) == 100
        finally:
            os.unlink(temp_path)


# ============================================================================
# 测试系统信息
# ============================================================================

class TestSystemInfo:
    """测试系统信息工具"""

    def test_get_system_info(self):
        """测试获取系统信息"""
        info = get_system_info()

        assert "platform" in info
        assert "hostname" in info
        assert "python_version" in info
        assert "timestamp" in info

        if platform.system() == "Darwin":
            assert "macos_version" in info
            assert "cpu" in info
            assert "memory_gb" in info


# ============================================================================
# macOS 特定工具测试
# ============================================================================

@pytest.mark.skipif(platform.system() != "Darwin", reason="仅 macOS")
class TestMacOSTools:
    """macOS 特定工具测试"""

    def test_clipboard_roundtrip(self):
        """测试剪贴板读写"""
        test_content = "PyClaw 剪贴板测试 🎉"

        # 保存原始内容
        original = clipboard_get()

        try:
            # 设置内容
            set_result = clipboard_set(test_content)
            assert set_result["success"] is True

            # 读取内容
            get_result = clipboard_get()
            assert get_result["success"] is True
            assert get_result["content"] == test_content

        finally:
            # 恢复原始内容
            if original["success"] and original["content"]:
                clipboard_set(original["content"])

    def test_applescript_exec(self):
        """测试 AppleScript 执行"""
        from pyclaw.agent import applescript_exec

        result = applescript_exec('return "hello"')
        assert result["success"] is True
        assert "hello" in result["output"]

    def test_applescript_math(self):
        """测试 AppleScript 计算"""
        from pyclaw.agent import applescript_exec

        result = applescript_exec('return 1 + 1')
        assert result["success"] is True
        assert "2" in result["output"]

    def test_get_running_apps(self):
        """测试获取运行中的应用"""
        from pyclaw.agent import get_running_apps

        result = get_running_apps()
        assert result["success"] is True
        assert "apps" in result
        assert len(result["apps"]) > 0
        # Finder 应该始终在运行
        assert "Finder" in result["apps"]

    def test_get_volume(self):
        """测试获取音量"""
        from pyclaw.agent import get_volume

        result = get_volume()
        assert result["success"] is True
        assert "raw" in result


# ============================================================================
# 集成测试
# ============================================================================

class TestIntegration:
    """集成测试"""

    def test_registry_execute_all_tools(self):
        """测试所有工具可通过 Registry 执行"""
        registry = create_builtin_registry()

        # 测试几个安全的工具
        safe_tools = [
            ("get_system_info", {}),
            ("list_files", {"path": "/tmp"}),
        ]

        for tool_name, args in safe_tools:
            result = registry.execute(tool_name, args)
            assert result.success is True, f"工具 {tool_name} 执行失败: {result.error}"

    def test_tool_disable_enable(self):
        """测试工具禁用启用"""
        registry = create_builtin_registry()

        # 禁用工具
        registry.disable("shell_exec")

        # 执行应该失败
        result = registry.execute("shell_exec", {"command": "echo test"})
        assert result.success is False
        assert "禁用" in result.error

        # 启用工具
        registry.enable("shell_exec")

        # 执行应该成功
        result = registry.execute("shell_exec", {"command": "echo test"})
        assert result.success is True
