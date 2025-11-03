import base64
from selenium import webdriver

options = webdriver.ChromeOptions()
driver = webdriver.Chrome(options=options)

driver.get("https://www.biorxiv.org/content/10.1101/2024.09.19.613934v1.full.pdf")

pdf = driver.execute_cdp_cmd("Page.printToPDF", {"printBackground": True})

with open("page.pdf", "wb") as f:
    f.write(base64.b64decode(pdf["data"]))

driver.quit()
