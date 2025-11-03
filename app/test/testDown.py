import os
import requests
from urllib.parse import quote

# === 配置 ===
SEARCH_QUERY = "(cancer) AND ((HAS_FREE_FULLTEXT:Y) OR HAS_FT:Y) AND (HAS_PDF:Y)"
RESULTS_LIMIT = 10
SAVE_DIR = "pdfs"
os.makedirs(SAVE_DIR, exist_ok=True)

def search_europe_pmc(query, limit=10):
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {
        "query": query,
        "format": "json",
        "pageSize": limit
    }
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json().get("resultList", {}).get("result", [])

def get_pdf_url(record):
    # Europe PMC 并不会直接返回 pdf 字段，只能通过 PMCID 构造 PDF 访问地址
    pmcid = record.get("pmcid")
    if not pmcid:
        return None
    # Europe PMC 的开放PDF地址通常是：https://europepmc.org/articles/{PMCID}?pdf=render
    return f"https://europepmc.org/articles/{pmcid}?pdf=render"

def download_pdf(url, filename):
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and "pdf" in r.headers.get("content-type", ""):
            with open(filename, "wb") as f:
                f.write(r.content)
            print(f"✅ 下载完成: {filename}")
        else:
            print(f"⚠️ 无法下载或不是PDF: {url}")
    except Exception as e:
        print(f"❌ 下载失败 {url}: {e}")

if __name__ == "__main__":
    print(f"🔍 正在检索 Europe PMC 文献: {SEARCH_QUERY}")
    records = search_europe_pmc(SEARCH_QUERY, RESULTS_LIMIT)

    for idx, rec in enumerate(records, start=1):
        title = rec.get("title", "No Title")
        pmcid = rec.get("pmcid")
        print(f"\n[{idx}] {title}")
        print(f"   PMCID: {pmcid}")
        pdf_url = get_pdf_url(rec)
        if pdf_url:
            print(f"   📎 PDF链接: {pdf_url}")
            filename = os.path.join(SAVE_DIR, f"{quote(title[:50])}.pdf")
            download_pdf(pdf_url, filename)
        else:
            print("   ⚠️ 未找到PDF链接")
