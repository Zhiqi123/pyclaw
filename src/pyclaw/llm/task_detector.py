"""
任务类型自动检测器

根据用户输入自动识别任务类型，用于智能模型路由。
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from enum import Enum


class TaskType(Enum):
    """任务类型"""
    CODE_GENERATION = "code_generation"      # 代码生成/编程
    CODE_REVIEW = "code_review"              # 代码审查
    COMPLEX_REASONING = "complex_reasoning"  # 复杂推理
    MATH_LOGIC = "math_logic"                # 数学逻辑
    CHINESE_CHAT = "chinese_chat"            # 中文对话
    TRANSLATION = "translation"              # 翻译
    SUMMARIZATION = "summarization"          # 摘要
    CREATIVE_WRITING = "creative_writing"    # 创意写作
    LONG_CONTEXT = "long_context"            # 长文本处理
    VISION = "vision"                        # 图片理解
    SIMPLE_QA = "simple_qa"                  # 简单问答
    DEFAULT = "default"                      # 默认


@dataclass
class TaskDetectionResult:
    """任务检测结果"""
    task_type: TaskType
    confidence: float  # 0.0 - 1.0
    detected_features: List[str]
    suggested_provider: Optional[str] = None


# 任务类型关键词和模式
TASK_PATTERNS: Dict[TaskType, Dict] = {
    TaskType.CODE_GENERATION: {
        "keywords": [
            "代码", "编程", "程序", "函数", "类", "方法", "实现", "写一个",
            "code", "program", "function", "class", "implement", "write",
            "python", "java", "javascript", "typescript", "rust", "go",
            "html", "css", "sql", "api", "算法", "数据结构"
        ],
        "patterns": [
            r"写[一个]*.*代码",
            r"实现[一个]*.*功能",
            r"帮我.*编程",
            r"def\s+\w+",
            r"class\s+\w+",
            r"function\s+\w+",
            r"import\s+\w+",
            r"```\w*\n",
        ],
        "weight": 1.0
    },
    TaskType.CODE_REVIEW: {
        "keywords": [
            "审查", "review", "检查代码", "代码问题", "bug", "优化代码",
            "重构", "refactor", "代码质量"
        ],
        "patterns": [
            r"帮我.*看.*代码",
            r"这段代码.*问题",
            r"review.*code",
        ],
        "weight": 0.9
    },
    TaskType.COMPLEX_REASONING: {
        "keywords": [
            "分析", "推理", "解释", "为什么", "原因", "逻辑",
            "analyze", "reason", "explain", "why", "because",
            "比较", "对比", "评估", "判断"
        ],
        "patterns": [
            r"为什么.*会",
            r"请.*分析",
            r"解释.*原理",
            r"如何.*理解",
        ],
        "weight": 0.8
    },
    TaskType.MATH_LOGIC: {
        "keywords": [
            "计算", "数学", "公式", "方程", "证明", "求解",
            "calculate", "math", "formula", "equation", "prove",
            "概率", "统计", "积分", "微分", "矩阵"
        ],
        "patterns": [
            r"\d+\s*[\+\-\*\/]\s*\d+",
            r"求.*值",
            r"计算.*结果",
            r"证明.*定理",
        ],
        "weight": 0.9
    },
    TaskType.TRANSLATION: {
        "keywords": [
            "翻译", "translate", "转换", "英译中", "中译英",
            "translation"
        ],
        "patterns": [
            r"翻译.*[成为到]",
            r"translate.*to",
            r"把.*翻译",
        ],
        "weight": 1.0
    },
    TaskType.SUMMARIZATION: {
        "keywords": [
            "总结", "摘要", "概括", "归纳", "要点",
            "summarize", "summary", "brief", "outline"
        ],
        "patterns": [
            r"总结.*内容",
            r"概括.*要点",
            r"summarize",
        ],
        "weight": 0.9
    },
    TaskType.CREATIVE_WRITING: {
        "keywords": [
            "写作", "故事", "小说", "诗", "文章", "创作",
            "write", "story", "novel", "poem", "article", "creative",
            "剧本", "歌词", "文案"
        ],
        "patterns": [
            r"写[一个篇首]*.*故事",
            r"创作.*",
            r"帮我写.*文章",
        ],
        "weight": 0.8
    },
    TaskType.SIMPLE_QA: {
        "keywords": [
            "是什么", "什么是", "定义", "介绍",
            "what is", "define", "introduce",
            "怎么样", "如何", "哪个", "哪些"
        ],
        "patterns": [
            r".*是什么[？?]?$",
            r"什么是.*[？?]?$",
            r"^介绍.*",
        ],
        "weight": 0.6
    },
}

# 任务类型到推荐 Provider 的映射
TASK_PROVIDER_MAPPING: Dict[TaskType, str] = {
    TaskType.CODE_GENERATION: "claude",
    TaskType.CODE_REVIEW: "claude",
    TaskType.COMPLEX_REASONING: "deepseek",  # DeepSeek-R1 擅长推理
    TaskType.MATH_LOGIC: "deepseek",
    TaskType.CHINESE_CHAT: "qwen",           # Qwen 中文能力强
    TaskType.TRANSLATION: "qwen",
    TaskType.SUMMARIZATION: "deepseek",
    TaskType.CREATIVE_WRITING: "claude",
    TaskType.LONG_CONTEXT: "claude",
    TaskType.VISION: "doubao",               # Doubao 视觉能力
    TaskType.SIMPLE_QA: "deepseek",          # 简单问答用经济模型
    TaskType.DEFAULT: "deepseek",
}


class TaskDetector:
    """
    任务类型检测器

    根据用户输入自动识别任务类型。

    使用示例:
        detector = TaskDetector()
        result = detector.detect("帮我写一个 Python 排序函数")
        print(result.task_type)  # TaskType.CODE_GENERATION
    """

    def __init__(self, custom_patterns: Optional[Dict] = None):
        """
        初始化检测器

        Args:
            custom_patterns: 自定义任务模式
        """
        self.patterns = TASK_PATTERNS.copy()
        if custom_patterns:
            self.patterns.update(custom_patterns)

        self.provider_mapping = TASK_PROVIDER_MAPPING.copy()

    def detect(self, text: str, has_image: bool = False) -> TaskDetectionResult:
        """
        检测任务类型

        Args:
            text: 用户输入文本
            has_image: 是否包含图片

        Returns:
            TaskDetectionResult
        """
        # 如果有图片，直接返回视觉任务
        if has_image:
            return TaskDetectionResult(
                task_type=TaskType.VISION,
                confidence=1.0,
                detected_features=["has_image"],
                suggested_provider=self.provider_mapping[TaskType.VISION]
            )

        # 检测长文本
        if len(text) > 5000:
            return TaskDetectionResult(
                task_type=TaskType.LONG_CONTEXT,
                confidence=0.9,
                detected_features=["long_text"],
                suggested_provider=self.provider_mapping[TaskType.LONG_CONTEXT]
            )

        # 计算各任务类型的得分
        scores: Dict[TaskType, float] = {}
        features: Dict[TaskType, List[str]] = {}

        text_lower = text.lower()

        for task_type, config in self.patterns.items():
            score = 0.0
            detected = []

            # 关键词匹配
            keywords = config.get("keywords", [])
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    score += 0.3
                    detected.append(f"keyword:{keyword}")

            # 正则模式匹配
            patterns = config.get("patterns", [])
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    score += 0.5
                    detected.append(f"pattern:{pattern[:20]}")

            # 应用权重
            weight = config.get("weight", 1.0)
            score *= weight

            if score > 0:
                scores[task_type] = min(score, 1.0)
                features[task_type] = detected

        # 选择得分最高的任务类型
        if scores:
            best_type = max(scores, key=scores.get)
            confidence = scores[best_type]

            # 如果置信度太低，使用默认类型
            if confidence < 0.3:
                best_type = TaskType.DEFAULT
                confidence = 0.5

            return TaskDetectionResult(
                task_type=best_type,
                confidence=confidence,
                detected_features=features.get(best_type, []),
                suggested_provider=self.provider_mapping.get(best_type)
            )

        # 检测是否主要是中文
        chinese_ratio = self._chinese_ratio(text)
        if chinese_ratio > 0.5:
            return TaskDetectionResult(
                task_type=TaskType.CHINESE_CHAT,
                confidence=0.6,
                detected_features=[f"chinese_ratio:{chinese_ratio:.2f}"],
                suggested_provider=self.provider_mapping[TaskType.CHINESE_CHAT]
            )

        # 默认类型
        return TaskDetectionResult(
            task_type=TaskType.DEFAULT,
            confidence=0.5,
            detected_features=[],
            suggested_provider=self.provider_mapping[TaskType.DEFAULT]
        )

    def _chinese_ratio(self, text: str) -> float:
        """计算中文字符比例"""
        if not text:
            return 0.0

        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        return chinese_chars / len(text)

    def set_provider_mapping(self, task_type: TaskType, provider: str) -> None:
        """设置任务类型到 Provider 的映射"""
        self.provider_mapping[task_type] = provider

    def add_pattern(
        self,
        task_type: TaskType,
        keywords: Optional[List[str]] = None,
        patterns: Optional[List[str]] = None
    ) -> None:
        """添加自定义模式"""
        if task_type not in self.patterns:
            self.patterns[task_type] = {"keywords": [], "patterns": [], "weight": 1.0}

        if keywords:
            self.patterns[task_type]["keywords"].extend(keywords)
        if patterns:
            self.patterns[task_type]["patterns"].extend(patterns)


# 全局检测器实例
_default_detector: Optional[TaskDetector] = None


def get_task_detector() -> TaskDetector:
    """获取全局任务检测器"""
    global _default_detector
    if _default_detector is None:
        _default_detector = TaskDetector()
    return _default_detector


def detect_task_type(text: str, has_image: bool = False) -> TaskDetectionResult:
    """便捷函数：检测任务类型"""
    return get_task_detector().detect(text, has_image)
