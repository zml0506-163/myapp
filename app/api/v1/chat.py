from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
import json
import asyncio
from typing import List, Dict, Any
from pydantic import BaseModel

from app.db.database import get_db_session
from app.models import User
from app.api.deps import get_current_active_user
from app.services.llm_service import llm_service
from app.services.workflow_service import workflow_service
from app.crud import message as crud_message, conversation as crud_conversation
from app.schemas.message import MessageCreateSchema
from app.schemas.conversation import ConversationUpdateSchema
from app.models import MessageType

router = APIRouter()


# 聊天请求模型
class ChatRequest(BaseModel):
    conversation_id: int
    content: str
    mode: str = "normal"  # "normal" | "attachment" | "multi_source"
    attachments: List[Dict[str, Any]] = []


async def should_generate_title(user_query: str, ai_response: str) -> bool:
    """
    判断是否应该生成标题（过滤寒暄、简单问候）

    Args:
        user_query: 用户的第一条消息
        ai_response: AI的回复

    Returns:
        True: 应该生成标题（实质性对话）
        False: 不应该生成标题（寒暄、简单问候）
    """
    # 简单规则：用户消息太短（<5字）且AI回复也较短（<50字），认为是寒暄
    if len(user_query.strip()) < 5 and len(ai_response.strip()) < 50:
        return False

    # 常见寒暄关键词
    greetings = [
        '你好', 'hello', 'hi', '在吗', '在不在', '您好',
        '嗨', '喂', '早', '晚上好', '下午好', '上午好',
        '在的', '在呢', '怎么样', '能帮我吗'
    ]

    user_lower = user_query.lower().strip()

    # 如果用户消息只是简单问候
    if any(greeting in user_lower for greeting in greetings) and len(user_query) < 15:
        return False

    # 使用 LLM 判断（更准确但会增加一次调用）
    prompt = f"""请判断以下对话是否是实质性对话（需要生成标题）。

用户：{user_query}
AI：{ai_response[:200]}...

判断标准：
- 实质性对话：包含具体问题、需求、咨询等，需要深入回答
- 非实质性对话：简单问候、寒暄、测试性提问

请只回答"是"或"否"，不要有其他内容。

回答："""

    messages = [{"role": "user", "content": prompt}]

    response = ""
    try:
        async for token in llm_service.chat_stream(
                messages=messages,
                system_prompt="你是一个对话分类助手，判断对话是否实质性。"
        ):
            response += token

        response = response.strip().lower()

        # 判断结果
        return '是' in response or 'yes' in response

    except Exception as e:
        print(f"判断对话类型失败: {e}")
        # 默认保守策略：如果判断失败，且用户消息较长，则生成标题
        return len(user_query) > 10


async def generate_conversation_title(user_query: str, ai_response: str) -> str:
    """
    根据对话内容生成标题

    Args:
        user_query: 用户的消息
        ai_response: AI的回复

    Returns:
        生成的标题（10字以内）
    """
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

    messages = [{"role": "user", "content": prompt}]

    title = ""
    try:
        async for token in llm_service.chat_stream(
                messages=messages,
                system_prompt="你是一个专业的标题生成助手，擅长用简短的语言概括主题。"
        ):
            title += token

        # 清理标题：去除换行、引号、多余空格
        title = title.strip().replace('\n', '').replace('"', '').replace("'", '').replace('《', '').replace('》', '')

        # 限制长度
        if len(title) > 15:
            title = title[:15] + "..."

        # 如果标题为空或太短，使用默认标题
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
    """
    统一聊天流式接口（唯一入口）

    功能：
    1. 自动保存用户消息
    2. 流式生成 AI 回复
    3. 自动保存 AI 回复
    4. 智能重命名对话标题（首次实质性对话）

    模式说明：
    - normal: 普通问答
    - attachment: 附件问答（有附件时自动切换）
    - multi_source: 多源检索（需要用户明确选择）

    注意：前端无需再单独调用 create_message 接口
    """

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

    # 自动检测模式：如果有附件且不是多源检索，则使用附件模式
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
        user_message = await crud_message.create_message(
            db,
            message_schema=user_message_schema,
            user_id=current_user.id
        )

    # 检查是否需要自动重命名（标题是"新对话"）
    is_first_conversation = False
    # 如果标题是"新对话"
    if conversation.title == "新对话":
        is_first_conversation = True

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
                        user_attachments=request.attachments
                ):
                    yield f"data: {json.dumps(output, ensure_ascii=False)}\n\n"

            elif actual_mode == "attachment":
                # === 模式2: 附件问答 ===
                if not request.attachments:
                    yield f"data: {json.dumps({'type': 'error', 'content': '未提供附件'}, ensure_ascii=False)}\n\n"
                    return

                # 根据附件类型选择处理方式
                image_attachments = [att for att in request.attachments
                                     if att.get('mime_type', '').startswith('image/')]
                pdf_attachments = [att for att in request.attachments
                                   if att.get('mime_type') == 'application/pdf']

                if image_attachments:
                    # 图片问答
                    for att in image_attachments:
                        async for chunk in llm_service.chat_with_image_stream(
                                text=request.content,
                                image_path=att.get('file_path', '')
                        ):
                            ai_content += chunk
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"

                elif pdf_attachments:
                    # PDF 问答
                    if len(pdf_attachments) == 1:
                        async for chunk in llm_service.chat_with_pdf_stream(
                                text=request.content,
                                pdf_path=pdf_attachments[0].get('file_path', '')
                        ):
                            ai_content += chunk
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
                    else:
                        pdf_paths = [att.get('file_path', '') for att in pdf_attachments]
                        async for chunk in llm_service.chat_with_multiple_pdfs_stream(
                                text=request.content,
                                pdf_paths=pdf_paths
                        ):
                            ai_content += chunk
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'content': '不支持的附件类型'}, ensure_ascii=False)}\n\n"
                    return

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
                # === 模式3: 普通问答 ===
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

                messages = []
                for msg in reversed(list(history_messages)):
                    messages.append({
                        "role": "user" if msg.message_type == MessageType.USER else "assistant",
                        "content": msg.content
                    })

                messages.append({"role": "user", "content": request.content})

                async for chunk in llm_service.chat_stream(messages=messages):
                    ai_content += chunk
                    yield f"data: {json.dumps({'type': 'result', 'content': chunk}, ensure_ascii=False)}\n\n"

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
            if is_first_conversation and ai_content:
                try:
                    # 1. 先判断是否应该生成标题（过滤寒暄）
                    should_rename = await should_generate_title(request.content, ai_content)

                    if should_rename:
                        # 2. 生成标题
                        new_title = await generate_conversation_title(request.content, ai_content)

                        # 3. 更新数据库
                        async with get_db_session() as db:
                            await crud_conversation.update_conversation(
                                db,
                                conversation_id=request.conversation_id,
                                conversation_schema=ConversationUpdateSchema(title=new_title),
                                user_id=current_user.id
                            )

                        # 4. 通知前端更新标题
                        yield f"data: {json.dumps({{'type': 'title_updated', 'conversation_id': request.conversation_id, 'title': new_title}}, ensure_ascii=False)}\n\n"
                    else:
                        # 寒暄对话，保持"新对话"标题
                        print(f"检测到寒暄对话，保持标题为'新对话'")

                except Exception as e:
                    print(f"自动重命名失败: {e}")
                    # 重命名失败不影响主流程，静默处理

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
    # TODO: 实现停止机制
    return {"message": "已发送停止信号"}