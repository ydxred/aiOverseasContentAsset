from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - keeps mock mode runnable before dependencies are installed.
    def load_dotenv(*_args: object, **_kwargs: object) -> bool:
        return False


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    workspace_dir: Path
    output_dir: Path
    log_dir: Path
    database_url: str | None
    provider: str
    model: str
    mock: bool
    openai_api_key: str | None
    anthropic_api_key: str | None
    google_api_key: str | None
    youtube_api_key: str | None
    deepseek_api_key: str | None
    qwen_api_key: str | None
    ark_api_key: str | None
    ark_model: str | None
    volc_appid: str | None
    volc_access_token: str | None
    volc_secret_key: str | None

    def ensure_directories(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def load_settings(
    *,
    output_dir: str | None = None,
    workspace_dir: str | None = None,
    force_mock: bool = False,
) -> Settings:
    root_dir = Path(__file__).resolve().parents[1]
    load_dotenv(root_dir / ".env")

    mock = force_mock or _as_bool(os.getenv("CONTENT_ASSET_MOCK"), default=False)
    settings = Settings(
        root_dir=root_dir,
        workspace_dir=(root_dir / (workspace_dir or os.getenv("CONTENT_ASSET_WORKSPACE_DIR") or "workspace")).resolve(),
        output_dir=(root_dir / (output_dir or os.getenv("CONTENT_ASSET_OUTPUT_DIR") or "output")).resolve(),
        log_dir=(root_dir / (os.getenv("CONTENT_ASSET_LOG_DIR") or "logs")).resolve(),
        database_url=os.getenv("DATABASE_URL") or None,
        provider=os.getenv("CONTENT_ASSET_PROVIDER") or ("mock" if mock else "openai"),
        model=os.getenv("CONTENT_ASSET_MODEL") or ("mock-content-asset-v1" if mock else "gpt-5.4"),
        mock=mock,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        google_api_key=os.getenv("GOOGLE_API_KEY") or None,
        youtube_api_key=os.getenv("YOUTUBE_API_KEY") or None,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
        qwen_api_key=os.getenv("QWEN_API_KEY") or None,
        ark_api_key=os.getenv("ARK_API_KEY") or None,
        ark_model=os.getenv("ARK_MODEL") or None,
        volc_appid=os.getenv("VOLC_APPID") or None,
        volc_access_token=os.getenv("VOLC_ACCESS_TOKEN") or None,
        volc_secret_key=os.getenv("VOLC_SECRET_KEY") or None,
    )
    settings.ensure_directories()
    return settings

