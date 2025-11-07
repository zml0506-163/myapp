from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models import User
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