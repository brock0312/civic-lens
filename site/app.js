// civic-lens 靜態前端：hash routing，資料全部從相對路徑 data/ 讀取。
import {
  DEEP_COUNTIES, COUNCIL_SITES, COUNCIL_PUBLISHERS, KIND_LABEL, isoOf, townWord, countyOrder, townsOf, needsVillage,
  councilDistrictFor, officeLabel, districtTitle, candidateOrder, districtSub,
} from './geo.js';

const PUBLISHERS = [['cec.gov.tw', '中央選舉委員會'], ['election.gov.taipei', '臺北市選舉委員會'], ['moi.gov.tw', '內政部'],
  ['ly.govapi.tw', '立法院（經 OpenFun 立法院 API，CC BY 4.0）'], ['ly.gov.tw', '立法院'], ...COUNCIL_PUBLISHERS];
export const INTERPELLATION_PAGE = 20;
const NO_RECORD ='本站目前沒有此人的任內問政紀錄（收錄範圍：第14屆臺北市議員書面質詢與口頭質詢影片）';
// 非深度縣市的縣市頁說明：列出目前提供的資料，措辭中性；候選人中的現任議員有沒有標示依 counties.json 的 councilor_roster
// councilor_bulletin：候選人中的現任議員另有 2022 選舉公報政見與學經歷
export const countyNote = (county) => `目前提供 2026 候選人名單與選區，候選人中的現任${county.councilor_roster ? '議員與' : ''}${county.name}長會標示${county.councilor_bulletin ? '，並收錄現任議員的 2022 選舉公報政見與學經歷' : ''}；${county.name}議會的問政紀錄仍在建置中。`;
// 首頁縣市清單的標籤：深度縣市「含問政紀錄」；其他縣市有現任議員公報時「含 2022 公報」
export const BULLETIN_TAG = '含 2022 公報';
export const countyTag = (c) => (DEEP_COUNTIES.has(c.iso) ? '含問政紀錄' : c.councilor_bulletin ? BULLETIN_TAG : '');
// 首頁縣市清單下的說明（counties 已依顯示順序排好）
export function homeNote(counties) {
  const roster = counties.filter((c) => c.councilor_roster && !DEEP_COUNTIES.has(c.iso)).map((c) => c.name);
  const bulletin = counties.some((c) => countyTag(c) === BULLETIN_TAG);
  return `標示「含問政紀錄」的縣市另收錄議員的問政紀錄；${bulletin ? `標示「${BULLETIN_TAG}」的縣市另收錄候選人中現任議員的 2022 選舉公報政見與學經歷；` : ''}其他縣市目前提供 2026 候選人名單與選區，候選人中的現任縣市長${roster.length ? `與${roster.join('、')}的現任議員` : ''}會標示，議員問政紀錄仍在建置中。`;
}
// 非深度縣市：問政紀錄還沒建置，措辭不能讓人以為此人沒有問政
export const noRecordNote = (county) => `${county.name}議會的問政紀錄仍在建置中，本站目前尚未收錄。`;
// 現任議員但所在縣市還沒有問政紀錄：「做了什麼」只有任職期間，要註明紀錄未收錄，不能讓人以為沒有問政
export function pendingRecordNotes(offices, counties) {
  const isos = offices.filter((f) => String(f.data?.office).endsWith('_councilor') && f.data?.district_id)
    .map((f) => isoOf(f.data.district_id)).filter((iso) => !DEEP_COUNTIES.has(iso) && counties.get(iso));
  return [...new Set(isos)].map((iso) => noRecordNote(counties.get(iso)));
}

// 政黨字串 → 黨徽相對路徑；只有「無」「無黨籍」用本站的「無」圖樣，查不到就回傳 null（只顯示文字）
export function emblemFor(party, parties) {
  if (party === '無' || party === '無黨籍') return 'assets/none.svg';
  const path = parties?.[party]?.emblem;
  return /^parties\/[\w.-]+$/.test(path || '') ? path : null;
}

// 質詢紀錄依日期新到舊，切成先顯示的前 n 筆與其餘
export function splitLatest(list, n = INTERPELLATION_PAGE) {
  const sorted = [...list].sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')));
  return { shown: sorted.slice(0, n), hidden: sorted.slice(n) };
}

// 秒數 → h:mm:ss（無條件捨去到秒）
export function hms(sec) {
  const t = Math.floor(Number(sec) || 0);
  const pad = (n) => String(n).padStart(2, '0');
  return `${Math.floor(t / 3600)}:${pad(Math.floor(t / 60) % 60)}:${pad(t % 60)}`;
}

// 口頭質詢影片的播放說明：影片只切到「組」，多人組要講清楚不是個人片段
export function videoNote(d) {
  if (d?.whole_session) {  // 新北：整場會議影片，沒有個人起點
    const n = Number(d.group_size) || 0;
    return `整場會議影片，本人發言時段未標示${n > 1 ? `；本場發言議員 ${n} 位` : ''}`;
  }
  if (d?.gid) return '從該議員發言處開始播放';  // 高雄 iVOD（有 gid）逐人標記發言起點，沒有質詢組
  if (d?.clip) {  // 臺中、臺南：議會逐人剪輯的影片；臺中聯合質詢是同組議員共用一支
    const n = Number(d.group_size) || 0;
    return n > 1 ? `${n} 位議員聯合質詢的影片` : '影片即該議員的質詢時段';
  }
  const size = Number(d?.group_size) || 0;
  const group = size > 1 ? `同組 ${size} 位議員，未細分到個人` : '';
  if (d?.seekable) return group ? `從本組開始播放；${group}` : '從本組開始播放';
  return `本組約從 ${hms(d?.start_sec)} 開始${group ? `；${group}` : ''}`;
}

// 質詢部門：固定順序，不依數量排序
export const DEPTS = ['民政', '財政建設', '教育', '交通', '警政衛生', '工務'];
// 高雄市議會：八個審查委員會的順序，再加都市計畫委員會業務質詢
export const KHH_DEPTS = ['民政', '財經', '教育', '交通', '警消衛環', '工務', '社政', '農林', '都市計畫委員會'];
// 臺中市議會：業務質詢六個分組，依定期會的質詢順序
export const TXG_DEPTS = ['民政', '財政經濟', '教育文化', '交通地政', '警消環衛', '都發建設水利'];

// 深度縣市的收錄範圍：部門清單、有沒有收書面質詢、沒有紀錄時的說明（措辭中性，不暗示此人沒有問政）
export const RECORDS = {
  tpe: { depts: DEPTS, written: true, noRecord: NO_RECORD },
  khh: {
    depts: KHH_DEPTS, written: false,
    noRecord: '本站目前沒有此人的口頭質詢影片紀錄（收錄範圍：第4屆高雄市議員口頭質詢影片）；高雄市議會的書面質詢紀錄仍在建置中。',
  },
  // 臺中、臺南：只有口頭質詢影片（V15）；書面質詢與出缺勤沒有找到逐人的官方紀錄，只說「尚未收錄」
  txg: {
    depts: TXG_DEPTS, written: false, note: '出缺勤紀錄本站尚未收錄。',
    noRecord: '本站目前沒有此人的口頭質詢影片紀錄（收錄範圍：第4屆臺中市議員口頭質詢影片）；書面質詢與出缺勤本站尚未收錄。',
  },
  tnn: {
    depts: [], written: false, note: '出缺勤紀錄本站尚未收錄。',
    videoBlurb: '連結至臺南市議會發布在 YouTube 的議事影片，影片來源：臺南市議會。',
    noRecord: '本站目前沒有此人的口頭質詢影片紀錄（收錄範圍：第4屆臺南市議員市政總質詢影片）；書面質詢與出缺勤本站尚未收錄。',
  },
  // 新北（V15 已定案第 4 點）：書面質詢一人一會期一份掃描 PDF（不抓題目）、整場會議影片、大會出席只有出席名單
  nwt: {
    depts: [], written: true,
    // ponytail: 口頭質詢影片暫不收：新北影音網站的單支影片連結依賴 session，連續開啟會出錯（V15 已定案第 6 點）
    countLine: (written) => `書面質詢及答復 <span class="num">${written.length}</span> 個會期（掃描檔）；口頭質詢影片尚未收錄`,
    writtenBlurb: '每個會期一筆，連結至新北市議會議事錄附錄「書面質詢及答復」的掃描檔（PDF），本站未擷取個別題目；只收個人書面質詢，不含聯合質詢。',
    noRecord: '本站目前沒有此人的書面質詢紀錄（收錄範圍：第4屆新北市議員個人書面質詢及答復；口頭質詢影片尚未收錄）。',
  },
};

// 各部門質詢筆數（書面＋口頭），依 depts 順序輸出，含 0 筆；不在 depts 的（如市政總質詢）計入 other
export function deptCounts(inters, depts = DEPTS) {
  const counts = depts.map((dept) => [dept, inters.filter((f) => f.data?.dept === dept).length]);
  return { counts, other: inters.length - counts.reduce((s, [, n]) => s + n, 0) };
}

// 出席率、請假率：分母是總筆數；議事錄沒有缺席欄位，所以不算缺席率
export function attendanceRates(list) {
  const total = list.length;
  const present = list.filter((f) => f.data?.status === 'present').length;
  const leave = list.filter((f) => f.data?.status === 'leave').length;
  return { total, present, leave, presentRate: total ? present / total : 0, leaveRate: total ? leave / total : 0 };
}

// 高雄：每筆是一份「議員出席情形統計表」的合計（meetings 次會議）。出席、請假、公差／公假的分母是各表會議次數合計；
// 缺席的分母只算有缺席欄的表（舊版沒有缺席欄，absent 為 null）。公差、公假是公務，和請假分開列（使用者 2026-10-03 決定）
export const LEAVE_TYPES = ['請假', '病假', '喪假', '事假'];
export const DUTY_TYPES = ['公差', '公假'];
export function attendanceTotals(list) {
  const sum = (get, rows = list) => rows.reduce((s, f) => s + (Number(get(f.data || {})) || 0), 0);
  const withAbsent = list.filter((f) => f.data?.absent != null);
  const total = sum((d) => d.meetings);
  const absentTotal = sum((d) => d.meetings, withAbsent);
  const types = (keys) => keys.map((k) => [k, sum((d) => d.leave_types?.[k])]).filter(([, n]) => n);
  const present = sum((d) => d.present);
  const leave = sum((d) => d.leave);
  const duty = sum((d) => d.duty);
  const absent = sum((d) => d.absent, withAbsent);
  const rate = (n, d = total) => (d ? n / d : 0);
  return {
    total, absentTotal, present, leave, duty, absent,
    leaveTypes: types(LEAVE_TYPES), dutyTypes: types(DUTY_TYPES),
    presentRate: rate(present), leaveRate: rate(leave), dutyRate: rate(duty), absentRate: rate(absent, absentTotal),
  };
}

export const KHH_ATTENDANCE_NOTE = '依高雄市議會公報附錄「議員出席情形統計表」：每份統計表涵蓋一個會期（成立大會、臨時會或定期大會）的每一次大會會議，逐次標記每位議員出席、請假（含病假、喪假、事假）、公差、公假或缺席，本站照各表的合計數加總。公差、公假是執行公務，和請假分開列。出席、請假、公差／公假的比例以全部統計表的會議次數為分母；較早的統計表沒有缺席欄（下方標示），缺席的比例只以有缺席欄的統計表的會議次數為分母。統計表上標記與合計數不一致的欄位，本站不收錄。';

// 本人欄位被整欄不收的會期：中性說明，不推測原因
export function attendanceExcludedNote(f) {
  const d = f.data || {};
  const why = d.reason === 'mismatch' ? '本人欄位的逐次標記與合計不一致' : '本人欄位無法可靠讀取';
  return `${String(d.session || '').replace(/^第4屆/, '')}的官方統計表，${why}，本站未收錄該會期。`;
}

export function khhAttendanceBlock(list, excluded = []) {
  const a = attendanceTotals(list);
  const row = (label, n, r, d) => `<li><span>${label}</span>${bar(r)}<span><span class="num">${pct(r)}</span>（<span class="num">${n}</span>／<span class="num">${d}</span>）</span></li>`;
  const types = (label, t) => (t.length ? `<p class="muted small">${label}：${t.map(([k, n]) => `${k} <span class="num">${n}</span> 次`).join('、')}。</p>` : '');
  const tables = [...list].reverse().map((f) => {
    const d = f.data || {};
    const u = safeUrl(f.source_url);
    const absent = d.absent == null ? '表上無缺席欄' : `缺席 <span class="num">${Number(d.absent)}</span>`;
    return `<li>${u ? ext(u, esc(d.session || '')) : esc(d.session || '')}：會議 <span class="num">${Number(d.meetings)}</span> 次，出席 <span class="num">${Number(d.present)}</span>、請假 <span class="num">${Number(d.leave)}</span>、公差／公假 <span class="num">${Number(d.duty)}</span>、${absent}</li>`;
  }).join('');
  return `<h3>出缺勤</h3>
      ${list.length ? `<ul class="bars rates">${row('出席', a.present, a.presentRate, a.total)}${row('請假', a.leave, a.leaveRate, a.total)}${row('公差／公假', a.duty, a.dutyRate, a.total)}${row('缺席', a.absent, a.absentRate, a.absentTotal)}</ul>
      <p class="muted small">出席、請假、公差／公假的分母是 <span class="num">${a.total}</span> 次會議（${list.length} 份統計表）；缺席的分母是有缺席欄的 <span class="num">${a.absentTotal}</span> 次會議。</p>
      ${types('請假依假別', a.leaveTypes)}${types('公差／公假依類別', a.dutyTypes)}` : ''}
      ${excluded.map((f) => `<p class="status" role="note">${esc(attendanceExcludedNote(f))}</p>`).join('')}
      <p class="muted small">${KHH_ATTENDANCE_NOTE}</p>
      ${list.length ? `<details class="sess"><summary>各會期統計表（<span class="num">${list.length}</span> 份，連結至公報原檔）</summary><ul class="plain small">${tables}</ul></details>` : ''}`;
}

// 新北：每筆是一個會期的摘要紀錄合計（meetings 次會議；present、leave、duty 是列在出席、請假、請假註記公假的次數）。
// 兩份名單都沒有的次數原因不明，不另列（使用者 2026-10-04 決定）；公假和高雄一樣與請假分開列
export const NWT_ATTENDANCE_NOTE = '依新北市議會議事錄每次會議「摘要紀錄」的出席與請假名單計算；請假名單上註記公假的，列為公差／公假，和請假分開。兩份名單都沒有列出的情形無法判斷原因，本站因此不區分缺席，也不另列次數。比例的分母是本站收錄、摘要紀錄列有出席名單的會議次數（定期會與臨時會，任職以後）；出席欄只寫「詳如簽到簿」的會議（多為審查委員會業務質詢與市政總質詢會議）不列入。';

export function nwtAttendanceBlock(list) {
  const sum = (k) => list.reduce((s, f) => s + (Number(f.data?.[k]) || 0), 0);
  const total = sum('meetings');
  const rate = (n) => (total ? n / total : 0);
  const row = (label, n) => `<li><span>${label}</span>${bar(rate(n))}<span><span class="num">${pct(rate(n))}</span>（<span class="num">${n}</span>／<span class="num">${total}</span>）</span></li>`;
  const sessions = list.map((f) => {  // export 已依日期由新到舊
    const d = f.data || {};
    const u = safeUrl(f.source_url);
    return `<li>${u ? ext(u, esc(d.session || '')) : esc(d.session || '')}：會議 <span class="num">${Number(d.meetings)}</span> 次，出席 <span class="num">${Number(d.present)}</span>、請假 <span class="num">${Number(d.leave) || 0}</span>、公差／公假 <span class="num">${Number(d.duty) || 0}</span></li>`;
  }).join('');
  return `<h3>出缺勤</h3>
      <ul class="bars rates">${row('出席', sum('present'))}${row('請假', sum('leave'))}${row('公差／公假', sum('duty'))}</ul>
      <p class="muted small">出席 <span class="num">${sum('present')}</span>／<span class="num">${total}</span> 次、請假 <span class="num">${sum('leave')}</span> 次、公差／公假 <span class="num">${sum('duty')}</span> 次（分母是 <span class="num">${total}</span> 次會議）。</p>
      <p class="muted small">${NWT_ATTENDANCE_NOTE}</p>
      <details class="sess"><summary>各會期（<span class="num">${list.length}</span> 個，連結至議事錄原檔）</summary><ul class="plain small">${sessions}</ul></details>`;
}

// 第1選舉區 2022 公報含重疊的隱藏文字，本站刻意不擷取：現任該區議員且沒有 profile 時要註明
export const DISTRICT01_BULLETIN = encodeURI('https://bulletin.cec.gov.tw/01選舉公報/05直轄市議員/111年/01臺北市/臺北市第01選舉區.pdf');
export function needsDistrict01Note(facts) {
  return (facts.office || []).some((f) => f.data?.district_id === 'tpe-council-01') && !(facts.profile || []).length;
}

// 臺北以外：對到公報檔的人都有 bulletin fact（原檔網址＋頁碼），沒收到文字欄位時連到這裡；臺北沒有，回 null
export function bulletinLink(facts) {
  const b = facts.bulletin?.[0];
  const u = safeUrl(b?.source_url);
  if (!u) return null;
  return b.data?.page ? `${u}#page=${Number(b.data.page)}` : u;
}

// 公報只擷取到學經歷或政見其中一項時，缺的那項改連公報原檔（有 bulletin fact 就用它，否則連另一項的公報原文）；值為 null 表示不缺
export function bulletinGaps(facts) {
  const profile = facts.profile?.[0];
  const platform = facts.platform?.[0];
  const link = bulletinLink(facts);
  return {
    profile: !profile && platform ? link ?? (platform.source_url || '') : null,
    platform: profile && !platform ? link ?? (profile.source_url || '') : null,
  };
}

// 臺北以外沒收到的欄位：不區分圖片或無文字層，中性寫「本站未收錄」並連原檔
export const BULLETIN_MISSING = (what) => `本站未收錄文字${what}，請見`;
const pageNote = (facts) => (facts.bulletin?.[0]?.data?.page ? `（第 ${Number(facts.bulletin[0].data.page)} 頁）` : '');

// 出處標籤依職位決定：議員來自議會名冊；首長來自中選會選舉結果
const isHead = (office) => String(office || '').endsWith('_mayor');
export const officeSourceLabel = (office) => (office === 'legislator' ? '立法院委員資料' : isHead(office) ? '選舉結果' : '議員名冊');

// ---------- 縣市長任職異動（V14 §3） ----------

// 全站統一的名詞說明：同一段文字、不針對個人，只在頁面出現停止職務時顯示
export const SUSPENSION_NOTE = '地方行政首長依地方制度法由上級機關停止職務。停職期間仍保有職位，由副首長代理；停職不代表判決確定。';
const suspensionNote = () => `<p class="small muted"><strong>停止職務</strong>：${SUSPENSION_NOTE}</p>`;

// 最後一筆異動是停止職務 → 停職中，回傳那筆異動；否則 null
export function suspensionOf(data) {
  const last = (data?.status_events || []).at(-1);
  return last?.event === 'suspended' ? last : null;
}
// 候選人標籤：本人在同一選區現任 →「現任」；別的選區或職位 →「現任新北市議員」；停職中不寫「現任」（V14 §3.3）
export function candidateTag(incumbent, districtId, counties) {
  const list = incumbent || [];
  const o = list.find((x) => x.district_id === districtId) || list[0];
  if (!o) return '';
  if (o.district_id === districtId) return o.suspended ? '停職中' : '現任';
  const label = officeLabel(o.office, counties.get(isoOf(o.district_id)));
  return o.suspended ? `${label}（停職中）` : `現任${label}`;
}
// 任職的選區：2022 劃分與 2026 不同（新竹縣）時只寫 2022 選區名稱，不連到 2026 選區頁
export const officeDistrict = (data, link) => (data.district_name ? esc(data.district_name) : link(data.district_id));
export const hasSuspension = (offices) => offices.some((f) => (f.data?.status_events || []).some((e) => e.event === 'suspended'));

function eventLine(e, ongoing) {
  const d = `<span class="num">${esc(e.date)}</span>`;
  if (e.event === 'suspended') return `${d} ${ongoing ? '起' : ''}停止職務，由${esc(e.acting_position)}${esc(e.acting_name)}${esc(e.acting_title)}`;
  if (e.event === 'reinstated') return `${d} 內政部同意復職`;
  return '';
}

// 人物頁「任職」的縣市長一列：當選、就職、異動各一行，出處與資料截至日期（取 fact 與異動擷取日的最新者）
export function headOfficeItem(f, districtHtml = '') {
  const d = f.data || {};
  const events = d.status_events || [];
  const suspended = suspensionOf(d);
  const links = [[f.source_url, d.source_label], [d.inauguration_source_url, d.inauguration_source_label],
    ...events.flatMap((e) => [[e.source_url, e.source_label], [e.acting_source_url, e.acting_source_label]])]
    .filter(([u, label]) => safeUrl(u) && label).map(([u, label]) => ext(safeUrl(u), esc(label)));
  const asOf = [f.fetched_at, ...events.map((e) => e.fetched_at)].map(fmtDate).sort().at(-1);
  return `<li><span><span class="name">${esc(d.title)}</span>${suspended ? '（停職中）' : ''}</span>
      <span>${districtHtml}</span>
      <div class="lines">
        <p><span class="num">${esc(d.elected_on)}</span> 當選${d.election_note ? `（${esc(d.election_note)}）` : ''}　<span class="num">${esc(f.date)}</span> 就職</p>
        ${events.map((e, i) => `<p>${eventLine(e, i === events.length - 1)}</p>`).join('')}
        <p class="src">出處：${links.join('；')}｜資料截至 <time datetime="${esc(asOf)}">${esc(asOf)}</time></p>
      </div></li>`;
}

// 更正表單：匿名 Google 表單（不需登入、不收集 Email）；清成空字串時頁面會顯示「更正表單準備中」
export const CORRECTION_FORM_URL = 'https://docs.google.com/forms/d/e/1FAIpQLSdoxikbfSY2jzSlQ70YUTU9AYWbg_CjDhYaIvSe8cWubhgXyQ/viewform';

const taipeiDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' });
export const fmtDate = (iso) => (iso ? taipeiDate.format(new Date(iso)) : '');

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const safeUrl = (u) => (/^https?:\/\//.test(u || '') ? u : '');
const ext = (u, text) => `<a href="${esc(u)}" target="_blank" rel="noopener">${text}</a>`;

// 發布機關：資料本身有標示就用它（例：臺北市選委會的登記冊放在中選會的共用平台上），沒有才依網域推論
export function publisherOf(url, publisher) {
  if (publisher) return publisher;
  const host = new URL(url).hostname;
  return PUBLISHERS.find(([h]) => host === h || host.endsWith(`.${h}`))?.[1] || host;
}

// 腳註：同一出處（網址＋擷取日）共用一個編號，依首次出現順序編號
function footnotes() {
  const list = [];
  return {
    ref(url, fetchedAt, label, publisher) {
      const u = safeUrl(url);
      if (!u) return '';
      const key = `${u}|${fmtDate(fetchedAt)}`;
      let i = list.findIndex((n) => n.key === key);
      if (i < 0) i = list.push({ key, url: u, fetchedAt, label, publisher }) - 1;
      return `<sup class="fn">[${i + 1}]</sup>`;
    },
    render(extra = '') {
      if (!list.length && !extra) return '';
      return `<section class="notes" aria-labelledby="notes-h"><h2 id="notes-h">資料來源</h2>
        <ul>${list.map((n, i) => `<li><span class="fn-n">[${i + 1}]</span><span>${ext(n.url, esc(n.label))}，${esc(publisherOf(n.url, n.publisher))}，擷取 <time datetime="${esc(n.fetchedAt)}">${fmtDate(n.fetchedAt)}</time></span></li>`).join('')}</ul>
        ${extra}</section>`;
    },
  };
}

// ---------- 資料載入 ----------

class NotFound extends Error {}
const cache = new Map();
let maxFetched = '';

function track(...isoTimes) {
  for (const t of isoTimes) if (t && t > maxFetched) maxFetched = t;
  const el = document.getElementById('updated');
  if (el && maxFetched) el.textContent = fmtDate(maxFetched);
}

function load(path) {
  if (!cache.has(path)) {
    const p = fetch(path).then((r) => {
      if (r.status === 404) throw new NotFound(path);
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    });
    p.catch(() => cache.delete(path));
    cache.set(path, p);
  }
  return cache.get(path);
}

// 黨徽索引由另一流程產生；不存在或壞掉時一律當作沒有黨徽
async function loadParties() {
  try {
    const idx = await load('parties/index.json');
    const src = safeUrl(idx?.source?.url);
    const el = document.getElementById('emblem-src');
    if (el && src) {
      el.innerHTML = `黨徽來源：${ext(src, esc(idx.source.name || new URL(src).hostname))}`;
      el.hidden = false;
    }
    return idx?.parties || {};
  } catch {
    return {};
  }
}

const idOk = (id) => /^[\w-]+$/.test(id);

async function boot() {
  const [data, parties] = await Promise.all([load('data/counties.json'), loadParties()]);
  track(...data.counties.map((c) => c.fetched_at));
  return { counties: new Map(data.counties.map((c) => [c.iso, c])), parties };
}

async function loadVillages(iso) {
  const v = await load(`data/villages/${iso}.json`);
  track(...v.sources.map((s) => s.fetched_at));
  return v.villages;
}

// 選區名稱與名額一律從 counties.json 取；只開放議員與縣市長選區（立委有人物資料後再開）
function districtMeta(ctx, id) {
  const county = ctx.counties.get(isoOf(id));
  const d = county?.districts.find((x) => x.district_id === id);
  return d && /_(councilor|mayor)$/.test(d.office) ? { d, county } : null;
}

// ---------- 共用片段 ----------

function crumbs(...items) {
  const li = items.map(([href, text], i) => (i === items.length - 1
    ? `<li aria-current="page">${esc(text)}</li>` : `<li><a href="${esc(href)}">${esc(text)}</a></li>`)).join('');
  return `<nav class="crumbs" aria-label="頁面位置"><ol>${li}</ol></nav>`;
}

function party(name, parties) {
  const src = emblemFor(name, parties);
  const img = src ? `<img src="${esc(src)}" alt="" width="20" height="20" decoding="async">` : '';
  // ponytail: 沒有黨徽時保留同寬空位，讓政黨文字對齊；不放替代圖樣
  return `<span class="party"><span class="emblem${src ? '' : ' blank'}">${img}</span><span>${esc(name)}</span></span>`;
}

const stat = (label, n, unit) => `<div><dt>${label}</dt><dd><span class="num">${esc(n)}</span>${unit}</dd></div>`;

// ---------- 頁面 ----------

function resultRow(d, county, villages) {
  return `<li><a href="#/d/${esc(d.district_id)}">
    <span class="result-title">${esc(districtTitle(d, county))}</span>
    <span class="result-sub">${esc(districtSub(d, villages, county))}</span>
    <span class="result-seats"><span class="num">${esc(d.seats)}</span> 席</span></a></li>`;
}

// 首頁：台灣地圖（滑鼠用，對輔助科技隱藏）＋縣市文字清單（主要導覽）
async function renderHome(main, ctx) {
  const counties = countyOrder([...ctx.counties.values()]);
  main.innerHTML = `
    <h1 tabindex="-1">查詢你的選區</h1>
    <p class="lede">選擇戶籍所在的縣市，查看 2026 年縣市長與縣市議員的候選人。</p>
    <div class="home">
      <div class="map" aria-hidden="true"></div>
      <nav aria-labelledby="county-h">
        <h2 id="county-h">縣市</h2>
        <ul class="counties">${counties.map((c) => `<li><a href="#/c/${esc(c.iso)}" data-iso="${esc(c.iso)}">${esc(c.name)}</a>${countyTag(c) ? `<span class="tag">${esc(countyTag(c))}</span>` : ''}</li>`).join('')}</ul>
        <p class="small muted">${esc(homeNote(counties))}</p>
      </nav>
    </div>`;

  let svg;
  try {
    svg = await (await fetch('assets/taiwan-counties.svg')).text();
  } catch {
    return; // 地圖只是輔助，載不到就只留清單
  }
  const map = main.querySelector('.map');
  if (!map) return; // 已換頁
  map.innerHTML = svg.replace(/^<\?xml[^>]*>\s*/, '');
  for (const iso of DEEP_COUNTIES) map.querySelector(`#county-${iso}`)?.classList.add('deep');
  for (const c of counties) if (countyTag(c) === BULLETIN_TAG) map.querySelector(`#county-${c.iso}`)?.classList.add('part');
  map.addEventListener('click', (e) => {
    const iso = e.target.closest('path[id^="county-"]')?.id.slice(7);
    if (iso && ctx.counties.has(iso)) location.hash = `#/c/${iso}`;
  });
  // 清單的 hover／focus 同步在地圖上加深
  const mark = (e, on) => map.querySelector(`#county-${e.target.dataset?.iso}`)?.classList.toggle('on', on);
  const list = main.querySelector('.counties');
  for (const [type, on] of [['mouseover', true], ['mouseout', false], ['focusin', true], ['focusout', false]]) {
    list.addEventListener(type, (e) => mark(e, on));
  }
}

// 縣市頁：鄉鎮市區 →（跨選區時）村里 → 原住民身分 → 議員選區與縣市長
async function renderCounty(main, ctx, iso) {
  const county = ctx.counties.get(iso);
  if (!county) return renderNotFound(main, '縣市');
  const villages = await loadVillages(iso);
  const word = townWord(county);
  const site = DEEP_COUNTIES.has(iso) ? '' : COUNCIL_SITES[iso];
  main.innerHTML = `
    ${crumbs(['#/', '全國'], ['', county.name])}
    <h1 tabindex="-1">${esc(county.name)}</h1>
    <p class="lede">選擇戶籍所在的${word}，查看 2026 年${esc(officeLabel(`${iso}_councilor`, county))}與${esc(officeLabel(`${iso}_mayor`, county))}的候選人。</p>
    ${DEEP_COUNTIES.has(iso) ? '' : `<p class="status" role="note">${esc(countyNote(county))}${site ? `議會資訊可先查閱${ext(site, `${esc(county.name)}議會官網`)}。` : ''}</p>`}
    <form class="lookup" onsubmit="return false">
      <div class="field">
        <label for="town">${word}</label>
        <select id="town"><option value="">請選擇</option>${townsOf(villages).map((t) => `<option>${esc(t)}</option>`).join('')}</select>
      </div>
      <div class="field" id="vill-field" hidden>
        <label for="vill">村里</label>
        <select id="vill"></select>
        <p class="small muted">這個${word}分屬不同議員選區，請選擇村里。</p>
      </div>
      <fieldset class="field">
        <legend>是否具原住民身分</legend>
        <label class="radio"><input type="radio" name="ind" value="none" checked> 無</label>
        <label class="radio"><input type="radio" name="ind" value="plains"> 平地原住民</label>
        <label class="radio"><input type="radio" name="ind" value="mountain"> 山地原住民</label>
      </fieldset>
    </form>
    <p class="hint">投票以戶籍地為準。</p>
    <section aria-labelledby="result-h" id="result" aria-live="polite"></section>`;

  const form = main.querySelector('form');
  const villField = main.querySelector('#vill-field');
  const meta = (id) => county.districts.find((d) => d.district_id === id);
  const update = (e) => {
    const town = form.town.value;
    if (e?.target === form.town) {
      const need = town && needsVillage(villages, iso, town);
      villField.hidden = !need;
      form.vill.innerHTML = need ? `<option value="">請選擇</option>${villages.filter((v) => v.town === town)
        .map((v) => `<option value="${esc(v.villcode)}">${esc(v.village)}</option>`).join('')}` : '';
    }
    const ind = form.ind.value;
    const out = main.querySelector('#result');
    const villcode = villField.hidden ? '' : form.vill.value;
    const hit = !villField.hidden && !villcode && ind === 'none' ? null : councilDistrictFor(villages, iso, { town, villcode, indigenous: ind });
    if (!hit) { out.innerHTML = ''; return; }
    const vill = villcode ? villages.find((v) => v.villcode === villcode)?.village || '' : '';
    const where = ind === 'none' || hit.fallback ? esc(town + vill) : `${esc(town)}${KIND_LABEL[ind]}選民`;
    const note = hit.fallback
      ? `本縣市未設${KIND_LABEL[ind]}選舉區，依戶籍所在選區投票。`
      : ind !== 'none' ? `具原住民身分的選民，議員投原住民選舉區，不投所在${word}的區域選舉區。` : '';
    out.innerHTML = `<h2 id="result-h">${where}的選區</h2>
      <ul class="results">${resultRow(meta(hit.id), county, villages)}${resultRow(meta(`${iso}-mayor`), county, villages)}</ul>
      ${note ? `<p class="small muted">${note}</p>` : ''}`;
  };
  form.addEventListener('change', update);
  update();
}

// 政黨取自 2022 開票（推薦政黨）時加註年份：之後換黨的人不會被顯示成目前政黨
export function partyOf(data, parties) {
  return `${party(data.party, parties)}${data.party_year ? `<span class="muted small">${esc(data.party_year)} 推薦</span>` : ''}`;
}

// 議員任職：2022 推薦政黨與任職起日各自的出處（臺北議員沒有這些欄位，不多註腳）
export function officeExtraRefs(f, notes) {
  const d = f.data || {};
  return [[d.party_source_url, d.party_source_label], [d.inauguration_source_url, d.inauguration_source_label]]
    .filter(([u, label]) => u && label).map(([u, label]) => notes.ref(u, f.fetched_at, label)).join('');
}

function rosterRow(p, fn, parties, tag) {
  return `<li><a class="name" href="#/p/${esc(p.person_id)}">${esc(p.name)}</a>
    ${partyOf(p.data, parties)}
    <span class="meta">${tag ? `<span class="tag">${esc(tag)}</span>` : ''}${fn}</span></li>`;
}

async function renderDistrict(main, ctx, id) {
  const m = districtMeta(ctx, id);
  if (!m) return renderNotFound(main, '選區');
  const { county } = m;
  let d, villages;
  try {
    [d, villages] = await Promise.all([load(`data/districts/${id}.json`), loadVillages(county.iso)]);
  } catch (e) {
    if (e instanceof NotFound) return renderNotFound(main, '選區');
    throw e;
  }
  track(d.fetched_at, ...d.people.map((p) => p.fetched_at));
  const notes = footnotes();
  const cands = candidateOrder(d.people.filter((p) => p.kind === 'candidacy'));
  const registered = cands.some((p) => p.data.status === 'registered');
  const seatsFn = notes.ref(d.source_url, d.fetched_at, '應選名額公告');
  const candRows = cands.map((p) => rosterRow(p, notes.ref(p.source_url, p.fetched_at, '候選人登記名冊', p.data.publisher), ctx.parties, candidateTag(p.incumbent, id, ctx.counties))).join('');
  const title = districtTitle(d, county);

  main.innerHTML = `
    ${crumbs(['#/', '全國'], [`#/c/${county.iso}`, county.name], ['', title])}
    <h1 tabindex="-1">${esc(title)}</h1>
    <p class="lede">${esc(districtSub(d, villages, county))}</p>
    <dl class="stats">
      ${stat('應選', d.seats, ` 席${seatsFn}`)}
      ${stat('候選人', cands.length, ' 人')}
    </dl>
    <section aria-labelledby="cand-h">
      <h2 id="cand-h">2026 候選人</h2>
      ${registered ? `<p class="status" role="note">${REGISTERED_NOTE}</p>` : ''}
      ${cands.length ? `<ol class="roster">${candRows}</ol><p class="small muted">依官方登記名冊順序排列，非選票號次。</p>` : '<p class="muted">尚無候選人資料。</p>'}
    </section>
    ${notes.render()}`;
}

export const REGISTERED_NOTE = '名單依選舉委員會公告的候選人登記冊，尚未經審定；號次將於官方名單公告（縣市長 11/12、議員 11/17）後補上。';

// 影片區塊說明：議會名稱依影片網址的網域（臺北 tccvideo、高雄 ivod.kcc）
export function videoBlurb(videos) {
  const u = safeUrl(videos[0]?.source_url);
  const council = u ? publisherOf(u) : '臺北市議會';
  return `連結至${council}議事影音系統，影片來源：${council}。`;
}

function videoRows(list) {
  return list.map((f) => {
    const u = safeUrl(f.source_url);
    return `<li><time class="date" datetime="${esc(f.date || '')}">${esc(f.date || '')}</time>
      <span class="dept">${esc(f.data?.dept || '')}</span>
      <span class="title">${esc(f.data?.title || '')}
        <span class="video">${u ? ext(u, '觀看影片') : ''}<span class="muted">${esc(videoNote(f.data))}</span></span></span></li>`;
  }).join('');
}

// 質詢子段：最新 20 筆＋「顯示全部」，按鈕行為在 renderPerson 綁定
function interSection(key, heading, { list, rows, blurb }) {
  if (!list.length) return '';
  const { shown, hidden } = splitLatest(list);
  return `<section class="inter" data-key="${key}" aria-labelledby="k-${key}"><h3 id="k-${key}">${heading}</h3>
    <p class="count">共 <span class="num">${list.length}</span> 筆${hidden.length ? `，以下為最新 <span class="num">${shown.length}</span> 筆` : ''}。${blurb}</p>
    <ol class="inters">${rows(shown)}</ol>
    ${hidden.length ? `<button type="button" class="more">顯示全部 ${list.length} 筆</button>` : ''}</section>`;
}

function interpellationRows(list) {
  return list.map((f) => {
    const u = safeUrl(f.source_url);
    const title = esc(f.data?.title || f.data?.doc_no || '');
    return `<li><time class="date" datetime="${esc(f.date || '')}">${esc(f.date || '')}</time>
      <span class="dept">${esc(f.data?.dept || '')}</span>
      <span class="title">${u ? ext(u, title) : title}${moreFiles(f.data?.files)}</span></li>`;
  }).join('');
}

// 新北書面質詢：同會期有多份 PDF 時，第 2 份起另列連結
const moreFiles = (files) => (files || []).slice(1).map((x, i) => (safeUrl(x.url) ? `；${ext(x.url, `第 ${i + 2} 份`)}` : '')).join('');

// ---------- 質詢摘要（NotebookLM，依公報速記錄） ----------

// 文字經使用者確認，照抄；每個會期區塊與頁尾各顯示一次
export const SUMMARY_DISCLAIMER = '質詢摘要為AI產出，僅供參考用途，詳細事實以原質詢速記錄與影片為準';
// 不能寫「缺席」或「沒有質詢」：可能是請假或改書面質詢
export const NO_SPEECH = '本會期公報速記錄中未見其口頭質詢發言';

// 只顯示至少有一條可連結引文的議題（批次已過濾，這裡再擋一次）
const issuesOf = (d) => (d?.issues || []).filter((i) => i?.topic && (i.citations || []).some((c) => safeUrl(c.source_url)));

function citeLinks(citations) {
  const seen = new Set();
  return citations.filter((c) => safeUrl(c.source_url) && !seen.has(c.source_url) && seen.add(c.source_url))
    .map((c) => ext(safeUrl(c.source_url), c.page ? `速記錄第 <span class="num">${esc(c.page)}</span> 頁` : '速記錄')).join('、');
}

function issueItem(i) {
  return `<li><h3>${esc(i.topic)}</h3>
    <dl class="issue">
      <dt>議員</dt><dd>${(i.councilor_points || []).map((p) => `<p>${esc(p)}</p>`).join('')}</dd>
      ${i.response_removed ? '' : `<dt>市府回應</dt><dd><p>${i.response ? esc(i.response) : '<span class="muted">速記錄節錄中未見市府回應</span>'}</p></dd>`}
      <dt>引文</dt><dd>${citeLinks(i.citations)}</dd>
    </dl></li>`;
}

// 影片：同日期、同組別（含質詢類別與部門）的口頭質詢影片 fact
function videoFor(v, src, videos) {
  return videos.find((f) => f.date === v.date && f.data?.group === v.group
    && f.data?.doc_type === src.doc_type && (f.data?.dept || null) === (src.dept || null));
}

function sourceItem(src, videos) {
  const pages = src.transcript_pages || [];
  const where = pages.length ? `速記錄 公報第 <span class="num">${esc(pages[0])}</span>${pages.length > 1 ? `–<span class="num">${esc(pages.at(-1))}</span>` : ''} 頁` : '速記錄';
  const tu = safeUrl(src.transcript_page_url) || safeUrl(src.transcript_url);
  const vids = (src.videos || []).map((v) => videoFor(v, src, videos)).filter((f) => f && safeUrl(f.source_url))
    .map((f) => ext(safeUrl(f.source_url), `影片（${esc(f.date)}）`));
  return `<li>${esc(src.heading)}（${(src.dates || []).map(esc).join('、')}）：${[tu ? ext(tu, where) : where, ...vids].join('、')}</li>`;
}

function sessionBlock(f, videos) {
  const d = f.data || {};
  const noSpeech = d.status === 'no_speech';
  const issues = issuesOf(d);
  if (!noSpeech && !issues.length) return '';
  const body = noSpeech ? `<p class="status" role="note">${NO_SPEECH}</p>` : `<ol class="issues">${issues.map(issueItem).join('')}</ol>`;
  return `<details class="sess"><summary><span class="sess-title">${esc(d.session || '')}${noSpeech ? '' : `<span class="muted">，<span class="num">${issues.length}</span> 個議題</span>`}</span>
      <span class="disclaimer">${SUMMARY_DISCLAIMER}</span></summary>
    ${body}
    <h3>原質詢出處</h3>
    <ul class="plain srcs">${(d.sources || []).map((s) => sourceItem(s, videos)).join('')}</ul></details>`;
}

// 人物頁「質詢摘要」：依會期由新到舊，每個會期一個原生 <details>
export function summarySection(summaries, videos = []) {
  const sorted = [...summaries].sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')));
  const blocks = sorted.map((f) => sessionBlock(f, videos)).filter(Boolean);
  if (!blocks.length) return '';
  return `<section aria-labelledby="k-summary"><h2 id="k-summary">質詢摘要</h2>
    <p class="count">依會期由新到舊。由 NotebookLM 根據臺北市議會公報速記錄整理，引文連結至速記錄原文頁面。</p>
    ${blocks.join('')}</section>`;
}

const pct = (r) => `${(r * 100).toFixed(1)}%`;
const bar = (ratio) => `<span class="bar" aria-hidden="true"><span style="width:${(ratio * 100).toFixed(1)}%"></span></span>`;
// 公報學經歷每項前有「•」，改用清單呈現時拿掉，其餘文字不動
const listItems = (items) => items.map((s) => `<li>${esc(String(s).replace(/^[•・\s]+/, ''))}</li>`).join('');

function srcLine(f, label, notes) {
  const u = safeUrl(f.source_url);
  if (!u) return '';
  return `<p class="src">出處：${ext(u, esc(label))}，${esc(publisherOf(u))}，擷取 <time datetime="${esc(f.fetched_at)}">${fmtDate(f.fetched_at)}</time>${notes.ref(u, f.fetched_at, label)}</p>`;
}

// 2022 開票紀錄未當選（之後遞補或補選就任）：公報不是當選時的政見，中性加註。只看 bulletin fact 的 elected，不從任職起日推斷
export const NOT_ELECTED_2022 = '本人於 2022 年選舉未當選，以下為當時的選舉公報內容。';

// 2022 選舉公報：學歷、經歷、政見；政見原文保留換行，不截斷
export function bulletinSection(facts, notes) {
  const profile = (facts.profile || [])[0];
  const platform = (facts.platform || [])[0];
  const link = bulletinLink(facts);
  let body;
  if (profile || platform) {
    const pd = profile?.data || {};
    const gap = bulletinGaps(facts);
    const gapNote = (what, url) => (link
      ? `<p class="status" role="note">${BULLETIN_MISSING(what)}${ext(link, '公報原檔')}${pageNote(facts)}。</p>`
      : `<p class="status" role="note">2022 公報${what}未能以文字擷取，請見${safeUrl(url) ? ext(safeUrl(url), '公報原文') : '公報原文'}。</p>`);
    body = `${pd.education?.length ? `<h3>學歷</h3><ul class="plain">${listItems(pd.education)}</ul>` : ''}
      ${pd.experience?.length ? `<h3>經歷</h3><ul class="plain">${listItems(pd.experience)}</ul>` : ''}
      ${profile ? srcLine(profile, '2022 選舉公報學經歷', notes) : ''}
      ${gap.profile !== null ? `<h3>學經歷</h3>${gapNote('學經歷', gap.profile)}` : ''}
      <h3 id="k-platform" tabindex="-1">政見</h3>
      ${platform ? `<div class="platform">${esc(platform.data?.text || '')}</div>${srcLine(platform, '2022 選舉公報政見', notes)}` : gapNote('政見', gap.platform)}`;
  } else if (link) {
    body = `<p class="status" role="note">${BULLETIN_MISSING('政見與學經歷')}${ext(link, '公報原檔')}${pageNote(facts)}。</p>`;
  } else if (needsDistrict01Note(facts)) {
    body = `<p class="status" role="note">第1選舉區 2022 公報因版面內含重疊文字，本站無法可靠擷取，請見${ext(DISTRICT01_BULLETIN, '公報原文')}。</p>`;
  } else return '';
  const lost = facts.bulletin?.[0]?.data?.elected === false ? `<p class="status" role="note">${NOT_ELECTED_2022}</p>` : '';
  return `<section aria-labelledby="k-bulletin"><h2 id="k-bulletin" tabindex="-1">2022 選舉公報</h2>${lost}${body}</section>`;
}

// 確定有罪判決：只要有 2026 參選資料就顯示（用詞依刑法第 76 條，不稱「前科」）。只列 final === true 的確定判決，照原文呈現不加評語；
// 沒有資料時只說「尚未收錄」，任何情況都不寫成沒有前科（見 docs/PLAN.md §6 G5）
export const JUDICIAL_SEARCH = 'https://judgment.judicial.gov.tw/FJUD/default.aspx';
export const TAIWANGOGO = 'https://council2026.taiwangogo.tw/';
export const TAIWANGOGO_NOTE = '該網站由台灣前進經營，時代力量代管，並與時代力量、台灣基進、台灣綠黨、小民參政歐巴桑聯盟合作。收錄範圍包含起訴、行政罰、民事判決與新聞報導。起訴不等於有罪，行政罰與民事判決也不是刑事前科。本站未查證其內容，提供連結不代表本站認同或背書；使用其內容前，請對照原始來源查證。';

export function criminalRecordSection(facts) {
  if (!(facts.candidacy || []).length) return '';
  const list = (facts.conviction || []).filter((f) => f.data?.final === true)
    .sort((a, b) => String(b.data.judgment_date || '').localeCompare(String(a.data.judgment_date || '')));
  const rows = list.map((f) => {
    const d = f.data;
    const u = safeUrl(f.source_url);
    return `<li><dl class="facts">
      <dt>法院</dt><dd>${esc(d.court)}</dd>
      <dt>判決字號</dt><dd>${u ? ext(u, esc(d.case_no)) : esc(d.case_no)}</dd>
      <dt>判決日期</dt><dd><time datetime="${esc(d.judgment_date)}">${esc(d.judgment_date)}</time></dd>
      <dt>罪名</dt><dd>${esc(d.offense)}</dd>
      <dt>判決結果</dt><dd>${esc(d.result)}</dd>
    </dl></li>`;
  }).join('');
  const status = list.length
    ? `<p class="count">本站收錄 <span class="num">${list.length}</span> 筆經查證的確定有罪判決。</p><ol class="convictions">${rows}</ol>`
    : '<p class="count">本站尚未收錄經查證的確定有罪判決。</p>';
  return `<section aria-labelledby="k-crime"><h2 id="k-crime">確定有罪判決查詢</h2>
    ${status}
    <p class="small muted">本站只收錄司法院公開、已確定且可佐證身分的有罪判決，並附判決字號與原文連結；無法確認已確定或無法佐證身分的判決不收錄。本站的查證以第三方資料庫列出的線索為起點，沒有涵蓋所有候選人，「尚未收錄」不代表查無判決。選舉公報依法不刊登前科（公職人員選舉罷免法第47條）。</p>
    <h3>查詢入口</h3>
    <ul class="portals">
      <li>${ext(JUDICIAL_SEARCH, '司法院裁判書查詢系統')}<span class="muted small">（官方）</span></li>
      <li><a href="${TAIWANGOGO}" target="_blank" rel="noopener noreferrer nofollow">council2026.taiwangogo.tw</a>
        <p class="small muted">${TAIWANGOGO_NOTE}</p></li>
    </ul></section>`;
}

// ---------- 立法院問政紀錄（ly_records：書面質詢、IVOD 發言片段、列名提案的議案） ----------

export const LY_NOTE = '第 11 屆立法委員任內紀錄，資料取自 OpenFun 立法院 API（CC BY 4.0），原始資料為立法院公報、議事轉播與議案系統。書面質詢的涵蓋範圍是立法院 API 收錄的第 11 屆第 1–3 會期書面質詢（第 4 會期起尚未收錄），筆數不代表任期內全部質詢；口頭質詢請見發言影片（IVOD）。出席與表決紀錄尚未收錄。';
export const LY_KINDS = {
  ly_interpellation: { heading: '書面質詢', unit: '筆', blurb: '依立法院公報「質詢事項」，限立法院 API 收錄的第 11 屆第 1–3 會期；口頭質詢見發言影片（IVOD）。標題連結至該筆資料。' },
  ly_video: { heading: '發言影片（IVOD）', unit: '段', blurb: '連結至立法院議事轉播系統的委員發言片段。' },
  ly_bill: { heading: '列名提案人的議案', unit: '件', blurb: '不含只列名連署的議案；標題連結至該筆資料。' },
};

// 摘要卡用的計數：只列有資料的種類，依 LY_KINDS 固定順序
export function lyCounts(facts) {
  return Object.entries(LY_KINDS).map(([k, m]) => [m.heading, (facts[k] || []).length, m.unit]).filter(([, n]) => n);
}

function lyRows(list) {
  return list.map((f) => {
    const u = safeUrl(f.source_url);
    const title = esc(f.data?.title || f.data?.bill_no || f.data?.no || '');
    const side = f.data?.status || (f.data?.committees || []).join('、');
    return `<li><time class="date" datetime="${esc(f.date || '')}">${esc(f.date || '')}</time>
      <span class="dept">${esc(side || '')}</span>
      <span class="title">${u ? ext(u, title) : title}</span></li>`;
  }).join('');
}

// 摘要卡「說過什麼｜做了什麼」：只是事實計數，不排序、不比較、不評語
export function summaryCard(facts, { offices, inters, written, videos, jump, rec = RECORDS.tpe, pending = [] }) {
  const ly = lyCounts(facts);
  const said = `<div class="said"><h2>說過什麼</h2>
    ${jump ? `<p><a href="#${jump}" data-jump="${jump}">2022 選舉公報政見與學經歷</a></p>` : '<p>本站目前沒有此人的 2022 選舉公報資料。</p>'}
    <p class="muted small">2026 選舉公報預計 11/25 前公布。</p></div>`;
  if (!offices.length && !inters.length) return `<section class="summary" aria-label="摘要">${said}</section>`;

  const term = offices.filter((f) => f.date).map((f) => {
    const s = suspensionOf(f.data);
    return `<span class="num">${esc(f.date)}</span> 起${s ? `（<span class="num">${esc(s.date)}</span> 起停止職務）` : ''}`;
  }).join('、');
  let did = term ? `<dl class="kv"><dt>任職期間</dt><dd>${term}</dd></dl>` : '';
  did += pending.map((n) => `<p class="muted small">${esc(n)}</p>`).join('');
  if (ly.length) did += `<dl class="kv"><dt>立法院</dt><dd>${ly.map(([h, n, u]) => `${esc(h)} <span class="num">${n}</span> ${u}`).join('、')}</dd></dl>`;
  if (inters.length) {
    const { counts, other } = deptCounts(inters, rec.depts);
    const max = Math.max(1, ...counts.map(([, n]) => n));
    did += `<dl class="kv"><dt>質詢</dt><dd>${rec.countLine ? rec.countLine(written, videos) : rec.written
    ? `共 <span class="num">${inters.length}</span> 筆（書面 <span class="num">${written.length}</span> 筆、口頭 <span class="num">${videos.length}</span> 筆）`
    : `口頭質詢影片 <span class="num">${videos.length}</span> 筆（書面質詢尚未收錄）`}</dd></dl>
      ${rec.depts.length ? `<h3>質詢的部門分布</h3>
      <p class="muted small">${rec.written ? '書面與口頭合計，' : ''}依部門固定順序排列。</p>
      <ul class="bars">${counts.map(([dept, n]) => `<li><span>${esc(dept)}</span>${bar(n / max)}<span class="num">${n}</span></li>`).join('')}</ul>
      ${other ? `<p class="muted small">另有 <span class="num">${other}</span> 筆未分部門（例如市政總質詢），不列入上表。</p>` : ''}` : ''}
      ${rec.note ? `<p class="muted small">${esc(rec.note)}</p>` : ''}`;
  }
  const att = facts.attendance || [];
  const attExcluded = facts.attendance_excluded || [];
  if (att.length && att[0].data?.from_lists) {
    did += nwtAttendanceBlock(att);
  } else if (attExcluded.length || (att.length && typeof att[0].data?.meetings === 'number')) {
    did += khhAttendanceBlock(att, attExcluded);
  } else if (att.length) {
    const a = attendanceRates(att);
    did += `<h3>出缺勤</h3>
      <ul class="bars rates">
        <li><span>出席率</span>${bar(a.presentRate)}<span><span class="num">${pct(a.presentRate)}</span>（<span class="num">${a.present}</span>／<span class="num">${a.total}</span>）</span></li>
        <li><span>請假率</span>${bar(a.leaveRate)}<span><span class="num">${pct(a.leaveRate)}</span>（<span class="num">${a.leave}</span>／<span class="num">${a.total}</span>）</span></li>
      </ul>
      <p class="muted small">以大會議事錄為準，一次會議簽到即計出席；議事錄沒有缺席欄位，所以不計算缺席。</p>`;
  }
  return `<section class="summary" aria-label="摘要">${said}<div class="did"><h2>做了什麼</h2>${did}</div></section>`;
}

async function renderPerson(main, ctx, id) {
  let p;
  try {
    p = await load(`data/people/${id}.json`);
  } catch (e) {
    if (e instanceof NotFound) return renderNotFound(main, '人物');
    throw e;
  }
  const facts = p.facts || {};
  for (const list of Object.values(facts)) track(...list.map((f) => f.fetched_at));
  const notes = footnotes();
  const candidacy = facts.candidacy || [];
  const offices = facts.office || [];
  const inters = facts.interpellation || [];
  const videos = inters.filter((f) => f.data?.video_id);
  const written = inters.filter((f) => !f.data?.video_id);
  // 議員、縣市長選區連到選區頁；立委選區沒有頁面，只寫選區名稱；不分區、原住民立委沒有選區 id，用 fallback 文字
  const districtLink = (districtId, fallback = '') => {
    const m = districtMeta(ctx, districtId);
    if (m) return `<a href="#/d/${esc(districtId)}">${esc(districtTitle(m.d, m.county))}</a>`;
    const d = districtId && ctx.counties.get(isoOf(districtId))?.districts.find((x) => x.district_id === districtId);
    return esc(d?.name || fallback || districtId || '');
  };
  const label = (office) => officeLabel(office, ctx.counties.get(String(office).split('_')[0]));
  const lead = candidacy[0] || offices[0];
  const leadCounty = lead && ctx.counties.get(isoOf(lead.data.district_id));
  const leadMeta = lead && districtMeta(ctx, lead.data.district_id);
  const rec = RECORDS[leadCounty?.iso];
  const kinds = {
    written: { list: written, rows: interpellationRows, blurb: rec?.writtenBlurb || '標題連結至臺北市議會公報原文。' },
    video: { list: videos, rows: videoRows, blurb: rec?.videoBlurb || videoBlurb(videos) },
    ...Object.fromEntries(Object.entries(LY_KINDS).map(([k, m]) => [k, { list: facts[k] || [], rows: lyRows, blurb: m.blurb }])),
  };
  // 深度縣市的現任議員沒有任何紀錄時也要說明收錄範圍（例：高雄只收口頭質詢影片）；其他職位維持不顯示
  const recordedCouncillor = offices.some((f) => f.data.office === `${leadCounty?.iso}_councilor`);
  const noRecord = rec ? rec.noRecord : leadCounty ? noRecordNote(leadCounty) : NO_RECORD;

  const cand = candidacy.map((f) => `<dl class="facts">
      <dt>職位</dt><dd>${esc(label(f.data.office))}${notes.ref(f.source_url, f.fetched_at, '候選人登記名冊', f.data.publisher)}</dd>
      <dt>選區</dt><dd>${districtLink(f.data.district_id)}</dd>
      <dt>政黨</dt><dd>${party(f.data.party, ctx.parties)}</dd>
      <dt>登記日期</dt><dd class="num">${esc(f.date || '')}</dd>
    </dl>`).join('');

  const office = offices.map((f) => (f.data.elected_on ? headOfficeItem(f, districtLink(f.data.district_id)) : `<li><span class="name">${esc(f.data.title || label(f.data.office))}</span>
      <span>${officeDistrict(f.data, (id) => districtLink(id, f.data.area_name))}</span>
      <span class="meta">${f.date ? `<span class="num">${esc(f.date)}</span> 起` : ''}${notes.ref(f.source_url, f.fetched_at, officeSourceLabel(f.data.office))}${officeExtraRefs(f, notes)}</span></li>`)).join('');

  const bulletin = bulletinSection(facts, notes);
  const jump = facts.profile?.length || facts.platform?.length ? 'k-platform' : bulletin && 'k-bulletin';

  const inter = inters.length ? `<section aria-labelledby="k-inter"><h2 id="k-inter">質詢紀錄</h2>
      ${interSection('written', '書面質詢', kinds.written)}
      ${interSection('video', '口頭質詢（影片）', kinds.video)}</section>` : '';
  const ly = lyCounts(facts).length ? `<section aria-labelledby="k-ly"><h2 id="k-ly">立法院問政紀錄</h2>
      <p class="count">${esc(LY_NOTE)}</p>
      ${Object.entries(LY_KINDS).map(([k, m]) => interSection(k, m.heading, kinds[k])).join('')}</section>` : '';

  main.innerHTML = `
    ${crumbs(['#/', '全國'], ...(leadCounty ? [[`#/c/${leadCounty.iso}`, leadCounty.name]] : []),
      ...(leadMeta ? [[`#/d/${leadMeta.d.district_id}`, districtTitle(leadMeta.d, leadMeta.county)]] : []), ['', p.name])}
    <h1 tabindex="-1">${esc(p.name)}</h1>
    ${lead ? `<p class="byline">${partyOf(lead.data, ctx.parties)}<span>${districtLink(lead.data.district_id)}</span></p>` : ''}
    ${summaryCard(facts, { offices, inters, written, videos, jump, rec, pending: pendingRecordNotes(offices, ctx.counties) })}
    ${cand ? `<section aria-labelledby="k-cand"><h2 id="k-cand">2026 參選</h2>${cand}</section>` : ''}
    ${criminalRecordSection(facts)}
    ${office ? `<section aria-labelledby="k-office"><h2 id="k-office">任職</h2><ul class="roster office">${office}</ul>${hasSuspension(offices) ? suspensionNote() : ''}</section>` : ''}
    ${bulletin}
    ${summarySection(facts.summary || [], videos)}
    ${inter}
    ${ly}
    ${inters.length || (offices.length && !(rec && recordedCouncillor)) ? '' : `<p class="empty">${esc(noRecord)}</p>`}
    ${notes.render()}`;

  // hash 已用於路由，頁內錨點改成捲動加聚焦
  main.querySelector('[data-jump]')?.addEventListener('click', (e) => {
    e.preventDefault();
    const target = document.getElementById(e.currentTarget.dataset.jump);
    target.scrollIntoView();
    target.focus({ preventScroll: true });
  });

  for (const sec of main.querySelectorAll('section.inter')) {
    const { list, rows, blurb } = kinds[sec.dataset.key];
    sec.querySelector('.more')?.addEventListener('click', (e) => {
      const { shown, hidden } = splitLatest(list);
      const ol = sec.querySelector('.inters');
      ol.insertAdjacentHTML('beforeend', rows(hidden));
      sec.querySelector('.count').innerHTML = `共 <span class="num">${list.length}</span> 筆。${blurb}`;
      ol.children[shown.length]?.querySelector('a')?.focus();
      e.currentTarget.remove();
    });
  }
}

// 內容依公開前審查報告 §4a；時限與字數等營運承諾尚未決定，先不寫數字
function renderCorrections(main) {
  const form = safeUrl(CORRECTION_FORM_URL);
  main.innerHTML = `
    <h1 tabindex="-1">更正與當事人說明</h1>
    <section aria-labelledby="c-contact"><h2 id="c-contact">如何聯絡</h2>
      <p>${form ? `請填寫${ext(form, '更正表單')}` : '<strong>更正表單準備中。</strong>表單上線後，請透過表單聯絡'}，註明頁面網址、有誤的資料與正確資料的出處。</p>
      <p>我們會盡快處理並在頁面上標註更正。</p></section>
    <section aria-labelledby="c-ours"><h2 id="c-ours">本站的錯誤</h2>
      <p>如果是本站擷取或解析錯誤，會直接更正，並在該筆資料旁註記更正日期。</p></section>
    <section aria-labelledby="c-source"><h2 id="c-source">原始資料有爭議</h2>
      <p>如果您認為官方原始資料本身有誤，本站不會改動官方原文，但會在該筆資料旁標示「當事人對此有異議」，並附上您的說明。同時建議您向原發布機關申請更正；原機關更正後，本站會在下一次每日更新時同步。</p></section>
    <section aria-labelledby="c-party"><h2 id="c-party">當事人說明</h2>
      <p>候選人或民意代表本人，可以針對與自己有關的資料提出說明。</p>
      <ul>
        <li>說明原文照登並標註日期，不包含對他人的指控。</li>
        <li>本站以同樣的規則處理所有人。</li>
        <li>為了避免冒名，本站會請您以可驗證的方式確認身分，例如服務處或官方信箱來函。</li>
      </ul></section>
    <section aria-labelledby="c-pdpa"><h2 id="c-pdpa">個人資料權利</h2>
      <p>依個人資料保護法第 3 條，您可以請求查詢、閱覽、製給複本、補充或更正、停止蒐集處理利用，或刪除您的個人資料。</p>
      <ul>
        <li>本站收錄的資料都取自已依法公開的來源（同法第 19 條第 1 項第 3 款、第 7 款），用途是讓選民查詢候選人與民意代表的法定公開資料。</li>
        <li>本站不收費，我們會盡快處理並回覆處理結果。</li>
      </ul></section>
    <section aria-labelledby="c-privacy"><h2 id="c-privacy">隱私說明</h2>
      <p>本站不使用 cookie，也不做追蹤或流量分析。網站由 GitHub Pages 託管，GitHub 可能依其隱私政策記錄存取紀錄（例如 IP 位址）。</p></section>`;
}

function renderNotFound(main, what) {
  main.innerHTML = `<h1 tabindex="-1">找不到這個${esc(what)}</h1>
    <p>網址可能有誤，或資料尚未收錄。<a href="#/">回到選區查詢</a></p>`;
}

function renderError(main, err) {
  console.warn(err);
  main.innerHTML = `<h1 tabindex="-1">資料載入失敗</h1>
    <p>目前無法讀取資料，請稍後重新整理頁面。若持續發生，可先查閱
    <a href="https://www.cec.gov.tw/" target="_blank" rel="noopener">中央選舉委員會</a>的公告。</p>`;
}

// ---------- 路由 ----------

let ctxPromise;

async function route(moveFocus) {
  const main = document.getElementById('main');
  const [, type, id] = location.hash.match(/^#\/(c|d|p)\/(.+)$/) || [];
  try {
    const ctx = await (ctxPromise ||= boot());
    if (location.hash === '#/about/corrections') renderCorrections(main);
    else if (!type) renderHome(main, ctx); // 不等地圖載完，標題先可聚焦
    else if (!idOk(id)) renderNotFound(main, { c: '縣市', d: '選區', p: '人物' }[type]);
    else if (type === 'c') await renderCounty(main, ctx, id);
    else if (type === 'd') await renderDistrict(main, ctx, id);
    else await renderPerson(main, ctx, id);
  } catch (err) {
    ctxPromise = null;
    renderError(main, err);
  }
  if (moveFocus) main.querySelector('h1')?.focus();
  window.scrollTo(0, 0);
}

if (typeof document !== 'undefined') {
  window.addEventListener('hashchange', () => route(true));
  route(false);
}
