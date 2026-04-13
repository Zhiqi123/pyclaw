"""
日志系统 - 统一日志管理

支持控制台和文件输出，文件轮转。
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

# 默认日志格式
DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 全局 logger 缓存
_loggers: dict = {}
_initialized = False


def setup_logger(
    name: str = "pyclaw",
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_size_mb: int = 10,
    backup_count: int = 5,
    log_format: str = DEFAULT_FORMAT,
    console_output: bool = True
) -> logging.Logger:
    """
    设置并返回 logger

    Args:
        name: logger 名称
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        log_file: 日志文件路径，None 则不输出到文件
        max_size_mb: 单个日志文件最大大小 (MB)
        backup_count: 保留的备份文件数量
        log_format: 日志格式
        console_output: 是否输出到控制台

    Returns:
        配置好的 logger
    """
    global _initialized

    logger = logging.getLogger(name)

    # 避免重复配置
    if name in _loggers:
        return _loggers[name]

    # 设置日志级别
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)

    # 创建格式化器
    formatter = logging.Formatter(log_format, datefmt=DEFAULT_DATE_FORMAT)

    # 控制台处理器
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件处理器
    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 防止日志传播到根 logger
    logger.propagate = False

    _loggers[name] = logger
    _initialized = True

    return logger


def get_logger(name: str = "pyclaw") -> logging.Logger:
    """
    获取 logger

    如果 logger 未初始化，返回基本配置的 logger

    Args:
        name: logger 名称

    Returns:
        logger 实例
    """
    if name in _loggers:
        return _loggers[name]

    # 如果主 logger 未初始化，先初始化
    if not _initialized and name != "pyclaw":
        setup_logger()

    # 返回子 logger
    return logging.getLogger(name)


def set_level(level: str, name: str = "pyclaw") -> None:
    """
    动态设置日志级别

    Args:
        level: 日志级别
        name: logger 名称
    """
    logger = get_logger(name)
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)

    # 同时更新所有 handler 的级别
    for handler in logger.handlers:
        handler.setLevel(log_level)


class LoggerMixin:
    """
    Logger Mixin 类

    为类提供便捷的日志功能

    使用示例:
        class MyClass(LoggerMixin):
            def do_something(self):
                self.logger.info("Doing something")
    """

    @property
    def logger(self) -> logging.Logger:
        """获取类专属的 logger"""
        name = f"pyclaw.{self.__class__.__name__}"
        return get_logger(name)
