import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from typing import Dict, Any, Optional

from fastapi import FastAPI, Depends, Request, Query, HTTPException, status as http_status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from starlette.responses import StreamingResponse, FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.db.crud import upsert_clinical_trial, ALLOWED_STATUSES, list_trials_with_pagination, list_papers
from app.db.database import engine, get_db
from app.tools.europepmc_client import search_europe_pmc, process_records_and_save_to_db
from app.models import Base, ClinicalTrial, Paper
from app.db import crud
from app.tools.pubmed_client import pubmed_client
from app.core.config import settings
from app.tools.clinical_trials_client import async_search_trials
from app.core.logger import logger

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    openapi_url=f"{settings.api_prefix}/openapi.json"
)

logger.info(f"启动FastAPI应用: {settings.project_name} v{settings.version}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    #     allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 创建全局线程池（避免重复创建，推荐在应用启动时初始化）
# 可根据服务器性能调整max_workers（建议5-10）
executor = ThreadPoolExecutor(max_workers=5)


# 注册路由
app.include_router(api_router, prefix=settings.api_prefix)

app.mount("/api/files", StaticFiles(directory=settings.pdf_dir), name="files")


def build_msg(type_: str, content: dict | str, newline: bool = True, eventType: str | None = None, ids: str | None = None) -> str:
    """
    type_: 'text', 'image', 'pdf', 'custom', 'link' 等
    content: 字符串或字典
    newline: 当前是否为新行
    """
    payload = {"type": type_, "content": content, "newline": newline, "eventType": eventType, "ids": ids}
    return to_json(payload) + "\n"


def to_json(obj):
    return json.dumps(obj, ensure_ascii=False)


# 启动建表
@app.on_event("startup")
async def on_startup():
    logger.info("应用启动：初始化数据库和存储目录")
    pdf_dir = Path(settings.pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("应用启动完成")


@app.post("/api/search")
async def search(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    q = data.get("q")
    limit = int(data.get("limit", 5))
    progress_queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    # 生产者：普通 coroutine（**不使用 yield**），把进度消息放入 queue
    async def producer():
        try:
            await progress_queue.put("准备搜索PubMed并获取相关文献")
            # 1. 搜索PMID
            pmids = await pubmed_client.esearch_pmids(q, retmax=limit * 5)
            # pmids = []
            # 2. 获取元数据
            meta = await pubmed_client.efetch_metadata(pmids)

            success_count = 0
            for pid in pmids:
                if success_count >= limit:
                    break

                # 线程安全的回调 —— 在工作线程里调用此回调会把消息放回主loop的 queue
                def progress_callback(message, newline=True):
                    asyncio.run_coroutine_threadsafe(
                        progress_queue.put(("MESSAGE", f"{message}", newline)),
                        loop
                    )

                await progress_queue.put(f"发现PMID：{pid} ")

                m = meta.get(pid, {})
                # 调用异步封装（内部用 run_in_executor 调同步函数）, 为了异步调用get_pdf_from_pubmed_sync方法
                # pdf_path = await get_pdf_from_pubmed(pid, m.get("pmcid"), executor, progress_callback)
                pdf_path = await pubmed_client.download_pdf_with_limit(
                    pid,
                    m.get("pmcid"),
                    executor,
                    progress_callback
                )
                if not pdf_path:
                    continue

                title = m.get("title") or "(no title)"
                # 把每篇成功的信息也放进队列（consumer 负责 build_msg）
                await progress_queue.put(("MESSAGE", f"完成收录{pid} - {title}", False))

                # 存数据库
                await crud.upsert_paper(
                    db,
                    pmid=pid,
                    pmcid=m.get("pmcid"),
                    title=title,
                    source_type='pubmed',
                    abstract=m.get("abstract"),
                    pub_date=m.get("pub_date"),
                    authors=m.get("authors"),
                    pdf_path=str(pdf_path),
                    source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"
                )
                success_count += 1

            # 告知结束并带上计数
            await progress_queue.put(f"搜索完成，共获取到{success_count}篇有效文献")

            # 搜索europe_pmc
            """处理搜索结果并保存到数据库"""
            await progress_queue.put("准备搜索europepmc并获取相关文献")
            records = await search_europe_pmc(q, limit=limit*3)
            success_count = await process_records_and_save_to_db(records, limit,progress_queue)
            await progress_queue.put(f"搜索完成，从europe pmc共获取到{success_count}篇有效文献")

            # 搜索临床试验
            await progress_queue.put("准备搜索临床试验")
            trials, _ = await async_search_trials([q], logic="OR")  # status="RECRUITING" 招募中

            for t in trials:
                await upsert_clinical_trial(
                    db,
                    nct_id=t["nct_id"],
                    title=t["title"],
                    official_title=t.get("official_title"),
                    status=t.get("status"),
                    start_date=t.get("start_date"),
                    completion_date=t.get("completion_date"),
                    study_type=t.get("study_type"),
                    phase=t.get("phase"),
                    allocation=t.get("allocation"),
                    intervention_model=t.get("intervention_model"),
                    conditions=t.get("conditions"),
                    sponsor=t.get("sponsor"),
                    locations=t.get("locations"),
                    source_url=t.get("source_url"),
                )
            if trials and len(trials) > 0:
                nct_ids = [t["nct_id"] for t in trials]
                await progress_queue.put(("MESSAGE", f"搜索完成，共找到{len(trials)}个相关临床试验", True))
                await progress_queue.put(("LINK", "点击查看", False, "trial", ",".join(nct_ids)))
            else:
                await progress_queue.put(f"搜索完成，未找到相关临床试验")

        except Exception as exc:
            # 出错也通过 queue 通知前端
            await progress_queue.put(("ERROR", str(exc)))
        await progress_queue.put(("DONE", "完成"))

    # 启动生产者任务（这是 coroutine，可以用 create_task）
    producer_task = asyncio.create_task(producer())

    # 消费者：异步生成器，从 queue 读取并 yield（这才是传给 StreamingResponse 的迭代器）
    async def queue_yielder():
        try:
            while True:
                msg = await progress_queue.get()
                # 用特殊 tuple 协议传递终结或错误信息
                if isinstance(msg, tuple):
                    tag = msg[0]
                    if tag == "DONE":
                        yield build_msg("done", f"")
                        break
                    elif tag == "ERROR":
                        yield build_msg("text", f"发生错误：{msg[1]}")
                        break
                    elif tag == "LINK":
                        yield build_msg("link", msg[1], msg[2], msg[3], msg[4])
                    elif tag == "MESSAGE":
                        yield build_msg("text", msg[1], msg[2])
                else:
                    # 普通字符串消息
                    yield build_msg("text", msg)
        finally:
            # 如果客户端断开或 generator 被关闭，确保取消 producer_task 避免悬挂
            if not producer_task.done():
                producer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await producer_task

    # 返回 StreamingResponse，media_type 按需可改为"text/event-stream"
    return StreamingResponse(queue_yielder(), media_type="text/event-stream")


# 在应用关闭时优雅关闭线程池
@app.on_event("shutdown")
def shutdown_event():
    logger.info("应用关闭：清理资源")
    executor.shutdown(wait=True)
    logger.info("应用关闭完成")


def format_paper(paper: Paper) -> Dict[str, Any]:
    """格式化文献数据为统一响应格式"""
    return {
        "id": paper.id,
        "pmid": paper.pmid,
        "pmcid": paper.pmcid,
        "title": paper.title,
        "source_type": paper.source_type,
        "abstract": paper.abstract,
        "pub_date": paper.pub_date,
        "authors": paper.authors,
        "pdf_url": paper.pdf_path,
        "source_url": paper.source_url,
        "created_at": paper.created_at.isoformat() if paper.created_at else None,
        "updated_at": paper.updated_at.isoformat() if paper.updated_at else None
    }


@app.get("/api/papers")
async def get_papers(
        page: int = Query(1, ge=1, description="页码，从1开始"),
        page_size: int = Query(10, ge=1, le=100, description="每页条数，最大100"),
        pmid: Optional[str] = Query(None, description="PMID编号搜索"),
        title: Optional[str] = Query(None, description="标题关键词搜索"),
        author: Optional[str] = Query(None, description="作者关键词搜索"),
        db: AsyncSession = Depends(get_db)
):
    """分页查询文献列表，支持多条件搜索"""
    offset = (page - 1) * page_size

    # 获取分页数据和总条数
    papers, total = await list_papers(
        db,
        limit=page_size,
        offset=offset,
        pmid=pmid,
        title=title,
        author=author
    )

    # 计算总页数
    pages = (total + page_size - 1) // page_size if total else 0

    return {
        "items": [format_paper(p) for p in papers],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages  # 总页数
    }


def format_trial(trial: ClinicalTrial) -> Dict[str, Any]:
    """格式化临床试验数据为API响应格式"""
    return {
        "id": trial.id,
        "nct_id": trial.nct_id,
        "title": trial.title,
        "official_title": trial.official_title,
        "status": trial.status,
        "start_date": trial.start_date,
        "completion_date": trial.completion_date,
        "study_type": trial.study_type,
        "phase": trial.phase,
        "allocation": trial.allocation,
        "intervention_model": trial.intervention_model,
        "conditions": trial.conditions,
        "sponsor": trial.sponsor,
        "locations": trial.locations,
        "source_url": trial.source_url,
        "created_at": trial.created_at.isoformat() if trial.created_at else None,
        "updated_at": trial.updated_at.isoformat() if trial.updated_at else None
    }


@app.get("/api/clinical_trials", response_model=Dict[str, Any])
async def get_clinical_trials(
        page: int = Query(1, ge=1, description="页码，从1开始"),
        page_size: int = Query(10, ge=1, le=100, description="每页条数，最大100"),
        nct_id: Optional[str] = Query(None, description="NCT编号筛选，多个逗号分隔"),
        condition: Optional[str] = Query(None, description="疾病/条件筛选"),
        status: Optional[str] = Query(None, description=f"状态筛选，允许值: {ALLOWED_STATUSES}"),
        db: AsyncSession = Depends(get_db)
):
    """分页查询临床试验列表，支持多条件筛选"""
    try:
        offset = (page - 1) * page_size
        trials, total = await list_trials_with_pagination(
            db,
            page_size=page_size,
            offset=offset,
            nct_id=nct_id,
            condition=condition,
            status=status
        )

        return {
            "items": [format_trial(trial) for trial in trials],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total is not None else 0  # 总页数
        }
    except Exception as e:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询失败: {str(e)}"
        )


# 或者使用自定义路径参数的方式，更灵活地处理文件下载
@app.get("/api/download/{pdf_path}")
async def download_file(pdf_path: str):
    """
    下载指定路径的文件
    file_path应为相对于storage目录的路径
    """
    # 构建完整的文件路径
    full_path = pdf_path

    # 检查文件是否存在
    if not os.path.exists(full_path):
        return {"error": "文件不存在"}

    # 检查是否是文件（不是目录）
    if not os.path.isfile(full_path):
        return {"error": "路径不是一个文件"}

    # 返回文件作为下载响应
    return FileResponse(
        path=full_path,
        filename=os.path.basename(full_path),
        media_type="application/pdf"  # 对于PDF文件的MIME类型
    )


app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

# SPA fallback: for non-API routes that 404, return index.html so SPA routes like /register work on refresh
@app.exception_handler(StarletteHTTPException)
async def spa_fallback(request: Request, exc: StarletteHTTPException):
    # Only intercept 404 and only for non-API paths
    if exc.status_code == 404:
        path = request.url.path or "/"
        if not (path.startswith("/api") or path.startswith("/api/files")):
            index_path = os.path.join("frontend", "dist", "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path, media_type="text/html")
    # Fallback to original JSON 404
    detail = getattr(exc, "detail", "Not Found")
    return JSONResponse({"detail": detail}, status_code=exc.status_code)
