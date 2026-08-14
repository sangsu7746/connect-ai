import os, pathlib
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

class Settings:
    naver_client_id = os.getenv("NAVER_CLIENT_ID", "")
    naver_client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    google_cse_key = os.getenv("GOOGLE_CSE_KEY", "")
    google_cse_id = os.getenv("GOOGLE_CSE_ID", "")
    server_port = int(os.getenv("SERVER_PORT", "8792"))

settings = Settings()
