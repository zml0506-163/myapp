from DrissionPage import Chromium
from DrissionPage._configs.chromium_options import ChromiumOptions
import time

# url = "https://onlinelibrary.wiley.com/doi/epdf/10.1002/cnr2.70344"
url = "https://www.embopress.org/doi/epdf/10.1038/s44318-025-00557-3"
# https://www.biorxiv.org/content/10.1101/2024.09.19.613934v1.full.pdf
# url = "https://www.embopress.org/doi/pdf/10.1038/s44318-025-00557-3?download=true"

# 创建配置对象
co = ChromiumOptions()
co.set_download_path("D:\\pythonwork\\pubmed_app\\storage\\pdfs")
# 添加必要的配置
# 添加浏览器启动参数（关键伪装配置）
# co.set_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36")
# co.set_argument("--disable-blink-features=AutomationControlled")  # 移除自动化标记
# co.set_argument("--window-size=1280,720")  # 模拟正常窗口大小
# co.set_argument("--disable-gpu")  # 禁用GPU加速（无头模式常用）
# co.set_argument("--enable-plugins")  # 模拟有插件
# co.set_argument("--log-level=3")  # 减少日志输出
# co.set_argument("--no-sandbox")  # 非沙箱模式（部分环境需要）

# 设置不加载图片、静音
# co.no_imgs(True).mute(True)
# co.incognito()  # 匿名模式
# co.headless()  # 无头模式
# co.set_argument('--no-sandbox')  # 无沙盒模式

# 初始化浏览器并打开页面
browser = Chromium(addr_or_opts=co)
tab = browser.new_tab(url)

# 等待页面加载
tab.wait.doc_loaded()

# tab.screencast.set_save_path("d:\\pythonwork\\pubmed_app\\storage\\pdfs")
# tab.screencast.start()
try:
    page = tab.ele('#info-tab-pane')
    page.wait.displayed(timeout=30)
    # 尝试定位下载按钮
    print("尝试定位下载按钮...")
    download_btn = tab.ele('xpath://*[@id="app-navbar"]/div[3]/div[3]/a')
    tab.set.download_path("d:\\pythonwork\\pubmed_app\\storage\\pdfs")
    tab.set.download_file_name(name='testdl', suffix='pdf')
    download_btn.click()
    tab.wait.download_begin()
    tab.wait.downloads_done()
except Exception as e:
    print(f"操作出错: {str(e)}")
# tab.screencast.stop()
# 关闭浏览器
browser.quit()
