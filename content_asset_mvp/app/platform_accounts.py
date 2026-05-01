from __future__ import annotations

from pathlib import Path
from typing import Any

from .platform_publish import PLATFORMS

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


ACCOUNT_FIELDS = {
    "platform",
    "platform_name",
    "account_id",
    "display_name",
    "enabled",
    "auto_publish_enabled",
    "login_method",
    "publish_url",
    "notes",
    "default_priority",
}
EDITABLE_FIELDS = {
    "account_id",
    "display_name",
    "enabled",
    "auto_publish_enabled",
    "login_method",
    "publish_url",
    "notes",
    "default_priority",
}


def default_platform_accounts() -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    for index, (platform, config) in enumerate(PLATFORMS.items(), start=1):
        accounts.append(
            {
                "platform": platform,
                "platform_name": config["platform_name"],
                "account_id": f"{platform}_main",
                "display_name": f"{config['platform_name']}主账号",
                "enabled": True,
                "auto_publish_enabled": False,
                "login_method": "manual_browser",
                "publish_url": _default_publish_url(platform),
                "notes": "模板账号，仅保存非敏感发布配置；不要在这里填写敏感凭据或平台授权值。",
                "default_priority": index,
            }
        )
    return accounts


def init_platform_accounts(path: Path, *, overwrite: bool = False) -> list[dict[str, Any]]:
    if path.exists() and not overwrite:
        return load_platform_accounts(path)
    accounts = default_platform_accounts()
    save_platform_accounts(path, accounts)
    return accounts


def load_platform_accounts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return default_platform_accounts()
    if yaml is None:
        raise RuntimeError("PyYAML is required to read platform account configuration")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_accounts = data.get("accounts") if isinstance(data, dict) else []
    by_platform: dict[str, dict[str, Any]] = {}
    if isinstance(raw_accounts, list):
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            platform = str(item.get("platform") or "")
            if platform in PLATFORMS:
                by_platform[platform] = normalize_platform_account(item)
    accounts = []
    for default in default_platform_accounts():
        platform = default["platform"]
        merged = dict(default)
        merged.update(by_platform.get(platform, {}))
        merged["platform"] = platform
        merged["platform_name"] = PLATFORMS[platform]["platform_name"]
        accounts.append(normalize_platform_account(merged))
    return accounts


def save_platform_accounts(path: Path, accounts: list[dict[str, Any]]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to write platform account configuration")
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [normalize_platform_account(account) for account in accounts if account.get("platform") in PLATFORMS]
    payload = {
        "schema_version": 1,
        "warning": "非敏感账号配置模板；不要保存敏感凭据、平台授权值或接口密钥。",
        "accounts": normalized,
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def update_platform_account(path: Path, platform: str, updates: dict[str, Any]) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    accounts = load_platform_accounts(path)
    for account in accounts:
        if account["platform"] != platform:
            continue
        for key, value in updates.items():
            if key in EDITABLE_FIELDS:
                account[key] = value
        account["platform_name"] = PLATFORMS[platform]["platform_name"]
        normalized = normalize_platform_account(account)
        account.clear()
        account.update(normalized)
        save_platform_accounts(path, accounts)
        return account
    raise ValueError(f"Platform account not found: {platform}")


def account_by_platform(accounts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(account.get("platform")): account for account in accounts if account.get("platform") in PLATFORMS}


def normalize_platform_account(account: dict[str, Any]) -> dict[str, Any]:
    platform = str(account.get("platform") or "")
    config = PLATFORMS.get(platform, {})
    normalized: dict[str, Any] = {
        "platform": platform,
        "platform_name": str(account.get("platform_name") or config.get("platform_name") or platform),
        "account_id": str(account.get("account_id") or f"{platform}_main").strip(),
        "display_name": str(account.get("display_name") or config.get("platform_name") or platform).strip(),
        "enabled": _as_bool(account.get("enabled"), default=True),
        "auto_publish_enabled": _as_bool(account.get("auto_publish_enabled"), default=False),
        "login_method": str(account.get("login_method") or "manual_browser").strip(),
        "publish_url": str(account.get("publish_url") or _default_publish_url(platform)).strip(),
        "notes": str(account.get("notes") or "").strip(),
        "default_priority": _as_int(account.get("default_priority"), default=99),
    }
    return {key: normalized[key] for key in ACCOUNT_FIELDS}


def _default_publish_url(platform: str) -> str:
    return {
        "douyin": "https://creator.douyin.com/creator-micro/content/upload",
        "kuaishou": "https://cp.kuaishou.com/article/publish/video",
        "wechat_channels": "https://channels.weixin.qq.com/platform/post/create",
        "bilibili": "https://member.bilibili.com/platform/upload/video/frame",
        "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish",
    }.get(platform, "")


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
