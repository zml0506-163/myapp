"""
流式服务 - 处理后台生成任务和SSE推送
app/services/stream_service.py
"""
import json
import asyncio
from typing import AsyncGenerator, List, Dict, Any
from app.models import MessageType, MessageStatus
from app.db.database import get_db_session
from app.crud import message as crud_message
from app.utils.cache_helper import set_cache, get_cache, delete_cache
from app.utils.message_helper import reconstruct_content_from_events
from app.core.logger import get_logger
from app.services.llm_service import llm_service
from app.services.workflow_service import workflow_service
from app.services.file_service import file_service
from app.services.smart_qa_service import smart_qa_service

logger = get_logger(__name__)


async def background_generate_task(
    message_id: int,
    conversation_id: int,
    user_id: int,
    user_query: str,
    mode: str,
    attachments: List[Dict],
    is_first_conversation: bool = False
):
    """后台生成任务 - 独立运行，不受SSE断开影响"""
    
    cache_key = f"message:{message_id}"
    events = []  # 存储所有事件
    
    try:
        # 设置初始状态
        await set_cache(f"{cache_key}:status", "generating")
        await set_cache(f"{cache_key}:events", json.dumps([], ensure_ascii=False))
        
        logger.info(f"开始生成消息 {message_id}, 模式: {mode}")
        
        if mode == "multi_source":
            # 多源检索工作流
            async for output in workflow_service.execute_with_streaming(
                conversation_id=conversation_id,
                user_id=user_id,
                user_query=user_query,
                message_id=message_id,  # 传递 message_id
                user_attachments=attachments,
                is_first_conversation=is_first_conversation
            ):
                events.append(output)
                # 实时更新缓存
                await set_cache(
                    f"{cache_key}:events",
                    json.dumps(events, ensure_ascii=False)
                )
        
        elif mode == "smart_qa":
            # 智能问答模式（基于历史上下文）
            async with get_db_session() as db:
                history_messages = await crud_message.get_messages_by_conversation(
                    db,
                    conversation_id=conversation_id,
                    user_id=user_id
                ) or []
            
            # 基于历史上下文回答
            answer = await smart_qa_service.answer_with_history_context(
                user_query=user_query,
                conversation_id=conversation_id,
                history_messages=history_messages
            )
            
            # 流式输出回答
            for char in answer:
                events.append({
                    'type': 'token',
                    'content': char
                })
                await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
                await asyncio.sleep(0.01)  # 控制输出速度
        
        elif mode == "attachment":
            # 附件模式
            if not attachments:
                raise ValueError("附件模式但未提供附件")
            
            # 处理附件事件
            events.append({
                'type': 'log',
                'content': '📎 正在处理附件，上传到阿里平台...\n',
                'source': 'attachment',
                'newline': True
            })
            await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
            
            for idx, att in enumerate(attachments, 1):
                events.append({
                    'type': 'log',
                    'content': f'  [{idx}/{len(attachments)}] 正在上传: {att.get("original_filename", "未知文件")}...\n',
                    'source': 'attachment',
                    'newline': True
                })
                await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
            
            file_ids, only_images = await file_service.process_attachments(attachments)
            
            if not file_ids:
                raise ValueError("附件处理失败")
            
            events.append({
                'type': 'log',
                'content': '✅ 附件上传完成，开始分析...\n',
                'source': 'attachment',
                'newline': True
            })
            await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
            
            # 使用LLM分析
            full_response = ""
            
            if only_images and len(file_ids) == 1:
                # 单张图片用VL模型
                image_att = attachments[0]
                # 获取历史消息用于上下文
                async with get_db_session() as db:
                    history_messages = await crud_message.get_messages_by_conversation(
                        db,
                        conversation_id=conversation_id,
                        user_id=user_id
                    ) or []
                
                # 构建历史消息上下文，按照要求的格式处理附件
                history_context = []
                for msg in history_messages:
                    # 添加用户或助手消息
                    if msg["message_type"] == "user":
                        history_context.append({"role": "user", "content": msg["content"]})
                    elif msg["message_type"] == "assistant":
                        history_context.append({"role": "assistant", "content": msg["content"]})
                    
                    # 如果消息有附件，按照要求格式添加system消息
                    if msg.get("attachments"):
                        file_ids_context = []
                        for att in msg["attachments"]:
                            # 使用文件名作为fileid（实际应用中应该保存真实的file_id）
                            file_ids_context.append(f"fileid://{att['filename']}")
                        if file_ids_context:
                            history_context.append({"role": "system", "content": ",".join(file_ids_context)})
                
                async for token in llm_service.chat_with_image_stream(
                    text=user_query,
                    image_path=image_att['file_path'],
                    history=history_context if history_context else None
                ):
                    full_response += token
                    events.append({
                        'type': 'token',
                        'content': token
                    })
                    await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
            else:
                # 多个文件或包含文档
                # 获取历史消息用于上下文
                async with get_db_session() as db:
                    history_messages = await crud_message.get_messages_by_conversation(
                        db,
                        conversation_id=conversation_id,
                        user_id=user_id
                    ) or []
                
                # 构建历史消息上下文，按照要求的格式处理附件
                history_context = []
                for msg in history_messages:
                    # 添加用户或助手消息
                    if msg["message_type"] == "user":
                        history_context.append({"role": "user", "content": msg["content"]})
                    elif msg["message_type"] == "assistant":
                        history_context.append({"role": "assistant", "content": msg["content"]})
                    
                    # 如果消息有附件，按照要求格式添加system消息
                    if msg.get("attachments"):
                        file_ids_context = []
                        for att in msg["attachments"]:
                            # 使用文件名作为fileid（实际应用中应该保存真实的file_id）
                            file_ids_context.append(f"fileid://{att['filename']}")
                        if file_ids_context:
                            history_context.append({"role": "system", "content": ",".join(file_ids_context)})
                
                async for token in llm_service.chat_with_context(
                    user_query=user_query,
                    history=history_context if history_context else None,
                    file_ids=file_ids,
                    system_prompt="你是一个专业的文档分析助手。"
                ):
                    full_response += token
                    events.append({
                        'type': 'token',
                        'content': token
                    })
                    await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
        
        else:
            # 普通模式
            # 获取历史消息用于上下文
            async with get_db_session() as db:
                history_messages = await crud_message.get_messages_by_conversation(
                    db,
                    conversation_id=conversation_id,
                    user_id=user_id
                ) or []
            
            # 构建历史消息上下文，按照要求的格式处理附件
            history_context = []
            for msg in history_messages:
                # 添加用户或助手消息
                if msg["message_type"] == "user":
                    history_context.append({"role": "user", "content": msg["content"]})
                elif msg["message_type"] == "assistant":
                    history_context.append({"role": "assistant", "content": msg["content"]})
                
                # 如果消息有附件，按照要求格式添加system消息
                if msg.get("attachments"):
                    file_ids_context = []
                    for att in msg["attachments"]:
                        # 使用文件名作为fileid（实际应用中应该保存真实的file_id）
                        file_ids_context.append(f"fileid://{att['filename']}")
                    if file_ids_context:
                        history_context.append({"role": "system", "content": ",".join(file_ids_context)})
            
            async for token in llm_service.chat_with_context(
                user_query=user_query,
                history=history_context if history_context else None,
                system_prompt="你是一个专业的AI助手。"
            ):
                events.append({
                    'type': 'token',
                    'content': token
                })
                await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
        
        # 生成完成
        await set_cache(f"{cache_key}:status", "completed")
        
        # 多源检索模式已经在 workflow_service 中保存结果，不需要重复保存
        if mode != "multi_source":
            # 重建完整内容用于持久化
            final_content = reconstruct_content_from_events(events)
            
            # 保存到数据库
            async with get_db_session() as db:
                await crud_message.update_message(
                    db,
                    message_id=message_id,
                    content=final_content,
                    status=MessageStatus.COMPLETED
                )
                
                # 更新消息元数据（如果有的话）
                if events:
                    # 查找事件中的元数据
                    metadata_events = [event for event in events if event.get('type') == 'metadata']
                    if metadata_events:
                        # 合并所有元数据事件
                        metadata = {}
                        for event in metadata_events:
                            if isinstance(event.get('data'), dict):
                                metadata.update(event['data'])
                        
                        # 更新数据库中的元数据
                        from sqlalchemy import update
                        from app.models import Message
                        await db.execute(
                            update(Message)
                            .where(Message.id == message_id)
                            .values(metadata_json=json.dumps(metadata, ensure_ascii=False))
                        )
                        await db.commit()
                
                # 如果是新会话，尝试生成标题
                if is_first_conversation and final_content.strip():
                    # 获取用户消息内容用于生成标题
                    user_message = await crud_message.get_message_by_id(db, message_id-1)  # 假设用户消息ID是AI消息ID-1
                    if user_message and user_message.message_type == MessageType.USER:
                        user_query = user_message.content
                        ai_response = final_content
                        
                        # 判断是否应该生成标题
                        from app.api.v1.chat import should_generate_title, generate_conversation_title
                        if await should_generate_title(user_query, ai_response):
                            new_title = await generate_conversation_title(user_query, ai_response)
                            
                            # 更新会话标题
                            from app.schemas.conversation import ConversationUpdateSchema
                            from app.crud import conversation as crud_conversation
                            await crud_conversation.update_conversation(
                                db,
                                conversation_id=conversation_id,
                                conversation_schema=ConversationUpdateSchema(title=new_title),
                                user_id=user_id
                            )
                            
                            # 推送标题更新事件
                            events.append({
                                'type': 'title_updated',
                                'conversation_id': conversation_id,
                                'title': new_title
                            })
                            await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
                            logger.info(f"对话已自动重命名为「{new_title}」")
        
        logger.info(f"消息 {message_id} 生成完成")
        
        # 延迟清除缓存（给前端时间获取最终状态）
        await asyncio.sleep(10)
        await delete_cache(f"{cache_key}:status")
        await delete_cache(f"{cache_key}:events")
        
    except Exception as e:
        logger.error(f"消息 {message_id} 生成失败: {e}")
        await set_cache(f"{cache_key}:status", "failed")
        
        # 多源检索模式已经在 workflow_service 中保存错误结果，不需要重复更新
        if mode != "multi_source":
            # 更新数据库状态
            async with get_db_session() as db:
                await crud_message.update_message_status(
                    db,
                    message_id=message_id,
                    status=MessageStatus.FAILED
                )


async def stream_events(message_id: int) -> AsyncGenerator[str, None]:
    """统一的SSE事件流生成器（首次连接和断线重连共用）"""
    
    cache_key = f"message:{message_id}"
    last_sent_index = -1  # 已发送的事件索引
    
    while True:
        # 检查状态
        status = await get_cache(f"{cache_key}:status")
        
        if status == "failed":
            yield f"data: {json.dumps({'type': 'error', 'content': '生成失败'}, ensure_ascii=False)}\n\n"
            break
        
        if status == "completed":
            # 发送剩余事件后结束
            events_json = await get_cache(f"{cache_key}:events")
            if events_json:
                events = json.loads(events_json)
                for i in range(last_sent_index + 1, len(events)):
                    yield f"data: {json.dumps(events[i], ensure_ascii=False)}\n\n"
            
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            break
        
        # 获取事件数组
        events_json = await get_cache(f"{cache_key}:events")
        
        if not events_json:
            await asyncio.sleep(0.05)
            continue
        
        events = json.loads(events_json)
        
        # 推送新增的事件（增量）
        for i in range(last_sent_index + 1, len(events)):
            yield f"data: {json.dumps(events[i], ensure_ascii=False)}\n\n"
            last_sent_index = i
        
        await asyncio.sleep(0.05)  # 轮询间隔
