// 全國縣市、選區與村里的純函式：不碰 DOM，app.js 與測試共用。

// 有深度問政資料（議會質詢、出缺勤等）的縣市；其他縣市只有 2026 候選人名單與選區
export const DEEP_COUNTIES = new Set(['tpe', 'nwt', 'khh', 'txg', 'tnn', 'hua', 'hsz']);  // 與 app.js 的 RECORDS 一致

// 各縣市議會官網：2026-10-02 逐一 curl 確認 HTTP 200 且頁面標題為該議會
export const COUNCIL_SITES = {
  tpe: 'https://www.tcc.gov.tw/', nwt: 'https://www.ntp.gov.tw/', tao: 'https://www.tycc.gov.tw/',
  txg: 'https://www.tccc.gov.tw/', tnn: 'https://www.tncc.gov.tw/', khh: 'https://www.kcc.gov.tw/',
  hsq: 'https://www.hcc.gov.tw/', mia: 'https://www.mcc.gov.tw/', cha: 'https://www.chcc.gov.tw/',
  nan: 'https://www.ntcc.gov.tw/', yun: 'https://www.ylcc.gov.tw/', cyq: 'https://www.cyscc.gov.tw/',
  pif: 'https://www.ptcc.gov.tw/', ila: 'https://www.ilcc.gov.tw/', hua: 'https://www.hlcc.gov.tw/',
  ttt: 'https://www.taitungcc.gov.tw/', pen: 'https://www.phcouncil.gov.tw/', kin: 'https://www.kmcc.gov.tw/',
  lie: 'https://www.mtcc.gov.tw/', kee: 'https://www.kmc.gov.tw/', hsz: 'https://www.hsinchu-cc.gov.tw/',
  cyi: 'https://www.cycc.gov.tw/',
};

// 縣市名稱（同 counties.json）：出處標籤要在資料載入前就能由網域推得議會名稱
export const COUNTY_NAMES = {
  tpe: '臺北市', nwt: '新北市', tao: '桃園市', txg: '臺中市', tnn: '臺南市', khh: '高雄市', hsq: '新竹縣', mia: '苗栗縣',
  cha: '彰化縣', nan: '南投縣', yun: '雲林縣', cyq: '嘉義縣', pif: '屏東縣', ila: '宜蘭縣', hua: '花蓮縣', ttt: '臺東縣',
  pen: '澎湖縣', kin: '金門縣', lie: '連江縣', kee: '基隆市', hsz: '新竹市', cyi: '嘉義市',
};

// 議會官網網域（去掉 www.）→ 議會名稱，給腳註的發布機關用
export const COUNCIL_PUBLISHERS = Object.entries(COUNCIL_SITES)
  .map(([iso, u]) => [new URL(u).hostname.replace(/^www\./, ''), `${COUNTY_NAMES[iso]}議會`]);

export const KIND_LABEL ={ plains: '平地原住民', mountain: '山地原住民' };

// 選區 id → 縣市代碼（立委選區是 ly-<iso>-NN）
export const isoOf = (districtId) => String(districtId).split('-')[String(districtId).startsWith('ly-') ? 1 : 0];

// 縣市名的最後一字（市／縣）與其下一層的稱呼
export const suffixOf = (county) => county.name.slice(-1);
export const townWord = (county) => (suffixOf(county) === '縣' ? '鄉鎮市' : '行政區');

// 縣市清單：直轄市（6xxxx）、臺灣省各縣市（10xxx）、福建省（09xxx：金門、連江），同組內依內政部代碼
export function countyOrder(counties) {
  const key = (c) => `${{ 6: 0, 1: 1 }[c.moi_code[0]] ?? 2}${c.moi_code}`;
  return [...counties].sort((a, b) => key(a).localeCompare(key(b)));
}

// 鄉鎮市區（依 villcode 順序，不重複）
export function townsOf(villages) {
  return [...new Set(villages.map((v) => v.town))];
}

const idsOf = (vs, key) => new Set(vs.map((v) => v.districts[key]));

// 這個鄉鎮市區跨了幾個區域議員選區；大於 1 時必須選到村里才能判定
export function needsVillage(villages, iso, town) {
  return idsOf(villages.filter((v) => v.town === town), `${iso}_councilor`).size > 1;
}

// 鄉鎮市區（＋村里）＋原住民身分 → { id, fallback }；無法判定時回傳 null。
// 縣市沒有該類原住民選區（資料沒有 <iso>_councilor_<kind> 鍵）時，依戶籍所在的區域選區投票，fallback 為 true。
export function councilDistrictFor(villages, iso, { town, villcode = '', indigenous = 'none' }) {
  const inTown = villages.filter((v) => v.town === town);
  if (!inTown.length) return null;
  if (KIND_LABEL[indigenous]) {
    const key = `${iso}_councilor_${indigenous}`;
    if (villages.some((v) => v.districts[key])) {
      const ids = idsOf(inTown, key);
      return ids.size === 1 && !ids.has(undefined) ? { id: [...ids][0], fallback: false } : null;
    }
  }
  const scope = villcode ? inTown.filter((v) => v.villcode === villcode) : inTown;
  const ids = idsOf(scope, `${iso}_councilor`);
  if (ids.size !== 1 || ids.has(undefined)) return null;
  return { id: [...ids][0], fallback: KIND_LABEL[indigenous] !== undefined };
}

// 職稱：立法委員／臺北市長／新竹縣長／臺北市議員
export function officeLabel(office, county) {
  if (office === 'legislator') return '立法委員';
  if (!county) return office;
  if (String(office).endsWith('_mayor')) return `${county.name}長`;
  if (String(office).endsWith('_councilor')) return `${county.name}議員`;
  return office;
}

// 選區標題：縣市長選區只寫職稱；議員選區是「臺北市議員 第1選舉區」（選區名去掉縣市前綴）
export function districtTitle(d, county) {
  if (String(d.office).endsWith('_mayor')) return officeLabel(d.office, county);
  if (d.office === 'legislator' || !county) return d.name;
  return `${officeLabel(d.office, county)} ${d.name.startsWith(county.name) ? d.name.slice(county.name.length) : d.name}`;
}

// 候選人排序：臺北用登記冊序號 reg_no，其他縣市用中選會名冊順序 list_order；都沒有的排最後
export function candidateOrder(list) {
  const n = (p) => p.data?.reg_no ?? p.data?.list_order ?? Infinity;
  return [...list].sort((a, b) => n(a) - n(b));
}

// 選區副標：縣市長是全縣市幾個鄉鎮市區；原住民選區看涵蓋範圍；區域選區列出鄉鎮市區（只含部分村里的標「部分」）
export function districtSub(d, villages, county) {
  const iso = county.iso;
  const towns = townsOf(villages);
  if (String(d.office).endsWith('_mayor')) return `全${suffixOf(county)} ${towns.length} 個${townWord(county)}`;
  for (const [kind, label] of Object.entries(KIND_LABEL)) {
    const covered = townsOf(villages.filter((v) => v.districts[`${iso}_councilor_${kind}`] === d.district_id));
    if (!covered.length) continue;
    return covered.length === towns.length
      ? `具${label}身分的全${suffixOf(county)}選民`
      : `具${label}身分、戶籍在${covered.join('、')}的選民`;
  }
  const key = `${iso}_councilor`;
  return townsOf(villages.filter((v) => v.districts[key] === d.district_id))
    .map((t) => (villages.some((v) => v.town === t && v.districts[key] !== d.district_id) ? `${t}（部分）` : t))
    .join('、');
}
