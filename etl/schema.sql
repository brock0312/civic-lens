-- 自編人物主鍵；各來源的 ID 只放在 person_source_id 當對照（PLAN §5）
CREATE TABLE IF NOT EXISTS person (
  person_id  TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  birth_date TEXT,     -- YYYY-MM-DD，選舉公報才有
  birth_year INTEGER   -- 中選會 JSON 只有出生年
);

-- 不確定就不要寫進來：比對結果不唯一的，一律不建對照
CREATE TABLE IF NOT EXISTS person_source_id (
  source      TEXT NOT NULL,  -- 例：cec_cand（每次參選一個）、ly_legislator
  source_key  TEXT NOT NULL,
  person_id   TEXT NOT NULL REFERENCES person(person_id),
  verified_by TEXT NOT NULL,  -- 誰、依據什麼確認身分
  PRIMARY KEY (source, source_key)
);

-- 所有對外顯示的事實；沒有出處與擷取時間就寫不進來
CREATE TABLE IF NOT EXISTS fact (
  fact_key   TEXT PRIMARY KEY,  -- 由 ETL 自訂的穩定鍵，重跑時據此 upsert
  person_id  TEXT NOT NULL REFERENCES person(person_id),
  kind       TEXT NOT NULL,     -- candidacy / office / interpellation / platform ...
  date       TEXT,              -- YYYY-MM-DD
  data       TEXT NOT NULL CHECK (json_valid(data)),
  source_url TEXT NOT NULL CHECK (source_url LIKE 'http%'),
  fetched_at TEXT NOT NULL      -- 這個版本的內容第一次擷取到的時間（ISO 8601 UTC）
);
CREATE INDEX IF NOT EXISTS fact_person ON fact(person_id, kind);

-- 選區；district_id 例：tpe-council-01、tpe-mayor、ly-tpe-01、hsq-council-14
CREATE TABLE IF NOT EXISTS district (
  district_id TEXT PRIMARY KEY,
  office      TEXT NOT NULL,   -- <iso>_councilor / <iso>_mayor / legislator
  name        TEXT NOT NULL,
  seats       INTEGER NOT NULL,
  source_url  TEXT NOT NULL CHECK (source_url LIKE 'http%'),
  fetched_at  TEXT NOT NULL
);

-- 村里 → 選區。投票以戶籍為準，查詢鍵是戶籍所在的里，不是使用者目前的位置
CREATE TABLE IF NOT EXISTS village_district (
  villcode    TEXT NOT NULL,   -- 內政部 VILLCODE = prv_code + city_code + dept_code + li_code[1:]
  office      TEXT NOT NULL,
  town        TEXT NOT NULL,
  village     TEXT NOT NULL,
  district_id TEXT NOT NULL REFERENCES district(district_id),
  source_url  TEXT NOT NULL CHECK (source_url LIKE 'http%'),
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY (villcode, office)
);

-- 來源的執行狀態（例如增量爬蟲已涵蓋哪些議員）；不對外顯示
CREATE TABLE IF NOT EXISTS source_state (
  source TEXT PRIMARY KEY,
  state  TEXT NOT NULL CHECK (json_valid(state))
);

-- 縣市；iso 是 ISO 3166-2:TW 小寫後三碼（tpe、nwt…），moi_code 是內政部 5 碼縣市代碼
CREATE TABLE IF NOT EXISTS county (
  iso        TEXT PRIMARY KEY,
  moi_code   TEXT NOT NULL,
  name       TEXT NOT NULL,
  source_url TEXT NOT NULL CHECK (source_url LIKE 'http%'),
  fetched_at TEXT NOT NULL
);
