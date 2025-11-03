# https://onlinelibrary.wiley.com/doi/10.1111/jcmm.70836
from bs4 import BeautifulSoup
import requests

headers = {
    'Content-Type': 'application/json',
    'Accept'    : 'application/json',
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'
}
download = "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/jcmm.70836?download=true"
url = f"https://onlinelibrary.wiley.com/doi/10.1111/jcmm.70836"
# https://onlinelibrary.wiley.com/doi/10.1002/cnr2.70344
# https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/cnr2.70344?download=true

req = requests.get(url,headers=headers)
req.encoding = "utf-8"
txt = req.text
soup = BeautifulSoup(txt,"html.parser")


links = soup.select("a")
for a in soup.find_all("a", href=True):
    if "pdf" in a["href"].lower() or "pdf" in a.text.lower():
        print(a["href"])
