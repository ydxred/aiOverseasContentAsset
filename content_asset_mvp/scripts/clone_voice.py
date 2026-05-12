"""Doubao 声音复刻 (Voice Replication / ICL 2.0) — upload reference audio
and register a speaker_id for use with the V3 TTS endpoint.

Usage:
    python -m scripts.clone_voice <wav_path> --speaker-id S_oca_main_v1

Endpoint reference: Volcengine "大模型语音合成" → 声音复刻 2.0
    POST https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload

Headers:
    Authorization: Bearer;<access_token>      (semicolon syntax — Volcengine quirk)
    Resource-Id: volc.megatts.voiceclone
    Content-Type: application/json

Body:
    {
      "appid": "<VOLC_APPID>",
      "speaker_id": "S_<custom>",
      "audios": [{"audio_bytes": "<base64>", "audio_format": "wav"}],
      "source": 2,
      "language": 0,
      "model_type": 1
    }

After successful upload + training, the same speaker_id is callable on the
V3 TTS endpoint with X-Api-Resource-Id: seed-icl-2.0 (the route already
implemented in app/tts_engine.py for ``S_*`` voice IDs)."""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


UPLOAD_URL = "https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload"
STATUS_URL = "https://openspeech.bytedance.com/api/v1/mega_tts/status"


def _post_json(url: str, body: dict, headers: dict, *, timeout: int = 120) -> dict:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=payload, method="POST", headers={**headers, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code}: {body or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"network error: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response: {raw[:300]}") from exc


def upload_voice(audio_path: Path, speaker_id: str, appid: str, access_token: str) -> dict:
    """Upload a reference audio under 声音复刻 2.0 (ICL V2).
    Headers and body shape per Volcengine docs/6561/1305191:
    - Resource-Id: seed-icl-2.0  (ICL 2.0 — NOT volc.megatts.voiceclone which is 1.0)
    - model_type: 4              (ICL V2 — NOT 1 which is 1.0)
    """
    audio_bytes = audio_path.read_bytes()
    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    body = {
        "appid": appid,
        "speaker_id": speaker_id,
        "audios": [{"audio_bytes": audio_b64, "audio_format": audio_path.suffix.lstrip(".") or "wav"}],
        "source": 2,
        "language": 0,
        "model_type": 4,
    }
    headers = {
        "Authorization": f"Bearer;{access_token}",
        "Resource-Id": "seed-icl-2.0",
    }
    return _post_json(UPLOAD_URL, body, headers)


def check_status(speaker_id: str, appid: str, access_token: str) -> dict:
    body = {"appid": appid, "speaker_id": speaker_id}
    headers = {
        "Authorization": f"Bearer;{access_token}",
        "Resource-Id": "seed-icl-2.0",
    }
    return _post_json(STATUS_URL, body, headers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", help="Path to reference audio (wav/mp3, 5-30s, mono preferred)")
    parser.add_argument("--speaker-id", default="S_oca_main_v1", help="Custom speaker ID (must start with S_)")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Max seconds to poll status after upload")
    args = parser.parse_args()

    appid = os.getenv("VOLC_APPID")
    access_token = os.getenv("VOLC_ACCESS_TOKEN")
    if not appid or not access_token:
        print("ERROR: VOLC_APPID / VOLC_ACCESS_TOKEN missing in env", file=sys.stderr)
        return 1
    if not args.speaker_id.startswith("S_"):
        print("ERROR: --speaker-id must start with 'S_' (downstream router needs the prefix)", file=sys.stderr)
        return 1

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"ERROR: {audio_path} not found", file=sys.stderr)
        return 1

    print(f"[clone] uploading {audio_path} ({audio_path.stat().st_size} bytes) as speaker_id={args.speaker_id}")
    upload_resp = upload_voice(audio_path, args.speaker_id, appid, access_token)
    print(f"[clone] upload response: {json.dumps(upload_resp, ensure_ascii=False)[:500]}")

    base_resp = upload_resp.get("BaseResp") or upload_resp.get("base_resp") or {}
    status_code = base_resp.get("StatusCode") if base_resp else upload_resp.get("status_code")
    if status_code not in (0, None):
        msg = base_resp.get("StatusMessage") or upload_resp.get("status_message") or "<no message>"
        print(f"[clone] upload reported error code={status_code} msg={msg}", file=sys.stderr)
        return 2

    deadline = time.time() + args.poll_seconds
    print(f"[clone] polling status (up to {args.poll_seconds}s)...")
    last = None
    while time.time() < deadline:
        try:
            resp = check_status(args.speaker_id, appid, access_token)
        except RuntimeError as exc:
            print(f"[clone] status error: {exc}")
            time.sleep(3)
            continue
        last = resp
        state = resp.get("status") or resp.get("Status")
        msg = resp.get("status_message") or resp.get("StatusMessage")
        print(f"[clone]   state={state} msg={msg}")
        if state in (1, "Success", "succeeded"):
            break
        if state in (3, "Failed", "failed"):
            print(f"[clone] training failed: {json.dumps(resp, ensure_ascii=False)[:300]}", file=sys.stderr)
            return 3
        time.sleep(3)
    print(f"[clone] final status: {json.dumps(last, ensure_ascii=False)[:300]}")
    print()
    print(f"[done] speaker_id ready: {args.speaker_id}")
    print(f"[next] export VOLC_TTS_VOICE={args.speaker_id} && --render-video to use this voice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
