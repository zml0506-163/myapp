from pydantic import BaseModel
from datetime import datetime

# 对话基础 Schema
class ConversationBaseSchema(BaseModel):
    title: str

# 对话创建 Schema
class ConversationCreateSchema(BaseModel):
    title: str = "新对话"

# 对话更新 Schema
class ConversationUpdateSchema(BaseModel):
    title: str

# 对话响应 Schema
class ConversationResponseSchema(ConversationBaseSchema):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True

# 对话列表 Schema（带消息数量）
class ConversationListSchema(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime | None = None
    message_count: int = 0

    class Config:
        from_attributes = True