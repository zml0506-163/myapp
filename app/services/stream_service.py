"""
流式服务 - 处理后台生成任务和SSE推送
app/services/stream_service.py
"""
import json
import asyncio
from typing import AsyncGenerator, List, Dict, Any
from sqlalchemy import select, func
from app.models import MessageType, MessageStatus, Conversation
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


async def should_generate_title(user_query: str, ai_response: str) -> bool:
    """判断是否应该生成标题（独立函数，方便复用）"""
    # 基本长度检查
    if len(user_query.strip()) < 5 and len(ai_response.strip()) < 50:
        return False

    # 常见问候语过滤
    greetings = [
        '你好', 'hello', 'hi', '在吗', '在不在', '您好',
        '嗨', '喂', '早', '晚上好', '下午好', '上午好', '测试'
    ]

    user_lower = user_query.lower().strip()
    if any(greeting in user_lower for greeting in greetings) and len(user_query) < 20:
        return False

    # 使用LLM判断
    prompt = f"""请判断以下对话是否需要生成标题。

用户问题：{user_query}
AI回答：{ai_response[:300]}...

判断标准：
- 实质性对话（包含具体问题、需求、咨询）→ 回答"是"
- 简单问候、测试性提问 → 回答"否"

只回答"是"或"否"，不要有其他内容。
"""

    response = ""
    try:
        async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个对话分类助手，判断对话是否实质性。"
        ):
            response += token

        response = response.strip().lower()
        should_gen = '是' in response or 'yes' in response
        logger.info(f"是否生成标题判断: {'是' if should_gen else '否'} (用户问题长度: {len(user_query)}, AI回答长度: {len(ai_response)})")
        return should_gen

    except Exception as e:
        logger.warning(f"判断对话类型失败: {e}")
        # 默认根据长度判断
        return len(user_query) > 10


async def generate_conversation_title(user_query: str, ai_response: str) -> str:
    """根据对话内容生成标题（独立函数，方便复用）"""
    prompt = f"""请根据以下对话内容，生成一个简短的对话标题（不超过15个字）：

用户问题：{user_query}
AI回答：{ai_response[:500]}...

要求：
1. 简洁明了，概括核心主题
2. 不超过15个字
3. 不要使用引号、书名号等标点符号
4. 直接输出标题，不要有其他内容
5. 如果是医疗咨询，突出疾病/症状关键词
6. 如果是技术问题，突出技术栈关键词

标题："""

    title = ""
    try:
        async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个专业的标题生成助手，擅长用简短的语言概括主题。"
        ):
            title += token

        # 清理标题
        title = title.strip().replace('\n', '').replace('"', '').replace("'", '').replace('《', '').replace('》', '')

        if len(title) > 18:
            title = title[:18] + "..."

        if not title or len(title) < 2:
            title = "新对话"

        logger.info(f"生成的标题: {title}")
        return title

    except Exception as e:
        logger.error(f"生成标题失败: {e}")
        return "新对话"


async def auto_rename_conversation(
    conversation_id: int,
    user_id: int,
    user_query: str,
    ai_response: str,
    events: List[Dict]
) -> None:
    """
    自动重命名对话（独立函数）

    Args:
        conversation_id: 对话ID
        user_id: 用户ID
        user_query: 用户问题
        ai_response: AI回答
        events: 事件列表（用于推送更新）
    """
    try:
        # 检查是否是新对话
        async with get_db_session() as db:
            result = await db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()

            if not conversation:
                logger.warning(f"对话 {conversation_id} 不存在")
                return

            # 只对标题为"新对话"的会话进行自动重命名
            if conversation.title != "新对话":
                logger.info(f"对话 {conversation_id} 标题已修改，跳过自动重命名")
                return

        # 判断是否应该生成标题
        if not await should_generate_title(user_query, ai_response):
            logger.info("对话内容不适合生成标题，保持默认标题")
            return

        # 生成新标题
        new_title = await generate_conversation_title(user_query, ai_response)

        # 更新数据库
        async with get_db_session() as db:
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

        logger.info(f"对话 {conversation_id} 已自动重命名为「{new_title}」")

    except Exception as e:
        logger.error(f"自动重命名失败: {e}")


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

        logger.info(f"开始生成消息 {message_id}, 模式: {mode}, 是否新对话: {is_first_conversation}")

        full_response = ""  # 用于存储完整回答

        if mode == "multi_source":
            # 多源检索工作流
            logger.info(f"开始执行多源检索工作流，消息ID: {message_id}")
            async for output in workflow_service.execute_with_streaming(
                conversation_id=conversation_id,
                user_id=user_id,
                user_query=user_query,
                message_id=message_id,
                user_attachments=attachments,
                is_first_conversation=is_first_conversation
            ):
                events.append(output)
                # 收集最终报告内容（用于生成标题）
                if output.get('type') == 'token':
                    full_response += output.get('content', '')
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

            full_response = answer

            # 流式输出回答
            for char in answer:
                events.append({
                    'type': 'token',
                    'content': char
                })
                await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
                await asyncio.sleep(0.01)

        elif mode == "attachment":
            # 附件模式（逻辑保持不变...省略）
            # [这里是原来的附件处理代码]
            pass

        else:
            # 普通模式
            async with get_db_session() as db:
                history_messages = await crud_message.get_messages_by_conversation(
                    db,
                    conversation_id=conversation_id,
                    user_id=user_id
                ) or []

            # 构建历史消息上下文
            history_context = []
            for msg in history_messages:
                if msg["message_type"] == "user":
                    history_context.append({"role": "user", "content": msg["content"]})
                elif msg["message_type"] == "assistant":
                    history_context.append({"role": "assistant", "content": msg["content"]})

            async for token in llm_service.chat_with_context(
                user_query=user_query,
                history=history_context if history_context else None,
                system_prompt="你是一个专业的AI助手。"
            ):
                full_response += token
                events.append({
                    'type': 'token',
                    'content': token
                })
                await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))

        # 🔥 统一的自动重命名逻辑（所有模式都支持）
        # 对于多源检索模式，我们需要从工作流结果中提取完整响应
        if mode == "multi_source":
            # 从工作流结果中提取完整响应内容
            try:
                from app.models import Message
                async with get_db_session() as db:
                    result = await db.execute(
                        select(Message).where(Message.id == message_id)
                    )
                    message = result.scalar_one_or_none()
                    if message and message.content:
                        full_response = message.content
                        logger.info(f"从数据库获取多源检索完整内容，长度: {len(full_response)}")
            except Exception as e:
                logger.error(f"获取多源检索完整内容失败: {e}")
        
        # 在发送done事件之前执行自动重命名
        logger.info(f"准备执行自动重命名，是否新对话: {is_first_conversation}，响应内容长度: {len(full_response)}")
        if is_first_conversation and full_response.strip():
            await auto_rename_conversation(
                conversation_id=conversation_id,
                user_id=user_id,
                user_query=user_query,
                ai_response=full_response,
                events=events
            )
            # 更新缓存（包含标题更新事件）
            await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
            
            # 等待一小段时间确保缓存更新完成
            await asyncio.sleep(0.1)

        # 添加done事件到events列表中
        events.append({'type': 'done'})
        
        # 更新缓存（包含done事件）
        await set_cache(f"{cache_key}:events", json.dumps(events, ensure_ascii=False))
        await set_cache(f"{cache_key}:status", "completed")
        
        logger.info(f"消息 {message_id} 生成完成，模式: {mode}，是否新对话: {is_first_conversation}")

        # 保存到数据库（多源检索模式已在workflow_service中保存）
        if mode != "multi_source":
            final_content = reconstruct_content_from_events(events)

            async with get_db_session() as db:
                await crud_message.update_message(
                    db,
                    message_id=message_id,
                    content=final_content,
                    status=MessageStatus.COMPLETED
                )

        # 延迟清除缓存
        await asyncio.sleep(10)
        await delete_cache(f"{cache_key}:status")
        await delete_cache(f"{cache_key}:events")

    except Exception as e:
        logger.error(f"消息 {message_id} 生成失败: {e}")
        await set_cache(f"{cache_key}:status", "failed")

        if mode != "multi_source":
            async with get_db_session() as db:
                await crud_message.update_message_status(
                    db,
                    message_id=message_id,
                    status=MessageStatus.FAILED
                )


async def stream_events(message_id: int) -> AsyncGenerator[str, None]:
    """统一的SSE事件流生成器（首次连接和断线重连共用）"""

    cache_key = f"message:{message_id}"
    last_sent_index = -1

    while True:
        status = await get_cache(f"{cache_key}:status")

        if status == "failed":
            yield f"data: {json.dumps({'type': 'error', 'content': '生成失败'}, ensure_ascii=False)}\n\n"
            break

        if status == "completed":
            events_json = await get_cache(f"{cache_key}:events")
            if events_json:
                events = json.loads(events_json)
                for i in range(last_sent_index + 1, len(events)):
                    yield f"data: {json.dumps(events[i], ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            break

        events_json = await get_cache(f"{cache_key}:events")

        if not events_json:
            await asyncio.sleep(0.05)
            continue

        events = json.loads(events_json)

        for i in range(last_sent_index + 1, len(events)):
            yield f"data: {json.dumps(events[i], ensure_ascii=False)}\n\n"
            last_sent_index = i

        await asyncio.sleep(0.05)