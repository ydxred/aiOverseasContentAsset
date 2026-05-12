from __future__ import annotations

from typing import Any

from .artifact_writer import ArtifactWriter
from .content_positioning import normalize_analysis_positioning
from .db import Database
from .llm_client import LLMClient


def analyze_content(meta: dict[str, Any], transcript_clean: dict[str, Any], writer: ArtifactWriter, llm: LLMClient, db: Database) -> dict[str, Any]:
    response = llm.generate("analysis", {"meta": meta, "transcript": transcript_clean})
    analysis = response.content
    if not isinstance(analysis, dict):
        raise RuntimeError("analysis response must be JSON-compatible")
    analysis = normalize_analysis_positioning(analysis, source_type=str(meta.get("source_type") or ""))
    path = writer.write_json("analysis.json", analysis)
    db.record_model_run(writer.output_dir.name, "analysis", response.provider, response.model, "succeeded")
    db.record_artifact(writer.output_dir.name, "analysis", str(path))
    return analysis

