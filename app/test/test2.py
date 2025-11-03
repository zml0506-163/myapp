import requests

def download_wiley_pdf(pdf_url, save_path="wiley_paper.pdf"):
    """
    下载 Wiley 文献 PDF
    :param pdf_url: 目标 PDF 链接（如 https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/cnr2.70344?download=true）
    :param save_path: 保存路径（默认当前文件夹，命名为 wiley_paper.pdf）
    """
    try:
        # 1. 从 Chrome 浏览器读取 Wiley 相关的 Cookie（关键：复用权限）
        # 若用 Edge 浏览器，将 browser_cookie3.chrome() 改为 browser_cookie3.edge()
        # 若用 Firefox，改为 browser_cookie3.firefox()

        # 2. 构造请求头：模拟浏览器（避免被识别为爬虫）
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
            "Referer": "https://onlinelibrary.wiley.com/"  # 模拟从 Wiley 官网跳转过来的请求
        }

        # 3. 发送 GET 请求下载 PDF（stream=True 用于大文件，避免内存占用过高）
        response = requests.get(
            url=pdf_url,
            headers=headers,
            stream=True,
            timeout=30  # 超时时间（秒），可根据网络调整
        )

        # 4. 校验请求是否成功（200=成功，403=权限不足，404=链接失效）
        response.raise_for_status()  # 若状态码非 200，直接抛出错误

        # 5. 写入文件（二进制模式，因为 PDF 是二进制文件）
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB 为单位读取（避免卡顿）
                if chunk:  # 过滤空数据块
                    f.write(chunk)

        print(f"✅ 下载成功！文件已保存至：{save_path}")

    except requests.exceptions.HTTPError as e:
        # 常见错误：403（权限不足）、404（链接无效）、500（服务器错误）
        status_code = e.response.status_code
        if status_code == 403:
            print(f"❌ 下载失败（错误码：{status_code}）：权限不足！请确认：")
            print("  1. 浏览器已登录 Wiley 账号或处于有订阅的网络（如校园网）")
            print("  2. 浏览器中能正常下载该链接（排除平台权限限制）")
        elif status_code == 404:
            print(f"❌ 下载失败（错误码：{status_code}）：链接无效！请检查链接是否正确。")
        else:
            print(f"❌ 下载失败（错误码：{status_code}）：服务器返回错误，建议稍后重试。")

    except Exception as e:
        # 其他错误：Cookie 读取失败、网络超时、文件写入失败等
        if "cookies" in str(e).lower():
            print(f"❌ Cookie 读取失败！可能原因：")
            print("  1. 浏览器未启动或未登录 Wiley 平台")
            print("  2. 浏览器版本过高，`browser_cookie3` 暂不支持（可尝试更新库：pip install --upgrade browser-cookie3）")
        else:
            print(f"❌ 其他错误：{str(e)}")

# ------------------- 调用函数 -------------------
# 替换为你的目标链接（即浏览器能下载的链接）
target_url = "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/cnr2.70344?download=true"
# 替换为你想保存的路径（如 "D:/文献/wiley_2024.pdf"）
save_file_path = "wiley_paper.pdf"

# 执行下载
download_wiley_pdf(pdf_url=target_url, save_path=save_file_path)