import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env", override=True)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]


class Settings:
    bifrost_url: str = os.getenv("BIFROST_URL", "http://127.0.0.1:8080")
    bifrost_model: str = os.getenv("BIFROST_MODEL", "gemini/gemini-3.1-flash-lite")
    bifrost_vk: str = os.getenv("BIFROST_VK", "")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    freshgate_threshold: int = max(0, min(100, _int_env("FRESHGATE_THRESHOLD", 60)))
    freshgate_policy: str = (
        os.getenv("FRESHGATE_POLICY", "correct").strip().lower() or "correct"
    )
    openai_stt_model: str = os.getenv("OPENAI_STT_MODEL", "openai/whisper-1")
    openai_tts_model: str = os.getenv("OPENAI_TTS_MODEL", "openai/tts-1")
    openai_tts_voice: str = os.getenv("OPENAI_TTS_VOICE", "alloy")
    cors_origins: list[str] = _cors_origins()
    cors_origin_regex: str | None = os.getenv(
        "CORS_ORIGIN_REGEX",
        r"https://.*\.vercel\.app",
    ) or None
    frontend_dir: Path = ROOT_DIR / "frontend"


settings = Settings()
