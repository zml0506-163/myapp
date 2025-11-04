from pydantic import BaseModel
from enum import Enum

class ChatMode(str, Enum):
    """聊天模式"""
    NORMAL = "normal"              # 普通问答
    WITH_ATTACHMENT = "attachment"  # 附件问答
    MULTI_SOURCE = "multi_source"   # 多源检索

class ChatRequestSchema(BaseModel):
    """聊天请求"""
    conversation_id: int
    content: str
    mode: ChatMode = ChatMode.NORMAL
    attachments: list[dict] = []  # [{id, filename, file_path, mime_type}]

class ChatResponseSchema(BaseModel):
    """聊天响应"""
    message_id: int
    content: str