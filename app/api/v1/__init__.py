# app/api/v1/__init__.py
from fastapi import APIRouter
from app.api.v1 import auth, conversations, messages, upload, chat

api_router = APIRouter()

# 路由注册顺序很重要！
# 1. 认证路由
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
# 2. 聊天路由（统一入口，必须在 messages 之前）
api_router.include_router(chat.router, prefix="", tags=["chat"])
# 3. 对话管理路由
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
# 4. 消息查询路由（只保留查询功能）
api_router.include_router(messages.router, prefix="", tags=["messages"])
# 5. 文件上传路由
api_router.include_router(upload.router, prefix="", tags=["upload"])
