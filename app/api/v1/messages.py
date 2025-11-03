from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import json

from app.db.database import get_db
from app.schemas.message import MessageResponseSchema, MessageCreateSchema
from app.models import User, MessageType
from app.crud import message as crud_message
from app.api.deps import get_current_active_user

router = APIRouter()

@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
        conversation_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """获取对话的所有消息"""
    messages = await crud_message.get_messages_by_conversation(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id
    )

    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在"
        )

    return messages

@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def create_message(
        conversation_id: int,
        message: MessageCreateSchema,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """发送消息"""
    # 确保 conversation_id 匹配
    message.conversation_id = conversation_id

    db_message = await crud_message.create_message(
        db,
        message_schema=message,
        user_id=current_user.id
    )

    if not db_message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在"
        )

    return db_message

@router.post("/chat/stream")
async def chat_stream(
        message: MessageCreateSchema,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """流式 AI 回复（Server-Sent Events）"""

    # 先保存用户消息
    user_message = await crud_message.create_message(
        db,
        message_schema=message,
        user_id=current_user.id
    )

    if not user_message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在"
        )

    async def event_generator():
        """生成 SSE 事件流"""
        # 模拟 AI 回复（实际应该调用 LLM API）
        ai_response = "这是一个模拟的 AI 回复。在实际应用中，这里应该调用大语言模型 API。"

        # 逐字发送
        for i, char in enumerate(ai_response):
            yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.05)

        # 保存 AI 消息到数据库
        ai_message_schema = MessageCreateSchema(
            conversation_id=message.conversation_id,
            content=ai_response,
            message_type=MessageType.ASSISTANT
        )

        db_ai_message = await crud_message.create_message(
            db,
            message_schema=ai_message_schema,
            user_id=current_user.id
        )

        # 发送完成事件
        yield f"data: {json.dumps({'type': 'done', 'message_id': db_ai_message['id']})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )