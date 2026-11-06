import concurrent.futures
import httpx
from bs4 import BeautifulSoup
from radar.config import load_sources
from pathlib import Path

cfg=load_sources(Path("."))
sources=[s for s in cfg["sources"] if s.get("enabled") and s["collector"] in {"nature","springer","nature_humanities"}]
def probe(s):
    try:
        r=httpx.get(s["url"],follow_redirects=True,timeout=25,headers={"User-Agent":cfg["user_agent"]})
        soup=BeautifulSoup(r.text,"lxml")
        print(s["key"],r.status_code,r.url,len(r.content),soup.title.get_text(strip=True) if soup.title else "",len(soup.select("article")),flush=True)
    except httpx.HTTPError as e:
        print(s["key"],str(e),flush=True)
with concurrent.futures.ThreadPoolExecutor(4) as pool:
    list(pool.map(probe,sources))
