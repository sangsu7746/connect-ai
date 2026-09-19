/**
 * 예외 메시지가 사용자 화면에 그대로 보여줄 만한지 판단해서 그렇지 않으면 fallback 문구로
 * 대체한다.
 *
 * ⚠️ 우리 코드가 명시적으로 만든 한국어 안내문(예: "오마주 각본을 만들지 못했어요…")만 통과
 *    시키고, 하위 레이어가 그대로 던지는 원문 에러는 걸러낸다 — 예를 들어 aiAdapters.ts의
 *    callProxy는 `Proxy error (400): {"error":{"code":400,"message":"Invalid value at
 *    'contents[0]…"` 같은 영어 JSON 원문을 그대로 던진다. 그런 문구가 화면에 뜨면 사용자는
 *    무엇을 해야 할지 알 수 없다. 짧고(200자 이하) 한글이 섞인 문장만 "우리가 의도적으로 쓴
 *    안내문"으로 간주한다.
 */
export function presentableErrorMessage(e: unknown, fallback: string): string {
  const msg = e instanceof Error ? e.message.trim() : ''
  const presentable = msg.length > 0 && msg.length <= 200 && /[가-힣]/.test(msg)
  return presentable ? msg : fallback
}
