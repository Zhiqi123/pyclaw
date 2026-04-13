"""
阶段6 调度增强层测试
"""

import pytest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock

from pyclaw.scheduler import (
    HeartbeatScheduler,
    ScheduledTask,
    TaskResult,
    TaskStatus,
    TaskPriority
)


class TestScheduledTask:
    """ScheduledTask 测试"""

    def test_create_task(self):
        """测试创建任务"""
        task = ScheduledTask(
            id="task_001",
            name="测试任务",
            callback=lambda: "result",
            interval=60
        )

        assert task.id == "task_001"
        assert task.name == "测试任务"
        assert task.interval == 60
        assert task.status == TaskStatus.PENDING

    def test_task_comparison(self):
        """测试任务比较（用于优先队列）"""
        now = datetime.now()
        task1 = ScheduledTask(
            id="t1", name="t1", callback=lambda: None,
            next_run=now + timedelta(seconds=10)
        )
        task2 = ScheduledTask(
            id="t2", name="t2", callback=lambda: None,
            next_run=now + timedelta(seconds=5)
        )

        # task2 应该先执行
        assert task2 < task1

    def test_priority_comparison(self):
        """测试优先级比较"""
        now = datetime.now()
        task1 = ScheduledTask(
            id="t1", name="t1", callback=lambda: None,
            next_run=now, priority=TaskPriority.LOW
        )
        task2 = ScheduledTask(
            id="t2", name="t2", callback=lambda: None,
            next_run=now, priority=TaskPriority.HIGH
        )

        # 相同时间，高优先级先执行
        assert task2 < task1


class TestTaskResult:
    """TaskResult 测试"""

    def test_success_result(self):
        """测试成功结果"""
        result = TaskResult(
            task_id="task_001",
            success=True,
            result="done",
            execution_time=0.5
        )

        assert result.success
        assert result.result == "done"
        assert result.error is None

    def test_error_result(self):
        """测试错误结果"""
        result = TaskResult(
            task_id="task_001",
            success=False,
            error="执行失败"
        )

        assert not result.success
        assert result.error == "执行失败"


class TestHeartbeatScheduler:
    """HeartbeatScheduler 测试"""

    def test_add_periodic_task(self):
        """测试添加周期任务"""
        scheduler = HeartbeatScheduler()
        callback = Mock()

        assert scheduler.add_periodic("task1", callback, interval=10)
        assert scheduler.task_count == 1
        assert scheduler.get_task("task1") is not None

    def test_add_duplicate_task(self):
        """测试添加重复任务"""
        scheduler = HeartbeatScheduler()
        callback = Mock()

        scheduler.add_periodic("task1", callback, interval=10)
        assert not scheduler.add_periodic("task1", callback, interval=20)
        assert scheduler.task_count == 1

    def test_add_once_task(self):
        """测试添加一次性任务"""
        scheduler = HeartbeatScheduler()
        callback = Mock()

        assert scheduler.add_once("task1", callback, delay=5)
        task = scheduler.get_task("task1")
        assert task is not None
        assert task.interval is None

    def test_add_once_at_time(self):
        """测试指定时间执行"""
        scheduler = HeartbeatScheduler()
        callback = Mock()
        run_at = datetime.now() + timedelta(hours=1)

        scheduler.add_once("task1", callback, at=run_at)
        task = scheduler.get_task("task1")
        assert task.next_run == run_at

    def test_remove_task(self):
        """测试移除任务"""
        scheduler = HeartbeatScheduler()
        callback = Mock()

        scheduler.add_periodic("task1", callback, interval=10)
        assert scheduler.remove("task1")
        assert scheduler.get_task("task1") is None

    def test_remove_nonexistent_task(self):
        """测试移除不存在的任务"""
        scheduler = HeartbeatScheduler()
        assert not scheduler.remove("nonexistent")

    def test_enable_disable_task(self):
        """测试启用/禁用任务"""
        scheduler = HeartbeatScheduler()
        callback = Mock()

        scheduler.add_periodic("task1", callback, interval=10)

        scheduler.disable("task1")
        assert not scheduler.get_task("task1").enabled

        scheduler.enable("task1")
        assert scheduler.get_task("task1").enabled

    def test_list_tasks(self):
        """测试列出任务"""
        scheduler = HeartbeatScheduler()

        scheduler.add_periodic("t1", Mock(), interval=10)
        scheduler.add_periodic("t2", Mock(), interval=20)
        scheduler.add_once("t3", Mock(), delay=5)

        tasks = scheduler.list_tasks()
        assert len(tasks) == 3

    def test_list_enabled_only(self):
        """测试只列出启用的任务"""
        scheduler = HeartbeatScheduler()

        scheduler.add_periodic("t1", Mock(), interval=10)
        scheduler.add_periodic("t2", Mock(), interval=20)
        scheduler.disable("t2")

        enabled = scheduler.list_tasks(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0].id == "t1"

    def test_run_now(self):
        """测试立即执行"""
        scheduler = HeartbeatScheduler()
        callback = Mock(return_value="result")

        scheduler.add_periodic("task1", callback, interval=60)
        result = scheduler.run_now("task1")

        assert result is not None
        assert result.success
        assert result.result == "result"
        callback.assert_called_once()

    def test_run_now_nonexistent(self):
        """测试立即执行不存在的任务"""
        scheduler = HeartbeatScheduler()
        result = scheduler.run_now("nonexistent")
        assert result is None

    def test_run_now_with_error(self):
        """测试立即执行出错"""
        scheduler = HeartbeatScheduler()
        callback = Mock(side_effect=Exception("测试错误"))

        scheduler.add_periodic("task1", callback, interval=60)
        result = scheduler.run_now("task1")

        assert result is not None
        assert not result.success
        assert "测试错误" in result.error

    def test_start_stop(self):
        """测试启动/停止"""
        scheduler = HeartbeatScheduler(tick_interval=0.1)

        assert not scheduler.is_running
        scheduler.start()
        assert scheduler.is_running

        scheduler.stop()
        assert not scheduler.is_running

    def test_periodic_execution(self):
        """测试周期执行"""
        scheduler = HeartbeatScheduler(tick_interval=0.05)
        counter = {"count": 0}

        def increment():
            counter["count"] += 1

        scheduler.add_periodic("counter", increment, interval=0.1, start_immediately=True)
        scheduler.start()

        time.sleep(0.35)
        scheduler.stop()

        # 应该执行了 3-4 次
        assert counter["count"] >= 3

    def test_once_execution(self):
        """测试一次性执行"""
        scheduler = HeartbeatScheduler(tick_interval=0.05)
        callback = Mock()

        scheduler.add_once("once", callback, delay=0.1)
        scheduler.start()

        time.sleep(0.3)
        scheduler.stop()

        callback.assert_called_once()

    def test_task_with_args(self):
        """测试带参数的任务"""
        scheduler = HeartbeatScheduler()
        callback = Mock()

        scheduler.add_periodic(
            "task1", callback, interval=60,
            args=(1, 2),
            kwargs={"key": "value"}
        )

        scheduler.run_now("task1")
        callback.assert_called_once_with(1, 2, key="value")

    def test_task_priority(self):
        """测试任务优先级"""
        scheduler = HeartbeatScheduler()

        scheduler.add_periodic("low", Mock(), interval=10, priority=TaskPriority.LOW)
        scheduler.add_periodic("high", Mock(), interval=10, priority=TaskPriority.HIGH)
        scheduler.add_periodic("critical", Mock(), interval=10, priority=TaskPriority.CRITICAL)

        tasks = scheduler.list_tasks()
        assert len(tasks) == 3

    def test_task_callbacks(self):
        """测试任务回调"""
        scheduler = HeartbeatScheduler(tick_interval=0.05)
        complete_results = []
        error_results = []

        def on_complete(result):
            complete_results.append(result)

        def on_error(result):
            error_results.append(result)

        scheduler.set_on_task_complete(on_complete)
        scheduler.set_on_task_error(on_error)

        scheduler.add_once("success", lambda: "ok", delay=0.05)
        scheduler.add_once("fail", Mock(side_effect=Exception("error")), delay=0.05)

        scheduler.start()
        time.sleep(0.2)
        scheduler.stop()

        assert len(complete_results) == 1
        assert complete_results[0].success

        assert len(error_results) == 1
        assert not error_results[0].success

    def test_retry_on_failure(self):
        """测试失败重试"""
        scheduler = HeartbeatScheduler(tick_interval=0.05)
        call_count = {"count": 0}

        def failing_task():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise Exception("失败")
            return "成功"

        scheduler.add_once("retry_task", failing_task, delay=0.05, max_retries=3)
        scheduler.start()

        # 重试延迟是 2^retry_count 秒，最多 30 秒
        # 第一次重试延迟 2 秒，第二次延迟 4 秒
        time.sleep(8)
        scheduler.stop()

        # 应该重试直到成功
        assert call_count["count"] >= 3

    def test_stats(self):
        """测试统计信息"""
        scheduler = HeartbeatScheduler(tick_interval=0.05)

        scheduler.add_once("t1", lambda: "ok", delay=0.05)
        scheduler.add_once("t2", Mock(side_effect=Exception("error")), delay=0.05)

        scheduler.start()
        time.sleep(0.2)
        scheduler.stop()

        stats = scheduler.stats
        assert stats["total_executed"] >= 2
        assert stats["total_success"] >= 1
        assert stats["total_failed"] >= 1

    def test_disabled_task_not_executed(self):
        """测试禁用的任务不执行"""
        scheduler = HeartbeatScheduler(tick_interval=0.05)
        callback = Mock()

        scheduler.add_once("disabled", callback, delay=0.05)
        scheduler.disable("disabled")

        scheduler.start()
        time.sleep(0.2)
        scheduler.stop()

        callback.assert_not_called()


class TestTaskStatus:
    """TaskStatus 枚举测试"""

    def test_values(self):
        """测试枚举值"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"


class TestTaskPriority:
    """TaskPriority 枚举测试"""

    def test_values(self):
        """测试枚举值"""
        assert TaskPriority.LOW.value == 0
        assert TaskPriority.NORMAL.value == 1
        assert TaskPriority.HIGH.value == 2
        assert TaskPriority.CRITICAL.value == 3

    def test_comparison(self):
        """测试优先级比较"""
        assert TaskPriority.CRITICAL.value > TaskPriority.HIGH.value
        assert TaskPriority.HIGH.value > TaskPriority.NORMAL.value
        assert TaskPriority.NORMAL.value > TaskPriority.LOW.value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
