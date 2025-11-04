import hashlib
import json
from sqlalchemy import select

from app.db.database import get_db_session
from app.models import SearchCache, Paper

class SearchService:
    """检索服务（带数据库缓存）"""

    @staticmethod
    def _compute_hash(query: str) -> str:
        """计算查询的哈希值"""
        return hashlib.md5(query.encode('utf-8')).hexdigest()

    async def search_pubmed(self, query: str) -> list[dict]:
        """
        检索 PubMed（带缓存）
        1. 先查缓存
        2. 如果没有，调用 API 并缓存
        3. 返回 Paper 列表
        """
        query_hash = self._compute_hash(f"pubmed:{query}")

        # 查询缓存
        async with get_db_session() as db:
            result = await db.execute(
                select(SearchCache).where(SearchCache.query_hash == query_hash)
            )
            cache = result.scalar_one_or_none()

            if cache:
                # 命中缓存，增加计数
                cache.hit_count += 1
                await db.commit()

                # 从缓存返回
                cached_pmids = json.loads(cache.results_json)

                # 从 Paper 表获取详细信息
                papers_result = await db.execute(
                    select(Paper).where(Paper.pmid.in_(cached_pmids))
                )
                papers = papers_result.scalars().all()

                return [self._paper_to_dict(p) for p in papers]

        # 缓存未命中，调用真实 API
        papers = await self._fetch_from_pubmed_api(query)

        # 保存到数据库
        async with get_db_session() as db:
            paper_ids = []
            for paper_data in papers:
                # 检查是否已存在
                existing = await db.execute(
                    select(Paper).where(Paper.pmid == paper_data['pmid'])
                )
                paper = existing.scalar_one_or_none()

                if not paper:
                    # 新增 Paper
                    paper = Paper(**paper_data)
                    db.add(paper)
                    await db.flush()

                paper_ids.append(paper.pmid)

            # 保存缓存记录
            cache = SearchCache(
                query_type='pubmed',
                query_text=query,
                query_hash=query_hash,
                results_json=json.dumps(paper_ids)
            )
            db.add(cache)
            await db.commit()

        return papers

    async def _fetch_from_pubmed_api(self, query: str) -> list[dict]:
        """调用真实的 PubMed API（待实现）"""
        # TODO: 实现真实的 PubMed API 调用
        # 示例返回格式
        return [
            {
                'pmid': '12345678',
                'pmcid': 'PMC1234567',
                'title': 'EGFR-TKI in Advanced NSCLC',
                'source_type': 'pubmed',
                'abstract': 'This study evaluated...',
                'pub_date': '2023-05',
                'authors': 'Zhang Y, Li H',
                'pdf_path': '/papers/12345678.pdf',
                'source_url': 'https://pubmed.ncbi.nlm.nih.gov/12345678/'
            }
        ]

    async def search_clinical_trials(self, keywords: str) -> list[dict]:
        """检索临床试验（带缓存）"""
        query_hash = self._compute_hash(f"clinical_trial:{keywords}")

        # 查询缓存
        async with get_db_session() as db:
            result = await db.execute(
                select(SearchCache).where(SearchCache.query_hash == query_hash)
            )
            cache = result.scalar_one_or_none()

            if cache:
                cache.hit_count += 1
                await db.commit()
                return json.loads(cache.results_json)

        # 调用真实 API
        trials = await self._fetch_from_clinical_trials_api(keywords)

        # 保存缓存
        async with get_db_session() as db:
            cache = SearchCache(
                query_type='clinical_trial',
                query_text=keywords,
                query_hash=query_hash,
                results_json=json.dumps(trials)
            )
            db.add(cache)
            await db.commit()

        return trials

    async def _fetch_from_clinical_trials_api(self, keywords: str) -> list[dict]:
        """调用真实的 ClinicalTrials.gov API（待实现）"""
        # TODO: 实现真实的 API 调用
        return []

    @staticmethod
    def _paper_to_dict(paper: Paper) -> dict:
        """Paper 模型转字典"""
        return {
            'pmid': paper.pmid,
            'pmcid': paper.pmcid,
            'title': paper.title,
            'abstract': paper.abstract,
            'pub_date': paper.pub_date,
            'authors': paper.authors,
            'pdf_path': paper.pdf_path,
            'source_url': paper.source_url
        }

search_service = SearchService()