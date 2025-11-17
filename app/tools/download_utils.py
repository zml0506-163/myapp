import io
import shutil
import socket
import tarfile
import warnings
from ftplib import error_perm, FTP
import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import requests
import time

from DrissionPage import Chromium
from DrissionPage._configs.chromium_options import ChromiumOptions
from pathlib import Path
from typing import Optional, Callable

from app.core.config import settings

# PDF 保存目录
BASE_DIR = Path(settings.pdf_dir)
BASE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

# 超时设置（秒）
# DOWNLOAD_TIMEOUT 作为“空闲读超时”，每次读取或网络空闲超过该时间将超时
DOWNLOAD_TIMEOUT = settings.pdf_download_idle_timeout
EXTRACT_TIMEOUT = 30   # 解压超时
WEBVIEW_TIMEOUT = 90   # 浏览器抓取超时


def download_pdf_from_webview(pdf_link, pmid, download_selector, page_wait_selector, progress_callback):
    """浏览器抓取PDF（带超时控制）"""
    if not isinstance(BASE_DIR, Path):
        base_dir = Path(BASE_DIR)
    else:
        base_dir = BASE_DIR

    if download_selector is None:
        download_selector = 'xpath://*[@id="app-navbar"]/div[3]/div[3]/a'

    if page_wait_selector is None:
        page_wait_selector = '#info-tab-pane'

    temp_path = base_dir / pmid
    browser = None

    try:
        if not temp_path.exists():
            temp_path.mkdir(parents=True, exist_ok=True)

        progress_callback("尝试抓取...", False)

        co = ChromiumOptions()
        co.set_download_path(temp_path.absolute())

        browser = Chromium(addr_or_opts=co)
        tab = browser.new_tab(pdf_link)

        tab.wait.doc_loaded()

        try:
            page = tab.ele(page_wait_selector)  # type: ignore
            if page is None:
                raise Exception(f"未找到页面元素: {page_wait_selector}")
            page.wait.displayed(timeout=15)  # type: ignore

            download_btn = tab.ele(download_selector)  # type: ignore
            if download_btn is None:
                raise Exception(f"未找到下载按钮: {download_selector}")
            download_btn.wait.displayed(timeout=15)  # type: ignore
            tab.set.download_path(str(temp_path.absolute()))
            tab.set.download_file_name(name=pmid, suffix='pdf')
            download_btn.click()  # type: ignore

            tab.wait.download_begin()
            tab.wait.downloads_done()

        except Exception as e:
            progress_callback("抓取PDF预览页面失败", False)
            print(f"操作出错: {str(e)}")
            return None

        pdf_files = list(temp_path.glob("*.pdf"))
        if not pdf_files:
            progress_callback("下载失败！", False)
            return None

        downloaded_pdf = pdf_files[0]
        target_pdf = base_dir / f"{pmid}.pdf"

        if target_pdf.exists():
            target_pdf.unlink()

        shutil.move(str(downloaded_pdf), str(target_pdf))
        return str(target_pdf)

    except Exception as e:
        print(f"处理文件时出错: {str(e)}")
        progress_callback(f"抓取失败: {str(e)}", False)
        return None

    finally:
        if browser:
            try:
                browser.quit()
            except:
                pass

        if temp_path.exists():
            try:
                shutil.rmtree(temp_path)
            except Exception as e:
                print(f"清理临时目录时出错: {str(e)}")


def download_pdf_from_tgz_sync(url: str, filename: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """下载 tar.gz 包并提取 PDF 文件（带超时控制）"""
    warnings.filterwarnings("ignore", category=InsecureRequestWarning)

    try:
        if url.startswith(('http://', 'https://')):
            with requests.get(url, headers=DOWNLOAD_HEADERS, timeout=DOWNLOAD_TIMEOUT, stream=True, verify=False) as resp:
                return _handle_tgz_http_response(resp, url, filename, progress_callback)

        elif url.startswith('ftp://'):
            return _download_tgz_from_ftp(url, filename, progress_callback)

        else:
            progress_callback(f"不支持的协议: {url.split('://')[0]}", False)
            return None

    except requests.Timeout:
        progress_callback(f"下载超时（{DOWNLOAD_TIMEOUT}秒）", False)
        return None
    except Exception as e:
        print(f"处理tar.gz时出错: {str(e)}")
        progress_callback(f"处理失败: {str(e)}", False)
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
            error_msg = "下载失败，被网站拒绝"
        elif resp.status_code == 404:
            error_msg = "下载失败，地址不存在"

        progress_callback(error_msg, False)
        print(f"{error_msg}，内容类型: {resp.headers.get('Content-Type')}")

    return None


def _download_pdf_from_ftp(url: str, filename: str, progress_callback):
    """FTP下载PDF（带超时控制）"""
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

        timeout = 30
        pdf_content = io.BytesIO()

        with FTP(host, timeout=timeout) as ftp:
            ftp.login(username, password)
            ftp.set_pasv(True)
            if ftp.sock:
                # 空闲读超时：若超过该时间没有数据返回，则抛出超时
                ftp.sock.settimeout(DOWNLOAD_TIMEOUT)

            try:
                file_size = ftp.size(file_path)
                if file_size:
                    progress_callback(f"开始下载PDF文件，总大小: {file_size // 1024} KB", True)
            except error_perm as e:
                if '550' in str(e):
                    progress_callback(f"FTP文件不存在", False)
                    return None
                else:
                    raise

            total_bytes = 0

            def _progress(chunk):
                nonlocal total_bytes
                total_bytes += len(chunk)
                if total_bytes % (1024 * 100) < len(chunk) or total_bytes == file_size:
                    progress = f"已下载 {total_bytes // 1024} KB"
                    if file_size and file_size > 0:
                        progress += f" ({total_bytes / file_size:.1%})"
                    progress_callback(progress, True)
                pdf_content.write(chunk)

            ftp.retrbinary(f'RETR {file_path}', _progress)

            pdf_content.seek(0)
            content = pdf_content.getvalue()

            if not content.startswith(b"%PDF"):
                progress_callback(f"下载的文件不是有效的PDF", False)
                return None

            path = BASE_DIR / filename
            with open(path, "wb") as out:
                out.write(content)

            progress_callback(f"PDF文件下载成功", True)
            return path

    except socket.timeout:
        progress_callback(f"FTP下载超时", False)
    except error_perm as e:
        progress_callback(f"FTP权限错误: {str(e)}", False)
    except Exception as e:
        progress_callback(f"FTP下载错误: {str(e)}", False)

    return None


def _download_tgz_from_ftp(url: str, filename: str, progress_callback):
    """FTP下载tar.gz（带超时控制）"""
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

        timeout = 30
        tgz_content = io.BytesIO()

        with FTP(host, timeout=timeout) as ftp:
            ftp.login(username, password)
            ftp.set_pasv(True)
            if ftp.sock:
                # 空闲读超时：若超过该时间没有数据返回，则抛出超时
                ftp.sock.settimeout(DOWNLOAD_TIMEOUT)

            try:
                ftp.size(file_path)
            except error_perm as e:
                if '550' in str(e):
                    progress_callback(f"FTP文件不存在", False)
                    return None
                else:
                    raise

            total_bytes = 0

            def _progress(chunk):
                nonlocal total_bytes
                total_bytes += len(chunk)
                if total_bytes % (1024 * 100) < len(chunk):
                    progress_callback(f"已下载 {total_bytes // 1024} KB...", True)
                tgz_content.write(chunk)

            ftp.retrbinary(f'RETR {file_path}', _progress)
            tgz_content.seek(0)

        return _extract_pdf_from_tgz_content(tgz_content.getvalue(), filename, url, progress_callback)

    except socket.timeout:
        progress_callback(f"FTP下载超时", False)
    except error_perm as e:
        progress_callback(f"FTP权限错误: {str(e)}", False)
    except Exception as e:
        progress_callback(f"FTP下载错误: {str(e)}", False)

    return None


def _extract_pdf_from_tgz_content(content: bytes, filename: str, url: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """从tar.gz内容中提取PDF文件（带超时控制）"""
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
            pdf_members = [m for m in tar.getmembers() if m.name.endswith(".pdf")]

            if not pdf_members:
                progress_callback(f"tar.gz 内未找到 PDF 文件", False)
                return None

            member = pdf_members[0]
            extracted_file = tar.extractfile(member)
            if extracted_file is None:
                progress_callback(f"tar.gz 提取文件失败", False)
                return None
            
            with extracted_file as f:
                pdf_content = f.read()
                if pdf_content.startswith(b"%PDF"):
                    path = BASE_DIR / filename
                    with open(path, "wb") as out:
                        out.write(pdf_content)
                    progress_callback(f"成功从 tar.gz 提取 PDF", True)
                    return path
                else:
                    progress_callback(f"tar.gz 中的文件不是有效的PDF", False)
                    return None

    except tarfile.TarError as e:
        progress_callback(f"tar.gz 文件格式错误", False)
    except Exception as e:
        progress_callback(f"解压 tar.gz 出错", False)

    return None


def download_pdf_sync(url: str, filename: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """同步下载PDF文件（支持总超时与空闲超时，HTTP流式进度）"""
    warnings.filterwarnings("ignore", category=InsecureRequestWarning)

    try:
        # HTTP/HTTPS：采用流式读取，按块更新进度，支持空闲超时与总超时
        if url.startswith(('http://', 'https://')):
            total_timeout = settings.pdf_download_total_timeout
            idle_timeout = settings.pdf_download_idle_timeout
            start_ts = time.time()
            last_progress_ts = start_ts
            chunk_size = 64 * 1024  # 64KB

            with requests.get(
                url,
                headers=DOWNLOAD_HEADERS,
                timeout=(idle_timeout, idle_timeout),  # 连接&读取超时均为空闲超时
                stream=True,
                verify=False
            ) as resp:
                if not (resp.status_code in (200, 206) and resp.headers.get("Content-Type", "").startswith("application/")):
                    # 回落到旧逻辑尝试直接处理完整响应
                    return _handle_http_response(resp, url, filename, progress_callback)

                path = BASE_DIR / filename
                total_bytes = 0
                header_checked = False
                buffer_head = b""

                with open(path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        now = time.time()
                        # 总超时控制
                        if now - start_ts > total_timeout:
                            progress_callback(f"下载超时（{total_timeout}秒）", False)
                            return None

                        # 处理空块
                        if not chunk:
                            if now - last_progress_ts > idle_timeout:
                                progress_callback(f"空闲超时（{idle_timeout}秒）", False)
                                return None
                            continue

                        f.write(chunk)
                        total_bytes += len(chunk)
                        last_progress_ts = now

                        # 检查PDF头
                        if not header_checked:
                            buffer_head += chunk[:5 - len(buffer_head)] if len(buffer_head) < 5 else b""
                            if len(buffer_head) >= 5:
                                if not buffer_head.startswith(b"%PDF"):
                                    progress_callback("不是PDF", False)
                                    return None
                                header_checked = True

                        # 每100KB报一次进度
                        if total_bytes % (100 * 1024) < len(chunk):
                            progress_callback(f"已下载 {total_bytes // 1024} KB...", True)

                progress_callback("成功下载", True)
                return path

        elif url.startswith('ftp://'):
            return _download_pdf_from_ftp(url, filename, progress_callback)

        else:
            progress_callback(f"不支持的协议: {url.split('://')[0]}", False)
            return None

    except requests.Timeout:
        progress_callback(f"下载超时（{DOWNLOAD_TIMEOUT}秒）", False)
        return None
    except Exception as e:
        progress_callback(f"下载失败: {str(e)}", False)
        return None


def _handle_http_response(resp, url: str, filename: str, progress_callback: Callable[[str, bool], None]) -> Optional[Path]:
    """处理HTTP/HTTPS响应并保存PDF文件"""
    if resp.status_code in (200, 299) and resp.headers.get("Content-Type", "").startswith("application/pdf"):
        path = BASE_DIR / filename
        content = resp.content
        if content.startswith(b"%PDF"):
            with open(path, "wb") as f:
                f.write(content)
            progress_callback(f"成功下载", True)
            return path
        else:
            progress_callback(f"不是PDF", False)
    else:
        error_msg = f"下载失败，状态码: {resp.status_code}"
        if resp.status_code == 403:
            error_msg = "下载失败，被网站拒绝"
        elif resp.status_code == 404:
            error_msg = "下载失败，地址不存在"

        progress_callback(error_msg, False)

    return None


def fetch_sync(url: str) -> str:
    """同步获取网页内容（带超时控制）"""
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


async def download_pdf_with_timeout(pmid, pdf_link, progress_callback, url_type, download_selector, page_wait_selector, executor, timeout=120):
    """
    带总超时的PDF下载（异步版本）

    Args:
        timeout: 总超时时间（秒），默认120秒
    """
    progress_callback(f"发现PDF", False)
    progress_callback(f"开始下载...", False)

    loop = asyncio.get_running_loop()

    try:
        # 使用 asyncio.wait_for 设置总超时
        if url_type == "tgz":
            pdf_path = await asyncio.wait_for(
                loop.run_in_executor(
                    executor,
                    download_pdf_from_tgz_sync,
                    pdf_link,
                    f"{pmid}.pdf",
                    progress_callback
                ),
                timeout=timeout
            )
        elif url_type == "webview":
            pdf_path = await asyncio.wait_for(
                loop.run_in_executor(
                    executor,
                    download_pdf_from_webview,
                    pdf_link,
                    pmid,
                    download_selector,
                    page_wait_selector,
                    progress_callback
                ),
                timeout=timeout
            )
        else:
            pdf_path = await asyncio.wait_for(
                loop.run_in_executor(
                    executor,
                    download_pdf_sync,
                    pdf_link,
                    f"{pmid}.pdf",
                    progress_callback
                ),
                timeout=timeout
            )

        if pdf_path:
            progress_callback(f"下载成功", False)
            return pdf_path
        else:
            progress_callback(f"下载失败", False)
            return None

    except asyncio.TimeoutError:
        progress_callback(f"下载超时（{timeout}秒），已跳过", False)
        return None
    except Exception as e:
        progress_callback(f"下载异常: {str(e)}", False)
        return None