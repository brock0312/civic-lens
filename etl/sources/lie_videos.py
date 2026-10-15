"""連江縣議會第 8 屆質詢影片：官網「質詢影音」依議員列清單（V16）。

counciler_index/7176 列出每位議員的清單連結 /ch/news/7176?clid=<n>；clid → 議員一律取該頁連結上的姓名文字（「副議長 林明揚」），
以 etl.match 的漢字正規化整名對連江縣議員名錄，同名或對不到的整份清單不收（印 log）。每份清單新到舊，每筆是該議員在一次定期大會的
縣政總質詢或縣長施政報告質詢，連到議會詳細頁 /ch/Detail/7176?mcid=<n>，頁面只嵌入 YouTube 影片（1–4 支）。
連結一律用議會詳細頁，不連 YouTube：剪輯影片所在頻道顯示名稱是個人（V16 已定案第 3 點）。只收「第八屆」的項目。
清單的日期是發布日期，不是質詢日期（第三、四次定期大會同日 2024-11-29 發布），所以頁面日期欄改寫會期（no_date），發布日期只用來排序。

交叉核對：清單標題沒有姓名，改讀詳細頁每支嵌入影片的 YouTube oEmbed 標題（/oembed 不在 YouTube robots 禁止清單），標題形如
「連江縣議會第8屆第7次定期大會總質詢-陳書建議員」。有任一支影片標題點名名錄上的其他議員、且沒有點名本人的項目不收（印 log）；
標題沒有點名任何議員的照收（歸屬依據是議會官網清單），筆數印在 log。
快取：data/cache/lie/（清單每次重抓；詳細頁與 oEmbed 標題不會變，有快取就不重抓）。
自我檢查：python3 -m etl.sources.lie_videos [姓名…]（只讀快取與 data/civic.sql，不連網、不寫 DB）；加 --fetch 先更新快取
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path

from etl.db import upsert_fact
from etl.fetch import get, now_utc
from etl.sources.nwt_book import key, resolve, roster_index, targets

OFFICE = "lie_councilor"
TERM = 8
HOST = "https://www.mtcc.gov.tw"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "lie"
NUM = {c: i for i, c in enumerate("一二三四五六七八九十", 1)}

COUNCILLOR = re.compile(r'<a href="[^"]*/ch/news/7176\?clid=(\d+)">.*?<div class="name">(.*?)</div>', re.S)
ITEM = re.compile(r"<a href='[^']*/ch/Detail/7176\?mcid=(\d+)[^']*'[^>]*>\s*<div class='news_line'>"
                  r"<div class='date'>(\d{4}-\d\d-\d\d)</div><div class='news_font'>(.*?)</div>", re.S)
TITLE = re.compile(r"^第(八)屆第([一二三四五六七八九十]+)次(定期大會)(縣政總質詢|總質詢|縣長施政報告質詢)$")
EMBED = re.compile(r'src="https://www\.youtube\.com/embed/([\w-]{11})')
PAGES = re.compile(r"共有<p>\s*(\d+)\s*</p>筆\s*\|\s*(\d+)\s*頁")

_last = {}


def fetch(url):
    """同一主機間隔 ≥ 1.1 秒，循序。"""
    host = urllib.parse.urlsplit(url).netloc
    wait = 1.1 - (time.monotonic() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        return get(url)
    finally:
        _last[host] = time.monotonic()


def zh_num(s):
    """一～十九的中文數字（「七」「十二」）→ int。"""
    if s.startswith("十"):
        return 10 + (NUM[s[1]] if len(s) > 1 else 0)
    return NUM[s[0]] * 10 + (NUM[s[2]] if len(s) > 2 else 0) if len(s) > 1 else NUM[s]


def parse_index(page):
    """質詢影音首頁 → [(clid, 姓名)]；姓名去掉職稱（議長、副議長、議員）與空白。"""
    out = []
    for clid, text in COUNCILLOR.findall(page):
        name = re.sub(r"^(副議長|議長|議員)", "", re.sub(r"\s+", "", html.unescape(text)))
        out.append((int(clid), name))
    return out


def parse_list(page):
    """議員清單一頁 → ([{mcid, published, title}], 總頁數)。"""
    items = [{"mcid": int(m), "published": d, "title": re.sub(r"\s+", "", html.unescape(t))} for m, d, t in ITEM.findall(page)]
    pages = PAGES.search(page)
    return items, int(pages.group(2)) if pages else 1


def parse_title(title):
    """「第八屆第七次定期大會縣政總質詢」→ {nth, session, kind}（官方偶寫「總質詢」，kind 一律寫「縣政總質詢」）；
    不是第八屆回 None；第八屆但格式未知 raise ValueError。"""
    if not title.startswith("第八屆"):
        return None
    m = TITLE.match(title)
    if not m:
        raise ValueError(f"連江清單標題格式未知：{title!r}")
    nth = zh_num(m.group(2))
    kind = "縣政總質詢" if m.group(4) == "總質詢" else m.group(4)
    return {"nth": nth, "session": f"第{TERM}屆第{nth}次{m.group(3)}", "kind": kind}


def detail_url(mcid):
    return f"{HOST}/ch/Detail/7176?mcid={mcid}"


def _cached(name, url, refresh):
    path = CACHE / name
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(url))
    return path.read_text(encoding="utf-8")


def oembed_title(video_id, fetch_missing=True):
    """YouTube oEmbed 標題（快取 data/cache/lie/oembed/<id>.json）；影片已下架或不公開回 None。"""
    path = CACHE / "oembed" / f"{video_id}.json"
    if not path.exists():
        if not fetch_missing:
            return None
        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
        try:
            body = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403, 404):
                raise
            body = b"{}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return json.loads(path.read_text(encoding="utf-8")).get("title")


def load(refresh=True):
    """→ [{clid, name, items: [{mcid, published, title, youtube: [id], yt_titles: [title|None]}]}]（只含第八屆項目）。"""
    out = []
    for clid, name in parse_index(_cached("counciler_index.html", f"{HOST}/ch/counciler_index/7176", refresh)):
        items, page_no = [], 1
        while True:
            rows, pages = parse_list(_cached(f"list_{clid}_p{page_no}.html",
                                             f"{HOST}/ch/news/7176/?pagenum={page_no}&qccid=&webaid=&clid={clid}", refresh))
            items += rows
            # 清單新到舊：這頁已出現第八屆以外的項目，或已是最末頁，就不再往下翻
            if page_no >= pages or any(not r["title"].startswith("第八屆") for r in rows):
                break
            page_no += 1
        for it in items:
            if not it["title"].startswith("第八屆"):
                continue
            detail = _cached(f"detail_{it['mcid']}.html", detail_url(it["mcid"]), False)
            it["youtube"] = list(dict.fromkeys(EMBED.findall(detail)))
            it["yt_titles"] = [oembed_title(v, refresh) for v in it["youtube"]]
        out.append({"clid": clid, "name": name, "items": [it for it in items if it["title"].startswith("第八屆")]})
    return out


def check_titles(name, yt_titles, roster_names):
    """嵌入影片標題 vs 清單所屬議員 → 'ok'（每支有標題的都點名本人）、'none'（沒有標題點名任何議員）、
    'mismatch'（有標題點名其他議員且沒點名本人，或有的點名本人、有的點名別人）。"""
    me = key(name)
    named = []
    for t in yt_titles:
        k = key(t or "")
        who = {n for n in roster_names if n in k}
        if who:
            named.append(me in who)
    if not named:
        return "none"
    return "ok" if all(named) else "mismatch"


def build(conn, councillors, log=print):
    """→ (targets, {person_id: [item]})。"""
    ts = targets(conn, OFFICE)
    roster = roster_index(conn, OFFICE)
    roster_names = set(roster)
    resolved = []
    for c in councillors:
        pid, why = resolve(c["name"], roster)
        if not pid:
            log(f"lie_videos：clid={c['clid']} {c['name']}：{why}，整份清單不收")
            continue
        resolved.append((pid, c))
    owners = {}
    for pid, c in resolved:
        for it in c["items"]:
            owners.setdefault(it["mcid"], set()).add(pid)
    by_pid = {}
    for pid, c in resolved:
        for it in c["items"]:
            if len(owners[it["mcid"]]) > 1:
                log(f"lie_videos：mcid={it['mcid']} 同時列在多位議員清單，不收")
                continue
            try:
                meta = parse_title(it["title"])
            except ValueError as e:
                log(f"lie_videos：{c['name']} mcid={it['mcid']} {e}，不收")
                continue
            verdict = check_titles(c["name"], it["yt_titles"], roster_names)
            if verdict == "mismatch":
                log(f"lie_videos：{c['name']} mcid={it['mcid']} 影片標題點名其他議員：{it['yt_titles']}，不收")
                continue
            if verdict == "none":
                log(f"lie_videos：{c['name']} mcid={it['mcid']} 影片標題沒有點名議員（照官網清單收錄）")
            by_pid.setdefault(pid, []).append({**it, **meta, "verified": verdict == "ok"})
    out = {}
    for t in ts:
        pid, why = resolve(t["name"], roster)
        if pid != t["person_id"]:
            log(f"lie_videos：對象 {t['name']}（{t['person_id']}）{why or '名錄對到別人'}，不收")
            continue
        # 遞補者從上任起算（以發布日期為準；第 8 屆目前沒有遞補）
        vs = [v for v in by_pid.get(pid, []) if v["published"] >= t["since"]]
        if vs:
            out[pid] = sorted(vs, key=lambda v: (v["nth"], v["kind"] != "縣長施政報告質詢", v["mcid"]))
    return ts, out


def write_videos(conn, by_pid, fetched_at):
    """每位議員每個詳細頁一筆 fact，刪除這次不在結果裡的舊 fact。回傳 (筆數, 刪除筆數)。"""
    known = {r[0] for r in conn.execute("SELECT fact_key FROM fact WHERE fact_key LIKE 'lievideo:%'")}
    current = set()
    # 發布日期不是質詢日，而且不同會期常同一天發布：排序用日期改取該會期最晚的發布日，同日再以 seq（會期＋場次先後）定序
    sess_date = {}
    for v in (v for items in by_pid.values() for v in items):
        sess_date[v["nth"]] = max(sess_date.get(v["nth"], ""), v["published"])
    for pid, items in by_pid.items():
        for v in items:
            k = f"lievideo:{v['mcid']}:{pid}"
            current.add(k)
            upsert_fact(conn, k, pid, "interpellation", {
                "title": v["title"], "doc_type": v["kind"], "dept": None, "term": TERM, "session": v["session"],
                "published": v["published"], "no_date": True, "video_id": str(v["mcid"]), "clip": True,
                "youtube_ids": v["youtube"], "title_checked": v["verified"],
                "seq": v["nth"] * 2 + (v["kind"] != "縣長施政報告質詢"),
            }, detail_url(v["mcid"]), fetched_at, date=sess_date[v["nth"]])
    stale = known - current
    conn.executemany("DELETE FROM fact WHERE fact_key = ?", [(k,) for k in stale])
    return len(current), len(stale)


def run(conn):
    councillors = load(refresh=True)
    if not councillors:
        raise ValueError("連江質詢影音首頁找不到議員")
    logs = set()
    ts, by_pid = build(conn, councillors, logs.add)
    for line in sorted(logs):
        print(line)
    n, stale = write_videos(conn, by_pid, now_utc())
    print(f"lie_videos：議員清單 {len(councillors)} 份；對象 {len(ts)} 人，有紀錄 {len(by_pid)} 人，{n} 筆，刪除 {stale} 筆")


def check(samples=()):
    from etl.sources.nwt_book import dump_conn
    councillors = load(refresh=False)
    logs = []
    ts, by_pid = build(dump_conn(), councillors, logs.append)
    for line in sorted(set(logs)):
        print(" ", line)
    for c in councillors:
        print(f"  clid={c['clid']} {c['name']}：第八屆 {len(c['items'])} 筆")
    print(f"對象 {len(ts)} 人；有紀錄 {len(by_pid)} 人，{sum(map(len, by_pid.values()))} 筆")
    for t in ts:
        vs = by_pid.get(t["person_id"], [])
        print(f"  {t['name']}：{len(vs)} 筆（標題核對相符 {sum(v['verified'] for v in vs)}）")
        if t["name"] in samples:
            for v in vs:
                print(f"    {v['session']} {v['kind']} 發布 {v['published']} {detail_url(v['mcid'])} {v['yt_titles']}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        load(refresh=True)
    check([a for a in sys.argv[1:] if not a.startswith("--")])
