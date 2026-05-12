from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe a video or audio file.")
    parser.add_argument("input_path")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--provider", choices=["auto", "openai", "local"], default="auto")
    parser.add_argument("--model", default="small", help="Local faster-whisper model name.")
    parser.add_argument("--openai-model", default="whisper-1")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    args = parser.parse_args()

    load_dotenv()
    provider = _resolve_provider(args.provider)
    if provider == "openai":
        return _transcribe_openai(args)
    return _transcribe_local(args)


def _transcribe_local(args: argparse.Namespace) -> int:
    from faster_whisper import WhisperModel

    device, compute_type = _resolve_device(args.device)
    print(f"Using faster-whisper model={args.model} device={device} compute_type={compute_type}")
    model = WhisperModel(args.model, device=device, compute_type=compute_type)
    segments, info = model.transcribe(args.input_path, language=args.language, vad_filter=True, beam_size=5)

    items: list[dict[str, object]] = []
    for segment in segments:
        item = {
            "start": round(segment.start, 2),
            "end": round(segment.end, 2),
            "text": segment.text.strip(),
        }
        items.append(item)
        print(f"{item['start']:.2f}-{item['end']:.2f} {item['text']}")

    Path(args.output_json).write_text(
        json.dumps(
            {
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
                "segments": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def _transcribe_openai(args: argparse.Namespace) -> int:
    from openai import OpenAI

    print(f"Using OpenAI transcription model={args.openai_model}")
    client = OpenAI()
    upload_path = _prepare_openai_audio(Path(args.input_path))
    try:
        result = _request_openai_transcription(client, upload_path, args)
    finally:
        if upload_path != Path(args.input_path) and upload_path.exists():
            upload_path.unlink()

    segments = _openai_segments(result)
    for item in segments:
        print(f"{item['start']:.2f}-{item['end']:.2f} {item['text']}")
    Path(args.output_json).write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": args.openai_model,
                "language": args.language,
                "segments": segments,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def _request_openai_transcription(client: object, upload_path: Path, args: argparse.Namespace) -> object:
    with upload_path.open("rb") as audio_file:
        try:
            return client.audio.transcriptions.create(
                model=args.openai_model,
                file=audio_file,
                language=args.language,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        except TypeError:
            audio_file.seek(0)
            return client.audio.transcriptions.create(
                model=args.openai_model,
                file=audio_file,
                language=args.language,
                response_format="verbose_json",
            )


def _prepare_openai_audio(input_path: Path) -> Path:
    max_upload_bytes = 24 * 1024 * 1024
    if input_path.stat().st_size <= max_upload_bytes and input_path.suffix.lower() in {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}:
        return input_path
    target = Path(tempfile.gettempdir()) / f"{input_path.stem}_openai_asr.mp3"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "48k",
        str(target),
    ]
    subprocess.run(command, check=True)
    print(f"Prepared compressed audio for API upload: {target} ({target.stat().st_size} bytes)")
    return target


def _resolve_provider(requested: str) -> str:
    if requested == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not configured. Add it to the environment or .env.")
        return "openai"
    if requested == "local":
        return "local"
    return "openai" if os.getenv("OPENAI_API_KEY") else "local"


def _openai_segments(result: object) -> list[dict[str, object]]:
    raw_segments = getattr(result, "segments", None)
    if raw_segments is None and isinstance(result, dict):
        raw_segments = result.get("segments")
    items: list[dict[str, object]] = []
    if raw_segments:
        for segment in raw_segments:
            start = getattr(segment, "start", None) if not isinstance(segment, dict) else segment.get("start")
            end = getattr(segment, "end", None) if not isinstance(segment, dict) else segment.get("end")
            text = getattr(segment, "text", None) if not isinstance(segment, dict) else segment.get("text")
            items.append(
                {
                    "start": round(float(start or 0), 2),
                    "end": round(float(end or 0), 2),
                    "text": str(text or "").strip(),
                }
            )
    if items:
        return items
    text = getattr(result, "text", None) if not isinstance(result, dict) else result.get("text")
    return [{"start": 0.0, "end": 0.0, "text": str(text or "").strip()}]


def _resolve_device(requested: str) -> tuple[str, str]:
    if requested == "cpu":
        return "cpu", "int8"
    if requested == "cuda":
        return "cuda", "float16"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


if __name__ == "__main__":
    raise SystemExit(main())
