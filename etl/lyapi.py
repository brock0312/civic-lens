"""立法院 API（OpenFun 維運，https://ly.govapi.tw/v2；資料 CC BY 4.0）的共用函式。

- Base URL 依 repo openfunltd/ly.govapi.tw-v2 的 skill.md：舊網址 v2.ly.govapi.tw 仍見於 docs/data-sources，以本檔為準。
- 不帶 Token 也能呼叫但可能被限流；本機環境變數 LYAPI_TOKEN 有值時帶 Bearer Token（不進 repo）。
- 列表回應：{"total", "total_page", "page", "limit", "<型別複數>": [...]}；Elasticsearch 分頁上限 page*limit <= 10000。
- 欄位格式（日期寫法、單一選區縣市的「選區名稱」）尚未在本機實測，解析一律寬鬆，對不上就 raise 或留空，不猜。
"""
import os
import re
import time
import urllib.error
import urllib.parse

from etl.fetch import get_json
from etl.sources.national_districts import ISO

BASE = "https://ly.govapi.tw/v2"
TERM = 11
WINDOW = 10000  # Elasticsearch result window
PUBLISHER = "立法院（經 OpenFun 立法院 API，CC BY 4.0）"


def headers():
    token = os.environ.get("LYAPI_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else None


def get_with_backoff(url, get=None, waits=(30, 60, 120, 240), sleep=time.sleep):
    """HTTP 429（限流）時等一下再試，等待時間優先用 Retry-After；其他錯誤與重試用完照常 raise。
    2026-10-03 本機第一次實跑：不帶 Token 連續抓約 40 個列表頁後回 429。"""
    get = get or (lambda u: get_json(u, headers=headers()))
    for wait in (*waits, None):
        try:
            return get(url)
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait is None:
                raise
            retry_after = (e.headers or {}).get("Retry-After")
            sleep(int(retry_after) if str(retry_after or "").isdigit() else wait)


def list_url(type_, params, page=1, limit=100):
    """params 的值是 list 時重複該鍵（例：output_fields=a&output_fields=b）。"""
    q = [*sorted(params.items()), ("page", page), ("limit", limit)]
    return f"{BASE}/{type_}?{urllib.parse.urlencode(q, doseq=True)}"


def item_url(type_, *ids):
    return f"{BASE}/{type_}/" + "/".join(urllib.parse.quote(str(i), safe="") for i in ids)


def fetch_all(type_, params, key=None, limit=100, get=None, sleep=1.1):
    """逐頁抓完一個列表端點，回傳 (items, 第一頁網址)。超過分頁上限就 raise（請縮小篩選範圍），不靜默截斷。"""
    get = get or get_with_backoff
    key = key or type_
    items, page, first = [], 1, list_url(type_, params, 1, limit)
    while True:
        if page * limit > WINDOW:
            raise ValueError(f"{first}：超過 {WINDOW} 筆分頁上限，請加篩選條件")
        body = get(list_url(type_, params, page, limit))
        if body.get("error"):
            raise ValueError(f"{first}：{body.get('message')}")
        items += body.get(key) or []
        if page >= int(body.get("total_page") or 1):
            break
        page += 1
        if sleep:
            time.sleep(sleep)
    total = body.get("total")
    if total is not None and len(items) != int(total):
        raise ValueError(f"{first}：total {total} 但抓到 {len(items)} 筆")
    return items, first


_DATE = re.compile(r"^(\d{2,4})[-/.](\d{1,2})[-/.](\d{1,2})")


def to_date(s):
    """'2024-02-01'、'2024/2/1'、'2024-02-01T09:00:00+08:00'、民國 '113/02/01' → 'YYYY-MM-DD'；認不得回 None。"""
    m = _DATE.match(str(s or "").strip())
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if y < 1911:
        y += 1911
    return f"{y:04d}-{mo:02d}-{d:02d}"


_AREA = re.compile(r"^(.{2}[市縣])(?:第(\d+)選(?:舉)?區|選(?:舉)?區)?$")


def area(name):
    """選區名稱 → (iso, district_id)。區域立委回 ('tnn', 'ly-tnn-06')；不分區與原住民回 (None, None)。
    只寫縣市名、沒寫第幾選區的（單一選區縣市）回 ly-<iso>-01；是否真的單一選區由呼叫端對 district 表確認。"""
    m = _AREA.match(str(name or "").strip().replace("台", "臺"))
    if not m or m.group(1) not in ISO:
        return None, None
    iso = ISO[m.group(1)]
    return iso, f"ly-{iso}-{int(m.group(2) or 1):02d}"


def is_current(row, term=TERM):
    """第 term 屆、沒有離職紀錄的委員（是否離職、離職日期、離職原因任一有值就算離職）。"""
    if int(row.get("屆") or 0) != term:
        return False
    flag = str(row.get("是否離職") or "").strip()
    return flag not in ("是", "Y", "y", "1", "true", "True") and not row.get("離職日期") and not row.get("離職原因")
