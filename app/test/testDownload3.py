import time

import pyautogui
from DrissionPage import Chromium
from DrissionPage._configs.chromium_options import ChromiumOptions
from DrissionPage.common import Keys
from platform import system
arguments = [
    "-no-first-run",
    "-force-color-profile=srgb",
    "-metrics-recording-only",
    "-password-store=basic",
    "-use-mock-keychain",
    "-export-tagged-pdf",
    "-no-default-browser-check",
    "-disable-background-mode",
    "-enable-features=NetworkService,NetworkServiceInProcess,LoadCryptoTokenExtension,PermuteTLSExtensions",
    "-disable-features=FlashDeprecationWarning,EnablePasswordsAccountStorage",
    "-deny-permission-prompts",
    "-disable-gpu",
    "-accept-lang=zh-CN", # 根据网站选择支持的地区 // [!code warning]
    "--guest"
]
# 创建配置对象（默认从 ini 文件中读取配置）
co = ChromiumOptions()
co._arguments = arguments
# 设置不加载图片、静音
# co.no_imgs(True).mute(True)
# co.incognito()  # 匿名模式
# co.headless()  # 无头模式
# co.set_argument('--no-sandbox')  # 无沙盒模式
co.set_download_path("D:\\pythonwork\\pubmed_app\\storage\\pdfs")
tab = Chromium(addr_or_opts=co).new_tab()

url = 'https://www.biorxiv.org/content/10.1101/2024.09.19.613934v1.full.pdf'
tab.get(url)

tab.wait.doc_loaded()
tab.wait(10)
tab.save(path="D:\\pythonwork\\pubmed_app\\storage\\pdfs\\", name="test3.pdf", as_pdf=False)

# 等待保存对话框出现
time.sleep(1)

print(f"完整页面已保存到:D:\\pythonwork\\pubmed_app\\storage\\pdfs\\test3.pdf")