"""
心跳调度器 - 定时任务管理
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime, timedelta
from enum import Enum
import heapq

from ..core.logger import LoggerMixin
from ..core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class ScheduledTask:
    """调度任务"""
    id: str
    name: str
    callback: Callable
    interval: Optional[float] = None  # 重复间隔（秒），None 表示一次性任务
    next_run: datetime = field(default_factory=datetime.now)
    priority: TaskPriority = TaskPriority.NORMAL
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    max_retries: int = 0
    retry_count: int = 0
    status: TaskStatus = TaskStatus.PENDING
    last_run: Optional[datetime] = None
    last_result: Any = None
    last_error: Optional[str] = None
    enabled: bool = True

    def __lt__(self, other):
        """用于优先队列比较"""
        if self.next_run == other.next_run:
            return self.priority.value > other.priority.value
        return self.next_run < other.next_run


@dataclass
class TaskResult:
    """任务执行结果"""
    task_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


class HeartbeatScheduler(LoggerMixin):
    """
    心跳调度器

    支持：
    - 一次性任务和周期性任务
    - 任务优先级
    - 失败重试
    - 任务取消和暂停

    使用示例:
        scheduler = HeartbeatScheduler()

        # 添加周期性任务
        scheduler.add_periodic("health_check", check_health, interval=60)

        # 添加一次性任务
        scheduler.add_once("init", initialize, delay=5)

        # 启动调度器
        scheduler.start()
    """

    def __init__(self, tick_interval: float = 1.0):
        """
        初始化调度器

        Args:
            tick_interval: 调度循环间隔（秒）
        """
        self._tick_interval = tick_interval
        self._tasks: Dict[str, ScheduledTask] = {}
        self._task_queue: List[ScheduledTask] = []  # 优先队列
        self._lock = threading.RLock()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._event_bus = EventBus()

        # 任务执行回调
        self._on_task_complete: Optional[Callable[[TaskResult], None]] = None
        self._on_task_error: Optional[Callable[[TaskResult], None]] = None

        # 统计
        self._stats = {
            "total_executed": 0,
            "total_success": 0,
            "total_failed": 0
        }

    def add_periodic(
        self,
        task_id: str,
        callback: Callable,
        interval: float,
        name: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        args: tuple = (),
        kwargs: Optional[Dict] = None,
        max_retries: int = 0,
        start_immediately: bool = False
    ) -> bool:
        """
        添加周期性任务

        Args:
            task_id: 任务 ID
            callback: 回调函数
            interval: 执行间隔（秒）
            name: 任务名称
            priority: 优先级
            args: 回调参数
            kwargs: 回调关键字参数
            max_retries: 最大重试次数
            start_immediately: 是否立即执行第一次

        Returns:
            是否添加成功
        """
        with self._lock:
            if task_id in self._tasks:
                self.logger.warning(f"任务 {task_id} 已存在")
                return False

            next_run = datetime.now() if start_immediately else datetime.now() + timedelta(seconds=interval)

            task = ScheduledTask(
                id=task_id,
                name=name or task_id,
                callback=callback,
                interval=interval,
                next_run=next_run,
                priority=priority,
                args=args,
                kwargs=kwargs or {},
                max_retries=max_retries
            )

            self._tasks[task_id] = task
            heapq.heappush(self._task_queue, task)

            self.logger.debug(f"添加周期任务: {task_id}, 间隔: {interval}s")
            return True

    def add_once(
        self,
        task_id: str,
        callback: Callable,
        delay: float = 0,
        at: Optional[datetime] = None,
        name: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        args: tuple = (),
        kwargs: Optional[Dict] = None,
        max_retries: int = 0
    ) -> bool:
        """
        添加一次性任务

        Args:
            task_id: 任务 ID
            callback: 回调函数
            delay: 延迟执行时间（秒）
            at: 指定执行时间（与 delay 二选一）
            name: 任务名称
            priority: 优先级
            args: 回调参数
            kwargs: 回调关键字参数
            max_retries: 最大重试次数

        Returns:
            是否添加成功
        """
        with self._lock:
            if task_id in self._tasks:
                self.logger.warning(f"任务 {task_id} 已存在")
                return False

            if at:
                next_run = at
            else:
                next_run = datetime.now() + timedelta(seconds=delay)

            task = ScheduledTask(
                id=task_id,
                name=name or task_id,
                callback=callback,
                interval=None,  # 一次性任务
                next_run=next_run,
                priority=priority,
                args=args,
                kwargs=kwargs or {},
                max_retries=max_retries
            )

            self._tasks[task_id] = task
            heapq.heappush(self._task_queue, task)

            self.logger.debug(f"添加一次性任务: {task_id}, 执行时间: {next_run}")
            return True

    def remove(self, task_id: str) -> bool:
        """
        移除任务

        Args:
            task_id: 任务 ID

        Returns:
            是否移除成功
        """
        with self._lock:
            if task_id not in self._tasks:
                return False

            task = self._tasks.pop(task_id)
            task.status = TaskStatus.CANCELLED

            # 从队列中移除（标记为取消，下次执行时跳过）
            self.logger.debug(f"移除任务: {task_id}")
            return True

    def enable(self, task_id: str) -> bool:
        """启用任务"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.enabled = True
                return True
            return False

    def disable(self, task_id: str) -> bool:
        """禁用任务"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.enabled = False
                return True
            return False

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self, enabled_only: bool = False) -> List[ScheduledTask]:
        """列出所有任务"""
        tasks = list(self._tasks.values())
        if enabled_only:
            tasks = [t for t in tasks if t.enabled]
        return tasks

    def start(self) -> None:
        """启动调度器"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.logger.info("调度器已启动")

    def stop(self, wait: bool = True) -> None:
        """
        停止调度器

        Args:
            wait: 是否等待当前任务完成
        """
        self._running = False
        if wait and self._thread:
            self._thread.join(timeout=10)
        self._thread = None
        self.logger.info("调度器已停止")

    def _run_loop(self) -> None:
        """调度主循环"""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                self.logger.error(f"调度循环错误: {e}")

            time.sleep(self._tick_interval)

    def _tick(self) -> None:
        """执行一次调度"""
        now = datetime.now()

        with self._lock:
            # 重建队列（移除已取消的任务）
            self._task_queue = [t for t in self._task_queue if t.id in self._tasks]
            heapq.heapify(self._task_queue)

            # 执行到期的任务
            while self._task_queue and self._task_queue[0].next_run <= now:
                task = heapq.heappop(self._task_queue)

                # 检查任务是否仍然有效
                if task.id not in self._tasks:
                    continue

                if not task.enabled:
                    # 重新调度禁用的任务
                    if task.interval:
                        task.next_run = now + timedelta(seconds=task.interval)
                        heapq.heappush(self._task_queue, task)
                    continue

                # 执行任务
                self._execute_task(task)

                # 重新调度周期性任务
                if task.interval and task.id in self._tasks:
                    task.next_run = now + timedelta(seconds=task.interval)
                    heapq.heappush(self._task_queue, task)

    def _execute_task(self, task: ScheduledTask) -> None:
        """执行任务"""
        task.status = TaskStatus.RUNNING
        task.last_run = datetime.now()
        start_time = time.time()

        try:
            result = task.callback(*task.args, **task.kwargs)
            execution_time = time.time() - start_time

            task.status = TaskStatus.COMPLETED
            task.last_result = result
            task.last_error = None
            task.retry_count = 0

            self._stats["total_executed"] += 1
            self._stats["total_success"] += 1

            task_result = TaskResult(
                task_id=task.id,
                success=True,
                result=result,
                execution_time=execution_time
            )

            if self._on_task_complete:
                self._on_task_complete(task_result)

            self._event_bus.publish(
                EventType.TASK_COMPLETED,
                data={"task_id": task.id, "success": True},
                source="HeartbeatScheduler"
            )

            self.logger.debug(f"任务完成: {task.id}, 耗时: {execution_time:.3f}s")

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)

            task.last_error = error_msg
            self._stats["total_executed"] += 1
            self._stats["total_failed"] += 1

            # 重试逻辑
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = TaskStatus.PENDING
                # 延迟重试
                task.next_run = datetime.now() + timedelta(seconds=min(30, 2 ** task.retry_count))
                heapq.heappush(self._task_queue, task)
                self.logger.warning(f"任务失败，将重试 ({task.retry_count}/{task.max_retries}): {task.id}")
            else:
                task.status = TaskStatus.FAILED

            task_result = TaskResult(
                task_id=task.id,
                success=False,
                error=error_msg,
                execution_time=execution_time
            )

            if self._on_task_error:
                self._on_task_error(task_result)

            self._event_bus.publish(
                EventType.TASK_FAILED,
                data={"task_id": task.id, "error": error_msg},
                source="HeartbeatScheduler"
            )

            self.logger.error(f"任务失败: {task.id}, 错误: {error_msg}")

    def set_on_task_complete(self, callback: Callable[[TaskResult], None]) -> None:
        """设置任务完成回调"""
        self._on_task_complete = callback

    def set_on_task_error(self, callback: Callable[[TaskResult], None]) -> None:
        """设置任务错误回调"""
        self._on_task_error = callback

    def run_now(self, task_id: str) -> Optional[TaskResult]:
        """
        立即执行任务

        Args:
            task_id: 任务 ID

        Returns:
            执行结果
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        start_time = time.time()
        try:
            result = task.callback(*task.args, **task.kwargs)
            return TaskResult(
                task_id=task_id,
                success=True,
                result=result,
                execution_time=time.time() - start_time
            )
        except Exception as e:
            return TaskResult(
                task_id=task_id,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time
            )

    @property
    def is_running(self) -> bool:
        """调度器是否运行中"""
        return self._running

    @property
    def stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()

    @property
    def task_count(self) -> int:
        """任务数量"""
        return len(self._tasks)
