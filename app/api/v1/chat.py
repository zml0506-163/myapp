"""
Chat API
app/api/v1/chat.py
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
import json
import asyncio
from typing import List, Dict, Any
from pydantic import BaseModel

from app.db.database import get_db_session
from app.models import User, MessageType, MessageStatus
from app.api.deps import get_current_active_user
from app.services.llm_service import llm_service
from app.services.workflow_service import workflow_service
from app.services.stream_service import background_generate_task, stream_events
from app.services.smart_qa_service import smart_qa_service
from app.crud import message as crud_message, conversation as crud_conversation
from app.schemas.message import MessageCreateSchema, AttachmentBaseSchema
from app.schemas.conversation import ConversationUpdateSchema
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


class ChatRequest(BaseModel):
    conversation_id: int
    content: str
    mode: str = "normal"  # "normal" | "attachment" | "multi_source"
    attachments: List[Dict[str, Any]] = []


async def should_generate_title(user_query: str, ai_response: str) -> bool:
    """判断是否应该生成标题"""
    if len(user_query.strip()) < 5 and len(ai_response.strip()) < 50:
        return False

    greetings = [
        '你好', 'hello', 'hi', '在吗', '在不在', '您好',
        '嗨', '喂', '早', '晚上好', '下午好', '上午好'
    ]

    user_lower = user_query.lower().strip()
    if any(greeting in user_lower for greeting in greetings) and len(user_query) < 15:
        return False

    prompt = f"""请判断以下对话是否是实质性对话（需要生成标题）。

用户：{user_query}
AI：{ai_response[:200]}...

判断标准：
- 实质性对话：包含具体问题、需求、咨询等，需要深入回答
- 非实质性对话：简单问候、寒暄、测试性提问

请只回答"是"或"否"，不要有其他内容。

回答："""

    response = ""
    try:
        async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个对话分类助手，判断对话是否实质性。"
        ):
            response += token

        response = response.strip().lower()
        return '是' in response or 'yes' in response

    except Exception as e:
        logger.warning(f"判断对话类型失败: {e}")
        return len(user_query) > 10


async def generate_conversation_title(user_query: str, ai_response: str) -> str:
    """根据对话内容生成标题"""
    prompt = f"""请根据以下对话内容，生成一个简短的对话标题（不超过10个字）：

用户：{user_query}
AI：{ai_response[:300]}...

要求：
1. 简洁明了，概括核心主题
2. 不超过10个字
3. 不要使用引号、书名号等标点符号
4. 直接输出标题，不要有其他内容
5. 如果是医疗咨询，突出疾病/症状关键词

标题："""

    title = ""
    try:
        async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个专业的标题生成助手，擅长用简短的语言概括主题。"
        ):
            title += token

        title = title.strip().replace('\n', '').replace('"', '').replace("'", '').replace('《', '').replace('》', '')

        if len(title) > 15:
            title = title[:15] + "..."

        if not title or len(title) < 2:
            title = "新对话"

        return title

    except Exception as e:
        logger.error(f"生成标题失败: {e}")
        return "新对话"


@router.post("/chat/stream")
async def chat_stream(
        request: ChatRequest,
        current_user: User = Depends(get_current_active_user)
):
    """统一聊天流式接口（启动后台任务+返回SSE流）"""

    # 验证对话归属
    async with get_db_session() as db:
        conversation = await crud_conversation.get_conversation_by_id(
            db,
            conversation_id=request.conversation_id,
            user_id=current_user.id
        )
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="对话不存在"
            )

    # 自动检测模式
    actual_mode = request.mode
    if request.attachments and request.mode == "normal":
        actual_mode = "attachment"

    # 如果是多源检索模式，检查是否可以使用历史上下文
    if actual_mode == "multi_source":
        # 获取历史消息
        async with get_db_session() as db:
            history_messages = await crud_message.get_messages_by_conversation(
                db,
                conversation_id=request.conversation_id,
                user_id=current_user.id
            ) or []
        
        # 判断是否需要重新检索
        should_retrieve = await smart_qa_service.should_retrieve_new_papers(
            request.content, 
            history_messages
        )
        
        if not should_retrieve:
            # 使用历史上下文回答
            logger.info("使用历史上下文回答，无需重新检索")
            actual_mode = "smart_qa"
        else:
            # 需要重新检索，保持多源检索模式
            logger.info("需要重新检索，使用多源检索模式")
            actual_mode = "multi_source"

    # 保存用户消息
    async with get_db_session() as db:
        user_message_schema = MessageCreateSchema(
            conversation_id=request.conversation_id,
            content=request.content,
            message_type=MessageType.USER,
            attachments=[
                AttachmentBaseSchema(
                    filename=att.get('filename', ''),
                    original_filename=att.get('original_filename', ''),
                    file_size=att.get('file_size', 0),
                    mime_type=att.get('mime_type')
                )
                for att in request.attachments
            ]
        )
        await crud_message.create_message(
            db,
            message_schema=user_message_schema,
            user_id=current_user.id
        )
        
        # 创建 AI 消息（初始状态为 generating）
        ai_message_schema = MessageCreateSchema(
            conversation_id=request.conversation_id,
            content="",  # 空内容
            message_type=MessageType.ASSISTANT
        )
        ai_message = await crud_message.create_message(
            db,
            message_schema=ai_message_schema,
            user_id=current_user.id,
            status=MessageStatus.GENERATING,
            metadata_json=json.dumps({
                "mode": actual_mode,
                "attachments": request.attachments
            }, ensure_ascii=False) if request.attachments else None
        )
        
        if not ai_message:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="创建消息失败"
            )
        
        message_id = ai_message['id']

    # 检查是否需要自动重命名
    is_first_conversation = (conversation.title == "新对话")
    
    # 启动后台生成任务
    asyncio.create_task(
        background_generate_task(
            message_id=message_id,
            conversation_id=request.conversation_id,
            user_id=current_user.id,
            user_query=request.content,
            mode=actual_mode,
            attachments=request.attachments,
            is_first_conversation=is_first_conversation
        )
    )
    
    # 返回 SSE 流
    return StreamingResponse(
        stream_events(message_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/chat/stream/continue/{message_id}")
async def continue_stream(
        message_id: int,
        current_user: User = Depends(get_current_active_user)
):
    """断线重连SSE接口"""
    
    # 验证消息归属
    async with get_db_session() as db:
        message = await crud_message.get_message_by_id(db, message_id)
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="消息不存在"
            )
        
        # 验证对话归属
        conversation = await crud_conversation.get_conversation_by_id(
            db,
            conversation_id=message.conversation_id,
            user_id=current_user.id
        )
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权访问该消息"
            )
    
    # 返回 SSE 流（使用同一个生成器）
    return StreamingResponse(
        stream_events(message_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/chat/stop")
async def stop_chat(
        conversation_id: int,
        current_user: User = Depends(get_current_active_user)
):
    """停止当前的聊天生成"""
    return {"message": "已发送停止信号"}