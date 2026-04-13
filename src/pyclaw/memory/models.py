"""
记忆系统数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageRole(Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class Message:
    """消息数据类"""
    id: Optional[int] = None
    conversation_id: Optional[int] = None
    role: MessageRole = MessageRole.USER
    content: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 工具调用相关
    tool_calls: Optional[List[Dict]] = None  # 助手发起的工具调用
    tool_call_id: Optional[str] = None       # 工具响应对应的调用ID
    name: Optional[str] = None               # 工具名称

    # 多模态内容
    attachments: Optional[List[Dict]] = None  # 图片等附件

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 LLM API）"""
        msg = {
            "role": self.role.value,
        }

        # 处理多模态内容
        if self.attachments and self.role == MessageRole.USER:
            # 生成 Claude API 需要的多模态格式
            content_parts = []

            # 添加图片
            for attachment in self.attachments:
                if attachment.get("type") == "image":
                    content_parts.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": attachment.get("media_type", "image/jpeg"),
                            "data": attachment.get("data", "")
                        }
                    })

            # 添加文本
            if self.content:
                content_parts.append({
                    "type": "text",
                    "text": self.content
                })

            msg["content"] = content_parts
        else:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls

        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id

        if self.name and self.role == MessageRole.TOOL:
            msg["name"] = self.name

        return msg

    @classmethod
    def from_dict(cls, data: Dict[str, Any], conversation_id: Optional[int] = None) -> "Message":
        """从字典创建消息"""
        role = MessageRole(data.get("role", "user"))
        return cls(
            conversation_id=conversation_id,
            role=role,
            content=data.get("content", ""),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
            metadata=data.get("metadata", {}),
            attachments=data.get("attachments")
        )


@dataclass
class Conversation:
    """对话数据类"""
    id: Optional[int] = None
    channel: str = "cli"           # 来源通道: cli, imessage, wechat
    channel_id: str = ""           # 通道内的会话标识
    title: str = ""                # 对话标题
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 关联的消息（非持久化字段）
    messages: List[Message] = field(default_factory=list)

    # 摘要（可选）
    summary: Optional[str] = None


@dataclass
class Summary:
    """对话摘要"""
    id: Optional[int] = None
    conversation_id: int = 0
    content: str = ""
    message_range: tuple = (0, 0)  # 摘要覆盖的消息范围
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Fact:
    """提取的事实"""
    id: Optional[int] = None
    content: str = ""
    source_conversation_id: Optional[int] = None
    category: str = ""  # 分类: preference, info, task 等
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
