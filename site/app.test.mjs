// 執行：node --test site/app.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fmtDate, emblemFor, splitLatest, publisherOf, hms, videoNote, DEPTS, deptCounts, attendanceRates, needsDistrict01Note, DISTRICT01_BULLETIN, bulletinGaps, bulletinLink, bulletinSection, NOT_ELECTED_2022, criminalRecordSection, JUDICIAL_SEARCH, TAIWANGOGO_NOTE, candidateTag, officeSourceLabel, summarySection, SUMMARY_DISCLAIMER, NO_SPEECH, noRecordNote, REGISTERED_NOTE, headOfficeItem, suspensionOf, hasSuspension, SUSPENSION_NOTE, countyNote, homeNote, partyOf, officeExtraRefs, officeDistrict, countyTag, BULLETIN_TAG, pendingRecordNotes, officeTitle, lyCounts, LY_NOTE } from './app.js';
import { videoBlurb, KHH_DEPTS, RECORDS, attendanceTotals, khhAttendanceBlock, KHH_ATTENDANCE_NOTE, attendanceExcludedNote } from './app.js';
import { TXG_DEPTS, summaryCard, nwtAttendanceBlock, NWT_ATTENDANCE_NOTE, videoRows, NWT_VOD_HOME } from './app.js';
import { HUA_ORAL, HUA_TRANSCRIPT, HUA_ATTENDANCE_NOTE, interpellationRows, TITLE_MAX } from './app.js';
import { DEEP_COUNTIES } from './geo.js';
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

test('videoNote for Kaohsiung per-councillor marks says playback starts at the speech', () => {
  assert.equal(videoNote({ seekable: true, group_size: 1, start_sec: 1701, gid: '80' }), '從該議員發言處開始播放');
  assert.equal(videoNote({ seekable: true, group: 3, group_size: 1, start_sec: 10 }), '從本組開始播放');
});

test('video blurb names the council from the video link host', () => {
  assert.equal(videoBlurb([{ source_url: 'https://tccvideo.tcc.gov.tw/Front/VideoContent/Index?id=x&num=1' }]), '連結至臺北市議會議事影音系統，影片來源：臺北市議會。');
  assert.equal(videoBlurb([{ source_url: 'https://ivod.kcc.gov.tw/watch/80/202609KCC0408R1150923143208VIDEOmp4?start=1701' }]), '連結至高雄市議會議事影音系統，影片來源：高雄市議會。');
});

test('videoNote for Taichung and Tainan clips says the video is the councillor slot or a joint interpellation', () => {
  assert.equal(videoNote({ clip: true, group_size: 1 }), '影片即該議員的質詢時段');
  assert.equal(videoNote({ clip: true, group_size: 3 }), '3 位議員聯合質詢的影片');
});

test('Taichung and Tainan video blurbs name the council; Tainan says the videos are on YouTube', () => {
  assert.equal(videoBlurb([{ source_url: 'https://vod.tccc.gov.tw/index.asp?url=22&cno=24&ano=14826' }]), '連結至臺中市議會議事影音系統，影片來源：臺中市議會。');
  assert.match(RECORDS.tnn.videoBlurb, /臺南市議會發布在 YouTube/);
  assert.equal(RECORDS.txg.videoBlurb, undefined);
});

test('Taichung and Tainan are deep counties with neutral not-yet-collected notes', () => {
  for (const iso of ['tpe', 'khh', 'txg', 'tnn']) assert.ok(DEEP_COUNTIES.has(iso), iso);
  for (const iso of ['txg', 'tnn']) {
    const r = RECORDS[iso];
    assert.equal(r.written, false);
    assert.match(r.noRecord, /書面質詢與出缺勤本站尚未收錄/);
    assert.match(r.note, /出缺勤紀錄本站尚未收錄/);
    assert.doesNotMatch(r.noRecord + r.note, /沒有問政|無問政|未質詢|缺席/);
  }
  assert.match(RECORDS.txg.noRecord, /第4屆臺中市議員口頭質詢影片/);
  assert.match(RECORDS.tnn.noRecord, /第4屆臺南市議員市政總質詢影片/);
});

test('summary card skips the department chart when the council has no departments (Tainan)', () => {
  const v = (dept) => ({ data: { dept, video_id: 'x', clip: true, group_size: 1 } });
  const card = (rec, inters) => summaryCard({}, { offices: [], inters, written: [], videos: inters, rec });
  const tnn = card(RECORDS.tnn, [v(null), v(null)]);
  assert.doesNotMatch(tnn, /部門分布/);
  assert.match(tnn, /口頭質詢影片 <span class="num">2<\/span> 筆/);
  assert.match(tnn, /出缺勤紀錄本站尚未收錄/);
  const txg = card(RECORDS.txg, [v('民政'), v(null)]);
  assert.match(txg, /部門分布/);
  assert.match(txg, /另有 <span class="num">1<\/span> 筆未分部門/);
  assert.deepEqual(TXG_DEPTS, ['民政', '財政經濟', '教育文化', '交通地政', '警消環衛', '都發建設水利']);
  const khh = card(RECORDS.khh, [v('民政')]);
  assert.match(khh, /部門分布/);
  assert.doesNotMatch(khh, /出缺勤紀錄本站尚未收錄/);
});

test('Kaohsiung departments use the council committees in a fixed order', () => {
  const inters = [it('財經', { video_id: 'v' }), it('警消衛環', { video_id: 'v' }), it(null, { video_id: 'v' })];
  const { counts, other } = deptCounts(inters, KHH_DEPTS);
  assert.deepEqual(counts.map(([d]) => d), KHH_DEPTS);
  assert.deepEqual(counts.filter(([, n]) => n).map(([d]) => d), ['財經', '警消衛環']);
  assert.equal(other, 1);
});

test('Kaohsiung empty note states the collected scope neutrally', () => {
  const n = RECORDS.khh.noRecord;
  assert.match(n, /第4屆高雄市議員口頭質詢影片/);
  assert.match(n, /書面質詢紀錄仍在建置中/);
  assert.doesNotMatch(n, /出缺勤/);
  assert.doesNotMatch(n, /沒有問政|無問政|未質詢|缺席/);
  assert.equal(RECORDS.khh.written, false);
});


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

const khhAtt = (session, meetings, present, types, absent, url = 'https://cissearch.kcc.gov.tw/a.pdf') => ({
  source_url: url,
  data: {
    session, meetings, present, absent, leave_types: types,
    leave: ['請假', '病假', '喪假', '事假'].reduce((s, k) => s + (types[k] || 0), 0),
    duty: ['公差', '公假'].reduce((s, k) => s + (types[k] || 0), 0),
  },
});

test('attendanceTotals keeps official duty apart from leave', () => {
  const a = attendanceTotals([
    khhAtt('第4屆第1次臨時會', 9, 6, { 請假: 1, 病假: 1, 公差: 1 }, null),
    khhAtt('第4屆第6次定期大會', 44, 40, { 請假: 1, 公假: 2 }, 1),
  ]);
  assert.deepEqual([a.total, a.present, a.leave, a.duty, a.absent], [53, 46, 3, 3, 1]);
  assert.deepEqual(a.leaveTypes, [['請假', 2], ['病假', 1]]);
  assert.deepEqual(a.dutyTypes, [['公差', 1], ['公假', 2]]);
  assert.equal(a.leaveRate, 3 / 53);
  assert.equal(a.dutyRate, 3 / 53);
  assert.equal(attendanceTotals([]).total, 0);
});

test('absence rate only counts meetings in tables that have an absence column', () => {
  const a = attendanceTotals([
    khhAtt('第4屆第1次臨時會', 9, 9, {}, null),
    khhAtt('第4屆第6次定期大會', 44, 43, {}, 1),
  ]);
  assert.deepEqual([a.total, a.absentTotal, a.absent], [53, 44, 1]);
  assert.equal(a.absentRate, 1 / 44);
  assert.equal(a.presentRate, 52 / 53);
  assert.equal(attendanceTotals([khhAtt('第4屆成立大會', 1, 1, {}, null)]).absentRate, 0);
});

test('Kaohsiung attendance block shows present, leave, duty and absence with explicit denominators and sources', () => {
  const html = khhAttendanceBlock([
    khhAtt('第4屆成立大會', 1, 1, {}, null),
    khhAtt('第4屆第9次臨時會', 7, 5, { 請假: 1, 公假: 1 }, 0, 'https://cissearch.kcc.gov.tw/b.pdf'),
  ]);
  assert.match(html, /<span>出席<\/span>/);
  assert.match(html, /<span>請假<\/span>.*（<span class="num">1<\/span>／<span class="num">8<\/span>）/);
  assert.match(html, /<span>公差／公假<\/span>/);
  assert.match(html, /<span>缺席<\/span>.*（<span class="num">0<\/span>／<span class="num">7<\/span>）/);
  assert.match(html, /缺席的分母是有缺席欄的 <span class="num">7<\/span> 次會議/);
  assert.match(html, /請假依假別：請假 <span class="num">1<\/span> 次。/);
  assert.match(html, /公差／公假依類別：公假 <span class="num">1<\/span> 次。/);
  assert.match(html, /href="https:\/\/cissearch\.kcc\.gov\.tw\/b\.pdf"/);
  assert.match(html, /第4屆成立大會<\/a>：會議 <span class="num">1<\/span> 次.*表上無缺席欄/);
  assert.ok(html.indexOf('第4屆第9次臨時會') < html.indexOf('第4屆成立大會'), 'newest table first');
  assert.ok(html.includes(KHH_ATTENDANCE_NOTE));
  assert.doesNotMatch(html, /排名|名次|分數|評分|未收錄該會期/);
});

test('a rejected table column shows a neutral note derived from the data', () => {
  const gap = { source_url: 'https://cissearch.kcc.gov.tw/c.pdf', data: { session: '第4屆第4次定期大會', reason: 'mismatch' } };
  assert.equal(attendanceExcludedNote(gap), '第4次定期大會的官方統計表，本人欄位的逐次標記與合計不一致，本站未收錄該會期。');
  assert.match(attendanceExcludedNote({ data: { session: '第4屆第1次臨時會', reason: 'blank' } }), /本人欄位無法可靠讀取/);
  const html = khhAttendanceBlock([khhAtt('第4屆成立大會', 1, 1, {}, null)], [gap]);
  assert.match(html, /第4次定期大會的官方統計表，本人欄位的逐次標記與合計不一致，本站未收錄該會期。/);
  assert.match(khhAttendanceBlock([], [gap]), /未收錄該會期/);
});

test('Kaohsiung attendance definition names the official table, separates official duty and states the denominators', () => {
  assert.match(KHH_ATTENDANCE_NOTE, /議員出席情形統計表/);
  assert.match(KHH_ATTENDANCE_NOTE, /成立大會、臨時會或定期大會/);
  assert.match(KHH_ATTENDANCE_NOTE, /公差、公假是執行公務，和請假分開列/);
  assert.match(KHH_ATTENDANCE_NOTE, /缺席的比例只以有缺席欄的統計表的會議次數為分母/);
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

const COUNTIES = new Map([['nwt', { iso: 'nwt', name: '新北市' }], ['ila', { iso: 'ila', name: '宜蘭縣' }], ['hsq', { iso: 'hsq', name: '新竹縣' }]]);
const inc = (office, district_id, suspended = false) => ({ office, district_id, suspended });

test('candidate holding office in the same district is tagged 現任, or 停職中 when suspended', () => {
  assert.equal(candidateTag([inc('nwt_councilor', 'nwt-council-01')], 'nwt-council-01', COUNTIES), '現任');
  assert.equal(candidateTag([inc('ila_mayor', 'ila-mayor', true)], 'ila-mayor', COUNTIES), '停職中');
});

test('candidate holding office elsewhere is tagged with that office title', () => {
  assert.equal(candidateTag([inc('nwt_councilor', 'nwt-council-03')], 'nwt-mayor', COUNTIES), '現任新北市議員');
  assert.equal(candidateTag([inc('ila_mayor', 'ila-mayor', true)], 'ila-council-01', COUNTIES), '宜蘭縣長（停職中）');
  assert.equal(candidateTag([inc('nwt_councilor', 'nwt-council-03'), inc('nwt_mayor', 'nwt-mayor')], 'nwt-mayor', COUNTIES), '現任');
});

test('Hsinchu County incumbent is current in the 2026 districts that replaced the 2022 one', () => {
  // export 把 2022 第 1 區展開成 2026 第 1、2 區
  const list = [inc('hsq_councilor', 'hsq-council-01'), inc('hsq_councilor', 'hsq-council-02')];
  assert.equal(candidateTag(list, 'hsq-council-02', COUNTIES), '現任');
  assert.equal(candidateTag(list, 'hsq-council-03', COUNTIES), '現任新竹縣議員');
});

test('office district shows the 2022 district name without linking when it was redistricted', () => {
  const link = (id) => `<a href="#/d/${id}">${id}</a>`;
  assert.equal(officeDistrict({ district_id: 'hsq-council-2022-01', district_name: '新竹縣第1選舉區（2022 年劃分）' }, link), '新竹縣第1選舉區（2022 年劃分）');
  assert.equal(officeDistrict({ district_id: 'nwt-council-01' }, link), '<a href="#/d/nwt-council-01">nwt-council-01</a>');
});

test('candidate without office has no tag', () => {
  assert.equal(candidateTag([], 'nwt-mayor', COUNTIES), '');
  assert.equal(candidateTag(undefined, 'nwt-mayor', COUNTIES), '');
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
  assert.match(n, /2026 候選人名單與選區，候選人中的現任新竹縣長會標示/);
  assert.match(n, /新竹縣議會的問政紀錄仍在建置中/);
  assert.doesNotMatch(n, /只提供|深度資料/);
});

test('county note says incumbent councillors are tagged only when the data has a roster', () => {
  const nwt = { iso: 'nwt', name: '新北市', councilor_roster: true };
  assert.match(countyNote(nwt), /候選人中的現任議員與新北市長會標示/);
  assert.doesNotMatch(countyNote(nwt), /名單、選區、現任|任職資料/);
  assert.match(countyNote(nwt), /新北市議會的問政紀錄仍在建置中/);
  assert.doesNotMatch(countyNote(hsq), /現任議員/);
});

test('home note lists non-Taipei counties whose incumbent councillors are tagged, from data', () => {
  const tpe = { iso: 'tpe', name: '臺北市', councilor_roster: true };
  const cha = { iso: 'cha', name: '彰化縣', councilor_roster: true };
  const tao = { iso: 'tao', name: '桃園市', councilor_roster: true };
  assert.match(homeNote([tpe, cha, hsq, tao]), /候選人中的現任縣市長與彰化縣、桃園市的現任議員會標示，議員問政紀錄仍在建置中/);
  assert.doesNotMatch(homeNote([tpe, cha]), /現任議員名單/);
  assert.doesNotMatch(homeNote([tpe, hsq]), /現任議員/);
});

test('a party taken from the 2022 results is labelled with the year', () => {
  assert.match(partyOf({ party: '民主進步黨', party_year: 2022 }, {}), /2022 推薦/);
  assert.doesNotMatch(partyOf({ party: '民主進步黨' }, {}), /推薦/);
});

test('office extra refs add 2022 party and inauguration sources only when the fields exist', () => {
  const notes = { ref: (u, t, label) => `[${label}]` };
  const f = { fetched_at: 't', data: { party_source_url: 'https://c', party_source_label: 'CEC', inauguration_source_url: 'https://m', inauguration_source_label: 'MOI' } };
  assert.equal(officeExtraRefs(f, notes), '[CEC][MOI]');
  assert.equal(officeExtraRefs({ fetched_at: 't', data: { party: 'x' } }, notes), '');
});

// 臺北以外的公報：bulletin fact 記原檔網址與頁碼
const NWT_PDF = 'https://bulletin.cec.gov.tw/01%E9%81%B8%E8%88%89%E5%85%AC%E5%A0%B1/x.pdf';
const noNotes = { ref: () => '' };
const linkFact = (page) => ({ source_url: NWT_PDF, data: { page }, fetched_at: '2026-10-02T00:00:00Z' });

test('bulletinLink adds the page anchor when known and is null for Taipei people', () => {
  assert.equal(bulletinLink({ bulletin: [linkFact(3)] }), `${NWT_PDF}#page=3`);
  assert.equal(bulletinLink({ bulletin: [linkFact()] }), NWT_PDF);
  assert.equal(bulletinLink({}), null);
});

test('bulletinGaps links the missing field to the bulletin page when there is a bulletin fact', () => {
  const plat = { source_url: NWT_PDF };
  assert.deepEqual(bulletinGaps({ platform: [plat], bulletin: [linkFact(2)] }), { profile: `${NWT_PDF}#page=2`, platform: null });
});

test('bulletinSection shows only the neutral original-file link when no text was collected', () => {
  const html = bulletinSection({ bulletin: [linkFact(5)] }, noNotes);
  assert.match(html, /2022 選舉公報/);
  assert.match(html, /本站未收錄文字政見與學經歷，請見<a href="[^"]+#page=5"[^>]*>公報原檔<\/a>（第 5 頁）。/);
});

test('bulletinSection for a non-Taipei person with a platform but no profile uses the neutral wording', () => {
  const html = bulletinSection({ platform: [{ ...linkFact(), data: { text: '一、政見' } }], bulletin: [linkFact(4)] }, noNotes);
  assert.match(html, /一、政見/);
  assert.match(html, /出處：.*2022 選舉公報政見.*中央選舉委員會/);
  assert.match(html, /本站未收錄文字學經歷，請見<a href="[^"]+#page=4"/);
  assert.doesNotMatch(html, /未能以文字擷取/);
});

test('bulletinSection notes a 2022 loss only when the matched 2022 count says not elected', () => {
  const lost = (elected) => ({ ...linkFact(5), data: { page: 5, elected } });
  const plat = [{ ...linkFact(), data: { text: '一、政見' } }];
  assert.ok(bulletinSection({ bulletin: [lost(false)] }, noNotes).includes(`<h2 id="k-bulletin" tabindex="-1">2022 選舉公報</h2><p class="status" role="note">${NOT_ELECTED_2022}</p>`));
  assert.ok(bulletinSection({ platform: plat, bulletin: [lost(false)] }, noNotes).includes(NOT_ELECTED_2022));
  assert.ok(!bulletinSection({ platform: plat, bulletin: [lost(true)] }, noNotes).includes(NOT_ELECTED_2022));
  assert.ok(!bulletinSection({ platform: plat, bulletin: [linkFact(5)] }, noNotes).includes(NOT_ELECTED_2022));
  assert.ok(!bulletinSection({ platform: plat }, noNotes).includes(NOT_ELECTED_2022)); // 臺北沒有 bulletin fact
});

test('bulletinSection keeps the Taipei wording when there is no bulletin fact', () => {
  const html = bulletinSection({ platform: [{ ...linkFact(), data: { text: 'x' } }] }, noNotes);
  assert.match(html, /2022 公報學經歷未能以文字擷取/);
  assert.equal(bulletinSection({}, noNotes), '');
});

test('publisherOf names county councils and the interior ministry from their domains', () => {
  assert.equal(publisherOf('https://www.ntp.gov.tw/content/list/list.aspx'), '新北市議會');
  assert.equal(publisherOf('https://api.cyscc.gov.tw/x'), '嘉義縣議會');
  assert.equal(publisherOf('https://www.tccc.gov.tw/x'), '臺中市議會');
  assert.equal(publisherOf('https://www.kmc.gov.tw/x'), '基隆市議會');
  assert.equal(publisherOf('https://www.kmcc.gov.tw/x'), '金門縣議會');
  assert.equal(publisherOf('https://www.moi.gov.tw/News_Content.aspx?n=4'), '內政部');
  assert.equal(publisherOf('https://www.tcc.gov.tw/x'), '臺北市議會');
});

test('county note and tag mention 2022 bulletins only when the data flags them', () => {
  const tao = { iso: 'tao', name: '桃園市', councilor_roster: true, councilor_bulletin: true };
  const lie = { iso: 'lie', name: '連江縣', councilor_roster: false, councilor_bulletin: false };
  const tpe = { iso: 'tpe', name: '臺北市', councilor_roster: true, councilor_bulletin: true };
  assert.match(countyNote(tao), /並收錄現任議員的 2022 選舉公報政見與學經歷；桃園市議會的問政紀錄仍在建置中/);
  assert.doesNotMatch(countyNote(lie), /公報/);
  assert.equal(countyTag(tpe), '含問政紀錄');
  assert.equal(countyTag(tao), BULLETIN_TAG);
  assert.equal(countyTag(lie), '');
  assert.match(homeNote([tpe, tao, lie]), /標示「含 2022 公報」的縣市另收錄候選人中現任議員的 2022 選舉公報政見與學經歷/);
  assert.doesNotMatch(homeNote([tpe, lie]), /2022 公報/);
});

test('incumbent councillors outside deep counties get the records-pending note, once per county', () => {
  const counties = new Map([['tao', { iso: 'tao', name: '桃園市' }], ['tpe', { iso: 'tpe', name: '臺北市' }], ['ila', { iso: 'ila', name: '宜蘭縣' }]]);
  const office = (o, d) => ({ data: { office: o, district_id: d } });
  assert.deepEqual(pendingRecordNotes([office('tao_councilor', 'tao-council-04'), office('tao_councilor', 'tao-council-04')], counties),
    ['桃園市議會的問政紀錄仍在建置中，本站目前尚未收錄。']);
  assert.deepEqual(pendingRecordNotes([office('tpe_councilor', 'tpe-council-01')], counties), []);
  assert.deepEqual(pendingRecordNotes([office('ila_mayor', 'ila-mayor')], counties), []);
});

test('sitting legislators running locally are tagged with their office, district or not', () => {
  const counties = new Map([['tnn', { iso: 'tnn', name: '臺南市' }]]);
  assert.equal(candidateTag([{ office: 'legislator', district_id: 'ly-tnn-06' }], 'tnn-mayor', counties), '現任立法委員');
  assert.equal(candidateTag([{ office: 'legislator' }], 'tnn-mayor', counties), '現任立法委員');
  assert.equal(officeSourceLabel('legislator'), '立法院委員資料');
});

test('legislative records are counted in a fixed order and attributed to the API licence', () => {
  assert.deepEqual(lyCounts({ ly_bill: [1, 2], ly_interpellation: [1] }), [['書面質詢', 1, '筆'], ['列名提案人的議案', 2, '件']]);
  assert.deepEqual(lyCounts({}), []);
  assert.match(LY_NOTE, /CC BY 4\.0/);
  assert.match(LY_NOTE, /出席與表決紀錄尚未收錄/);
  assert.match(LY_NOTE, /第 11 屆第 1–3 會期書面質詢/);
  assert.match(LY_NOTE, /口頭質詢請見發言影片（IVOD）/);
  assert.equal(publisherOf('https://ly.govapi.tw/v2/bill/1'), '立法院（經 OpenFun 立法院 API，CC BY 4.0）');
  assert.equal(publisherOf('https://ivod.ly.gov.tw/Play/Clip/1M/1'), '立法院');
});

// ---------- 新北（V15 已定案第 4 點） ----------

const nwtAtt = (session, meetings, present, leave = 0, duty = 0, url = 'https://ntpbook.ntp.gov.tw/Home/BookAgenda?cBookMdslID=a') => ({
  source_url: url, data: { session, meetings, present, leave, duty, from_lists: true },
});

test('New Taipei is a deep county with a neutral scope note and no department chart', () => {
  assert.ok(DEEP_COUNTIES.has('nwt'));
  const r = RECORDS.nwt;
  assert.equal(r.written, true);
  assert.deepEqual(r.depts, []);
  assert.match(r.noRecord, /第4屆新北市議員個人書面質詢及答復、口頭質詢影片/);
  assert.match(r.writtenBlurb, /掃描檔/);
  assert.doesNotMatch(r.noRecord + r.writtenBlurb, /沒有問政|無問政|未質詢|缺席/);
});

test('New Taipei videos are listed without per-video links and point readers to the video site home', () => {
  const f = { date: '2026-09-03', source_url: NWT_VOD_HOME, data: { video_id: 'v1', link: 'home', session: '第4屆第8次定期會', title: '市政總質詢', group_size: 5 } };
  const html = videoRows([f]);
  assert.match(html, /2026-09-03/);
  assert.match(html, /<span class="dept">第4屆第8次定期會<\/span>/);
  assert.match(html, /市政總質詢/);
  assert.match(html, /本場發言議員 5 位/);
  assert.doesNotMatch(html, /<a |觀看影片/);
  assert.equal(NWT_VOD_HOME, 'https://vod.ntp.gov.tw/VodCloud/index.htm');
  assert.match(RECORDS.nwt.videoBlurb, /新北市議會影音網的單支影片網址無法穩定連結，請至<a href="https:\/\/vod\.ntp\.gov\.tw\/VodCloud\/index\.htm"[^>]*>影音網首頁<\/a>以日期查詢/);
  // 其他縣市的影片列仍有單支連結
  assert.match(videoRows([{ date: '2026-01-01', source_url: 'https://example.org/v', data: { video_id: 'y', clip: true, group_size: 1, title: 't' } }]), /觀看影片/);
});

test('New Taipei attendance shows present, leave and official duty out of collected meetings, with the definition and per-session sources', () => {
  const html = nwtAttendanceBlock([nwtAtt('第4屆第1次定期會', 40, 36, 2, 1, 'https://ntpbook.ntp.gov.tw/Home/BookAgenda?cBookMdslID=b'), nwtAtt('第4屆成立大會', 1, 1)]);
  assert.match(html, /<span>出席<\/span>.*（<span class="num">37<\/span>／<span class="num">41<\/span>）/);
  assert.match(html, /<span>請假<\/span>.*（<span class="num">2<\/span>／<span class="num">41<\/span>）/);
  assert.match(html, /<span>公差／公假<\/span>.*（<span class="num">1<\/span>／<span class="num">41<\/span>）/);
  assert.match(html, /出席 <span class="num">37<\/span>／<span class="num">41<\/span> 次、請假 <span class="num">2<\/span> 次、公差／公假 <span class="num">1<\/span> 次/);
  assert.ok(html.includes(NWT_ATTENDANCE_NOTE));
  assert.match(NWT_ATTENDANCE_NOTE, /出席與請假名單.*公假.*不區分缺席.*詳如簽到簿/);
  assert.match(html, /href="https:\/\/ntpbook\.ntp\.gov\.tw\/Home\/BookAgenda\?cBookMdslID=b"/);
  assert.match(html, /第4屆第1次定期會<\/a>：會議 <span class="num">40<\/span> 次，出席 <span class="num">36<\/span>、請假 <span class="num">2<\/span>、公差／公假 <span class="num">1<\/span>/);
  assert.ok(html.indexOf('第4屆第1次定期會') < html.indexOf('第4屆成立大會'), 'newest session first');
  assert.doesNotMatch(html, /<span>缺席|未列|排名|評分/);
});

test('summary card for New Taipei counts written sessions and videos and uses the list-based attendance block', () => {
  const w = { data: { title: '第6次定期大會書面質詢及答復（掃描檔）', scanned: true } };
  const v = { data: { video_id: 'x', link: 'home', group_size: 5 } };
  const att = [nwtAtt('第4屆第6次定期會', 45, 43, 1)];
  const card = summaryCard({ attendance: att }, { offices: [], inters: [w, v, v], written: [w], videos: [v, v], rec: RECORDS.nwt });
  assert.match(card, /書面質詢及答復 <span class="num">1<\/span> 個會期（掃描檔）、口頭質詢影片 <span class="num">2<\/span> 筆/);
  assert.doesNotMatch(card, /部門分布|出席率|請假率|<span>缺席/);
  assert.match(card, /出席 <span class="num">43<\/span>／<span class="num">45<\/span> 次、請假 <span class="num">1<\/span> 次/);
  // 其他縣市的摘要卡不受影響
  const khh = summaryCard({}, { offices: [], inters: [v], written: [], videos: [v], rec: RECORDS.khh });
  assert.match(khh, /口頭質詢影片 <span class="num">1<\/span> 筆（書面質詢尚未收錄）/);
});

test('Chiayi City councillors from the 2022 results are tagged "2022 當選", never "現任"', () => {
  const counties = new Map([['cyi', { iso: 'cyi', name: '嘉義市' }]]);
  const o = { office: 'cyi_councilor', district_id: 'cyi-council-01', suspended: false, basis: 'cec_2022' };
  assert.equal(candidateTag([o], 'cyi-council-01', counties), '2022 當選');
  assert.equal(candidateTag([o], 'cyi-mayor', counties), '2022 當選嘉義市議員');
  assert.equal(officeTitle({ title: '嘉義市議員', basis: 'cec_2022' }, 'x'), '2022 年當選嘉義市議員');
  assert.equal(officeTitle({ title: '新北市議員' }, 'x'), '新北市議員');
  assert.equal(officeSourceLabel('cyi_councilor', 'cec_2022'), '選舉結果');
});

test('county and home notes describe Chiayi City councillors as 2022 winners', () => {
  const cyi = { iso: 'cyi', name: '嘉義市', councilor_roster: false, councilor_cec_2022: true, councilor_bulletin: true };
  const cha = { iso: 'cha', name: '彰化縣', councilor_roster: true };
  const n = countyNote(cyi);
  assert.match(n, /候選人中的現任嘉義市長與 2022 年當選議員會標示，並收錄 2022 年當選議員的 2022 選舉公報政見與學經歷/);
  assert.doesNotMatch(n, /現任議員/);
  assert.match(homeNote([cha, cyi]), /候選人中的現任縣市長與彰化縣的現任議員、嘉義市的 2022 年當選議員會標示/);
  assert.match(homeNote([cyi]), /候選人中的現任縣市長與嘉義市的 2022 年當選議員會標示/);
});

// ---------- 花蓮（V16 已定案第 6 點） ----------

test('Hualien is a deep county whose summary card counts written questions, oral answers and videos separately', () => {
  assert.ok(DEEP_COUNTIES.has('hua'));
  const r = RECORDS.hua;
  assert.deepEqual(r.depts, []);
  const w = { data: { doc_type: '書面質詢', no_date: true } };
  const o = { data: { doc_type: HUA_ORAL, no_date: true } };
  const t = { data: { doc_type: HUA_TRANSCRIPT, no_date: true } };
  const v = { data: { video_id: 'x', whole: true, group_size: 3 } };
  const card = summaryCard({}, { offices: [], inters: [w, o, o, t, v], written: [w, o, o, t], videos: [v], rec: r });
  assert.match(card, /書面質詢 <span class="num">1<\/span> 筆、口頭質詢答覆 <span class="num">2<\/span> 筆、縣政總質詢影片 <span class="num">1<\/span> 筆/);
  assert.match(card, /第 2 至第 6 次定期大會.*尚未刊出，本站未收錄/);
  assert.doesNotMatch(card, /部門分布|<span>缺席/);
  assert.doesNotMatch(r.noRecord + r.writtenBlurb + r.oralBlurb + r.transcriptBlurb, /沒有問政|無問政|未質詢|缺席/);
});

test('Hualien attendance reuses the list-based block without an official-duty row', () => {
  const att = [nwtAtt('第20屆第6次定期大會', 25, 24, 1, 0, 'https://www.hlcc.gov.tw/upfile/a.pdf#page=16')];
  const html = nwtAttendanceBlock(att, RECORDS.hua.attendance);
  assert.match(html, /出席 <span class="num">24<\/span>／<span class="num">25<\/span> 次、請假 <span class="num">1<\/span> 次（分母/);
  assert.match(html, /第20屆第6次定期大會<\/a>：會議 <span class="num">25<\/span> 次，出席 <span class="num">24<\/span>、請假 <span class="num">1<\/span><\/li>/);
  assert.doesNotMatch(html, /公差／公假|<span>缺席/);
  assert.ok(html.includes(HUA_ATTENDANCE_NOTE));
  assert.ok(!html.includes(NWT_ATTENDANCE_NOTE));
  assert.match(HUA_ATTENDANCE_NOTE, /出席與請假名單.*不區分缺席.*分組審查會議不列入/);
  const card = summaryCard({ attendance: att }, { offices: [], inters: [], written: [], videos: [], rec: RECORDS.hua });
  assert.doesNotMatch(card, /公差／公假/);
});

test('Hualien answer-table rows show the session instead of a date, link to the PDF page and clip runaway titles', () => {
  const f = { date: '2025-10-31', source_url: 'https://www.hlcc.gov.tw/upfile/a.pdf#page=807',
    data: { session: '第20屆第6次定期大會', dept: '原住民行政處', title: '有關補助原住民社工員實施計畫', no_date: true } };
  const html = interpellationRows([f]);
  assert.match(html, /<span class="date">第6次定期大會<\/span>/);
  assert.doesNotMatch(html, /2025-10-31/);
  assert.match(html, /<span class="dept">原住民行政處<\/span>/);
  assert.match(html, /href="https:\/\/www\.hlcc\.gov\.tw\/upfile\/a\.pdf#page=807"[^>]*>有關補助原住民社工員實施計畫</);
  const long = interpellationRows([{ ...f, data: { ...f.data, title: '甲'.repeat(TITLE_MAX + 5) } }]);
  assert.match(long, new RegExp(`>${'甲'.repeat(TITLE_MAX)}…（全文見原檔）<`));
  // 有日期的其他縣市不受影響
  assert.match(interpellationRows([{ date: '2024-01-02', source_url: 'https://x.org/a', data: { title: 't' } }]), /<time class="date" datetime="2024-01-02">2024-01-02<\/time>/);
});

test('Hualien whole-session videos name the askers in that session and say there is no personal start time', () => {
  assert.equal(videoNote({ whole: true, group_size: 3, councillors: ['黃馨', '簡智隆', '傅國淵'] }), '本場質詢議員：黃馨、簡智隆、傅國淵（3 位），未細分到個人');
  assert.equal(videoNote({ whole: true, group_size: 1, councillors: ['甲'] }), '整場影片，未標示本人質詢起點');
  assert.match(RECORDS.hua.videoBlurb, /YouTube.*本人質詢時段未標示.*影片來源：花蓮縣議會/);
});
