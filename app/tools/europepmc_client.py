import asyncio
import os
import requests
from pathlib import Path
from typing import Optional, Dict, Any

from app.db import crud  # 数据库操作
from app.core.config import settings
from app.db.database import AsyncSessionLocal

# === 配置 ===
SEARCH_QUERY = " AND ((HAS_FREE_FULLTEXT:Y) OR HAS_FT:Y) AND (HAS_PDF:Y)"
RESULTS_LIMIT = 10
BASE_DIR = Path(settings.pdf_dir)
os.makedirs(BASE_DIR, exist_ok=True)


async def search_europe_pmc(query: str, limit: int = 10) -> list[Dict[str, Any]]:
    """搜索Europe PMC并返回结果列表"""
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {
        "query": query + SEARCH_QUERY,
        "format": "json",
        "pageSize": limit
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("resultList", {}).get("result", [])
    except Exception as e:
        print(f"搜索失败: {e}")
        return []


def get_pdf_url(record: Dict[str, Any]) -> Optional[str]:
    """从记录中获取PDF下载链接"""
    pmcid = record.get("pmcid")
    if not pmcid:
        return None
    return f"https://europepmc.org/articles/{pmcid}?pdf=render"


def get_unique_filename(record: Dict[str, Any]) -> str:
    """生成唯一的PDF文件名，优先使用PMCID，其次使用PMID"""
    pmcid = record.get("pmcid")
    pmid = record.get("pmid")

    if pmcid:
        return f"europepmc_{pmcid}.pdf"
    elif pmid:
        return f"europepmc_{pmid}.pdf"
    else:
        # 若均无则使用标题哈希值确保唯一性
        title_hash = hash(record.get("title", ""))
        return f"europepmc_paper_{title_hash}.pdf"


def download_pdf(url: str, save_path: Path) -> bool:
    """下载PDF并返回是否成功"""
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and "pdf" in r.headers.get("content-type", "").lower():
            with open(save_path, "wb") as f:
                f.write(r.content)
            print(f"下载完成: {save_path}")
            return True
        else:
            print(f"无法下载或不是PDF (状态码: {r.status_code}): {url}")
            return False
    except Exception as e:
        print(f"下载失败 {url}: {e}")
        return False


async def process_records_and_save_to_db(records, limit, progress_queue) -> int:
    success_count = 0
    async with AsyncSessionLocal() as db:  # 每个任务独立 Session
        for record in records:
            if success_count >= limit:
                return success_count

            pmid = record.get("pmid")
            pmcid = record.get("pmcid")
            title = record.get("title")
            pub_date = record.get("pubYear")
            authors = record.get("authorString")
            hasPDF = record.get("hasPDF")

            if hasPDF == 'N':
                continue

            await progress_queue.put(("MESSAGE", f"发现PMID:{pmid}，PMCID:{pmcid}，【{title}】", True))

            pdf_url = get_pdf_url(record)
            filename = get_unique_filename(record)
            pdf_path = BASE_DIR / filename

            # 异步执行下载任务（避免阻塞）
            if pdf_url:
                loop = asyncio.get_running_loop()
                await progress_queue.put(("MESSAGE", f', 下载PDF...', False))
                # 确保 pdf_url 类型为 str（非 None）
                url_to_download: str = pdf_url
                download_success = await loop.run_in_executor(None, lambda: download_pdf(url_to_download, pdf_path))
                if not download_success:
                    await progress_queue.put(("MESSAGE", f"失败！", False))
                    continue
                await progress_queue.put(("MESSAGE", f"成功！", False))

            source_url = f"https://europepmc.org/article/MED/{pmid}" if pmid else \
                f"https://europepmc.org/articles/{pmcid}" if pmcid else ""

            # 保存数据库
            await crud.upsert_paper(
                db,
                pmid=pmid,
                pmcid=pmcid,
                title=title,
                source_type='europepmc',
                abstract='',
                pub_date=pub_date,
                authors=authors,
                pdf_path=str(pdf_path) if pdf_path and pdf_path.exists() else None,
                source_url=source_url
            )

            success_count += 1

        await db.commit()  # 统一提交
    return success_count
