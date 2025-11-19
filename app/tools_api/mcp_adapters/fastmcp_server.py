from __future__ import annotations
import time
from typing import List, Dict, Any, Optional, Callable, AsyncGenerator
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.tools_api.local_adapters.local_tools_adapter import LocalToolsAdapter

# Optional fastmcp import (soft dependency)
try:
    from fastmcp import MCPServer, tool
    _FASTMCP_AVAILABLE = True
except Exception:  # pragma: no cover
    MCPServer = None  # type: ignore
    tool = None  # type: ignore
    _FASTMCP_AVAILABLE = False

# Expose FastAPI sub-app to be mounted by main app
mcp_app = FastAPI(title="MCP Service (fastmcp)", version="1.0.0")
_local = LocalToolsAdapter()


def _check_auth(request: Request) -> None:
    token = settings.mcp_auth_token
    if not token:
        return
    header_name = settings.mcp_auth_header or "Authorization"
    auth = request.headers.get(header_name)
    expected = f"Bearer {token}"
    if auth != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ============ fastmcp server (optional) ============
_mcp_server: Optional["MCPServer"] = None
if _FASTMCP_AVAILABLE:
    _mcp_server = MCPServer(name="pubmed-app-tools")

    @_mcp_server.tool()
    def search_trials(keywords: str, size: int = 5) -> Dict[str, Any]:
        # Delegate to local implementation
        # fastmcp tools are sync-friendly; we run async via local adapter through simple wrapper
        import anyio
        async def _run():
            res = await _local.search_trials(keywords, size)
            return {"trials": [t.dict() for t in res.trials], "meta": (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})}
        return anyio.run(_run)

    @_mcp_server.tool()
    def search_papers(query: str, size: int = 5, sources: Optional[List[str]] = None) -> Dict[str, Any]:
        import anyio
        async def _run():
            res = await _local.search_papers(query, size, sources or [])
            return {"papers": [p.dict() for p in res.papers], "meta": (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})}
        return anyio.run(_run)

    @_mcp_server.tool()
    def summarize_papers(analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        import anyio
        async def _run():
            res = await _local.summarize_papers(analyses)
            return {"summary": res.summary, "meta": (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})}
        return anyio.run(_run)

    @_mcp_server.tool()
    def download_pdf(url: str, filename: str) -> Dict[str, Any]:
        import anyio
        async def _run():
            res = await _local.download_pdf(url, filename)
            return {"path": res.path, "bytes": res.bytes, "meta": (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})}
        return anyio.run(_run)

    @_mcp_server.tool()
    def extract_tgz(url: str, filename: str) -> Dict[str, Any]:
        import anyio
        async def _run():
            res = await _local.extract_tgz(url, filename)
            return {"path": res.path, "bytes": res.bytes, "meta": (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})}
        return anyio.run(_run)

    @_mcp_server.tool()
    def generate_report(user_query: str, patient_features: str, papers_summary: str, trial_analysis: str) -> Dict[str, Any]:
        import anyio
        async def _run():
            res = await _local.generate_report(user_query, patient_features, papers_summary, trial_analysis)
            return {"final_answer": res.final_answer, "meta": (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})}
        return anyio.run(_run)

# ============ REST bridge (keeps current adapter contract) ============

@mcp_app.get("/health")
async def http_health():
    tools = [
        "search_papers",
        "search_trials",
        "summarize_papers",
        "analyze_pdf",
        "analyze_trials_stream",
        "download_pdf",
        "extract_tgz",
        "generate_report",
    ]
    return {
        "status": "ok",
        "fastmcp_available": _FASTMCP_AVAILABLE,
        "tools": tools,
    }

@mcp_app.get("/tools")
async def http_tools():
    tools = [
        "search_papers",
        "search_trials",
        "summarize_papers",
        "analyze_pdf",
        "analyze_trials_stream",
        "download_pdf",
        "extract_tgz",
        "generate_report",
    ]
    return {"tools": tools}

@mcp_app.get("/self_check")
async def http_self_check():
    tools = [
        "search_papers",
        "search_trials",
        "summarize_papers",
        "analyze_pdf",
        "analyze_trials_stream",
        "download_pdf",
        "extract_tgz",
        "generate_report",
    ]
    return {
        "status": "ok",
        "mcp_enabled": bool(getattr(settings, 'mcp_enabled', False)),
        "fastmcp_available": _FASTMCP_AVAILABLE,
        "auth_required": bool(getattr(settings, 'mcp_auth_token', None)),
        "auth_header": getattr(settings, 'mcp_auth_header', 'Authorization'),
        "whitelist": getattr(settings, 'mcp_tool_whitelist', []) or [],
        "request_timeout_seconds": getattr(settings, 'mcp_request_timeout_seconds', None),
        "stream_timeout_seconds": getattr(settings, 'mcp_stream_timeout_seconds', None),
        "tools": tools,
    }

@mcp_app.post("/tools/search_trials")
async def http_search_trials(payload: Dict[str, Any], request: Request):
    _check_auth(request)
    keywords: str = payload.get("keywords", "")
    size: int = int(payload.get("size", 3))
    t0 = time.time()
    # Prefer fastmcp if available, otherwise local
    if _FASTMCP_AVAILABLE and _mcp_server:
        data = _mcp_server.call("search_trials", keywords=keywords, size=size)  # type: ignore
        trials = data.get("trials", [])
        meta = data.get("meta", {})
    else:
        res = await _local.search_trials(keywords, size)
        trials = [t.dict() for t in res.trials]
        meta = (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})
    meta.setdefault("took_ms", int((time.time() - t0) * 1000))
    return {"trials": trials, "meta": meta}


@mcp_app.post("/tools/search_papers")
async def http_search_papers(payload: Dict[str, Any], request: Request):
    _check_auth(request)
    query: str = payload.get("query", "")
    size: int = int(payload.get("size", 3))
    sources = payload.get("sources", [])
    t0 = time.time()
    if _FASTMCP_AVAILABLE and _mcp_server:
        data = _mcp_server.call("search_papers", query=query, size=size, sources=sources)  # type: ignore
        papers = data.get("papers", [])
        meta = data.get("meta", {})
    else:
        res = await _local.search_papers(query, size, sources)
        papers = [p.dict() for p in res.papers]
        meta = (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})
    meta.setdefault("took_ms", int((time.time() - t0) * 1000))
    return {"papers": papers, "meta": meta}


@mcp_app.post("/tools/summarize_papers")
async def http_summarize_papers(payload: Dict[str, Any], request: Request):
    _check_auth(request)
    analyses: List[Dict[str, Any]] = payload.get("analyses", [])
    t0 = time.time()
    if _FASTMCP_AVAILABLE and _mcp_server:
        data = _mcp_server.call("summarize_papers", analyses=analyses)  # type: ignore
        meta = data.get("meta", {})
        summary = data.get("summary", "")
    else:
        res = await _local.summarize_papers(analyses)
        summary = res.summary
        meta = (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})
    meta.setdefault("took_ms", int((time.time() - t0) * 1000))
    return {"summary": summary, "meta": meta}


@mcp_app.post("/tools/download_pdf")
async def http_download_pdf(payload: Dict[str, Any], request: Request):
    _check_auth(request)
    url: str = payload.get("url", "")
    filename: str = payload.get("filename", "mock.pdf")
    t0 = time.time()
    if _FASTMCP_AVAILABLE and _mcp_server:
        data = _mcp_server.call("download_pdf", url=url, filename=filename)  # type: ignore
        meta = data.get("meta", {})
        path = data.get("path", "")
        bytes_ = data.get("bytes", 0)
    else:
        res = await _local.download_pdf(url, filename)
        path = res.path
        bytes_ = res.bytes
        meta = (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})
    meta.setdefault("took_ms", int((time.time() - t0) * 1000))
    meta.setdefault("source_url", url)
    return {"path": path, "bytes": bytes_, "meta": meta}


@mcp_app.post("/tools/extract_tgz")
async def http_extract_tgz(payload: Dict[str, Any], request: Request):
    _check_auth(request)
    url: str = payload.get("url", "")
    filename: str = payload.get("filename", "mock.tgz")
    t0 = time.time()
    if _FASTMCP_AVAILABLE and _mcp_server:
        data = _mcp_server.call("extract_tgz", url=url, filename=filename)  # type: ignore
        meta = data.get("meta", {})
        path = data.get("path", "")
        bytes_ = data.get("bytes", 0)
    else:
        res = await _local.extract_tgz(url, filename)
        path = res.path
        bytes_ = res.bytes
        meta = (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})
    meta.setdefault("took_ms", int((time.time() - t0) * 1000))
    meta.setdefault("source_url", url)
    return {"path": path, "bytes": bytes_, "meta": meta}


@mcp_app.post("/tools/analyze_pdf")
async def http_analyze_pdf(payload: Dict[str, Any], request: Request):
    _check_auth(request)
    patient_features: str = payload.get("patient_features", "")
    user_query: str = payload.get("user_query", "")
    pdf_path: str = payload.get("pdf_path", "")

    async def streamer() -> AsyncGenerator[str, None]:
        if _FASTMCP_AVAILABLE and _mcp_server:
            # Use local stream to ensure identical tokenization behavior
            async for token in _local.analyze_pdf_stream(patient_features, user_query, pdf_path):
                yield token
        else:
            async for token in _local.analyze_pdf_stream(patient_features, user_query, pdf_path):
                yield token

    return StreamingResponse(streamer(), media_type="text/plain; charset=utf-8")


@mcp_app.post("/tools/analyze_trials_stream")
async def http_analyze_trials_stream(payload: Dict[str, Any], request: Request):
    _check_auth(request)
    patient_features: str = payload.get("patient_features", "")
    trials: List[Dict[str, Any]] = payload.get("trials", [])

    async def streamer() -> AsyncGenerator[str, None]:
        from app.tools_api.models import Trial
        objs = [Trial(**t) for t in trials]
        if _FASTMCP_AVAILABLE and _mcp_server:
            # Keep local streaming to preserve SSE token behavior
            async for token in _local.analyze_trials_stream(patient_features, objs):
                yield token
        else:
            async for token in _local.analyze_trials_stream(patient_features, objs):
                yield token

    return StreamingResponse(streamer(), media_type="text/plain; charset=utf-8")


@mcp_app.post("/tools/generate_report")
async def http_generate_report(payload: Dict[str, Any], request: Request):
    _check_auth(request)
    user_query: str = payload.get("user_query", "")
    patient_features: str = payload.get("patient_features", "")
    papers_summary: str = payload.get("papers_summary", "")
    trial_analysis: str = payload.get("trial_analysis", "")
    t0 = time.time()
    if _FASTMCP_AVAILABLE and _mcp_server:
        data = _mcp_server.call(
            "generate_report",
            user_query=user_query,
            patient_features=patient_features,
            papers_summary=papers_summary,
            trial_analysis=trial_analysis,
        )  # type: ignore
        meta = data.get("meta", {})
        final_answer = data.get("final_answer", "")
    else:
        res = await _local.generate_report(user_query, patient_features, papers_summary, trial_analysis)
        final_answer = res.final_answer
        meta = (res.meta or {}).dict() if hasattr(res.meta, 'dict') else (res.meta or {})
    meta.setdefault("took_ms", int((time.time() - t0) * 1000))
    return {"final_answer": final_answer, "meta": meta}
