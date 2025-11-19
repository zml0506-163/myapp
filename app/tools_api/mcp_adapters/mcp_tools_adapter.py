from __future__ import annotations
import asyncio
from typing import AsyncGenerator, List

from app.tools_api.facade import ToolsFacade
from app.tools_api.models import (
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
from app.tools_api.local_adapters.local_tools_adapter import LocalToolsAdapter
from app.core.logger import get_logger
from app.core.config import settings
import requests
import json
import time


class McpToolsAdapter(ToolsFacade):
    """
    MCP 适配器（mock 实现）：
    - 当前阶段先委托给 LocalToolsAdapter，保证切换不影响功能与前端行为。
    - 后续接入 MCP 客户端后，在此替换为真实的远程调用。
    """

    def __init__(self):
        self._local = LocalToolsAdapter()
        self._logger = get_logger(__name__)
        self._wl = set((settings.mcp_tool_whitelist or []))
        self._verify_config()

    def _allowed(self, tool: str) -> bool:
        if not self._wl:
            return True
        return tool in self._wl

    def _map_error(self, resp: requests.Response | None, exc: Exception | None) -> str:
        try:
            status = resp.status_code if resp is not None else None
        except Exception:
            status = None
        if status == 429:
            return "rate_limited"
        if status and 400 <= status < 500:
            return "invalid_input"
        return "upstream_error"

    def _verify_config(self) -> None:
        try:
            if settings.mcp_enabled:
                if not settings.mcp_base_url:
                    self._logger.warning("mcp_enabled=true but MCP_BASE_URL is empty; adapter will fallback to local")
                if self._wl:
                    self._logger.info("mcp_tool_whitelist active: %s", ",".join(sorted(self._wl)))
                else:
                    self._logger.info("mcp_tool_whitelist not set; all tools allowed for MCP when enabled")
                if not getattr(settings, 'mcp_request_timeout_seconds', None):
                    self._logger.info("mcp_request_timeout_seconds not set; using default")
                if not getattr(settings, 'mcp_stream_timeout_seconds', None):
                    self._logger.info("mcp_stream_timeout_seconds not set; using default")
                if not settings.mcp_auth_token:
                    self._logger.info("MCP_AUTH_TOKEN not provided; continuing without auth header")
        except Exception:
            # 仅记录，不影响正常初始化
            pass

    # 检索
    async def search_papers(self, query: str, size: int, sources: List[str] | None = None) -> PapersResult:
        if settings.mcp_enabled and settings.mcp_base_url and self._allowed("search_papers"):
            try:
                url = settings.mcp_base_url.rstrip('/') + "/tools/search_papers"
                payload = {"query": query, "size": size, "sources": sources or []}
                t0 = time.time(); self._logger.info("mcp_http -> POST %s", url)
                headers = {}
                if settings.mcp_auth_token:
                    headers[settings.mcp_auth_header] = f"Bearer {settings.mcp_auth_token}"
                resp = requests.post(url, json=payload, timeout=settings.mcp_request_timeout_seconds, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                papers = [
                    Paper(**p) for p in data.get("papers", [])
                ]
                took = int((time.time() - t0) * 1000)
                meta = data.get("meta") or {}
                meta.setdefault("took_ms", took)
                return PapersResult(papers=papers, meta=Meta(**meta))
            except Exception as e:
                code = self._map_error(locals().get('resp', None), e)
                self._logger.warning("mcp_http search_papers fallback local error_code=%s err=%s", code, str(e))
        self._logger.info("mcp_adapter -> search_papers delegate to local")
        return await self._local.search_papers(query, size, sources)

    async def search_trials(self, keywords: str, size: int) -> TrialsResult:
        if settings.mcp_enabled and settings.mcp_base_url and self._allowed("search_trials"):
            try:
                url = settings.mcp_base_url.rstrip('/') + "/tools/search_trials"
                payload = {"keywords": keywords, "size": size}
                t0 = time.time(); self._logger.info("mcp_http -> POST %s", url)
                headers = {}
                if settings.mcp_auth_token:
                    headers[settings.mcp_auth_header] = f"Bearer {settings.mcp_auth_token}"
                resp = requests.post(url, json=payload, timeout=settings.mcp_request_timeout_seconds, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                trials = [
                    Trial(**t) for t in data.get("trials", [])
                ]
                took = int((time.time() - t0) * 1000)
                meta = data.get("meta") or {}
                meta.setdefault("took_ms", took)
                return TrialsResult(trials=trials, meta=Meta(**meta))
            except Exception as e:
                code = self._map_error(locals().get('resp', None), e)
                self._logger.warning("mcp_http search_trials fallback local error_code=%s err=%s", code, str(e))
        self._logger.info("mcp_adapter -> search_trials delegate to local")
        return await self._local.search_trials(keywords, size)

    # 下载/解压
    async def download_pdf(self, url: str, filename: str) -> DownloadResult:
        if settings.mcp_enabled and settings.mcp_base_url and self._allowed("download_pdf"):
            resp = None
            try:
                endpoint = settings.mcp_base_url.rstrip('/') + "/tools/download_pdf"
                payload = {"url": url, "filename": filename}
                t0 = time.time(); self._logger.info("mcp_http -> POST %s", endpoint)
                headers = {}
                if settings.mcp_auth_token:
                    headers[settings.mcp_auth_header] = f"Bearer {settings.mcp_auth_token}"
                resp = requests.post(endpoint, json=payload, timeout=settings.mcp_request_timeout_seconds, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                took = int((time.time() - t0) * 1000)
                meta = data.get("meta") or {}
                meta.setdefault("took_ms", took)
                return DownloadResult(path=data.get("path", ""), bytes=data.get("bytes", 0), meta=Meta(**meta))
            except Exception as e:
                code = self._map_error(resp, e)
                self._logger.warning("mcp_http download_pdf fallback local error_code=%s err=%s", code, str(e))
        self._logger.info("mcp_adapter -> download_pdf delegate to local")
        return await self._local.download_pdf(url, filename)

    async def extract_tgz(self, url: str, filename: str) -> DownloadResult:
        if settings.mcp_enabled and settings.mcp_base_url and self._allowed("extract_tgz"):
            resp = None
            try:
                endpoint = settings.mcp_base_url.rstrip('/') + "/tools/extract_tgz"
                payload = {"url": url, "filename": filename}
                t0 = time.time(); self._logger.info("mcp_http -> POST %s", endpoint)
                headers = {}
                if settings.mcp_auth_token:
                    headers[settings.mcp_auth_header] = f"Bearer {settings.mcp_auth_token}"
                resp = requests.post(endpoint, json=payload, timeout=settings.mcp_request_timeout_seconds, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                took = int((time.time() - t0) * 1000)
                meta = data.get("meta") or {}
                meta.setdefault("took_ms", took)
                return DownloadResult(path=data.get("path", ""), bytes=data.get("bytes", 0), meta=Meta(**meta))
            except Exception as e:
                code = self._map_error(resp, e)
                self._logger.warning("mcp_http extract_tgz fallback local error_code=%s err=%s", code, str(e))
        self._logger.info("mcp_adapter -> extract_tgz delegate to local")
        return await self._local.extract_tgz(url, filename)

    # 分析（流式）
    async def analyze_pdf_stream(self, patient_features: str, user_query: str, pdf_path: str) -> AsyncGenerator[str, None]:  # type: ignore
        """
        文献 PDF 分析（流式逐 token）。
        - 输出：逐字 token（不含额外包装），前端沿用现有 SSE 处理。
        - 失败时应无缝回退本地实现，保证流不中断。
        - 日志键与错误码映射同约定。
        """
        async for token in self._analyze_pdf_stream_impl(patient_features, user_query, pdf_path):
            yield token

    async def _analyze_pdf_stream_impl(self, patient_features: str, user_query: str, pdf_path: str) -> AsyncGenerator[str, None]:
        if settings.mcp_enabled and settings.mcp_base_url and self._allowed("analyze_pdf"):
            try:
                url = settings.mcp_base_url.rstrip('/') + "/tools/analyze_pdf"
                payload = {"patient_features": patient_features, "user_query": user_query, "pdf_path": pdf_path}
                t0 = time.time(); self._logger.info("mcp_http -> POST(stream) %s", url)
                headers = {}
                if settings.mcp_auth_token:
                    headers[settings.mcp_auth_header] = f"Bearer {settings.mcp_auth_token}"
                with requests.post(url, json=payload, timeout=settings.mcp_stream_timeout_seconds, stream=True, headers=headers) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=1024):
                        if not chunk:
                            continue
                        try:
                            text = chunk.decode('utf-8', errors='ignore')
                        except Exception:
                            text = chunk.decode('utf-8', errors='ignore')
                        if text:
                            yield text
                took = int((time.time() - t0) * 1000)
                self._logger.info("mcp_http analyze_pdf_stream done took_ms=%d", took)
                return
            except Exception as e:
                code = self._map_error(locals().get('resp', None), e)
                self._logger.warning("mcp_http analyze_pdf_stream fallback local error_code=%s err=%s", code, str(e))
        self._logger.info("mcp_adapter -> analyze_pdf_stream delegate to local")
        async for token in self._local.analyze_pdf_stream(patient_features, user_query, pdf_path):
            yield token

    async def summarize_papers(self, analyses: List[dict]) -> SummaryResult:
        if settings.mcp_enabled and settings.mcp_base_url and self._allowed("summarize_papers"):
            try:
                url = settings.mcp_base_url.rstrip('/') + "/tools/summarize_papers"
                payload = {"analyses": analyses}
                t0 = time.time(); self._logger.info("mcp_http -> POST %s", url)
                headers = {}
                if settings.mcp_auth_token:
                    headers[settings.mcp_auth_header] = f"Bearer {settings.mcp_auth_token}"
                resp = requests.post(url, json=payload, timeout=settings.mcp_request_timeout_seconds, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                took = int((time.time() - t0) * 1000)
                meta = data.get("meta") or {}
                meta.setdefault("took_ms", took)
                return SummaryResult(summary=data.get("summary", ""), meta=Meta(**meta))
            except Exception as e:
                code = self._map_error(locals().get('resp', None), e)
                self._logger.warning("mcp_http summarize_papers fallback local error_code=%s err=%s", code, str(e))
        self._logger.info("mcp_adapter -> summarize_papers delegate to local")
        return await self._local.summarize_papers(analyses)

    async def analyze_trials_stream(self, patient_features: str, trials: List[Trial]) -> AsyncGenerator[str, None]:  # type: ignore
        """
        临床试验分析（流式逐 token）。
        - 输出流与 analyze_pdf_stream 语义一致。
        - 失败时回退本地实现，SSE 不中断。
        """
        async for token in self._analyze_trials_stream_impl(patient_features, trials):
            yield token

    async def _analyze_trials_stream_impl(self, patient_features: str, trials: List[Trial]) -> AsyncGenerator[str, None]:
        if settings.mcp_enabled and settings.mcp_base_url and self._allowed("analyze_trials_stream"):
            try:
                url = settings.mcp_base_url.rstrip('/') + "/tools/analyze_trials_stream"
                payload = {
                    "patient_features": patient_features,
                    "trials": [t.dict() for t in trials],
                }
                t0 = time.time(); self._logger.info("mcp_http -> POST(stream) %s", url)
                headers = {}
                if settings.mcp_auth_token:
                    headers[settings.mcp_auth_header] = f"Bearer {settings.mcp_auth_token}"
                with requests.post(url, json=payload, timeout=settings.mcp_stream_timeout_seconds, stream=True, headers=headers) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=1024):
                        if not chunk:
                            continue
                        text = chunk.decode('utf-8', errors='ignore')
                        if text:
                            yield text
                took = int((time.time() - t0) * 1000)
                self._logger.info("mcp_http analyze_trials_stream done took_ms=%d", took)
                return
            except Exception as e:
                code = self._map_error(locals().get('resp', None), e)
                self._logger.warning("mcp_http analyze_trials_stream fallback local error_code=%s err=%s", code, str(e))
        self._logger.info("mcp_adapter -> analyze_trials_stream delegate to local")
        async for token in self._local.analyze_trials_stream(patient_features, trials):
            yield token

    # 报告
    async def generate_report(self, user_query: str, patient_features: str, papers_summary: str, trial_analysis: str) -> ReportResult:
        if settings.mcp_enabled and settings.mcp_base_url and self._allowed("generate_report"):
            try:
                url = settings.mcp_base_url.rstrip('/') + "/tools/generate_report"
                payload = {
                    "user_query": user_query,
                    "patient_features": patient_features,
                    "papers_summary": papers_summary,
                    "trial_analysis": trial_analysis,
                }
                t0 = time.time(); self._logger.info("mcp_http -> POST %s", url)
                headers = {}
                if settings.mcp_auth_token:
                    headers[settings.mcp_auth_header] = f"Bearer {settings.mcp_auth_token}"
                resp = requests.post(url, json=payload, timeout=settings.mcp_request_timeout_seconds, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                took = int((time.time() - t0) * 1000)
                meta = data.get("meta") or {}
                meta.setdefault("took_ms", took)
                return ReportResult(final_answer=data.get("final_answer", ""), meta=Meta(**meta))
            except Exception as e:
                code = self._map_error(locals().get('resp', None), e)
                self._logger.warning("mcp_http generate_report fallback local error_code=%s err=%s", code, str(e))
        self._logger.info("mcp_adapter -> generate_report delegate to local")
        return await self._local.generate_report(user_query, patient_features, papers_summary, trial_analysis)
