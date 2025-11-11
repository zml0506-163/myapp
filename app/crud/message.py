from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.sql import func
from app.models import Message, Attachment, Conversation, MessageStatus, MessageType
from app.schemas.message import MessageCreateSchema

async def get_messages_by_conversation(
        db: AsyncSession,
        conversation_id: int,
        user_id: int
) -> list[dict] | None:
    """获取对话的所有消息（手动加载附件）"""
    # 先验证对话属于该用户
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id
        )
    )
    if not conv_result.scalar_one_or_none():
        return None

    # 获取消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()

    # 手动加载每条消息的附件
    messages_with_attachments = []
    for msg in messages:
        att_result = await db.execute(
            select(Attachment).where(Attachment.message_id == msg.id)
        )
        attachments = att_result.scalars().all()

        messages_with_attachments.append({
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "content": msg.content,
            "message_type": msg.message_type,
            "status": msg.status,
            "metadata": msg.metadata_json,  # 添加元数据
            "created_at": msg.created_at,
            "attachments": [
                {
                    "id": att.id,
                    "filename": att.filename,
                    "original_filename": att.original_filename,
                    "file_size": att.file_size,
                    "mime_type": att.mime_type,
                    "created_at": att.created_at
                }
                for att in attachments
            ]
        })

    return messages_with_attachments

async def create_message(
        db: AsyncSession,
        message_schema: MessageCreateSchema,
        user_id: int,
        status: MessageStatus = MessageStatus.COMPLETED,
        metadata_json: str | None = None  # 添加元数据参数
) -> dict | None:
    """创建消息"""
    # 验证对话属于该用户
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == message_schema.conversation_id,
            Conversation.user_id == user_id
        )
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        return None

    # 创建消息
    db_message = Message(
        conversation_id=message_schema.conversation_id,
        content=message_schema.content,
        message_type=message_schema.message_type,
        status=status,
        metadata_json=metadata_json  # 添加元数据
    )
    db.add(db_message)
    await db.flush()  # 获取消息 ID

    # 创建附件
    attachments_data = []
    if message_schema.attachments:
        for att_schema in message_schema.attachments:
            db_attachment = Attachment(
                message_id=db_message.id,
                filename=att_schema.filename,
                original_filename=att_schema.original_filename,
                file_size=att_schema.file_size,
                file_path=att_schema.filename,
                mime_type=att_schema.mime_type
            )
            db.add(db_attachment)
            await db.flush()

            attachments_data.append({
                "id": db_attachment.id,
                "filename": db_attachment.filename,
                "original_filename": db_attachment.original_filename,
                "file_size": db_attachment.file_size,
                "mime_type": db_attachment.mime_type,
                "created_at": db_attachment.created_at
            })

    # 更新对话的 updated_at
    await db.execute(
        update(Conversation)
        .where(Conversation.id == message_schema.conversation_id)
        .values(updated_at=func.now())
    )

    await db.commit()
    await db.refresh(db_message)

    return {
        "id": db_message.id,
        "conversation_id": db_message.conversation_id,
        "content": db_message.content,
        "message_type": db_message.message_type,
        "status": db_message.status,
        "metadata": db_message.metadata_json,  # 添加元数据
        "created_at": db_message.created_at,
        "attachments": attachments_data
    }


async def get_message_by_id(db: AsyncSession, message_id: int) -> Message | None:
    """获取消息"""
    result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    return result.scalar_one_or_none()


async def update_message(
        db: AsyncSession,
        message_id: int,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETED
) -> bool:
    """更新消息内容和状态"""
    await db.execute(
        update(Message)
        .where(Message.id == message_id)
        .values(content=content, status=status)
    )
    await db.commit()
    return True


async def update_message_status(
        db: AsyncSession,
        message_id: int,
        status: MessageStatus
) -> bool:
    """更新消息状态"""
    await db.execute(
        update(Message)
        .where(Message.id == message_id)
        .values(status=status)
    )
    await db.commit()
    return True

async def delete_message(
        db: AsyncSession,
        message_id: int,
        user_id: int
) -> bool:
    """删除消息（手动级联删除附件）"""
    # 验证消息属于该用户的对话
    result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.id == message_id,
            Conversation.user_id == user_id
        )
    )
    message = result.scalar_one_or_none()
    if not message:
        return False

    # 删除所有相关附件
    await db.execute(
        delete(Attachment).where(Attachment.message_id == message_id)
    )

    # 删除消息
    await db.execute(
        delete(Message).where(Message.id == message_id)
    )

    await db.commit()
    return True