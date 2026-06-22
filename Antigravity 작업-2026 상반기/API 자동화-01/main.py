"""
API Key 자동 발급 및 설정 자동화 프로그램
진입점 (CLI)

사용법:
  python main.py --service anthropic
  python main.py --service gemini
  python main.py --service openai
  python main.py --list-keys
  python main.py --test-vault
  python main.py --test-browser
"""

import argparse
import asyncio
import io
import sys
from loguru import logger

# Windows CP949 환경에서 UTF-8 출력을 위한 stdout 래핑
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    except AttributeError:
        pass  # GUI 모드에서는 buffer 없음

# 로그 설정 (API Key 절대 출력 안 함)
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    "logs/app_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    encoding="utf-8",
)

SUPPORTED_SERVICES = {
    "anthropic": ("plugins.anthropic_plugin", "AnthropicPlugin"),
    "gemini":    ("plugins.gemini_plugin",    "GeminiPlugin"),
    "openai":    ("plugins.openai_plugin",    "OpenAIPlugin"),
    "github":    ("plugins.github_plugin",    "GitHubPlugin"),
    "aws":       ("plugins.aws_plugin",       "AWSPlugin"),
    "youtube":   ("plugins.youtube_plugin",   "YouTubePlugin"),
}


async def run_service(service_name: str):
    """특정 서비스의 API Key를 자동 발급"""
    if service_name not in SUPPORTED_SERVICES:
        logger.error(f"지원하지 않는 서비스: {service_name}")
        logger.info(f"지원 서비스 목록: {', '.join(SUPPORTED_SERVICES.keys())}")
        return False

    module_path, class_name = SUPPORTED_SERVICES[service_name]

    try:
        import importlib
        module = importlib.import_module(module_path)
        plugin_class = getattr(module, class_name)
    except ImportError as e:
        logger.error(f"플러그인 로드 실패 ({service_name}): {e}")
        return False

    logger.info(f"🚀 [{service_name.upper()}] API Key 자동 발급 시작")

    plugin = plugin_class()
    result = await plugin.run()

    if result.success:
        logger.success(f"✅ [{service_name.upper()}] API Key 발급 완료!")
        logger.info(f"   키 이름: {result.key_name}")
        logger.info(f"   저장 위치: Windows Credential Manager (암호화)")
        logger.info(f"   .env 업데이트: {result.env_updated}")
    else:
        logger.error(f"❌ [{service_name.upper()}] API Key 발급 실패: {result.error}")

    return result.success


def list_keys():
    """저장된 API Key 목록 조회"""
    from security.key_vault import KeyVault
    vault = KeyVault()
    keys = vault.list_keys()

    if not keys:
        logger.info("저장된 API Key가 없습니다.")
        return

    logger.info("📋 저장된 API Key 목록:")
    for service, key_names in keys.items():
        for name in key_names:
            logger.info(f"   [{service.upper()}] {name}")


def test_vault():
    """키 저장소 기능 테스트"""
    from security.key_vault import KeyVault
    logger.info("🔐 키 저장소 테스트 시작...")

    vault = KeyVault()

    test_value = "test-api-key-12345"
    vault.store_key("test_service", "test_key", test_value)
    logger.info("   저장: ✅")

    retrieved = vault.retrieve_key("test_service", "test_key")
    assert retrieved == test_value, "키 복원 실패!"
    logger.info("   복원: ✅")

    vault.delete_key("test_service", "test_key")
    assert vault.retrieve_key("test_service", "test_key") is None
    logger.info("   삭제: ✅")

    logger.success("🔐 키 저장소 테스트 통과!")


async def test_browser():
    """브라우저 엔진 기본 동작 테스트"""
    from core.browser_engine import BrowserEngine
    logger.info("🌐 브라우저 엔진 테스트 시작...")

    engine = BrowserEngine(headless=False)
    await engine.start()

    try:
        page = await engine.new_page()
        await page.goto("https://example.com")
        title = await page.title()
        logger.info(f"   페이지 제목: {title}")
        logger.success("🌐 브라우저 엔진 테스트 통과!")
    finally:
        await engine.stop()


def main():
    parser = argparse.ArgumentParser(
        description="API Key 자동 발급 및 설정 자동화 프로그램",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python main.py --service anthropic     # Anthropic Claude API Key 발급
  python main.py --service gemini        # Google Gemini API Key 발급
  python main.py --service openai        # OpenAI API Key 발급
  python main.py --list-keys             # 저장된 키 목록 조회
  python main.py --test-vault            # 키 저장소 테스트
  python main.py --test-browser          # 브라우저 엔진 테스트
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--service", "-s",
        choices=list(SUPPORTED_SERVICES.keys()),
        help="API Key를 발급할 서비스 선택"
    )
    group.add_argument(
        "--list-keys", "-l",
        action="store_true",
        help="저장된 API Key 목록 조회"
    )
    group.add_argument(
        "--test-vault",
        action="store_true",
        help="키 저장소 암호화 기능 테스트"
    )
    group.add_argument(
        "--test-browser",
        action="store_true",
        help="브라우저 엔진 기본 동작 테스트"
    )
    group.add_argument(
        "--rotate-key",
        action="store_true",
        help="마스터 암호화 키 로테이션 (90일 권장)"
    )
    group.add_argument(
        "--gui",
        action="store_true",
        help="GUI 모드로 실행 (PyQt6)"
    )

    args = parser.parse_args()

    try:
        if args.service:
            success = asyncio.run(run_service(args.service))
            sys.exit(0 if success else 1)

        elif args.list_keys:
            list_keys()

        elif args.test_vault:
            test_vault()

        elif args.test_browser:
            asyncio.run(test_browser())

        elif args.rotate_key:
            from security.key_vault import KeyVault
            logger.info("🔄 마스터 키 로테이션 시작...")
            vault = KeyVault()
            vault.rotate_master_key()
            logger.success("✅ 마스터 키 로테이션 완료")

        elif args.gui:
            from gui.main_window import launch_gui
            launch_gui()

    except KeyboardInterrupt:
        logger.info("\n사용자가 중단했습니다.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"예기치 않은 오류: {e}")
        raise


if __name__ == "__main__":
    main()
