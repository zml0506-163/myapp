"""
PubMed 客户端 - 支持超时控制和并发限制
app/tools/pubmed_client.py
"""
import asyncio
import time
import httpx
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Optional, Callable
from metapub import FindIt
from fastapi.logger import logger
import xml.etree.ElementTree as ET

from app.core.config import settings
from app.tools.download_utils import download_pdf_sync, download_pdf_from_tgz_sync, download_pdf_from_webview

# NCBI E-utilities 基础地址
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://pubmed.ncbi.nlm.nih.gov/',
    'Accept-Language': 'en-US,en;q=0.5'
}


class PubMedClient:
    """优化的 PubMed 客户端"""

    def __init__(self):
        self.download_timeout = settings.pdf_download_timeout
        self.max_retries = settings.pdf_download_max_retries
        self.max_concurrent = settings.max_concurrent_downloads
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    async def esearch_pmids(self, query: str, retmax: int = None) -> List[str]:
        """根据关键词搜索 PubMed，返回 PMID 列表"""
        if retmax is None:
            retmax = settings.max_pmids_to_fetch

        term = f"{query} AND free full text[sb]"
        params = {
            "db": "pubmed",
            "term": term,
            "retmode": "json",
            "retmax": str(retmax)
        }

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{EUTILS}/esearch.fcgi", params=params)
            r.raise_for_status()
            j = r.json()
            return j.get("esearchresult", {}).get("idlist", [])

    async def efetch_metadata(self, pmids: List[str]) -> Dict[str, Dict]:
        """根据 PMID 获取文章的基本信息"""
        if not pmids:
            return {}

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml"
        }

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{EUTILS}/efetch.fcgi", params=params)
            r.raise_for_status()
            xml_text = r.text

        root = ET.fromstring(xml_text)
        meta = {}

        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID")
            title = self._extract_title(article)
            abstract = self._extract_abstract(article)
            pub_date = self._extract_pub_date(article)
            authors = self._extract_authors(article)
            pmcid_elem = article.find(".//ArticleIdList/ArticleId[@IdType='pmc']")
            pmcid = pmcid_elem.text if pmcid_elem is not None else None

            meta[pmid] = {
                "title": title,
                "abstract": abstract,
                "pub_date": pub_date,
                "authors": authors,
                "pmcid": pmcid
            }
        return meta

    async def download_pdf_with_limit(
            self,
            pmid: str,
            pmcid: Optional[str],
            executor: ThreadPoolExecutor,
            progress_callback: Callable
    ) -> Optional[Path]:
        """
        带并发控制的 PDF 下载
        
        使用 Semaphore 限制并发数量
        """
        async with self._semaphore:
            return await self._download_pdf_internal(
                pmid,
                pmcid,
                executor,
                progress_callback
            )

    async def _download_pdf_internal(
            self,
            pmid: str,
            pmcid: Optional[str],
            executor: ThreadPoolExecutor,
            progress_callback: Callable
    ) -> Optional[Path]:
        """
        内部 PDF 下载逻辑（带超时和重试）
        """
        try:
            progress_callback("开始查找PDF资源...", False)

            # 1. 尝试从 PMC 获取
            if pmcid:
                progress_callback("发现PMC资源", False)
                from app.tools.publisher_rules import get_pdf_path_from_pmcid

                pdf_link = get_pdf_path_from_pmcid(pmcid)
                if pdf_link:
                    url_type = "tgz" if pdf_link.endswith(".tar.gz") else "pdf"

                    # 带超时下载
                    pdf_path = await self._download_with_timeout(
                        pdf_link,
                        pmid,
                        url_type,
                        executor,
                        progress_callback
                    )

                    if pdf_path:
                        return pdf_path

            # 2. 尝试使用 metapub
            pdf_link = await self._find_pdf_by_metapub(pmid)
            if pdf_link:
                progress_callback("发现PDF资源", False)
                pdf_path = await self._download_with_timeout(
                    pdf_link,
                    pmid,
                    "pdf",
                    executor,
                    progress_callback
                )
                if pdf_path:
                    return pdf_path

            # 3. 尝试从出版商页面获取
            pdf_path = await self._try_publisher_pages(
                pmid,
                executor,
                progress_callback
            )

            return pdf_path

        except asyncio.TimeoutError:
            progress_callback(f"下载超时（{self.download_timeout}秒）", False)
            logger.warning(f"PMID {pmid} 下载超时")
            return None
        except Exception as e:
            progress_callback(f"下载失败: {str(e)}", False)
            logger.error(f"PMID {pmid} 下载失败: {e}")
            return None

    async def _download_with_timeout(
            self,
            pdf_link: str,
            pmid: str,
            url_type: str,
            executor: ThreadPoolExecutor,
            progress_callback: Callable
    ) -> Optional[Path]:
        """
        带超时的下载（支持重试）
        """
        loop = asyncio.get_running_loop()

        for retry in range(self.max_retries):
            try:
                progress_callback(f"开始下载（尝试 {retry + 1}/{self.max_retries}）...", False)

                if url_type == "tgz":
                    download_func = download_pdf_from_tgz_sync
                elif url_type == "webview":
                    download_func = download_pdf_from_webview
                else:
                    download_func = download_pdf_sync

                # 使用 wait_for 设置超时
                pdf_path = await asyncio.wait_for(
                    loop.run_in_executor(
                        executor,
                        download_func,
                        pdf_link,
                        f"{pmid}.pdf",
                        progress_callback
                    ),
                    timeout=self.download_timeout
                )

                if pdf_path:
                    progress_callback("下载成功", False)
                    return pdf_path
                else:
                    if retry < self.max_retries - 1:
                        progress_callback("下载失败，准备重试...", False)
                        await asyncio.sleep(2)  # 等待2秒后重试
                    else:
                        progress_callback("下载失败", False)

            except asyncio.TimeoutError:
                if retry < self.max_retries - 1:
                    progress_callback(f"超时，准备重试...", False)
                    await asyncio.sleep(2)
                else:
                    progress_callback(f"超时（{self.download_timeout}秒）", False)
                    raise

        return None

    async def _find_pdf_by_metapub(self, pmid: str) -> Optional[str]:
        """使用 metapub 查找 PDF 链接"""
        loop = asyncio.get_running_loop()

        try:
            pdf_link = await loop.run_in_executor(
                None,
                lambda: FindIt(pmid).url
            )
            return pdf_link
        except Exception as e:
            logger.warning(f"metapub 查找失败: {e}")
            return None

    async def _try_publisher_pages(
            self,
            pmid: str,
            executor: ThreadPoolExecutor,
            progress_callback: Callable
    ) -> Optional[Path]:
        """尝试从出版商页面获取 PDF"""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin, urlparse
            from app.tools.publisher_rules import PUBLISHER_RULES, DEFAULT_RULE
            import requests

            pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            progress_callback(f"访问出版商页面", False)

            # 获取页面
            loop = asyncio.get_running_loop()
            html = await loop.run_in_executor(
                None,
                lambda: requests.get(pubmed_url, headers=HEADERS, timeout=10).text
            )

            soup = BeautifulSoup(html, "html.parser")
            links = soup.select("div.full-text-links div.full-text-links-list a")

            if not links:
                return None

            for link in links:
                full_text_link = link.get("href")
                publisher_url = urljoin(pubmed_url, full_text_link)

                # 选择解析规则
                domain = urlparse(publisher_url).netloc
                parser = PUBLISHER_RULES.get(domain, DEFAULT_RULE)

                # 获取 PDF 链接
                if parser == DEFAULT_RULE:
                    html2 = await loop.run_in_executor(
                        None,
                        lambda: requests.get(publisher_url, headers=HEADERS, timeout=10).text
                    )
                else:
                    html2 = ""

                result = parser(publisher_url, html2)
                if not result:
                    continue

                pdf_link, url_type, download_selector, page_wait_selector = result

                # 下载
                pdf_path = await self._download_with_timeout(
                    pdf_link,
                    pmid,
                    url_type,
                    executor,
                    progress_callback
                )

                if pdf_path:
                    return pdf_path

        except Exception as e:
            logger.error(f"出版商页面解析失败: {e}")

        return None

    def _extract_title(self, article) -> str:
        """提取标题"""
        title = article.findtext(".//ArticleTitle")
        if not title:
            title = article.findtext(".//BookTitle")
        if not title:
            title = article.findtext(".//VernacularTitle")
        return title or ""

    def _extract_abstract(self, article) -> str:
        """提取摘要"""
        parts = []
        for abs_text in article.findall(".//AbstractText"):
            label = abs_text.attrib.get("Label")
            text = abs_text.text or ""
            if label:
                parts.append(f"{label}: {text}")
            else:
                parts.append(text)
        return " ".join(parts).strip()

    def _extract_pub_date(self, article) -> str:
        """提取发表日期"""
        pub_date_node = article.find(".//PubDate")
        if pub_date_node is not None:
            year = pub_date_node.findtext("Year")
            month = pub_date_node.findtext("Month")
            day = pub_date_node.findtext("Day")
            if year:
                return "-".join(filter(None, [year, month, day]))
        return ""

    def _extract_authors(self, article) -> str:
        """提取作者"""
        authors = []
        for au in article.findall(".//Author"):
            last = au.findtext("LastName") or ""
            fore = au.findtext("ForeName") or ""
            if fore and last:
                authors.append(f"{fore} {last}")
            elif last:
                authors.append(last)
        return ", ".join(authors)


# 全局实例
pubmed_client = PubMedClient()