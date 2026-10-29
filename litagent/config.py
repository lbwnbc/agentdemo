"""配置加载：环境变量优先，其次读取项目根目录下的 .env。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path=PROJECT_ROOT / ".env"):
    """极简 .env 解析，不覆盖已存在的环境变量。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-5.3-flash"
    temperature: float = 0.2
    timeout: float = 60.0
    max_retries: int = 3

    @property
    def chat_url(self):
        return "{}/chat/completions".format(self.base_url.rstrip("/"))


def load_settings():
    _load_dotenv()
    api_key = os.environ.get("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 ZHIPU_API_KEY，请复制 .env.example 为 .env 并填入密钥")
    return Settings(
        api_key=api_key,
        base_url=os.environ.get("ZHIPU_BASE_URL", Settings.base_url),
        model=os.environ.get("ZHIPU_MODEL", Settings.model),
        temperature=float(os.environ.get("ZHIPU_TEMPERATURE", Settings.temperature)),
        timeout=float(os.environ.get("ZHIPU_TIMEOUT", Settings.timeout)),
        max_retries=int(os.environ.get("ZHIPU_MAX_RETRIES", Settings.max_retries)),
    )
