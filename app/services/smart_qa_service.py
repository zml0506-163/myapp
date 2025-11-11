"""
智能问答服务 - 优化连续问答体验
支持基于历史检索结果的快速问答
"""
import json
from typing import Dict, List, Optional
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, MessageStatus, MessageType
from app.db.database import get_db_session
from app.services.llm_service import llm_service
from app.core.logger import get_logger

logger = get_logger(__name__)


class SmartQAService:
    """智能问答服务"""

    async def should_retrieve_new_papers(self, user_query: str, history_messages: List[Dict]) -> bool:
        """
        判断是否需要重新检索文献

        Args:
            user_query: 用户当前问题
            history_messages: 历史对话消息

        Returns:
            bool: True表示需要重新检索，False表示可以使用历史结果
        """
        try:
            # 如果历史消息少于2条，需要重新检索
            if len(history_messages) < 2:
                return True

            # 检查最近是否有多源检索的消息
            has_recent_multi_source = False
            for msg in history_messages[-5:]:  # 检查最近5条消息
                if msg.get('metadata'):
                    try:
                        metadata = json.loads(msg['metadata']) if isinstance(msg['metadata'], str) else msg['metadata']
                        if metadata.get('workflow_type') == 'multi_source':
                            has_recent_multi_source = True
                            break
                    except:
                        pass

            # 如果没有找到多源检索记录，需要重新检索
            if not has_recent_multi_source:
                logger.info("历史消息中未找到多源检索记录，需要重新检索")
                return True

            # 构建判断提示词
            context = "\n".join([
                f"{'用户' if msg['message_type'] == 'user' else 'AI'}: {msg['content'][:200]}..."
                for msg in history_messages[-4:]  # 最近4条对话
            ])

            prompt = f"""请判断用户的新问题是否需要重新检索医学文献：

历史对话上下文：
{context}

用户新问题：{user_query}

判断标准：
- 如果是针对已有信息的追问（如"详细解释"、"为什么"、"举例说明"、"具体机制"等）→ 回答"否"
- 如果是新的疾病/症状咨询（与之前话题不相关）→ 回答"是"
- 如果明确提到新的患者信息或病例 → 回答"是"
- 如果问题是对前面内容的延伸讨论 → 回答"否"

只回答"是"或"否"，不要有任何其他内容。
"""

            response = ""
            async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个专业的对话分析助手，判断是否需要重新检索文献。"
            ):
                response += token

            response = response.strip().lower()
            needs_search = '是' in response or 'yes' in response

            logger.info(f"判断结果: {'需要' if needs_search else '不需要'}重新检索")
            return needs_search

        except Exception as e:
            logger.warning(f"判断是否需要重新检索失败: {e}")
            # 默认需要重新检索（保守策略）
            return True

    async def get_history_metadata(self, conversation_id: int) -> Optional[Dict]:
        """
        获取对话中最近的多源检索元数据

        Args:
            conversation_id: 对话ID

        Returns:
            Dict: 元数据信息，如果没有找到则返回None
        """
        try:
            async with get_db_session() as db:
                # 查找最近的多源检索消息（只查AI消息）
                result = await db.execute(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation_id,
                        Message.message_type == MessageType.ASSISTANT,
                        Message.metadata_json.isnot(None)
                    )
                    .order_by(desc(Message.created_at))
                    .limit(10)  # 查看最近10条AI消息
                )
                messages = result.scalars().all()

                logger.debug(f"查找到 {len(messages)} 条带元数据的AI消息")

                # 查找包含工作流元数据的消息
                for msg in messages:
                    try:
                        metadata = json.loads(msg.metadata_json or "{}")
                        logger.debug(f"消息 {msg.id} 的元数据: {list(metadata.keys())}")

                        if metadata.get("workflow_type") == "multi_source":
                            logger.info(f"找到多源检索元数据: 消息ID {msg.id}")
                            return metadata
                    except json.JSONDecodeError as e:
                        logger.warning(f"解析消息 {msg.id} 的元数据失败: {e}")
                        continue

                logger.warning("未找到有效的多源检索元数据")
                return None
        except Exception as e:
            logger.error(f"获取历史元数据失败: {e}")
            return None

    async def answer_with_history_context(
        self,
        user_query: str,
        conversation_id: int,
        history_messages: List[Dict]
    ) -> str:
        """
        基于历史上下文回答问题（不重新检索）

        Args:
            user_query: 用户问题
            conversation_id: 对话ID
            history_messages: 历史对话

        Returns:
            str: 回答内容
        """
        try:
            # 获取历史元数据
            metadata = await self.get_history_metadata(conversation_id)
            if not metadata:
                logger.warning(f"对话 {conversation_id} 未找到历史检索信息")
                return "抱歉，我没有找到之前的检索信息。请重新提问或开启多源检索模式获取最新信息。"

            # 构建上下文
            context_parts = []

            # 添加患者特征
            if metadata.get("patient_features"):
                context_parts.append(f"### 患者特征\n{metadata['patient_features'][:500]}...")

            # 添加检索到的文献摘要
            papers = metadata.get("papers", [])
            if papers:
                paper_summaries = []
                for i, paper in enumerate(papers[:5]):  # 只取前5篇
                    paper_summaries.append(f"{i+1}. {paper.get('title', '未知标题')}")
                context_parts.append(f"### 相关文献（共{len(papers)}篇）\n" + "\n".join(paper_summaries))

            # 添加临床试验信息
            trials = metadata.get("trials", [])
            if trials:
                trial_summaries = []
                for i, trial in enumerate(trials[:3]):  # 只取前3个
                    trial_summaries.append(f"{i+1}. {trial.get('title', '未知试验')}")
                context_parts.append(f"### 临床试验（共{len(trials)}个）\n" + "\n".join(trial_summaries))

            # 添加附件信息
            attachments = metadata.get("attachments", [])
            if attachments:
                att_names = [att.get('original_filename', att.get('filename', '未知文件'))
                            for att in attachments]
                context_parts.append(f"### 附件\n" + ", ".join(att_names))

            context = "\n\n".join(context_parts)

            # 添加历史对话作为补充上下文
            recent_history = "\n".join([
                f"{'用户' if msg['message_type'] == 'user' else 'AI'}: {msg['content'][:300]}..."
                for msg in history_messages[-3:]  # 最近3条对话
            ])

            # 构建回答提示词
            prompt = f"""基于以下医学信息和历史对话回答用户问题：

{context}

历史对话：
{recent_history}

用户问题：{user_query}

要求：
1. 基于提供的文献、临床试验和历史对话信息回答
2. 如果信息不足以回答问题，请明确说明需要哪些额外信息
3. 保持专业、准确的回答风格
4. 如果问题是对之前内容的深入探讨，可以适当展开说明
"""

            response = ""
            async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个专业的医疗咨询助手，基于提供的文献信息和历史对话回答问题。"
            ):
                response += token

            return response

        except Exception as e:
            logger.error(f"基于历史上下文回答失败: {e}")
            return f"抱歉，回答时出现错误。请稍后重试或重新进行多源检索。"


# 全局实例
smart_qa_service = SmartQAService()