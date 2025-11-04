from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
import json
import asyncio

from app.db.database import get_db_session
from app.models import User
from app.api.deps import get_current_active_user
from app.schemas.chat import ChatRequestSchema, ChatMode
from app.services.llm_service import llm_service
from app.services.langgraph_workflow import streaming_workflow
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
    智能聊天流式接口
    注意：不使用 Depends(get_db)，改为按需获取连接
    """

    # 验证对话归属（独立会话）
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

    # 保存用户消息（独立会话）
    async with get_db_session() as db:
        user_message_schema = MessageCreateSchema(
            conversation_id=request.conversation_id,
            content=request.content,
            message_type=MessageType.USER,
            attachments=[]
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
            interrupted = False  # 用户是否中断

            if request.mode == ChatMode.MULTI_SOURCE:
                # 多源检索工作流（真正的流式）
                async for output in streaming_workflow.execute_with_streaming(
                        conversation_id=request.conversation_id,
                        user_id=current_user.id,
                        user_query=request.content,
                        user_attachments=request.attachments
                ):
                    # 检查客户端是否断开
                    # TODO: 实现断开检测机制

                    if output['type'] == 'token':
                        ai_content += output['content']

                    # 发送给前端
                    yield f"data: {json.dumps(output, ensure_ascii=False)}\n\n"

                # 工作流已自动保存结果，这里不需要再保存

            elif request.mode == ChatMode.NORMAL:
                # 普通问答（流式）
                async for chunk in llm_service.chat_stream(
                        messages=[{"role": "user", "content": request.content}]
                ):
                    ai_content += chunk
                    yield f"data: {json.dumps({'type': 'token', 'step': 'chat', 'content': chunk}, ensure_ascii=False)}\n\n"

                # 保存 AI 消息（独立会话）
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

            elif request.mode == ChatMode.WITH_ATTACHMENT:
                # 附件问答
                if not request.attachments:
                    yield f"data: {json.dumps({'type': 'error', 'content': '未提供附件'}, ensure_ascii=False)}\n\n"
                    return

                attachment = request.attachments[0]
                mime_type = attachment.get('mime_type', '')

                if mime_type.startswith('image/'):
                    # 图片问答（流式）
                    async for chunk in llm_service.chat_with_image_stream(
                            text=request.content,
                            image_path=attachment['file_path']
                    ):
                        ai_content += chunk
                        yield f"data: {json.dumps({'type': 'token', 'step': 'image_chat', 'content': chunk}, ensure_ascii=False)}\n\n"

                elif mime_type == 'application/pdf':
                    # PDF 问答（流式）
                    from app.services.pdf_service import pdf_service
                    pdf_text = pdf_service.extract_text(attachment['file_path'])

                    async for chunk in llm_service.chat_with_documents_stream(
                            text=request.content,
                            document_content=pdf_text
                    ):
                        ai_content += chunk
                        yield f"data: {json.dumps({'type': 'token', 'step': 'pdf_chat', 'content': chunk}, ensure_ascii=False)}\n\n"

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
            # 如果有部分内容，保存到数据库
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
            yield f"data: {json.dumps({'type': 'error', 'content': f'{str(e)}\n{error_detail}'}, ensure_ascii=False)}\n\n"

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
    """停止当前的聊天生成（前端调用此接口）"""
    # TODO: 实现停止机制
    # 可以使用 Redis 存储运行中的任务，前端调用此接口时设置停止标志
    return {"message": "已发送停止信号"}