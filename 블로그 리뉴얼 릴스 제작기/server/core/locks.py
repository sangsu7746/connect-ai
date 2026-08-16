"""프로세스 공용 락. scenes_json은 이미지 잡·텍스트 편집·렌더가 함께 쓰므로
fresh-read→병합→쓰기 구간을 직렬화한다 (M3 최종 리뷰 파킹 항목 마감).
단일 프로세스(uvicorn 1 워커 + 스레드 잡) 전제 — 느린 I/O(SD·Gemini·ffmpeg)는
락 밖에서 수행하고, ms 단위의 병합 구간만 락 안에 둔다."""
import threading

scenes_lock = threading.Lock()
