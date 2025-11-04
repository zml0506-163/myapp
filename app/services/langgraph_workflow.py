import os
from typing import TypedDict, AsyncGenerator
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.db.database import get_db_session
from app.services.search_service import search_service
from app.services.pdf_service import pdf_service
from app.models import WorkflowExecution, Message, MessageType, Attachment

class WorkflowState(TypedDict):
    """工作流状态"""
    conversation_id: int
    user_id: int
    user_query: str
    user_attachments: list  # 用户上传的附件
    history_messages: list  # 历史对话
    patient_features: str
    pubmed_query: str
    clinical_trial_keywords: str
    papers: list
    trials: list
    paper_analyses: list  # 每个 PDF 的分析结果
    trial_analysis: str
    final_answer: str
    current_step: str
    errors: list


class StreamingLangGraphWorkflow:
    """支持真正流式输出的工作流"""

    def __init__(self):
        self.llm_max = ChatOpenAI(
            model=settings.qwen_max_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            streaming=True,
            temperature=0.7,
        )

        self.llm_long = ChatOpenAI(
            model=settings.qwen_long_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            streaming=True,
            temperature=0.7,
        )

        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        workflow = StateGraph(WorkflowState)

        workflow.add_node("extract_features", self._extract_features)
        workflow.add_node("generate_queries", self._generate_queries)
        workflow.add_node("search", self._search)
        workflow.add_node("analyze_papers", self._analyze_papers)
        workflow.add_node("analyze_trials", self._analyze_trials)
        workflow.add_node("generate_final", self._generate_final)

        workflow.set_entry_point("extract_features")
        workflow.add_edge("extract_features", "generate_queries")
        workflow.add_edge("generate_queries", "search")
        workflow.add_edge("search", "analyze_papers")
        workflow.add_edge("analyze_papers", "analyze_trials")
        workflow.add_edge("analyze_trials", "generate_final")
        workflow.add_edge("generate_final", END)

        return workflow.compile()

    async def execute_with_streaming(
            self,
            conversation_id: int,
            user_id: int,
            user_query: str,
            user_attachments: list = None
    ) -> AsyncGenerator[dict, None]:
        """
        执行工作流并流式输出

        Yields:
            {
                'type': 'step_start' | 'token' | 'step_complete' | 'error' | 'done',
                'step': str,
                'content': str
            }
        """

        # 创建工作流执行记录
        execution_id = None
        async with get_db_session() as db:
            execution = WorkflowExecution(
                conversation_id=conversation_id,
                user_id=user_id,
                workflow_type='multi_source',
                status='running',
                current_step='initializing'
            )
            db.add(execution)
            await db.commit()
            execution_id = execution.id

        # 加载历史对话
        history_messages = await self._load_history(conversation_id)

        # 初始状态
        state = {
            'conversation_id': conversation_id,
            'user_id': user_id,
            'user_query': user_query,
            'user_attachments': user_attachments or [],
            'history_messages': history_messages,
            'patient_features': '',
            'pubmed_query': '',
            'clinical_trial_keywords': '',
            'papers': [],
            'trials': [],
            'paper_analyses': [],
            'trial_analysis': '',
            'final_answer': '',
            'current_step': '',
            'errors': []
        }

        try:
            # 执行各个步骤
            async for chunk in self._execute_step_with_streaming(
                    state, 'extract_features', self._extract_features
            ):
                yield chunk

            async for chunk in self._execute_step_with_streaming(
                    state, 'generate_queries', self._generate_queries
            ):
                yield chunk

            async for chunk in self._execute_step_with_streaming(
                    state, 'search', self._search
            ):
                yield chunk

            async for chunk in self._execute_step_with_streaming(
                    state, 'analyze_papers', self._analyze_papers
            ):
                yield chunk

            async for chunk in self._execute_step_with_streaming(
                    state, 'analyze_trials', self._analyze_trials
            ):
                yield chunk

            async for chunk in self._execute_step_with_streaming(
                    state, 'generate_final', self._generate_final
            ):
                yield chunk

            # 保存最终结果到数据库
            await self._save_final_result(state, execution_id)

            # 更新执行记录
            async with get_db_session() as db:
                execution = await db.get(WorkflowExecution, execution_id)
                execution.status = 'completed'
                execution.completed_at = func.now()
                await db.commit()

            yield {'type': 'done', 'step': 'workflow', 'content': ''}

        except Exception as e:
            # 记录错误
            async with get_db_session() as db:
                execution = await db.get(WorkflowExecution, execution_id)
                execution.status = 'failed'
                execution.error_message = str(e)
                await db.commit()

            yield {'type': 'error', 'step': state['current_step'], 'content': str(e)}

    async def _execute_step_with_streaming(
            self,
            state: dict,
            step_name: str,
            step_func
    ) -> AsyncGenerator[dict, None]:
        """执行单个步骤并流式输出"""
        state['current_step'] = step_name

        yield {
            'type': 'step_start',
            'step': step_name,
            'content': f'开始执行: {step_name}'
        }

        try:
            # 调用步骤函数（已经是流式的）
            async for chunk in step_func(state):
                yield chunk

            yield {
                'type': 'step_complete',
                'step': step_name,
                'content': f'完成: {step_name}'
            }

        except Exception as e:
            state['errors'].append(f"{step_name}: {str(e)}")
            yield {
                'type': 'error',
                'step': step_name,
                'content': f'错误: {str(e)}'
            }

    async def _extract_features(self, state: dict) -> AsyncGenerator[dict, None]:
        """步骤1: 提取患者特征（流式）"""

        # 构建上下文
        context = ""
        if state['history_messages']:
            context = "历史对话:\n" + "\n".join([
                f"{'用户' if m['type'] == 'user' else 'AI'}: {m['content']}"
                for m in state['history_messages'][-5:]  # 最近5条
            ]) + "\n\n"

        # 如果有附件，先分析附件
        if state['user_attachments']:
            context += "用户上传的附件:\n"
            for att in state['user_attachments']:
                if att.get('mime_type', '').startswith('image/'):
                    context += f"- 图片: {att['original_filename']}\n"
                elif att.get('file_path', '').endswith('.pdf'):
                    # 解析 PDF
                    pdf_text = pdf_service.extract_text(att['file_path'], max_length=10000)
                    context += f"- PDF文档: {att['original_filename']}\n内容摘要: {pdf_text[:500]}...\n\n"

        prompt = f"""{context}

当前用户问题：{state['user_query']}

请从以上信息中提取患者的关键特征，包括：
1. 主要疾病/诊断
2. 病理类型和分期
3. 基因突变信息
4. 既往治疗史
5. 当前状态和需求

请以结构化、清晰的方式列出。"""

        messages = [HumanMessage(content=prompt)]

        full_response = ""
        async for chunk in self.llm_max.astream(messages):
            content = chunk.content
            full_response += content
            yield {
                'type': 'token',
                'step': 'extract_features',
                'content': content
            }

        state['patient_features'] = full_response

    async def _generate_queries(self, state: dict) -> AsyncGenerator[dict, None]:
        """步骤2: 生成检索条件（流式）"""

        prompt = f"""基于以下患者特征，生成精确的检索条件：

{state['patient_features']}

请生成：
1. PubMed 检索表达式（使用布尔运算符，尽可能精确）
2. ClinicalTrials.gov 关键词（3-5个核心词，逗号分隔）

严格按照 JSON 格式输出：
{{
    "pubmed_query": "...",
    "clinical_trial_keywords": "..."
}}"""

        messages = [HumanMessage(content=prompt)]

        full_response = ""
        async for chunk in self.llm_max.astream(messages):
            content = chunk.content
            full_response += content
            yield {
                'type': 'token',
                'step': 'generate_queries',
                'content': content
            }

        # 解析 JSON
        try:
            start = full_response.find('{')
            end = full_response.rfind('}') + 1
            if start != -1 and end > start:
                queries = json.loads(full_response[start:end])
                state['pubmed_query'] = queries.get('pubmed_query', '')
                state['clinical_trial_keywords'] = queries.get('clinical_trial_keywords', '')
        except Exception as e:
            state['errors'].append(f"解析检索条件失败: {str(e)}")
            state['pubmed_query'] = "EGFR mutation AND lung cancer"
            state['clinical_trial_keywords'] = "EGFR,lung cancer"

    async def _search(self, state: dict) -> AsyncGenerator[dict, None]:
        """步骤3: 执行检索（带缓存）"""

        yield {
            'type': 'token',
            'step': 'search',
            'content': f"\n\n正在检索 PubMed: {state['pubmed_query']}\n"
        }

        # 检索 PubMed（带缓存）
        papers = await search_service.search_pubmed(state['pubmed_query'])
        state['papers'] = papers[:5]  # 取前5篇

        yield {
            'type': 'token',
            'step': 'search',
            'content': f"检索到 {len(state['papers'])} 篇相关文献\n\n"
        }

        yield {
            'type': 'token',
            'step': 'search',
            'content': f"正在检索临床试验: {state['clinical_trial_keywords']}\n"
        }

        # 检索临床试验（带缓存）
        trials = await search_service.search_clinical_trials(state['clinical_trial_keywords'])
        state['trials'] = trials[:5]

        yield {
            'type': 'token',
            'step': 'search',
            'content': f"检索到 {len(state['trials'])} 个临床试验\n\n"
        }

    async def _analyze_papers(self, state: dict) -> AsyncGenerator[dict, None]:
        """步骤4: 逐个分析 PDF（流式）"""

        if not state['papers']:
            yield {
                'type': 'token',
                'step': 'analyze_papers',
                'content': "未检索到相关文献\n"
            }
            return

        for i, paper in enumerate(state['papers']):
            yield {
                'type': 'token',
                'step': 'analyze_papers',
                'content': f"\n\n### 分析文献 {i+1}/{len(state['papers'])}: {paper['title']}\n\n"
            }

            # 解析 PDF 全文
            pdf_text = ""
            if paper.get('pdf_path') and os.path.exists(paper['pdf_path']):
                pdf_text = pdf_service.extract_text(paper['pdf_path'], max_length=30000)

            prompt = f"""基于患者特征和文献内容，请进行深入分析：

## 患者特征
{state['patient_features']}

## 用户问题
{state['user_query']}

## 文献信息
标题: {paper['title']}
作者: {paper.get('authors', 'N/A')}
发表日期: {paper.get('pub_date', 'N/A')}

摘要:
{paper.get('abstract', 'N/A')}

全文内容:
{pdf_text[:20000] if pdf_text else '(PDF 未找到或解析失败)'}

请完成：
1. 文献核心内容概述
2. 与患者情况的相关性分析
3. 主要发现和结论
4. 证据等级评估
5. 对患者的临床意义"""

            messages = [HumanMessage(content=prompt)]

            analysis = ""
            async for chunk in self.llm_long.astream(messages):
                content = chunk.content
                analysis += content
                yield {
                    'type': 'token',
                    'step': 'analyze_papers',
                    'content': content
                }

            state['paper_analyses'].append({
                'paper': paper,
                'analysis': analysis
            })

    async def _analyze_trials(self, state: dict) -> AsyncGenerator[dict, None]:
        """步骤5: 分析临床试验（流式）"""

        if not state['trials']:
            yield {
                'type': 'token',
                'step': 'analyze_trials',
                'content': "\n\n未检索到相关临床试验\n"
            }
            return

        trials_text = "\n\n".join([
            f"### 试验 {i+1}\n"
            f"NCT ID: {t.get('nct_id', 'N/A')}\n"
            f"标题: {t.get('title', 'N/A')}\n"
            f"状态: {t.get('status', 'N/A')}\n"
            f"阶段: {t.get('phase', 'N/A')}\n"
            f"疾病: {t.get('conditions', 'N/A')}"
            for i, t in enumerate(state['trials'])
        ])

        prompt = f"""基于患者特征评估临床试验适配性：

## 患者特征
{state['patient_features']}

## 临床试验
{trials_text}

请针对每个试验评估：
1. 适配度评分 (0-100分)
2. 入组标准分析
3. 排除标准考量
4. 试验优势
5. 风险提示
6. 推荐等级

最后给出综合建议。"""

        messages = [HumanMessage(content=prompt)]

        analysis = ""
        async for chunk in self.llm_long.astream(messages):
            content = chunk.content
            analysis += content
            yield {
                'type': 'token',
                'step': 'analyze_trials',
                'content': content
            }

        state['trial_analysis'] = analysis

    async def _generate_final(self, state: dict) -> AsyncGenerator[dict, None]:
        """步骤6: 生成最终报告（流式）"""

        # 汇总所有分析
        papers_summary = "\n\n".join([
            f"文献{i+1}: {item['paper']['title']}\n{item['analysis'][:300]}..."
            for i, item in enumerate(state['paper_analyses'])
        ])

        prompt = f"""基于所有分析生成最终报告：

## 原始问题
{state['user_query']}

## 患者特征
{state['patient_features'][:500]}...

## 文献分析汇总
{papers_summary}

## 临床试验分析
{state['trial_analysis'][:500]}...

请生成结构化报告：
1. 执行摘要
2. 治疗方案建议
3. 临床试验推荐
4. 注意事项
5. 后续行动建议

请专业、客观、有针对性。"""

        messages = [HumanMessage(content=prompt)]

        final_answer = ""
        async for chunk in self.llm_max.astream(messages):
            content = chunk.content
            final_answer += content
            yield {
                'type': 'token',
                'step': 'generate_final',
                'content': content
            }

        state['final_answer'] = final_answer

    async def _load_history(self, conversation_id: int) -> list[dict]:
        """加载历史对话"""
        async with get_db_session() as db:
            messages = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(10)
            )
            messages = messages.scalars().all()

            return [
                {
                    'type': 'user' if m.message_type == MessageType.USER else 'assistant',
                    'content': m.content
                }
                for m in reversed(list(messages))
            ]

    async def _save_final_result(self, state: dict, execution_id: int):
        """保存最终结果到数据库"""
        async with get_db_session() as db:
            # 拼接完整的 AI 回答
            full_content = f"""# 多源检索分析报告

## 患者特征分析
{state['patient_features']}

## 检索条件
- PubMed: {state['pubmed_query']}
- 临床试验: {state['clinical_trial_keywords']}

## 检索结果
- 文献数量: {len(state['papers'])}
- 临床试验数量: {len(state['trials'])}

## 文献分析
"""

            # 添加每篇文献的分析
            for i, item in enumerate(state['paper_analyses']):
                full_content += f"\n### 文献 {i+1}: {item['paper']['title']}\n"
                full_content += f"{item['analysis']}\n\n"

            # 添加临床试验分析
            full_content += f"\n## 临床试验分析\n{state['trial_analysis']}\n\n"

            # 添加最终报告
            full_content += f"\n## 最终报告\n{state['final_answer']}\n"

            # 保存为消息
            from app.crud import message as crud_message
            from app.schemas.message import MessageCreateSchema

            message_schema = MessageCreateSchema(
                conversation_id=state['conversation_id'],
                content=full_content,
                message_type=MessageType.ASSISTANT,
                attachments=[]
            )

            saved_message = await crud_message.create_message(
                db,
                message_schema=message_schema,
                user_id=state['user_id']
            )

            # 更新执行记录
            execution = await db.get(WorkflowExecution, execution_id)
            execution.result_message_id = saved_message['id']
            execution.patient_features = state['patient_features']
            execution.search_queries = json.dumps({
                'pubmed': state['pubmed_query'],
                'clinical_trial': state['clinical_trial_keywords']
            })
            await db.commit()

streaming_workflow = StreamingLangGraphWorkflow()