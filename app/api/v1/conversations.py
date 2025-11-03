from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.conversation import (
    ConversationResponseSchema,
    ConversationCreateSchema,
    ConversationUpdateSchema,
    ConversationListSchema
)
from app.models import User
from app.crud import conversation as crud_conversation
from app.api.deps import get_current_active_user

router = APIRouter()

@router.get("", response_model=list[ConversationListSchema])
async def get_conversations(
        skip: int = 0,
        limit: int = 100,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """获取对话列表"""
    conversations = await crud_conversation.get_conversations(
        db,
        user_id=current_user.id,
        skip=skip,
        limit=limit
    )
    return conversations

@router.post("", response_model=ConversationResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_conversation(
        conversation: ConversationCreateSchema,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """创建新对话"""
    return await crud_conversation.create_conversation(
        db,
        conversation_schema=conversation,
        user_id=current_user.id
    )

@router.get("/{conversation_id}", response_model=ConversationResponseSchema)
async def get_conversation(
        conversation_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """获取对话详情"""
    conversation = await crud_conversation.get_conversation_by_id(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id
    )

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在"
        )

    return conversation

@router.put("/{conversation_id}", response_model=ConversationResponseSchema)
async def update_conversation(
        conversation_id: int,
        conversation: ConversationUpdateSchema,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """重命名对话"""
    db_conversation = await crud_conversation.update_conversation(
        db,
        conversation_id=conversation_id,
        conversation_schema=conversation,
        user_id=current_user.id
    )

    if not db_conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在"
        )

    return db_conversation

@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
        conversation_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """删除对话"""
    success = await crud_conversation.delete_conversation(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在"
        )

    return None