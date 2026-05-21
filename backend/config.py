"""应用配置模块"""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"

load_dotenv(PROJECT_ROOT / ".env")


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


class Settings:
    """应用设置"""

    APP_TITLE: str = "LocalLife Agent Mock API"
    APP_VERSION: str = "0.1.0"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    RELOAD: bool = True

    # DeepSeek 配置（从环境变量读取）
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    DEEPSEEK_TIMEOUT_SECONDS: float = _env_float("DEEPSEEK_TIMEOUT_SECONDS", 90.0)

    @property
    def llm_available(self) -> bool:
        return bool(self.DEEPSEEK_API_KEY)


settings = Settings()
