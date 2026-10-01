import json
import shutil
from pathlib import Path


def export(conn, out_dir):
    out_dir = Path(out_dir)
    people_dir = out_dir / "people"
    districts_dir = out_dir / "districts"
    shutil.rmtree(people_dir, ignore_errors=True)
    shutil.rmtree(districts_dir, ignore_errors=True)
    people_dir.mkdir(parents=True, exist_ok=True)
    districts_dir.mkdir(parents=True, exist_ok=True)

    people = conn.execute("SELECT person_id, name FROM person").fetchall()
    facts = conn.execute(
        "SELECT fact_key, person_id, kind, date, data, source_url, fetched_at FROM fact"
    ).fetchall()

    facts_by_person = {}
    for row in facts:
        facts_by_person.setdefault(row["person_id"], []).append(row)

    districts = {
        row["district_id"]: {**dict(row), "people": []}
        for row in conn.execute(
            "SELECT district_id, office, name, seats, source_url, fetched_at FROM district"
        )
    }

    for person in people:
        person_id = person["person_id"]
        person_facts = facts_by_person.get(person_id, [])
        by_kind = {}
        for row in person_facts:
            by_kind.setdefault(row["kind"], []).append(row)

        facts_out = {}
        for kind, rows in by_kind.items():
            rows_sorted = _sort_facts(rows)
            facts_out[kind] = [
                {
                    "date": r["date"],
                    "data": json.loads(r["data"]),
                    "source_url": r["source_url"],
                    "fetched_at": r["fetched_at"],
                }
                for r in rows_sorted
            ]

        person_out = {
            "person_id": person_id,
            "name": person["name"],
            "facts": facts_out,
        }
        (people_dir / f"{person_id}.json").write_text(
            json.dumps(person_out, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

        for row in person_facts:
            if row["kind"] not in ("candidacy", "office"):
                continue
            data = json.loads(row["data"])
            district_id = data.get("district_id")
            if district_id is None:
                continue
            if district_id not in districts:
                raise ValueError(f"{row['fact_key']}: district_id {district_id!r} 不在 district 表")
            districts[district_id]["people"].append(
                {
                    "person_id": person_id,
                    "name": person["name"],
                    "kind": row["kind"],
                    "data": data,
                    "source_url": row["source_url"],
                    "fetched_at": row["fetched_at"],
                }
            )

    for district_id, district_out in districts.items():
        people_sorted = sorted(district_out["people"], key=lambda e: (e["person_id"], e["kind"]))
        _write_json(districts_dir / f"{district_id}.json", {**district_out, "people": people_sorted})

    # 村里依縣市拆檔：data/villages/<iso>.json，前端只載所選縣市
    villages_dir = out_dir / "villages"
    shutil.rmtree(villages_dir, ignore_errors=True)
    villages_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "villages.json").unlink(missing_ok=True)  # 舊版的全國單檔
    by_iso = {}
    for row in conn.execute(
        "SELECT villcode, office, town, village, district_id, source_url, fetched_at FROM village_district"
    ):
        county = by_iso.setdefault(_iso_of(row["district_id"]), {"villages": {}, "sources": set()})
        village = county["villages"].setdefault(
            row["villcode"],
            {"villcode": row["villcode"], "town": row["town"], "village": row["village"], "districts": {}},
        )
        village["districts"][row["office"]] = row["district_id"]
        county["sources"].add((row["office"], row["source_url"], row["fetched_at"]))
    for iso, county in by_iso.items():
        vs = county["villages"]
        _write_json(
            villages_dir / f"{iso}.json",
            {
                "villages": [vs[k] for k in sorted(vs)],
                "sources": [
                    {"office": o, "source_url": u, "fetched_at": f} for o, u, f in sorted(county["sources"])
                ],
            },
        )

    districts_by_county = {}
    for district_id in sorted(districts):
        d = districts[district_id]
        districts_by_county.setdefault(_iso_of(district_id), []).append(
            {k: d[k] for k in ("district_id", "office", "name", "seats")}
        )
    _write_json(
        out_dir / "counties.json",
        {
            "counties": [
                {**dict(row), "districts": districts_by_county.get(row["iso"], [])}
                for row in conn.execute(
                    "SELECT iso, moi_code, name, source_url, fetched_at FROM county ORDER BY iso"
                )
            ]
        },
    )


def _iso_of(district_id):
    return district_id.split("-")[1] if district_id.startswith("ly-") else district_id.split("-")[0]


def _write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _sort_facts(rows):
    # date 由新到舊、NULL 排最後；date 相同時依 fact_key 排（穩定排序疊兩次即可）
    by_fact_key = sorted(rows, key=lambda r: r["fact_key"])
    dated = [r for r in by_fact_key if r["date"] is not None]
    undated = [r for r in by_fact_key if r["date"] is None]
    dated.sort(key=lambda r: r["date"], reverse=True)
    return dated + undated
