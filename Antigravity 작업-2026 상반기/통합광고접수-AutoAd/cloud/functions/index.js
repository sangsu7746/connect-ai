// ============================================================
//  loanintake — 소비자 대출 상담 접수 수신함  (AutoAd)
//  · loanIntakeSubmit : 공개. 접수폼이 호출 → Firestore 저장
//  · loanIntakePull   : 비공개(토큰). 사무실 PC가 미처리 리드를 가져가 대출앱에 등록
//  ⚠ 함수명은 전역 유일(loanIntake 접두사). codebase=loanintake 로 분리 배포하여
//    기존 함수(printcraft/imgtools/오마주 등)를 덮어쓰지 않는다.
//    배포: firebase deploy --only functions:loanintake,hosting:loanintake
// ============================================================
const { onRequest } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");

// ⚠ firebase-admin 은 최상단에서 부르지 않는다.
//   배포 시 CLI 가 10초 안에 모듈을 읽어 함수 목록을 파악해야 하는데,
//   이 환경에서는 최상단 require 만으로 27초가 걸려 배포가 실패했다.
//   실제 요청이 들어올 때 한 번만 불러오면 배포도 되고 콜드스타트도 짧아진다.
let _admin = null;
let _db = null;
function fb() {
  if (!_admin) {
    _admin = require("firebase-admin");
    if (!_admin.apps.length) _admin.initializeApp();
  }
  return _admin;
}
function store() {
  if (!_db) _db = fb().firestore();
  return _db;
}
function stamp() {
  return fb().firestore.FieldValue.serverTimestamp();
}

const COLLECTION = "loanLeads";
const PULL_TOKEN = defineSecret("LOAN_PULL_TOKEN"); // 사무실 PC 인증용

const MAX = { name: 40, phone: 30, amount: 40, collateral: 40, source: 80, utm: 80 };
const clip = (v, n) => String(v == null ? "" : v).trim().slice(0, n);

// 한국 휴대폰/일반 전화 최소 형태 검증 (숫자 9~11자리)
function validPhone(p) {
  return /^[0-9]{9,11}$/.test(String(p).replace(/[^0-9]/g, ""));
}

// ── 공개: 접수 제출 ─────────────────────────────────────────
exports.loanIntakeSubmit = onRequest(
  { region: "us-central1", cors: true, maxInstances: 10 },
  async (req, res) => {
    if (req.method === "OPTIONS") return res.status(204).send("");
    if (req.method !== "POST") return res.status(405).json({ error: "POST only" });

    try {
      const b = req.body || {};

      // 봇 차단: 사람에게 보이지 않는 필드가 채워졌으면 조용히 성공 처리
      if (clip(b.company_website, 100)) {
        console.log("[intake] honeypot 차단");
        return res.json({ ok: true });
      }
      if (b.consent !== true) {
        return res.status(400).json({ error: "개인정보 수집·이용 동의가 필요합니다." });
      }
      const name = clip(b.name, MAX.name);
      const phone = clip(b.phone, MAX.phone);
      if (!name) return res.status(400).json({ error: "이름을 입력해 주세요." });
      if (!validPhone(phone)) return res.status(400).json({ error: "연락처를 확인해 주세요." });

      // ⚠ 주민등록번호 등 민감정보는 수집하지 않는다(폼·스키마 모두 미포함).
      const doc = {
        name,
        phone,
        amount: clip(b.amount, MAX.amount),
        collateral: clip(b.collateral, MAX.collateral),
        source_channel: clip(b.source_channel, MAX.source),
        utm: clip(b.utm, MAX.utm),
        consent_at: stamp(),
        created_at: stamp(),
        status: "pending", // pending → pulled (사무실 PC가 가져감)
      };
      const ref = await store().collection(COLLECTION).add(doc);
      console.log(`[intake] 접수 저장 ${ref.id} / 유입 ${doc.source_channel || "-"}`);
      return res.json({ ok: true, id: ref.id });
    } catch (e) {
      console.error("[intake] 저장 실패:", e);
      return res.status(500).json({ error: "접수 처리 중 오류가 발생했습니다." });
    }
  }
);

// ── 비공개: 사무실 PC가 미처리 리드를 가져감 ────────────────
//  전달 방식: 빌려주기(leasing) → PC가 받았다고 확인(ack) → 확정(pulled)
//
//  ⚠ 예전에는 넘겨주는 즉시 pulled 로 확정했다. 그러면 커밋과 응답 사이에
//    네트워크가 끊길 때 리드가 복구 수단 없이 사라진다(손님은 접수한 줄 알고 기다림).
//    지금은 확인을 못 받으면 LEASE_MIN 뒤에 다시 배달한다.
//    → 같은 리드가 두 번 배달될 수 있다. 받는 쪽이 cloud_id 로 걸러낸다(cloud_sync.py).
const LEASE_MIN = 10; // 이 시간 안에 확인이 안 오면 재배달

function toLead(d) {
  const v = d.data();
  return {
    id: d.id,
    name: v.name,
    phone: v.phone,
    amount: v.amount || "",
    collateral: v.collateral || "",
    source_channel: v.source_channel || "",
    utm: v.utm || "",
    // 실제 접수 시각 — PC 동기화 시각과 다르므로 반드시 함께 내려준다
    created_at: v.created_at ? v.created_at.toDate().toISOString() : null,
    consent_at: v.consent_at ? v.consent_at.toDate().toISOString() : null,
  };
}

function authed(req) {
  const auth = req.get("authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  return token && token === PULL_TOKEN.value();
}

exports.loanIntakePull = onRequest(
  { region: "us-central1", secrets: [PULL_TOKEN], maxInstances: 5 },
  async (req, res) => {
    if (!authed(req)) return res.status(401).json({ error: "unauthorized" });
    try {
      const limit = Math.min(parseInt(req.query.limit, 10) || 50, 200);
      // ⚠ orderBy 를 쓰면 (status + created_at) 복합 인덱스가 필요해진다.
      //   공용 프로젝트의 인덱스 설정을 건드리지 않으려고 정렬은 아래에서 메모리로 처리.
      const pend = await store()
        .collection(COLLECTION)
        .where("status", "==", "pending")
        .limit(limit)
        .get();

      const docs = pend.docs.slice();

      // 확인을 못 받은 채 빌려준 지 오래된 건은 다시 배달 대상에 넣는다.
      // (PC가 받다가 죽었거나 응답이 유실된 경우)
      if (docs.length < limit) {
        const cutoff = Date.now() - LEASE_MIN * 60 * 1000;
        const lease = await store()
          .collection(COLLECTION)
          .where("status", "==", "leasing")
          .limit(limit - docs.length)
          .get();
        lease.forEach((d) => {
          const at = d.data().lease_at;
          // lease_at 이 없으면(이전 버전 잔여) 만료로 간주해 회수한다
          const ms = at && at.toDate ? at.toDate().getTime() : 0;
          if (ms < cutoff) docs.push(d);
        });
      }

      const leads = [];
      const batch = store().batch();
      docs.forEach((d) => {
        leads.push(toLead(d));
        batch.update(d.ref, {
          status: "leasing",
          lease_at: stamp(),
        });
      });
      // ⚠ 여기서 실패해도 문서는 pending/만료leasing 으로 남아 다음에 다시 배달된다.
      if (leads.length) await batch.commit();
      leads.sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
      console.log(`[intake] pull ${leads.length}건 대여`);
      return res.json({ ok: true, count: leads.length, leads });
    } catch (e) {
      console.error("[intake] pull 실패:", e);
      return res.status(500).json({ error: "pull failed" });
    }
  }
);

// ── 공개: 광고 링크 클릭 추적 후 실제 목적지로 보냄 ──────────
//  광고 본문의 링크를 이 주소로 만들면, 클릭이 기록된 뒤 목적지로 넘어간다.
//  (링크를 서비스 사이트로 직행시키면 몇 명이 눌렀는지 알 방법이 없다)
//
//  형태: /r?c=<creative_id>&ch=<channel_key>&u=<encodeURIComponent(목적지)>
//
//  ⚠ 열린 리다이렉트가 되지 않게 목적지 도메인을 화이트리스트로 제한한다.
//    아무 주소로나 보내주면 피싱에 도용된다.
const ALLOW_HOSTS = [
  "headjim-loan.web.app", "headjim-ink.web.app", "headjim-pod.web.app",
  "headjim-photomagic.web.app", "headjim-petportrait.web.app",
  "headjim-headshot.web.app", "headjim-stickerme.web.app",
  "headjim-color.web.app", "headjim-ai.web.app", "headjim-web.web.app",
  "ad-studio-app.web.app", "memoryfilm.web.app", "wallpreview-web.web.app",
  "mirizip.com", "www.mirizip.com", "headjim.com", "www.headjim.com",
];

//  두 번째 형태(채널별 추적 경로): https://<우리사이트>/t/<캠페인>-<채널>
//    콘텐츠형 글은 본문에 링크를 나열하지 않는다. cloudfunctions.net 주소가
//    보이는 순간 광고로 읽히기 때문이다. 그래서 우리 사이트의 짧은 경로를 적고,
//    호스팅 rewrite 가 이 함수로 넘긴다.
//    이때 목적지는 '방금 눌린 그 사이트의 첫 화면'이다 → u 파라미터가 없고,
//    따라서 열린 리다이렉트 통로 자체가 생기지 않는다(Host 는 화이트리스트로 확인).
const TRACK_PATH_RE = /^\/t\/([0-9]{1,9}-[0-9]{1,9})\/?$/;

exports.adClick = onRequest(
  { region: "us-central1", maxInstances: 20 },
  async (req, res) => {
    const q = req.query || {};
    const raw = String(q.u || "");
    let dest = null;
    let key = clip(q.c, 40);
    let chan = clip(q.ch, 80);

    const hit = TRACK_PATH_RE.exec(String(req.path || ""));
    if (hit) {
      // 경로 방식 — Host 가 우리 것일 때만 그 사이트로 되돌린다.
      const host = String(req.hostname || "").toLowerCase();
      // ref 는 착지 페이지가 유입 채널을 알 수 있게 남긴다(없어도 동작엔 지장 없음).
      if (ALLOW_HOSTS.includes(host)) dest = `https://${host}/?ref=${hit[1]}`;
      key = hit[1];
      chan = chan || `ch_${hit[1].split("-")[1]}`;
    } else {
      try {
        const u = new URL(raw);
        if ((u.protocol === "https:" || u.protocol === "http:") &&
            ALLOW_HOSTS.includes(u.hostname)) {
          dest = u.toString();
        }
      } catch (e) { /* 잘못된 주소 */ }
    }

    // 목적지가 이상하면 기록만 하고 홈으로 — 아무 데나 보내지 않는다.
    const fallback = "https://headjim.com";
    try {
      await store().collection("adClicks").add({
        creative_id: key,
        channel: chan,
        dest: dest || "",
        bad_dest: dest ? "" : (hit ? String(req.hostname || "") : raw).slice(0, 200),
        ua: clip(req.get("user-agent"), 200),
        at: stamp(),
      });
    } catch (e) {
      console.error("[adClick] 기록 실패:", e);   // 기록 실패가 이동을 막아선 안 된다
    }
    res.set("Cache-Control", "no-store");
    return res.redirect(302, dest || fallback);
  }
);

// ── 비공개: PC가 클릭 기록을 회수 ───────────────────────────
exports.adClickPull = onRequest(
  { region: "us-central1", secrets: [PULL_TOKEN], maxInstances: 5 },
  async (req, res) => {
    if (!authed(req)) return res.status(401).json({ error: "unauthorized" });
    try {
      const limit = Math.min(parseInt(req.query.limit, 10) || 500, 2000);
      const snap = await store().collection("adClicks")
        .where("synced", "==", null).limit(limit).get()
        .catch(() => null);
      // synced 필드가 없는 문서를 못 잡는 환경이 있어 전체에서 걸러 쓴다
      const src = snap && !snap.empty ? snap
        : await store().collection("adClicks").limit(limit).get();
      const rows = [];
      const batch = store().batch();
      src.forEach((d) => {
        const v = d.data();
        if (v.synced) return;
        rows.push({
          id: d.id,
          creative_id: v.creative_id || "",
          channel: v.channel || "",
          at: v.at && v.at.toDate ? v.at.toDate().toISOString() : null,
        });
        batch.update(d.ref, { synced: true });
      });
      if (rows.length) await batch.commit();
      return res.json({ ok: true, count: rows.length, clicks: rows });
    } catch (e) {
      console.error("[adClick] pull 실패:", e);
      return res.status(500).json({ error: "pull failed" });
    }
  }
);

// ── 비공개: PC가 '받았다'고 확인 → 확정 ─────────────────────
//  PC 는 원본을 디스크에 저장한 뒤에 이걸 부른다. 그 전에 부르면 안 된다.
exports.loanIntakeAck = onRequest(
  { region: "us-central1", secrets: [PULL_TOKEN], maxInstances: 5 },
  async (req, res) => {
    if (!authed(req)) return res.status(401).json({ error: "unauthorized" });
    if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
    try {
      const ids = Array.isArray((req.body || {}).ids) ? req.body.ids : [];
      if (!ids.length) return res.json({ ok: true, count: 0 });
      if (ids.length > 200) return res.status(400).json({ error: "too many ids" });

      const batch = store().batch();
      ids.forEach((id) => {
        batch.update(store().collection(COLLECTION).doc(String(id)), {
          status: "pulled",
          pulled_at: stamp(),
        });
      });
      await batch.commit();
      console.log(`[intake] ack ${ids.length}건 확정`);
      return res.json({ ok: true, count: ids.length });
    } catch (e) {
      console.error("[intake] ack 실패:", e);
      return res.status(500).json({ error: "ack failed" });
    }
  }
);
