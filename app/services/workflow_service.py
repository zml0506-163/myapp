"""
工作流服务
app/services/workflow_service.py
"""
import os
import json
import time
from typing import TypedDict, AsyncGenerator, List, Dict, Optional, Set
import asyncio
import logging
from sqlalchemy import select, func, update

from app.core.config import settings
from app.db.database import get_db_session
from app.services.llm_service import llm_service
from app.services.search_service import search_service
from app.prompts.workflow_prompts import WorkflowPrompts
from app.models import WorkflowExecution, Message, MessageType, MessageStatus
from app.crud import message as crud_message
from app.schemas.message import MessageCreateSchema
from app.core.logger import get_logger
from app.tools_api.factory import resolve_tool_facade
from app.tools_api.models import Trial as ToolTrial
from app.workflows.router import make_plan

logger = get_logger(__name__)
logging.basicConfig(level=logging.INFO)


class WorkflowState(TypedDict):
    """工作流状态"""
    conversation_id: int
    user_id: int
    user_query: str
    user_attachments: List[Dict]
    history_messages: List[Dict]
    patient_features: str
    pubmed_query: str
    europepmc_query: str  # 新增：Europe PMC 检索条件
    clinical_trial_keywords: str
    papers: List[Dict]
    trials: List[Dict]
    paper_analyses: List[Dict]
    trial_analysis: str
    final_answer: str
    current_step: str
    errors: List[str]
    intent: Dict[str, bool]


class WorkflowService:
    """优化的工作流服务"""

    def __init__(self):
        self.prompts = WorkflowPrompts()
        # 工具接口层（可切换 local/mcp），保持向后兼容
        self.tools = resolve_tool_facade()
        # 执行级别计时与步数统计（仅用于日志展示）
        self._start_ts: float = 0.0
        self._steps_done: int = 0
        self._budget_tokens: int = 0

    async def _detect_intent(self, user_query: str) -> Dict[str, bool]:
        """基于用户问题识别意图：是否只检索文献/只检索临床试验/两者都检索"""
        q = (user_query or "").lower()
        trials_keywords = ["临床试验", "试验", "nct", "clinical trial", "入组", "排除标准"]
        papers_keywords = ["文献", "论文", "pmid", "研究", "综述", "paper"]
        use_trials = any(k in q for k in trials_keywords)
        use_papers = any(k in q for k in papers_keywords)
        # 如果用户没有明确指出，则默认两者都检索
        if not use_trials and not use_papers:
            use_trials = True
            use_papers = True
        return {"use_papers": use_papers, "use_trials": use_trials}

    async def execute_with_streaming(
            self,
            conversation_id: int,
            user_id: int,
            user_query: str,
            message_id: int,  # 添加 message_id 参数
            user_attachments: Optional[List[Dict]] = None,
            is_first_conversation: bool = False
    ) -> AsyncGenerator[Dict, None]:
        """执行工作流并流式输出"""

        execution_id = await self._create_execution(conversation_id, user_id)
        logger.info(f"开始执行工作流，对话ID: {conversation_id}, 消息ID: {message_id}, 是否新对话: {is_first_conversation}")

        state: WorkflowState = {
            'conversation_id': conversation_id,
            'user_id': user_id,
            'user_query': user_query,
            'user_attachments': user_attachments or [],
            'history_messages': await self._load_history(conversation_id),
            'patient_features': '',
            'pubmed_query': '',
            'europepmc_query': '',  # 新增初始化
            'clinical_trial_keywords': '',
            'papers': [],
            'trials': [],
            'paper_analyses': [],
            'trial_analysis': '',
            'final_answer': '',
            'current_step': '',
            'errors': [],
            'intent': {'use_papers': True, 'use_trials': True}
        }

        try:
            # 记录执行起始时间
            self._start_ts = time.time()
            self._steps_done = 0
            self._budget_tokens = 0
            # 可选：展示路由计划（仅日志/展示，不改变实际执行）

            # 可选：展示型 plan（不改流程）
            if settings.deliberate_enabled:
                yield {
                    'type': 'section_start',
                    'step': 'plan_deliberate',
                    'title': '🧩 规划（展示型）',
                    'collapsible': True,
                }
                yield {
                    'type': 'log',
                    'step': 'plan_deliberate',
                    'source': 'router',
                    'content': 'plan: display_only=true reason=fixed_plan\n',
                    'newline': True,
                }
                yield {'type': 'section_end', 'step': 'plan_deliberate'}

            # 根据用户问题识别意图（决定使用哪些检索工具）
            state['intent'] = await self._detect_intent(state['user_query'])

            # 预加载缓存的患者特征（无附件时优先复用）
            cached_pf = await self._load_cached_patient_features(state['conversation_id'])
            if cached_pf and not state['user_attachments']:
                state['patient_features'] = cached_pf

            # 执行所有步骤
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

            # 可选：展示型 rerank 与 grounding（不改流程，仅日志）
            if settings.deliberate_enabled:
                # rerank 展示（保留展示，不改流程）
                yield {
                    'type': 'section_start',
                    'step': 'rerank_deliberate',
                    'title': '🔀 候选重排（展示型）',
                    'collapsible': True,
                }
                rerank_basis = 'relevance,diversity,balance'
                paper_cnt = len(state.get('papers', []) or [])
                trial_cnt = len(state.get('trials', []) or [])
                yield {
                    'type': 'log',
                    'step': 'rerank_deliberate',
                    'source': 'workflow',
                    'content': f'rerank: display_only=true basis={rerank_basis} candidates=paper:{paper_cnt},trial:{trial_cnt}\n',
                    'newline': True,
                }
                yield {'type': 'section_end', 'step': 'rerank_deliberate'}

                # grounding 实际校验（重要）：在展示段位置输出真实校验日志
                async for chunk in self._step_grounding_check(state):
                    yield chunk

            async for chunk in self._step_generate_final(state):
                yield chunk



            # 保存结果
            await self._save_result(state, execution_id, message_id)
            await self._update_execution(execution_id, 'completed')
            logger.info(f"工作流执行完成，执行ID: {execution_id}")

            # 生成标题
            if is_first_conversation:
                logger.info(f"开始生成对话标题，对话ID: {conversation_id}")
                new_title = await self._generate_title(state, conversation_id, user_id)
                # 通知前端标题已更新
                if new_title:
                    yield {
                        'type': 'title_updated',
                        'conversation_id': conversation_id,
                        'title': new_title
                    }

            # 最终完成信号
            yield {'type': 'done', 'content': ''}

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"工作流执行失败: {error_detail}")

            await self._update_execution(execution_id, 'failed', str(e))
            
            # 保存错误信息到数据库
            await self._save_error_result(state, execution_id, message_id, str(e))
            
            yield {
                'type': 'error',
                'step': state.get('current_step', 'unknown'),
                'content': f'❌ 执行失败: {str(e)}'
            }

    async def _step_extract_features(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤1: 提取患者特征（修复日志输出）"""
        state['current_step'] = 'extract_features'

        # 开始区块
        yield {
            'type': 'section_start',
            'step': 'extract_features',
            'title': '🔍 提取患者特征',
            'collapsible': True
        }

        # 若已有缓存患者特征且当前没有附件，则直接复用并跳过提取
        if state['patient_features'] and not state['user_attachments']:
            yield {
                'type': 'result',
                'step': 'extract_features',
                'content': state['patient_features'],
                'is_incremental': False,
                'summary': '✅ 复用患者特征（跳过提取）'
            }
            yield {'type': 'section_end', 'step': 'extract_features'}
            return

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
        prompt = self.prompts.extract_features(context, state['user_query'])

        full_response = ""

        try:
            # 处理附件
            file_ids = []
            if state['user_attachments']:
                from app.services.file_service import file_service
                
                # 输出上传文件日志
                yield {
                    'type': 'log',
                    'step': 'extract_features',
                    'source': 'extract_features',
                    'content': f'正在上传和解析 {len(state["user_attachments"])} 个文件...\n\n',
                    'newline': True
                }
                
                file_ids, only_images = await file_service.process_attachments(
                    state['user_attachments']
                )
                
                # 输出解析文件日志
                yield {
                    'type': 'log',
                    'step': 'extract_features',
                    'source': 'extract_features',
                    'content': '文件上传完成，正在解析文件内容...\n\n',
                    'newline': True
                }

                # 如果只有一张图片，使用VL模型
                if only_images and len(file_ids) == 1:
                    image_att = state['user_attachments'][0]
                    async for token in llm_service.chat_with_image_stream(
                            text=prompt,
                            image_path=image_att['file_path'],
                            history=[]
                    ):
                        full_response += token
                        self._budget_tokens += 1
                        # 流式输出结果（增量）
                        yield {
                            'type': 'result',
                            'step': 'extract_features',
                            'content': token,  # 只返回增量 token
                            'is_incremental': True
                        }
                else:
                    # 使用统一接口
                    async for token in llm_service.chat_with_context(
                            user_query=prompt,
                            file_ids=file_ids,
                            system_prompt="你是一个专业的医疗信息分析助手。",
                            model=settings.qwen_long_model
                    ):
                        full_response += token
                        self._budget_tokens += 1
                        # 流式输出结果（增量）
                        yield {
                            'type': 'result',
                            'step': 'extract_features',
                            'content': token,  # 只返回增量 token
                            'is_incremental': True
                        }
            else:
                # 无附件：普通对话
                async for token in llm_service.chat_with_context(
                        user_query=prompt,
                        system_prompt="你是一个专业的医疗信息分析助手。"
                ):
                    full_response += token
                    self._budget_tokens += 1
                    # 流式输出结果（增量）
                    yield {
                        'type': 'result',
                        'step': 'extract_features',
                        'content': token,  # 只返回增量 token
                        'is_incremental': True
                    }

            state['patient_features'] = full_response
            
            # 按照与 LLM 的约定校验输出
            if 'EXTRACT_FAILED:' in full_response or '无法从提供的信息中提取出有效的患者特征' in full_response:
                # LLM 明确表示无法提取
                error_msg = full_response.replace('EXTRACT_FAILED:', '').strip()
                if not error_msg:
                    error_msg = '❌ 未能提取出有效的患者特征，请提供更详细的信息'
                
                yield {
                    'type': 'result',
                    'step': 'extract_features',
                    'content': f'❌ {error_msg}',
                    'is_incremental': False,
                    'summary': '❌ 特征提取失败'
                }
                raise ValueError(f'患者特征提取失败: {error_msg}')
            
            # 基本长度校验（防止异常情况）
            if len(full_response.strip()) < 20:
                error_msg = '❌ 返回内容过短，可能提取失败，请提供更多患者信息'
                yield {
                    'type': 'result',
                    'step': 'extract_features',
                    'content': error_msg,
                    'is_incremental': False,
                    'summary': '❌ 特征提取失败'
                }
                raise ValueError('患者特征内容过短')
            
            # 成功提取，推送完整内容
            yield {
                'type': 'result',
                'step': 'extract_features',
                'content': full_response,
                'is_incremental': False,
                'summary': '✅ 特征提取完成'
            }

        except Exception as e:
            error_msg = f'❌ 分析失败: {str(e)}\n'
            yield {
                'type': 'log',
                'step': 'extract_features',
                'source': 'extract_features',
                'content': error_msg,
                'newline': True
            }
            state['errors'].append(f'extract_features: {str(e)}')
            # 结束区块
            yield {'type': 'section_end', 'step': 'extract_features'}
            # 重新抛出异常，终止工作流
            raise

    async def _step_generate_queries(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤2: 生成检索条件"""
        state['current_step'] = 'generate_queries'

        yield {
            'type': 'section_start',
            'step': 'generate_queries',
            'title': '🔍 生成检索条件',
            'collapsible': True
        }
        # 按用户意图完全跳过该步骤（无需生成任何检索条件）
        if not (state.get('intent', {}).get('use_papers', True) or state.get('intent', {}).get('use_trials', True)):
            yield {
                'type': 'result',
                'step': 'generate_queries',
                'content': 'ℹ️ 已按用户意图跳过检索条件生成',
                'summary': 'ℹ️ 跳过检索条件生成'
            }
            yield {'type': 'section_end', 'step': 'generate_queries'}
            return

        yield {
            'type': 'log',
            'step': 'generate_queries',
            'source': 'generate_queries',
            'content': '正在生成检索条件...\n\n',
            'newline': True
        }

        need_papers = state.get('intent', {}).get('use_papers', True)
        need_trials = state.get('intent', {}).get('use_trials', True)
        prompt = self.prompts.generate_queries_selective(state['patient_features'], need_papers, need_trials)
        full_response = ""

        try:
            async for token in llm_service.chat_with_context(
                    user_query=prompt,
                    system_prompt="你是一个专业的检索条件生成助手。"
            ):
                full_response += token
                self._budget_tokens += 1
                # 流式显示思考过程
                yield {
                    'type': 'log',
                    'step': 'generate_queries',
                    'source': 'generate_queries',
                    'content': token,
                    'newline': False
                }

            # 按照与 LLM 的约定校验输出
            if 'GENERATE_FAILED:' in full_response:
                # LLM 明确表示无法生成
                error_msg = full_response.replace('GENERATE_FAILED:', '').strip()
                if not error_msg:
                    error_msg = '无法生成有效的检索条件，请提供更详细的信息'
                
                yield {
                    'type': 'result',
                    'step': 'generate_queries',
                    'content': f'❌ {error_msg}',
                    'summary': '❌ 检索条件生成失败'
                }
                raise ValueError(f'检索条件生成失败: {error_msg}')
            
            # 解析JSON
            start = full_response.find('{')
            end = full_response.rfind('}') + 1
            if start != -1 and end > start:
                queries = json.loads(full_response[start:end])
                state['pubmed_query'] = queries.get('pubmed_query', '').strip()
                state['europepmc_query'] = queries.get('europepmc_query', '').strip()
                state['clinical_trial_keywords'] = queries.get('clinical_trial_keywords', '').strip()
            else:
                raise ValueError("未找到有效的JSON")
            
            # 根据用户意图过滤不需要的检索项
            if not state.get('intent', {}).get('use_papers', True):
                state['pubmed_query'] = ''
                state['europepmc_query'] = ''
            if not state.get('intent', {}).get('use_trials', True):
                state['clinical_trial_keywords'] = ''

            # 检查解析结果是否为空
            if not state['pubmed_query'] and not state['europepmc_query'] and not state['clinical_trial_keywords']:
                error_msg = '❌ 生成的检索条件为空，请提供更具体的患者信息'
                yield {
                    'type': 'result',
                    'step': 'generate_queries',
                    'content': error_msg,
                    'summary': '❌ 检索条件生成失败'
                }
                raise ValueError('检索条件为空')

            yield {
                'type': 'result',
                'step': 'generate_queries',
                'content': f"""**PubMed 检索式**: `{state['pubmed_query']}`

**Europe PMC 检索式**: `{state['europepmc_query']}`

**临床试验关键词**: `{state['clinical_trial_keywords']}`""",
                'summary': '✅ 检索条件生成完成',
                'data': {
                    'pubmed_query': state['pubmed_query'],
                    'europepmc_query': state['europepmc_query'],
                    'clinical_trial_keywords': state['clinical_trial_keywords']
                }
            }

        except Exception as e:
            yield {
                'type': 'log',
                'step': 'generate_queries',
                'source': 'generate_queries',
                'content': f'\n❌ 生成失败: {str(e)}\n',
                'newline': True
            }
            state['errors'].append(f'generate_queries: {str(e)}')
            # 结束区块
            yield {'type': 'section_end', 'step': 'generate_queries'}
            # 重新抛出异常，终止工作流
            raise

    async def _step_search(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤3: 执行检索（支持自动放宽重试）"""
        state['current_step'] = 'search'

        yield {
            'type': 'section_start',
            'step': 'search',
            'title': '📚 执行多源检索',
            'collapsible': True
        }
        # 按用户意图跳过检索
        if not (state.get('intent', {}).get('use_papers', True) or state.get('intent', {}).get('use_trials', True)):
            yield {
                'type': 'result',
                'step': 'search',
                'content': 'ℹ️ 已按用户意图跳过检索',
                'summary': 'ℹ️ 跳过检索'
            }
            yield {'type': 'section_end', 'step': 'search'}
            return
        logging.getLogger("workflow_service").info("section_start search")

        progress_queue = asyncio.Queue()
        target_count = settings.max_search_results
        max_retries = 2  # 最多重试2次
        need_papers = state.get('intent', {}).get('use_papers', True)
        need_trials = state.get('intent', {}).get('use_trials', True)
        
        for retry in range(max_retries + 1):
            if retry > 0:
                yield {
                    'type': 'log',
                    'source': 'search',
                    'content': f'\n⚠️ 第{retry}次检索结果为0，正在放宽条件重试...\n',
                    'newline': True
                }
                relaxed_msgs = []
                # 放宽检索条件（文献+试验）
                if need_papers:
                    state['pubmed_query'], state['europepmc_query'] = await self._relax_queries(
                        state['pubmed_query'], 
                        state['europepmc_query'],
                        state['patient_features']
                    )
                    relaxed_msgs.append(f'🔄 放宽后 PubMed: `{state["pubmed_query"]}`')
                    relaxed_msgs.append(f'🔄 放宽后 Europe PMC: `{state["europepmc_query"]}`')
                # 放宽试验关键词
                if need_trials:
                    state['clinical_trial_keywords'] = await self._relax_trials_keywords(
                        state['clinical_trial_keywords'],
                        state['patient_features']
                    )
                    relaxed_msgs.append(f'🔄 放宽后 Trials: `{state["clinical_trial_keywords"]}`')
                if relaxed_msgs:
                    yield {
                        'type': 'log',
                        'source': 'search',
                        'content': "\n".join(relaxed_msgs) + "\n",
                        'newline': True
                    }

            async def search_all():
                """执行检索任务"""
                try:
                    async def _fetch_papers_via_tools(query: str, label: str, sources: List[str], fallback_coro):
                        if not query:
                            return []
                        await progress_queue.put({
                            'type': 'log',
                            'source': label,
                            'content': f'🔍 使用工具接口检索 {label}，检索式: `{query}`\n',
                            'newline': True
                        })
                        try:
                            result = await self.tools.search_papers(
                                query=query,
                                size=target_count,
                                sources=sources
                            )
                            papers = [paper.dict() for paper in result.papers]
                            await progress_queue.put({
                                'type': 'log',
                                'source': label,
                                'content': f'✅ 工具接口返回 {len(papers)} 篇文献\n',
                                'newline': True
                            })
                            return papers
                        except Exception as tool_error:
                            await progress_queue.put({
                                'type': 'log',
                                'source': label,
                                'content': f'⚠️ 工具接口检索失败，回退本地实现: {tool_error}\n',
                                'newline': True
                            })
                            return await fallback_coro()

                    logger.info(
                        "search start pubmed_query=%s europepmc_query=%s trials_keywords=%s",
                        state.get('pubmed_query'),
                        state.get('europepmc_query'),
                        state.get('clinical_trial_keywords')
                    )

                    all_papers: List[Dict] = []

                    if need_papers and (state['pubmed_query'] or state['europepmc_query']):
                        tasks: List[asyncio.Task] = []

                        if state['pubmed_query']:
                            async def _fallback_pubmed():
                                return await search_service._fetch_pubmed_papers(
                                    state['pubmed_query'],
                                    target_count,
                                    progress_queue
                                )
                            tasks.append(asyncio.create_task(_fetch_papers_via_tools(
                                state['pubmed_query'],
                                'pubmed',
                                ['pubmed'],
                                _fallback_pubmed
                            )))

                        if state['europepmc_query']:
                            async def _fallback_europepmc():
                                return await search_service._fetch_europepmc_papers(
                                    state['europepmc_query'],
                                    target_count,
                                    progress_queue
                                )
                            tasks.append(asyncio.create_task(_fetch_papers_via_tools(
                                state['europepmc_query'],
                                'europepmc',
                                ['europepmc'],
                                _fallback_europepmc
                            )))

                        if tasks:
                            paper_batches = await asyncio.gather(*tasks)
                            for batch in paper_batches:
                                if batch:
                                    all_papers.extend(batch)

                    # 去重、打分并限制数量
                    if all_papers:
                        state['papers'].extend(all_papers)
                        state['papers'] = self._trim_and_score_papers(
                            state['papers'],
                            state['pubmed_query'],
                            state['europepmc_query'],
                            target_count
                        )

                    # 仅在需要试验检索时执行
                    if state.get('intent', {}).get('use_trials', True) and state['clinical_trial_keywords']:
                        try:
                            trials_result = await self.tools.search_trials(
                                state['clinical_trial_keywords'],
                                target_count,
                            )
                            # ToolsFacade 使用统一模型；此处转换为原来的 dict 结构
                            converted = [
                                {
                                    'nct_id': t.nct_id,
                                    'title': t.title,
                                    'status': t.status,
                                    'phase': t.phase,
                                    'conditions': t.conditions,
                                    'sponsor': t.sponsor,
                                    'locations': t.locations,
                                    'source_url': t.source_url,
                                }
                                for t in trials_result.trials
                            ]
                            state['trials'].extend(converted)
                        except Exception as _e:
                            # 回退老实现，保持兼容
                            trials = await search_service.search_trials_with_ranking(
                                state['clinical_trial_keywords'],
                                target_count,
                                progress_queue
                            )
                            state['trials'].extend(trials)
                        if state['trials']:
                            state['trials'] = self._trim_trials(state['trials'], target_count)
                        if not state['trials']:
                            logger.info("trials empty for keywords=%s", state.get('clinical_trial_keywords'))
                        try:
                            logging.getLogger("workflow_service").info(
                                "trials fetched count=%d keywords=%s",
                                len(state['trials']),
                                state.get('clinical_trial_keywords')
                            )
                            # 采样前3个标题用于快速确认
                            sample_titles = [t.get('title') for t in state['trials'][:3]]
                            logging.getLogger("workflow_service").info(
                                "trials sample titles=%s",
                                sample_titles
                            )
                        except Exception:
                            pass

                except Exception as e:
                    await progress_queue.put({
                        'type': 'log',
                        'source': 'search',
                        'content': f'❌ 检索出错: {str(e)}\n',
                        'newline': True
                    })
                finally:
                    await progress_queue.put({'type': 'DONE'})

            # 启动检索任务
            search_task = asyncio.create_task(search_all())

            # 转发进度消息
            while True:
                msg = await progress_queue.get()

                if isinstance(msg, dict):
                    if msg.get('type') == 'DONE':
                        break
                    elif msg.get('type') in ('log', 'result', 'progress'):
                        # 直接转发
                        if msg.get('type') == 'progress':
                            logging.getLogger("workflow_service").info(
                                "forward progress source=%s id=%s status=%s",
                                msg.get('source'), msg.get('id'), msg.get('status')
                            )
                        yield msg

            await search_task
            
            # 检查结果
            if self._should_stop_search(state, need_papers, need_trials) or retry >= max_retries:
                break  # 有结果或达到最大重试次数，退出

        # 汇总结果
        yield {
            'type': 'result',
            'step': 'search',
            'content': f"""### 📊 检索汇总

- **文献总数**: {len(state['papers'])} 篇
- **临床试验**: {len(state['trials'])} 个""",
            'summary': f'✅ 检索完成（{len(state["papers"])} 篇文献，{len(state["trials"])} 个试验）',
            'data': {
                'paper_count': len(state['papers']),
                'trial_count': len(state['trials'])
            }
        }

        yield {'type': 'section_end', 'step': 'search'}

    def _trim_and_score_papers(
            self,
            papers: List[Dict],
            pubmed_query: str,
            europepmc_query: str,
            limit: int
    ) -> List[Dict]:
        deduped = search_service._deduplicate_papers(papers)
        for paper in deduped:
            query = self._select_query_for_paper(paper, pubmed_query, europepmc_query)
            title_score = search_service._calculate_relevance(query, paper.get('title', ''))
            abstract_score = search_service._calculate_relevance(query, paper.get('abstract', ''))
            paper['relevance_score'] = (title_score * 0.7 + abstract_score * 0.3)
        deduped.sort(key=lambda p: p.get('relevance_score', 0), reverse=True)
        return deduped[:limit] if limit and limit > 0 else deduped

    def _select_query_for_paper(self, paper: Dict, pubmed_query: str, europepmc_query: str) -> str:
        source = (paper.get('source_type') or '').lower()
        if source == 'europepmc' and europepmc_query:
            return europepmc_query
        if source == 'pubmed' and pubmed_query:
            return pubmed_query
        # fallback：任选可用的 query
        if pubmed_query:
            return pubmed_query
        if europepmc_query:
            return europepmc_query
        return ''

    def _should_stop_search(self, state: WorkflowState, need_papers: bool, need_trials: bool) -> bool:
        has_papers = len(state.get('papers', [])) > 0
        has_trials = len(state.get('trials', [])) > 0
        if need_papers and not need_trials:
            return has_papers
        if need_trials and not need_papers:
            return has_trials
        if need_papers and need_trials:
            return has_papers or has_trials
        return True

    def _trim_trials(self, trials: List[Dict], limit: int) -> List[Dict]:
        seen: Set[str] = set()
        unique: List[Dict] = []
        for trial in trials:
            key = (trial.get('nct_id') or '').strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            unique.append(trial)
        return unique[:limit] if limit and limit > 0 else unique
    
    async def _relax_queries(self, pubmed_query: str, europepmc_query: str, patient_features: str) -> tuple:
        """放宽检索条件（移除最不重要的条件）"""
        # 简单的放宽策略：移除 AND 后面的一个条件
        if ' AND ' in pubmed_query:
            parts = pubmed_query.split(' AND ')
            relaxed_pubmed = ' AND '.join(parts[:-1]) if len(parts) > 1 else parts[0]
        else:
            relaxed_pubmed = pubmed_query
        
        if ',' in europepmc_query:
            parts = [p.strip() for p in europepmc_query.split(',')]
            relaxed_europepmc = ', '.join(parts[:-1]) if len(parts) > 1 else parts[0]
        else:
            relaxed_europepmc = europepmc_query
        
        return relaxed_pubmed, relaxed_europepmc

    async def _relax_trials_keywords(self, trial_keywords: str, patient_features: str) -> str:
        """放宽临床试验关键词：减少过窄词、增加同义词/核心词，输出逗号分隔的3-5个关键词"""
        base = (trial_keywords or '').strip()
        prompt = f"""基于患者特征与当前临床试验关键词，生成更宽松的关键词（3-5个，逗号分隔）。

患者特征：{patient_features[:400]}
当前关键词：{base or '（空）'}

要求：
- 去除过窄的修饰词，保留疾病名称、药物/机制、阶段等核心词
- 仅输出关键词，用逗号分隔；不要输出额外说明
- 若当前为空，请根据患者特征生成合理的3-5个关键词
"""
        resp = ''
        try:
            async for token in llm_service.chat_with_context(
                user_query=prompt,
                system_prompt="你是一个检索策略助手，负责放宽临床试验关键词。"
            ):
                resp += token
        except Exception:
            return base or ''
        # 规范化：以逗号分割，去空白，最多5个
        parts = [p.strip() for p in resp.split(',') if p.strip()]
        return ', '.join(parts[:5])
    async def _step_analyze_papers(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤4: 分析文献（使用统一接口）"""
        state['current_step'] = 'analyze_papers'

        yield {
            'type': 'section_start',
            'step': 'analyze_papers',
            'title': '📄 分析文献',
            'collapsible': True
        }
        # 按用户意图跳过文献分析
        if not state.get('intent', {}).get('use_papers', True):
            yield {
                'type': 'result',
                'step': 'analyze_papers',
                'content': 'ℹ️ 已按用户意图跳过文献分析',
                'summary': 'ℹ️ 跳过文献分析'
            }
            yield {'type': 'section_end', 'step': 'analyze_papers'}
            return

        if not state['papers']:
            yield {
                'type': 'result',
                'step': 'analyze_papers',
                'content': 'ℹ️ 未检索到相关文献',
                'summary': 'ℹ️ 无文献可分析'
            }
            yield {'type': 'section_end', 'step': 'analyze_papers'}
            return

        from app.services.file_service import file_service

        for i, paper in enumerate(state['papers']):
            yield {
                'type': 'log',
                'step': 'analyze_papers',
                'source': 'analyze_papers',
                'content': f'\n📄 分析文献 {i+1}/{len(state["papers"])}: {paper["title"][:50]}...\n\n',
                'newline': True
            }

            pdf_path = paper.get('pdf_path')
            if not pdf_path or not os.path.exists(pdf_path):
                yield {
                    'type': 'log',
                    'step': 'analyze_papers',
                    'source': 'analyze_papers',
                    'content': '⚠️ PDF不存在，跳过\n',
                    'newline': True
                }
                continue

            prompt = self.prompts.analyze_paper(
                state['patient_features'],
                state['user_query'],
                paper
            )

            analysis = ""
            try:
                # 优先通过工具接口层进行 PDF 流式分析
                async for token in self.tools.analyze_pdf_stream(
                        patient_features=state['patient_features'],
                        user_query=state['user_query'],
                        pdf_path=pdf_path,
                ):  # type: ignore
                    analysis += token
                    self._budget_tokens += 1
                    yield {
                        'type': 'result',
                        'step': 'analyze_papers',
                        'content': token,
                        'is_incremental': True
                    }
                
                # 成功分析后，将结果添加到状态中
                state['paper_analyses'].append({
                    'paper': paper,
                    'analysis': analysis
                })
                
                # 最后推送完整内容
                yield {
                    'type': 'result',
                    'step': 'analyze_papers',
                    'content': f"""### 文献 {i+1}: {paper['title']}

{analysis}""",
                    'is_incremental': False,
                    'data': {
                        'paper_id': paper.get('id'),
                        'pmid': paper.get('pmid'),
                        'title': paper['title']
                    }
                }
            except Exception as e:
                # 回退：沿用现有 llm_service + file_service 路径，保证兼容
                try:
                    file_id = await file_service.get_or_upload_file(pdf_path)
                    if not file_id:
                        raise Exception("文件上传失败")
                    
                    prompt = self.prompts.analyze_paper(
                        state['patient_features'],
                        state['user_query'],
                        paper
                    )
                    
                    analysis = ""
                    async for token in llm_service.chat_with_context(
                            user_query=prompt,
                            file_ids=[file_id],
                            system_prompt="你是一个专业的医疗文献分析助手。请仔细阅读PDF文档，按照指定格式输出结构化分析。",
                            model=settings.qwen_long_model
                    ):
                        analysis += token
                        self._budget_tokens += 1
                        yield {
                            'type': 'result',
                            'step': 'analyze_papers',
                            'content': token,
                            'is_incremental': True
                        }
                    
                    # 成功分析后，将结果添加到状态中
                    state['paper_analyses'].append({
                        'paper': paper,
                        'analysis': analysis
                    })
                    
                    # 最后推送完整内容
                    yield {
                        'type': 'result',
                        'step': 'analyze_papers',
                        'content': f"""### 文献 {i+1}: {paper['title']}

{analysis}""",
                        'is_incremental': False,
                        'data': {
                            'paper_id': paper.get('id'),
                            'pmid': paper.get('pmid'),
                            'title': paper['title']
                        }
                    }
                except Exception as fallback_e:
                    yield {
                        'type': 'log',
                        'step': 'analyze_papers',
                        'source': 'analyze_papers',
                        'content': f'❌ 分析失败: {str(fallback_e)}\n',
                        'newline': True
                    }
                    continue

        yield {
            'type': 'result',
            'step': 'analyze_papers',
            'content': '',
            'summary': f'✅ 文献分析完成（{len(state["paper_analyses"])} 篇）'
        }

        yield {'type': 'section_end', 'step': 'analyze_papers'}

    async def _step_analyze_trials(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤5: 分析临床试验"""
        state['current_step'] = 'analyze_trials'

        yield {
            'type': 'section_start',
            'step': 'analyze_trials',
            'title': '💊 分析临床试验',
            'collapsible': True
        }
        # 按用户意图跳过临床试验分析
        if not state.get('intent', {}).get('use_trials', True):
            yield {
                'type': 'result',
                'step': 'analyze_trials',
                'content': 'ℹ️ 已按用户意图跳过临床试验分析',
                'summary': 'ℹ️ 跳过临床试验分析'
            }
            yield {'type': 'section_end', 'step': 'analyze_trials'}
            return

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
            'source': 'analyze_trials',
            'content': f'正在分析 {len(state["trials"])} 个临床试验...\n\n',
            'newline': True
        }

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

        # 使用工具接口层进行流式分析，保持 SSE 输出不变
        analysis = ""
        try:
            # 转换为工具层 Trial 模型
            tool_trials = [
                ToolTrial(
                    nct_id=t.get('nct_id', ''),
                    title=t.get('title', ''),
                    status=t.get('status'),
                    phase=t.get('phase'),
                    conditions=t.get('conditions'),
                    sponsor=t.get('sponsor'),
                    locations=t.get('locations'),
                    source_url=t.get('source_url'),
                )
                for t in state['trials']
            ]

            _token_count = 0
            async for token in self.tools.analyze_trials_stream(
                state['patient_features'],
                tool_trials,
            ):  # type: ignore
                analysis += token
                _token_count += 1
                self._budget_tokens += 1
                yield {
                    'type': 'result',
                    'step': 'analyze_trials',
                    'content': token,
                    'is_incremental': True,
                }

            logger.info(
                "analyze_trials done tokens=%d content_len=%d",
                _token_count,
                len(analysis),
            )
            if not analysis:
                logger.warning("No analysis output")

            state['trial_analysis'] = analysis
            yield {
                'type': 'result',
                'step': 'analyze_trials',
                'content': analysis,
                'is_incremental': False,
                'summary': f'✅ 临床试验分析完成（{len(state["trials"])} 个）',
            }

        except Exception as e:
            yield {
                'type': 'log',
                'step': 'analyze_trials',
                'source': 'analyze_trials',
                'content': f'❌ 分析失败: {str(e)}\n',
                'newline': True
            }
            logger.exception("analyze_trials error: %s", str(e))

        yield {'type': 'section_end', 'step': 'analyze_trials'}

    async def _step_generate_final(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """步骤6: 生成最终报告"""
        state['current_step'] = 'generate_final'

        yield {
            'type': 'section_start',
            'step': 'generate_final',
            'title': '📝 生成最终报告',
            'collapsible': False
        }

        yield {
            'type': 'log',
            'step': 'generate_final',
            'source': 'generate_final',
            'content': '正在生成综合报告...\n\n',
            'newline': True
        }

        papers_summary = []
        for i, item in enumerate(state['paper_analyses']):
            summary = f"**文献 {i+1}**: {item['paper']['title']} - {item['analysis'][:200]}..."
            papers_summary.append(summary)

        prompt = self.prompts.generate_final_report(
            state['user_query'],
            state['patient_features'],
            '\n'.join(papers_summary) if papers_summary else "暂无",
            state['trial_analysis']
        )

        final_answer = ""
        try:
            # 优先通过工具接口层生成报告（一次性文本），再按字符回放为 token 以保持前端体验
            try:
                report = await self.tools.generate_report(
                    user_query=state['user_query'],
                    patient_features=state['patient_features'],
                    papers_summary='\n'.join(papers_summary) if papers_summary else "暂无",
                    trial_analysis=state['trial_analysis'],
                )
                final_answer = report.final_answer or ""
                for ch in final_answer:
                    yield {
                        'type': 'token',
                        'step': 'generate_final',
                        'content': ch,
                    }
                    self._budget_tokens += 1
            except Exception:
                # 回退：沿用现有 llm_service 流式路径
                async for token in llm_service.chat_with_context(
                        user_query=prompt,
                        system_prompt="你是一个专业的医疗咨询报告生成助手。",
                        model=settings.qwen_long_model
                ):
                    final_answer += token
                    self._budget_tokens += 1
                    yield {
                        'type': 'token',
                        'step': 'generate_final',
                        'content': token
                    }

            # 保存最终答案并输出完成汇总
            state['final_answer'] = final_answer
            yield {
                'type': 'result',
                'step': 'generate_final',
                'content': '',
                'summary': '✅ 最终报告生成完成'
            }

        except Exception as e:
            yield {
                'type': 'log',
                'step': 'generate_final',
                'source': 'generate_final',
                'content': f'❌ 生成失败: {str(e)}\n',
                'newline': True
            }

        yield {'type': 'section_end', 'step': 'generate_final'}

    async def _step_grounding_check(self, state: WorkflowState) -> AsyncGenerator[Dict, None]:
        """证据对齐与冲突检测：输出结构化日志（不改变业务结果）。"""
        import re
        yield {
            'type': 'section_start',
            'step': 'grounding_deliberate',
            'title': '🧷 证据对齐（Grounding）',
            'collapsible': True,
        }
        # Grounding 文本来源：临床试验分析 + 各文献分析正文
        trial_text = state.get('trial_analysis') or ''
        paper_texts = []
        for item in state.get('paper_analyses', []) or []:
            try:
                paper = item.get('paper') or {}
                title = paper.get('title') or ''
                analysis = item.get('analysis') or ''
                if title or analysis:
                    paper_texts.append(f"{title}\n{analysis}")
            except Exception:
                continue
        text = trial_text + ('\n' if trial_text and paper_texts else '') + '\n'.join(paper_texts)
        # 提取引用锚点
        pmids = set(re.findall(r"PMID[:\s]?\d+", text, flags=re.IGNORECASE))
        ncts = set(re.findall(r"NCT\d+", text, flags=0))
        refs_count = len(pmids) + len(ncts)
        if refs_count == 0:
            yield {'type': 'log', 'step': 'grounding_deliberate', 'source': 'grounding', 'content': 'warn: no_citations_found\n', 'newline': True}
        else:
            yield {'type': 'log', 'step': 'grounding_deliberate', 'source': 'grounding', 'content': f'citations: count={refs_count} pmids={len(pmids)} ncts={len(ncts)}\n', 'newline': True}

        # 简单一致性/冲突检测（启发式）
        lower = text.lower()
        has_positive = any(k in lower for k in ['显著提高', 'significant improvement', 'effective'])
        has_negative = any(k in lower for k in ['未显示显著', 'no significant', 'ineffective'])
        if has_positive and has_negative:
            yield {'type': 'log', 'step': 'grounding_deliberate', 'source': 'grounding', 'content': 'conflict: positive_vs_negative_evidence\n', 'newline': True}

        # 追溯性：展示若干引用样例
        sample_refs = list(pmids)[:3] + list(ncts)[:3]
        if sample_refs:
            yield {'type': 'log', 'step': 'grounding_deliberate', 'source': 'grounding', 'content': f'trace: sample_refs={", ".join(sample_refs)}\n', 'newline': True}

        yield {'type': 'section_end', 'step': 'grounding_deliberate'}

        # 可选：展示型 critique（不改流程）
        if settings.deliberate_enabled:
            yield {
                'type': 'section_start',
                'step': 'critique_deliberate',
                'title': '🧪 评审（展示型）',
                'collapsible': True,
            }
            yield {
                'type': 'log',
                'step': 'critique_deliberate',
                'source': 'router',
                'content': 'critique: display_only=true checks=[format,consistency]\n',
                'newline': True,
            }
            yield {'type': 'section_end', 'step': 'critique_deliberate'}

    async def _generate_title(self, state: WorkflowState, conversation_id: int, user_id: int) -> Optional[str]:
        """生成对话标题，返回新标题"""
        try:
            title_prompt = f"""请根据以下医疗咨询内容生成一个简短的标题（不超过15个字）：

用户问题：{state['user_query']}

患者特征：{state['patient_features'][:300]}...

要求：
1. 突出疾病/症状关键词
2. 不超过15个字
3. 直接输出标题，不要有其他内容
4. 不使用引号、书名号等标点符号

标题："""

            new_title = ""
            async for token in llm_service.chat_with_context(
                    user_query=title_prompt,
                    system_prompt="你是一个专业的标题生成助手。"
            ):
                new_title += token

            # 清理标题
            new_title = new_title.strip().replace('\n', '').replace('"', '').replace("'", '')

            if new_title and len(new_title) > 2:
                if len(new_title) > 15:
                    new_title = new_title[:15] + "..."

                async with get_db_session() as db:
                    from app.schemas.conversation import ConversationUpdateSchema
                    from app.crud import conversation as crud_conversation
                    await crud_conversation.update_conversation(
                        db,
                        conversation_id=conversation_id,
                        conversation_schema=ConversationUpdateSchema(title=new_title),
                        user_id=user_id
                    )

                logger.info(f"对话 {conversation_id} 已自动重命名为「{new_title}」")
                return new_title
            else:
                logger.warning(f"生成的标题无效，标题: {new_title}")
                return None

        except Exception as e:
            logger.error(f"生成标题失败: {e}")
            return None

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

    async def _update_execution(self, execution_id: int, status: str, error: Optional[str] = None):
        """更新执行状态"""
        async with get_db_session() as db:
            execution = await db.get(WorkflowExecution, execution_id)
            if execution is None:
                logger.warning(f"找不到执行记录: {execution_id}")
                return
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

    async def _load_cached_patient_features(self, conversation_id: int) -> Optional[str]:
        """从之前的工作流执行记录中加载缓存的患者特征"""
        async with get_db_session() as db:
            result = await db.execute(
                select(WorkflowExecution)
                .where(WorkflowExecution.conversation_id == conversation_id)
                .where(WorkflowExecution.patient_features.isnot(None))
                .order_by(WorkflowExecution.created_at.desc())
                .limit(1)
            )
            execution = result.scalar_one_or_none()
            
            if execution and execution.patient_features:
                logger.info(f"从执行记录 {execution.id} 中加载缓存的患者特征")
                return execution.patient_features
            
            return None

    async def _save_result(self, state: WorkflowState, execution_id: int, message_id: int):
        """保存最终结果"""
        async with get_db_session() as db:
            # 动态构建报告内容
            full_parts: list[str] = []
            full_parts.append("# 多源检索分析报告\n\n")

            # 1. 患者特征
            full_parts.append("## 1. 患者特征分析\n")
            full_parts.append(f"{state['patient_features']}\n\n---\n")

            # 2. 检索条件（按需输出）
            full_parts.append("\n## 2. 检索条件\n")
            added_any = False
            if state.get('intent', {}).get('use_papers', True):
                if state['pubmed_query']:
                    full_parts.append(f"- **PubMed**: `{state['pubmed_query']}`\n"); added_any = True
                if state['europepmc_query']:
                    full_parts.append(f"- **Europe PMC**: `{state['europepmc_query']}`\n"); added_any = True
            if state.get('intent', {}).get('use_trials', True) and state['clinical_trial_keywords']:
                full_parts.append(f"- **临床试验**: `{state['clinical_trial_keywords']}`\n"); added_any = True
            if not added_any:
                full_parts.append("- 暂无\n")
            full_parts.append("\n---\n")

            # 3. 检索结果汇总
            full_parts.append("\n## 3. 检索结果\n")
            full_parts.append(f"- **文献数量**: {len(state['papers'])} 篇\n")
            full_parts.append(f"- **临床试验数量**: {len(state['trials'])} 个\n\n---\n")

            # 4. 文献分析（如有且用户需要）
            if state.get('intent', {}).get('use_papers', True) and state['paper_analyses']:
                full_parts.append("\n## 4. 文献分析\n\n")
                for i, item in enumerate(state['paper_analyses']):
                    full_parts.append(f"\n### 文献 {i+1}: {item['paper']['title']}\n\n")
                    full_parts.append(f"{item['analysis']}\n\n---\n")

            # 5. 临床试验分析（如有且用户需要）
            if state.get('intent', {}).get('use_trials', True) and state['trial_analysis']:
                full_parts.append("\n## 5. 临床试验分析\n\n")
                full_parts.append(f"{state['trial_analysis']}\n\n---\n")

            # 6. 综合报告
            full_parts.append(f"\n## 6. 综合报告\n\n{state['final_answer']}\n")

            full_content = "".join(full_parts)

            # 构建元数据
            metadata = {
                "workflow_type": "multi_source",
                "patient_features": state['patient_features'],
                "search_queries": {
                    "pubmed": state['pubmed_query'],
                    "europepmc": state['europepmc_query'],
                    "clinical_trial": state['clinical_trial_keywords']
                },
                "papers": [
                    {
                        "id": paper.get('id'),
                        "pmid": paper.get('pmid'),
                        "title": paper.get('title'),
                        "authors": paper.get('authors')
                    }
                    for paper in state['papers']
                ],
                "trials": [
                    {
                        "nct_id": trial.get('nct_id'),
                        "title": trial.get('title')
                    }
                    for trial in state['trials']
                ],
                "attachments": [
                    {
                        "filename": att.get('filename'),
                        "original_filename": att.get('original_filename')
                    }
                    for att in state['user_attachments']
                ]
            }

            # 更新现有消息，而不是创建新消息
            await crud_message.update_message(
                db,
                message_id=message_id,
                content=full_content,
                status=MessageStatus.COMPLETED
            )
            
            # 更新消息元数据
            await db.execute(
                update(Message)
                .where(Message.id == message_id)
                .values(metadata_json=json.dumps(metadata, ensure_ascii=False))
            )

            execution = await db.get(WorkflowExecution, execution_id)
            if execution is None:
                logger.warning(f"找不到执行记录: {execution_id}")
                return
            execution.result_message_id = message_id
            execution.patient_features = state['patient_features']
            execution.search_queries = json.dumps({
                'pubmed': state['pubmed_query'],
                'clinical_trial': state['clinical_trial_keywords']
            })
            await db.commit()
    
    async def _save_error_result(self, state: WorkflowState, execution_id: int, message_id: int, error_msg: str):
        """保存错误结果到数据库"""
        async with get_db_session() as db:
            # 构建错误信息内容
            error_content = f"""❌ **多源检索执行失败**\n\n"""
            
            # 添加错误信息（去除重复的前缀）
            clean_error_msg = error_msg
            if '：' in error_msg:
                # 提取冒号后面的内容
                clean_error_msg = error_msg.split('：', 1)[1].strip()
            
            error_content += f"""{clean_error_msg}\n\n---\n\n请根据以上提示调整您的输入，然后重试。
"""
            
            # 更新现有消息，而不是创建新消息
            await crud_message.update_message(
                db,
                message_id=message_id,
                content=error_content,
                status=MessageStatus.FAILED
            )


workflow_service = WorkflowService()