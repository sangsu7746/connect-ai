// ============================================================
// Ad Studio 로컬 크롤러 도우미
// ------------------------------------------------------------
// 사용자 PC에서 실제 브라우저(Playwright Chromium)로 페이지를 열어
// 렌더링 완료된 본문 텍스트를 돌려준다. 서버/AI 크롤러가 차단당하는
// 사이트(네이버 스마트스토어 등)와 SPA도 일반 방문자처럼 읽을 수 있다.
//
// 실행: 실행하기.bat (첫 실행 시 자동 설치) 또는 npm run setup && npm start
// 포트: 8791 (Ad Studio 웹이 http://127.0.0.1:8791 로 접속)
// ============================================================
const http = require('http');
const { chromium } = require('playwright');

const PORT = 8791;
const MAX_TEXT_LENGTH = 20000;
const PAGE_TIMEOUT_MS = 30000;

// Ad Studio 웹앱만 허용 — 다른 사이트가 이 도우미를 프록시로 악용하지 못하게 막는다
function isAllowedOrigin(origin) {
  if (!origin) return false;
  if (/^https:\/\/headjim-adstudio(--[\w-]+)?\.(web\.app|firebaseapp\.com)$/.test(origin)) return true;
  if (/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) return true;
  return false;
}

let browserPromise = null;
function getBrowser() {
  if (!browserPromise) {
    browserPromise = chromium.launch({ headless: true });
  }
  return browserPromise;
}

async function fetchPageText(url) {
  const browser = await getBrowser();
  const context = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    locale: 'ko-KR',
    viewport: { width: 1280, height: 900 },
  });
  try {
    const page = await context.newPage();
    // 텍스트 추출에 불필요한 무거운 리소스는 건너뛴다 (속도·트래픽 절약)
    await page.route('**/*', route => {
      const type = route.request().resourceType();
      if (type === 'image' || type === 'media' || type === 'font') return route.abort();
      return route.continue();
    });

    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS });
    // SPA가 그려질 시간을 준다 — networkidle은 광고 스크립트 때문에 영영 안 올 수 있어 짧게 제한
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(500);

    const result = await page.evaluate(() => {
      const meta = name =>
        document.querySelector(`meta[property="${name}"], meta[name="${name}"]`)?.content || '';
      return {
        title: document.title || '',
        ogTitle: meta('og:title'),
        ogDescription: meta('og:description') || meta('description'),
        bodyText: document.body ? document.body.innerText : '',
      };
    });

    const combined = [
      result.title,
      result.ogTitle && result.ogTitle !== result.title ? result.ogTitle : '',
      result.ogDescription,
      '',
      result.bodyText,
    ]
      .filter(Boolean)
      .join('\n')
      .replace(/\n{3,}/g, '\n\n')
      .slice(0, MAX_TEXT_LENGTH);

    return { title: result.title, text: combined };
  } finally {
    await context.close();
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', chunk => {
      data += chunk;
      if (data.length > 64 * 1024) {
        reject(new Error('요청 본문이 너무 큽니다.'));
        req.destroy();
      }
    });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  const origin = req.headers.origin;
  const corsHeaders = {
    'Access-Control-Allow-Origin': isAllowedOrigin(origin) ? origin : 'null',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  if (req.method === 'OPTIONS') {
    res.writeHead(204, corsHeaders);
    return res.end();
  }

  const send = (status, obj) => {
    res.writeHead(status, { ...corsHeaders, 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(obj));
  };

  try {
    if (req.method === 'GET' && req.url === '/health') {
      return send(200, { ok: true, name: 'adstudio-local-helper', version: '1.0.0' });
    }

    if (req.method === 'POST' && req.url === '/fetch') {
      if (!isAllowedOrigin(origin)) {
        return send(403, { error: '허용되지 않은 출처입니다.' });
      }
      const body = JSON.parse((await readBody(req)) || '{}');
      const url = String(body.url || '').trim();
      if (!/^https?:\/\//i.test(url)) {
        return send(400, { error: 'http(s) URL이 필요합니다.' });
      }
      console.log(`[fetch] ${url}`);
      const result = await fetchPageText(url);
      console.log(`[fetch] 완료 — ${result.text.length.toLocaleString()}자 추출`);
      return send(200, result);
    }

    send(404, { error: 'Not Found' });
  } catch (err) {
    console.error('[error]', err.message);
    send(500, { error: `페이지를 읽지 못했습니다: ${err.message}` });
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log('============================================');
  console.log('  Ad Studio 로컬 크롤러 도우미 실행 중');
  console.log(`  http://127.0.0.1:${PORT}`);
  console.log('  이 창을 열어두면 Ad Studio의 URL 분석이');
  console.log('  네이버·쿠팡·SPA 페이지도 읽을 수 있어요.');
  console.log('  종료: 이 창을 닫거나 Ctrl+C');
  console.log('============================================');
});

process.on('SIGINT', async () => {
  if (browserPromise) {
    try { (await browserPromise).close(); } catch { /* 무시 */ }
  }
  process.exit(0);
});
