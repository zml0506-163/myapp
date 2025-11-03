import os
import warnings

import requests
import urllib3
from DrissionPage import Chromium
from DrissionPage._configs.chromium_options import ChromiumOptions

# # 创建配置对象（默认从 ini 文件中读取配置）
# co = ChromiumOptions()
# # 设置不加载图片、静音
# co.no_imgs(True).mute(True)
# co.incognito()  # 匿名模式
# # co.headless()  # 无头模式
# co.set_argument('--no-sandbox')  # 无沙盒模式
# co.set_download_path("D:\\pythonwork\\pubmed_app\\storage\\pdfs")
# tab = Chromium(addr_or_opts=co).latest_tab
# tab.get('https://jitc.bmj.com/content/13/9/e012211')
# tab.download("https://jitc.bmj.com/content/jitc/13/9/e012211.full.pdf", "D:\\pythonwork\\pubmed_app\\storage\\pdfs")

from DrissionPage import SessionPage

# url = 'https://europepmc.org/articles/PMC12411929?pdf=render'
# url = 'https://www.cell.com/action/showPdf?pii=S2666-3791%2825%2900423-9'
url = 'https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC12483169&blobtype=pdf'
BASE_DIR = "D:\\pythonwork\\pubmed_app\\storage\\pdfs"
#
# page = SessionPage()
# page.download(url, BASE_DIR)


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}


def download_pdf_sync(url: str, filename: str):
    """同步下载PDF文件（复用requests确保成功率）"""
    try:
        warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
        # 发送请求下载PDF
        with requests.get(url, headers=HEADERS, timeout=60, stream=True, verify=False) as resp:
            # 验证响应状态和内容类型
            if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("application/pdf"):
                path = BASE_DIR + "/" + filename
                # 验证PDF文件头
                content = resp.content
                if content.startswith(b"%PDF"):
                    with open(path, "wb") as f:
                        f.write(content)
                    print(f"成功下载: {filename}")
                    return path
                else:
                    print(f"不是有效的PDF文件: {url}")
                    return None
            else:
                print(f"下载失败，状态码: {resp.status_code}，内容类型: {resp.headers.get('Content-Type')}")
    except Exception as e:
        print(f"下载PDF时出错: {str(e)}")
    return None

download_pdf_sync(url, "test.pdf")

