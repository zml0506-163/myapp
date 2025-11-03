import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning
import time
from http.client import IncompleteRead

# 忽略SSL证书验证警告（仅在必要时使用）
urllib3.disable_warnings(InsecureRequestWarning)

# 假设这些变量已定义
url = 'http://apps.who.int/iris/bitstream/10665/78128/3/9789241505147_eng.pdf'
BASE_DIR = "D:\\pythonwork\\pubmed_app\\storage\\pdfs"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://pubmed.ncbi.nlm.nih.gov/',
    'Accept-Language': 'en-US,en;q=0.5'
}

def download_pdf_with_urllib(url: str, filename: str):
    """使用urllib尝试下载，作为备用方案"""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as response:
            content = response.read()
            # 验证PDF文件头
            if content.startswith(b"%PDF"):
                path = f"{BASE_DIR}/{filename}"
                with open(path, "wb") as f:
                    f.write(content)
                print(f"urllib成功下载: {filename}")
                return path
            else:
                print(f"urllib: 不是有效的PDF文件: {url}")
                return None
    except Exception as e:
        print(f"urllib下载失败: {str(e)}")
        return None

def download_pdf_sync(url: str, filename: str, max_retries: int = 3) :
    """同步下载PDF文件，增加多种错误处理策略"""
    # 先尝试requests方法
    retries = 0
    while retries < max_retries:
        try:
            # 尝试不同的请求头配置
            headers = HEADERS.copy()

            # 尝试1: 禁用分块传输
            # if retries == 0:
            #     headers["Accept-Encoding"] = "identity"
            # # 尝试2: 允许gzip压缩
            # elif retries == 1:
            #     headers["Accept-Encoding"] = "gzip, deflate, br"
            # # 尝试3: 不指定编码
            # else:
            #     headers.pop("Accept-Encoding", None)

            # 发送请求下载PDF，verify=False跳过SSL验证（仅在必要时使用）
            with requests.get(
                    url,
                    headers=headers,
                    timeout=60,
                    stream=True,
                    verify=False  # 注意：这会降低安全性，仅在必要时使用
            ) as resp:
                if resp.status_code == 200:
                    # 不检查Content-Type，有些服务器可能返回不正确的类型
                    path = f"{BASE_DIR}/{filename}"

                    # 尝试读取所有内容而不是分块
                    try:
                        content = resp.content
                        if content.startswith(b"%PDF"):
                            with open(path, "wb") as f:
                                f.write(content)
                            print(f"成功下载: {filename}")
                            return path
                        else:
                            print(f"不是有效的PDF文件: {url}")
                            return None
                    except IncompleteRead:
                        # 处理不完整读取的情况
                        print(f"读取不完整，尝试分块方式...")
                        first_bytes = resp.raw.read(4)
                        if first_bytes == b"%PDF":
                            with open(path, "wb") as f:
                                f.write(first_bytes)
                                for chunk in resp.iter_content(chunk_size=1024):
                                    if chunk:
                                        f.write(chunk)
                            print(f"分块方式成功下载: {filename}")
                            return path
                        else:
                            print(f"不是有效的PDF文件: {url}")
                            return None
                else:
                    print(f"下载失败，状态码: {resp.status_code}")
                    retries += 1
                    if retries < max_retries:
                        time.sleep(2)
                        continue
                    return None

        except Exception as e:
            print(f"下载错误（{retries+1}/{max_retries}）: {str(e)}")
            retries += 1
            if retries < max_retries:
                time.sleep(2)
                continue
            # 所有重试都失败，尝试备用方案
            print("尝试使用urllib作为备用方案...")
            return download_pdf_with_urllib(url, filename)

    # 所有方法都失败
    print(f"所有方法都失败，下载失败: {url}")
    return None

# 测试特定URL
download_pdf_sync(url, "who_document.pdf")
