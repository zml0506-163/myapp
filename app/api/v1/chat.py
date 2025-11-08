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
from app.models import User, MessageType
from app.api.deps import get_current_active_user
from app.services.llm_service import llm_service
from app.services.workflow_service import workflow_service
from app.crud import message as crud_message, conversation as crud_conversation
from app.schemas.message import MessageCreateSchema
from app.schemas.conversation import ConversationUpdateSchema

router = APIRouter()


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
        print(f"判断对话类型失败: {e}")
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
        print(f"生成标题失败: {e}")
        return "新对话"


@router.post("/chat/stream")
async def chat_stream(
        request: ChatRequest,
        current_user: User = Depends(get_current_active_user)
):
    """统一聊天流式接口"""

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

    # 保存用户消息
    async with get_db_session() as db:
        user_message_schema = MessageCreateSchema(
            conversation_id=request.conversation_id,
            content=request.content,
            message_type=MessageType.USER,
            attachments=[
                {
                    'filename': att.get('filename', ''),
                    'original_filename': att.get('original_filename', ''),
                    'file_size': att.get('file_size', 0),
                    'mime_type': att.get('mime_type')
                }
                for att in request.attachments
            ]
        )
        await crud_message.create_message(
            db,
            message_schema=user_message_schema,
            user_id=current_user.id
        )

    # 检查是否需要自动重命名
    is_first_conversation = (conversation.title == "新对话")

    async def event_generator():
        """生成 SSE 事件流"""
        try:
            ai_content = ""

            if actual_mode == "multi_source":
                # === 模式1: 多源检索工作流 ===
                async for output in workflow_service.execute_with_streaming(
                        conversation_id=request.conversation_id,
                        user_id=current_user.id,
                        user_query=request.content,
                        user_attachments=request.attachments,
                        is_first_conversation=is_first_conversation
                ):
                    yield f"data: {json.dumps(output, ensure_ascii=False)}\n\n"

            elif actual_mode == "attachment":
                # === 模式2: 附件问答（统一处理） ===
                if not request.attachments:
                    yield f"data: {json.dumps({'type': 'error', 'content': '未提供附件'}, ensure_ascii=False)}\n\n"
                    return

                # 处理附件
                from app.services.file_service import file_service
                file_ids, only_images = await file_service.process_attachments(request.attachments)

                if not file_ids:
                    yield f"data: {json.dumps({'type': 'error', 'content': '附件处理失败'}, ensure_ascii=False)}\n\n"
                    return

                # 如果只有一张图片，使用VL模型
                if only_images and len(file_ids) == 1:
                    image_att = request.attachments[0]
                    async for chunk in llm_service.chat_with_image_stream(
                            text=request.content,
                            image_path=image_att.get('file_path', '')
                    ):
                        ai_content += chunk
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
                else:
                    # 使用统一接口（支持多文件）
                    async for chunk in llm_service.chat_with_context(
                            user_query=request.content,
                            file_ids=file_ids,
                            system_prompt="你是一个专业的文档分析助手。请仔细阅读文件并基于内容回答。"
                    ):
                        ai_content += chunk
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"

                # 保存 AI 消息
                async with get_db_session() as db:
                    ai_message_schema = MessageCreateSchema(
                        conversation_id=request.conversation_id,
                        content=ai_content,
                        message_type=MessageType.ASSISTANT
                    )
                    ai_message = await crud_message.create_message(
                        db,
                        message_schema=ai_message_schema,
                        user_id=current_user.id
                    )

                    yield f"data: {json.dumps({'type': 'done', 'message_id': ai_message['id']}, ensure_ascii=False)}\n\n"

            else:  # normal mode
                # === 模式3: 普通问答（使用统一接口） ===
                async with get_db_session() as db:
                    from sqlalchemy import select
                    from app.models import Message

                    result = await db.execute(
                        select(Message)
                        .where(Message.conversation_id == request.conversation_id)
                        .order_by(Message.created_at.desc())
                        .limit(5)
                    )
                    history_messages = result.scalars().all()

                # 构建历史对话
                history = []
                for msg in reversed(list(history_messages)):
                    history.append({
                        "role": "user" if msg.message_type == MessageType.USER else "assistant",
                        "content": msg.content
                    })

                # 使用统一接口
                async for chunk in llm_service.chat_with_context(
                        user_query=request.content,
                        history=history,
                        system_prompt="你是一个专业的医疗问答助手。"
                ):
                    ai_content += chunk
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"

                # 保存 AI 消息
                async with get_db_session() as db:
                    ai_message_schema = MessageCreateSchema(
                        conversation_id=request.conversation_id,
                        content=ai_content,
                        message_type=MessageType.ASSISTANT
                    )
                    ai_message = await crud_message.create_message(
                        db,
                        message_schema=ai_message_schema,
                        user_id=current_user.id
                    )

                    yield f"data: {json.dumps({'type': 'done', 'message_id': ai_message['id']}, ensure_ascii=False)}\n\n"

            # === 智能重命名逻辑 ===
            if is_first_conversation and ai_content and actual_mode != "multi_source":
                try:
                    should_rename = await should_generate_title(request.content, ai_content)

                    if should_rename:
                        new_title = await generate_conversation_title(request.content, ai_content)

                        async with get_db_session() as db:
                            await crud_conversation.update_conversation(
                                db,
                                conversation_id=request.conversation_id,
                                conversation_schema=ConversationUpdateSchema(title=new_title),
                                user_id=current_user.id
                            )

                        yield f"data: {json.dumps({{'type': 'title_updated', 'conversation_id': request.conversation_id, 'title': new_title}}, ensure_ascii=False)}\n\n"
                    else:
                        print(f"检测到寒暄对话，保持标题为'新对话'")

                except Exception as e:
                    print(f"自动重命名失败: {e}")

        except asyncio.CancelledError:
            if ai_content and actual_mode != "multi_source":
                async with get_db_session() as db:
                    ai_message_schema = MessageCreateSchema(
                        conversation_id=request.conversation_id,
                        content=ai_content + "\n\n[回答已中断]",
                        message_type=MessageType.ASSISTANT
                    )
                    await crud_message.create_message(
                        db,
                        message_schema=ai_message_schema,
                        user_id=current_user.id
                    )
            raise

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"Chat Error: {error_detail}")
            yield f"data: {json.dumps({'type': 'error', 'content': f'❌ 错误: {str(e)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/chat/stop")
async def stop_chat(
        conversation_id: int,
        current_user: User = Depends(get_current_active_user)
):
    """停止当前的聊天生成"""
    return {"message": "已发送停止信号"}