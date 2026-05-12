from __future__ import annotations

from .artifact_writer import ArtifactWriter


def create_feedback_template(content_id: str, writer: ArtifactWriter) -> dict[str, object]:
    result = {
        "content_id": content_id,
        "status": "template_created",
        "feedback_type": "manual_review",
        "fields": [
            "is_topic_useful",
            "is_script_usable",
            "main_issues",
            "risk_judgment_accuracy",
            "style_fit",
            "post_publish_performance",
        ],
    }
    writer.write_json("feedback_template.json", result)
    return result

