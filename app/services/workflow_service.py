"""
工作流服务 V3 - 优化版本
- 使用独立的提示词模块
- 使用优化的检索服务
- 流程更清晰
"""
import os
import json
from typing import TypedDict, AsyncGenerator, List, Dict
import asyncio
from sqlalchemy import select, func

from app.core.config import settings
from app.db.database import get_db_session
from app.services.llm_service import llm_service
from app.services.search_service import optimized_search_service
from app.prompts.workflow_prompts import WorkflowPrompts
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
    patient_features: str
    pubmed_query: str
    clinical_trial_keywords: str
    papers: List[Dict]
    trials: List[Dict]
    paper_analyses: List[Dict]
    trial_analysis: str
    final_answer: str
    current_step: str
    errors: List[str]


class WorkflowService:
    """优化的工作流服务"""

    def __init__(self):
        self.prompts = WorkflowPrompts()

    async def execute_with_streaming(
            self,
            conversation_id: int,
            user_id: int,
            user_query: str,
            user_attachments: List[Dict] = None
    ) -> AsyncGenerator[Dict, None]:
        """执行工作流并流式输出"""

        # 创建执行记录
        execution_id = await self._create_execution(conversation_id, user_id)

        # 初始化状态
        state: WorkflowState = {
            'conversation_id': conversation_id,
            'user_id': user_id,
            'user_query': user_query,
            'user_attachments': user_attachments or [],
            'history_messages': await self._load_history(conversation_id),
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
            # 执行步骤
            async for chunk in self._step_extract_features(state):
                yield chunk

            async for chunk in self._step_generate_queries(state):
                yield chunk

            async for chunk in self._step_search(state):
                yield chunk

            async for chunk in self._step_analyze_papers(state):
                yield chunk

            async for chunk in self._step_analyze_trials(state):
                yield chunk

            async for chunk in self._step_generate_final(state):
                yield chunk

            # 保存结果
            await self._save_result(state, execution_id)

            # 更新执行状态
            await self._update_execution(execution_id, 'completed')

            yield {'type': 'done', 'content': ''}

        except Exception as e:
            await self._update_execution(execution_id, 'failed', str(e))
            yield {
                'type': 'error',
                'step': state.get('current_step', 'unknown'),
                'content': f'❌ 执行失败: {str(e)}'
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

        # 使用提示词模板
        prompt = self.prompts.extract_features(context, state['user_query'])
        messages = [{"role": "user", "content": prompt}]

        # 检查是否有图片
        image_attachments = [att for att in state['user_attachments']
                             if att.get('mime_type', '').startswith('image/')]

        full_response = ""

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

        yield {'type': 'section_end', 'step': 'extract_features'}

    async def _step_generate_queries(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤2: 生成检索条件"""
        state['current_step'] = 'generate_queries'

        yield {
            'type': 'section_start',
            'step': 'generate_queries',
            'title': '生成检索条件',
            'collapsible': True
        }

        # 使用提示词模板
        prompt = self.prompts.generate_queries(state['patient_features'])
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

            # 解析JSON
            start = full_response.find('{')
            end = full_response.rfind('}') + 1
            if start != -1 and end > start:
                queries = json.loads(full_response[start:end])
                state['pubmed_query'] = queries.get('pubmed_query', '')
                state['clinical_trial_keywords'] = queries.get('clinical_trial_keywords', '')
            else:
                raise ValueError("未找到有效的JSON")

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

        yield {'type': 'section_end', 'step': 'generate_queries'}

    async def _step_search(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤3: 执行检索（使用优化的检索服务）"""
        state['current_step'] = 'search'

        yield {
            'type': 'section_start',
            'step': 'search',
            'title': '执行多源检索',
            'collapsible': True
        }

        progress_queue = asyncio.Queue()
        target_count = settings.max_search_results  # 5篇

        # 启动检索任务
        async def search_all():
            # 检索文献（会自动排序和去重）
            papers = await optimized_search_service.search_papers_with_ranking(
                state['pubmed_query'],
                target_count,
                progress_queue
            )
            state['papers'].extend(papers)

            # 检索临床试验（会自动排序）
            trials = await optimized_search_service.search_trials_with_ranking(
                state['clinical_trial_keywords'],
                target_count,
                progress_queue
            )
            state['trials'].extend(trials)

            await progress_queue.put({'type': 'DONE'})

        search_task = asyncio.create_task(search_all())

        # 处理进度消息
        while True:
            msg = await progress_queue.get()

            if isinstance(msg, dict):
                if msg.get('type') == 'DONE':
                    break
                elif msg.get('type') in ('log', 'result'):
                    yield msg

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

        yield {'type': 'section_end', 'step': 'search'}

    async def _step_analyze_papers(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤4: 分析文献（使用提示词模板）"""
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

        for i, paper in enumerate(state['papers']):
            yield {
                'type': 'log',
                'step': 'analyze_papers',
                'content': f'\n📄 分析文献 {i+1}/{len(state["papers"])}: {paper["title"]}\n'
            }

            pdf_path = paper.get('pdf_path')
            if not pdf_path or not os.path.exists(pdf_path):
                yield {
                    'type': 'log',
                    'step': 'analyze_papers',
                    'content': '⚠️ PDF文件不存在，跳过\n'
                }
                continue

            # 使用提示词模板
            prompt = self.prompts.analyze_paper(
                state['patient_features'],
                state['user_query'],
                paper
            )

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

        yield {'type': 'section_end', 'step': 'analyze_papers'}

    async def _step_analyze_trials(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤5: 分析临床试验（使用提示词模板）"""
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

        # 使用提示词模板
        prompt = self.prompts.analyze_trials(
            state['patient_features'],
            chr(10).join(trials_text)
        )

        messages = [{"role": "user", "content": prompt}]

        analysis = ""
        try:
            async for token in llm_service.chat_stream(
                    messages=messages,
                    model=settings.qwen_long_model
            ):
                analysis += token

            state['trial_analysis'] = analysis

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

        yield {'type': 'section_end', 'step': 'analyze_trials'}

    async def _step_generate_final(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤6: 生成最终报告（使用提示词模板）"""
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

        # 使用提示词模板
        prompt = self.prompts.generate_final_report(
            state['user_query'],
            state['patient_features'],
            chr(10).join(papers_summary) if papers_summary else "暂无",
            state['trial_analysis']
        )

        messages = [{"role": "user", "content": prompt}]

        final_answer = ""
        try:
            async for token in llm_service.chat_stream(messages=messages):
                final_answer += token

            state['final_answer'] = final_answer

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

        yield {'type': 'section_end', 'step': 'generate_final'}

    async def _create_execution(self, conversation_id: int, user_id: int) -> int:
        """创建执行记录"""
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
            return execution.id

    async def _update_execution(self, execution_id: int, status: str, error: str = None):
        """更新执行状态"""
        async with get_db_session() as db:
            execution = await db.get(WorkflowExecution, execution_id)
            execution.status = status
            if status == 'completed':
                execution.completed_at = func.now()
            if error:
                execution.error_message = error
            await db.commit()

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

    async def _save_result(self, state: WorkflowState, execution_id: int):
        """保存最终结果"""
        async with get_db_session() as db:
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

            if state['paper_analyses']:
                for i, item in enumerate(state['paper_analyses']):
                    full_content += f"\n### 文献 {i+1}: {item['paper']['title']}\n\n"
                    full_content += f"{item['analysis']}\n\n---\n"
            else:
                full_content += "\n暂无文献分析\n\n---\n"

            full_content += f"\n## 5. 临床试验分析\n\n"
            if state['trial_analysis']:
                full_content += f"{state['trial_analysis']}\n\n---\n"
            else:
                full_content += "\n暂无临床试验分析\n\n---\n"

            full_content += f"\n## 6. 综合报告\n\n{state['final_answer']}\n"

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

            execution = await db.get(WorkflowExecution, execution_id)
            execution.result_message_id = saved_message['id']
            execution.patient_features = state['patient_features']
            execution.search_queries = json.dumps({
                'pubmed': state['pubmed_query'],
                'clinical_trial': state['clinical_trial_keywords']
            })
            await db.commit()


# 全局实例
workflow_service = WorkflowService()