// 執行：node --test site/app.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fmtDate, emblemFor, splitLatest, publisherOf, hms, videoNote, DEPTS, deptCounts, attendanceRates, needsDistrict01Note, DISTRICT01_BULLETIN, bulletinGaps, criminalRecordSection, JUDICIAL_SEARCH, TAIWANGOGO_NOTE, incumbentHeading, officeSourceLabel, summarySection, SUMMARY_DISCLAIMER, NO_SPEECH, noRecordNote, REGISTERED_NOTE, headOfficeItem, suspensionOf, hasSuspension, SUSPENSION_NOTE, countyNote, homeNote, partyOf } from './app.js';
import { councilDistrictFor, townsOf, needsVillage, officeLabel, districtTitle, candidateOrder, districtSub, countyOrder, isoOf, COUNCIL_SITES } from './geo.js';

const EXPECTED = {
  北投區: '01', 士林區: '01', 內湖區: '02', 南港區: '02', 松山區: '03', 信義區: '03',
  中山區: '04', 大同區: '04', 中正區: '05', 萬華區: '05', 大安區: '06', 文山區: '06',
};
const fixture = [
  { villcode: '1', town: '士林區', districts: { tpe_councilor: 'tpe-council-01', tpe_councilor_plains: 'tpe-council-07', tpe_councilor_mountain: 'tpe-council-08' } },
  { villcode: '2', town: '士林區', districts: { tpe_councilor: 'tpe-council-01', tpe_councilor_plains: 'tpe-council-07', tpe_councilor_mountain: 'tpe-council-08' } },
  { villcode: '3', town: '大安區', districts: { tpe_councilor: 'tpe-council-06', tpe_councilor_plains: 'tpe-council-07', tpe_councilor_mountain: 'tpe-council-08' } },
];
// 竹北市跨兩個議員選區；本縣只有山地原住民選區、沒有平地原住民選區（模擬嘉義縣的情形）
const split = [
  { villcode: '10004010001', town: '竹北市', village: '甲里', districts: { hsq_councilor: 'hsq-council-01', hsq_councilor_mountain: 'hsq-council-13' } },
  { villcode: '10004010002', town: '竹北市', village: '乙里', districts: { hsq_councilor: 'hsq-council-02', hsq_councilor_mountain: 'hsq-council-13' } },
  { villcode: '10004020001', town: '竹東鎮', village: '丙里', districts: { hsq_councilor: 'hsq-council-03', hsq_councilor_mountain: 'hsq-council-14' } },
];
const hsq = { iso: 'hsq', name: '新竹縣' };
const tpe = { iso: 'tpe', name: '臺北市' };

test('maps a town to its single councilor district', () => {
  assert.deepEqual(councilDistrictFor(fixture, 'tpe', { town: '士林區' }), { id: 'tpe-council-01', fallback: false });
  assert.deepEqual(councilDistrictFor(split, 'hsq', { town: '竹東鎮' }), { id: 'hsq-council-03', fallback: false });
});

test('a town split across districts needs a village before it resolves', () => {
  assert.equal(needsVillage(split, 'hsq', '竹北市'), true);
  assert.equal(needsVillage(split, 'hsq', '竹東鎮'), false);
  assert.equal(councilDistrictFor(split, 'hsq', { town: '竹北市' }), null);
  assert.deepEqual(councilDistrictFor(split, 'hsq', { town: '竹北市', villcode: '10004010002' }), { id: 'hsq-council-02', fallback: false });
});

test('indigenous voters use the indigenous district of their town when the county has one', () => {
  assert.deepEqual(councilDistrictFor(fixture, 'tpe', { town: '大安區', indigenous: 'plains' }), { id: 'tpe-council-07', fallback: false });
  assert.deepEqual(councilDistrictFor(split, 'hsq', { town: '竹北市', indigenous: 'mountain' }), { id: 'hsq-council-13', fallback: false });
  assert.deepEqual(councilDistrictFor(split, 'hsq', { town: '竹東鎮', indigenous: 'mountain' }), { id: 'hsq-council-14', fallback: false });
});

test('indigenous voters fall back to the regional district when the county has no such district', () => {
  assert.deepEqual(councilDistrictFor(split, 'hsq', { town: '竹東鎮', indigenous: 'plains' }), { id: 'hsq-council-03', fallback: true });
  assert.equal(councilDistrictFor(split, 'hsq', { town: '竹北市', indigenous: 'plains' }), null, 'split town still needs a village');
  assert.deepEqual(councilDistrictFor(split, 'hsq', { town: '竹北市', villcode: '10004010001', indigenous: 'plains' }), { id: 'hsq-council-01', fallback: true });
});

test('returns null when town is empty or unknown', () => {
  assert.equal(councilDistrictFor(fixture, 'tpe', { town: '' }), null);
  assert.equal(councilDistrictFor(fixture, 'tpe', { town: '不存在區', indigenous: 'plains' }), null);
});

test('townsOf keeps first-seen order without duplicates', () => {
  assert.deepEqual(townsOf(fixture), ['士林區', '大安區']);
});

test('office labels and district titles derive from the county name', () => {
  assert.equal(officeLabel('tpe_councilor', tpe), '臺北市議員');
  assert.equal(officeLabel('hsq_mayor', hsq), '新竹縣長');
  assert.equal(officeLabel('legislator', undefined), '立法委員');
  assert.equal(districtTitle({ office: 'tpe_councilor', name: '臺北市第1選舉區' }, tpe), '臺北市議員 第1選舉區');
  assert.equal(districtTitle({ office: 'hsq_councilor', name: '新竹縣第13選舉區（山地原住民）' }, hsq), '新竹縣議員 第13選舉區（山地原住民）');
  assert.equal(districtTitle({ office: 'hsq_mayor', name: '新竹縣' }, hsq), '新竹縣長');
});

test('candidates sort by reg_no, else list_order, without mutating the input', () => {
  const list = [{ data: { list_order: 3 } }, { data: { reg_no: 1 } }, { data: {} }, { data: { list_order: 2 } }];
  assert.deepEqual(candidateOrder(list).map((p) => p.data.reg_no ?? p.data.list_order), [1, 2, 3, undefined]);
  assert.equal(list[0].data.list_order, 3);
});

test('district subtitles: whole county, listed towns, and partial towns', () => {
  assert.equal(districtSub({ district_id: 'tpe-council-07', office: 'tpe_councilor' }, fixture, tpe), '具平地原住民身分的全市選民');
  assert.equal(districtSub({ district_id: 'hsq-council-14', office: 'hsq_councilor' }, split, hsq), '具山地原住民身分、戶籍在竹東鎮的選民');
  assert.equal(districtSub({ district_id: 'hsq-council-01', office: 'hsq_councilor' }, split, hsq), '竹北市（部分）');
  assert.equal(districtSub({ district_id: 'hsq-mayor', office: 'hsq_mayor' }, split, hsq), '全縣 2 個鄉鎮市');
});

test('isoOf reads the county from councilor, mayor and legislator ids', () => {
  assert.equal(isoOf('hsz-council-03'), 'hsz');
  assert.equal(isoOf('kin-mayor'), 'kin');
  assert.equal(isoOf('ly-tao-02'), 'tao');
});

test('county list puts municipalities first and Kinmen and Lienchiang last', () => {
  const got = countyOrder([{ iso: 'lie', moi_code: '09007' }, { iso: 'cyi', moi_code: '10020' }, { iso: 'tao', moi_code: '68000' }, { iso: 'tpe', moi_code: '63000' }]);
  assert.deepEqual(got.map((c) => c.iso), ['tpe', 'tao', 'cyi', 'lie']);
});

test('non-deep counties get a neutral note, never implying the person did nothing', () => {
  const note = noRecordNote(hsq);
  assert.match(note, /新竹縣議會的問政紀錄仍在建置中/);
  assert.doesNotMatch(note, /沒有問政|無問政/);
  assert.doesNotMatch(REGISTERED_NOTE, /臺北/);
});

test('council links never point to the third-party site and cover all 22 counties', () => {
  assert.equal(Object.keys(COUNCIL_SITES).length, 22);
  for (const u of Object.values(COUNCIL_SITES)) assert.match(u, /^https:\/\/www\.[\w-]+\.gov\.tw\/$/);
});

test('fmtDate converts UTC timestamps to Asia/Taipei dates', () => {
  assert.equal(fmtDate('2026-09-28T17:00:00Z'), '2026-09-29');
});

const real = new URL('./data/villages/tpe.json', import.meta.url);
test('all 12 Taipei towns map to the official councilor districts (exported data)', { skip: !existsSync(real) && 'site/data 未產生' }, () => {
  const villages = JSON.parse(readFileSync(real, 'utf8')).villages;
  assert.deepEqual(townsOf(villages).sort(), Object.keys(EXPECTED).sort());
  for (const [town, n] of Object.entries(EXPECTED)) {
    assert.equal(councilDistrictFor(villages, 'tpe', { town })?.id, `tpe-council-${n}`, town);
  }
});

const hsqData = new URL('./data/villages/hsq.json', import.meta.url);
test('only Zhubei needs a village in Hsinchu County (exported data)', { skip: !existsSync(hsqData) && 'site/data 未產生' }, () => {
  const villages = JSON.parse(readFileSync(hsqData, 'utf8')).villages;
  assert.deepEqual(townsOf(villages).filter((t) => needsVillage(villages, 'hsq', t)), ['竹北市']);
});

const parties = {
  中國國民黨: { emblem: 'parties/kmt.png' },
  無黨團結聯盟: { emblem: 'parties/npsu.svg' },
  壞路徑黨: { emblem: 'javascript:alert(1)' },
};

test('emblemFor uses the none mark only for exactly 無 or 無黨籍', () => {
  assert.equal(emblemFor('無', parties), 'assets/none.svg');
  assert.equal(emblemFor('無黨籍', parties), 'assets/none.svg');
  assert.equal(emblemFor('無黨團結聯盟', parties), 'parties/npsu.svg');
  assert.equal(emblemFor('無黨團結聯盟', {}), null);
});

test('emblemFor returns the index path, or null when missing, unsafe or index absent', () => {
  assert.equal(emblemFor('中國國民黨', parties), 'parties/kmt.png');
  assert.equal(emblemFor('台灣麻將最大黨', parties), null);
  assert.equal(emblemFor('壞路徑黨', parties), null);
  assert.equal(emblemFor('中國國民黨', undefined), null);
});

test('splitLatest shows the newest 20 interpellations and keeps the rest hidden', () => {
  const list = Array.from({ length: 25 }, (_, i) => ({ date: `2025-01-${String(i + 1).padStart(2, '0')}` }));
  const { shown, hidden } = splitLatest(list);
  assert.equal(shown.length, 20);
  assert.equal(hidden.length, 5);
  assert.equal(shown[0].date, '2025-01-25');
  assert.equal(hidden.at(-1).date, '2025-01-01');
  assert.equal(list[0].date, '2025-01-01', 'input not mutated');
});

test('splitLatest hides nothing when there are 20 or fewer records', () => {
  const { shown, hidden } = splitLatest([{ date: '2024-01-01' }, { date: '2024-05-01' }]);
  assert.deepEqual(shown.map((f) => f.date), ['2024-05-01', '2024-01-01']);
  assert.equal(hidden.length, 0);
});

test('publisherOf prefers the record publisher over the URL domain', () => {
  const url = 'https://web.cec.gov.tw/api/file/abc.pdf';
  assert.equal(publisherOf(url, '臺北市選舉委員會'), '臺北市選舉委員會');
  assert.equal(publisherOf(url), '中央選舉委員會');
  assert.equal(publisherOf('https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id=x'), '臺北市議會');
});

test('hms formats seconds as h:mm:ss, flooring fractions', () => {
  assert.equal(hms(0), '0:00:00');
  assert.equal(hms(641.078113), '0:10:41');
  assert.equal(hms(5113.9), '1:25:13');
  assert.equal(hms(36000), '10:00:00');
});

test('videoNote explains seekable groups and group size', () => {
  assert.equal(videoNote({ seekable: true, group_size: 1, start_sec: 10 }), '從本組開始播放');
  assert.equal(videoNote({ seekable: true, group_size: 4, start_sec: 10 }), '從本組開始播放；同組 4 位議員，未細分到個人');
});

test('videoNote gives the approximate start time when the link cannot seek', () => {
  assert.equal(videoNote({ seekable: false, group_size: 1, start_sec: 5113.9 }), '本組約從 1:25:13 開始');
  assert.equal(videoNote({ seekable: false, group_size: 3, start_sec: 641 }), '本組約從 0:10:41 開始；同組 3 位議員，未細分到個人');
});

const it = (dept, extra = {}) => ({ data: { dept, ...extra } });

test('deptCounts counts written plus oral per department in the fixed order, including zeros', () => {
  const inters = [it('工務'), it('工務', { video_id: 'v' }), it('民政'), it('教育', { video_id: 'v' }), it(null, { video_id: 'v' }), it('原民會')];
  const { counts, other } = deptCounts(inters);
  assert.deepEqual(counts, [['民政', 1], ['財政建設', 0], ['教育', 1], ['交通', 0], ['警政衛生', 0], ['工務', 2]]);
  assert.equal(other, 2);
});

test('deptCounts keeps the fixed order regardless of which department has the most', () => {
  const inters = [...Array(9).fill(it('工務')), it('民政'), it('交通'), it('交通')];
  assert.deepEqual(deptCounts(inters).counts.map(([d]) => d), DEPTS);
  assert.deepEqual(DEPTS, ['民政', '財政建設', '教育', '交通', '警政衛生', '工務']);
});

test('attendanceRates divides present and leave by the total record count', () => {
  const s = (status) => ({ data: { status } });
  const r = attendanceRates([s('present'), s('present'), s('present'), s('leave'), s('present'), s('present'), s('present'), s('leave')]);
  assert.deepEqual(r, { total: 8, present: 6, leave: 2, presentRate: 0.75, leaveRate: 0.25 });
  assert.deepEqual(attendanceRates([]), { total: 0, present: 0, leave: 0, presentRate: 0, leaveRate: 0 });
});

test('needsDistrict01Note only for a district 01 office holder without a profile', () => {
  const office = (district_id) => ({ data: { district_id } });
  assert.equal(needsDistrict01Note({ office: [office('tpe-council-01')] }), true);
  assert.equal(needsDistrict01Note({ office: [office('tpe-council-01')], profile: [{}] }), false);
  assert.equal(needsDistrict01Note({ office: [office('tpe-council-02')] }), false);
  assert.equal(needsDistrict01Note({ candidacy: [office('tpe-council-01')] }), false);
});

test('bulletinGaps links the missing profile or platform to the other one\'s bulletin', () => {
  const plat = { source_url: 'https://bulletin.cec.gov.tw/a.pdf' };
  const prof = { source_url: 'https://bulletin.cec.gov.tw/b.pdf' };
  assert.deepEqual(bulletinGaps({ platform: [plat] }), { profile: plat.source_url, platform: null });
  assert.deepEqual(bulletinGaps({ profile: [prof] }), { profile: null, platform: prof.source_url });
  assert.deepEqual(bulletinGaps({ profile: [prof], platform: [plat] }), { profile: null, platform: null });
  assert.deepEqual(bulletinGaps({}), { profile: null, platform: null });
});

test('district 01 bulletin link is percent-encoded', () => {
  assert.equal(DISTRICT01_BULLETIN, 'https://bulletin.cec.gov.tw/01%E9%81%B8%E8%88%89%E5%85%AC%E5%A0%B1/05%E7%9B%B4%E8%BD%84%E5%B8%82%E8%AD%B0%E5%93%A1/111%E5%B9%B4/01%E8%87%BA%E5%8C%97%E5%B8%82/%E8%87%BA%E5%8C%97%E5%B8%82%E7%AC%AC01%E9%81%B8%E8%88%89%E5%8D%80.pdf');
});

const cand = [{ data: { office: 'tpe_councilor', district_id: 'tpe-council-01' } }];
const conv = (judgment_date, extra = {}) => ({
  source_url: `https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=${judgment_date}`,
  data: { court: '臺灣臺北地方法院', case_no: `111年度訴字第${judgment_date.slice(5, 7)}號`, judgment_date, offense: '詐欺', result: '有期徒刑6月', final: true, title: 't', ...extra },
});
const BANNED = /無前科|沒有前科|清白/;

test('criminal record section shows only when the person has a candidacy', () => {
  assert.equal(criminalRecordSection({}), '');
  assert.equal(criminalRecordSection({ office: [{}], conviction: [conv('2020-01-01')] }), '');
  assert.match(criminalRecordSection({ candidacy: cand }), /<h2 id="k-crime">確定有罪判決查詢<\/h2>/);
});

test('without convictions shows the status line, both portals in order and the full disclosure', () => {
  const html = criminalRecordSection({ candidacy: cand });
  assert.match(html, /本站尚未收錄經查證的確定有罪判決。/);
  assert.match(html, /選舉公報依法不刊登前科（公職人員選舉罷免法第47條）。/);
  assert.ok(html.includes(TAIWANGOGO_NOTE));
  assert.ok(TAIWANGOGO_NOTE.endsWith('本站未查證其內容，提供連結不代表本站認同或背書；使用其內容前，請對照原始來源查證。'));
  const j = html.indexOf(`href="${JUDICIAL_SEARCH}"`);
  const g = html.indexOf('href="https://council2026.taiwangogo.tw/"');
  assert.ok(j > 0 && g > j, 'judicial portal comes first');
});

test('taiwangogo link is site-level with noopener noreferrer nofollow', () => {
  const html = criminalRecordSection({ candidacy: cand });
  const links = [...html.matchAll(/<a href="([^"]*taiwangogo[^"]*)"([^>]*)>/g)];
  assert.equal(links.length, 1);
  assert.equal(links[0][1], 'https://council2026.taiwangogo.tw/');
  assert.match(links[0][2], /rel="noopener noreferrer nofollow"/);
  assert.match(links[0][2], /target="_blank"/);
});

test('convictions render newest first with court, linked case number, date, offense and result', () => {
  const html = criminalRecordSection({ candidacy: cand, conviction: [conv('2019-03-01'), conv('2021-07-01')] });
  assert.match(html, /本站收錄 <span class="num">2<\/span> 筆經查證的確定有罪判決。/);
  assert.ok(html.indexOf('2021-07-01') < html.indexOf('2019-03-01'));
  assert.match(html, /<a href="https:\/\/judgment\.judicial\.gov\.tw\/FJUD\/data\.aspx\?ty=JD&#38;id=2021-07-01" target="_blank" rel="noopener">111年度訴字第07號<\/a>/);
  for (const s of ['臺灣臺北地方法院', '詐欺', '有期徒刑6月']) assert.ok(html.includes(s), s);
  assert.ok(html.includes('council2026.taiwangogo.tw') && html.includes(TAIWANGOGO_NOTE), 'portals kept below');
  assert.ok(!html.includes('本站尚未收錄'));
});

test('convictions whose final is not exactly true are never shown', () => {
  const html = criminalRecordSection({ candidacy: cand, conviction: [conv('2020-01-01', { final: false }), conv('2020-02-01', { final: 'true' }), conv('2020-03-01', { final: undefined }), conv('2018-05-01')] });
  assert.match(html, /本站收錄 <span class="num">1<\/span> 筆/);
  for (const d of ['2020-01-01', '2020-02-01', '2020-03-01']) assert.ok(!html.includes(d), d);
  assert.match(criminalRecordSection({ candidacy: cand, conviction: [conv('2020-01-01', { final: false })] }), /本站尚未收錄經查證的確定有罪判決。/);
});

test('criminal record section never says the person has no record', () => {
  for (const facts of [{ candidacy: cand }, { candidacy: cand, conviction: [conv('2020-01-01')] }, { candidacy: cand, conviction: [conv('2020-01-01', { final: false })] }]) {
    assert.doesNotMatch(criminalRecordSection(facts), BANNED);
  }
});

test('incumbent heading follows the district office: mayor, county magistrate or councilor', () => {
  assert.equal(incumbentHeading({ office: 'tpe_mayor', name: '臺北市' }), '現任市長');
  assert.equal(incumbentHeading({ office: 'hsq_mayor', name: '新竹縣' }), '現任縣長');
  assert.equal(incumbentHeading({ office: 'tpe_councilor', name: '臺北市第01選舉區' }), '現任議員');
  assert.equal(incumbentHeading({ office: 'ila_mayor', name: '宜蘭縣' }, true), '宜蘭縣長（停職中）');
});

test('office source label is the election result for mayors and the council roster otherwise', () => {
  assert.equal(officeSourceLabel('tpe_mayor'), '選舉結果');
  assert.equal(officeSourceLabel('tpe_councilor'), '議員名冊');
});

test('criminal-record section discloses that verification starts from third-party leads', () => {
  const html = criminalRecordSection({ candidacy: [{ data: {} }] });
  assert.match(html, /沒有涵蓋所有候選人/);
  assert.match(html, /「尚未收錄」不代表查無判決/);
  assert.doesNotMatch(html, /前科資訊/);
});

const VIEWER = 'https://gaz.tcc.gov.tw/pdf/viewer.html?id=AAA';
const src = { heading: '交通部門質詢第8組', doc_type: '部門質詢', dept: '交通', group: 8, dates: ['2025-05-22'], transcript_url: VIEWER, transcript_page_url: `${VIEWER}#page=3`, transcript_pages: [560, 566], videos: [{ date: '2025-05-22', group: 9 }] };
const cite = { source_url: `${VIEWER}#page=4`, page: 562, cited_text: '原文' };
const summary = (session, date, data) => ({ date, data: { session, sources: [src], status: 'ok', issues: [], ...data } });

test('summarySection shows the disclaimer on every session block', () => {
  const html = summarySection([
    summary('第14屆第4次定期大會', '2024-12-01', { issues: [{ topic: '議題甲', councilor_points: ['詢問'], response: '說明', citations: [cite] }] }),
    summary('第14屆第5次定期大會', '2025-06-10', { status: 'no_speech' }),
  ]);
  assert.equal(html.split(SUMMARY_DISCLAIMER).length - 1, 2);
  assert.equal(html.split('<details').length - 1, 2);
  assert.ok(html.indexOf('第5次') < html.indexOf('第4次'), 'newest session first');
});

test('summarySection shows the no_speech wording without implying absence', () => {
  const html = summarySection([summary('第14屆第5次定期大會', '2025-06-10', { status: 'no_speech' })]);
  assert.ok(html.includes(NO_SPEECH));
  assert.equal(NO_SPEECH, '本會期公報速記錄中未見其口頭質詢發言');
  assert.ok(!/缺席|沒有質詢/.test(html));
});

test('summarySection skips issues without a linkable citation and sessions left empty', () => {
  const html = summarySection([summary('第14屆第5次定期大會', '2025-06-10', { issues: [
    { topic: '有引文', councilor_points: ['詢問'], response: null, citations: [cite] },
    { topic: '空引文', councilor_points: ['詢問'], response: null, citations: [] },
    { topic: '壞連結', councilor_points: ['詢問'], response: null, citations: [{ source_url: 'javascript:x', page: 1 }] },
  ] })]);
  assert.ok(html.includes('有引文') && html.includes('速記錄第 <span class="num">562</span> 頁'));
  assert.ok(!html.includes('空引文') && !html.includes('壞連結'));
  assert.equal(summarySection([summary('第14屆第5次定期大會', '2025-06-10', { issues: [{ topic: '空', citations: [] }] })]), '');
});

test('summarySection omits the response row when a cross-session response was removed', () => {
  const html = summarySection([summary('第14屆第5次定期大會', '2025-06-10', { issues: [
    { topic: '回應已移除', councilor_points: ['詢問'], response: null, response_removed: true, citations: [cite] },
  ] })]);
  assert.ok(html.includes('回應已移除'));
  assert.ok(!html.includes('市府回應') && !html.includes('未見市府回應'));
  const kept = summarySection([summary('第14屆第5次定期大會', '2025-06-10', { issues: [
    { topic: '無回應', councilor_points: ['詢問'], response: null, response_removed: false, citations: [cite] },
  ] })]);
  assert.ok(kept.includes('速記錄節錄中未見市府回應'));
});

test('summarySection links the transcript and the video of the same date and group', () => {
  const video = { date: '2025-05-22', source_url: 'https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id=v', data: { group: 9, doc_type: '部門質詢', dept: '交通' } };
  const other = { ...video, source_url: 'https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id=wrong', data: { ...video.data, group: 8 } };
  const html = summarySection([summary('第14屆第5次定期大會', '2025-06-10', { status: 'no_speech' })], [other, video]);
  assert.ok(html.includes(`href="${VIEWER}#page=3"`));
  assert.ok(html.includes('id=v"') && !html.includes('id=wrong'));
});

test('footer carries the summary disclaimer once', () => {
  const page = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
  assert.equal(page.split(SUMMARY_DISCLAIMER).length - 1, 1);
});

// V14 §3：縣市長任職
const CEC = 'https://db.cec.gov.tw/static/elections/data/tickets/ELC/C2/x.json';
const headFact = (iso, title, events, extra = {}) => ({
  date: '2022-12-25', source_url: CEC, fetched_at: '2026-10-01T03:00:00Z',
  data: { office: `${iso}_mayor`, district_id: `${iso}-mayor`, title, elected_on: '2022-11-26', source_label: '中選會 2022 開票結果',
    inauguration_source_url: 'https://www.moi.gov.tw/News_Content.aspx?n=4&s=274773', inauguration_source_label: '內政部 2022-12-25 新聞稿',
    ...(events ? { status_events: events } : {}), ...extra },
});
const ILA = [{ date: '2024-12-31', event: 'suspended', acting_name: '林茂盛', acting_position: '副縣長', acting_title: '代理縣長',
  source_url: 'https://www.moi.gov.tw/News_Content.aspx?n=4&s=324430', source_label: '內政部 2024-12-31 公告',
  acting_source_url: 'https://www.e-land.gov.tw/cp.aspx?n=2700', acting_source_label: '宜蘭縣政府代理縣長介紹', fetched_at: '2026-10-02' }];
const HSZ = [
  { date: '2024-07-26', event: 'suspended', acting_name: '邱臣遠', acting_position: '副市長', acting_title: '代理市長',
    source_url: 'https://www.moi.gov.tw/News_Content.aspx?n=4&s=318288', source_label: '內政部 2024-07-26 公告', fetched_at: '2026-10-02' },
  { date: '2025-12-17', event: 'reinstated', source_url: 'https://www.moi.gov.tw/News_Content.aspx?n=4&s=335771', source_label: '內政部 2026-01-04 說明', fetched_at: '2026-10-02' },
];
const text = (html) => html.replace(/<[^>]+>/g, '').replace(/[ \n]+/g, ' ');

test('a suspended head is titled 停職中 with the acting deputy, never 現任 or 前縣長', () => {
  const t = text(headOfficeItem(headFact('ila', '宜蘭縣長', ILA)));
  assert.match(t, /宜蘭縣長（停職中）/);
  assert.match(t, /2022-11-26 當選　2022-12-25 就職/);
  assert.match(t, /2024-12-31 起停止職務，由副縣長林茂盛代理縣長/);
  assert.match(t, /出處：中選會 2022 開票結果；內政部 2022-12-25 新聞稿；內政部 2024-12-31 公告；宜蘭縣政府代理縣長介紹｜資料截至 2026-10-02/);
  assert.doesNotMatch(t, /現任|前縣長|解職|涉|因案/);
});

test('a reinstated head lists the past suspension without 起 and is not titled 停職中', () => {
  const t = text(headOfficeItem(headFact('hsz', '新竹市長', HSZ)));
  assert.match(t, /新竹市長 /);
  assert.doesNotMatch(t, /停職中/);
  assert.match(t, /2024-07-26 停止職務，由副市長邱臣遠代理市長/);
  assert.match(t, /2025-12-17 內政部同意復職/);
  assert.equal(suspensionOf(headFact('hsz', '新竹市長', HSZ).data), null);
  assert.equal(suspensionOf(headFact('ila', '宜蘭縣長', ILA).data).acting_name, '林茂盛');
});

test('a head without changes shows only election and inauguration; Chiayi City shows the rerun note', () => {
  const t = text(headOfficeItem(headFact('kee', '基隆市長')));
  assert.match(t, /基隆市長 .*2022-11-26 當選　2022-12-25 就職 出處：中選會 2022 開票結果；內政部 2022-12-25 新聞稿｜資料截至 2026-10-01/);
  const c = text(headOfficeItem(headFact('cyi', '嘉義市長', null, { elected_on: '2022-12-18', election_note: '重行選舉' })));
  assert.match(c, /2022-12-18 當選（重行選舉）　2022-12-25 就職/);
});

test('data as-of date is the latest of the fact and its status events', () => {
  const f = { ...headFact('ila', '宜蘭縣長', ILA), fetched_at: '2026-10-05T01:00:00Z' };
  assert.match(text(headOfficeItem(f)), /資料截至 2026-10-05/);
});

test('the suspension glossary is needed only when a suspension appears, and names no one', () => {
  assert.equal(hasSuspension([headFact('ila', '宜蘭縣長', ILA)]), true);
  assert.equal(hasSuspension([headFact('hsz', '新竹市長', HSZ)]), true);
  assert.equal(hasSuspension([headFact('kee', '基隆市長')]), false);
  assert.equal(hasSuspension([{ data: { office: 'tpe_mayor', title: '臺北市長（第8屆）' } }]), false);
  assert.doesNotMatch(SUSPENSION_NOTE, /林|高|宜蘭|新竹/);
  assert.match(SUSPENSION_NOTE, /停職不代表判決確定/);
});

test('non-Taipei county note lists what is provided, neutrally', () => {
  const n = countyNote(hsq);
  assert.match(n, /2026 候選人名單、選區與新竹縣長任職資料/);
  assert.match(n, /新竹縣議會的問政紀錄仍在建置中/);
  assert.doesNotMatch(n, /只提供|深度資料/);
});

test('county note mentions the incumbent councillor list only when the data has one', () => {
  const nwt = { iso: 'nwt', name: '新北市', councilor_roster: true };
  assert.match(countyNote(nwt), /2026 候選人名單、選區、現任議員名單與新北市長任職資料/);
  assert.match(countyNote(nwt), /新北市議會的問政紀錄仍在建置中/);
  assert.doesNotMatch(countyNote(hsq), /現任議員/);
});

test('home note lists non-Taipei counties with an incumbent councillor list, from data', () => {
  const tpe = { iso: 'tpe', name: '臺北市', councilor_roster: true };
  const nwt = { iso: 'nwt', name: '新北市', councilor_roster: true };
  const khh = { iso: 'khh', name: '高雄市', councilor_roster: true };
  assert.match(homeNote([tpe, nwt, hsq, khh]), /縣市長任職資料，新北市、高雄市另有現任議員名單，議員問政紀錄仍在建置中/);
  assert.doesNotMatch(homeNote([tpe, hsq]), /現任議員/);
});

test('a party taken from the 2022 results is labelled with the year', () => {
  assert.match(partyOf({ party: '民主進步黨', party_year: 2022 }, {}), /2022 推薦/);
  assert.doesNotMatch(partyOf({ party: '民主進步黨' }, {}), /推薦/);
});
