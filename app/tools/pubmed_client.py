import asyncio
import time
import httpx
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Optional
from metapub import FindIt
from fastapi.logger import logger
import xml.etree.ElementTree as ET

from app.tools.publisher_rules import PUBLISHER_RULES, DEFAULT_RULE, get_pdf_path_from_pmcid

# NCBI E-utilities 基础地址
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# 请求头
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://pubmed.ncbi.nlm.nih.gov/',
    'Accept-Language': 'en-US,en;q=0.5'
}

# -------------------------------
# PubMed API 部分
# -------------------------------

async def esearch_pmids(query: str, retmax: int = 20) -> List[str]:
    """根据关键词搜索 PubMed，返回 PMID 列表"""
    # 组合检索词：关键词 + 免费全文过滤
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


async def efetch_metadata(pmids: List[str]) -> Dict[str, Dict]:
    """根据 PMID 获取文章的基本信息（标题、摘要、作者、时间）"""
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
        title = extract_title(article)
        abstract = extract_abstract(article)
        pub_date = extract_pub_date(article)
        authors = extract_authors(article)
        # 新增：提取 PMCID
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


def extract_title(article) -> str:
    """兼容不同类型文献的标题"""
    title = article.findtext(".//ArticleTitle")
    if not title:
        title = article.findtext(".//BookTitle")
    if not title:
        title = article.findtext(".//BookDocument/ArticleTitle")
    if not title:
        title = article.findtext(".//VernacularTitle")
    return title or ""


def extract_abstract(article) -> str:
    """兼容结构化摘要"""
    parts = []
    for abs_text in article.findall(".//AbstractText"):
        label = abs_text.attrib.get("Label")
        text = abs_text.text or ""
        if label:
            parts.append(f"{label}: {text}")
        else:
            parts.append(text)
    # 有些是 <OtherAbstract>
    for abs_text in article.findall(".//OtherAbstract/AbstractText"):
        text = abs_text.text or ""
        parts.append(text)
    return " ".join(parts).strip()


def extract_pub_date(article) -> str:
    """兼容 Year/Month/Day、MedlineDate、ArticleDate"""
    pub_date_node = article.find(".//PubDate")
    if pub_date_node is not None:
        year = pub_date_node.findtext("Year")
        month = pub_date_node.findtext("Month")
        day = pub_date_node.findtext("Day")
        medline_date = pub_date_node.findtext("MedlineDate")
        if year:
            return "-".join(filter(None, [year, month, day]))
        if medline_date:
            return medline_date

    # 兜底：ArticleDate
    article_date = article.find(".//ArticleDate")
    if article_date is not None:
        year = article_date.findtext("Year")
        month = article_date.findtext("Month")
        day = article_date.findtext("Day")
        if year:
            return "-".join(filter(None, [year, month, day]))

    return ""


def extract_authors(article) -> str:
    """兼容 LastName/ForeName/Initials/CollectiveName"""
    authors = []
    for au in article.findall(".//Author"):
        last = au.findtext("LastName") or ""
        fore = au.findtext("ForeName") or ""
        initials = au.findtext("Initials") or ""
        collab = au.findtext("CollectiveName") or ""

        if collab:
            authors.append(collab)
        else:
            if fore and last:
                authors.append(f"{fore} {last}")
            elif initials and last:
                authors.append(f"{initials} {last}")
            elif last:
                authors.append(last)

    return ", ".join(authors)


# -------------------------------
# 爬虫部分：获取 PDF
# -------------------------------

def find_pdf_links_by_metapub(pmid, max_retries=5, retry_delay=1):
    """
    通过pmid获取PDF链接，当遇到访问频率限制等错误时会自动重试

    参数:
        pmid: 文献的PMID编号
        max_retries: 最大重试次数，默认5次
        retry_delay: 重试间隔时间(秒)，默认1秒

    返回:
        str: PDF下载链接，如果获取失败则返回None
    """
    for attempt in range(max_retries):
        try:
            # 使用FindIt获取PDF链接
            pdf_link = FindIt(pmid).url
            return pdf_link
        except Exception as e:
            # 判断是否是访问频率限制相关的错误
            if "rate limit" in str(e).lower() or "frequency" in str(e).lower():
                logger.warning(f"第 {attempt + 1} 次尝试获取PMID {pmid} 的PDF链接失败: 访问频率限制，错误信息: {str(e)}")
            else:
                logger.error(f"第 {attempt + 1} 次尝试获取PMID {pmid} 的PDF链接失败: 错误信息: {str(e)}")

        # 如果不是最后一次尝试，则等待后重试
        if attempt < max_retries - 1:
            logger.info(f"将在 {retry_delay} 秒后进行第 {attempt + 2} 次重试...")
            time.sleep(retry_delay)

    # 所有尝试都失败
    logger.error(f"经过 {max_retries} 次尝试后，仍无法获取PMID {pmid} 的PDF链接")
    return None


def fetch_sync(url: str) -> str:
    """同步获取网页内容（带超时控制）"""
    import requests
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"请求失败: {resp.status_code}")
        resp.encoding = "utf-8"
        return resp.text
    except requests.Timeout:
        raise Exception(f"获取页面超时（30秒）")
    except Exception as e:
        raise Exception(f"获取页面失败: {str(e)}")


def download_pdf_sync(pdf_link: str, pmid: str, url_type: str,
                      download_selector: str, page_wait_selector: str,
                      progress_callback) -> Optional[Path]:
    """
    同步下载PDF（根据url_type选择下载方式）

    Args:
        pdf_link: PDF链接
        pmid: PMID编号
        url_type: 'pdf' | 'tgz' | 'webview'
        download_selector: 网页下载按钮选择器（仅webview需要）
        page_wait_selector: 页面等待选择器（仅webview需要）
        progress_callback: 进度回调函数
    """
    # 导入下载工具（这里使用原来的download_utils）
    from app.tools.download_utils import (
        download_pdf_sync as direct_download,
        download_pdf_from_tgz_sync,
        download_pdf_from_webview
    )

    try:
        progress_callback("发现PDF", False)
        progress_callback("开始下载...", False)

        if url_type == "tgz":
            pdf_path = download_pdf_from_tgz_sync(
                pdf_link,
                f"{pmid}.pdf",
                progress_callback
            )
        elif url_type == "webview":
            pdf_path = download_pdf_from_webview(
                pdf_link,
                pmid,
                download_selector,
                page_wait_selector,
                progress_callback
            )
        else:  # url_type == "pdf"
            pdf_path = direct_download(
                pdf_link,
                f"{pmid}.pdf",
                progress_callback
            )

        if pdf_path:
            progress_callback("下载成功", False)
        else:
            progress_callback("下载失败", False)

        return pdf_path

    except Exception as e:
        logger.error(f"下载PDF时出错: {str(e)}")
        progress_callback(f"下载异常: {str(e)}", False)
        return None


def get_pdf_from_pubmed_sync(pmid: str, pmcid: str, progress_callback) -> Optional[Path]:
    """同步版本：从PubMed获取PDF并下载"""
    try:
        progress_callback("开始查找PDF资源...", False)
        pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        progress_callback(f"打开 <a target='_blank' href='{pubmed_url}'>{pubmed_url}</a>", False)

        html = fetch_sync(pubmed_url)
        soup = BeautifulSoup(html, "html.parser")

        links = soup.select("div.full-text-links div.full-text-links-list a")
        if not links:
            logger.info(f"PMID {pmid} 未发现full text links")
            progress_callback("未发现Full Text Links", False)
            return None

        progress_callback("发现Full Text Links", False)

        # 获取PDF下载地址的几种方式：
        # 1. 查看是否为PMC，如果是可以通过oa.fcgi接口获取pdf下载地址
        if pmcid is not None:
            progress_callback("发现PMC资源", False)
            pdf_link = get_pdf_path_from_pmcid(pmcid)
            if pdf_link is not None:
                url_type = "tgz" if pdf_link.endswith(".tar.gz") else "pdf"
                pdf_path = download_pdf_sync(
                    pdf_link, pmid, url_type,
                    None, None, progress_callback
                )
                if pdf_path:
                    return pdf_path

        # 2. 通过metapub的FindIt方法获取
        pdf_link = find_pdf_links_by_metapub(pmid)
        if pdf_link:
            progress_callback("发现PDF资源", False)
            pdf_path = download_pdf_sync(
                pdf_link, pmid, "pdf",
                None, None, progress_callback
            )
            if pdf_path:
                return pdf_path

        # 3. 通过full text link的详情页面爬虫获取
        if not pdf_link:
            for link in links:
                full_text_link = link.get("href")
                publisher_url = urljoin(pubmed_url, full_text_link)
                progress_callback(f"访问<a target='_blank' href='{publisher_url}'>出版商页面</a>", False)

                # 获取域名，选择对应规则
                domain = urlparse(publisher_url).netloc
                parser = PUBLISHER_RULES.get(domain, DEFAULT_RULE)

                # 如果是需要访问详情页的规则，先获取页面
                if parser == DEFAULT_RULE:
                    html2 = fetch_sync(publisher_url)
                else:
                    html2 = ""

                result = parser(publisher_url, html2)
                if not result:
                    continue

                pdf_link, url_type, download_selector, page_wait_selector = result
                logger.info(f"PMID {pmid} PDF链接: {pdf_link} url_type:{url_type}")

                pdf_path = download_pdf_sync(
                    pdf_link, pmid, url_type,
                    download_selector, page_wait_selector,
                    progress_callback
                )

                if pdf_path:
                    return pdf_path

        return None

    except Exception as e:
        logger.error(f"处理PMID {pmid} 时出错: {str(e)}")
        progress_callback("下载失败！", False)
        return None


async def get_pdf_from_pubmed(
        pmid: str,
        pmcid: str,
        executor: ThreadPoolExecutor,
        progress_callback
) -> Optional[Path]:
    """
    异步接口：使用线程池执行同步函数（带总超时）

    Args:
        pmid: PMID编号
        pmcid: PMCID编号（可选）
        executor: 线程池执行器
        progress_callback: 进度回调函数

    Returns:
        Optional[Path]: 下载成功返回PDF路径，失败返回None
    """
    loop = asyncio.get_running_loop()

    try:
        # 设置总超时时间为 120 秒
        return await asyncio.wait_for(
            loop.run_in_executor(
                executor,
                get_pdf_from_pubmed_sync,
                pmid,
                pmcid,
                progress_callback
            ),
            timeout=120.0
        )
    except asyncio.TimeoutError:
        logger.error(f"获取PMID {pmid} 的PDF超时（120秒）")
        progress_callback("下载超时（120秒），已跳过", False)
        return None
    except Exception as e:
        logger.error(f"获取PMID {pmid} 的PDF时出错: {str(e)}")
        progress_callback(f"下载失败: {str(e)}", False)
        return None