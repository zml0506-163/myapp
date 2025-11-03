from DrissionPage import Chromium
from DrissionPage._configs.chromium_options import ChromiumOptions
# 创建配置对象
co = ChromiumOptions()
# 设置不加载图片、静音
# co.no_imgs(True).mute(True)
# co.incognito()  # 匿名模式
# co.headless()  # 无头模式
# co.set_argument('--no-sandbox')  # 无沙盒模式

# 初始化浏览器并打开页面
browser = Chromium(addr_or_opts=co)
# tab = browser.new_tab("https://www.cell.com/cell-reports-medicine/fulltext/S2666-3791(25)00423-9")
#
# elem = tab.ele('xpath://*[@id="article_more_menu"]/ul/li[1]/div/div/ul/li[1]/a', timeout=30)
# elem.attr("href")

tab = browser.new_tab("https://www.cell.com/action/showPdf?pii=S2666-3791%2825%2900423-9")

# 等待页面加载
tab.wait.doc_loaded()

download_selector = '@id=toolbar'
page_wait_selector = "#thumbnails"

try:
    tab.wait(5)
    # 等待信息面板显示
    js_code = """
        return document.querySelector("#viewer");
    """
    tab.wait(5)
    download_button = tab.run_js(js_code)

    # 定位并点击下载按钮
    download_btn = tab.ele(download_selector)
    download_btn.wait.displayed(timeout=15)
    tab.set.download_path("D:\\pythonwork\\pubmed_app\\storage\\pdfs\\test")
    tab.set.download_file_name(name="test11", suffix='pdf')
    download_btn.click()
    # 等待下载完成
    tab.wait.download_begin()
    tab.wait.downloads_done()

except Exception as e:
    print(f"操作出错: {str(e)}")

browser.quit()


