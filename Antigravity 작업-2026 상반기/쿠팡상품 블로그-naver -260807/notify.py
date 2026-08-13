"""
notify.py
텔레그램 알림 — 발행한 글과 구매 링크를 사람에게 보낸다.

설정 (config.json 에 직접 넣으세요. 토큰은 비밀값이라 코드가 받아 적지 않습니다):
    "telegram_bot_token": "123456:ABC-DEF...",
    "telegram_chat_id":   "123456789"

토큰 만들기:
    1) 텔레그램에서 @BotFather 대화 → /newbot → 이름 정하면 토큰이 나온다
    2) 만든 봇과 대화를 한 번 시작(아무 메시지나 전송)
    3) python notify.py chatid  → 내 chat_id 를 찾아 준다
    4) config.json 에 두 값을 넣는다

확인:
    python notify.py test
"""
import os
import sys
import json

try:
    import requests
except ImportError:
    requests = None

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
API = "https://api.telegram.org/bot{token}/{method}"


def _cfg() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def is_configured() -> bool:
    c = _cfg()
    return bool(c.get("telegram_bot_token") and c.get("telegram_chat_id"))


def send(text: str, disable_preview: bool = True) -> bool:
    """
    텔레그램으로 메시지를 보낸다. 설정이 없으면 조용히 False 를 돌려준다.
    알림이 실패했다고 발행 자체를 실패시키지 않는다.
    """
    if requests is None:
        print("[notify] requests 미설치")
        return False
    c = _cfg()
    token, chat = c.get("telegram_bot_token"), c.get("telegram_chat_id")
    if not token or not chat:
        print("[notify] 텔레그램 미설정 — config.json 에 telegram_bot_token / telegram_chat_id 를 넣으세요")
        return False
    try:
        r = requests.post(
            API.format(token=token, method="sendMessage"),
            json={"chat_id": chat, "text": text,
                  "disable_web_page_preview": disable_preview},
            timeout=15,
        )
        if r.status_code == 200:
            return True
        print(f"[notify] 전송 실패 {r.status_code}: {r.text[:120]}")
        return False
    except Exception as e:
        print(f"[notify] 전송 오류: {str(e)[:80]}")
        return False


def notify_published(product: dict, post_title: str, blog_url: str = "",
                     category: str = "") -> bool:
    """
    글을 올린 뒤, 딥링크로 바꿔야 할 상품 링크를 사람에게 보낸다.

    지금 DB 의 affiliate_url 은 추적 코드가 없는 일반 상품 주소라 수수료가 0원이다.
    사람이 파트너스에서 딥링크를 만들어 넣어야 수익이 생긴다.
    """
    pid = product.get("product_id", "")
    url = product.get("affiliate_url") or product.get("detail_url", "")
    is_deep = "link.coupang.com" in url

    lines = [
        "📝 블로그 글 발행 완료",
        f"제목: {post_title}",
    ]
    if category:
        lines.append(f"카테고리: {category}")
    if blog_url:
        lines.append(f"글 주소: {blog_url}")
    lines += ["", f"상품: {product.get('title', '')[:40]}", f"상품ID: {pid}", "", "🔗 상품 링크"]
    lines.append(url)

    if is_deep:
        lines += ["", "✅ 이미 파트너스 딥링크입니다. 추가 작업 없음."]
    else:
        lines += [
            "",
            "⚠️ 이 링크는 추적 코드가 없어 수수료가 0원입니다.",
            "파트너스에서 딥링크를 만든 뒤 아래 명령으로 저장하면",
            "다음 글부터 자동으로 들어갑니다:",
            "",
            f'setlink {pid} <딥링크>',
        ]
    return send("\n".join(lines))


def find_chat_id() -> None:
    """봇과 대화를 시작한 뒤 실행하면 chat_id 를 찾아 준다."""
    c = _cfg()
    token = c.get("telegram_bot_token")
    if not token:
        print("config.json 에 telegram_bot_token 을 먼저 넣으세요.")
        return
    try:
        r = requests.get(API.format(token=token, method="getUpdates"), timeout=15)
        data = r.json()
        if not data.get("ok"):
            print("응답 오류:", str(data)[:150])
            return
        seen = {}
        for u in data.get("result", []):
            msg = u.get("message") or u.get("channel_post") or {}
            ch = msg.get("chat") or {}
            if ch.get("id"):
                seen[ch["id"]] = ch.get("title") or ch.get("username") or ch.get("first_name", "")
        if not seen:
            print("대화 기록이 없습니다. 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
            return
        print("찾은 chat_id:")
        for k, v in seen.items():
            print(f"  {k}   ({v})")
        print("\n위 값을 config.json 의 telegram_chat_id 에 넣으세요.")
    except Exception as e:
        print("오류:", str(e)[:100])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "chatid":
        find_chat_id()
    elif cmd == "test":
        if not is_configured():
            print("텔레그램 미설정입니다.\n")
            print(__doc__)
        else:
            ok = send("✅ 쿠팡 블로그 알림 연결 테스트입니다.")
            print("전송:", "성공" if ok else "실패")
    else:
        print(__doc__)
