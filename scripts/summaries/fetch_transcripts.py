"""抓臺北市議會公報的市政總質詢、部門業務質詢速記錄 PDF（質詢摘要 S1）。

用法：python3 scripts/summaries/fetch_transcripts.py 06
  06＝第 14 屆第幾次定期大會。整個會期都抓（組員名單要從 PDF 內文解析，下載前無法可靠篩人）；已下載的跳過。
輸出：data/cache/transcripts/14-06/<viewer_id>.pdf，以及 index.json（每組一筆：標題、類別、組別、起始頁、viewer 網址）。

抓法見 docs/validation/V4-council-attendance.md §4.2、M4 §2：清單頁與 gaz_viewer 的 dataIndex 綁 cookie session，
所以每翻一頁清單就要馬上把該頁的 gaz_viewer 打完。viewer.html?id= 跨 session 穩定、不需 cookie，當作出處網址。
"""
import html
import http.cookiejar
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "transcripts"
BASE = "https://gaz.tcc.gov.tw"
UA = "civic-lens-etl/0.1"
MIN_INTERVAL = 1.2  # 秒
CATEGORIES = ("總質詢", "業務質詢")

_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
_last = 0.0


def get(url):
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with _opener.open(req, timeout=120) as resp:
            return resp.read()
    finally:
        _last = time.monotonic()


ITEM = re.compile(r'gaz_viewer\.html\?dataIndex=(\d+)[^"]*"[^>]*title="另開視窗至:([^"]+)".*?起始頁：(\d+)', re.S)
TITLE = re.compile(r"第\s*14\s*屆第(\d+)次定期大會(?:(市政總質詢)|(\S+?)部門)第(\d+)組")


def parse_list(page):
    """清單頁 → [{data_index, title, doc_type, dept, group, start_page}]。

    清單的內文摘要取自起始頁整頁，常夾著上一組的結尾（甚至別組的表頭），所以日期與組員一律從 PDF 內文解析，不用清單。
    """
    out = []
    for idx, title, start in ITEM.findall(page):
        title = html.unescape(title).strip()
        if "書面答覆" in title:  # 市府書面答覆資料不是速記錄，不收
            continue
        t = TITLE.search(title)
        if not t:
            raise ValueError(f"清單項目格式未知：{title!r}")
        out.append({
            "data_index": int(idx),
            "title": title,
            "doc_type": "市政總質詢" if t.group(2) else "部門質詢",
            "dept": t.group(3),
            "group": int(t.group(4)),
            "start_page": int(start),
        })
    return out


def list_url(category, session, page):
    q = urllib.parse.urlencode({
        "sort": "asc", "sortField": "date", "pageSize": 40, "cst": "S", "se": 14, "ti": session, "currentPage": page,
    })
    return f"{BASE}/search/gaz/gazSubCate/{urllib.parse.quote(category)}/result.html?{q}"


def resolve(item, page):
    """同一 session 內：gaz_viewer → viewer id → PDF 檔案網址。"""
    gv = get(f"{BASE}/pdf/index/gaz_viewer.html?dataIndex={item['data_index']}&fromPage={page}").decode()
    m = re.search(r"viewer\.html\?id=([0-9A-F]+)", gv)
    if not m:
        raise ValueError(f"{item['title']}：gaz_viewer 沒有 viewer id")
    # dataIndex 綁 session，位移就會開到別份：用 gaz_viewer 頁面上的標題核對（組別名稱與清單一致）
    label = re.search(r'<iframe id="doc-ifr" title="([^"]+)"', gv)
    label = re.sub(r"<[^>]*>?|\(.*?\)| ", "", html.unescape(label.group(1))) if label else ""
    if not label or label not in item["title"].replace(" ", ""):
        raise ValueError(f"dataIndex 位移：清單 {item['title']!r}，gaz_viewer {label!r}")
    viewer_id = m.group(1)
    pv = get(f"{BASE}/pdf/viewer.html?id={viewer_id}").decode()
    f = re.search(r'tcc_file = "([^"]+)"', pv)
    if not f:
        raise ValueError(f"{item['title']}：viewer 頁沒有 tcc_file")
    return viewer_id, f.group(1)


def run(session):
    out_dir = CACHE / f"14-{session}"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.json"
    index = {d["title"]: d for d in json.loads(index_path.read_text())} if index_path.exists() else {}
    for category in CATEGORIES:
        page = 1
        while True:
            items = parse_list(get(list_url(category, session, page)).decode())
            if not items:
                break
            for it in items:
                known = index.get(it["title"])
                if known and (out_dir / f"{known['viewer_id']}.pdf").exists():
                    continue
                viewer_id, file_url = resolve(it, page)
                pdf = get(file_url)
                if not pdf.startswith(b"%PDF"):
                    raise ValueError(f"{it['title']}：下載內容不是 PDF（{len(pdf)} bytes）")
                (out_dir / f"{viewer_id}.pdf").write_bytes(pdf)
                rec = {k: v for k, v in it.items() if k != "data_index"}
                index[it["title"]] = {**rec, "viewer_id": viewer_id,
                                      "viewer_url": f"{BASE}/pdf/viewer.html?id={viewer_id}"}
                index_path.write_text(json.dumps(list(index.values()), ensure_ascii=False, indent=1))
                print(f"{time.strftime('%T')} {it['title']} {len(pdf)} bytes", flush=True)
            page += 1
    print(f"完成：{len(index)} 組", flush=True)


if __name__ == "__main__":
    run(sys.argv[1])
