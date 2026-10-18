// 分享圖卡：版面計算是純函式（layoutCard，node --test 用假的量字函式測），繪圖與對話框只在瀏覽器執行。
// 圖卡固定淺色、全卡黑灰階（使用者 2026-10-18 定案：不放黨徽、政黨不寫「推薦」）；只有出缺勤用百分比與長條（分母是本人的會議次數），
// 部門長條以本人最多的部門為基準，件數只寫數字：都不和其他人比較。
import { CARD_DIMS, CARD_NOTE, CARD_NEW, SHARE_LABEL, cardContent, shareLinks } from './app.js';

export const FORMATS = {
  story: { w: 1080, h: 1920, label: '限時動態（9:16）' },
  post: { w: 1080, h: 1350, label: '貼文（4:5）' },
};
export const FONT = '"PingFang TC", "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif';
const C = { bg: '#f6f6f4', ink: '#171717', ink2: '#3b3b39', muted: '#5a5a57', line: '#d4d4cf' };
export const SEG_FILLS = ['#171717', '#6e6e69', '#a3a39e', '#d4d4cf', '#ebebe8'];  // 第 4 段起較淺，圖例色塊加框線
const PAD = 64;

export const pctText = (r) => `${(r * 100).toFixed(1)}%`;

// 依寬度斷行：中文逐字、英數連續字元不拆
const CLOSING = /^[）」』〉》，、。；：！？)\]]$/u;

export function wrapText(text, width, measure) {
  const tokens = String(text).match(/[A-Za-z0-9.,'’\-‧]+|\s+|./gu) || [];
  const lines = [];
  let cur = '';
  for (const t of tokens) {
    if (cur && measure(cur + t) > width) {
      // 避頭：右括號與標點不放行首，連同前一個字一起換行（「縣政總質詢紀錄（份」＋「）」）
      const tail = CLOSING.test(t) && [...cur.trimEnd()].length > 1 ? [...cur.trimEnd()].pop() : '';
      lines.push(cur.trimEnd().slice(0, cur.trimEnd().length - tail.length));
      cur = tail + t.trimStart();
    } else cur += t;
  }
  if (cur.trim()) lines.push(cur.trimEnd());
  return lines;
}

// 回傳 { w, h, ops, overflow, scale }；ops 是 rect／text 指令。內容放不下時整體縮小（最小 0.6 倍），議題題目則只放得下的部分。
export function layoutCard(content, format, measure) {
  const { w: W, h: H } = FORMATS[format];
  for (let k = 1; k >= 0.6; k -= 0.05) {
    const r = layoutAt(content, W, H, k, measure);
    // 任何文字超出畫布寬度也算放不下
    const wide = r.ops.some((o) => o.t === 'text' && (o.align === 'right' ? o.x - measure(o.text, o.size, o.weight) < 0
      : o.align === 'center' ? measure(o.text, o.size, o.weight) > W : o.x + measure(o.text, o.size, o.weight) > W));
    if (wide) r.overflow = true;
    if (!r.overflow || k - 0.05 < 0.6) return { ...r, w: W, h: H, scale: Number(k.toFixed(2)) };
  }
  return null;
}

function layoutAt(content, W, H, k, measure) {
  const ops = [];
  const S = (n) => Math.round(n * k);
  const font = (size, weight = 400) => ({ size, weight });
  const width = (t, f) => measure(t, f.size, f.weight);
  const rect = (x, y, w, h, fill) => ops.push({ t: 'rect', x, y, w, h, fill });
  const text = (x, y, s, f, fill, align = 'left') => ops.push({ t: 'text', x, y, text: s, size: f.size, weight: f.weight, fill, align });
  const CW = W - PAD * 2;

  // 刊頭
  const mh = S(120);
  rect(0, 0, W, mh, C.ink);
  text(PAD, Math.round(mh * 0.66), 'civic-lens', font(S(56), 500), C.bg);
  text(W - PAD, Math.round(mh * 0.64), '2026 候選人紀錄卡', font(S(34)), C.bg, 'right');

  // 頁尾（由下往上）：導流條、網址、說明
  const band = S(120);
  rect(0, H - band, W, band, C.ink);
  text(PAD, H - band + Math.round(band * 0.6), content.kind === 'new' ? '看候選人資料 →' : '完整紀錄與原始出處 →', font(S(40), 500), C.bg);
  const foot = [];
  if (content.omitted?.length) foot.push(`本卡未呈現：${content.omitted.join('、')}`);
  if (content.kind === 'records' || content.kind === 'none') foot.push(CARD_NOTE);
  foot.push(`資料來源：${content.sources.join('、')}${content.term ? `（${content.term}，各項收錄期間標在數字下方）` : ''}`);
  foot.push(content.url.replace(/^https?:\/\//, ''));
  const ff = font(S(30));
  const lh = S(44);
  const footLines = foot.flatMap((s) => wrapText(s, CW, (t) => width(t, ff)));
  let fy = H - band - S(36);
  for (const s of [...footLines].reverse()) {
    text(PAD, fy, s, ff, C.muted);
    fy -= lh;
  }
  const bodyBottom = fy - S(24);
  rect(PAD, bodyBottom + S(8), CW, 2, C.line);

  // 身分：選區、姓名＋現任標籤、職稱、政黨
  let y = mh + S(56);
  text(PAD, y + S(36), content.district, font(S(36)), C.muted);
  y += S(60);
  const tf = font(S(38), 500);
  const tagW = content.tag ? width(content.tag, tf) + S(28) : 0;
  // 姓名先縮字級；最小字級仍放不下（原住民族語姓名等）就換行，標籤接在最後一行後面，放不下再另起一行
  let ns = S(fmtOf(W, H) === 'story' ? 128 : 112);
  const withTag = tagW ? tagW + S(24) : 0;
  while (ns > S(72) && width(content.name, font(ns, 500)) + withTag > CW) ns -= 4;
  const names = width(content.name, font(ns, 500)) + withTag > CW ? wrapText(content.name, CW, (t) => width(t, font(ns, 500))) : [content.name];
  names.forEach((s, i) => text(PAD, y + Math.round(ns * (0.88 + i * 1.08)), s, font(ns, 500), C.ink));
  y += Math.round(ns * 1.08 * (names.length - 1));
  if (content.tag) {
    const th = S(60);
    const lastW = width(names.at(-1), font(ns, 500));
    const below = lastW + withTag > CW;
    if (below) y += Math.round(ns * 1.08);
    const tx = below ? PAD : PAD + lastW + S(24);
    const ty = below ? y : y + Math.round(ns * 0.5 - th / 2);
    rect(tx, ty, tagW, th, C.ink);
    rect(tx + 3, ty + 3, tagW - 6, th - 6, C.bg);
    text(tx + S(14), ty + Math.round(th * 0.7), content.tag, tf, C.ink);
    if (below) y += th - Math.round(ns * 1.12) + S(16);
  }
  y += Math.round(ns * 1.12);
  if (content.title) {
    text(PAD, y + S(38), content.title, font(S(38)), C.ink2);
    y += S(56);
  }
  text(PAD, y + S(40), content.party, font(S(40)), C.ink2);
  y += S(68);
  rect(PAD, y, CW, S(10), C.ink);
  y += S(10) + S(44);

  if (content.kind === 'new') {
    const big = font(S(72), 500);
    const lines = String(CARD_NEW).split(/(?<=，)/);
    const mid = Math.round((y + bodyBottom) / 2);
    lines.forEach((s, i) => text(W / 2, mid + (i - (lines.length - 1) / 2) * S(104) + S(26), s, big, C.ink, 'center'));
    rect(W / 2 - S(40), mid + lines.length * S(52) + S(30), S(80), 3, C.ink);
    return { ops, overflow: mid - lines.length * S(52) < y };
  }
  if (content.kind !== 'records') {
    const f = font(S(52), 500);
    for (const s of String(content.text).split(/(?<=，)/).flatMap((c) => wrapText(c, CW, (t) => width(t, f)))) {
      text(PAD, y + S(52), s, f, C.ink);
      y += S(76);
    }
    return { ops, overflow: y > bodyBottom };
  }

  const dims = content.dims;
  const gap = S(44);
  let overflow = false;
  let noTopic = false;
  for (let i = 0; i < dims.length; i++) {
    const d = dims[i];
    if (d.id === 'attendance') y = attendance(d, y) + gap;
    else if (d.id === 'dept') y = dept(d, y) + gap;
    else if (d.id === 'issues') y = issues(d, y);
    else {
      const row = [d];
      while (dims[i + 1] && 'n' in dims[i + 1]) row.push(dims[++i]);
      y = counts(row, y) + gap;
    }
    if (y > bodyBottom) overflow = true;
  }
  return { ops, overflow: overflow || noTopic };

  function attendance(d, top) {
    const pf = font(S(140), 500);
    const pct = pctText(d.rate);
    text(PAD, top + S(124), pct, pf, C.ink);
    text(PAD + width(pct, pf) + S(20), top + S(124), '出席率', font(S(36)), C.muted);
    let yy = top + S(156);
    const bh = S(40);
    let x = PAD;
    d.segs.forEach((s, i) => {
      const w = d.total ? Math.round((CW * s.n) / d.total) : 0;
      if (w) rect(x, yy, Math.min(w, PAD + CW - x), bh, SEG_FILLS[i]);
      x += w;
    });
    yy += bh + S(20);
    const lf = font(S(32));
    const items = [...d.segs.map((s, i) => ({ sw: SEG_FILLS[i], s: `${s.label} ${s.n}` })), { s: `／ ${d.total} 次會議` }];
    let lx = PAD;
    let line = 0;
    for (const it of items) {
      const iw = (it.sw ? S(36) : 0) + width(it.s, lf) + S(28);
      if (lx + iw > PAD + CW && lx > PAD) { lx = PAD; line++; }
      const by = yy + line * S(48);
      if (it.sw) {
        rect(lx, by + S(4), S(26), S(26), it.sw);
        if (SEG_FILLS.indexOf(it.sw) >= 3) { rect(lx, by + S(4), S(26), 2, C.ink2); rect(lx, by + S(28), S(26), 2, C.ink2); }
        lx += S(36);
      }
      text(lx, by + S(28), it.s, lf, C.ink2);
      lx += width(it.s, lf) + S(28);
    }
    yy += (line + 1) * S(48);
    if (d.period) {
      text(PAD, yy + S(28), `收錄期間 ${d.period}`, font(S(28)), C.muted);
      yy += S(42);
    }
    if (d.note) {
      text(PAD, yy + S(28), d.note, font(S(30)), C.muted);
      yy += S(44);
    }
    return yy;
  }

  function counts(row, top) {
    const per = Math.min(row.length, 3);
    const cw = Math.floor(CW / per);
    const lf = font(S(30));
    let yy = top;
    for (let r = 0; r < row.length; r += per) {
      const cells = row.slice(r, r + per);
      const labels = cells.map((c) => wrapText(/）$/.test(c.label) ? c.label.replace(/）$/, `，${c.unit}）`) : `${c.label}（${c.unit}）`, cw - S(28), (t) => width(t, lf)));
      const pf = font(S(26));
      const periods = cells.map((c) => [c.period, c.note].filter(Boolean).flatMap((t) => wrapText(t, cw - S(28), (x) => width(x, pf))));
      const lines = Math.max(...labels.map((l, j) => l.length + periods[j].length));
      const h = S(24) + S(104) + S(16) + lines * S(42) + S(12);
      rect(PAD, yy, CW, 2, C.line);
      cells.forEach((c, j) => {
        const x = PAD + j * cw + (j ? S(20) : 0);
        if (j) rect(PAD + j * cw, yy + S(16), 2, h - S(32), C.line);
        text(x, yy + S(24) + S(96), String(c.n), font(S(110), 500), C.ink);
        labels[j].forEach((s, li) => text(x, yy + S(24) + S(104) + S(16) + S(30) + li * S(42), s, lf, C.muted));
        periods[j].forEach((s, li) => text(x, yy + S(24) + S(104) + S(16) + S(30) + (labels[j].length + li) * S(42), s, pf, C.muted));
      });
      yy += h;
      rect(PAD, yy, CW, 2, C.line);
    }
    return yy;
  }

  function dept(d, top) {
    const lf = font(S(30));
    text(PAD, top + S(30), `質詢部門分布（本人各部門筆數${d.period ? `，${d.period}` : ''}）`, lf, C.muted);
    let yy = top + S(52);
    const cols = d.counts.length > 4 ? 2 : 1;
    const colW = Math.floor((CW - (cols - 1) * S(40)) / cols);
    const labW = Math.max(...d.counts.map(([n]) => width(n, lf))) + S(16);
    const numW = S(64);
    const barW = Math.max(S(40), colW - labW - numW);
    const max = Math.max(1, ...d.counts.map(([, n]) => n));
    const rh = S(46);
    const rows = Math.ceil(d.counts.length / cols);
    d.counts.forEach(([name, n], i) => {
      const c = Math.floor(i / rows);
      const r = i % rows;
      const x = PAD + c * (colW + S(40));
      const by = yy + r * rh;
      text(x, by + S(32), name, lf, C.ink2);
      rect(x + labW, by + S(12), barW, S(20), '#ebebe8');
      if (n) rect(x + labW, by + S(12), Math.max(2, Math.round((barW * n) / max)), S(20), C.ink2);
      text(x + colW, by + S(32), String(n), lf, C.ink, 'right');
    });
    yy += rows * rh;
    if (d.other) {
      text(PAD, yy + S(30), `另有 ${d.other} 筆未分部門（例如市政總質詢）`, font(S(28)), C.muted);
      yy += S(44);
    }
    return yy;
  }

  function issues(d, top) {
    const hf = font(S(30));
    const tf2 = font(S(36));
    text(PAD, top + S(30), `質詢議題｜${d.session}`, hf, C.muted);
    let yy = top + S(48);
    const tail = S(52);
    let shown = 0;
    for (const [i, topic] of d.topics.entries()) {
      const lines = wrapText(`${String(i + 1).padStart(2, '0')}  ${topic}`, CW, (t) => width(t, tf2));
      const need = lines.length * S(50);
      if (yy + need + tail > bodyBottom) break;
      lines.forEach((s, li) => text(PAD, yy + S(40) + li * S(50), s, tf2, C.ink));
      yy += need + S(6);
      shown++;
    }
    // 限動至少放 3 題、貼文至少 1 題（題數不足就整張縮小）；放不完的寫「…共 N 題」
    if (shown < Math.min(d.topics.length, fmtOf(W, H) === 'story' ? 3 : 1)) noTopic = true;
    const end = shown < d.topics.length ? `…共 ${d.topics.length} 題；AI 摘要，經人工審閱` : 'AI 摘要，經人工審閱；以原速記錄為準';
    text(PAD, yy + S(36), end, font(S(28)), C.muted);
    return yy + tail;
  }
}

const fmtOf = (W, H) => (H / W > 1.5 ? 'story' : 'post');

// ---------- 瀏覽器：繪圖、分享對話框 ----------

export function drawCard(canvas, content, fmt) {
  const ctx = canvas.getContext('2d');
  const measure = (t, size, weight = 400) => { ctx.font = `${weight} ${size}px ${FONT}`; return ctx.measureText(t).width; };
  const lay = layoutCard(content, fmt, measure);
  canvas.width = lay.w;
  canvas.height = lay.h;
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, lay.w, lay.h);
  ctx.textBaseline = 'alphabetic';
  for (const op of lay.ops) {
    ctx.fillStyle = op.fill;
    if (op.t === 'rect') ctx.fillRect(op.x, op.y, op.w, op.h);
    else {
      ctx.font = `${op.weight} ${op.size}px ${FONT}`;
      ctx.textAlign = op.align;
      ctx.fillText(op.text, op.x, op.y);
    }
  }
  return lay;
}

// 預覽圖的替代文字：照圖卡上的文字順序（讀螢幕的使用者也能知道卡上的數字與議題）
export const cardAlt = (lay) => lay.ops.filter((o) => o.t === 'text').map((o) => o.text).join('，');

const escHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const dimLabel = (d) => ('n' in d ? d.label : CARD_DIMS[d.id]);

export function openShareDialog(model) {
  const dlg = document.createElement('dialog');
  dlg.className = 'support share';
  dlg.setAttribute('aria-labelledby', 'share-h');
  const pick = model.kind === 'records' && model.dims.length > 1;
  dlg.innerHTML = `<form method="dialog"><button class="more">關閉</button></form>
    <h2 id="share-h">分享圖卡</h2>
    <fieldset class="share-fmt"><legend>尺寸</legend>
      ${Object.entries(FORMATS).map(([k, f], i) => `<label><input type="radio" name="fmt" value="${k}"${i ? '' : ' checked'}> ${f.label}</label>`).join('')}
    </fieldset>
    ${pick ? `<fieldset class="share-dims"><legend>圖卡呈現的項目</legend>
      ${model.dims.map((d) => `<label><input type="checkbox" name="dim" value="${d.id}" checked> ${escHtml(dimLabel(d))}</label>`).join('')}
      <p class="muted small">沒有勾選的項目，圖卡上會註明「本卡未呈現」。</p></fieldset>` : ''}
    <img class="share-preview" alt="">
    <p class="share-actions"></p>
    <p class="muted small share-hint" hidden>如果無法直接分享，請長按上方圖片儲存，再到 Instagram、Threads 或 LINE 發布。</p>`;
  document.body.append(dlg);
  const img = dlg.querySelector('.share-preview');
  const actions = dlg.querySelector('.share-actions');
  const hint = dlg.querySelector('.share-hint');
  const canvas = document.createElement('canvas');
  let url = '';
  let file = null;

  const selected = () => (pick ? new Set([...dlg.querySelectorAll('input[name=dim]:checked')].map((x) => x.value)) : null);
  const fmt = () => dlg.querySelector('input[name=fmt]:checked').value;
  async function render() {
    const f = fmt();
    const lay = drawCard(canvas, cardContent(model, selected()), f);
    const blob = await new Promise((res) => canvas.toBlob(res, 'image/png'));
    if (url) URL.revokeObjectURL(url);
    url = URL.createObjectURL(blob);
    const name = `civic-lens-${model.name}-${f}.png`;
    file = new File([blob], name, { type: 'image/png' });
    img.src = url;
    img.alt = `分享圖卡預覽（${FORMATS[f].label}）：${cardAlt(lay)}`;
    const canShare = Boolean(navigator.canShare?.({ files: [file] }));
    const text = `${model.name}｜${model.district}｜civic-lens 候選人紀錄`;
    actions.innerHTML = `${canShare ? `<button type="button" class="more" data-share>${SHARE_LABEL}</button>` : ''}
      <a class="more" href="${url}" download="${escHtml(name)}">儲存圖片</a>
      ${canShare ? '' : shareLinks(model.url, text).map(([n, u]) => `<a class="more" href="${escHtml(u)}" target="_blank" rel="noopener">分享連結到 ${n}</a>`).join('')}`;
    hint.hidden = canShare || !matchMedia('(pointer: coarse)').matches;
    actions.querySelector('[data-share]')?.addEventListener('click', async () => {
      try {
        await navigator.share({ files: [file] });  // 只帶圖：網址已印在圖上，帶文字時部分 App（IG）會略過圖片
      } catch (e) {
        if (e?.name !== 'AbortError') hint.hidden = false;
      }
    });
  }
  dlg.addEventListener('change', render);
  dlg.addEventListener('close', () => { if (url) URL.revokeObjectURL(url); dlg.remove(); });
  dlg.showModal();
  return (document.fonts?.ready || Promise.resolve()).then(render);
}
