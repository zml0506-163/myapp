import re
from typing import Optional, Tuple
from urllib.parse import urljoin
from DrissionPage import Chromium
from DrissionPage._configs.chromium_options import ChromiumOptions
import requests
from bs4 import BeautifulSoup

# ========== 出版商规则函数 ==========

def parse_wiley(publisher_url: str, html: str) -> tuple[str, str, str, str] | None:
    """规则1: Wiley 出版社，直接拼接 pdfdirect 链接"""
    # 例: https://onlinelibrary.wiley.com/doi/10.1111/jcmm.70836
    #     https://onlinelibrary.wiley.com/doi/epdf/10.1111/jcmm.70836
    # PDF: https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/jcmm.70836?download=true
    if "/doi/" in publisher_url:
        # 返回pdf预览页面
        return publisher_url.replace("/doi/", "/doi/epdf/"), "webview" , None, None
    return None


def parse_bmj(publisher_url: str, html: str) -> tuple[str, str, str, str] | None:
    """解析 BMJ (jitc.bmj.com) 出版商页面，拼接 PDF 链接"""
    try:
        # 1. 从 publisher_url 提取 PMID
        m = re.search(r"pmid=(\d+)", publisher_url)
        if not m:
            return None
        pmid = m.group(1)

        # 2. PubMed efetch 获取 DOI
        efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        params = {"db": "pubmed", "id": pmid, "retmode": "xml"}
        r = requests.get(efetch_url, params=params, timeout=10)
        r.raise_for_status()
        xml = r.text

        m = re.search(r'<ArticleId IdType="doi">([^<]+)</ArticleId>', xml)
        if not m:
            return None
        doi = m.group(1)

        # 3. 用 Crossref API 查询 volume 和 issue
        crossref_url = f"https://api.crossref.org/works/{doi}"
        cr = requests.get(crossref_url, timeout=10).json()
        message = cr.get("message", {})
        volume = message.get("volume")
        issue = message.get("issue")
        if not volume or not issue:
            return None

        # 4. 生成 eID，比如 DOI: 10.1136/jitc-2025-012357 → e012357
        eid = "e" + doi.split("-")[-1]

        # 5. 拼接 BMJ PDF 链接
        pdf_url = f"https://jitc.bmj.com/content/jitc/{volume}/{issue}/{eid}.full.pdf"
        return pdf_url , "pdf", None, None

    except Exception as e:
        print(f"[BMJ] 解析失败: {e}")
        return None


def parse_default(publisher_url: str, html: str) -> tuple[str, str, str, str] | None:
    """规则3: 默认逻辑，用 BeautifulSoup 找 <a> 标签中包含 pdf 的链接"""
    soup = BeautifulSoup(html, "html.parser")
    meta_tag = soup.find('meta', {'name': 'citation_pdf_url'})
    # 提取 content 属性的值（即 PDF 链接）
    if meta_tag:
        pdf_url = meta_tag.get('content')
        return pdf_url
    for a in soup.find_all("a", href=True):
        if "pdf" in a["href"].lower() or "pdf" in a.text.lower():
            return urljoin(publisher_url, a["href"])
    return None


def parse_custom_example(publisher_url: str, html: str) -> tuple[str, str, str, str] | None:
    """规则2: 某些出版商，PDF链接在 <button> 或 <p> 标签里"""
    soup = BeautifulSoup(html, "html.parser")
    # 举例：查找 data-pdf 属性的按钮
    btn = soup.find("button", {"data-pdf": True})
    if btn:
        return urljoin(publisher_url, btn["data-pdf"])
    return None


def parse_skip(publisher_url: str, html: str) -> tuple[str, str, str, str] | None:
    """规则4: 无法处理，直接返回 None"""
    return None


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://pubmed.ncbi.nlm.nih.gov/',
    'Accept-Language': 'en-US,en;q=0.5'
}


def parse_cell(publisher_url: str, html: str) -> tuple[str, str, str, str] | None:
    # 创建配置对象
    co = ChromiumOptions()
    # 设置不加载图片、静音
    # co.no_imgs(True).mute(True)
    # co.incognito()  # 匿名模式
    # co.headless()  # 无头模式
    # co.set_argument('--no-sandbox')  # 无沙盒模式

    # 初始化浏览器并打开页面
    browser = Chromium(addr_or_opts=co)
    tab = browser.new_tab("https://www.cell.com/cell-reports-medicine/fulltext/S2666-3791(25)00423-9")

    elem = tab.ele('xpath://*[@id="article_more_menu"]/ul/li[1]/div/div/ul/li[1]/a', timeout=15)
    link = elem.attr("href")
    browser.quit()
    download_selector = "#thumbnails"
    page_wait_selector = "#download"
    if link:
        return urljoin(publisher_url, link), "webview", download_selector, page_wait_selector
    return None


def parse_elsevier(publisher_url: str, html: str) -> tuple[str, str, str, str] | None:
    # https://linkinghub.elsevier.com/retrieve/pii/S2666-3791(25)00423-9
    # https://www.cell.com/cell-reports-medicine/fulltext/S2666-3791(25)00423-9
    new_publisher_url = publisher_url.replace("https://linkinghub.elsevier.com/retrieve/pii/", "https://www.cell.com/cell-reports-medicine/fulltext/")
    return parse_cell(new_publisher_url, html)

# ========== 出版商映射表 ==========

PUBLISHER_RULES = {
    "onlinelibrary.wiley.com": parse_wiley,   # onlinelibrary.wiley.com
    "jitc.bmj.com": parse_bmj,  #jitc.bmj.com
    "www.cell.com": parse_cell, #www.cell.com
    "linkinghub.elsevier.com": parse_elsevier,
    # 其他域名可以继续添加
}

# 默认解析方法
DEFAULT_RULE = parse_default


def get_pdf_path_from_pmcid(pmcid: str):
    # 1. 用 PMCID 查询 oa.fcgi
    oa_url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"
    response = requests.get(oa_url)
    oa_xml = response.text

    soup = BeautifulSoup(oa_xml, "xml")
    # 优先直接 PDF 链接
    pdf_link = soup.find("link", {"format": "pdf"})
    if pdf_link:
        pdf_url = pdf_link["href"]
        return pdf_url

    # 其次 tgz 包
    tgz_link = soup.find("link", {"format": "tgz"})
    if tgz_link:
        tgz_url = tgz_link["href"]
        return tgz_url
    return None