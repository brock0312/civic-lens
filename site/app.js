// civic-lens 靜態前端：hash routing，資料全部從相對路徑 data/ 讀取。

export const INDIGENOUS_DISTRICT = { plains: 'tpe-council-07', mountain: 'tpe-council-08' };
export const MAYOR_DISTRICT = 'tpe-mayor';
// ponytail: MVP 只開放議員與市長選區；立委有人物資料後再加 ly-tpe-*
const SHOWN_DISTRICTS = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `tpe-council-0${n}`).concat(MAYOR_DISTRICT);

const OFFICE_LABEL = { tpe_councilor: '臺北市議員', tpe_mayor: '臺北市長', legislator: '立法委員' };
const INDIGENOUS_SUB = { [INDIGENOUS_DISTRICT.plains]: '具平地原住民身分的全市選民', [INDIGENOUS_DISTRICT.mountain]: '具山地原住民身分的全市選民' };
const PUBLISHERS = [['cec.gov.tw', '中央選舉委員會'], ['election.gov.taipei', '臺北市選舉委員會'], ['tcc.gov.tw', '臺北市議會']];
export const INTERPELLATION_PAGE = 20;
const NO_RECORD ='本站目前沒有此人的任內問政紀錄（收錄範圍：第14屆臺北市議員書面質詢與口頭質詢影片）';

// ponytail: villages.json 已是全國資料，但首頁目前只做臺北；全國地圖上線時改為依縣市篩選
// 只留有臺北議員選區對照的里（基隆也有中正、信義、中山等同名行政區）
export function taipeiVillages(villages) {
  return villages.filter((v) => v.districts.tpe_councilor);
}

// 行政區（依 villcode 順序，不重複）
export function townsOf(villages) {
  return [...new Set(villages.map((v) => v.town))];
}

// 行政區＋原住民身分 → 議員選區 id；無法判定時回傳 null
export function councilDistrictFor(villages, town, indigenous) {
  if (INDIGENOUS_DISTRICT[indigenous]) return INDIGENOUS_DISTRICT[indigenous];
  const ids = new Set(villages.filter((v) => v.town === town).map((v) => v.districts.tpe_councilor));
  return ids.size === 1 ? [...ids][0] : null;
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
  const size = Number(d?.group_size) || 0;
  const group = size > 1 ? `同組 ${size} 位議員，未細分到個人` : '';
  if (d?.seekable) return group ? `從本組開始播放；${group}` : '從本組開始播放';
  return `本組約從 ${hms(d?.start_sec)} 開始${group ? `；${group}` : ''}`;
}

// 質詢部門：固定順序，不依數量排序
export const DEPTS = ['民政', '財政建設', '教育', '交通', '警政衛生', '工務'];

// 各部門質詢筆數（書面＋口頭），依 DEPTS 順序輸出，含 0 筆；不在 DEPTS 的（如市政總質詢）計入 other
export function deptCounts(inters) {
  const counts = DEPTS.map((dept) => [dept, inters.filter((f) => f.data?.dept === dept).length]);
  return { counts, other: inters.length - counts.reduce((s, [, n]) => s + n, 0) };
}

// 出席率、請假率：分母是總筆數；議事錄沒有缺席欄位，所以不算缺席率
export function attendanceRates(list) {
  const total = list.length;
  const present = list.filter((f) => f.data?.status === 'present').length;
  const leave = list.filter((f) => f.data?.status === 'leave').length;
  return { total, present, leave, presentRate: total ? present / total : 0, leaveRate: total ? leave / total : 0 };
}

// 第1選舉區 2022 公報含重疊的隱藏文字，本站刻意不擷取：現任該區議員且沒有 profile 時要註明
export const DISTRICT01_BULLETIN = encodeURI('https://bulletin.cec.gov.tw/01選舉公報/05直轄市議員/111年/01臺北市/臺北市第01選舉區.pdf');
export function needsDistrict01Note(facts) {
  return (facts.office || []).some((f) => f.data?.district_id === 'tpe-council-01') && !(facts.profile || []).length;
}

// 公報只擷取到學經歷或政見其中一項時，缺的那項改連另一項的公報原文；值為 null 表示不缺
export function bulletinGaps(facts) {
  const profile = facts.profile?.[0];
  const platform = facts.platform?.[0];
  return {
    profile: !profile && platform ? platform.source_url || '' : null,
    platform: profile && !platform ? profile.source_url || '' : null,
  };
}

// 現任者的段落標題與出處標籤依職位決定：首長選區用市長／縣長（依選區名稱有無「縣」），其餘為議員
const isHead = (office) => String(office || '').endsWith('_mayor');
export function incumbentHeading(d) {
  if (!isHead(d.office)) return '現任議員';
  return String(d.name || '').includes('縣') ? '現任縣長' : '現任市長';
}
// 議員來自議會名冊；首長來自中選會選舉結果
export const officeSourceLabel = (office) => (isHead(office) ? '選舉結果' : '議員名冊');

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
  const [villages, parties, ...districts] = await Promise.all([
    load('data/villages.json'),
    loadParties(),
    ...SHOWN_DISTRICTS.map((id) => load(`data/districts/${id}.json`)),
  ]);
  track(...villages.sources.map((s) => s.fetched_at));
  for (const d of districts) track(d.fetched_at, ...d.people.map((p) => p.fetched_at));
  return { villages: taipeiVillages(villages.villages), parties, districts: Object.fromEntries(districts.map((d) => [d.district_id, d])) };
}

// ---------- 共用片段 ----------

const shortName = (d) => d.name.replace(/^臺北市/, '');
const districtTitle = (d) => (d.office === 'tpe_mayor' ? '臺北市長' : `${OFFICE_LABEL[d.office] || d.office} ${shortName(d)}`);

function districtSub(d, villages) {
  if (d.office === 'tpe_mayor') return `全市 ${townsOf(villages).length} 個行政區`;
  if (INDIGENOUS_SUB[d.district_id]) return INDIGENOUS_SUB[d.district_id];
  return townsOf(villages.filter((v) => v.districts.tpe_councilor === d.district_id)).join('、');
}

function party(name, parties) {
  const src = emblemFor(name, parties);
  const img = src ? `<img src="${esc(src)}" alt="" width="20" height="20" decoding="async">` : '';
  // ponytail: 沒有黨徽時保留同寬空位，讓政黨文字對齊；不放替代圖樣
  return `<span class="party"><span class="emblem${src ? '' : ' blank'}">${img}</span><span>${esc(name)}</span></span>`;
}

const stat = (label, n, unit) => `<div><dt>${label}</dt><dd><span class="num">${esc(n)}</span>${unit}</dd></div>`;

// ---------- 頁面 ----------

function resultRow(d, villages) {
  return `<li><a href="#/d/${esc(d.district_id)}">
    <span class="result-title">${esc(districtTitle(d))}</span>
    <span class="result-sub">${esc(districtSub(d, villages))}</span>
    <span class="result-seats"><span class="num">${esc(d.seats)}</span> 席</span></a></li>`;
}

function renderHome(main, ctx) {
  const towns = townsOf(ctx.villages);
  main.innerHTML = `
    <h1 tabindex="-1">查詢你的選區</h1>
    <p class="lede">選擇戶籍所在的行政區，查看 2026 年臺北市議員與市長的候選人。</p>
    <form class="lookup" onsubmit="return false">
      <div class="field">
        <label for="town">行政區</label>
        <select id="town"><option value="">請選擇</option>${towns.map((t) => `<option>${esc(t)}</option>`).join('')}</select>
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
  const update = () => {
    const town = form.town.value;
    const ind = form.ind.value;
    const id = councilDistrictFor(ctx.villages, town, ind);
    const out = main.querySelector('#result');
    if (!id) { out.innerHTML = ''; return; }
    const where = ind === 'none' ? esc(town) : ind === 'plains' ? '平地原住民選民' : '山地原住民選民';
    out.innerHTML = `<h2 id="result-h">${where}的選區</h2>
      <ul class="results">${resultRow(ctx.districts[id], ctx.villages)}${resultRow(ctx.districts[MAYOR_DISTRICT], ctx.villages)}</ul>
      ${ind !== 'none' ? '<p class="small muted">具原住民身分的選民，市議員投原住民選舉區，不投所在行政區的選舉區。</p>' : ''}`;
  };
  form.addEventListener('change', update);
  update();
}

function rosterRow(p, fn, parties, incumbent) {
  return `<li><a class="name" href="#/p/${esc(p.person_id)}">${esc(p.name)}</a>
    ${party(p.data.party, parties)}
    <span class="meta">${incumbent ? '<span class="tag">現任</span>' : ''}${fn}</span></li>`;
}

function renderDistrict(main, ctx, id) {
  const d = ctx.districts[id];
  if (!d) return renderNotFound(main, '選區');
  const notes = footnotes();
  const cands = d.people.filter((p) => p.kind === 'candidacy').sort((a, b) => a.data.reg_no - b.data.reg_no);
  const office = d.people.filter((p) => p.kind === 'office');
  const officeIds = new Set(office.map((p) => p.person_id));
  const registered = cands.some((p) => p.data.status === 'registered');
  const seatsFn = notes.ref(d.source_url, d.fetched_at, '應選名額公告');
  const candRows = cands.map((p) => rosterRow(p, notes.ref(p.source_url, p.fetched_at, '候選人登記名冊', p.data.publisher), ctx.parties, officeIds.has(p.person_id))).join('');
  const officeRows = office.map((p) => rosterRow(p, notes.ref(p.source_url, p.fetched_at, officeSourceLabel(p.data.office)), ctx.parties, false)).join('');

  main.innerHTML = `
    <h1 tabindex="-1">${esc(districtTitle(d))}</h1>
    <p class="lede">${esc(districtSub(d, ctx.villages))}</p>
    <dl class="stats">
      ${stat('應選', d.seats, ` 席${seatsFn}`)}
      ${stat('候選人', cands.length, ' 人')}
      ${office.length ? stat('現任', office.length, ' 人') : ''}
    </dl>
    <section aria-labelledby="cand-h">
      <h2 id="cand-h">2026 候選人</h2>
      ${registered ? '<p class="status" role="note">名單依臺北市選委會 115-09-08 登記冊，尚未經審定；號次將於官方名單公告（市長 11/12、議員 11/17）後補上。</p>' : ''}
      ${cands.length ? `<ol class="roster">${candRows}</ol><p class="small muted">依官方登記順序排列，非選票號次。</p>` : '<p class="muted">尚無候選人資料。</p>'}
    </section>
    ${office.length ? `<section aria-labelledby="office-h"><h2 id="office-h">${incumbentHeading(d)}</h2>
      <ul class="roster">${officeRows}</ul></section>` : ''}
    ${notes.render()}`;
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
      <span class="title">${u ? ext(u, title) : title}</span></li>`;
  }).join('');
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

// 2022 選舉公報：學歷、經歷、政見；政見原文保留換行，不截斷
function bulletinSection(facts, notes) {
  const profile = (facts.profile || [])[0];
  const platform = (facts.platform || [])[0];
  let body;
  if (profile || platform) {
    const pd = profile?.data || {};
    const gap = bulletinGaps(facts);
    const gapNote = (what, url) => `<p class="status" role="note">2022 公報${what}未能以文字擷取，請見${safeUrl(url) ? ext(safeUrl(url), '公報原文') : '公報原文'}。</p>`;
    body = `${pd.education?.length ? `<h3>學歷</h3><ul class="plain">${listItems(pd.education)}</ul>` : ''}
      ${pd.experience?.length ? `<h3>經歷</h3><ul class="plain">${listItems(pd.experience)}</ul>` : ''}
      ${profile ? srcLine(profile, '2022 選舉公報學經歷', notes) : ''}
      ${gap.profile !== null ? `<h3>學經歷</h3>${gapNote('學經歷', gap.profile)}` : ''}
      <h3 id="k-platform" tabindex="-1">政見</h3>
      ${platform ? `<div class="platform">${esc(platform.data?.text || '')}</div>${srcLine(platform, '2022 選舉公報政見', notes)}` : gapNote('政見', gap.platform)}`;
  } else if (needsDistrict01Note(facts)) {
    body = `<p class="status" role="note">第1選舉區 2022 公報因版面內含重疊文字，本站無法可靠擷取，請見${ext(DISTRICT01_BULLETIN, '公報原文')}。</p>`;
  } else return '';
  return `<section aria-labelledby="k-bulletin"><h2 id="k-bulletin" tabindex="-1">2022 選舉公報</h2>${body}</section>`;
}

// 確定有罪判決：只要有 2026 參選資料就顯示（用詞依刑法第 76 條，不稱「前科」）。只列 final === true 的確定判決，照原文呈現不加評語；
// 沒有資料時只說「尚未收錄」，任何情況都不寫成沒有前科（見 docs/PLAN.md §6 G5）
export const JUDICIAL_SEARCH = 'https://judgment.judicial.gov.tw/FJUD/default.aspx';
export const TAIWANGOGO = 'https://council2026.taiwangogo.tw/';
export const TAIWANGOGO_NOTE = '該網站由台灣前進經營，時代力量代管，並與時代力量、台灣基進、台灣綠黨、小民參政歐巴桑聯盟合作。收錄範圍包含起訴、行政罰、民事判決與新聞報導。起訴不等於有罪，行政罰與民事判決也不是刑事前科。本站未查證其內容，提供連結不代表本站認同或背書。';

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
  return `<section aria-labelledby="k-crime"><h2 id="k-crime">確定有罪判決</h2>
    ${status}
    <p class="small muted">本站只收錄司法院公開、已確定且可佐證身分的有罪判決，並附判決字號與原文連結；無法確認已確定或無法佐證身分的判決不收錄。本站的查證以第三方資料庫列出的線索為起點，沒有涵蓋所有候選人，「尚未收錄」不代表查無判決。選舉公報依法不刊登前科（公職人員選舉罷免法第47條）。</p>
    <h3>查詢入口</h3>
    <ul class="portals">
      <li>${ext(JUDICIAL_SEARCH, '司法院裁判書查詢系統')}<span class="muted small">（官方）</span></li>
      <li><a href="${TAIWANGOGO}" target="_blank" rel="noopener noreferrer nofollow">council2026.taiwangogo.tw</a>
        <p class="small muted">${TAIWANGOGO_NOTE}</p></li>
    </ul></section>`;
}

// 摘要卡「說過什麼｜做了什麼」：只是事實計數，不排序、不比較、不評語
function summaryCard(facts, { offices, inters, written, videos, jump }) {
  const said = `<div class="said"><h2>說過什麼</h2>
    ${jump ? `<p><a href="#${jump}" data-jump="${jump}">2022 選舉公報政見與學經歷</a></p>` : '<p>本站目前沒有此人的 2022 選舉公報資料。</p>'}
    <p class="muted small">2026 選舉公報預計 11/25 前公布。</p></div>`;
  if (!offices.length && !inters.length) return `<section class="summary" aria-label="摘要">${said}</section>`;

  const term = offices.filter((f) => f.date).map((f) => `<span class="num">${esc(f.date)}</span> 起`).join('、');
  let did = term ? `<dl class="kv"><dt>任職期間</dt><dd>${term}</dd></dl>` : '';
  if (inters.length) {
    const { counts, other } = deptCounts(inters);
    const max = Math.max(1, ...counts.map(([, n]) => n));
    did += `<dl class="kv"><dt>質詢</dt><dd>共 <span class="num">${inters.length}</span> 筆（書面 <span class="num">${written.length}</span> 筆、口頭 <span class="num">${videos.length}</span> 筆）</dd></dl>
      <h3>質詢的部門分布</h3>
      <p class="muted small">書面與口頭合計，依部門固定順序排列。</p>
      <ul class="bars">${counts.map(([dept, n]) => `<li><span>${esc(dept)}</span>${bar(n / max)}<span class="num">${n}</span></li>`).join('')}</ul>
      ${other ? `<p class="muted small">另有 <span class="num">${other}</span> 筆未分部門（例如市政總質詢），不列入上表。</p>` : ''}`;
  }
  const att = facts.attendance || [];
  if (att.length) {
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
  const kinds = {
    written: { list: written, rows: interpellationRows, blurb: '標題連結至臺北市議會公報原文。' },
    video: { list: videos, rows: videoRows, blurb: '連結至臺北市議會議事影音系統，影片來源：臺北市議會。' },
  };

  const districtLink = (districtId) => {
    const d = ctx.districts[districtId];
    return d ? `<a href="#/d/${esc(d.district_id)}">${esc(districtTitle(d))}</a>` : esc(districtId);
  };
  const lead = candidacy[0] || offices[0];

  const cand = candidacy.map((f) => `<dl class="facts">
      <dt>職位</dt><dd>${esc(OFFICE_LABEL[f.data.office] || f.data.office)}${notes.ref(f.source_url, f.fetched_at, '候選人登記名冊', f.data.publisher)}</dd>
      <dt>選區</dt><dd>${districtLink(f.data.district_id)}</dd>
      <dt>政黨</dt><dd>${party(f.data.party, ctx.parties)}</dd>
      <dt>登記日期</dt><dd class="num">${esc(f.date || '')}</dd>
    </dl>`).join('');

  const office = offices.map((f) => `<li><span class="name">${esc(f.data.title || OFFICE_LABEL[f.data.office] || '')}</span>
      <span>${districtLink(f.data.district_id)}</span>
      <span class="meta">${f.date ? `<span class="num">${esc(f.date)}</span> 起` : ''}${notes.ref(f.source_url, f.fetched_at, officeSourceLabel(f.data.office))}</span></li>`).join('');

  const bulletin = bulletinSection(facts, notes);
  const jump = facts.profile?.length || facts.platform?.length ? 'k-platform' : bulletin && 'k-bulletin';

  const inter = inters.length ? `<section aria-labelledby="k-inter"><h2 id="k-inter">質詢紀錄</h2>
      ${interSection('written', '書面質詢', kinds.written)}
      ${interSection('video', '口頭質詢（影片）', kinds.video)}</section>` : '';

  main.innerHTML = `
    <h1 tabindex="-1">${esc(p.name)}</h1>
    ${lead ? `<p class="byline">${party(lead.data.party, ctx.parties)}<span>${districtLink(lead.data.district_id)}</span></p>` : ''}
    ${summaryCard(facts, { offices, inters, written, videos, jump })}
    ${cand ? `<section aria-labelledby="k-cand"><h2 id="k-cand">2026 參選</h2>${cand}</section>` : ''}
    ${criminalRecordSection(facts)}
    ${office ? `<section aria-labelledby="k-office"><h2 id="k-office">任職</h2><ul class="roster office">${office}</ul></section>` : ''}
    ${bulletin}
    ${inter}
    ${offices.length || inters.length ? '' : `<p class="empty">${NO_RECORD}</p>`}
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
    <a href="https://election.gov.taipei/" target="_blank" rel="noopener">臺北市選舉委員會</a>的公告。</p>`;
}

// ---------- 路由 ----------

let ctxPromise;

async function route(moveFocus) {
  const main = document.getElementById('main');
  const [, type, id] = location.hash.match(/^#\/(d|p)\/(.+)$/) || [];
  try {
    const ctx = await (ctxPromise ||= boot());
    if (location.hash === '#/about/corrections') renderCorrections(main);
    else if (!type) renderHome(main, ctx);
    else if (!idOk(id)) renderNotFound(main, type === 'd' ? '選區' : '人物');
    else if (type === 'd') renderDistrict(main, ctx, id);
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
