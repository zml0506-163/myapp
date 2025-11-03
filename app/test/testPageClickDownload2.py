from playwright.sync_api import Page, expect

url = "https://onlinelibrary.wiley.com/doi/epdf/10.1002/cnr2.70344"

def test_get_started_link(page: Page):
    page.goto(url)

    # 定位信息标签面板并等待其显示（使用page替代tab）
    info_panel = page.locator('#info-tab-pane')
    info_panel.wait_for(state='visible', timeout=30000)  # 超时30秒

    # 尝试定位下载按钮
    print("尝试定位下载按钮...")
    download_btn = page.locator('xpath=//*[@id="app-navbar"]/div[3]/div[3]/a')

    # 设置下载路径并等待下载完成
    with page.expect_download() as download_info:
        # 点击下载按钮
        download_btn.click()

    # 获取下载对象
    download = download_info.value

    # 保存文件到指定路径
    save_path = "d:\\pythonwork\\pubmed_app\\storage\\pdfs\\testdl.pdf"
    download.save_as(save_path)

    # 验证下载是否成功（如果失败会抛出异常）
    if download.failure():
        print(f"下载失败: {download.failure()}")
    else:
        print(f"文件已成功保存到: {save_path}")