// ============================================================
// 부동산릴스 로컬 크롤러 도우미 (선택)
// ------------------------------------------------------------
// 사용자 PC에서 실제 브라우저(Playwright Chromium)로 블로그를 열어
// 렌더링된 본문 텍스트 + 본문 이미지를 data URL로 돌려준다.
// 네이버 등 봇 차단·SPA도 일반 방문자처럼 읽고, 이미지는 이 프로세스가
// 직접 받아 data URL로 넘기므로 브라우저 CORS 문제 없이 ffmpeg에 바로 쓸 수 있다.
//
// 실행: 실행하기.bat (첫 실행 시 자동 설치) 또는 npm i && npm start
// 포트: 8791  (앱이 http://127.0.0.1:8791 로 접속)
// ============================================================
const http = require('http');
const { chromium } = require('playwright');

const PORT = 8791;
const MAX_TEXT_LENGTH = 20000;
const MAX_IMAGES = 20;
const PAGE_TIMEOUT_MS = 30000;

// 앱(estate-reels)과 로컬 개발만 허용 — 이 도우미를 임의 프록시로 악용하지 못하게 막는다
function isAllowedOrigin(origin) {
  if (!origin) return false;
  if (/^https:\/\/estate-reels(--[\w-]+)?\.(web\.app|firebaseapp\.com)$/.test(origin)) return true;
  if (/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) return true;
  return false;
}

let browserPromise = null;
const getBrowser = () => (browserPromise ||= chromium.launch({ headless: true }));

// m.blog.naver.com 형태로 정규화 (본문이 서버 렌더되는 모바일 페이지)
function normalize(url) {
  try {
    const u = new URL(url);
    if (/(^|\.)blog\.naver\.com$/.test(u.hostname)) {
      const id = u.searchParams.get('blogId'); const no = u.searchParams.get('logNo');
      if (id && no) return `https://m.blog.naver.com/${id}/${no}`;
      const m = u.pathname.match(/^\/([^/]+)\/(\d+)/);
      if (m) return `https://m.blog.naver.com/${m[1]}/${m[2]}`;
    }
  } catch { /* keep */ }
  return url;
}

async function fetchPage(rawUrl) {
  const url = normalize(rawUrl);
  const browser = await getBrowser();
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    locale: 'ko-KR', viewport: { width: 1280, height: 900 },
  });
  try {
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS });
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(600);

    const data = await page.evaluate((MAX) => {
      const meta = n => document.querySelector(`meta[property="${n}"],meta[name="${n}"]`)?.content || '';
      const title = meta('og:title') || document.title || '';
      const text = (document.body ? document.body.innerText : '').slice(0, 20000);
      const abs = s => { try { return new URL(s, location.href).href; } catch { return ''; } };
      const urls = new Set();
      const og = meta('og:image'); if (og) urls.add(abs(og));
      document.querySelectorAll('img').forEach(img => {
        const src = img.getAttribute('data-lazy-src') || img.getAttribute('data-src') || img.currentSrc || img.src;
        if (!src) return;
        if ((img.naturalWidth && img.naturalWidth < 300) || /icon|logo|button|blank|profile|emoticon|sticker/i.test(src)) return;
        urls.add(abs(src));
      });
      return { title, text, images: [...urls].filter(Boolean).slice(0, MAX) };
    }, MAX_IMAGES);

    // 이미지를 이 프로세스가 직접 받아 data URL로 (브라우저 CORS 우회)
    const images = [];
    for (const src of data.images) {
      try {
        const resp = await context.request.get(src, { timeout: 15000 });
        if (!resp.ok()) continue;
        const ct = resp.headers()['content-type'] || 'image/jpeg';
        if (!/^image\//.test(ct)) continue;
        const buf = await resp.body();
        if (buf.length < 6000) continue;
        images.push(`data:${ct};base64,${buf.toString('base64')}`);
      } catch { /* skip */ }
      if (images.length >= MAX_IMAGES) break;
    }
    return { title: data.title, text: data.text.slice(0, MAX_TEXT_LENGTH), images };
  } finally {
    await context.close();
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let d = '';
    req.on('data', c => { d += c; if (d.length > 64 * 1024) { reject(new Error('too large')); req.destroy(); } });
    req.on('end', () => resolve(d));
    req.on('error', reject);
  });
}

http.createServer(async (req, res) => {
  const origin = req.headers.origin;
  const cors = {
    'Access-Control-Allow-Origin': isAllowedOrigin(origin) ? origin : 'null',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
  if (req.method === 'OPTIONS') { res.writeHead(204, cors); return res.end(); }
  const send = (s, o) => { res.writeHead(s, { ...cors, 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(o)); };
  try {
    if (req.method === 'GET' && req.url === '/health') return send(200, { ok: true, name: 'estate-reels-local-helper' });
    if (req.method === 'POST' && req.url === '/fetch') {
      if (!isAllowedOrigin(origin)) return send(403, { error: '허용되지 않은 출처입니다.' });
      const body = JSON.parse((await readBody(req)) || '{}');
      const url = String(body.url || '').trim();
      if (!/^https?:\/\//i.test(url)) return send(400, { error: 'http(s) URL이 필요합니다.' });
      console.log(`[fetch] ${url}`);
      const r = await fetchPage(url);
      console.log(`[fetch] 완료 — 본문 ${r.text.length.toLocaleString()}자, 이미지 ${r.images.length}장`);
      return send(200, r);
    }
    send(404, { error: 'Not Found' });
  } catch (err) {
    console.error('[error]', err.message);
    send(500, { error: `읽지 못했습니다: ${err.message}` });
  }
}).listen(PORT, '127.0.0.1', () => {
  console.log('============================================');
  console.log('  부동산릴스 로컬 크롤러 도우미 실행 중');
  console.log(`  http://127.0.0.1:${PORT}`);
  console.log('  이 창을 열어두면 네이버·티스토리 URL의');
  console.log('  본문과 사진을 자동으로 가져올 수 있어요.');
  console.log('============================================');
});

process.on('SIGINT', async () => {
  if (browserPromise) { try { (await browserPromise).close(); } catch {} }
  process.exit(0);
});
