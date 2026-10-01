// 執行：node --test site/app.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { councilDistrictFor, taipeiVillages, townsOf, fmtDate, emblemFor, splitLatest, publisherOf, hms, videoNote, DEPTS, deptCounts, attendanceRates, needsDistrict01Note, DISTRICT01_BULLETIN, bulletinGaps } from './app.js';

const EXPECTED = {
  北投區: '01', 士林區: '01', 內湖區: '02', 南港區: '02', 松山區: '03', 信義區: '03',
  中山區: '04', 大同區: '04', 中正區: '05', 萬華區: '05', 大安區: '06', 文山區: '06',
};
const fixture = [
  { town: '士林區', districts: { tpe_councilor: 'tpe-council-01' } },
  { town: '士林區', districts: { tpe_councilor: 'tpe-council-01' } },
  { town: '大安區', districts: { tpe_councilor: 'tpe-council-06' } },
  { town: '怪區', districts: { tpe_councilor: 'tpe-council-01' } },
  { town: '怪區', districts: { tpe_councilor: 'tpe-council-02' } },
];

test('maps a town to its single councilor district', () => {
  assert.equal(councilDistrictFor(fixture, '士林區', 'none'), 'tpe-council-01');
  assert.equal(councilDistrictFor(fixture, '大安區', 'none'), 'tpe-council-06');
});

test('indigenous voters map to 07/08 regardless of town', () => {
  assert.equal(councilDistrictFor(fixture, '', 'plains'), 'tpe-council-07');
  assert.equal(councilDistrictFor(fixture, '士林區', 'mountain'), 'tpe-council-08');
});

test('returns null when town is empty, unknown or ambiguous', () => {
  assert.equal(councilDistrictFor(fixture, '', 'none'), null);
  assert.equal(councilDistrictFor(fixture, '不存在區', 'none'), null);
  assert.equal(councilDistrictFor(fixture, '怪區', 'none'), null);
});

test('townsOf keeps first-seen order without duplicates', () => {
  assert.deepEqual(townsOf(fixture), ['士林區', '大安區', '怪區']);
});

test('fmtDate converts UTC timestamps to Asia/Taipei dates', () => {
  assert.equal(fmtDate('2026-09-28T17:00:00Z'), '2026-09-29');
});

const real = new URL('./data/villages.json', import.meta.url);
test('all 12 Taipei towns map to the official councilor districts (exported data)', { skip: !existsSync(real) && 'site/data 未產生' }, () => {
  const villages = taipeiVillages(JSON.parse(readFileSync(real, 'utf8')).villages);
  assert.deepEqual(townsOf(villages).sort(), Object.keys(EXPECTED).sort());
  for (const [town, n] of Object.entries(EXPECTED)) {
    assert.equal(councilDistrictFor(villages, town, 'none'), `tpe-council-${n}`, town);
  }
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

test('taipeiVillages drops same-named towns from other counties', () => {
  const mixed = [
    { town: '中正區', districts: { tpe_councilor: 'tpe-council-05' } },
    { town: '中正區', districts: { kee_councilor: 'kee-council-02' } },
  ];
  assert.deepEqual(councilDistrictFor(mixed, '中正區', 'none'), null);
  assert.equal(councilDistrictFor(taipeiVillages(mixed), '中正區', 'none'), 'tpe-council-05');
});
