from __future__ import annotations

from typing import Any

from .artifact_writer import ArtifactWriter
from .db import Database
from .llm_client import LLMClient


def check_risk(meta: dict[str, Any], analysis: dict[str, Any], writer: ArtifactWriter, llm: LLMClient, db: Database) -> dict[str, Any]:
    response = llm.generate("risk", {"meta": meta, "analysis": analysis})
    risk_report = response.content
    if not isinstance(risk_report, dict):
        raise RuntimeError("risk response must be JSON-compatible")
    path = writer.write_json("risk_report.json", risk_report)
    db.record_model_run(writer.output_dir.name, "risk", response.provider, response.model, "succeeded")
    db.record_artifact(writer.output_dir.name, "risk_report", str(path))
    return risk_report

