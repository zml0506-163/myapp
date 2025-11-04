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

from app.tools.download_utils import fetch_sync, download_pdf
from app.tools.publisher_rules import PUBLISHER_RULES, DEFAULT_RULE, get_pdf_path_from_pmcid
import xml.etree.ElementTree as ET


# NCBI E-utilities 基础地址
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

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
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒

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


def get_pdf_from_pubmed_sync(pmid: str, pmcid: str, progress_callback) -> Path | None:
    """同步版本：从PubMed获取PDF并下载"""
    try:
        progress_callback("开始查找PDF资源...", False)
        pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        progress_callback(f" 打开 <a target='_blank' href='{pubmed_url}'>{pubmed_url}</a>", False)
        html = fetch_sync(pubmed_url)
        soup = BeautifulSoup(html, "html.parser")

        links = soup.select("div.full-text-links div.full-text-links-list a")
        if not links:
            print(f"PMID {pmid} 未发现full text links")
            return None
        progress_callback(", 发现Full Text Links", False)
        """
        获取PDF下载地址几种方式：
        1、查看是否为PMC，如果是可以通过oa.fcgi接口获取pdf下载地址
        2、通过metapub的FindIt方法获取
        3、通过full text link的详情页面爬虫获取
        """
        # 1、查看是否为PMC，如果是可以通过oa.fcgi接口获取pdf下载地址
        if pmcid is not None:
            progress_callback(f", 发现PMC资源", False)
            pdf_link = get_pdf_path_from_pmcid(pmcid)
            if pdf_link is not None:
                url_type = "pdf"
                if pdf_link.endswith(".tar.gz"):
                    url_type = "tgz"
                pdf_path = download_pdf(pmid, pdf_link, progress_callback, url_type, None, None)
                return pdf_path
        # 2、通过metapub的FindIt方法获取
        pdf_link = find_pdf_links_by_metapub(pmid)
        # pdf_link = FindIt(pmid).url  # 通过FindIt可以获取到pdf下载链接
        if pdf_link:
            progress_callback(f", 发现PDF资源", False)
            pdf_path = download_pdf(pmid, pdf_link, progress_callback, "pdf", None, None)
            return pdf_path
        if not pdf_link:
            # 3、通过full text link的详情页面爬虫获取
            for link in links:
                full_text_link = link.get("href")
                # action = link.get("data-ga-action")
                # if action == "PMC":
                # 如果还是没有，再通过出版商页面爬虫获取, 爬虫比较容易被人机校验拦截导致访问403
                publisher_url = urljoin(pubmed_url, full_text_link)
                progress_callback(f", 访问<a target='_blank' href='{publisher_url}'>出版商页面</a>", False)

                # 获取域名，选择对应规则
                domain = urlparse(publisher_url).netloc
                parser = PUBLISHER_RULES.get(domain, DEFAULT_RULE)

                # 如果是需要访问详情页的规则，先获取页面
                if parser == DEFAULT_RULE:
                    html2 = fetch_sync(publisher_url)
                else:
                    html2 = ""

                pdf_link, url_type,  download_selector, page_wait_selector = parser(publisher_url, html2)
                if not pdf_link:
                    continue
                print(f"PMID {pmid} PDF链接: {pdf_link} url_type:{url_type}")
                pdf_path = download_pdf(pmid, pdf_link, progress_callback, url_type, download_selector, page_wait_selector)
                if pdf_path is None:
                    continue
                return pdf_path
        return None
    except Exception as e:
        print(f"处理PMID {pmid} 时出错: {str(e)}")
        progress_callback(f" 下载失败！", False)
        return None


async def get_pdf_from_pubmed(pmid: str, pmcid: str, executor: ThreadPoolExecutor, progress_callback) -> Optional[Path]:
    """异步接口：使用线程池执行同步函数"""
    loop = asyncio.get_running_loop()
    # 在线程池中运行同步函数
    try:
        # 在线程池中运行同步函数
        return await loop.run_in_executor(
            executor,
            get_pdf_from_pubmed_sync,
            pmid,
            pmcid,
            progress_callback # progress_callback用于给前端返回SSE结果
        )
    except Exception as e:
        # 记录错误并返回None
        logger.error(f"获取PMID {pmid} 的PDF时出错: {str(e)}")
        return None


