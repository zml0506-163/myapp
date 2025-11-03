from pydantic import BaseModel
from datetime import datetime
from app.models import MessageType

# 附件基础 Schema
class AttachmentBaseSchema(BaseModel):
    filename: str
    original_filename: str
    file_size: int
    mime_type: str | None = None

# 附件响应 Schema
class AttachmentResponseSchema(AttachmentBaseSchema):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# 消息基础 Schema
class MessageBaseSchema(BaseModel):
    content: str
    message_type: MessageType

# 消息创建 Schema
class MessageCreateSchema(MessageBaseSchema):
    conversation_id: int
    attachments: list[AttachmentBaseSchema] = []

# 消息响应 Schema
class MessageResponseSchema(MessageBaseSchema):
    id: int
    conversation_id: int
    created_at: datetime
    attachments: list[AttachmentResponseSchema] = []

    class Config:
        from_attributes = True