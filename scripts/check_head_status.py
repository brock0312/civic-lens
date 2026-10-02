"""重查宜蘭、新竹市首長狀態（V14 §5）：只回報，不改 data/head_status.csv。

用法：python3 scripts/check_head_status.py　有任何需人工確認就 exit 1。
"""
import csv
import html
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from etl import fetch  # noqa: E402

ILA_URL = "https://www.e-land.gov.tw/cp.aspx?n=2700"
HSZ_URL = "https://www.hccg.gov.tw/hccg/app/artwebsite?module=artwebsite&id=900&serno=null"
MOI_LIST = "https://www.moi.gov.tw/News.aspx?n=4&sms=9009&page=1&PageSize=200"
KEYWORDS = ("停止職務", "停職", "復職", "代理", "解職")


def text_of(page):
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def check_ila(page):
    """回傳 None 表示無變動，否則原因。"""
    t = text_of(page)
    if "代理縣長" not in t or "林茂盛" not in t:
        return "找不到「代理縣長」或「林茂盛」，頁面可能改了或代理人變動"
    return None


def check_hsz(page):
    t = text_of(page)
    if "高虹安" not in t:
        return "找不到「高虹安」，頁面可能改了或市長變動"
    if "代理" in t:
        return "頁面出現「代理」字樣"
    return None


def news_hits(page, names, since, base=MOI_LIST):
    """日期（民國）不早於 since（西元 YYYY-MM-DD）、標題含關鍵字或首長姓名的 (標題, 網址)。"""
    out = []
    pat = r'<span>(\d{2,3})-(\d\d-\d\d)</span>.*?href="([^"]*News_Content[^"]*)"[^>]*title="([^"]*)"'
    for y, md, href, title in re.findall(pat, page, re.S):
        title = html.unescape(title)
        if f"{int(y) + 1911}-{md}" >= since and (
            any(k in title for k in KEYWORDS) or any(n in title for n in names)
        ):
            out.append((title, urljoin(base, html.unescape(href))))
    return out


def mayor_names():
    try:
        con = sqlite3.connect(ROOT / "data" / "civic.db")
        rows = con.execute(
            "select distinct p.name from fact f join person p using(person_id) "
            "where f.kind='office' and json_extract(f.data,'$.office') like '%\\_mayor' escape '\\'"
        ).fetchall()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return []


_last = {}


def get_text(url):
    host = urlparse(url).netloc
    wait = _last.get(host, 0) + 1.1 - time.time()
    if wait > 0:
        time.sleep(wait)
    try:
        return fetch.get(url).decode("utf-8", "replace")
    finally:
        _last[host] = time.time()


def main():
    with open(ROOT / "data" / "head_status.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    last = {}
    for r in rows:
        last[r["iso"]] = r
    since = max(last[i]["fetched_at"] for i in ("ila", "hsz"))
    bad = 0

    def report(label, fn, url, *args):
        nonlocal bad
        try:
            why = fn(get_text(url), *args)
        except Exception as e:  # 抓取失敗也要人工確認
            why = f"抓取失敗 {url}：{e}"
        if why:
            bad += 1
        print(f"{label}：{'需人工確認：' + why if why else '無變動'}")

    print(f"狀態最後一筆：宜蘭 {last['ila']['event']}、新竹市 {last['hsz']['event']}；fetched_at 起點 {since}")
    report("宜蘭縣", check_ila, ILA_URL)
    report("新竹市", check_hsz, HSZ_URL)
    try:
        hits = news_hits(get_text(MOI_LIST), mayor_names(), since)
        # ponytail: 列表頁沒有日期欄，只列出前 200 則內的命中，由人工對照 fetched_at
        if hits:
            bad += 1
            print("內政部新聞稿：需人工確認：標題命中（對照 fetched_at 之後的）")
            for title, url in hits:
                print(f"  {title} {url}")
        else:
            print("內政部新聞稿：無變動")
    except Exception as e:
        bad += 1
        print(f"內政部新聞稿：需人工確認：抓取失敗 {e}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
