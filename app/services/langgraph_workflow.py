import os
import json
from typing import TypedDict, AsyncGenerator, List, Dict, Optional
from langgraph.graph import StateGraph, END
from sqlalchemy import select, func

from app.core.config import settings
from app.db.database import get_db_session
from app.services.llm_service import llm_service
from app.services.search_service import search_service
from app.models import WorkflowExecution, Message, MessageType


class WorkflowState(TypedDict):
    """工作流状态"""
    conversation_id: int
    user_id: int
    user_query: str
    user_attachments: List[Dict]  # 用户上传的附件
    history_messages: List[Dict]  # 历史对话

    # 步骤1：特征提取
    patient_features: str

    # 步骤2：检索条件生成
    pubmed_query: str
    clinical_trial_keywords: str

    # 步骤3：检索结果
    papers: List[Dict]
    trials: List[Dict]

    # 步骤4：文献分析结果
    paper_analyses: List[Dict]

    # 步骤5：临床试验分析
    trial_analysis: str

    # 步骤6：最终报告
    final_answer: str

    # 流程控制
    current_step: str
    errors: List[str]


class MultiSourceWorkflow:
    """多源检索工作流 - 使用 LangGraph 编排"""

    def __init__(self):
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """构建工作流图"""
        workflow = StateGraph(WorkflowState)

        # 添加节点
        workflow.add_node("extract_features", self._extract_features)
        workflow.add_node("generate_queries", self._generate_queries)
        workflow.add_node("search", self._search)
        workflow.add_node("analyze_papers", self._analyze_papers)
        workflow.add_node("analyze_trials", self._analyze_trials)
        workflow.add_node("generate_final", self._generate_final)

        # 定义流程
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
            user_attachments: List[Dict] = None
    ) -> AsyncGenerator[Dict, None]:
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

        # 初始化状态
        state: WorkflowState = {
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
            async for chunk in self._execute_step(state, 'extract_features', self._extract_features):
                yield chunk

            async for chunk in self._execute_step(state, 'generate_queries', self._generate_queries):
                yield chunk

            async for chunk in self._execute_step(state, 'search', self._search):
                yield chunk

            async for chunk in self._execute_step(state, 'analyze_papers', self._analyze_papers):
                yield chunk

            async for chunk in self._execute_step(state, 'analyze_trials', self._analyze_trials):
                yield chunk

            async for chunk in self._execute_step(state, 'generate_final', self._generate_final):
                yield chunk

            # 保存最终结果
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

            yield {'type': 'error', 'step': state.get('current_step', 'unknown'), 'content': str(e)}

    async def _execute_step(
            self,
            state: WorkflowState,
            step_name: str,
            step_func
    ) -> AsyncGenerator[Dict, None]:
        """执行单个步骤"""
        state['current_step'] = step_name

        yield {
            'type': 'step_start',
            'step': step_name,
            'content': f'\n\n## 步骤：{self._get_step_title(step_name)}\n\n'
        }

        try:
            async for chunk in step_func(state):
                yield chunk

            yield {
                'type': 'step_complete',
                'step': step_name,
                'content': '\n\n---\n'
            }

        except Exception as e:
            state['errors'].append(f"{step_name}: {str(e)}")
            yield {
                'type': 'error',
                'step': step_name,
                'content': f'\n\n❌ 错误: {str(e)}\n\n'
            }

    def _get_step_title(self, step_name: str) -> str:
        """获取步骤标题"""
        titles = {
            'extract_features': '提取患者特征',
            'generate_queries': '生成检索条件',
            'search': '执行检索',
            'analyze_papers': '分析文献',
            'analyze_trials': '分析临床试验',
            'generate_final': '生成最终报告'
        }
        return titles.get(step_name, step_name)

    async def _extract_features(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤1: 提取患者特征"""

        # 构建上下文
        context_parts = []

        # 添加历史对话
        if state['history_messages']:
            context_parts.append("### 历史对话")
            for msg in state['history_messages'][-5:]:
                role = "用户" if msg['type'] == 'user' else "AI"
                context_parts.append(f"**{role}**: {msg['content']}")
            context_parts.append("")

        # 处理附件
        if state['user_attachments']:
            context_parts.append("### 用户上传的附件")
            for att in state['user_attachments']:
                context_parts.append(f"- {att['original_filename']} ({att.get('mime_type', 'unknown')})")
            context_parts.append("")

        context = "\n".join(context_parts)

        # 构建提示词
        prompt = f"""{context}

### 当前用户问题
{state['user_query']}

### 任务
请从以上信息中提取患者的关键特征，包括：

1. **主要疾病/诊断**: 明确患者的主要疾病名称
2. **病理类型和分期**: 如果提到，请列出详细的病理类型和TNM分期
3. **基因突变信息**: 列出所有提到的基因突变（如EGFR、ALK、ROS1等）
4. **既往治疗史**: 之前接受过的治疗方案
5. **当前状态和需求**: 患者目前的状态和想了解的内容

请以结构化、清晰的方式列出这些信息。如果某些信息未提及，请标注"未提及"。"""

        messages = [{"role": "user", "content": prompt}]

        # 如果有图片附件，使用视觉模型
        image_attachments = [att for att in state['user_attachments']
                             if att.get('mime_type', '').startswith('image/')]

        full_response = ""

        if image_attachments:
            # 使用 qwen3-vl-plus 处理图片
            for att in image_attachments:
                async for token in llm_service.chat_with_image_stream(
                        text=prompt,
                        image_path=att['file_path'],
                        history=state['history_messages']
                ):
                    full_response += token
                    yield {'type': 'token', 'step': 'extract_features', 'content': token}
        else:
            # 使用 qwen-max 处理文本
            async for token in llm_service.chat_stream(messages=messages):
                full_response += token
                yield {'type': 'token', 'step': 'extract_features', 'content': token}

        state['patient_features'] = full_response

    async def _generate_queries(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤2: 生成检索条件"""

        prompt = f"""基于以下患者特征，生成精确的检索条件：

### 患者特征
{state['patient_features']}

### 任务
请生成以下检索条件：

1. **PubMed 检索表达式**: 使用布尔运算符（AND、OR、NOT），构建精确的检索式，确保能检索到相关文献
2. **ClinicalTrials.gov 关键词**: 提取3-5个核心关键词，用逗号分隔

**输出格式（必须严格遵守JSON格式）**:
```json
{{
    "pubmed_query": "这里是PubMed检索表达式",
    "clinical_trial_keywords": "关键词1,关键词2,关键词3"
}}
```

只输出JSON，不要有其他内容。"""

        messages = [{"role": "user", "content": prompt}]

        full_response = ""
        async for token in llm_service.chat_stream(messages=messages):
            full_response += token
            yield {'type': 'token', 'step': 'generate_queries', 'content': token}

        # 解析 JSON
        try:
            start = full_response.find('{')
            end = full_response.rfind('}') + 1
            if start != -1 and end > start:
                queries = json.loads(full_response[start:end])
                state['pubmed_query'] = queries.get('pubmed_query', '')
                state['clinical_trial_keywords'] = queries.get('clinical_trial_keywords', '')
            else:
                raise ValueError("未找到有效的JSON")
        except Exception as e:
            error_msg = f"\n\n⚠️ 检索条件解析失败: {str(e)}，使用默认条件\n\n"
            yield {'type': 'token', 'step': 'generate_queries', 'content': error_msg}
            state['errors'].append(f"解析检索条件失败: {str(e)}")
            # 使用默认条件
            state['pubmed_query'] = state['user_query']
            state['clinical_trial_keywords'] = state['user_query']

    async def _search(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤3: 执行检索（调用检索工具）"""

        # 检索 PubMed
        yield {
            'type': 'token',
            'step': 'search',
            'content': f"🔍 正在检索 PubMed: `{state['pubmed_query']}`\n\n"
        }

        papers = await search_service.search_pubmed(state['pubmed_query'])
        state['papers'] = papers[:settings.max_search_results]

        yield {
            'type': 'token',
            'step': 'search',
            'content': f"✅ 检索到 **{len(state['papers'])}** 篇相关文献\n\n"
        }

        # 检索临床试验
        yield {
            'type': 'token',
            'step': 'search',
            'content': f"🔍 正在检索临床试验: `{state['clinical_trial_keywords']}`\n\n"
        }

        trials = await search_service.search_clinical_trials(state['clinical_trial_keywords'])
        state['trials'] = trials[:settings.max_search_results]

        yield {
            'type': 'token',
            'step': 'search',
            'content': f"✅ 检索到 **{len(state['trials'])}** 个临床试验\n\n"
        }

    async def _analyze_papers(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤4: 逐个分析 PDF（使用 qwen-long，让模型直接读取PDF）"""

        if not state['papers']:
            yield {
                'type': 'token',
                'step': 'analyze_papers',
                'content': "ℹ️ 未检索到相关文献\n\n"
            }
            return

        for i, paper in enumerate(state['papers']):
            yield {
                'type': 'token',
                'step': 'analyze_papers',
                'content': f"\n### 📄 文献 {i+1}/{len(state['papers'])}: {paper['title']}\n\n"
            }

            # 检查 PDF 是否存在
            pdf_path = paper.get('pdf_path')
            if not pdf_path or not os.path.exists(pdf_path):
                yield {
                    'type': 'token',
                    'step': 'analyze_papers',
                    'content': "⚠️ PDF文件不存在，跳过该文献\n\n"
                }
                continue

            # 构建分析提示词
            prompt = f"""请仔细阅读这篇PDF文献，并基于以下信息进行深入分析：

### 患者特征
{state['patient_features']}

### 用户问题
{state['user_query']}

### 文献基本信息
- **标题**: {paper['title']}
- **作者**: {paper.get('authors', 'N/A')}
- **发表日期**: {paper.get('pub_date', 'N/A')}

### 分析任务
请完成以下分析（基于PDF全文）：

1. **文献核心内容概述**: 简要说明文献的主要研究内容
2. **与患者情况的相关性**: 分析该文献与患者情况的相关程度
3. **主要发现和结论**: 列出文献的关键发现
4. **证据等级评估**: 评估该研究的证据级别（如RCT、回顾性研究等）
5. **对患者的临床意义**: 说明该文献对患者的实际指导意义

请使用结构化格式输出，便于阅读。"""

            # 使用 qwen-long 直接读取 PDF
            analysis = ""
            try:
                async for token in llm_service.chat_with_pdf_stream(
                        text=prompt,
                        pdf_path=pdf_path,
                        history=[]
                ):
                    analysis += token
                    yield {'type': 'token', 'step': 'analyze_papers', 'content': token}
            except Exception as e:
                error_msg = f"\n\n⚠️ 分析失败: {str(e)}\n\n"
                yield {'type': 'token', 'step': 'analyze_papers', 'content': error_msg}
                continue

            state['paper_analyses'].append({
                'paper': paper,
                'analysis': analysis
            })

            yield {'type': 'token', 'step': 'analyze_papers', 'content': '\n\n---\n\n'}

    async def _analyze_trials(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤5: 分析临床试验"""

        if not state['trials']:
            yield {
                'type': 'token',
                'step': 'analyze_trials',
                'content': "ℹ️ 未检索到相关临床试验\n\n"
            }
            return

        # 格式化临床试验信息
        trials_text = []
        for i, trial in enumerate(state['trials']):
            trial_info = f"""### 试验 {i+1}
- **NCT ID**: {trial.get('nct_id', 'N/A')}
- **标题**: {trial.get('title', 'N/A')}
- **状态**: {trial.get('status', 'N/A')}
- **阶段**: {trial.get('phase', 'N/A')}
- **研究类型**: {trial.get('study_type', 'N/A')}
- **疾病/条件**: {trial.get('conditions', 'N/A')}
- **赞助方**: {trial.get('sponsor', 'N/A')}
- **地点**: {trial.get('locations', 'N/A')}
"""
            trials_text.append(trial_info)

        prompt = f"""基于患者特征评估以下临床试验的适配性：

### 患者特征
{state['patient_features']}

### 临床试验列表
{chr(10).join(trials_text)}

### 分析任务
请针对每个试验进行评估：

1. **适配度评分** (0-100分): 评估该试验与患者的匹配程度
2. **入组标准分析**: 分析患者是否符合入组条件
3. **排除标准考量**: 评估是否存在排除因素
4. **试验优势**: 说明该试验的优势和特点
5. **潜在风险**: 提示可能的风险
6. **推荐等级**: 给出推荐级别（强烈推荐/推荐/谨慎推荐/不推荐）

最后给出**综合建议**，说明最适合的1-2个试验。"""

        messages = [{"role": "user", "content": prompt}]

        analysis = ""
        async for token in llm_service.chat_stream(
                messages=messages,
                model=settings.qwen_long_model
        ):
            analysis += token
            yield {'type': 'token', 'step': 'analyze_trials', 'content': token}

        state['trial_analysis'] = analysis

    async def _generate_final(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤6: 生成最终报告"""

        # 汇总文献分析
        papers_summary = []
        for i, item in enumerate(state['paper_analyses']):
            summary = f"""### 文献 {i+1}: {item['paper']['title']}

{item['analysis'][:500]}...

[查看完整分析请参考上文]
"""
            papers_summary.append(summary)

        prompt = f"""请基于所有分析生成一份结构化的最终报告：

### 原始问题
{state['user_query']}

### 患者特征摘要
{state['patient_features'][:500]}...

### 文献分析汇总
{chr(10).join(papers_summary)}

### 临床试验分析摘要
{state['trial_analysis'][:500]}...

### 报告要求
请生成一份专业的医疗咨询报告，包含：

1. **执行摘要**: 简要总结本次分析的核心内容
2. **治疗方案建议**: 基于文献分析，提供治疗方案建议
3. **临床试验推荐**: 推荐最适合的1-2个临床试验
4. **注意事项**: 提示需要注意的风险和问题
5. **后续行动建议**: 给出具体的下一步建议

请保持专业、客观，使用易懂的语言。"""

        messages = [{"role": "user", "content": prompt}]

        final_answer = ""
        async for token in llm_service.chat_stream(messages=messages):
            final_answer += token
            yield {'type': 'token', 'step': 'generate_final', 'content': token}

        state['final_answer'] = final_answer

    async def _load_history(self, conversation_id: int) -> List[Dict]:
        """加载历史对话"""
        async with get_db_session() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(10)
            )
            messages = result.scalars().all()

            return [
                {
                    'type': 'user' if m.message_type == MessageType.USER else 'assistant',
                    'content': m.content
                }
                for m in reversed(list(messages))
            ]

    async def _save_final_result(self, state: WorkflowState, execution_id: int):
        """保存最终结果到数据库"""
        async with get_db_session() as db:
            # 拼接完整的 AI 回答
            full_content = f"""# 多源检索分析报告

## 1. 患者特征分析
{state['patient_features']}

## 2. 检索条件
- **PubMed**: {state['pubmed_query']}
- **临床试验**: {state['clinical_trial_keywords']}

## 3. 检索结果
- **文献数量**: {len(state['papers'])}
- **临床试验数量**: {len(state['trials'])}

## 4. 文献分析
"""

            # 添加每篇文献的分析
            for i, item in enumerate(state['paper_analyses']):
                full_content += f"\n### 文献 {i+1}: {item['paper']['title']}\n\n"
                full_content += f"{item['analysis']}\n\n---\n\n"

            # 添加临床试验分析
            full_content += f"\n## 5. 临床试验分析\n\n{state['trial_analysis']}\n\n"

            # 添加最终报告
            full_content += f"\n## 6. 最终报告\n\n{state['final_answer']}\n"

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


# 全局实例
streaming_workflow = MultiSourceWorkflow()