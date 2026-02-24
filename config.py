import os
import logging
from dataclasses import dataclass, field
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


def _require_env(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Переменная окружения {key} не задана. Проверьте .env файл.")
    return val


@dataclass(frozen=True)
class Config:
    # Telegram
    bot_token: str = field(default_factory=lambda: _require_env("TOKEN"))
    chat_id: str = field(default_factory=lambda: _require_env("CHAT_ID"))
    channel_id: str = field(default_factory=lambda: os.getenv("CHANNEL_ID", ""))

    # Database
    db_url: str = field(default_factory=lambda: _require_env("DB_URL"))

    # OpenAI
    openai_api_key: str = field(default_factory=lambda: os.getenv("CHATGPT_API_KEY", ""))

    # TMDB
    tmdb_api_key: str = field(default_factory=lambda: os.getenv("TMDB_API_KEY", ""))

    # Redis
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://redis:6379"))

    @property
    def full_chat_id(self) -> str:
        """Chat ID в формате для Telegram API (-100...)."""
        cid = self.chat_id
        if not cid.startswith("-100"):
            cid = f"-100{cid}"
        return cid


def setup_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


cfg = Config()
