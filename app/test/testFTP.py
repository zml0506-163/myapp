
from ftplib import FTP, error_perm
import socket
import os
from urllib.parse import urlparse

def ftp_download_file(ftp_host, remote_path, local_save_path, timeout=60, max_retries=3):
    """
    下载单个FTP文件（支持匿名登录和重试）
    :param ftp_host: FTP服务器地址
    :param remote_path: 远程文件完整路径
    :param local_save_path: 本地保存路径
    :param timeout: 超时时间（秒）
    :param max_retries: 最大重试次数
    :return: 下载成功返回True，否则False
    """
    retries = 0
    while retries < max_retries:
        ftp = None
        try:
            # 建立连接并设置超时
            ftp = FTP(ftp_host, timeout=timeout)
            # 匿名登录
            ftp.login('anonymous', '')

            # 分离远程目录和文件名
            remote_dir = os.path.dirname(remote_path)
            remote_filename = os.path.basename(remote_path)

            # 切换到远程目录
            if remote_dir:
                ftp.cwd(remote_dir)

            # 创建本地目录（如果不存在）
            local_dir = os.path.dirname(local_save_path)
            if local_dir and not os.path.exists(local_dir):
                os.makedirs(local_dir, exist_ok=True)

            # 下载文件
            with open(local_save_path, 'wb') as local_file:
                ftp.retrbinary(f'RETR {remote_filename}', local_file.write)

            print(f"✅ 下载成功：{local_save_path}")
            return True

        except error_perm as e:
            print(f"❌ 权限错误 {retries+1}/{max_retries}：{str(e)} - {remote_path}")
        except socket.timeout:
            print(f"⏰ 超时重试 {retries+1}/{max_retries}：{remote_path}")
        except Exception as e:
            print(f"❌ 下载失败 {retries+1}/{max_retries}：{str(e)} - {remote_path}")
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()

        retries += 1

    print(f"❌ 达到最大重试次数，放弃下载：{remote_path}")
    return False

def batch_ftp_download(url_list, local_base_dir='downloads'):
    """批量下载FTP文件"""
    for url in url_list:
        # 解析FTP链接
        parsed = urlparse(url)
        if parsed.scheme != 'ftp':
            print(f"跳过非FTP链接：{url}")
            continue

        ftp_host = parsed.netloc
        remote_path = parsed.path.lstrip('/')  # 去除路径开头的斜杠，避免cwd错误

        # 构建本地保存路径（保持远程目录结构）
        local_save_path = os.path.join(local_base_dir, remote_path)

        # 下载文件
        ftp_download_file(ftp_host, remote_path, local_save_path)

if __name__ == "__main__":
    # 你的FTP文件列表
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

    # 开始批量下载（文件会保存到当前目录的downloads文件夹下，保持原目录结构）
    batch_ftp_download(ftp_urls)