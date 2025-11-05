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
from app.services.workflow_service_v2 import workflow_service_v2
from app.crud import message as crud_message, conversation as crud_conversation
from app.schemas.message import MessageCreateSchema
from app.models import MessageType

router = APIRouter()


# 聊天请求模型
class ChatRequest(BaseModel):
    conversation_id: int
    content: str
    mode: str = "normal"  # "normal" | "attachment" | "multi_source"
    attachments: List[Dict[str, Any]] = []


@router.post("/chat/stream")
async def chat_stream(
        request: ChatRequest,
        current_user: User = Depends(get_current_active_user)
):
    """
    智能聊天流式接口
    
    模式说明：
    - normal: 普通问答
    - attachment: 附件问答（有附件时自动切换）
    - multi_source: 多源检索（需要用户明确选择）
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

    async def event_generator():
        """生成 SSE 事件流"""
        try:
            ai_content = ""

            if actual_mode == "multi_source":
                # === 模式1: 多源检索工作流 ===
                async for output in workflow_service_v2.execute_with_streaming(
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