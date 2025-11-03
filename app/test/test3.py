import urllib.request

url = 'https://www.biorxiv.org/content/10.1101/2024.09.19.613934v1.full.pdf'

BASE_DIR = "D:\\pythonwork\\pubmed_app\\storage\\pdfs"
urllib.request.urlretrieve(url, f"{BASE_DIR}/test3.pdf")