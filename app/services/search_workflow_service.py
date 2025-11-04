"""
多源检索工作流服务
"""
import asyncio
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select, or_, and_

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
        """同步回调，在线程池中安全调用"""
        asyncio.run_coroutine_threadsafe(
            self.queue.put({
                'type': 'log',
                'source': self.source,
                'content': message,
                'newline': newline
            }),
            self.loop
        )


class MultiSourceSearchService:
    """多源检索服务 - 封装原有客户端"""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)

    async def search_pubmed_with_cache(
            self,
            query: str,
            limit: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """
        检索 PubMed（优先使用缓存）
        返回: 文献列表
        """
        results = []

        await progress_queue.put({
            'type': 'log',
            'source': 'pubmed',
            'content': f'🔍 开始检索 PubMed: {query}\n',
            'newline': True
        })

        # 1. 先查数据库缓存
        async with get_db_session() as db:
            search_terms = query.replace('AND', '').replace('OR', '').split()[:3]
            if search_terms:
                query_filter = select(Paper).where(
                    and_(
                        Paper.source_type == 'pubmed',
                        or_(*[Paper.title.ilike(f"%{term}%") for term in search_terms])
                    )
                ).limit(limit)

                result = await db.execute(query_filter)
                cached_papers = result.scalars().all()

                if cached_papers:
                    await progress_queue.put({
                        'type': 'log',
                        'source': 'pubmed',
                        'content': f'✅ 数据库中找到 {len(cached_papers)} 篇已缓存文献\n',
                        'newline': True
                    })

                    for paper in cached_papers:
                        results.append(self._paper_to_dict(paper))

        # 2. 如果缓存不足，执行真实检索
        if len(results) < limit:
            remaining = limit - len(results)
            await progress_queue.put({
                'type': 'log',
                'source': 'pubmed',
                'content': f'📥 需要下载 {remaining} 篇新文献\n',
                'newline': True
            })

            new_papers = await self._fetch_new_pubmed_papers(
                query, remaining, progress_queue
            )
            results.extend(new_papers)

        await progress_queue.put({
            'type': 'result',
            'source': 'pubmed',
            'content': f'✅ PubMed 检索完成，共 {len(results)} 篇文献',
            'data': {
                'count': len(results),
                'papers': results
            }
        })

        return results

    async def _fetch_new_pubmed_papers(
            self,
            query: str,
            limit: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """执行真实的 PubMed 检索和下载"""
        results = []

        try:
            # 搜索 PMID
            pmids = await esearch_pmids(query, retmax=limit * 5)

            if not pmids:
                await progress_queue.put({
                    'type': 'log',
                    'source': 'pubmed',
                    'content': '⚠️ 未找到相关文献\n',
                    'newline': True
                })
                return results

            await progress_queue.put({
                'type': 'log',
                'source': 'pubmed',
                'content': f'找到 {len(pmids)} 个 PMID\n',
                'newline': True
            })

            # 获取元数据
            meta = await efetch_metadata(pmids)

            # 下载 PDF 并保存
            success_count = 0
            async with get_db_session() as db:
                for pid in pmids:
                    if success_count >= limit:
                        break

                    # 检查是否已存在
                    result = await db.execute(
                        select(Paper).where(
                            Paper.pmid == pid,
                            Paper.source_type == 'pubmed'
                        )
                    )
                    if result.scalar_one_or_none():
                        await progress_queue.put({
                            'type': 'log',
                            'source': 'pubmed',
                            'content': f'  ✓ PMID {pid} 已存在，跳过\n',
                            'newline': True
                        })
                        continue

                    await progress_queue.put({
                        'type': 'log',
                        'source': 'pubmed',
                        'content': f'  📄 处理 PMID {pid}...',
                        'newline': False
                    })

                    m = meta.get(pid, {})

                    # 创建进度回调
                    progress = SearchProgress(progress_queue, 'pubmed')

                    # 下载 PDF
                    pdf_path = await get_pdf_from_pubmed(
                        pid,
                        m.get("pmcid"),
                        self.executor,
                        progress.callback
                    )

                    if not pdf_path:
                        await progress_queue.put({
                            'type': 'log',
                            'source': 'pubmed',
                            'content': ' ❌\n',
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
                    success_count += 1

        except Exception as e:
            await progress_queue.put({
                'type': 'log',
                'source': 'pubmed',
                'content': f'❌ 检索出错: {str(e)}\n',
                'newline': True
            })

        return results

    async def search_europepmc_with_cache(
            self,
            query: str,
            limit: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """检索 Europe PMC（优先使用缓存）"""
        results = []

        await progress_queue.put({
            'type': 'log',
            'source': 'europepmc',
            'content': f'🔍 开始检索 Europe PMC: {query}\n',
            'newline': True
        })

        # 1. 先查数据库缓存
        async with get_db_session() as db:
            search_terms = query.replace('AND', '').replace('OR', '').split()[:3]
            if search_terms:
                query_filter = select(Paper).where(
                    and_(
                        Paper.source_type == 'europepmc',
                        or_(*[Paper.title.ilike(f"%{term}%") for term in search_terms])
                    )
                ).limit(limit)

                result = await db.execute(query_filter)
                cached_papers = result.scalars().all()

                if cached_papers:
                    await progress_queue.put({
                        'type': 'log',
                        'source': 'europepmc',
                        'content': f'✅ 数据库中找到 {len(cached_papers)} 篇已缓存文献\n',
                        'newline': True
                    })

                    for paper in cached_papers:
                        results.append(self._paper_to_dict(paper))

        # 2. 如果缓存不足，执行真实检索
        if len(results) < limit:
            remaining = limit - len(results)
            await progress_queue.put({
                'type': 'log',
                'source': 'europepmc',
                'content': f'📥 需要下载 {remaining} 篇新文献\n',
                'newline': True
            })

            new_papers = await self._fetch_new_europepmc_papers(
                query, remaining, progress_queue
            )
            results.extend(new_papers)

        await progress_queue.put({
            'type': 'result',
            'source': 'europepmc',
            'content': f'✅ Europe PMC 检索完成，共 {len(results)} 篇文献',
            'data': {
                'count': len(results),
                'papers': results
            }
        })

        return results

    async def _fetch_new_europepmc_papers(
            self,
            query: str,
            limit: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """执行真实的 Europe PMC 检索"""
        results = []

        try:
            # 搜索记录（使用原有客户端）
            records = await search_europe_pmc(query, limit=limit * 3)

            if not records:
                await progress_queue.put({
                    'type': 'log',
                    'source': 'europepmc',
                    'content': '⚠️ 未找到相关文献\n',
                    'newline': True
                })
                return results

            await progress_queue.put({
                'type': 'log',
                'source': 'europepmc',
                'content': f'找到 {len(records)} 条记录\n',
                'newline': True
            })

            # 处理记录（封装版本，不调用原有的 process_records_and_save_to_db）
            success_count = 0
            async with get_db_session() as db:
                for record in records:
                    if success_count >= limit:
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

                    if result.scalar_one_or_none():
                        await progress_queue.put({
                            'type': 'log',
                            'source': 'europepmc',
                            'content': f'  ✓ {pmid or pmcid} 已存在，跳过\n',
                            'newline': True
                        })
                        continue

                    title = record.get("title")
                    await progress_queue.put({
                        'type': 'log',
                        'source': 'europepmc',
                        'content': f'  📄 处理 {pmid or pmcid}: {title[:50]}...',
                        'newline': False
                    })

                    # 获取 PDF URL
                    pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render" if pmcid else None

                    if not pdf_url:
                        await progress_queue.put({
                            'type': 'log',
                            'source': 'europepmc',
                            'content': ' ⚠️ 无PDF\n',
                            'newline': True
                        })
                        continue

                    # 下载 PDF（使用线程池）
                    from pathlib import Path
                    import requests

                    filename = f"europepmc_{pmcid or pmid}.pdf"
                    pdf_path = Path(settings.pdf_dir) / filename

                    loop = asyncio.get_running_loop()

                    def download_pdf():
                        try:
                            r = requests.get(pdf_url, timeout=20)
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
                    success_count += 1

        except Exception as e:
            await progress_queue.put({
                'type': 'log',
                'source': 'europepmc',
                'content': f'❌ 检索出错: {str(e)}\n',
                'newline': True
            })

        return results

    async def search_clinical_trials_with_cache(
            self,
            keywords: str,
            limit: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """检索临床试验（优先使用缓存）"""
        results = []

        await progress_queue.put({
            'type': 'log',
            'source': 'clinical_trials',
            'content': f'🔍 开始检索临床试验: {keywords}\n',
            'newline': True
        })

        # 1. 先查数据库缓存
        async with get_db_session() as db:
            keyword_list = [kw.strip() for kw in keywords.split(',')]
            if keyword_list:
                query_filter = select(ClinicalTrial).where(
                    or_(*[ClinicalTrial.conditions.ilike(f"%{kw}%") for kw in keyword_list])
                ).limit(limit)

                result = await db.execute(query_filter)
                cached_trials = result.scalars().all()

                if cached_trials:
                    await progress_queue.put({
                        'type': 'log',
                        'source': 'clinical_trials',
                        'content': f'✅ 数据库中找到 {len(cached_trials)} 个已缓存试验\n',
                        'newline': True
                    })

                    for trial in cached_trials:
                        results.append(self._trial_to_dict(trial))

        # 2. 如果缓存不足，执行真实检索
        if len(results) < limit:
            remaining = limit - len(results)
            await progress_queue.put({
                'type': 'log',
                'source': 'clinical_trials',
                'content': f'📥 需要检索 {remaining} 个新试验\n',
                'newline': True
            })

            new_trials = await self._fetch_new_clinical_trials(
                keywords, remaining, progress_queue
            )
            results.extend(new_trials)

        await progress_queue.put({
            'type': 'result',
            'source': 'clinical_trials',
            'content': f'✅ 临床试验检索完成，共 {len(results)} 个试验',
            'data': {
                'count': len(results),
                'trials': results
            }
        })

        return results

    async def _fetch_new_clinical_trials(
            self,
            keywords: str,
            limit: int,
            progress_queue: asyncio.Queue
    ) -> List[Dict]:
        """执行真实的临床试验检索"""
        results = []

        try:
            # 调用原有客户端
            keyword_list = [kw.strip() for kw in keywords.split(',')]
            trials, _ = await async_search_trials(
                keyword_list,
                logic="OR",
                size=limit * 2
            )

            if not trials:
                await progress_queue.put({
                    'type': 'log',
                    'source': 'clinical_trials',
                    'content': '⚠️ 未找到相关试验\n',
                    'newline': True
                })
                return results

            await progress_queue.put({
                'type': 'log',
                'source': 'clinical_trials',
                'content': f'找到 {len(trials)} 个试验\n',
                'newline': True
            })

            # 保存到数据库
            success_count = 0
            async with get_db_session() as db:
                for trial in trials:
                    if success_count >= limit:
                        break

                    nct_id = trial["nct_id"]

                    # 检查是否已存在
                    result = await db.execute(
                        select(ClinicalTrial).where(ClinicalTrial.nct_id == nct_id)
                    )
                    if result.scalar_one_or_none():
                        await progress_queue.put({
                            'type': 'log',
                            'source': 'clinical_trials',
                            'content': f'  ✓ {nct_id} 已存在，跳过\n',
                            'newline': True
                        })
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

                    results.append(trial)
                    success_count += 1

        except Exception as e:
            await progress_queue.put({
                'type': 'log',
                'source': 'clinical_trials',
                'content': f'❌ 检索出错: {str(e)}\n',
                'newline': True
            })

        return results

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
search_service = MultiSourceSearchService()