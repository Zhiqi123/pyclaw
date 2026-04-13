"""
任务类型检测器测试
"""

import pytest

from pyclaw.llm.task_detector import (
    TaskType, TaskDetector, TaskDetectionResult,
    detect_task_type, get_task_detector,
    TASK_PROVIDER_MAPPING
)


class TestTaskType:
    """TaskType 枚举测试"""

    def test_values(self):
        """测试枚举值"""
        assert TaskType.CODE_GENERATION.value == "code_generation"
        assert TaskType.COMPLEX_REASONING.value == "complex_reasoning"
        assert TaskType.CHINESE_CHAT.value == "chinese_chat"
        assert TaskType.DEFAULT.value == "default"


class TestTaskDetectionResult:
    """TaskDetectionResult 测试"""

    def test_create_result(self):
        """测试创建结果"""
        result = TaskDetectionResult(
            task_type=TaskType.CODE_GENERATION,
            confidence=0.9,
            detected_features=["keyword:代码"],
            suggested_provider="claude"
        )

        assert result.task_type == TaskType.CODE_GENERATION
        assert result.confidence == 0.9
        assert "keyword:代码" in result.detected_features
        assert result.suggested_provider == "claude"


class TestTaskDetector:
    """TaskDetector 测试"""

    def test_detect_code_generation(self):
        """测试检测代码生成任务"""
        detector = TaskDetector()

        result = detector.detect("帮我写一个 Python 排序函数")
        assert result.task_type == TaskType.CODE_GENERATION
        assert result.confidence > 0.5

    def test_detect_code_generation_english(self):
        """测试检测英文代码生成任务"""
        detector = TaskDetector()

        result = detector.detect("Write a function to sort an array")
        assert result.task_type == TaskType.CODE_GENERATION

    def test_detect_code_review(self):
        """测试检测代码审查任务"""
        detector = TaskDetector()

        result = detector.detect("帮我 review 一下这段代码有什么问题")
        assert result.task_type == TaskType.CODE_REVIEW

    def test_detect_complex_reasoning(self):
        """测试检测复杂推理任务"""
        detector = TaskDetector()

        result = detector.detect("请分析一下为什么这个算法的时间复杂度是 O(n log n)")
        assert result.task_type == TaskType.COMPLEX_REASONING

    def test_detect_math_logic(self):
        """测试检测数学逻辑任务"""
        detector = TaskDetector()

        result = detector.detect("计算 1+2+3+...+100 的结果")
        assert result.task_type == TaskType.MATH_LOGIC

    def test_detect_translation(self):
        """测试检测翻译任务"""
        detector = TaskDetector()

        result = detector.detect("把这段话翻译成英文")
        assert result.task_type == TaskType.TRANSLATION

    def test_detect_summarization(self):
        """测试检测摘要任务"""
        detector = TaskDetector()

        result = detector.detect("总结一下这篇文章的要点")
        assert result.task_type == TaskType.SUMMARIZATION

    def test_detect_creative_writing(self):
        """测试检测创意写作任务"""
        detector = TaskDetector()

        result = detector.detect("帮我写一个关于太空探险的故事")
        assert result.task_type == TaskType.CREATIVE_WRITING

    def test_detect_simple_qa(self):
        """测试检测简单问答任务"""
        detector = TaskDetector()

        result = detector.detect("什么是机器学习？")
        assert result.task_type == TaskType.SIMPLE_QA

    def test_detect_vision_with_image(self):
        """测试检测视觉任务（有图片）"""
        detector = TaskDetector()

        result = detector.detect("描述这张图片", has_image=True)
        assert result.task_type == TaskType.VISION
        assert result.confidence == 1.0

    def test_detect_long_context(self):
        """测试检测长文本任务"""
        detector = TaskDetector()

        long_text = "这是一段很长的文本。" * 1000  # 超过 5000 字符
        result = detector.detect(long_text)
        assert result.task_type == TaskType.LONG_CONTEXT

    def test_detect_chinese_chat(self):
        """测试检测中文对话任务"""
        detector = TaskDetector()

        # 纯中文且没有匹配其他模式，可能返回 DEFAULT 或 CHINESE_CHAT
        result = detector.detect("今天天气怎么样")
        # 短文本可能匹配多种类型或回退到默认
        assert result.task_type in [TaskType.SIMPLE_QA, TaskType.CHINESE_CHAT, TaskType.DEFAULT]

    def test_detect_default(self):
        """测试默认任务类型"""
        detector = TaskDetector()

        result = detector.detect("hello world")
        # 短英文文本可能返回默认类型
        assert result.task_type in [TaskType.DEFAULT, TaskType.SIMPLE_QA, TaskType.CODE_GENERATION]

    def test_low_confidence_fallback(self):
        """测试低置信度回退到默认"""
        detector = TaskDetector()

        # 非常短的无特征文本
        result = detector.detect("ok")
        assert result.confidence >= 0.5  # 至少有默认置信度

    def test_set_provider_mapping(self):
        """测试设置提供商映射"""
        detector = TaskDetector()

        detector.set_provider_mapping(TaskType.CODE_GENERATION, "deepseek")
        result = detector.detect("写一个函数")

        assert result.suggested_provider == "deepseek"

    def test_add_custom_pattern(self):
        """测试添加自定义模式"""
        detector = TaskDetector()

        # 添加自定义关键词
        detector.add_pattern(
            TaskType.CODE_GENERATION,
            keywords=["自定义关键词"]
        )

        result = detector.detect("这是自定义关键词测试")
        assert result.task_type == TaskType.CODE_GENERATION

    def test_chinese_ratio(self):
        """测试中文比例计算"""
        detector = TaskDetector()

        # 纯中文
        ratio = detector._chinese_ratio("你好世界")
        assert ratio == 1.0

        # 纯英文
        ratio = detector._chinese_ratio("hello world")
        assert ratio == 0.0

        # 混合
        ratio = detector._chinese_ratio("你好 world")
        assert 0 < ratio < 1

        # 空字符串
        ratio = detector._chinese_ratio("")
        assert ratio == 0.0


class TestGlobalDetector:
    """全局检测器测试"""

    def test_get_task_detector(self):
        """测试获取全局检测器"""
        detector1 = get_task_detector()
        detector2 = get_task_detector()

        # 应该是同一个实例
        assert detector1 is detector2

    def test_detect_task_type_function(self):
        """测试便捷函数"""
        result = detect_task_type("帮我写代码")

        assert isinstance(result, TaskDetectionResult)
        assert result.task_type == TaskType.CODE_GENERATION


class TestProviderMapping:
    """提供商映射测试"""

    def test_default_mappings(self):
        """测试默认映射"""
        assert TASK_PROVIDER_MAPPING[TaskType.CODE_GENERATION] == "claude"
        assert TASK_PROVIDER_MAPPING[TaskType.COMPLEX_REASONING] == "deepseek"
        assert TASK_PROVIDER_MAPPING[TaskType.CHINESE_CHAT] == "qwen"
        assert TASK_PROVIDER_MAPPING[TaskType.VISION] == "doubao"
