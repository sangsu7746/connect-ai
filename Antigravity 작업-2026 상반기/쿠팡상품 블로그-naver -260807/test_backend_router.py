# 오프라인 검증 — 네트워크/브라우저 없이 라우팅 규칙과 판정만 확인한다.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend_router import Attempt, run_chain, pick, ordered_backends, summarize
import coupang_live_collector as C

fail = []
def eq(name, got, want):
    if got != want:
        fail.append(f"{name}: got={got!r} want={want!r}")
    print(("  OK  " if got == want else "  FAIL") + f" {name} -> {got!r}")

print("[1] ordered_backends — override")
eq("기본 순서", ordered_backends(["a", "b", "c"]), ["a", "b", "c"])
eq("b를 앞으로", ordered_backends(["a", "b", "c"], override="b"), ["b", "a", "c"])
eq("모르는 이름은 무시", ordered_backends(["a", "b"], override="zzz"), ["a", "b"])

print("\n[2] 두 단계 판정 — 첫 응답이 아니라 첫 완전성공이 이긴다")
calls = []
def mk(name, status):
    def f():
        calls.append(name)
        return Attempt(status=status, data={"from": name})
    return f
atts = run_chain(["x", "y", "z"], {"x": mk("x", "partial"), "y": mk("y", "ok"), "z": mk("z", "ok")})
eq("partial에서 안 멈춤", calls, ["x", "y"])          # z 는 y가 ok라 실행 안 됨
eq("채택은 ok", pick(atts).data["from"], "y")

print("\n[3] ok 없으면 partial 채택 / 전부 실패면 None")
atts2 = run_chain(["x", "y"], {"x": mk("x", "blocked"), "y": mk("y", "partial")})
eq("partial 채택", pick(atts2).data["from"], "y")
atts3 = run_chain(["x"], {"x": mk("x", "blocked")})
eq("전부 실패", pick(atts3), None)

print("\n[4] 예외/None 핸들러가 체인을 끊지 않는다")
def boom(): raise RuntimeError("터짐")
def unavailable(): return None
atts4 = run_chain(["b", "u", "y"], {"b": boom, "u": unavailable, "y": mk("y", "ok")})
eq("예외 후에도 계속", pick(atts4).data["from"], "y")
eq("None은 기록 안 함", [a.backend for a in atts4], ["b", "y"])
print("   요약:", summarize(atts4))

print("\n[5] classify_detail — '열렸다'와 '왔다'를 구분한다")
eq("제목없음=blocked", C.classify_detail({"title": ""}), "blocked")
eq("가격0=partial", C.classify_detail({"title": "티", "current_price": 0, "thumbnails": ["u"]}), "partial")
eq("이미지0=partial", C.classify_detail({"title": "티", "current_price": 1000}), "partial")
eq("둘다있음=ok", C.classify_detail({"title": "티", "current_price": 1000, "detail_images": ["u"]}), "ok")

print("\n[6] parse_product_url")
eq("숫자ID", C.parse_product_url("12345")[1], "https://www.coupang.com/vp/products/12345")
eq("데스크톱URL", C.parse_product_url("https://www.coupang.com/vp/products/999?itemId=1")[0], "999")
eq("모바일URL", C.parse_product_url("https://m.coupang.com/vm/products/777")[0], "777")
try:
    C.parse_product_url("https://naver.com/x"); fail.append("잘못된 URL이 통과됨")
except ValueError:
    print("  OK   쿠팡 아닌 URL 거부")

print("\n[7] jina 파서 — 실제 응답 모양의 텍스트로 (네트워크 없음)")
sample = """Title: 빙그레 바나나맛우유 240ml x 24개 - 쿠팡!
URL Source: https://www.coupang.com/vp/products/123
Markdown Content:
88%
18,670원
(100ml당 156원)
167,700원
1,234 개 상품평
한 달간 9,000개 이상 구매했어요
![대표](https://thumbnail6.coupangcdn.com/thumbnails/remote/230x230ex/image/x.jpg)
![상세](https://image.coupangcdn.com/image/displayitem/a/b/c.jpg)
![로고](https://thumbnail6.coupangcdn.com/thumbnails/remote/100x100ex/image/logo.png)
""" + "x" * 400

class R:  # requests.get 대역
    status_code, text = 200, sample
C_req = type(sys)("requests"); C_req.get = lambda *a, **k: R()
sys.modules["requests"] = C_req

att = C._bk_jina("https://www.coupang.com/vp/products/123")
d = att.data
eq("상태", att.status, "ok")
eq("제목에서 '- 쿠팡!' 제거", d["title"], "빙그레 바나나맛우유 240ml x 24개")
eq("할인률", d["discount_rate"], 88)
eq("현재가", d["current_price"], 18670)
eq("정가", d["original_price"], 167700)
eq("리뷰수", d["review_count"], 1234)
eq("상세이미지", d["detail_images"], ["https://image.coupangcdn.com/image/displayitem/a/b/c.jpg"])
eq("썸네일 고해상도 치환", d["thumbnails"],
   ["https://thumbnail6.coupangcdn.com/thumbnails/remote/1000x1000ex/image/x.jpg"])  # 로고 제외됨

print("\n[8] 차단 응답은 blocked 로")
R.text = "요청하신 페이지의 사용권한이 없습니다" + "y" * 500
eq("차단 감지", C._bk_jina("https://www.coupang.com/vp/products/1").status, "blocked")

print("\n" + ("=" * 50))
print("실패 " + str(len(fail)) + "건" + ((":\n  " + "\n  ".join(fail)) if fail else " — 전부 통과"))
sys.exit(1 if fail else 0)
