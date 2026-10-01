#!/bin/bash
# 縣市界 SHP → site/assets/taiwan-counties.svg（V11 §5）。只在開發時跑；網站執行時不依賴任何套件。
#
# 來源：內政部國土測繪中心「直轄市、縣市界線(TWD97經緯度)」https://data.gov.tw/dataset/7442
#       政府資料開放授權條款第 1 版（需標示出處，已寫進 SVG 註解）
# 做法：簡化 1%；本島＋澎湖留原位（剪掉釣魚臺、東沙、南沙、彭佳嶼）；
#       金門（剪掉烏坵）、馬祖移進台灣海峽的虛線框，馬祖放大約 2.5 倍讓它點得到；
#       每個縣市一個 <path id="county-<iso>" data-moi="<內政部縣市代碼>">，iso 取自 etl/sources/national_districts.py；
#       插圖虛線框是 <path id="inset-kin">、<path id="inset-lie">，前端可把點框視為點該縣市。
#
# 用法：scripts/build_map.sh（需要 curl、unzip、python3、npx；可用 MAPSHAPER=/path/to/mapshaper 指定已安裝的版本）
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/site/assets/taiwan-counties.svg"
M=${MAPSHAPER:-"npx -y mapshaper@0.7.70"}
ZIP_URL='https://www.tgos.tw/tgos/VirtualDir/Product/1cd4f4c9-6b01-4cf9-bf6c-23a73aa17d24/%E7%9B%B4%E8%BD%84%E5%B8%82%E3%80%81%E7%B8%A3(%E5%B8%82)%E7%95%8C%E7%B7%9A1140318.zip'
PROJ='+proj=tmerc +lat_0=0 +lon_0=121 +k=0.9999 +x_0=250000 +y_0=0 +ellps=GRS80 +units=m'

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

curl -sSf -A civic-lens-etl/0.1 -o "$T/county.zip" "$ZIP_URL"
# zip 內另有 Big5 檔名的 xlsx，macOS unzip 解不開，只取 SHP 相關檔
unzip -q -o "$T/county.zip" 'COUNTY_MOI_*' -d "$T"
SHP=$(ls "$T"/COUNTY_MOI_*.shp)

# 縣市名 → iso 對照（單一真相在 ETL 模組）
ISO_JS=$(cd "$ROOT" && python3 -c 'import json; from etl.sources.national_districts import COUNTIES; print(json.dumps({n: i for i, n in COUNTIES}, ensure_ascii=False))')

$M -i "$SHP" encoding=utf8 -simplify 1% weighted keep-shapes \
  -filter-fields COUNTYCODE,COUNTYNAME -o "$T/s.json" format=geojson
$M -i "$T/s.json" -filter "COUNTYNAME!='金門縣' && COUNTYNAME!='連江縣'" \
  -clip bbox=119.25,21.85,122.15,25.70 -o "$T/main.json"
$M -i "$T/s.json" -filter "COUNTYNAME=='金門縣'" -clip bbox=118.10,24.35,118.60,24.60 \
  -affine shift=1.30,-0.15 -o "$T/kinmen.json"
# 馬祖原範圍約 0.60°×0.44°，fit-bbox 保持長寬比，放進 1.5°×1.1° 的框 ≈ 2.5 倍
$M -i "$T/s.json" -filter "COUNTYNAME=='連江縣'" -affine fit-bbox=118.95,24.75,120.45,25.85 -o "$T/matsu.json"
$M -i "$T/main.json" "$T/kinmen.json" "$T/matsu.json" combine-files \
  -merge-layers force name=counties \
  -filter-slivers min-area=0.3km2 \
  -each "id='county-' + ($ISO_JS)[COUNTYNAME]; moi=COUNTYCODE" \
  -rectangle bbox=119.36,24.16,119.94,24.49 name=frame_kinmen -each "id='inset-kin'" target=frame_kinmen \
  -rectangle bbox=118.90,24.70,120.50,25.90 name=frame_matsu -each "id='inset-lie'" target=frame_matsu \
  -merge-layers target=frame_kinmen,frame_matsu name=frames force \
  -proj "$PROJ" target=* \
  -style target=counties fill='#dde5ee' stroke='#ffffff' stroke-width=0.6 \
  -style target=frames fill=none stroke='#8a96a3' stroke-width=0.6 stroke-dasharray='3 2' \
  -o "$T/map.svg" target=counties,frames id-field=id svg-data=moi width=600 precision=0.1

python3 - "$T/map.svg" "$OUT" <<'EOF'
import re, sys
svg = open(sys.argv[1], encoding="utf-8").read()
ids = re.findall(r'<path[^>]*id="(county-[a-z]{3})"', svg)
if len(ids) != 22 or len(set(ids)) != 22:
    sys.exit(f"縣市 path 數量不對：{ids}")
note = ("<!-- 資料來源：內政部國土測繪中心「直轄市、縣市界線(TWD97經緯度)」1140318 版 "
        "https://data.gov.tw/dataset/7442 ，政府資料開放授權條款第 1 版。"
        "由 scripts/build_map.sh 簡化 1%；金門、馬祖為移位的插圖（虛線框），馬祖放大約 2.5 倍。 -->")
svg = re.sub(r"(<svg[^>]*>)", lambda m: m.group(1) + "\n" + note, svg, count=1)
open(sys.argv[2], "w", encoding="utf-8").write(svg)
print(f"{sys.argv[2]}: {len(svg.encode())} B，{len(ids)} 個縣市")
EOF
