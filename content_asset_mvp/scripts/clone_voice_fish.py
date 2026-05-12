"""Fish Audio voice clone — upload reference audio and register a model_id.

Fish Audio API (https://api.fish.audio) is dramatically simpler than Volcengine:
    POST /model (multipart/form-data) → returns _id (use as reference_id in TTS calls)

Usage:
    python -m scripts.clone_voice_fish workspace/voice_ref/ref.wav --title "我的声音"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests


def upload_voice(audio_path: Path, title: str, description: str, api_key: str,
                 reference_text: str | None = None, train_mode: str = "fast") -> dict:
    """Upload reference audio to Fish Audio to create a voice model.

    train_mode: 'fast' (~30s, lower quality) or 'high_quality' (~5min, better fidelity)
    """
    with audio_path.open("rb") as f:
        files = {"voices": (audio_path.name, f, "audio/wav")}
        data: dict[str, str] = {
            "title": title,
            "description": description,
            "type": "tts",
            "train_mode": train_mode,
            "visibility": "private",
            "enhance_audio_quality": "true",
        }
        if reference_text:
            data["texts"] = reference_text

        resp = requests.post(
            "https://api.fish.audio/model",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files, data=data, timeout=300,
        )
    return resp.json() if resp.ok else {"_error": resp.status_code, "_body": resp.text[:500]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", help="Reference audio path (wav/mp3, 10-30s)")
    parser.add_argument("--title", default="海外AI信号-主声", help="Voice display name")
    parser.add_argument("--description", default="海外 AI 商业机会 + 工具解读叙事女声", help="Description")
    parser.add_argument("--reference-text", help="Transcript of the reference audio (improves clone quality)")
    parser.add_argument("--train-mode", choices=["fast", "high_quality"], default="fast")
    args = parser.parse_args()

    api_key = os.getenv("FISH_API_KEY")
    if not api_key:
        print("ERROR: FISH_API_KEY missing in env", file=sys.stderr)
        return 1

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"ERROR: {audio_path} not found", file=sys.stderr)
        return 1

    print(f"[fish-clone] uploading {audio_path} ({audio_path.stat().st_size} bytes), train_mode={args.train_mode}")
    resp = upload_voice(audio_path, args.title, args.description, api_key,
                        reference_text=args.reference_text, train_mode=args.train_mode)

    if "_error" in resp:
        print(f"[fish-clone] FAILED status={resp['_error']}: {resp['_body']}", file=sys.stderr)
        return 2

    model_id = resp.get("_id") or resp.get("id")
    print(f"[fish-clone] full response:\n{json.dumps(resp, ensure_ascii=False, indent=2)[:600]}")
    if not model_id:
        print("[fish-clone] no _id in response", file=sys.stderr)
        return 3

    print()
    print(f"[done] model_id (reference_id): {model_id}")
    print(f"[next] set FISH_MODEL_ID={model_id} in .env, then --render-video to use this voice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
