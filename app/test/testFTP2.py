import urllib.request
import os
from urllib.parse import urlparse
import time

def download_with_urllib(url, local_save_path, timeout=60, max_retries=3):
    """使用 urllib 下载 FTP 文件（内置库，支持 FTP 协议）"""
    retries = 0
    while retries < max_retries:
        try:
            # 创建本地目录
            local_dir = os.path.dirname(local_save_path)
            if local_dir and not os.path.exists(local_dir):
                os.makedirs(local_dir, exist_ok=True)

            # 设置超时和请求头（模拟浏览器，避免部分服务器拦截）
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            request = urllib.request.Request(url, headers=headers)

            # 下载文件（设置超时）
            with urllib.request.urlopen(request, timeout=timeout) as response, \
                    open(local_save_path, 'wb') as local_file:

                # 分块读取，适合大文件
                while True:
                    chunk = response.read(1024 * 1024)  # 1MB 块
                    if not chunk:
                        break
                    local_file.write(chunk)

            print(f"✅ 下载成功：{local_save_path}")
            return True

        except urllib.error.URLError as e:
            print(f"❌ 链接错误 {retries+1}/{max_retries}：{str(e)} - {url}")
        except TimeoutError:
            print(f"⏰ 超时重试 {retries+1}/{max_retries}：{url}")
        except Exception as e:
            print(f"❌ 下载失败 {retries+1}/{max_retries}：{str(e)} - {url}")

        retries += 1
        if retries < max_retries:
            time.sleep(2)  # 重试前等待 2 秒

    print(f"❌ 达到最大重试次数，放弃下载：{url}")
    return False

def batch_download(url_list, local_base_dir='downloads'):
    """批量下载 URL 列表中的文件"""
    for url in url_list:
        parsed = urlparse(url)
        if parsed.scheme != 'ftp':
            print(f"跳过非 FTP 链接：{url}")
            continue

        # 构建本地保存路径（保留远程目录结构）
        remote_path = parsed.path.lstrip('/')  # 去除开头的斜杠
        local_save_path = os.path.join(local_base_dir, remote_path)

        # 下载文件
        download_with_urllib(url, local_save_path)

if __name__ == "__main__":
    # 你的 FTP 文件列表
    ftp_urls = [
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/34/9d/main.PMC12550780.pdf",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/01/4d/jhc-12-2379.PMC12553378.pdf",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/42/98/main.PMC12549784.pdf",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/f6/6a/PMC12546027.tar.gz",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/e4/5d/PMC12549584.tar.gz",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/ba/4a/PMC12546131.tar.gz",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/73/93/PMC12548061.tar.gz",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/50/3f/PMC12545153.tar.gz",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/81/75/PMC12546077.tar.gz",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/31/73/PMC12546201.tar.gz",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/d2/93/PMC12546247.tar.gz",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/9a/c8/PMC12549545.tar.gz"
    ]

    # 开始批量下载
    batch_download(ftp_urls)