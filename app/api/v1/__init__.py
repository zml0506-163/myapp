# app/api/v1/__init__.py
from fastapi import APIRouter
from app.api.v1 import auth, conversations, messages, upload, chat

api_router = APIRouter()

# 注意：chat 路由要在 messages 之前注册，避免路径冲突
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(chat.router, prefix="", tags=["chat"])  # 先注册 chat
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(messages.router, prefix="", tags=["messages"])
api_router.include_router(upload.router, prefix="", tags=["upload"])