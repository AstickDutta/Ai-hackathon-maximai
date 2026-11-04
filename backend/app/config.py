import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


class Settings:
    bifrost_url: str = os.getenv("BIFROST_URL", "http://127.0.0.1:8080")
    bifrost_model: str = os.getenv("BIFROST_MODEL", "gemini/gemini-3.1-flash-lite")
    bifrost_vk: str = os.getenv("BIFROST_VK", "")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    frontend_dir: Path = ROOT_DIR / "frontend"


settings = Settings()
