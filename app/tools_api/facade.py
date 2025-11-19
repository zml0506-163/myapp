from __future__ import annotations
from typing import AsyncGenerator, List, Coroutine
from abc import ABC, abstractmethod

from .models import (
    PapersResult,
    TrialsResult,
    DownloadResult,
    AnalysisResult,
    SummaryResult,
    ReportResult,
    Paper,
    Trial,
)


class ToolsFacade(ABC):
    """
    工具接口层（端口/适配器）：
    - 工作流仅依赖本接口，不关心底层实现（本地实现 or MCP 客户端）。
    - 分析类接口需提供“流式”输出以兼容前端逐字打印体验。
    - 错误码与 meta（took_ms、retries）由实现方补充。
    """

    # 检索
    @abstractmethod
    async def search_papers(self, query: str, size: int, sources: List[str] | None = None) -> PapersResult:
        """
        检索文献列表。
        参数：
        - query: 关键词或查询语句
        - size: 返回数量上限
        - sources: 可选来源限定（如 ["pubmed", "europe_pmc"]）
        返回：PapersResult，要求 meta 至少包含 took_ms。
        失败处理：实现需记录统一日志键（tool/args_digest/took_ms/retries/error_code），并可择机回退本地实现。
        错误码约定：429->rate_limited；其他4xx->invalid_input；其余->upstream_error。
        """
        ...

    @abstractmethod
    async def search_trials(self, keywords: str, size: int) -> TrialsResult:
        """
        检索临床试验。
        参数：
        - keywords: 关键词（可为组合）
        - size: 返回数量上限
        返回：TrialsResult，要求 meta 至少包含 took_ms。
        错误码与日志同上。
        """
        ...

    # 下载/解压
    @abstractmethod
    async def download_pdf(self, url: str, filename: str) -> DownloadResult:
        """
        下载 PDF（或委托远端下载再回传元数据）。
        参数：url, filename
        返回：DownloadResult {path, bytes, meta{took_ms,...}}
        超时与鉴权由实现按 settings 控制；错误码映射与回退同约定。
        """
        ...

    @abstractmethod
    async def extract_tgz(self, url: str, filename: str) -> DownloadResult:
        """
        下载并解压 tgz 包，返回解压路径与字节数（可为估计值）。
        返回 meta.took_ms；错误码/回退约定同上。
        """
        ...

    # 文献与试验分析（流式）
    @abstractmethod
    async def analyze_pdf_stream(self, patient_features: str, user_query: str, pdf_path: str) -> AsyncGenerator[str, None]:
        """
        文献 PDF 分析（流式逐 token）。
        - 输出：逐字 token（不含额外包装），前端沿用现有 SSE 处理。
        - 失败时应无缝回退本地实现，保证流不中断。
        - 日志键与错误码映射同约定。
        """
        ...

    @abstractmethod
    async def summarize_papers(self, analyses: List[dict]) -> SummaryResult:
        """
        汇总多篇文献要点。
        参数：analyses：[{paper, analysis, ...}]
        返回：SummaryResult {summary, meta{took_ms,...}}
        """
        ...

    @abstractmethod
    async def analyze_trials_stream(self, patient_features: str, trials: List[Trial]) -> AsyncGenerator[str, None]:
        """
        临床试验分析（流式逐 token）。
        - 输出流与 analyze_pdf_stream 语义一致。
        - 失败时回退本地实现，SSE 不中断。
        """
        ...

    # 报告
    @abstractmethod
    async def generate_report(self, user_query: str, patient_features: str, papers_summary: str, trial_analysis: str) -> ReportResult:
        """
        生成综合报告（一次性返回）。
        返回：ReportResult {final_answer, meta{took_ms,...}}
        错误码与日志键一致；失败可回退旧路径但不改变前端行为。
        """
        ...
