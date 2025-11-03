from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.models import Conversation, Message
from app.schemas.conversation import ConversationCreateSchema, ConversationUpdateSchema

async def get_conversations(
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 100
) -> list[dict]:
    """获取用户的对话列表"""
    # 子查询：统计每个对话的消息数
    message_count_subq = (
        select(
            Message.conversation_id,
            func.count(Message.id).label("message_count")
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    # 主查询
    result = await db.execute(
        select(
            Conversation,
            func.coalesce(message_count_subq.c.message_count, 0).label("message_count")
        )
        .outerjoin(
            message_count_subq,
            Conversation.id == message_count_subq.c.conversation_id
        )
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )

    rows = result.all()
    return [
        {
            "id": row.Conversation.id,
            "title": row.Conversation.title,
            "user_id": row.Conversation.user_id,
            "created_at": row.Conversation.created_at,
            "updated_at": row.Conversation.updated_at,
            "message_count": row.message_count
        }
        for row in rows
    ]

async def get_conversation_by_id(
        db: AsyncSession,
        conversation_id: int,
        user_id: int
) -> Conversation | None:
    """获取单个对话"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id
        )
    )
    return result.scalar_one_or_none()

async def create_conversation(
        db: AsyncSession,
        conversation_schema: ConversationCreateSchema,
        user_id: int
) -> Conversation:
    """创建对话"""
    db_conversation = Conversation(
        title=conversation_schema.title,
        user_id=user_id
    )
    db.add(db_conversation)
    await db.commit()
    await db.refresh(db_conversation)
    return db_conversation

async def update_conversation(
        db: AsyncSession,
        conversation_id: int,
        conversation_schema: ConversationUpdateSchema,
        user_id: int
) -> Conversation | None:
    """更新对话"""
    db_conversation = await get_conversation_by_id(db, conversation_id, user_id)
    if not db_conversation:
        return None

    db_conversation.title = conversation_schema.title
    await db.commit()
    await db.refresh(db_conversation)
    return db_conversation

async def delete_conversation(
        db: AsyncSession,
        conversation_id: int,
        user_id: int
) -> bool:
    """删除对话"""
    result = await db.execute(
        delete(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id
        )
    )
    await db.commit()
    return result.rowcount > 0