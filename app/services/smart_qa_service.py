"""
智能问答服务 - 优化连续问答体验
支持基于历史检索结果的快速问答
"""
import json
from typing import Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, MessageStatus
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
            # 构建判断提示词
            context = "\n".join([
                f"用户: {msg['content'][:200]}..." 
                for msg in history_messages[-3:]  # 最近3条对话
                if msg['message_type'] == 'user'
            ])
            
            prompt = f"""请判断用户的新问题是否需要重新检索医学文献：

历史对话上下文：
{context}

用户新问题：{user_query}

判断标准：
- 如果是基于已有文献的追问（如"详细说明"、"具体机制"等）→ 不需要重新检索
- 如果是新的疾病/症状咨询 → 需要重新检索
- 如果明确提到新的患者信息 → 需要重新检索

请回答"是"或"否"，不要有其他内容。
"""
            
            response = ""
            async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个专业的对话分析助手，判断是否需要重新检索文献。"
            ):
                response += token
            
            response = response.strip().lower()
            return '是' in response or 'yes' in response
            
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
                # 查找最近的多源检索消息
                result = await db.execute(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation_id,
                        Message.metadata_json.isnot(None)
                    )
                    .order_by(Message.created_at.desc())
                    .limit(10)  # 查看最近10条消息
                )
                messages = result.scalars().all()
                
                # 查找包含工作流元数据的消息
                for msg in messages:
                    try:
                        metadata = json.loads(msg.metadata_json or "{}")
                        if metadata.get("workflow_type") == "multi_source":
                            return metadata
                    except json.JSONDecodeError:
                        continue
                
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
                return "❌ 未找到历史检索信息，请重新进行多源检索。"
            
            # 构建上下文
            context_parts = []
            
            # 添加患者特征
            if metadata.get("patient_features"):
                context_parts.append(f"### 患者特征\n{metadata['patient_features']}")
            
            # 添加检索到的文献摘要
            papers = metadata.get("papers", [])
            if papers:
                paper_summaries = []
                for i, paper in enumerate(papers[:5]):  # 只取前5篇
                    paper_summaries.append(f"{i+1}. {paper.get('title', '未知标题')}")
                context_parts.append(f"### 相关文献\n" + "\n".join(paper_summaries))
            
            # 添加临床试验信息
            trials = metadata.get("trials", [])
            if trials:
                trial_summaries = []
                for i, trial in enumerate(trials[:3]):  # 只取前3个
                    trial_summaries.append(f"{i+1}. {trial.get('title', '未知试验')}")
                context_parts.append(f"### 临床试验\n" + "\n".join(trial_summaries))
            
            # 添加附件信息
            attachments = metadata.get("attachments", [])
            if attachments:
                att_names = [att.get('original_filename', att.get('filename', '未知文件')) 
                            for att in attachments]
                context_parts.append(f"### 附件\n" + ", ".join(att_names))
            
            context = "\n\n".join(context_parts)
            
            # 构建回答提示词
            prompt = f"""基于以下医学信息回答用户问题：

{context}

用户问题：{user_query}

要求：
1. 基于提供的文献和信息回答
2. 如果信息不足，请明确说明
3. 保持专业、准确的回答风格
"""
            
            response = ""
            async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个专业的医疗咨询助手，基于提供的文献信息回答问题。"
            ):
                response += token
            
            return response
            
        except Exception as e:
            logger.error(f"基于历史上下文回答失败: {e}")
            return f"❌ 回答失败: {str(e)}"


# 全局实例
smart_qa_service = SmartQAService()