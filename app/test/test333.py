from selenium import webdriver
from selenium.webdriver.common.by import By
from time import sleep

# 配置 WebDriver（使用 Chrome 浏览器）
driver = webdriver.Chrome()

# 打开指定 URL
driver.get('https://www.cell.com/action/showPdf?pii=S2666-3791%2825%2900423-9')

# 等待页面加载，确保所有 JavaScript 执行完毕
sleep(5)  # 根据需要调整等待时间

# 获取页面的 body 元素
body = driver.find_element(By.TAG_NAME, "body")

# 打印页面的 body 内容
print(body.text)

# 关闭浏览器
# driver.quit()
