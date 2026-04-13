"""
阶段4 技能系统测试
"""

import pytest
import tempfile
from pathlib import Path

from pyclaw.skills import (
    Skill, SkillTrigger, SkillMatch, TriggerType,
    SkillLoader, SkillRegistry, SkillExecutor, SkillExecutionResult
)


class TestSkillTrigger:
    """SkillTrigger 测试"""

    def test_exact_match(self):
        """测试精确匹配"""
        trigger = SkillTrigger(pattern="你好", type=TriggerType.EXACT)
        assert trigger.matches("你好")
        assert not trigger.matches("你好啊")
        assert not trigger.matches("说你好")

    def test_prefix_match(self):
        """测试前缀匹配"""
        trigger = SkillTrigger(pattern="天气", type=TriggerType.PREFIX)
        assert trigger.matches("天气怎么样")
        assert trigger.matches("天气")
        assert not trigger.matches("今天天气")

    def test_contains_match(self):
        """测试包含匹配"""
        trigger = SkillTrigger(pattern="天气", type=TriggerType.CONTAINS)
        assert trigger.matches("今天天气怎么样")
        assert trigger.matches("天气")
        assert trigger.matches("查询天气信息")

    def test_regex_match(self):
        """测试正则匹配"""
        trigger = SkillTrigger(pattern=r"\d+点", type=TriggerType.REGEX)
        assert trigger.matches("3点开会")
        assert trigger.matches("下午2点见")
        assert not trigger.matches("几点钟")
        assert not trigger.matches("现在几点")

    def test_case_sensitive(self):
        """测试大小写敏感"""
        trigger = SkillTrigger(pattern="Hello", type=TriggerType.EXACT, case_sensitive=True)
        assert trigger.matches("Hello")
        assert not trigger.matches("hello")
        assert not trigger.matches("HELLO")

    def test_case_insensitive(self):
        """测试大小写不敏感"""
        trigger = SkillTrigger(pattern="Hello", type=TriggerType.EXACT, case_sensitive=False)
        assert trigger.matches("Hello")
        assert trigger.matches("hello")
        assert trigger.matches("HELLO")


class TestSkill:
    """Skill 测试"""

    def test_skill_matches(self):
        """测试技能匹配"""
        skill = Skill(
            name="weather",
            triggers=[
                SkillTrigger(pattern="天气", type=TriggerType.CONTAINS),
                SkillTrigger(pattern="weather", type=TriggerType.CONTAINS)
            ]
        )
        assert skill.matches("今天天气怎么样")
        assert skill.matches("what's the weather")
        assert not skill.matches("你好")

    def test_get_matching_trigger(self):
        """测试获取匹配的触发器"""
        skill = Skill(
            name="test",
            triggers=[
                SkillTrigger(pattern="精确", type=TriggerType.EXACT),
                SkillTrigger(pattern="包含", type=TriggerType.CONTAINS)
            ]
        )
        trigger = skill.get_matching_trigger("精确")
        assert trigger is not None
        assert trigger.type == TriggerType.EXACT

        trigger = skill.get_matching_trigger("这里包含关键词")
        assert trigger is not None
        assert trigger.type == TriggerType.CONTAINS

    def test_render_user_prompt(self):
        """测试渲染用户提示词"""
        skill = Skill(
            name="test",
            user_prompt_template="用户说: {user_input}, 城市: {city}"
        )
        result = skill.render_user_prompt("查询天气", city="北京")
        assert "查询天气" in result
        assert "北京" in result

    def test_render_user_prompt_no_template(self):
        """测试无模板时直接返回输入"""
        skill = Skill(name="test")
        result = skill.render_user_prompt("原始输入")
        assert result == "原始输入"


class TestSkillLoader:
    """SkillLoader 测试"""

    def test_parse_skill_md(self):
        """测试解析 SKILL.md"""
        content = """---
name: weather
description: 获取天气信息
version: 1.0.0
triggers:
  - pattern: "天气"
    type: contains
  - pattern: "weather"
    type: contains
model: qwen
tags:
  - utility
  - weather
---

# 系统提示词

你是一个天气查询助手。

# 用户提示词模板

用户想要查询: {user_input}
"""
        loader = SkillLoader()
        skill = loader.parse(content)

        assert skill is not None
        assert skill.name == "weather"
        assert skill.description == "获取天气信息"
        assert skill.version == "1.0.0"
        assert len(skill.triggers) == 2
        assert skill.model_preference == "qwen"
        assert "utility" in skill.tags
        assert "天气查询助手" in skill.system_prompt
        assert "{user_input}" in skill.user_prompt_template

    def test_parse_simple_triggers(self):
        """测试解析简单触发器格式"""
        content = """---
name: test
triggers:
  - "关键词1"
  - "关键词2"
---

提示词内容
"""
        loader = SkillLoader()
        skill = loader.parse(content)

        assert skill is not None
        assert len(skill.triggers) == 2
        assert skill.triggers[0].pattern == "关键词1"
        assert skill.triggers[0].type == TriggerType.EXACT

    def test_parse_no_frontmatter(self):
        """测试无 front-matter 的情况"""
        content = "这是一个没有 front-matter 的文件"
        loader = SkillLoader()
        skill = loader.parse(content)
        assert skill is None

    def test_parse_missing_name(self):
        """测试缺少 name 字段"""
        content = """---
description: 测试
---

内容
"""
        loader = SkillLoader()
        skill = loader.parse(content)
        assert skill is None

    def test_load_file(self):
        """测试加载文件"""
        content = """---
name: file_test
description: 文件测试
---

系统提示词内容
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name

        try:
            loader = SkillLoader()
            skill = loader.load(temp_path)

            assert skill is not None
            assert skill.name == "file_test"
            # macOS 上 /var 是 /private/var 的符号链接，使用 samefile 比较
            assert Path(skill.source_path).samefile(Path(temp_path))
        finally:
            Path(temp_path).unlink()

    def test_load_nonexistent_file(self):
        """测试加载不存在的文件"""
        loader = SkillLoader()
        skill = loader.load("/nonexistent/path/SKILL.md")
        assert skill is None

    def test_cache(self):
        """测试缓存功能"""
        content = """---
name: cache_test
---

内容
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name

        try:
            loader = SkillLoader()

            # 第一次加载
            skill1 = loader.load(temp_path)
            # 第二次加载（应该从缓存）
            skill2 = loader.load(temp_path)

            assert skill1 is not None
            assert skill2 is not None

            # 清除缓存
            loader.clear_cache()
        finally:
            Path(temp_path).unlink()


class TestSkillRegistry:
    """SkillRegistry 测试"""

    def test_register_skill(self):
        """测试注册技能"""
        registry = SkillRegistry()
        skill = Skill(name="test", description="测试技能")

        assert registry.register(skill)
        assert registry.get("test") is not None
        assert registry.count == 1

    def test_register_duplicate(self):
        """测试重复注册"""
        registry = SkillRegistry()
        skill1 = Skill(name="test", description="版本1")
        skill2 = Skill(name="test", description="版本2")

        registry.register(skill1)
        registry.register(skill2)

        # 应该被覆盖
        assert registry.count == 1
        assert registry.get("test").description == "版本2"

    def test_unregister_skill(self):
        """测试注销技能"""
        registry = SkillRegistry()
        skill = Skill(name="test", tags=["tag1"])

        registry.register(skill)
        assert registry.unregister("test")
        assert registry.get("test") is None
        assert registry.count == 0

    def test_list_skills_by_tag(self):
        """测试按标签列出技能"""
        registry = SkillRegistry()
        registry.register(Skill(name="s1", tags=["utility"]))
        registry.register(Skill(name="s2", tags=["utility", "weather"]))
        registry.register(Skill(name="s3", tags=["chat"]))

        utility_skills = registry.list_skills(tag="utility")
        assert len(utility_skills) == 2

        chat_skills = registry.list_skills(tag="chat")
        assert len(chat_skills) == 1

    def test_list_enabled_only(self):
        """测试只列出启用的技能"""
        registry = SkillRegistry()
        registry.register(Skill(name="s1", enabled=True))
        registry.register(Skill(name="s2", enabled=False))

        enabled = registry.list_skills(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0].name == "s1"

        all_skills = registry.list_skills(enabled_only=False)
        assert len(all_skills) == 2

    def test_match_skills(self):
        """测试匹配技能"""
        registry = SkillRegistry()
        registry.register(Skill(
            name="weather",
            triggers=[SkillTrigger(pattern="天气", type=TriggerType.CONTAINS)]
        ))
        registry.register(Skill(
            name="time",
            triggers=[SkillTrigger(pattern="时间", type=TriggerType.CONTAINS)]
        ))

        matches = registry.match("今天天气怎么样")
        assert len(matches) == 1
        assert matches[0].skill.name == "weather"

    def test_match_no_result(self):
        """测试无匹配结果"""
        registry = SkillRegistry()
        registry.register(Skill(
            name="weather",
            triggers=[SkillTrigger(pattern="天气", type=TriggerType.CONTAINS)]
        ))

        matches = registry.match("你好")
        assert len(matches) == 0

    def test_enable_disable(self):
        """测试启用/禁用技能"""
        registry = SkillRegistry()
        registry.register(Skill(name="test", enabled=True))

        registry.disable("test")
        assert not registry.get("test").enabled

        registry.enable("test")
        assert registry.get("test").enabled

    def test_load_directory(self):
        """测试从目录加载技能"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建技能文件
            skill_dir = Path(temp_dir) / "skill1"
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text("""---
name: skill1
description: 技能1
---

提示词
""", encoding='utf-8')

            registry = SkillRegistry()
            loaded = registry.load_directory(temp_dir)

            assert loaded == 1
            assert registry.get("skill1") is not None

    def test_get_tags(self):
        """测试获取所有标签"""
        registry = SkillRegistry()
        registry.register(Skill(name="s1", tags=["a", "b"]))
        registry.register(Skill(name="s2", tags=["b", "c"]))

        tags = registry.get_tags()
        assert set(tags) == {"a", "b", "c"}


class TestSkillExecutor:
    """SkillExecutor 测试"""

    def setup_method(self):
        """每个测试前设置"""
        self.registry = SkillRegistry()
        self.registry.register(Skill(
            name="weather",
            description="天气查询",
            system_prompt="你是天气助手",
            user_prompt_template="查询 {user_input} 的天气",
            triggers=[SkillTrigger(pattern="天气", type=TriggerType.CONTAINS)],
            model_preference="qwen"
        ))
        self.executor = SkillExecutor(self.registry, default_system_prompt="默认助手")

    def test_execute_matched_skill(self):
        """测试执行匹配的技能"""
        result = self.executor.execute("北京天气怎么样")

        assert result.success
        assert result.skill_name == "weather"
        assert "天气助手" in result.system_prompt
        assert "北京天气怎么样" in result.user_prompt
        assert result.model_preference == "qwen"
        assert result.metadata["matched"] is True

    def test_execute_no_match(self):
        """测试无匹配时使用默认配置"""
        result = self.executor.execute("你好")

        assert result.success
        assert result.skill_name == ""
        assert result.system_prompt == "默认助手"
        assert result.user_prompt == "你好"
        assert result.metadata["matched"] is False

    def test_execute_force_skill(self):
        """测试强制使用指定技能"""
        result = self.executor.execute("随便说点什么", force_skill="weather")

        assert result.success
        assert result.skill_name == "weather"

    def test_execute_force_nonexistent_skill(self):
        """测试强制使用不存在的技能"""
        result = self.executor.execute("测试", force_skill="nonexistent")

        assert not result.success
        assert "不存在" in result.error

    def test_match_skill(self):
        """测试仅匹配不执行"""
        match = self.executor.match_skill("查询天气")

        assert match is not None
        assert match.skill.name == "weather"

    def test_get_all_matches(self):
        """测试获取所有匹配"""
        self.registry.register(Skill(
            name="weather2",
            triggers=[SkillTrigger(pattern="天气", type=TriggerType.CONTAINS)]
        ))

        matches = self.executor.get_all_matches("天气预报")
        assert len(matches) == 2

    def test_pre_processor(self):
        """测试前置处理器"""
        def strip_processor(text, context):
            return text.strip()

        self.executor.add_pre_processor(strip_processor)
        result = self.executor.execute("  北京天气  ")

        assert result.success
        assert result.skill_name == "weather"

    def test_post_processor(self):
        """测试后置处理器"""
        def add_metadata(result, context):
            result.metadata["custom"] = "value"
            return result

        self.executor.add_post_processor(add_metadata)
        result = self.executor.execute("天气")

        assert result.metadata.get("custom") == "value"

    def test_context_in_template(self):
        """测试上下文变量在模板中的使用"""
        self.registry.register(Skill(
            name="greeting",
            user_prompt_template="用户 {username} 说: {user_input}",
            triggers=[SkillTrigger(pattern="你好", type=TriggerType.CONTAINS)]
        ))

        result = self.executor.execute("你好", context={"username": "张三"})

        assert result.success
        assert "张三" in result.user_prompt


class TestSkillMatch:
    """SkillMatch 测试"""

    def test_skill_match_creation(self):
        """测试创建匹配结果"""
        skill = Skill(name="test")
        trigger = SkillTrigger(pattern="test")
        match = SkillMatch(skill=skill, trigger=trigger, score=0.9)

        assert match.skill.name == "test"
        assert match.trigger.pattern == "test"
        assert match.score == 0.9

    def test_skill_match_default_score(self):
        """测试默认分数"""
        skill = Skill(name="test")
        trigger = SkillTrigger(pattern="test")
        match = SkillMatch(skill=skill, trigger=trigger)

        assert match.score == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
