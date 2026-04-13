# PyClaw 使用指南

轻量级个人 AI 助手系统

## 快速开始

### 安装

```bash
cd pyclaw
pip install -e .
```

### 初始化配置

```bash
# 生成配置文件模板
pyclaw init

# 指定输出路径
pyclaw init -o ~/.pyclaw/config.yaml
```

### 配置 API Key

编辑 `config.yaml` 或设置环境变量：

```bash
# Claude (Anthropic)
export ANTHROPIC_API_KEY=your_key

# DeepSeek
export DEEPSEEK_API_KEY=your_key

# 通义千问
export DASHSCOPE_API_KEY=your_key

# 豆包
export DOUBAO_API_KEY=your_key
```

---

## CLI 命令

### 基础对话

```bash
# 简单对话
pyclaw chat "你好，请介绍一下自己"

# 指定 Provider
pyclaw chat -p claude "帮我写一个 Python 快速排序"
pyclaw chat -p deepseek "解释一下什么是递归"

# 指定任务类型（自动路由到最佳模型）
pyclaw chat -t code_generation "实现二分查找"
pyclaw chat -t chinese_chat "用中文解释量子计算"

# 自定义系统提示词
pyclaw chat -s "你是一个专业的代码审查员" "检查这段代码的问题"
```

### 交互模式 (REPL)

```bash
# 进入交互式对话
pyclaw repl

# 指定 Provider
pyclaw repl -p claude

# 带系统提示词
pyclaw repl -s "你是一个 Python 专家"
```

REPL 内置命令：

- `exit` / `quit` / `q` - 退出
- `clear` - 清空对话历史
- `Ctrl+C` - 中断

### 后台服务

```bash
# 启动服务（前台运行）
pyclaw server start

# 以守护进程模式启动（后台运行）
pyclaw server start -d

# 查看服务状态
pyclaw server status

# 停止服务
pyclaw server stop

# 强制停止
pyclaw server stop -f

# 重启服务
pyclaw server restart

# 查看日志
pyclaw server logs

# 查看最近 100 行日志
pyclaw server logs -n 100

# 持续跟踪日志
pyclaw server logs -f
```

服务文件位置：

- PID 文件: `~/.pyclaw/pyclaw.pid`
- 日志文件: `~/.pyclaw/logs/server.log`

### 系统状态

```bash
# 查看系统状态
pyclaw status

# 列出可用 Provider
pyclaw providers

# 检测任务类型
pyclaw detect "帮我写一个排序算法"
pyclaw detect "翻译成英文"
```

### 全局选项

```bash
# 查看版本
pyclaw --version

# 详细输出
pyclaw -v chat "你好"

# 调试模式
pyclaw -d chat "你好"

# 指定配置文件
pyclaw -c /path/to/config.yaml chat "你好"
```

---

## 配置文件

配置文件查找顺序：

1. 环境变量 `PYCLAW_CONFIG`
2. 当前目录 `pyclaw.yaml` 或 `config.yaml`
3. 用户目录 `~/.pyclaw/config.yaml`

### 配置结构

```yaml
# LLM 配置
llm:
  default_provider: deepseek  # 默认 Provider

  # 任务路由规则
  task_routing:
    code_generation: claude      # 代码生成 -> Claude
    code_review: claude          # 代码审查 -> Claude
    complex_reasoning: deepseek  # 复杂推理 -> DeepSeek
    chinese_chat: qwen           # 中文对话 -> Qwen
    default: deepseek            # 默认 -> DeepSeek

# Provider 配置
providers:
  claude:
    api_key: sk-xxx              # API Key
    api_base: https://api.anthropic.com  # API 地址（支持中转）
    model: claude-sonnet-4-20250514
    max_tokens: 8192
    temperature: 0.7
    timeout: 600

  deepseek:
    api_key: ${DEEPSEEK_API_KEY}  # 支持环境变量
    api_base: https://api.deepseek.com/v1
    model: deepseek-chat
    max_tokens: 4096
    temperature: 0.7

# 通道配置
channels:
  imessage:
    enabled: true
    db_path: ~/Library/Messages/chat.db
    poll_interval: 2
    allowed_senders:
      - "+8613800138000"
      - "user@example.com"

  wechat:
    enabled: false

# 记忆配置
memory:
  database_path: ~/.pyclaw/memory.db
  max_context_tokens: 8000
  max_history_messages: 50

# 日志配置
logging:
  level: INFO
  file: ~/.pyclaw/pyclaw.log
```

### 使用中转 API

```yaml
providers:
  claude:
    api_key: sk-xxx
    api_base: https://your-proxy.com  # 中转地址
    model: claude-sonnet-4-20250514
```

---

## 任务类型

| 任务类型            | 说明     | 推荐 Provider |
| ------------------- | -------- | ------------- |
| `code_generation`   | 代码生成 | Claude        |
| `code_review`       | 代码审查 | Claude        |
| `complex_reasoning` | 复杂推理 | DeepSeek      |
| `math_logic`        | 数学逻辑 | DeepSeek      |
| `chinese_chat`      | 中文对话 | Qwen          |
| `translation`       | 翻译     | Qwen          |
| `summarization`     | 摘要     | DeepSeek      |
| `creative_writing`  | 创意写作 | Claude        |
| `simple_qa`         | 简单问答 | DeepSeek      |

---

## 技能系统

技能目录：`~/.pyclaw/skills/`

### 技能格式

技能文件：`*.SKILL.md` 或 `SKILL.md`

```markdown
---
name: weather
description: 查询天气信息
version: 1.0.0
triggers:
  - pattern: "天气"
    type: contains
  - pattern: "weather"
    type: contains
tags:
  - utility
enabled: true
---

# 系统提示词

你是一个天气查询助手...

# 用户提示词模板

用户请求: {user_input}
```

### 触发器类型

- `exact` - 精确匹配
- `prefix` - 前缀匹配
- `contains` - 包含匹配
- `regex` - 正则匹配

### 内置技能

| 分类    | 技能            | 说明               |
| ------- | --------------- | ------------------ |
| utility | weather         | 天气查询 (wttr.in) |
| utility | summarize       | 内容摘要           |
| utility | github          | GitHub CLI         |
| notes   | apple-notes     | Apple Notes        |
| notes   | obsidian        | Obsidian           |
| notes   | notion          | Notion API         |
| tasks   | apple-reminders | Apple 提醒事项     |
| tasks   | things-mac      | Things 3           |
| media   | openai-whisper  | 语音转文字         |
| media   | spotify-player  | Spotify 控制       |
| system  | peekaboo        | macOS UI 自动化    |
| system  | tmux            | 终端会话管理       |

---

## 环境变量

| 变量                      | 说明             |
| ------------------------- | ---------------- |
| `PYCLAW_CONFIG`           | 配置文件路径     |
| `ANTHROPIC_API_KEY`       | Claude API Key   |
| `DEEPSEEK_API_KEY`        | DeepSeek API Key |
| `DASHSCOPE_API_KEY`       | 通义千问 API Key |
| `DOUBAO_API_KEY`          | 豆包 API Key     |
| `PYCLAW_DEFAULT_PROVIDER` | 默认 Provider    |
| `PYCLAW_LOG_LEVEL`        | 日志级别         |

---

## 常见问题

### 没有可用的 Provider

```
错误: 没有可用的 LLM Provider，请检查配置文件中的 API Key
```

解决：配置 API Key（配置文件或环境变量）

### 配置文件解析错误

检查 YAML 格式：

- 使用英文引号 `"` 而非中文引号 `"`
- 缩进使用空格，不要用 Tab
- 列表项使用 `- ` 开头

### API 调用超时

增加 timeout 配置：

```yaml
providers:
  claude:
    timeout: 600  # 10分钟
```

---

## 记忆系统

PyClaw 具有完整的记忆系统，能够记住对话历史和用户信息。

### 数据目录

PyClaw 的所有数据存储在用户主目录下的隐藏文件夹中：

```
~/.pyclaw/                    # 即 /Users/<用户名>/.pyclaw/
├── config.yaml               # 配置文件（含 API Key）
├── data/
│   └── pyclaw.db            # SQLite 数据库（对话、消息、事实）
├── logs/
│   └── server.log           # 后台服务日志
├── skills/                   # 自定义技能目录
└── pyclaw.pid               # 服务进程 ID（运行时）
```

**注意**：以 `.` 开头的文件夹在 macOS Finder 中默认隐藏。

**查看隐藏文件**：在 Finder 中按 `Command + Shift + .`

**直接打开目录**：

```bash
open ~/.pyclaw
```

### 数据备份

建议定期备份以下文件：

```bash
# 复制到桌面
cp -r ~/.pyclaw ~/Desktop/pyclaw_backup

# 或压缩备份
zip -r ~/Desktop/pyclaw_backup.zip ~/.pyclaw
```

| 文件             | 是否需要备份 | 说明                         |
| ---------------- | ------------ | ---------------------------- |
| `config.yaml`    | ✅ 是         | 配置文件（注意保护 API Key） |
| `data/pyclaw.db` | ✅ 是         | 对话历史和记忆数据           |
| `skills/`        | ✅ 是         | 自定义技能                   |
| `logs/`          | ❌ 否         | 运行日志，可重新生成         |
| `pyclaw.pid`     | ❌ 否         | 临时文件                     |

### 数据存储位置

| 数据            | 路径                         | 说明                     |
| --------------- | ---------------------------- | ------------------------ |
| PyClaw 数据库   | `~/.pyclaw/data/pyclaw.db`   | 对话历史、事实、摘要     |
| iMessage 数据库 | `~/Library/Messages/chat.db` | macOS 系统数据库（只读） |
| 服务日志        | `~/.pyclaw/logs/server.log`  | 后台服务日志             |
| PID 文件        | `~/.pyclaw/pyclaw.pid`       | 服务进程 ID              |

### 查看数据库内容

```bash
# 查看所有表
sqlite3 ~/.pyclaw/data/pyclaw.db ".tables"

# 查看对话列表
sqlite3 ~/.pyclaw/data/pyclaw.db "SELECT * FROM conversations"

# 查看最近消息
sqlite3 ~/.pyclaw/data/pyclaw.db "SELECT id, role, substr(content,1,50) FROM messages ORDER BY id DESC LIMIT 10"
```

### 记忆类型

1. **对话历史** - 按通道和联系人分别存储
   - 每个 iMessage 联系人有独立的对话上下文
   - CLI 对话也会保存历史

2. **事实记忆** - 从对话中提取的持久信息
   - 用户偏好（preference）
   - 用户信息（info）
   - 待办任务（task）
   - 用户习惯（habit）

3. **对话摘要** - 长对话自动压缩
   - 超过 50 条消息时触发压缩
   - 保留最近 20 条消息
   - 旧消息压缩为摘要

### 配置选项

```yaml
memory:
  database_path: ~/.pyclaw/memory.db  # 数据库路径
  max_context_tokens: 8000            # 上下文 token 限制
  max_history_messages: 50            # 历史消息数量限制
  enable_facts: true                  # 是否启用事实记忆
```

### 上下文构建

PyClaw 自动构建上下文，按以下顺序：

1. 系统提示词
2. 用户事实（已知信息）
3. 历史摘要
4. 最近对话历史
5. 当前消息

当 token 超出限制时，自动从最早的消息开始截断。

---

## 开发

### 运行测试

```bash
pytest tests/ -v
```

### 项目结构

```
pyclaw/
├── src/pyclaw/
│   ├── core/          # 核心模块
│   ├── llm/           # LLM 集成
│   ├── memory/        # 记忆系统
│   ├── skills/        # 技能系统
│   ├── channels/      # 通道系统
│   ├── agent/         # Agent 核心
│   └── cli.py         # CLI 入口
├── skills/            # 内置技能
├── tests/             # 测试
└── config.yaml        # 配置文件
```
