from __future__ import annotations

from .artifact_writer import ArtifactWriter


def create_distribution_record(content_id: str, writer: ArtifactWriter) -> dict[str, object]:
    result = {
        "content_id": content_id,
        "status": "skipped",
        "platform": "draft",
        "output_path": str(writer.output_dir),
        "issues": ["MVP v1 only creates an offline review package and does not publish automatically."],
    }
    writer.write_json("distribution.json", result)
    return result

