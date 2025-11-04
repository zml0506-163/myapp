from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
import json
import asyncio

from app.db.database import get_db_session
from app.models import User
from app.api.deps import get_current_active_user
from app.schemas.chat import ChatRequestSchema, ChatMode
from app.services.llm_service import llm_service
from app.services.workflow_service_v2 import workflow_service_v2
from app.crud import message as crud_message, conversation as crud_conversation
from app.schemas.message import MessageCreateSchema
from app.models import MessageType

router = APIRouter()

@router.post("/chat/stream")
async def chat_stream_endpoint(
        request: ChatRequestSchema,
        current_user: User = Depends(get_current_active_user)
):
    """
    智能聊天流式接口 - V2

    输出格式优化:
    - type='log': 过程日志（前端可折叠）
    - type='result': 步骤结果（前端显示）
    - type='section_start': 区块开始
    - type='section_end': 区块结束
    - type='done': 完成
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

    # 保存用户消息
    async with get_db_session() as db:
        user_message_schema = MessageCreateSchema(
            conversation_id=request.conversation_id,
            content=request.content,
            message_type=MessageType.USER,
            attachments=[
                {
                    'filename': att['filename'],
                    'original_filename': att['original_filename'],
                    'file_size': att['file_size'],
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

            if request.mode == ChatMode.MULTI_SOURCE:
                # === 模式1: 多源检索工作流（使用新版本）===
                async for output in workflow_service_v2.execute_with_streaming(
                        conversation_id=request.conversation_id,
                        user_id=current_user.id,
                        user_query=request.content,
                        user_attachments=request.attachments
                ):
                    # 直接转发输出
                    yield f"data: {json.dumps(output, ensure_ascii=False)}\n\n"

                # 工作流已自动保存结果，不需要额外保存

            elif request.mode == ChatMode.WITH_ATTACHMENT:
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
                    # 图片问答 - 使用 qwen3-vl-plus
                    for att in image_attachments:
                        async for chunk in llm_service.chat_with_image_stream(
                                text=request.content,
                                image_path=att['file_path']
                        ):
                            ai_content += chunk
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"

                elif pdf_attachments:
                    # PDF 问答 - 使用 qwen-long
                    if len(pdf_attachments) == 1:
                        # 单个 PDF
                        async for chunk in llm_service.chat_with_pdf_stream(
                                text=request.content,
                                pdf_path=pdf_attachments[0]['file_path']
                        ):
                            ai_content += chunk
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
                    else:
                        # 多个 PDF
                        pdf_paths = [att['file_path'] for att in pdf_attachments]
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

            elif request.mode == ChatMode.NORMAL:
                # === 模式3: 普通问答 ===

                # 加载历史对话（最近5条）
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

                # 构建消息列表
                messages = []
                for msg in reversed(list(history_messages)):
                    messages.append({
                        "role": "user" if msg.message_type == MessageType.USER else "assistant",
                        "content": msg.content
                    })

                # 添加当前问题
                messages.append({"role": "user", "content": request.content})

                # 流式生成回答
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
            # 客户端断开连接
            if ai_content and request.mode != ChatMode.MULTI_SOURCE:
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