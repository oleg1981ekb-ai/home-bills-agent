"""Configuration for Home Bills Agent (Anapa Water Agent v1.1).

Loads from environment variables with .env.example defaults.
Supports DRY_RUN and AUTO_SEND flags.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """Application settings loaded from env / .env.example."""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_USER_ID: str = ""

    # Vodokanal provider
    VODOKAN_LOGIN: str = ""
    VODOKAN_PASSWORD: str = ""

    # Account
    ACCOUNT_ID: str = "acc1"
    COUNTER_CODE: str = ""
    ID_DB: int = 1

    # Anthropic vision model (approved)
    ANTHROPIC_API_KEY: str = ""
    VISION_MODEL: str = "claude-sonnet-4-5"

    # OpenRouter vision (OpenAI-compatible; free models available)
    OPENROUTER_API_KEY: str = ""
    VISION_PROVIDER: str = "anthropic"  # anthropic | openrouter

    # Scheduler
    TZ: str = "Europe/Moscow"
    WINDOW_START: int = 1
    WINDOW_END: int = 25
    REMINDER_START_DAY: int = 18
    REMINDER_TIME: str = "09:00"
    EVENING_TIME: str = "19:00"
    EVENING_FROM_DAY: int = 22

    # Anomaly thresholds
    ANOMALY_FACTOR: float = 2.0
    CONFIDENCE_MIN: float = 0.9

    # Dry run
    DRY_RUN: bool = False

    # Auto send
    AUTO_SEND: bool = False

    # Whitelist of allowed users (TELEGRAM_USER_ID)
    WHITELISTED_USERS: list[str] = field(default_factory=list)

    # Test/utility flag: skip loading .env / .env.example (keeps unit tests hermetic)
    skip_dotenv: bool = False

    @staticmethod
    def _load_dotenv(path: Path) -> dict[str, str]:
        """Parse .env file into dict (no external deps)."""
        result = {}
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    result[k.strip()] = v.strip()
        return result

    def __post_init__(self):
        # Load defaults from .env.example, then override with real .env and env vars
        env: dict[str, str] = {}
        if not self.skip_dotenv:
            project_root = Path(__file__).resolve().parents[2]
            example_path = project_root / ".env.example"
            if example_path.exists():
                env.update(self._load_dotenv(example_path))
            real_env_path = project_root / ".env"
            if real_env_path.exists():
                env.update(self._load_dotenv(real_env_path))
        env.update({k: v for k, v in os.environ.items() if v})

        self.TELEGRAM_BOT_TOKEN = env.get("TELEGRAM_BOT_TOKEN", self.TELEGRAM_BOT_TOKEN)
        self.TELEGRAM_USER_ID = env.get("TELEGRAM_USER_ID", self.TELEGRAM_USER_ID)
        self.VODOKAN_LOGIN = env.get("VODOKAN_LOGIN", self.VODOKAN_LOGIN)
        self.VODOKAN_PASSWORD = env.get("VODOKAN_PASSWORD", self.VODOKAN_PASSWORD)
        self.ACCOUNT_ID = env.get("ACCOUNT_ID", self.ACCOUNT_ID)
        self.COUNTER_CODE = env.get("COUNTER_CODE", self.COUNTER_CODE)
        self.ID_DB = int(env.get("ID_DB", str(self.ID_DB)))
        self.ANTHROPIC_API_KEY = env.get("ANTHROPIC_API_KEY", self.ANTHROPIC_API_KEY)
        self.VISION_MODEL = env.get("VISION_MODEL", self.VISION_MODEL)
        self.OPENROUTER_API_KEY = env.get("OPENROUTER_API_KEY", self.OPENROUTER_API_KEY)
        self.VISION_PROVIDER = env.get("VISION_PROVIDER", self.VISION_PROVIDER)
        self.TZ = env.get("TZ", self.TZ)
        self.WINDOW_START = int(env.get("WINDOW_START", str(self.WINDOW_START)))
        self.WINDOW_END = int(env.get("WINDOW_END", str(self.WINDOW_END)))
        self.REMINDER_START_DAY = int(env.get("REMINDER_START_DAY", str(self.REMINDER_START_DAY)))
        self.REMINDER_TIME = env.get("REMINDER_TIME", self.REMINDER_TIME)
        self.EVENING_TIME = env.get("EVENING_TIME", self.EVENING_TIME)
        self.EVENING_FROM_DAY = int(env.get("EVENING_FROM_DAY", str(self.EVENING_FROM_DAY)))
        self.ANOMALY_FACTOR = float(env.get("ANOMALY_FACTOR", str(self.ANOMALY_FACTOR)))
        self.CONFIDENCE_MIN = float(env.get("CONFIDENCE_MIN", str(self.CONFIDENCE_MIN)))
        self.DRY_RUN = env.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
        self.AUTO_SEND = env.get("AUTO_SEND", "false").lower() in ("true", "1", "yes")
        whitelist = env.get("WHITELISTED_USERS", "")
        self.WHITELISTED_USERS = [u.strip() for u in whitelist.split(",") if u.strip()]

    def is_user_allowed(self, user_id: str) -> bool:
        """Check if user is in whitelist or is the main TELEGRAM_USER_ID."""
        if self.TELEGRAM_USER_ID and user_id == self.TELEGRAM_USER_ID:
            return True
        return user_id in self.WHITELISTED_USERS


settings = Settings()