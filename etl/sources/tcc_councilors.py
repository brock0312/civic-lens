"""臺北市議會第 14 屆現任議員名錄（M4）＋人工維護的身分對照表 data/identity.csv。"""
import csv
import re
import time
from pathlib import Path

from etl.db import upsert, upsert_fact, upsert_person
from etl.fetch import get, now_utc

# qtype=1..8 只決定頁面預設展開哪個選區分頁，每一頁都含全部 8 個選區（見 docs/validation/M4-interpellations.md）
ROSTER_URL = "https://www.tcc.gov.tw/cp.aspx?n=13898"
PROFILE_URL = "https://www.tcc.gov.tw/Councilor_Content.aspx?n=13898&s={}"  # 議員個人頁，有出生年月日（民國）
IDENTITY_PATH = Path(__file__).resolve().parents[2] / "data" / "identity.csv"
SOURCE = "tcc14"
TERM_START = "2022-12-25"  # 公報第129卷第14期「第14屆就職典禮暨成立大會（111年12月25、26日）」

DISTRICTS = {f"第{c}選區": f"tpe-council-0{i}" for i, c in enumerate("一二三四五六七八", 1)}
SECTION = re.compile(r'<a\s+title="(第.選區)<br>[^"]*"')
MEMBER = re.compile(
    r'<a class="div" href="Councilor_Content\.aspx\?n=13898&s=(\d+)" title="([^"]+)"[^>]*>.*?'
    r'<img src="images/party_logo\d+\.jpg" alt="([^"]+)"><span>([^<]+)</span>',
    re.S,
)


def parse_roster(html):
    """回傳 [{name, district_id, party, sid}]；選區取自頁面上的分區標題，sid 是個人頁編號。"""
    parts = SECTION.split(html)
    out = []
    for i in range(1, len(parts), 2):
        if parts[i] not in DISTRICTS:
            raise ValueError(f"未知的選區標題：{parts[i]!r}")
        body = parts[i + 1].split('<div class="hd">')[0]  # 只看到下一個分區標題為止
        n_links = body.count('<a class="div" href="Councilor_Content.aspx')
        rows = MEMBER.findall(body)
        if len(rows) != n_links:
            raise ValueError(f"{parts[i]}：{n_links} 個議員連結只解析出 {len(rows)} 筆")
        for sid, title, party, name in rows:
            if title != name:
                raise ValueError(f"連結 title {title!r} 與姓名 {name!r} 不一致")
            out.append({"name": name, "district_id": DISTRICTS[parts[i]], "party": party, "sid": sid})
    if {r["district_id"] for r in out} != set(DISTRICTS.values()):
        raise ValueError(f"名錄選區不齊：{sorted({r['district_id'] for r in out})}")
    names = [r["name"] for r in out]
    if len(names) != len(set(names)):
        raise ValueError("名錄上有同名議員，source_key 用姓名會撞，需改用其他鍵")
    return out


def load_identity(path=IDENTITY_PATH, source=SOURCE):
    """回傳 {source_key: (person_id, verified_by)}，只取指定 source 的列。"""
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["source"] == source]
    out = {}
    for r in rows:
        if r["source_key"] in out:
            raise ValueError(f"identity.csv 重複：{source} {r['source_key']}")
        if not r["person_id"] or not r["verified_by"]:
            raise ValueError(f"identity.csv 缺 person_id 或 verified_by：{r}")
        out[r["source_key"]] = (r["person_id"], r["verified_by"])
    return out


def write_roster(conn, roster, identity, fetched_at):
    """寫入有對照的議員，回傳 {姓名: person_id}；沒對照的跳過（不確定就不顯示）。"""
    mapped = {}
    for r in roster:
        if r["name"] not in identity:
            print(f"警告：{SOURCE} 議員 {r['name']}（{r['district_id']}）不在 identity.csv，跳過")
            continue
        person_id, verified_by = identity[r["name"]]
        upsert(conn, "person", {"person_id": person_id, "name": r["name"]}, ("person_id",))
        upsert(
            conn, "person_source_id",
            {"source": SOURCE, "source_key": r["name"], "person_id": person_id, "verified_by": verified_by},
            ("source", "source_key"),
        )
        upsert_fact(
            conn, f"office:tcc14:{person_id}", person_id, "office",
            {
                "office": "tpe_councilor",
                "term": 14,
                "district_id": r["district_id"],
                "party": r["party"],
                "title": "臺北市議員（第14屆）",
            },
            ROSTER_URL, fetched_at, date=TERM_START,
        )
        mapped[r["name"]] = person_id
    return mapped


PROFILE_NAME = re.compile(r'<span id="ContentPlaceHolder1_FormView1_CouncilorNameLabel">([^<]*)</span>')
PROFILE_BIRTH = re.compile(r'<span id="ContentPlaceHolder1_FormView1_BirthdayLabel">([^<]*)</span>')


def parse_birth_date(html, name):
    """議員個人頁 → YYYY-MM-DD。頁面上的姓名必須與名錄一致，生日格式不對就 raise。"""
    names = PROFILE_NAME.findall(html)
    if names != [name]:
        raise ValueError(f"個人頁姓名 {names} 與名錄 {name!r} 不一致")
    births = PROFILE_BIRTH.findall(html)
    m = re.fullmatch(r"民國(\d+)年(\d+)月(\d+)日", births[0].strip()) if len(births) == 1 else None
    if not m:
        raise ValueError(f"{name} 個人頁生日格式未知：{births}")
    y, mo, d = (int(x) for x in m.groups())
    return f"{y + 1911:04d}-{mo:02d}-{d:02d}"


def write_birth_dates(conn, roster, mapped):
    # 只寫 birth_date，其他欄位不動；tpe_bulletin_2022 用這個官方生日確認公報上的人是同一人
    for r in roster:
        if r["name"] not in mapped:
            continue
        time.sleep(1)  # ponytail: 固定 1 秒間隔，53 頁約 1 分鐘
        birth = parse_birth_date(get(PROFILE_URL.format(r["sid"])).decode("utf-8"), r["name"])
        # 要連 name 一起給：INSERT … ON CONFLICT 會先檢查 NOT NULL，只給 birth_date 會失敗
        upsert_person(conn, mapped[r["name"]], r["name"], birth_date=birth)


def run(conn):
    roster = parse_roster(get(ROSTER_URL).decode("utf-8"))
    mapped = write_roster(conn, roster, load_identity(), now_utc())
    write_birth_dates(conn, roster, mapped)
