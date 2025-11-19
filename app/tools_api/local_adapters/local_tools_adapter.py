from __future__ import annotations
import asyncio
import time
import hashlib
from typing import AsyncGenerator, List, Optional, Coroutine, Dict

from app.services.search_service import SearchService
from app.services.llm_service import llm_service
from app.prompts.workflow_prompts import WorkflowPrompts
from app.core.config import settings
from app.core.logger import get_logger

from ..facade import ToolsFacade
from ..models import (
    PapersResult,
    TrialsResult,
    DownloadResult,
    AnalysisResult,
    SummaryResult,
    ReportResult,
    Paper,
    Trial,
    Meta,
)


class LocalToolsAdapter(ToolsFacade):
    """
    本地适配器：复用项目内 services 与 prompts，实现 Facade 接口。
    提供所有工具方法的本地实现，可作为 MCP 适配器的备选方案。
    """

    def __init__(self):
        self._search_service = SearchService()
        self._logger = get_logger(__name__)

    def _args_digest(self, *parts: str) -> str:
        h = hashlib.sha256()
        for p in parts:
            h.update((p or "").encode("utf-8"))
        return h.hexdigest()[:12]

    # ===================== 检索 =====================
    async def search_papers(self, query: str, size: int, sources: List[str] | None = None) -> PapersResult:
        _t0 = time.time()
        _tool = "search_papers"
        _digest = self._args_digest(query, str(size))
        q: asyncio.Queue = asyncio.Queue()
        normalized_sources = {s.lower() for s in (sources or []) if s}
        if not normalized_sources:
            normalized_sources = {"pubmed", "europepmc"}
        valid_sources = {"pubmed", "europepmc"}
        if not (normalized_sources & valid_sources):
            normalized_sources = {"pubmed", "europepmc"}
        papers_pubmed: List[Dict] = []
        papers_europepmc: List[Dict] = []
        if "pubmed" in normalized_sources:
            papers_pubmed = await self._search_service._fetch_pubmed_papers(query, size, q)
        if "europepmc" in normalized_sources:
            papers_europepmc = await self._search_service._fetch_europepmc_papers(query, size, q)
        all_papers = []
        if isinstance(papers_pubmed, list):
            all_papers.extend(papers_pubmed)
        if isinstance(papers_europepmc, list):
            all_papers.extend(papers_europepmc)
        all_papers = self._search_service._deduplicate_papers(all_papers)
        for p in all_papers:
            title_score = self._search_service._calculate_relevance(query, p.get('title', ''))
            abstract_score = self._search_service._calculate_relevance(query, p.get('abstract', ''))
            p['relevance_score'] = (title_score * 0.7 + abstract_score * 0.3)
        all_papers.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        selected = all_papers[:size]
        took = int((time.time() - _t0) * 1000)
        self._logger.info("tool_call tool=%s args_digest=%s took_ms=%d count=%d", _tool, _digest, took, len(selected))
        return PapersResult(papers=[
            Paper(
                id=p.get('id'),
                pmid=p.get('pmid'),
                pmcid=p.get('pmcid'),
                title=p.get('title', ''),
                abstract=p.get('abstract'),
                pub_date=p.get('pub_date'),
                authors=p.get('authors'),
                pdf_path=p.get('pdf_path'),
                source_url=p.get('source_url'),
                source_type=p.get('source_type'),
            ) for p in selected
        ], meta=Meta())

    async def search_trials(self, keywords: str, size: int) -> TrialsResult:
        _t0 = time.time(); _tool = "search_trials"; _digest = self._args_digest(keywords, str(size))
        q: asyncio.Queue = asyncio.Queue()
        trials = await self._search_service.search_trials_with_ranking(
            keywords,
            size,
            q,
        )
        took = int((time.time() - _t0) * 1000)
        self._logger.info("tool_call tool=%s args_digest=%s took_ms=%d count=%d", _tool, _digest, took, len(trials))
        return TrialsResult(trials=[
            Trial(
                nct_id=t.get("nct_id", ""),
                title=t.get("title", ""),
                status=t.get("status"),
                phase=t.get("phase"),
                conditions=t.get("conditions"),
                sponsor=t.get("sponsor"),
                locations=t.get("locations"),
                source_url=t.get("source_url"),
            ) for t in trials
        ], meta=Meta())

    # ===================== 下载/解压 =====================
    async def download_pdf(self, url: str, filename: str) -> DownloadResult:
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from app.tools.download_utils import download_pdf_sync

        _t0 = time.time(); _tool = "download_pdf"; _digest = self._args_digest(url, filename)

        def _progress(msg: str, ok: bool):
            # 仅做精简日志，避免刷屏
            if ok:
                if any(k in msg for k in ["成功", "已下载", "开始下载", "发现PDF", "下载成功"]):
                    self._logger.info("tool_progress tool=%s args_digest=%s msg=%s", _tool, _digest, msg)
            else:
                self._logger.warning("tool_progress tool=%s args_digest=%s msg=%s", _tool, _digest, msg)

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            path = await loop.run_in_executor(ex, download_pdf_sync, url, filename, _progress)

        if path is None:
            took = int((time.time() - _t0) * 1000)
            self._logger.error("tool_call tool=%s args_digest=%s took_ms=%d error=download_failed", _tool, _digest, took)
            raise RuntimeError("download failed")

        p = Path(path)
        size = p.stat().st_size if p.exists() else None
        took = int((time.time() - _t0) * 1000)
        self._logger.info("tool_call tool=%s args_digest=%s took_ms=%d bytes=%s", _tool, _digest, took, size)
        return DownloadResult(path=str(p), bytes=size, meta=Meta(took_ms=took))

    async def extract_tgz(self, url: str, filename: str) -> DownloadResult:
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from app.tools.download_utils import download_pdf_from_tgz_sync

        _t0 = time.time(); _tool = "extract_tgz"; _digest = self._args_digest(url, filename)

        def _progress(msg: str, ok: bool):
            if ok:
                if any(k in msg for k in ["成功", "已下载", "开始下载", "开始", "提取", "PDF"]):
                    self._logger.info("tool_progress tool=%s args_digest=%s msg=%s", _tool, _digest, msg)
            else:
                self._logger.warning("tool_progress tool=%s args_digest=%s msg=%s", _tool, _digest, msg)

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            path = await loop.run_in_executor(ex, download_pdf_from_tgz_sync, url, filename, _progress)

        if path is None:
            took = int((time.time() - _t0) * 1000)
            self._logger.error("tool_call tool=%s args_digest=%s took_ms=%d error=extract_failed", _tool, _digest, took)
            raise RuntimeError("extract failed")

        p = Path(path)
        size = p.stat().st_size if p.exists() else None
        took = int((time.time() - _t0) * 1000)
        self._logger.info("tool_call tool=%s args_digest=%s took_ms=%d bytes=%s", _tool, _digest, took, size)
        return DownloadResult(path=str(p), bytes=size, meta=Meta(took_ms=took))

    # ===================== 文献与试验分析 =====================
    async def analyze_pdf_stream(self, patient_features: str, user_query: str, pdf_path: str) -> AsyncGenerator[str, None]:
        # 延迟导入，避免循环依赖
        from app.services.file_service import file_service

        # 构造与现有工作流一致的提示
        paper_stub = {"title": "", "pdf_path": pdf_path}
        prompt = WorkflowPrompts.analyze_paper(
            patient_features=patient_features,
            user_query=user_query,
            paper=paper_stub,
        )

        # 上传或获取文件ID，然后复用 llm_service 的统一接口进行流式分析
        _t0 = time.time(); _tool = "analyze_pdf_stream"; _digest = self._args_digest(user_query[:64], pdf_path)
        file_id = await file_service.get_or_upload_file(pdf_path)
        async for token in llm_service.chat_with_context(
            user_query=prompt,
            file_ids=[file_id] if file_id else None,
            system_prompt="你是一个专业的医疗文献分析助手。请仔细阅读PDF文档，按照指定格式输出结构化分析。",
            model=settings.qwen_long_model,
        ):
            if token:
                yield token
        took = int((time.time() - _t0) * 1000)
        self._logger.info("tool_call tool=%s args_digest=%s took_ms=%d", _tool, _digest, took)

    async def summarize_papers(self, analyses: List[dict]) -> SummaryResult:
        _t0 = time.time(); _tool = "summarize_papers"; _digest = self._args_digest(str(len(analyses)))
        parts: List[str] = []
        for i, a in enumerate(analyses):
            title = (a.get('paper') or {}).get('title', f'文献 {i+1}')
            text = a.get('analysis') or ''
            parts.append(f"### {title}\n{text}")
        prompt = f"请综合以下文献分析，输出200-400字的要点总结：\n\n" + "\n\n".join(parts)
        summary = ""
        async for token in llm_service.chat_with_context(
            user_query=prompt,
            system_prompt="你是一个专业的医疗文献总结助手。",
            model=settings.qwen_long_model,
        ):
            if token:
                summary += token
        took = int((time.time() - _t0) * 1000)
        self._logger.info("tool_call tool=%s args_digest=%s took_ms=%d", _tool, _digest, took)
        return SummaryResult(summary=summary, meta=Meta())

    async def analyze_trials_stream(self, patient_features: str, trials: List[Trial]) -> AsyncGenerator[str, None]:
        # 组装 trials 文本，与现有 workflow 保持一致
        trials_text_parts: List[str] = []
        for i, t in enumerate(trials):
            trials_text_parts.append(
                f"""### 试验 {i+1}: {t.title}
- **NCT ID**: {t.nct_id}
- **状态**: {t.status or ''}
- **阶段**: {t.phase or ''}
- **疾病**: {t.conditions or ''}
- **赞助方**: {t.sponsor or ''}
"""
            )
        prompt = WorkflowPrompts.analyze_trials(patient_features, "\n".join(trials_text_parts))

        # 复用 llm_service 流式接口与现有长文本模型
        _t0 = time.time(); _tool = "analyze_trials_stream"; _digest = self._args_digest(str(len(trials)))
        async for token in llm_service.chat_with_context(
            user_query=prompt,
            system_prompt="你是一个专业的临床试验分析助手。",
            model=settings.qwen_long_model,
        ):
            if token:
                yield token
        took = int((time.time() - _t0) * 1000)
        self._logger.info("tool_call tool=%s args_digest=%s took_ms=%d", _tool, _digest, took)
        return

    # ===================== 报告 =====================
    async def generate_report(self, user_query: str, patient_features: str, papers_summary: str, trial_analysis: str) -> ReportResult:
        _t0 = time.time(); _tool = "generate_report"; _digest = self._args_digest(user_query[:64])
        prompt = WorkflowPrompts.generate_final_report(
            user_query,
            patient_features,
            papers_summary or "暂无",
            trial_analysis or "暂无",
        )
        final = ""
        async for token in llm_service.chat_with_context(
            user_query=prompt,
            system_prompt="你是一个专业的医疗咨询报告生成助手。",
            model=settings.qwen_long_model,
        ):
            if token:
                final += token
        took = int((time.time() - _t0) * 1000)
        self._logger.info("tool_call tool=%s args_digest=%s took_ms=%d", _tool, _digest, took)
        return ReportResult(final_answer=final, meta=Meta())
