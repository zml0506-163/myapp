from bs4 import BeautifulSoup
import requests

headers = {
    'Content-Type': 'application/json',
    'Accept'    : 'application/json',
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'
}
url = f"https://pubmed.ncbi.nlm.nih.gov/40903692/"
req = requests.get(url,headers=headers)
req.encoding = "utf-8"
txt = req.text
soup = BeautifulSoup(txt,"html.parser")


links = soup.select("div.full-text-links-list a")