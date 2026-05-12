from __future__ import annotations

import os
import subprocess


def get_github_token() -> str | None:
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    token = result.stdout.strip()
    return token or None


def github_auth_status() -> str:
    if os.getenv("GITHUB_TOKEN"):
        return "GITHUB_TOKEN 已配置"
    if get_github_token():
        return "GitHub CLI 已登录"
    return "未配置"
