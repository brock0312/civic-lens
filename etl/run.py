import sys
import traceback
from pathlib import Path

from etl.db import open_db, dump
from etl.export import export
from etl.sources import (
    hsz_book, hsz_videos, hua_book, hua_videos, khh_attendance, khh_videos, ly_legislators, ly_records, national_bulletin_2022, national_candidates,
    national_councilors, national_districts, national_heads, national_legislators, nwt_book, nwt_videos, tcc_attendance,
    tcc_councilors, tcc_interpellations, tcc_summaries, tcc_videos, ttt_book,
    tpe_bulletin_2022, tpe_candidates, tpe_districts, tnn_videos, txg_videos,
)

ROOT = Path(__file__).resolve().parent.parent

# 每個模組提供 run(conn)；districts 要先跑（FK）；公報要在 tcc_councilors（寫生日）與 tpe_candidates（登記冊對照）之後
# national_candidates 要在 national_districts（名額核對）與 tpe_candidates（臺北交叉核對）之後
# national_heads、national_councilors 要在 national_candidates 之後（串接 2026 候選人）
# khh_videos、txg_videos、tnn_videos、khh_attendance、nwt_book、nwt_videos、hua_book、hua_videos、hsz_book、hsz_videos、ttt_book 要在 national_councilors 之後（現任議員的任職 fact 與 person_id）
# national_bulletin_2022 要在 national_heads、national_councilors 之後（掛到有任職 fact 的人）
# tcc_attendance 要在 tcc_councilors（identity 對照）之後
# tcc_summaries 讀 repo 內的 data/summaries/，不連網；要在 tcc_councilors（person 列）之後
# ly_legislators 要在 national_legislators（立委選區）與 national_candidates、tpe_candidates（串接 2026 候選人）之後；ly_records 在它之後
# nwt_videos 只列清單、連新北議會影音網首頁：單支影片網址依賴 session，官方 YouTube 沒有逐人對應（V15 已定案第 6 點）
SOURCES = [
    tpe_districts, tpe_candidates, national_districts, national_legislators, national_candidates, national_heads,
    national_councilors, khh_videos, txg_videos, tnn_videos, khh_attendance, nwt_book, nwt_videos, hua_book, hua_videos,
    hsz_book, hsz_videos, ttt_book, national_bulletin_2022,
    tcc_councilors, tcc_interpellations, tcc_videos, tcc_attendance, tcc_summaries, tpe_bulletin_2022, ly_legislators, ly_records,
]


def main():
    db_path = ROOT / "data" / "civic.db"
    dump_path = ROOT / "data" / "civic.sql"
    conn = open_db(db_path, dump_path)

    had_failure = False
    for source in SOURCES:
        try:
            source.run(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            traceback.print_exc()
            had_failure = True

    # 先 dump 再 export：export 出錯時，已成功抓到的資料仍會被保存
    dump(conn, dump_path)
    export(conn, ROOT / "site" / "data")

    if had_failure:
        sys.exit(1)


if __name__ == "__main__":
    main()
