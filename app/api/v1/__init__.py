from fastapi import APIRouter
from app.api.v1 import auth, conversations, messages, upload

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(messages.router, prefix="", tags=["messages"])
api_router.include_router(upload.router, prefix="", tags=["upload"])