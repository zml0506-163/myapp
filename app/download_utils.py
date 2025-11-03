import io
import shutil
import socket
import tarfile
import warnings
from ftplib import error_perm, FTP

import requests

from DrissionPage import Chromium
from DrissionPage._configs.chromium_options import ChromiumOptions
from pathlib import Path
from typing import Optional, Callable

from urllib3.exceptions import InsecureRequestWarning

from app.core.config import settings

# PDF 保存目录
BASE_DIR = Path(settings.pdf_dir)
BASE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://pubmed.ncbi.nlm.nih.gov/',
    'Accept-Language': 'en-US,en;q=0.5'
}

DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}


def download_pdf_from_webview(pdf_link, pmid, download_selector, page_wait_selector, progress_callback):
    # 确保BASE_DIR是Path对象
    if not isinstance(BASE_DIR, Path):
        base_dir = Path(BASE_DIR)
    else:
        base_dir = BASE_DIR

    if download_selector is None:
        download_selector = 'xpath://*[@id="app-navbar"]/div[3]/div[3]/a'

    if page_wait_selector is None:
        page_wait_selector = '#info-tab-pane'

    # 创建临时下载目录
    temp_path = base_dir / pmid
    try:
        if not temp_path.exists():
            temp_path.mkdir(parents=True, exist_ok=True)

        progress_callback(" 尝试抓取...", False)
        # 初始化浏览器设置
        co = ChromiumOptions()
        co.set_download_path(temp_path.absolute())

        # 初始化浏览器并打开页面
        browser = Chromium(addr_or_opts=co)
        tab = browser.new_tab(pdf_link)

        # 等待页面加载
        tab.wait.doc_loaded()

        try:
            # 等待信息面板显示
            page = tab.ele(page_wait_selector)
            page.wait.displayed(timeout=15)

            # 定位并点击下载按钮
            download_btn = tab.ele(download_selector)
            download_btn.wait.displayed(timeout=15)
            tab.set.download_path(temp_path.absolute())
            tab.set.download_file_name(name=pmid, suffix='pdf')
            download_btn.click()
            # 等待下载完成
            tab.wait.download_begin()
            tab.wait.downloads_done()

        except Exception as e:
            progress_callback("抓取PDF预览页面失败...", False)
            print(f"操作出错: {str(e)}")

        # 关闭浏览器
        browser.quit()

        # 查找下载的PDF文件
        pdf_files = list(temp_path.glob("*.pdf"))
        if not pdf_files:
            # 没找到PDF文件
            progress_callback("下载失败！", False)
            return None

        # 取第一个找到的PDF文件
        downloaded_pdf = pdf_files[0]

        # 目标文件路径
        target_pdf = base_dir / f"{pmid}.pdf"

        # 如果目标文件已存在，先删除
        if target_pdf.exists():
            target_pdf.unlink()

        # 重命名并移动文件到BASE_DIR
        shutil.move(str(downloaded_pdf), str(target_pdf))

        # 返回成功下载的文件路径
        return str(target_pdf)

    except Exception as e:
        print(f"处理文件时出错: {str(e)}")
        return None

    finally:
        # 确保临时目录被删除，无论成功失败
        if temp_path.exists():
            try:
                shutil.rmtree(temp_path)
                print(f"已清理临时目录: {temp_path}")
            except Exception as e:
                print(f"清理临时目录时出错: {str(e)}")


def download_pdf_from_tgz_sync(url: str, filename: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """下载 tar.gz 包并提取 PDF 文件（支持HTTP/HTTPS和FTP协议）"""
    # 禁用警告
    warnings.filterwarnings("ignore", category=InsecureRequestWarning)

    try:
        if url.startswith(('http://', 'https://')):
            # 处理HTTP/HTTPS链接
            with requests.get(url, headers=DOWNLOAD_HEADERS, timeout=60, stream=True, verify=False) as resp:
                return _handle_tgz_http_response(resp, url, filename, progress_callback)

        elif url.startswith('ftp://'):
            # 处理FTP链接
            return _download_tgz_from_ftp(url, filename, progress_callback)

        else:
            progress_callback(f"不支持的协议: {url.split('://')[0]}", False)
            print(f"不支持的协议: {url.split('://')[0]}")
            return None

    except Exception as e:
        print(f"处理tar.gz时出错: {str(e)}")
        progress_callback(f"处理失败，错误: {str(e)}", False)
        return None

def _handle_tgz_http_response(resp, url: str, filename: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """处理HTTP/HTTPS响应并提取PDF文件"""
    if resp.status_code == 200 and (
            resp.headers.get("Content-Type", "").startswith("application/x-gzip")
            or resp.headers.get("Content-Type", "").startswith("application/gzip")
    ):
        return _extract_pdf_from_tgz_content(resp.content, filename, url, progress_callback)
    else:
        error_msg = f"下载失败，状态码: {resp.status_code}"
        if resp.status_code == 403:
            error_msg = "下载失败，可能存在人工校验，被网站拒绝！"
        elif resp.status_code == 404:
            error_msg = "下载失败，地址不存在！"

        progress_callback(error_msg, False)
        print(f"{error_msg}，内容类型: {resp.headers.get('Content-Type')}")

    return None


def _download_pdf_from_ftp(url: str, filename: str, progress_callback):
    try:
        # 解析FTP URL
        url_parts = url.split('ftp://')[1].split('/')
        host_part = url_parts[0]
        file_path = '/'.join(url_parts[1:]) if len(url_parts) > 1 else ''

        if '@' in host_part:
            user_pass, host = host_part.split('@', 1)
            if ':' in user_pass:
                username, password = user_pass.split(':', 1)
            else:
                username = user_pass
                password = ''
        else:
            host = host_part
            username = 'anonymous'
            password = ''

        # 设置超时参数
        timeout = 10
        pdf_content = io.BytesIO()

        # 建立FTP连接
        with FTP(host, timeout=timeout) as ftp:
            ftp.login(username, password)
            ftp.set_pasv(True)  # 启用被动模式
            ftp.sock.settimeout(30)  # 数据连接超时

            # 检查文件存在
            try:
                file_size = ftp.size(file_path)
                progress_callback(f"开始下载PDF文件，总大小: {file_size // 1024} KB", True)
            except error_perm as e:
                if '550' in str(e):
                    progress_callback(f"FTP文件不存在: {url}", False)
                    return None
                else:
                    raise

            total_bytes = 0

            def _progress(chunk):
                nonlocal total_bytes
                total_bytes += len(chunk)
                # 每100KB更新一次进度
                if total_bytes % (1024 * 100) < len(chunk) or total_bytes == file_size:
                    progress = f"已下载 {total_bytes // 1024} KB"
                    if file_size > 0:
                        progress += f" ({total_bytes / file_size:.1%})"
                    progress_callback(progress, True)
                pdf_content.write(chunk)

            # 下载文件
            ftp.retrbinary(f'RETR {file_path}', _progress)

            pdf_content.seek(0)
            content = pdf_content.getvalue()

            # 验证PDF文件有效性
            if not content.startswith(b"%PDF"):
                progress_callback(f"下载的文件不是有效的PDF: {url}", False)
                return None

            # 保存PDF文件
            path = BASE_DIR / filename
            with open(path, "wb") as out:
                out.write(content)

            progress_callback(f"PDF文件下载成功: {filename}", True)
            print(f"成功保存PDF: {filename}")
            return path

    except socket.timeout:
        msg = f"FTP下载超时: {url}"
        progress_callback(msg, False)
        print(msg)
    except error_perm as e:
        msg = f"FTP权限错误: {str(e)}"
        progress_callback(msg, False)
        print(msg)
    except Exception as e:
        msg = f"FTP下载错误: {str(e)}"
        progress_callback(msg, False)
        print(msg)

    return None


def _download_tgz_from_ftp(url: str, filename: str, progress_callback):
    try:
        # 解析FTP URL
        url_parts = url.split('ftp://')[1].split('/')
        host_part = url_parts[0]
        file_path = '/'.join(url_parts[1:]) if len(url_parts) > 1 else ''

        if '@' in host_part:
            user_pass, host = host_part.split('@', 1)
            if ':' in user_pass:
                username, password = user_pass.split(':', 1)
            else:
                username = user_pass
                password = ''
        else:
            host = host_part
            username = 'anonymous'
            password = ''

        # 设置超时参数（例如：10秒）
        timeout = 10
        tgz_content = io.BytesIO()

        # 建立FTP连接
        with FTP(host, timeout=timeout) as ftp:
            ftp.login(username, password)
            ftp.set_pasv(True)  # 建议启用被动模式
            ftp.sock.settimeout(30)  # 控制数据连接超时（部分服务器会用另一个socket）

            # 检查文件存在
            try:
                ftp.size(file_path)
            except error_perm as e:
                if '550' in str(e):
                    progress_callback(f"FTP文件不存在: {url}", False)
                    return None
                else:
                    raise

            total_bytes = 0

            def _progress(chunk):
                nonlocal total_bytes
                total_bytes += len(chunk)
                if total_bytes % (1024 * 100) < len(chunk):  # 每100KB输出一次
                    progress_callback(f"已下载 {total_bytes // 1024} KB...", True)
                tgz_content.write(chunk)

            # 下载文件
            ftp.retrbinary(f'RETR {file_path}', _progress)

            tgz_content.seek(0)

        return _extract_pdf_from_tgz_content(tgz_content.getvalue(), filename, url, progress_callback)

    except socket.timeout:
        msg = f"FTP下载超时: {url}"
        progress_callback(msg, False)
        print(msg)
    except error_perm as e:
        msg = f"FTP权限错误: {str(e)}"
        progress_callback(msg, False)
        print(msg)
    except Exception as e:
        msg = f"FTP下载错误: {str(e)}"
        progress_callback(msg, False)
        print(msg)

    return None

def _extract_pdf_from_tgz_content(content: bytes, filename: str, url: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """从tar.gz内容中提取PDF文件"""
    try:
        # 读取 tar.gz 文件
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
            pdf_members = [m for m in tar.getmembers() if m.name.endswith(".pdf")]

            if not pdf_members:
                progress_callback(f"下载失败，tar.gz 内未找到 PDF 文件: {url}", False)
                return None

            # 提取第一个PDF文件（如果有多个）
            member = pdf_members[0]
            with tar.extractfile(member) as f:
                if f:
                    pdf_content = f.read()
                    # 验证是否为PDF文件
                    if pdf_content.startswith(b"%PDF"):
                        # 保存到目标文件
                        path = BASE_DIR / filename
                        with open(path, "wb") as out:
                            out.write(pdf_content)
                        print(f"成功从 tar.gz 提取 PDF: {filename}")
                        progress_callback(f"成功从 tar.gz 提取 PDF: {filename}", True)
                        return path
                    else:
                        progress_callback(f"tar.gz 中的文件不是有效的PDF: {url}", False)
                        print(f"tar.gz 中的文件不是有效的PDF: {url}")
                        return None

    except tarfile.TarError as e:
        print(f"tar.gz 文件格式错误: {e}")
        progress_callback(f"下载失败，tar.gz 文件格式错误！", False)
    except Exception as e:
        print(f"解压 tar.gz 出错: {e}")
        progress_callback(f"下载失败，解压 tar.gz 出错！", False)

    return None



def download_pdf_sync(url: str, filename: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """同步下载PDF文件（支持HTTP/HTTPS和FTP协议）"""
    # 禁用警告
    warnings.filterwarnings("ignore", category=InsecureRequestWarning)

    try:
        if url.startswith(('http://', 'https://')):
            # 处理HTTP/HTTPS链接
            with requests.get(url, headers=DOWNLOAD_HEADERS, timeout=60, stream=True, verify=False) as resp:
                return _handle_http_response(resp, url, filename, progress_callback)

        elif url.startswith('ftp://'):
            # 处理FTP链接
            return _download_pdf_from_ftp(url, filename, progress_callback)

        else:
            progress_callback(f"不支持的协议: {url.split('://')[0]}", False)
            print(f"不支持的协议: {url.split('://')[0]}")
            return None

    except Exception as e:
        print(f"下载PDF时出错: {str(e)}")
        progress_callback(f"下载失败，错误: {str(e)}", False)
        return None

def _handle_http_response(resp, url: str, filename: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """处理HTTP/HTTPS响应并保存PDF文件"""
    if resp.status_code in (200, 299) and resp.headers.get("Content-Type", "").startswith("application/pdf"):
        path = BASE_DIR / filename
        # 验证PDF文件头
        content = resp.content
        if content.startswith(b"%PDF"):
            with open(path, "wb") as f:
                f.write(content)
            print(f"成功下载: {filename}")
            progress_callback(f"成功下载: {filename}", True)
            return path
        else:
            progress_callback(f"下载失败【不是PDF】：{url}", False)
            print(f"不是有效的PDF文件: {url}")
    else:
        error_msg = f"下载失败，状态码: {resp.status_code}"
        if resp.status_code == 403:
            error_msg = "下载失败，可能存在人工校验，被网站拒绝！"
        elif resp.status_code == 404:
            error_msg = "下载失败，地址不存在！"

        progress_callback(error_msg, False)
        print(f"{error_msg}，内容类型: {resp.headers.get('Content-Type')}")

    return None

def download_with_timeout(ftp, file_path, timeout=30):
    """手动实现 retrbinary，支持数据连接超时"""
    # 创建数据连接
    conn = ftp.transfercmd(f'RETR {file_path}')
    conn.settimeout(timeout)

    buffer = io.BytesIO()
    try:
        while True:
            block = conn.recv(8192)
            if not block:
                break
            buffer.write(block)
    finally:
        conn.close()
    # 完成数据接收
    ftp.voidresp()
    buffer.seek(0)
    return buffer

def _download_tgz_from_ftp(url: str, filename: str, progress_callback):
    try:
        url_parts = url.split('ftp://')[1].split('/')
        host_part = url_parts[0]
        file_path = '/'.join(url_parts[1:]) if len(url_parts) > 1 else ''

        if '@' in host_part:
            user_pass, host = host_part.split('@', 1)
            if ':' in user_pass:
                username, password = user_pass.split(':', 1)
            else:
                username = user_pass
                password = ''
        else:
            host = host_part
            username = 'anonymous'
            password = ''

        # 连接 + 控制连接超时
        ftp = FTP(host, timeout=10)
        ftp.login(username, password)
        ftp.set_pasv(True)

        try:
            ftp.size(file_path)
        except error_perm as e:
            if '550' in str(e):
                progress_callback(f"FTP文件不存在: {url}", False)
                return None
            else:
                raise

        # 关键：手动控制数据连接
        progress_callback(f"开始下载 {file_path}", True)
        tgz_content = download_with_timeout(ftp, file_path, timeout=20)
        progress_callback(f"下载完成 {len(tgz_content.getvalue()) // 1024} KB", True)

        ftp.quit()

        # 提取PDF
        return _extract_pdf_from_tgz_content(tgz_content.getvalue(), filename, url, progress_callback)

    except socket.timeout:
        msg = f"FTP下载超时: {url}"
        progress_callback(msg, False)
        print(msg)
    except error_perm as e:
        msg = f"FTP权限错误: {str(e)}"
        progress_callback(msg, False)
        print(msg)
    except Exception as e:
        msg = f"FTP下载错误: {str(e)}"
        progress_callback(msg, False)
        print(msg)

    return None


# def scihub_search_download(pmid):
#     paper_type = "pmid"
#     out = f"{BASE_DIR.absolute()}/{pmid}.pdf"
#     scihub_download(pmid, paper_type = paper_type, out=out)


def fetch_sync(url: str) -> str:
    """同步获取网页内容（复用已验证的requests逻辑）"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"请求失败: {resp.status_code}")
        resp.encoding = "utf-8"  # 显式指定编码
        return resp.text
    except Exception as e:
        raise Exception(f"获取页面 {url} 失败: {str(e)}")



def download_pdf(pmid, pdf_link,progress_callback, url_type, download_selector, page_wait_selector):
    progress_callback(f", 发现<a target='_blank' href='{pdf_link}'>PDF</a>", False)
    progress_callback(f", 开始下载...", False)

    if url_type == "tgz":
        pdf_path = download_pdf_from_tgz_sync(pdf_link, f"{pmid}.pdf", progress_callback)
    elif url_type == "webview":
        pdf_path = download_pdf_from_webview(pdf_link, pmid, download_selector, page_wait_selector, progress_callback)
    else:
        pdf_path = download_pdf_sync(pdf_link, f"{pmid}.pdf", progress_callback)
    if pdf_path:
        progress_callback(f" 下载并保存成功！", False)
    else:
        progress_callback(f" 下载失败！", False)
        return None
    return pdf_path