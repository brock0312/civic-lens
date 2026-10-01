import json
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ponytail: 只靠 IF NOT EXISTS 補新表；改既有欄位時要手寫 migration
def open_db(db_path, dump_path):
    db_path = Path(db_path)
    dump_path = Path(dump_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    # dump 是 CI 中處理外部輸入的 job 產出的；禁止 ATTACH（連帶擋住 VACUUM INTO），讓被竄改的 dump 不能寫出 DB 以外的檔案
    conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    if dump_path.exists():
        # iterdump 依表名排序，可能把 fact 排在 person 前面；插入時關掉 FK 檢查避免順序問題
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(dump_path.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def dump(conn, dump_path):
    # 生日只用於同一次執行內的身分比對（tpe_bulletin_2022 對 tcc_councilors 寫入的生日），不進公開 dump（個資法第 5 條最小化）
    # civic.db 每次都由 dump 重建、export 不讀生日，所以直接清空正在使用的連線沒有副作用
    conn.execute("UPDATE person SET birth_date = NULL, birth_year = NULL")
    conn.commit()
    with open(dump_path, "w", encoding="utf-8") as f:
        for line in conn.iterdump():
            f.write(line + "\n")


def upsert(conn, table, row, key):
    # 表名與欄位名都是程式內寫死的常數，不是外部輸入，所以可以用 f-string 組 SQL；值一律走參數
    cols = list(row)
    others = [c for c in cols if c not in key]
    changed = " OR ".join(f"{table}.{c} IS NOT excluded.{c}" for c in others if c != "fetched_at")
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT({', '.join(key)}) DO UPDATE SET "
        f"{', '.join(f'{c} = excluded.{c}' for c in others)} WHERE {changed}",
        [row[c] for c in cols],
    )


def upsert_person(conn, person_id, name, birth_date=None, birth_year=None):
    # 沒給的生日欄位不寫，避免把其他來源（例如選舉公報）補上的生日洗成 NULL
    row = {"person_id": person_id, "name": name}
    if birth_date is not None:
        row["birth_date"] = birth_date
    if birth_year is not None:
        row["birth_year"] = birth_year
    upsert(conn, "person", row, ("person_id",))


def upsert_fact(conn, fact_key, person_id, kind, data, source_url, fetched_at, date=None):
    upsert(
        conn, "fact",
        {
            "fact_key": fact_key,
            "person_id": person_id,
            "kind": kind,
            "date": date,
            "data": json.dumps(data, ensure_ascii=False, sort_keys=True),
            "source_url": source_url,
            "fetched_at": fetched_at,
        },
        ("fact_key",),
    )
