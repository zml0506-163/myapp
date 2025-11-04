"""
多源检索工作流 - V2
输出格式优化：区分日志(log)和结果(result)
只有结果会保存到数据库
"""
import os
import json
from typing import TypedDict, AsyncGenerator, List, Dict
import asyncio
from sqlalchemy import select, func

from app.core.config import settings
from app.db.database import get_db_session
from app.services.llm_service import llm_service
from app.services.search_workflow_service import search_service
from app.models import WorkflowExecution, Message, MessageType
from app.crud import message as crud_message
from app.schemas.message import MessageCreateSchema


class WorkflowState(TypedDict):
    """工作流状态"""
    conversation_id: int
    user_id: int
    user_query: str
    user_attachments: List[Dict]
    history_messages: List[Dict]

    # 步骤结果（存储）
    patient_features: str
    pubmed_query: str
    clinical_trial_keywords: str
    papers: List[Dict]
    trials: List[Dict]
    paper_analyses: List[Dict]
    trial_analysis: str
    final_answer: str

    # 流程控制
    current_step: str
    errors: List[str]


class MultiSourceWorkflowV2:
    """多源检索工作流 V2 - 优化输出格式"""

    async def execute_with_streaming(
            self,
            conversation_id: int,
            user_id: int,
            user_query: str,
            user_attachments: List[Dict] = None
    ) -> AsyncGenerator[Dict, None]:
        """
        执行工作流并流式输出

        输出格式:
        - type='log': 过程日志，不保存
        - type='result': 步骤结果，保存到最终报告
        - type='section_start': 区块开始标记
        - type='section_end': 区块结束标记
        - type='done': 完成标记
        """

        # 创建执行记录
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
            # 步骤1: 提取患者特征
            async for chunk in self._step_extract_features(state):
                yield chunk

            # 步骤2: 生成检索条件
            async for chunk in self._step_generate_queries(state):
                yield chunk

            # 步骤3: 多源检索
            async for chunk in self._step_search(state):
                yield chunk

            # 步骤4: 分析文献
            async for chunk in self._step_analyze_papers(state):
                yield chunk

            # 步骤5: 分析临床试验
            async for chunk in self._step_analyze_trials(state):
                yield chunk

            # 步骤6: 生成最终报告
            async for chunk in self._step_generate_final(state):
                yield chunk

            # 保存最终结果
            await self._save_final_result(state, execution_id)

            # 更新执行记录
            async with get_db_session() as db:
                execution = await db.get(WorkflowExecution, execution_id)
                execution.status = 'completed'
                execution.completed_at = func.now()
                await db.commit()

            yield {'type': 'done', 'content': ''}

        except Exception as e:
            # 记录错误
            async with get_db_session() as db:
                execution = await db.get(WorkflowExecution, execution_id)
                execution.status = 'failed'
                execution.error_message = str(e)
                await db.commit()

            yield {
                'type': 'error',
                'step': state.get('current_step', 'unknown'),
                'content': f'❌ 工作流执行失败: {str(e)}'
            }

    async def _step_extract_features(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤1: 提取患者特征"""
        state['current_step'] = 'extract_features'

        yield {
            'type': 'section_start',
            'step': 'extract_features',
            'title': '提取患者特征',
            'collapsible': True
        }

        # 构建上下文
        context_parts = []
        if state['history_messages']:
            context_parts.append("### 历史对话")
            for msg in state['history_messages'][-5:]:
                role = "用户" if msg['type'] == 'user' else "AI"
                context_parts.append(f"**{role}**: {msg['content'][:200]}...")

        if state['user_attachments']:
            context_parts.append("\n### 用户上传的附件")
            for att in state['user_attachments']:
                context_parts.append(f"- {att['original_filename']}")

        context = "\n".join(context_parts)

        prompt = f"""{context}

### 当前用户问题
{state['user_query']}

### 任务
请从以上信息中提取患者的关键特征，包括：
1. **主要疾病/诊断**
2. **病理类型和分期**
3. **基因突变信息**
4. **既往治疗史**
5. **当前状态和需求**

请以结构化、清晰的方式列出这些信息。"""

        messages = [{"role": "user", "content": prompt}]

        # 检查是否有图片附件
        image_attachments = [att for att in state['user_attachments']
                             if att.get('mime_type', '').startswith('image/')]

        full_response = ""

        # 日志: 开始分析
        yield {
            'type': 'log',
            'step': 'extract_features',
            'content': '🤔 正在分析患者信息...\n'
        }

        try:
            if image_attachments:
                for att in image_attachments:
                    async for token in llm_service.chat_with_image_stream(
                            text=prompt,
                            image_path=att['file_path'],
                            history=[]
                    ):
                        full_response += token
            else:
                async for token in llm_service.chat_stream(messages=messages):
                    full_response += token

            state['patient_features'] = full_response

            # 结果: 提取的特征
            yield {
                'type': 'result',
                'step': 'extract_features',
                'content': full_response,
                'summary': '✅ 患者特征提取完成'
            }

        except Exception as e:
            yield {
                'type': 'log',
                'step': 'extract_features',
                'content': f'❌ 分析失败: {str(e)}\n'
            }
            state['errors'].append(f'extract_features: {str(e)}')

        yield {
            'type': 'section_end',
            'step': 'extract_features'
        }

    async def _step_generate_queries(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤2: 生成检索条件"""
        state['current_step'] = 'generate_queries'

        yield {
            'type': 'section_start',
            'step': 'generate_queries',
            'title': '生成检索条件',
            'collapsible': True
        }

        prompt = f"""基于以下患者特征，生成精确的检索条件：

### 患者特征
{state['patient_features']}

### 任务
请生成以下检索条件：
1. **PubMed 检索表达式**: 使用布尔运算符（AND、OR），构建精确的检索式
2. **ClinicalTrials.gov 关键词**: 提取3-5个核心关键词，用逗号分隔

**输出格式（必须严格遵守JSON格式）**:
```json
{{
    "pubmed_query": "检索表达式",
    "clinical_trial_keywords": "关键词1,关键词2,关键词3"
}}
```

只输出JSON，不要有其他内容。"""

        messages = [{"role": "user", "content": prompt}]

        yield {
            'type': 'log',
            'step': 'generate_queries',
            'content': '🔍 正在生成检索条件...\n'
        }

        full_response = ""
        try:
            async for token in llm_service.chat_stream(messages=messages):
                full_response += token

            # 解析 JSON
            start = full_response.find('{')
            end = full_response.rfind('}') + 1
            if start != -1 and end > start:
                queries = json.loads(full_response[start:end])
                state['pubmed_query'] = queries.get('pubmed_query', '')
                state['clinical_trial_keywords'] = queries.get('clinical_trial_keywords', '')
            else:
                raise ValueError("未找到有效的JSON")

            # 结果: 检索条件
            yield {
                'type': 'result',
                'step': 'generate_queries',
                'content': f"""**PubMed 检索式**: `{state['pubmed_query']}`

**临床试验关键词**: `{state['clinical_trial_keywords']}`""",
                'summary': '✅ 检索条件生成完成',
                'data': {
                    'pubmed_query': state['pubmed_query'],
                    'clinical_trial_keywords': state['clinical_trial_keywords']
                }
            }

        except Exception as e:
            yield {
                'type': 'log',
                'step': 'generate_queries',
                'content': f'⚠️ 解析失败，使用默认条件: {str(e)}\n'
            }
            state['pubmed_query'] = state['user_query']
            state['clinical_trial_keywords'] = state['user_query']
            state['errors'].append(f'generate_queries: {str(e)}')

        yield {
            'type': 'section_end',
            'step': 'generate_queries'
        }

    async def _step_search(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤3: 多源检索"""
        state['current_step'] = 'search'

        yield {
            'type': 'section_start',
            'step': 'search',
            'title': '执行多源检索',
            'collapsible': True
        }

        limit = settings.max_search_results
        progress_queue = asyncio.Queue()

        # 启动检索任务
        async def search_all():
            # PubMed
            papers = await search_service.search_pubmed_with_cache(
                state['pubmed_query'],
                limit,
                progress_queue
            )
            state['papers'].extend(papers[:limit])

            # Europe PMC
            if len(state['papers']) < limit:
                remaining = limit - len(state['papers'])
                papers = await search_service.search_europepmc_with_cache(
                    state['pubmed_query'],
                    remaining,
                    progress_queue
                )
                state['papers'].extend(papers[:remaining])

            # 临床试验
            trials = await search_service.search_clinical_trials_with_cache(
                state['clinical_trial_keywords'],
                limit,
                progress_queue
            )
            state['trials'].extend(trials[:limit])

            await progress_queue.put({'type': 'DONE'})

        search_task = asyncio.create_task(search_all())

        # 处理进度消息
        while True:
            msg = await progress_queue.get()

            if isinstance(msg, dict):
                if msg.get('type') == 'DONE':
                    break
                elif msg.get('type') == 'log':
                    # 日志消息
                    yield {
                        'type': 'log',
                        'step': 'search',
                        'source': msg.get('source'),
                        'content': msg['content']
                    }
                elif msg.get('type') == 'result':
                    # 结果消息
                    yield {
                        'type': 'result',
                        'step': 'search',
                        'source': msg.get('source'),
                        'content': msg['content'],
                        'data': msg.get('data')
                    }

        await search_task

        # 汇总结果
        yield {
            'type': 'result',
            'step': 'search',
            'content': f"""### 📊 检索汇总

- **文献总数**: {len(state['papers'])} 篇
- **临床试验**: {len(state['trials'])} 个""",
            'summary': f'✅ 多源检索完成（{len(state["papers"])} 篇文献，{len(state["trials"])} 个试验）',
            'data': {
                'paper_count': len(state['papers']),
                'trial_count': len(state['trials'])
            }
        }

        yield {
            'type': 'section_end',
            'step': 'search'
        }

    async def _step_analyze_papers(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤4: 分析文献"""
        state['current_step'] = 'analyze_papers'

        yield {
            'type': 'section_start',
            'step': 'analyze_papers',
            'title': '分析文献',
            'collapsible': True
        }

        if not state['papers']:
            yield {
                'type': 'result',
                'step': 'analyze_papers',
                'content': 'ℹ️ 未检索到相关文献',
                'summary': 'ℹ️ 无文献可分析'
            }
            yield {'type': 'section_end', 'step': 'analyze_papers'}
            return

        # 只分析前5篇
        papers_to_analyze = state['papers'][:5]

        for i, paper in enumerate(papers_to_analyze):
            yield {
                'type': 'log',
                'step': 'analyze_papers',
                'content': f'\n📄 分析文献 {i+1}/{len(papers_to_analyze)}: {paper["title"]}\n'
            }

            pdf_path = paper.get('pdf_path')
            if not pdf_path or not os.path.exists(pdf_path):
                yield {
                    'type': 'log',
                    'step': 'analyze_papers',
                    'content': '⚠️ PDF文件不存在，跳过\n'
                }
                continue

            prompt = f"""请分析这篇PDF文献：

### 患者特征
{state['patient_features']}

### 用户问题
{state['user_query']}

### 文献信息
- **标题**: {paper['title']}
- **作者**: {paper.get('authors', 'N/A')}
- **发表日期**: {paper.get('pub_date', 'N/A')}

### 分析任务
1. **核心内容**: 简要概述
2. **相关性**: 与患者情况的相关程度
3. **主要发现**: 列出关键结论
4. **证据等级**: 评估研究类型和可靠性
5. **临床意义**: 对患者的实际指导价值

请使用结构化格式输出。"""

            analysis = ""
            try:
                async for token in llm_service.chat_with_pdf_stream(
                        text=prompt,
                        pdf_path=pdf_path,
                        history=[]
                ):
                    analysis += token

                state['paper_analyses'].append({
                    'paper': paper,
                    'analysis': analysis
                })

                # 结果: 单篇文献分析
                yield {
                    'type': 'result',
                    'step': 'analyze_papers',
                    'content': f"""### 文献 {i+1}: {paper['title']}

{analysis}""",
                    'data': {
                        'paper_id': paper.get('id'),
                        'pmid': paper.get('pmid'),
                        'title': paper['title']
                    }
                }

            except Exception as e:
                yield {
                    'type': 'log',
                    'step': 'analyze_papers',
                    'content': f'❌ 分析失败: {str(e)}\n'
                }

        yield {
            'type': 'result',
            'step': 'analyze_papers',
            'content': '',
            'summary': f'✅ 文献分析完成（{len(state["paper_analyses"])} 篇）'
        }

        yield {
            'type': 'section_end',
            'step': 'analyze_papers'
        }

    async def _step_analyze_trials(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤5: 分析临床试验"""
        state['current_step'] = 'analyze_trials'

        yield {
            'type': 'section_start',
            'step': 'analyze_trials',
            'title': '分析临床试验',
            'collapsible': True
        }

        if not state['trials']:
            yield {
                'type': 'result',
                'step': 'analyze_trials',
                'content': 'ℹ️ 未检索到相关临床试验',
                'summary': 'ℹ️ 无试验可分析'
            }
            yield {'type': 'section_end', 'step': 'analyze_trials'}
            return

        yield {
            'type': 'log',
            'step': 'analyze_trials',
            'content': f'🤔 正在分析 {len(state["trials"])} 个临床试验...\n'
        }

        # 格式化试验信息
        trials_text = []
        for i, trial in enumerate(state['trials']):
            trial_info = f"""### 试验 {i+1}: {trial.get('title')}
- **NCT ID**: {trial.get('nct_id')}
- **状态**: {trial.get('status')}
- **阶段**: {trial.get('phase')}
- **疾病**: {trial.get('conditions')}
- **赞助方**: {trial.get('sponsor')}
"""
            trials_text.append(trial_info)

        prompt = f"""基于患者特征评估以下临床试验：

### 患者特征
{state['patient_features']}

### 临床试验列表
{chr(10).join(trials_text)}

### 分析任务
针对每个试验:
1. **适配度评分** (0-100分)
2. **入组标准分析**
3. **排除标准考量**
4. **试验优势**
5. **潜在风险**
6. **推荐等级**

最后给出综合建议。"""

        messages = [{"role": "user", "content": prompt}]

        analysis = ""
        try:
            async for token in llm_service.chat_stream(
                    messages=messages,
                    model=settings.qwen_long_model
            ):
                analysis += token

            state['trial_analysis'] = analysis

            # 结果: 试验分析
            yield {
                'type': 'result',
                'step': 'analyze_trials',
                'content': analysis,
                'summary': f'✅ 临床试验分析完成（{len(state["trials"])} 个）'
            }

        except Exception as e:
            yield {
                'type': 'log',
                'step': 'analyze_trials',
                'content': f'❌ 分析失败: {str(e)}\n'
            }

        yield {
            'type': 'section_end',
            'step': 'analyze_trials'
        }

    async def _step_generate_final(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤6: 生成最终报告"""
        state['current_step'] = 'generate_final'

        yield {
            'type': 'section_start',
            'step': 'generate_final',
            'title': '生成最终报告',
            'collapsible': False
        }

        yield {
            'type': 'log',
            'step': 'generate_final',
            'content': '📝 正在生成综合报告...\n'
        }

        # 汇总文献分析
        papers_summary = []
        for i, item in enumerate(state['paper_analyses']):
            summary = f"**文献 {i+1}**: {item['paper']['title']} - {item['analysis'][:200]}..."
            papers_summary.append(summary)

        prompt = f"""请基于所有分析生成一份专业医疗咨询报告：

### 原始问题
{state['user_query']}

### 患者特征
{state['patient_features'][:500]}...

### 文献分析（{len(state['paper_analyses'])} 篇）
{chr(10).join(papers_summary) if papers_summary else "暂无"}

### 临床试验分析（{len(state['trials'])} 个）
{state['trial_analysis'][:500] if state['trial_analysis'] else "暂无"}...

### 报告要求
生成结构化报告，包含：
1. **执行摘要**
2. **治疗方案建议**
3. **临床试验推荐**
4. **注意事项**
5. **后续行动建议**"""

        messages = [{"role": "user", "content": prompt}]

        final_answer = ""
        try:
            async for token in llm_service.chat_stream(messages=messages):
                final_answer += token

            state['final_answer'] = final_answer

            # 结果: 最终报告
            yield {
                'type': 'result',
                'step': 'generate_final',
                'content': final_answer,
                'summary': '✅ 最终报告生成完成'
            }

        except Exception as e:
            yield {
                'type': 'log',
                'step': 'generate_final',
                'content': f'❌ 生成失败: {str(e)}\n'
            }

        yield {
            'type': 'section_end',
            'step': 'generate_final'
        }

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
        """保存最终结果到数据库（只保存结果，不保存日志）"""
        async with get_db_session() as db:
            # 构建完整的最终报告
            full_content = f"""# 多源检索分析报告

## 1. 患者特征分析
{state['patient_features']}

---

## 2. 检索条件
- **PubMed**: `{state['pubmed_query']}`
- **临床试验**: `{state['clinical_trial_keywords']}`

---

## 3. 检索结果
- **文献数量**: {len(state['papers'])} 篇
- **临床试验数量**: {len(state['trials'])} 个

---

## 4. 文献分析
"""

            # 添加文献分析
            if state['paper_analyses']:
                for i, item in enumerate(state['paper_analyses']):
                    full_content += f"\n### 文献 {i+1}: {item['paper']['title']}\n\n"
                    full_content += f"{item['analysis']}\n\n---\n"
            else:
                full_content += "\n暂无文献分析\n\n---\n"

            # 添加试验分析
            full_content += f"\n## 5. 临床试验分析\n\n"
            if state['trial_analysis']:
                full_content += f"{state['trial_analysis']}\n\n---\n"
            else:
                full_content += "\n暂无临床试验分析\n\n---\n"

            # 添加最终报告
            full_content += f"\n## 6. 综合报告\n\n{state['final_answer']}\n"

            # 保存为消息
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
workflow_service_v2 = MultiSourceWorkflowV2()