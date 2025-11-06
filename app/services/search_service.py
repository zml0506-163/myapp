"""
优化的多源检索服务 V2
- 检索更多，筛选最相关
- 去重处理
- PDF下载失败继续检索
"""
import asyncio
from typing import List, Dict, Set
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select, or_, and_
import difflib

from app.core.config import settings
from app.db.database import get_db_session
from app.models import Paper, ClinicalTrial
from app.db.crud import upsert_paper, upsert_clinical_trial

from app.tools.pubmed_client import esearch_pmids, efetch_metadata, get_pdf_from_pubmed
from app.tools.europepmc_client import search_europe_pmc
from app.tools.clinical_trials_client import async_search_trials


class SearchProgress:
    """进度回调封装"""
    def __init__(self, queue: asyncio.Queue, source: str):
        self.queue = queue
        self.source = source
        self.loop = asyncio.get_running_loop()

    def callback(self, message: str, newline: bool = True):
        """同步回调"""
        asyncio.run_coroutine_threadsafe(
            self.queue.put({
                'type': 'log',
                'source': self.source,
                'content': message,
                'newline': newline
            }),
            self.loop
        )


class OptimizedSearchService:
    """优化的多源检索服务"""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)

    def _calculate_relevance(self, query: str, text: str) -> float:
        """
        计算文本与查询的相关度（0-100分）

        使用简单的关键词匹配算法
        """
        if not text:
            return 0.0

        # 提取查询关键词
        query_terms = set(query.lower().replace('and', '').replace('or', '').split())
        query_terms = {term.strip() for term in query_terms if len(term.strip()) > 2}

        if not query_terms:
            return 50.0  # 默认分数

        # 计算匹配度
        text_lower = text.lower()
        matches = sum(1 for term in query_terms if term in text_lower)
        score = (matches / len(query_terms)) * 100

        return min(score, 100.0)

    def _deduplicate_papers(self, papers: List[Dict]) -> List[Dict]:
        """
        去重文献（基于PMID、PMCID或标题相似度）
        """
        seen_ids: Set[str] = set()
        seen_titles: List[str] = []
        unique_papers = []

        for paper in papers:
            # 检查PMID
            if paper.get('pmid') and paper['pmid'] in seen_ids:
                continue

            # 检查PMCID
            if paper.get('pmcid') and paper['pmcid'] in seen_ids:
                continue

            # 检查标题相似度（> 0.9 认为重复）
            title = paper.get('title', '')
            is_duplicate = False
            for seen_title in seen_titles:
                similarity = difflib.SequenceMatcher(None, title.lower(), seen_title.lower()).ratio()
                if similarity > 0.9:
                    is_duplicate = True
                    break

            if is_duplicate:
                continue

            # 添加唯一文献
            if paper.get('pmid'):
                seen_ids.add(paper['pmid'])
            if paper.get('pmcid'):
                seen_ids.add(paper['pmcid'])
            seen_titles.append(title)
            unique_papers.append(paper)

        return unique_papers

    async def search_papers_with_ranking(
            self,
            query: str,
            target_count: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """
        检索并排序文献

        Args:
            query: 检索表达式
            target_count: 目标文献数量
            progress_queue: 进度队列

        Returns:
            排序后的文献列表
        """
        # 1. 先查数据库缓存
        cached_papers = []
        async with get_db_session() as db:
            search_terms = query.replace('AND', '').replace('OR', '').split()[:5]
            if search_terms:
                query_filter = select(Paper).where(
                    and_(
                        or_(
                            Paper.source_type == 'pubmed',
                            Paper.source_type == 'europepmc'
                        ),
                        or_(*[Paper.title.ilike(f"%{term}%") for term in search_terms if len(term) > 2])
                    )
                ).limit(target_count * 3)

                result = await db.execute(query_filter)
                cached = result.scalars().all()

                if cached:
                    await progress_queue.put({
                        'type': 'log',
                        'source': 'cache',
                        'content': f'📚 数据库中找到 {len(cached)} 篇已缓存文献\n',
                        'newline': True
                    })

                    for paper in cached:
                        cached_papers.append(self._paper_to_dict(paper))

        # 2. 如果缓存不足，执行检索（检索更多）
        all_papers = cached_papers.copy()

        if len(all_papers) < target_count * 3:
            await progress_queue.put({
                'type': 'log',
                'source': 'pubmed',
                'content': f'\n🔍 开始检索 PubMed 和 Europe PMC...\n',
                'newline': True
            })

            # PubMed检索（检索3倍数量）
            pubmed_papers = await self._fetch_pubmed_papers(
                query, target_count * 3, progress_queue
            )
            all_papers.extend(pubmed_papers)

            # Europe PMC检索（检索3倍数量）
            europepmc_papers = await self._fetch_europepmc_papers(
                query, target_count * 3, progress_queue
            )
            all_papers.extend(europepmc_papers)

        # 3. 去重
        all_papers = self._deduplicate_papers(all_papers)

        await progress_queue.put({
            'type': 'log',
            'source': 'dedup',
            'content': f'🔄 去重后共 {len(all_papers)} 篇文献\n',
            'newline': True
        })

        # 4. 计算相关度并排序
        for paper in all_papers:
            title_score = self._calculate_relevance(query, paper.get('title', ''))
            abstract_score = self._calculate_relevance(query, paper.get('abstract', ''))
            paper['relevance_score'] = (title_score * 0.7 + abstract_score * 0.3)

        all_papers.sort(key=lambda p: p.get('relevance_score', 0), reverse=True)

        # 5. 返回前N篇
        selected_papers = all_papers[:target_count]

        await progress_queue.put({
            'type': 'result',
            'source': 'papers',
            'content': f'✅ 筛选出最相关的 {len(selected_papers)} 篇文献',
            'data': {
                'count': len(selected_papers),
                'papers': selected_papers
            }
        })

        return selected_papers

    async def _fetch_pubmed_papers(
            self,
            query: str,
            limit: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """检索PubMed（持续检索直到满足数量）"""
        results = []

        try:
            # 搜索PMID
            pmids = await esearch_pmids(query, retmax=limit * 5)

            if not pmids:
                await progress_queue.put({
                    'type': 'log',
                    'source': 'pubmed',
                    'content': '⚠️ PubMed 未找到相关文献\n',
                    'newline': True
                })
                return results

            # 获取元数据
            meta = await efetch_metadata(pmids)

            # 处理每个PMID，直到达到目标数量
            async with get_db_session() as db:
                for pid in pmids:
                    if len(results) >= limit:
                        break

                    # 检查是否已存在
                    result = await db.execute(
                        select(Paper).where(
                            Paper.pmid == pid,
                            Paper.source_type == 'pubmed'
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        results.append(self._paper_to_dict(existing))
                        continue

                    await progress_queue.put({
                        'type': 'log',
                        'source': 'pubmed',
                        'content': f'  📄 处理 PMID {pid}...',
                        'newline': False
                    })

                    m = meta.get(pid, {})
                    progress = SearchProgress(progress_queue, 'pubmed')

                    # 下载PDF（带重试机制）
                    max_retries = 2
                    pdf_path = None

                    for retry in range(max_retries):
                        pdf_path = await get_pdf_from_pubmed(
                            pid,
                            m.get("pmcid"),
                            self.executor,
                            progress.callback
                        )

                        if pdf_path:
                            break

                        if retry < max_retries - 1:
                            await progress_queue.put({
                                'type': 'log',
                                'source': 'pubmed',
                                'content': ' 重试...',
                                'newline': False
                            })

                    if not pdf_path:
                        await progress_queue.put({
                            'type': 'log',
                            'source': 'pubmed',
                            'content': ' ❌ 跳过\n',
                            'newline': True
                        })
                        continue

                    await progress_queue.put({
                        'type': 'log',
                        'source': 'pubmed',
                        'content': ' ✅\n',
                        'newline': True
                    })

                    # 保存到数据库
                    paper = await upsert_paper(
                        db,
                        pmid=pid,
                        pmcid=m.get("pmcid"),
                        title=m.get("title") or "(no title)",
                        source_type='pubmed',
                        abstract=m.get("abstract"),
                        pub_date=m.get("pub_date"),
                        authors=m.get("authors"),
                        pdf_path=str(pdf_path),
                        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"
                    )

                    results.append(self._paper_to_dict(paper))

        except Exception as e:
            await progress_queue.put({
                'type': 'log',
                'source': 'pubmed',
                'content': f'❌ PubMed 检索出错: {str(e)}\n',
                'newline': True
            })

        return results

    async def _fetch_europepmc_papers(
            self,
            query: str,
            limit: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """检索Europe PMC（持续检索直到满足数量）"""
        results = []

        try:
            records = await search_europe_pmc(query, limit=limit * 5)

            if not records:
                await progress_queue.put({
                    'type': 'log',
                    'source': 'europepmc',
                    'content': '⚠️ Europe PMC 未找到相关文献\n',
                    'newline': True
                })
                return results

            # 处理记录
            async with get_db_session() as db:
                for record in records:
                    if len(results) >= limit:
                        break

                    pmid = record.get("pmid")
                    pmcid = record.get("pmcid")
                    has_pdf = record.get("hasPDF")

                    if has_pdf == 'N':
                        continue

                    # 检查是否已存在
                    if pmid:
                        result = await db.execute(
                            select(Paper).where(
                                Paper.pmid == pmid,
                                Paper.source_type == 'europepmc'
                            )
                        )
                    elif pmcid:
                        result = await db.execute(
                            select(Paper).where(
                                Paper.pmcid == pmcid,
                                Paper.source_type == 'europepmc'
                            )
                        )
                    else:
                        continue

                    existing = result.scalar_one_or_none()

                    if existing:
                        results.append(self._paper_to_dict(existing))
                        continue

                    title = record.get("title")
                    await progress_queue.put({
                        'type': 'log',
                        'source': 'europepmc',
                        'content': f'  📄 处理 {pmcid or pmid}...',
                        'newline': False
                    })

                    # 下载PDF
                    from pathlib import Path
                    import requests

                    pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render" if pmcid else None

                    if not pdf_url:
                        await progress_queue.put({
                            'type': 'log',
                            'source': 'europepmc',
                            'content': ' ⚠️ 无PDF\n',
                            'newline': True
                        })
                        continue

                    filename = f"europepmc_{pmcid or pmid}.pdf"
                    pdf_path = Path(settings.pdf_dir) / filename

                    loop = asyncio.get_running_loop()

                    def download_pdf():
                        try:
                            r = requests.get(pdf_url, timeout=60)
                            if r.status_code == 200 and "pdf" in r.headers.get("content-type", "").lower():
                                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(pdf_path, "wb") as f:
                                    f.write(r.content)
                                return True
                        except:
                            pass
                        return False

                    download_success = await loop.run_in_executor(
                        self.executor,
                        download_pdf
                    )

                    if not download_success:
                        await progress_queue.put({
                            'type': 'log',
                            'source': 'europepmc',
                            'content': ' ❌\n',
                            'newline': True
                        })
                        continue

                    await progress_queue.put({
                        'type': 'log',
                        'source': 'europepmc',
                        'content': ' ✅\n',
                        'newline': True
                    })

                    # 保存到数据库
                    paper = await upsert_paper(
                        db,
                        pmid=pmid,
                        pmcid=pmcid,
                        title=title,
                        source_type='europepmc',
                        abstract='',
                        pub_date=record.get("pubYear"),
                        authors=record.get("authorString"),
                        pdf_path=str(pdf_path),
                        source_url=f"https://europepmc.org/article/MED/{pmid}" if pmid else f"https://europepmc.org/articles/{pmcid}"
                    )

                    results.append(self._paper_to_dict(paper))

        except Exception as e:
            await progress_queue.put({
                'type': 'log',
                'source': 'europepmc',
                'content': f'❌ Europe PMC 检索出错: {str(e)}\n',
                'newline': True
            })

        return results

    async def search_trials_with_ranking(
            self,
            keywords: str,
            target_count: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """
        检索并排序临床试验

        Args:
            keywords: 关键词
            target_count: 目标试验数量
            progress_queue: 进度队列

        Returns:
            排序后的试验列表
        """
        all_trials = []

        await progress_queue.put({
            'type': 'log',
            'source': 'clinical_trials',
            'content': f'\n🔍 开始检索临床试验: {keywords}\n',
            'newline': True
        })

        # 1. 先查数据库缓存
        async with get_db_session() as db:
            keyword_list = [kw.strip() for kw in keywords.split(',') if kw.strip()]
            if keyword_list:
                query_filter = select(ClinicalTrial).where(
                    or_(*[ClinicalTrial.conditions.ilike(f"%{kw}%") for kw in keyword_list])
                ).limit(target_count * 3)

                result = await db.execute(query_filter)
                cached = result.scalars().all()

                if cached:
                    await progress_queue.put({
                        'type': 'log',
                        'source': 'clinical_trials',
                        'content': f'📚 数据库中找到 {len(cached)} 个已缓存试验\n',
                        'newline': True
                    })

                    for trial in cached:
                        all_trials.append(self._trial_to_dict(trial))

        # 2. 如果缓存不足，执行检索（检索3倍数量）
        if len(all_trials) < target_count * 3:
            remaining = target_count * 3 - len(all_trials)

            try:
                keyword_list = [kw.strip() for kw in keywords.split(',')]
                trials, _ = await async_search_trials(
                    keyword_list,
                    logic="OR",
                    size=remaining * 2
                )

                # 保存到数据库
                async with get_db_session() as db:
                    for trial in trials:
                        nct_id = trial["nct_id"]

                        # 检查是否已存在
                        result = await db.execute(
                            select(ClinicalTrial).where(ClinicalTrial.nct_id == nct_id)
                        )
                        existing = result.scalar_one_or_none()

                        if existing:
                            all_trials.append(self._trial_to_dict(existing))
                            continue

                        await progress_queue.put({
                            'type': 'log',
                            'source': 'clinical_trials',
                            'content': f'  💊 保存 {nct_id}\n',
                            'newline': True
                        })

                        # 保存到数据库
                        saved_trial = await upsert_clinical_trial(
                            db,
                            nct_id=trial["nct_id"],
                            title=trial["title"],
                            official_title=trial.get("official_title"),
                            status=trial.get("status"),
                            start_date=trial.get("start_date"),
                            completion_date=trial.get("completion_date"),
                            study_type=trial.get("study_type"),
                            phase=trial.get("phase"),
                            allocation=trial.get("allocation"),
                            intervention_model=trial.get("intervention_model"),
                            conditions=trial.get("conditions"),
                            sponsor=trial.get("sponsor"),
                            locations=trial.get("locations"),
                            source_url=trial.get("source_url"),
                        )

                        all_trials.append(trial)

            except Exception as e:
                await progress_queue.put({
                    'type': 'log',
                    'source': 'clinical_trials',
                    'content': f'❌ 检索出错: {str(e)}\n',
                    'newline': True
                })

        # 3. 计算相关度并排序
        for trial in all_trials:
            title_score = self._calculate_relevance(keywords, trial.get('title', ''))
            condition_score = self._calculate_relevance(keywords, trial.get('conditions', ''))
            trial['relevance_score'] = (title_score * 0.5 + condition_score * 0.5)

        all_trials.sort(key=lambda t: t.get('relevance_score', 0), reverse=True)

        # 4. 返回前N个
        selected_trials = all_trials[:target_count]

        await progress_queue.put({
            'type': 'result',
            'source': 'clinical_trials',
            'content': f'✅ 筛选出最相关的 {len(selected_trials)} 个临床试验',
            'data': {
                'count': len(selected_trials),
                'trials': selected_trials
            }
        })

        return selected_trials

    def _paper_to_dict(self, paper: Paper) -> Dict:
        """Paper 模型转字典"""
        return {
            'id': paper.id,
            'pmid': paper.pmid,
            'pmcid': paper.pmcid,
            'title': paper.title,
            'abstract': paper.abstract,
            'pub_date': paper.pub_date,
            'authors': paper.authors,
            'pdf_path': paper.pdf_path,
            'source_url': paper.source_url,
            'source_type': paper.source_type
        }

    def _trial_to_dict(self, trial: ClinicalTrial) -> Dict:
        """ClinicalTrial 模型转字典"""
        return {
            'nct_id': trial.nct_id,
            'title': trial.title,
            'official_title': trial.official_title,
            'status': trial.status,
            'phase': trial.phase,
            'study_type': trial.study_type,
            'conditions': trial.conditions,
            'sponsor': trial.sponsor,
            'locations': trial.locations,
            'source_url': trial.source_url
        }

    def __del__(self):
        """清理线程池"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)


# 全局实例
optimized_search_service = OptimizedSearchService()