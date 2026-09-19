"""
쿠팡 파트너스 Open API — 딥링크를 로그인 없이 만든다.

이게 왜 큰가:
지금까지 딥링크는 브라우저로 파트너스에 로그인해 상품을 검색하고 '링크 생성'을 누르는
방식이었다. 로그인은 사람만 할 수 있고(비밀번호는 코드가 다루지 않는다), 인증 쿠키가
세션 쿠키라 실행마다 다시 필요했다. 상품 매칭도 검색 결과에서 골라야 해서 10%쯤 실패했다.
API 는 그 전부를 없앤다 — 상품 URL 을 주면 딥링크가 돌아온다.

인증: HMAC-SHA256 서명을 Authorization 헤더에 넣는다.
  message   = signed-date + METHOD + PATH + QUERY
  signature = HMAC-SHA256(secret_key, message) 를 16진수로
  헤더      = CEA algorithm=HmacSHA256, access-key=..., signed-date=..., signature=...
  signed-date 는 GMT 기준 '%y%m%dT%H%M%SZ' 다. 로컬 시각을 쓰면 서명이 어긋난다.

키는 config.json 의 coupang_access_key / coupang_secret_key 에 둔다.
"""
import hashlib
import hmac
import io
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOMAIN = "https://api-gateway.coupang.com"
DEEPLINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"


def _cfg() -> dict:
    try:
        return json.load(io.open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
    except Exception:
        return {}


def has_keys() -> bool:
    c = _cfg()
    return bool(c.get("coupang_access_key") and c.get("coupang_secret_key"))


def _authorization(method: str, path: str, query: str = "") -> str:
    c = _cfg()
    access, secret = c.get("coupang_access_key", ""), c.get("coupang_secret_key", "")
    if not access or not secret:
        raise RuntimeError(
            "config.json 에 coupang_access_key / coupang_secret_key 가 없습니다.\n"
            "  python set_coupang_api.py 로 넣으세요.")
    # 반드시 GMT. 로컬 시각을 쓰면 서명 불일치로 401 이 난다.
    signed_date = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = signed_date + method + path + query
    signature = hmac.new(secret.encode("utf-8"),
                         message.encode("utf-8"), hashlib.sha256).hexdigest()
    return (f"CEA algorithm=HmacSHA256, access-key={access}, "
            f"signed-date={signed_date}, signature={signature}")


def _post(path: str, payload: dict, timeout: int = 20) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DOMAIN + path, data=body, method="POST",
        headers={"Authorization": _authorization("POST", path),
                 "Content-Type": "application/json;charset=UTF-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {detail}") from None


def make_deeplinks(urls: list, sub_id: str = "") -> dict:
    """
    쿠팡 상품 URL 여러 개를 딥링크로 바꾼다. {원본URL: 딥링크} 를 돌려준다.

    한 번에 여러 개를 보낼 수 있어 브라우저 방식보다 비교가 안 되게 빠르다.
    실패한 항목은 결과에서 빠진다 — 호출자가 확인해야 한다.
    """
    urls = [u for u in (urls or []) if u]
    if not urls:
        return {}
    payload = {"coupangUrls": urls}
    if sub_id:
        payload["subId"] = sub_id          # 채널별 실적 구분용(선택)

    res = _post(DEEPLINK_PATH, payload)
    out = {}
    for item in (res.get("data") or []):
        src = item.get("originalUrl") or ""
        link = item.get("shortenUrl") or item.get("landingUrl") or ""
        if src and "link.coupang.com" in link:
            out[src] = link
    return out


def selftest() -> int:
    """키가 살아 있는지, 딥링크가 실제로 나오는지 확인한다."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 58)
    print("  쿠팡 파트너스 API 점검")
    print("=" * 58)
    if not has_keys():
        print("  ✘ config.json 에 키가 없습니다.")
        print("    python set_coupang_api.py 로 넣으세요.")
        return 1
    c = _cfg()
    print(f"  access key: {c['coupang_access_key'][:8]}... "
          f"(secret {len(c['coupang_secret_key'])}자)")

    import sqlite3
    conn = sqlite3.connect(os.path.join(BASE_DIR, "price_history.db"))
    row = conn.execute(
        "SELECT product_id, title, detail_url FROM products "
        "WHERE is_real=1 AND detail_url<>'' LIMIT 1").fetchone()
    conn.close()
    if not row:
        print("  ✘ 시험할 상품이 DB 에 없습니다.")
        return 1
    print(f"  시험 상품: {row[1][:40]}")

    try:
        got = make_deeplinks([row[2]])
    except Exception as e:
        print(f"  ✘ 호출 실패: {str(e)[:200]}")
        print()
        print("  자주 나오는 원인:")
        print("    401  키가 틀렸거나 signed-date 가 GMT 가 아님")
        print("    403  승인 대기 중이거나 API 사용 권한이 없음")
        return 1

    if not got:
        print("  ✘ 응답은 왔으나 딥링크가 비어 있습니다.")
        return 1
    for k, v in got.items():
        print(f"  ✅ {v}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
